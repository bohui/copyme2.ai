#!/usr/bin/env python3
"""Run bounded, real provider calls for every active Memoir skill.

Synthetic isolated inputs only; no Supabase writes, user sessions, or deployment.
Receipts distinguish instruction contracts, composition phases, and native search.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx
import jsonschema

from scripts.memoir_live_skill_cases import cases, progressive_page, skill_prompt, validate_case
from apps.api.prompt_artifact import load_prompt_artifact


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def save(path, value):
    data = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    temporary = path.with_suffix(path.suffix + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as output:
        output.write(data)
    temporary.replace(path)


def provider_rejection(raw):
    """Classify a provider error without retaining its message, body or headers."""
    try:
        error = json.loads(raw).get('error', {})
        message = str(error.get('message', '')).lower()
    except (ValueError, AttributeError):
        return 'unclassified_provider_rejection'
    for field in ('tool_choice', 'web_search', 'max_tool_calls', 'include', 'reasoning'):
        if field in message:
            return field + '_rejected'
    return 'unclassified_provider_rejection'


def json_framing_kind(text):
    """Diagnose multiple documents without accepting or repairing them."""
    documents, offset = [], 0
    decoder = json.JSONDecoder()
    try:
        while offset < len(text):
            while offset < len(text) and text[offset].isspace():
                offset += 1
            if offset == len(text):
                break
            value, offset = decoder.raw_decode(text, offset)
            documents.append(value)
    except ValueError:
        return 'invalid_json_framing'
    if len(documents) > 1:
        return 'repeated_json_documents' if all(v == documents[0] for v in documents) else 'multiple_json_documents'
    return 'invalid_json_framing'


class LiveProvider:
    def __init__(self, config, receipt, directory, *, timeout, deadline, max_calls, effort):
        self.config, self.receipt, self.directory = config, receipt, directory
        self.timeout, self.deadline, self.max_calls, self.effort = timeout, deadline, max_calls, effort

    async def call(self, case_id, skill, instructions, packet, schema=None, *, search=False):
        if len(self.receipt['calls']) >= self.max_calls or time.monotonic() >= self.deadline:
            raise RuntimeError('live_call_budget_exhausted')
        model = (self.config.get('MEMORY_SPARK_MEMOIR_COMPOSER_MODEL') if skill == 'memoir-composer' else None)
        effort = (self.config.get('MEMORY_SPARK_MEMOIR_COMPOSER_REASONING_EFFORT') or 'low') if skill == 'memoir-composer' else self.effort
        if search:
            effort = 'low'
        body = {'model': model or self.config['MEMORY_SPARK_LLM_MODEL'], 'instructions': instructions,
                'input': json.dumps(packet, ensure_ascii=False), 'store': False,
                'max_output_tokens': 8192 if skill == 'memoir-composer' else 3000,
                'reasoning': {'effort': effort}}
        if schema:
            body['text'] = {'format': {'type': 'json_schema', 'name': 'skill_result', 'strict': True, 'schema': schema}}
        if search:
            body['input'] = body.pop('instructions')
            body.update(tools=[{'type': 'web_search'}], tool_choice='required',
                        include=['web_search_call.action.sources'])
        record = dict(case_id=case_id, skill=skill, requested_model=body['model'], effort=effort,
                      status='started', request_sha256=sha(json.dumps(body, sort_keys=True)),
                      provider_response_id=None, served_model=None, usage=None)
        self.receipt['calls'].append(record)
        save(self.directory / 'receipt.json', self.receipt)
        started = time.monotonic()
        try:
            timeout = min(self.timeout, self.deadline - started)
            async with asyncio.timeout(timeout):
                async with httpx.AsyncClient(follow_redirects=False, trust_env=False) as client:
                    async with client.stream('POST', self.config['MEMORY_SPARK_LLM_BASE_URL'].rstrip('/') + '/responses',
                        headers={'Authorization': 'Bearer ' + self.config['MEMORY_SPARK_LLM_API_KEY']},
                        json=body, timeout=timeout) as response:
                        record['http_status'] = response.status_code
                        if not response.is_success:
                            rejection = bytearray()
                            async for chunk in response.aiter_bytes():
                                rejection.extend(chunk)
                                if len(rejection) > 16384:
                                    break
                            record['rejection_category'] = provider_rejection(rejection[:16384])
                        response.raise_for_status()
                        raw = bytearray()
                        async for chunk in response.aiter_bytes():
                            raw.extend(chunk)
                            if len(raw) > 2 * 1024 * 1024:
                                raise ValueError('response_too_large')
                if self.config['MEMORY_SPARK_LLM_API_KEY'].encode() in raw:
                    raise ValueError('unsafe_output')
                decoded = json.loads(raw)
            if decoded.get('status') != 'completed' or not decoded.get('id'):
                raise ValueError('provider_response_not_completed')
            record.update(provider_response_id=decoded['id'], served_model=decoded.get('model'), usage=decoded.get('usage'))
            if search:
                record['native_output'] = [{'type': item.get('type'), 'status': item.get('status'),
                    'source_count': len((item.get('action') or {}).get('sources', []))}
                    for item in decoded.get('output', []) if isinstance(item, dict)]
            text = ''.join(c.get('text', '') for item in decoded.get('output', []) if item.get('type') == 'message'
                           for c in item.get('content', []) if c.get('type') == 'output_text')
            if not text.strip():
                raise ValueError('empty_model_output')
            # These replies are synthetic/public. Never persist raw provider bodies or headers.
            save(self.directory / ('output-' + str(len(self.receipt['calls'])) + '.json'),
                 {'case_id': case_id, 'skill': skill, 'output': text})
            try:
                value = json.loads(text) if schema else text
            except json.JSONDecodeError:
                record['json_failure_kind'] = json_framing_kind(text)
                raise
            if schema:
                jsonschema.Draft202012Validator(schema).validate(value)
            record['status'] = 'completed'
            return value, decoded
        except Exception as error:
            record.update(status='failed', error_class=type(error).__name__)
            raise
        finally:
            record['elapsed_seconds'] = round(time.monotonic() - started, 3)
            save(self.directory / 'receipt.json', self.receipt)


async def compose(provider, locale):
    from contextlib import asynccontextmanager
    from copy import deepcopy
    from types import SimpleNamespace
    from apps.api.lifetime_memory_composer import _compose
    from apps.api.lifetime_memory_lane_engine import BoundedLaneInput, lane_contract
    from apps.api.memoir_preview import normalize_composer_refs
    checkpoints, phases = {}, []
    # Bind the host fingerprint/token budget to the same configured route used
    # by the real calls, including when the configuration came from ENV_FILE.
    os.environ['MEMORY_SPARK_MEMOIR_COMPOSER_MODEL'] = provider.config.get(
        'MEMORY_SPARK_MEMOIR_COMPOSER_MODEL') or provider.config['MEMORY_SPARK_LLM_MODEL']
    class Broker:
        async def rpc(self, name, **payload):
            if name == 'read_memoir_checkpoint':
                return deepcopy(checkpoints.get(payload['p_key']))
            if name == 'save_memoir_checkpoint':
                checkpoints[payload['p_key']] = deepcopy(payload['p_value'])
                return True
            if name == 'record_lifetime_lane_output':
                return True
            raise ValueError('unexpected_isolated_composer_rpc')
    class IsolatedPublisher:
        @asynccontextmanager
        async def guard(self, fence):
            yield
    current = None
    async def real_model(request):
        bounded = BoundedLaneInput.model_validate(json.loads(request.content)['bounded_lane'])
        instructions, schema = lane_contract(bounded.phase, locale, batch=True)
        instructions += load_prompt_artifact(ROOT / 'tests/evaluation/prompts/live-skills/independent-events.md')
        phase_id = f'composer-{locale}-{current["coverage_round"]}-{bounded.phase}-{len(phases)+1}'
        phases.append({'round':current['coverage_round'],'phase':bounded.phase})
        value, _ = await provider.call(phase_id, 'memoir-composer', instructions, json.loads(bounded.packet), schema)
        return httpx.Response(200, json={'reply':json.dumps(normalize_composer_refs(value),ensure_ascii=False)})
    worker = SimpleNamespace(broker=Broker(), worker_url='https://isolated.invalid',worker_secret='synthetic',
        worker_transport=httpx.MockTransport(real_model),lane_publisher=IsolatedPublisher())
    current = progressive_page(locale)
    original = deepcopy(current)
    first = await _compose(current,worker)
    if first['status'] != 'ready' or current != original:
        raise ValueError('initial_progressive_checkpoint_failed')
    save(provider.directory / ('composer-'+locale+'-5.json'),first)
    unchanged_event = current['batch']['events'][1]['id']
    unchanged = [s for s in first['sections'] if 'block' in s and s['event_ids'] == [unchanged_event]]
    if not unchanged:
        raise ValueError('independent_passage_required_for_preservation_check')
    current = progressive_page(locale, first)
    second = await _compose(current,worker)
    save(provider.directory / ('composer-'+locale+'-10.json'),second)
    kept = {s['id']:s for s in second.get('sections',[]) if 'block' in s}
    if any(s['id'] not in kept or s['block'] != kept[s['id']]['block'] for s in unchanged):
        raise ValueError('unchanged_writing_not_preserved')
    new_sources = {s['id'] for s in current['batch']['new_messages']}
    if not any(ref['source_id'] in new_sources for s in second['sections'] for ref in s['source_refs']):
        raise ValueError('progressive_update_lost_new_original_evidence')
    return {'checkpoints':[5,10],'phases':phases,'unchanged_passages_preserved':len(unchanged),
            'new_original_evidence_retained':True,'rendered':True,'publication_approved':False,
            'scope':'actual composer orchestration with real models; isolated checkpoint storage, native PostgreSQL tested separately'}


async def native_search(provider, skill):
    # Real search calls are required. A plausible answer with URLs cannot pass.
    if skill == 'memoir-historical-news-research':
        from apps.api.historical_news import validate_evidence
        from apps.api.historical_news_provider import decode_discovery, GatewayHistoricalProvider
        query = 'Sydney, Australia 2000–2000 civic culture sport public events'
        from apps.api.prompt_artifact import prompt_path
        instructions = load_prompt_artifact(prompt_path('memoir/skills/memoir-historical-news-research/discovery')).replace('{{query}}', query)
        _, response = await provider.call('historical-native-search', skill, instructions, {'public_query': query}, search=True)
        discovery = decode_discovery(response)
        hypothesis = {'start': 2000, 'end': 2000, 'place': 'Sydney, Australia', 'country': 'Australia'}
        adapter = GatewayHistoricalProvider()
        checked, errors = [], []
        for lead in discovery['events'][:2]:
            try:
                timeout = min(30, provider.deadline - time.monotonic())
                if timeout <= 0:
                    raise TimeoutError()
                page = await adapter.inspect(lead['source_url'], timeout=timeout)
                checked.append(validate_evidence(lead, discovery['receipt'], page, hypothesis))
            except Exception as error:
                errors.append(type(error).__name__)
        save(provider.directory / 'historical-sources.json', {'receipt': discovery['receipt'],
            'verified_clues': checked, 'inspection_errors': errors})
        if not checked:
            raise ValueError('no_independently_verified_historical_clue')
        return {'native_search_receipt': discovery['receipt'], 'verified_clues': len(checked), 'inspection_errors': errors}
    from apps.api.place_photo_browser import _research
    helper = _research()
    _, response = await provider.call('photo-native-search', skill,
        'Search for original public photograph pages and archive albums for the place "Sydney". '
        'Requested scene capture period: 1980-01-01 through 1989-12-31. Cite original source pages. '
        'Webpage publication and upload dates are not capture dates.',
        {'public_place': 'Sydney, Australia', 'capture_period': '1980–1989'}, search=True)
    calls = [c for c in response['output'] if c.get('type') == 'web_search_call' and c.get('status') == 'completed' and c.get('id')]
    if not 1 <= len(calls) <= 4:
        raise ValueError('missing_native_search_receipt')
    origins = {s['url']: call['id'] for call in calls
        for s in call.get('action', {}).get('sources', []) if s.get('url')}
    urls = list(origins)[:24]
    if not urls:
        raise ValueError('missing_native_sources')
    temporal = helper.normalize_period('1980s', date.today())
    verified, errors, receipts = [], [], []
    for url in urls[:2]:
        try:
            remaining = min(30, provider.deadline - time.monotonic())
            if remaining <= 0:
                raise TimeoutError()
            # Helper enforces public URLs, DNS pinning, robots, and item date evidence.
            found = await asyncio.to_thread(helper.llm_source_photos, url, 'Sydney', temporal, timeout=remaining)
            verified.extend(found)
            if found:
                receipts.append(dict(response_id=response['id'], tool_call_id=origins[url], discovery_source_url=url))
        except Exception as error:
            errors.append(type(error).__name__)
    save(provider.directory / 'photo-sources.json', {'response_id': response['id'], 'tool_call_ids': [call['id'] for call in calls],
        'returned_urls': urls, 'verified_photos': verified, 'inspection_errors': errors})
    if not verified:
        raise ValueError('no_independently_verified_photo')
    return {'native_search_receipt': {'response_id': response['id'], 'verified_source_receipts': receipts},
            'verified_photos': len(verified), 'inspection_errors': errors}


def manifest():
    skills = sorted(p.parent.name for p in (ROOT / 'skills').glob('*/SKILL.md'))
    return dict(skills=skills, scope='isolated live LLM skill contracts; no application persistence or end-to-end certification',
                synthetic=True, concurrency=1, transport_retries=0,
                skill_sha256={s: hashlib.sha256((ROOT / 'skills' / s / 'SKILL.md').read_bytes()).hexdigest() for s in skills})


def task_list():
    tasks = [(c['id'], c['skill'], c) for c in cases()]
    tasks += [('composer-pipeline-' + locale, 'memoir-composer', locale) for locale in ('en-AU', 'zh-CN')]
    tasks += [(s + '-native-discovery', s, None) for s in ('memoir-historical-news-research', 'memoir-place-photo-research')]
    if {t[1] for t in tasks} != set(manifest()['skills']):
        raise ValueError('missing_live_skill_case')
    return tasks


async def execute(args):
    from dotenv import dotenv_values
    config = {**dotenv_values(args.env_file, interpolate=False), **os.environ}
    required = ('MEMORY_SPARK_LLM_BASE_URL', 'MEMORY_SPARK_LLM_MODEL', 'MEMORY_SPARK_LLM_API_KEY')
    if not all(config.get(k) for k in required):
        raise ValueError('existing_gateway_configuration_required')
    url = urlsplit(config[required[0]])
    if url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('invalid_gateway_origin')
    directory = args.output_root.expanduser().resolve() / str(uuid4())
    directory.mkdir(parents=True, mode=0o700)
    receipt = {**manifest(), 'schema_version': 'memoir-live-skill-tests/1', 'run_id': directory.name,
               'started_at': datetime.now(timezone.utc).isoformat(), 'status': 'running', 'calls': [], 'results': [],
               'limits': {'max_calls': args.max_calls, 'timeout_seconds': args.timeout, 'deadline_seconds': args.deadline},
               'provider_request_count': None, 'note': 'HTTP dispatches counted; gateway internal attempts unavailable'}
    started = time.monotonic()
    provider = LiveProvider(config, receipt, directory, timeout=args.timeout, deadline=started + args.deadline,
                            max_calls=args.max_calls, effort=args.effort)
    tasks = task_list()
    if args.skill:
        tasks = [row for row in tasks if row[1] == args.skill]
    if args.case:
        tasks = [row for row in tasks if row[0] == args.case]
    if not tasks:
        raise ValueError('empty_skill_case_selection')
    receipt['selected_skills'] = sorted({row[1] for row in tasks})
    save(directory / 'receipt.json', receipt)
    for case_id, skill, case in tasks:
        before = len(receipt['calls'])
        result = dict(case_id=case_id, skill=skill, status='running', scope=(case.get('scope') if isinstance(case, dict) else None))
        tick = time.monotonic()
        try:
            if skill == 'memoir-composer':
                result['checks'] = await compose(provider, case)
            elif case is None:
                result['checks'] = await native_search(provider, skill)
            else:
                value, _ = await provider.call(case_id, skill, case['instructions'], case['input'], case['schema'])
                validate_case(case, value)
                result['checks'] = {'schema_and_semantics': True}
            result['status'] = 'passed'
        except Exception as error:
            result.update(status='failed', error_class=type(error).__name__)
            # Only known fixed diagnostic identifiers, never exception text from transports/providers.
            message = str(error)
            if type(error) in (ValueError, RuntimeError) and message.replace('_', '').isalnum() and len(message) < 90:
                result['reason'] = message
            latest = receipt['calls'][-1] if len(receipt['calls']) > before else {}
            if latest.get('json_failure_kind'):
                result['reason'] = latest['json_failure_kind']
            elif latest.get('rejection_category'):
                result['reason'] = latest['rejection_category']
        result.update(elapsed_seconds=round(time.monotonic() - tick, 3), http_dispatches=len(receipt['calls']) - before)
        receipt['results'].append(result)
        save(directory / 'receipt.json', receipt)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    receipt['status'] = 'passed' if all(r['status'] == 'passed' for r in receipt['results']) else 'failed'
    receipt['elapsed_seconds'] = round(time.monotonic() - started, 3)
    save(directory / 'receipt.json', receipt)
    report = ['# Memoir live skill tests', '', receipt['scope'], '',
              '| Case | Skill | Result | Seconds | HTTP dispatches |', '| --- | --- | --- | ---: | ---: |']
    report += [f"| {r['case_id']} | {r['skill']} | {r['status']} | {r['elapsed_seconds']} | {r['http_dispatches']} |" for r in receipt['results']]
    report += ['', 'Native search passes require completed tool receipts and independently inspected source evidence.',
               'Profile cases validate admitted checkpoint pages, not host scheduling or persisted effects. Retired localization is excluded.',
               'Story-game tests the missing-authority rejection; game runtime is unavailable. Grouping uses deterministic production code.',
               'HTTP calls are bounded; internal gateway attempts and monetary cost are not verified.', '']
    (directory / 'report.md').write_text('\n'.join(report))
    print(json.dumps({'status': receipt['status'], 'receipt': str(directory / 'receipt.json'), 'report': str(directory / 'report.md')}))
    return 0 if receipt['status'] == 'passed' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Without this flag, print the plan and make zero calls')
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    parser.add_argument('--output-root', type=Path, default=Path.home() / 'memoir-test-results/live-skills')
    parser.add_argument('--skill', choices=manifest()['skills'])
    parser.add_argument('--case', choices=[t[0] for t in task_list()], help='Run one specific case')
    parser.add_argument('--effort', choices=['low', 'medium', 'high', 'max'], default='max')
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--deadline', type=float, default=1800)
    parser.add_argument('--max-calls', type=int, default=32)
    args = parser.parse_args()
    if not 1 <= args.max_calls <= 32 or not 1 <= args.timeout <= 240 or not 1 <= args.deadline <= 1800:
        parser.error('Limits exceed the bounded live suite')
    if not args.execute:
        selected = [t for t in task_list() if (not args.skill or t[1] == args.skill)
                    and (not args.case or t[0] == args.case)]
        print(json.dumps({**manifest(), 'selected_cases': [t[0] for t in selected],
                         'selected_skills': sorted({t[1] for t in selected}), 'http_dispatches': 0},
                         ensure_ascii=False, indent=2))
        return 0
    try:
        return asyncio.run(execute(args))
    except Exception as error:
        print(json.dumps({'status': 'failed', 'error_class': type(error).__name__}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
