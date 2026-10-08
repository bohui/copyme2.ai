"""Score recorded or live production extraction against synthetic place golds."""
import argparse
import asyncio
import json
from pathlib import Path
import re
import sys
import time
from uuid import uuid4
import httpx

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ''):
    sys.path.insert(0, str(ROOT))

from apps.api.codex_runtime import CodexRuntime
from apps.api.place_identity import place_identity, place_path
from apps.api.place_journey import (
    MARKER_START, MARKER_END, extract_place_journeys, grounded_place_journeys,
    reuse_known_place, validate_place_journey,
)

DATASET = ROOT / 'tests/evaluation/place_identity_cases.json'


def load_cases(path=DATASET):
    data = json.loads(Path(path).read_text())
    cases = [{**data['case_defaults'], **case} for case in data['cases']]
    if not cases or len({case['id'] for case in cases}) != len(cases):
        raise ValueError('Place evaluation needs nonempty, distinct case IDs')
    return data['dataset_version'], cases


def score_response(case, response):
    """Check the actual model markers, then the production identity seam."""
    raw = re.findall(re.escape(MARKER_START) + r'(.*?)' + re.escape(MARKER_END), response, re.S)
    valid = response.count(MARKER_START) == response.count(MARKER_END) == len(raw)
    for item in raw:
        try:
            valid = valid and validate_place_journey(json.loads(item)) is not None
        except (ValueError, TypeError):
            valid = False
    _, parsed = extract_place_journeys(response)
    accepted = grounded_place_journeys(parsed, case['text'])
    identities = [place_identity(place) for place in accepted]
    parsed_identities = [place_identity(place) for place in parsed]
    expected = []
    for place in case['expected_places']:
        paths = case.get('hierarchy_alternatives', {}).get(place['place'], [])
        expected.append({place_identity(place), *(place_identity({**place, 'hierarchy': path}) for path in paths)})
    unmatched = list(expected)
    for identity in identities:
        match = next((choices for choices in unmatched if identity in choices), None)
        if match is not None:
            unmatched.remove(match)
        else:
            break
    matches_expected = not unmatched and len(identities) == len(expected)
    current = case.get('place_journey')
    retained = True
    if case.get('reuse_current_coordinates'):
        retained = bool(accepted) and all(
            all(reuse_known_place(current, place).get(field) == current.get(field)
                for field in ('latitude', 'longitude')) for place in accepted)
    known = [*(case.get('profile', {}).get('memory_places') or []), current]
    independent = True
    for place in accepted:
        child_path = place_path(place, normalized=True)
        for parent in filter(None, known):
            parent_path = place_path(parent, normalized=True)
            if (len(parent_path) < len(child_path) and child_path[:len(parent_path)] == parent_path
                    and parent.get('latitude') is not None
                    and place.get('latitude') == parent.get('latitude')
                    and place.get('longitude') == parent.get('longitude')):
                independent = False
    checks = {
        'valid_place_markers': valid,
        'grounded_in_current_message': all(grounded_place_journeys([place], case['text']) for place in parsed),
        'expected_geographic_identities': matches_expected,
        'unique_geographic_identities': len(raw) == len(parsed_identities) == len(set(parsed_identities)),
        'known_coordinates_retained': retained,
        'child_coordinates_independent': independent,
    }
    return {'case_id': case['id'], 'passed': all(checks.values()), 'checks': checks,
            'accepted_places': accepted}


async def evaluate(args):
    version, cases = load_cases(args.dataset)
    if args.case_id:
        selected = set(args.case_id)
        if selected - {case['id'] for case in cases}:
            raise ValueError('Unknown place evaluation case ID')
        cases = [case for case in cases if case['id'] in selected]
    runtime = None
    if args.live:
        from dotenv import load_dotenv
        load_dotenv(ROOT / '.env', override=False)
        if not args.worker_url:
            raise ValueError('--live requires an explicit --worker-url')
        runtime = CodexRuntime(worker_url=args.worker_url, model=args.model,
                               task_publisher_enabled=False)
        if not runtime.worker_secret:
            raise ValueError('MEMORY_SPARK_CODEX_WORKER_SECRET must be configured')
    results = []
    for case in cases:
        started = time.monotonic()
        response = case['recorded_response']
        try:
            if runtime:
                async with asyncio.timeout(args.timeout):
                    response = await runtime._workspace_extraction(
                        user_id=str(uuid4()), memories=case['memories'], profile=case['profile'],
                        place_journey=case.get('place_journey'), family_enabled=False,
                        family_context=None, project_id=None, text=case['text'],
                        language=case['language'], canonical_events=True)
            result = {**score_response(case, response), 'response': response}
        except (RuntimeError, TimeoutError, httpx.HTTPError) as error:
            result = {'case_id': case['id'], 'passed': False, 'error_type': type(error).__name__}
        result['elapsed_seconds'] = round(time.monotonic() - started, 3)
        results.append(result)
        print(json.dumps({'case_id': case['id'], 'passed': result['passed'],
                          'elapsed_seconds': result['elapsed_seconds']}), flush=True)
    receipt = {'dataset_version': version, 'mode': 'live_model' if runtime else 'recorded_fixture',
               'configured_model': runtime.model if runtime else None,
               'worker_requests': runtime.observed_worker_requests if runtime else 0,
               'passed': all(result['passed'] for result in results), 'results': results}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=DATASET)
    parser.add_argument('--live', action='store_true', help='Run the real configured workspace extraction')
    parser.add_argument('--worker-url')
    parser.add_argument('--model', help='Optional extraction model override for comparison')
    parser.add_argument('--case-id', action='append')
    parser.add_argument('--timeout', type=float, default=60)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not 0 < args.timeout <= 120:
        parser.error('--timeout must be greater than zero and no more than 120 seconds')
    result = asyncio.run(evaluate(args))
    print(json.dumps({key: value for key, value in result.items() if key != 'results'}))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
