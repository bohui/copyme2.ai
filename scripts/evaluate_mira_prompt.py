"""Bounded, blinded comparison of draft Mira prompts on existing fictional cases."""
import argparse
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def digest(value):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()


def cases():
    """Use the actual reply projection and existing bilingual regression inputs."""
    sys.path.insert(0, str(ROOT / 'tests'))
    from apps.api.conversation_reply import reply_instructions, reply_packet
    from apps.api.lifetime_memory_engine import validate_governed_context
    from scripts.memoir_skill_scenarios import build_cases
    from test_lifetime_memory_engine import fixture, encode
    from test_interview_question_novelty import partial_answer, question_goal_case, SCENARIOS
    result = []
    for item in build_cases():
        if item['skill'] != 'memoir-interviewer':
            continue
        governed, original = fixture()
        context = deepcopy(item['task']['context'])
        context['source']['id'] = original['source']['id']
        context['sources'] = [context['source']]
        context.update(reply_contract='reply-v2', two_lane_memory=True)
        packet = json.loads(governed.packet)
        text = context['source']['text']
        packet['current']['narrator'].update(original=text, char_end=len(text), language=item['locale'],
            version=context['source']['version'])
        packet['pinned']['language'] = item['locale']
        packet.update(instructions=reply_instructions(), interview_context={
            key: value for key, value in context.items() if key not in {'source', 'sources'}})
        view = reply_packet(validate_governed_context(encode(packet), context))
        result.append(dict(id=item['id'], context=context, view=view, criteria=item['gold']))
    for locale in ('en-AU', 'zh-CN'):
        for kind in ('partial', 'unanswered', 'reopen'):
            context, view = partial_answer(locale, reply_kind=kind)
            result.append(dict(id=f'continuity/{kind}/{locale}', context=context, view=view,
                criteria=dict(required=['Revisit the delivered question only when explicitly requested; otherwise follow the volunteered book-club memory.'])))
        for scenario in SCENARIOS:
            context, view = question_goal_case(locale, scenario, 'reply-v2')
            result.append(dict(id=f'question/{scenario}/{locale}', context=context, view=view,
                criteria=dict(required=['Follow the current scene, routine, consequence or reflection; preserve known company and respect the closed topic.'])))
    return result


def judge_schema():
    rating = dict(type='object', additionalProperties=False,
        properties=dict(score=dict(type='integer', minimum=0, maximum=4),
            critical=dict(type='array', items=dict(type='string')), reason=dict(type='string')),
        required=['score', 'critical', 'reason'])
    row = dict(type='object', additionalProperties=False, required=['id', 'A', 'B', 'winner'],
        properties=dict(id=dict(type='string'), A=rating, B=rating,
            winner=dict(type='string', enum=['A', 'B', 'tie'])))
    return dict(type='object', additionalProperties=False, required=['results'],
        properties=dict(results=dict(type='array', items=row)))


async def evaluate(args, inputs):
    import httpx
    from dotenv import dotenv_values
    from jsonschema import validate
    from apps.api.conversation_reply import reply_schema
    from apps.api.conversation_reply_transport import reply_messages
    from apps.api.lifetime_memory_continuity import validate_governed_collector_result
    from apps.api.model_request import decode_json_response
    config = dotenv_values(args.env_file)
    model = config.get('MEMORY_SPARK_COLLECTOR_MODEL') or config['MEMORY_SPARK_LLM_MODEL']
    effort = config.get('MEMORY_SPARK_COLLECTOR_REASONING_EFFORT') or config['MEMORY_SPARK_LLM_REASONING_EFFORT']
    arms = dict(baseline=dict(prompt=args.baseline.read_text(),
        dispatch=args.baseline_dispatch.read_text() if args.baseline_dispatch else ''),
        candidate=dict(prompt=(ROOT / 'apps/api/prompts/mira/system.md').read_text(), dispatch=''))
    rubric = (ROOT / 'tests/evaluation/prompts/mira-comparison.md').read_text()
    report = dict(schema_version='mira-prompt-comparison/1', synthetic=True,
        scope='Draft conversation proposals; no production publication or application persistence',
        model=model, judge_model=args.judge_model, effort=effort,
        prompts={arm: dict(**value, sha256=digest(value), published_version=None,
            characters=len(value['prompt'] + value['dispatch'])) for arm, value in arms.items()},
        judge_sha256=digest(rubric), cases_sha256=digest(inputs), results=[], judgments=[])
    semaphore = asyncio.Semaphore(4)
    calls = 0
    async with httpx.AsyncClient(timeout=75, trust_env=False, follow_redirects=False) as client:
        async def request(body):
            nonlocal calls
            async with semaphore:
                calls += 1
                if calls > 100:
                    raise ValueError('Evaluation request budget exceeded')
                started = time.monotonic()
                response = await client.post(config['MEMORY_SPARK_LLM_BASE_URL'].rstrip('/') + '/responses',
                    headers={'Authorization': 'Bearer ' + config['MEMORY_SPARK_LLM_API_KEY']}, json=body)
                response.raise_for_status()
                raw = response.json()
                return decode_json_response(raw), dict(response_id=raw['id'], model=raw.get('model'),
                    usage=raw.get('usage'), seconds=round(time.monotonic() - started, 3))
        async def generate(case, arm):
            schema = reply_schema(case['context'])
            view = {**case['view'], 'instructions': arms[arm]['prompt']}
            body = dict(model=model, input=reply_messages(view, arms[arm]['dispatch']),
                store=False, tools=[], tool_choice='none', reasoning=dict(effort=effort),
                max_output_tokens=3000, text=dict(format=dict(type='json_schema', name='mira_reply', strict=True, schema=schema)))
            row = dict(id=case['id'], arm=arm)
            try:
                output, receipt = await request(body)
                row.update(output=output, receipt=receipt)
                validate(output, schema)
                validated = validate_governed_collector_result(output, case['context'])
                facts = case['criteria'].get('facts', {})
                if 'question' in facts and bool(validated['plan']['candidates']) != facts['question']:
                    raise ValueError('Narrator control outcome mismatch')
                row.update(contract='pass', reply=validated['reply'])
            except Exception as error:
                row.update(contract='fail', error_type=type(error).__name__, error=str(error)[:500])
            report['results'].append(row)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        await asyncio.gather(*(generate(case, arm) for case in inputs for arm in arms))
        pairs = []
        for case in inputs:
            order = ['candidate', 'baseline'] if int(digest(case['id'])[0], 16) % 2 else ['baseline', 'candidate']
            rows = {row['arm']: row for row in report['results'] if row['id'] == case['id']}
            labels = dict(zip(('A', 'B'), order))
            pairs.append(dict(id=case['id'], task=case['view'], criteria=case['criteria'],
                A=rows[order[0]].get('output'), B=rows[order[1]].get('output')))
            pairs[-1]['task'] = {key: value for key, value in pairs[-1]['task'].items() if key != 'instructions'}
            case['judge_labels'] = labels
        async def judge(batch):
            body = dict(model=args.judge_model, instructions=rubric, input=json.dumps(batch, ensure_ascii=False),
                store=False, reasoning=dict(effort='low'), max_output_tokens=6000,
                text=dict(format=dict(type='json_schema', name='mira_comparison', strict=True, schema=judge_schema())))
            result, receipt = await request(body)
            validate(result, judge_schema())
            if {row['id'] for row in result['results']} != {row['id'] for row in batch}:
                raise ValueError('Judge returned incomplete or foreign cases')
            for row in result['results']:
                case = next(case for case in inputs if case['id'] == row['id'])
                report['judgments'].append(dict(id=row['id'], receipt=receipt,
                    ratings={case['judge_labels'][key]: row[key] for key in ('A', 'B')},
                    winner=case['judge_labels'].get(row['winner'], 'tie')))
        await asyncio.gather(*(judge(pairs[i:i + 4]) for i in range(0, len(pairs), 4)))
    report['summary'] = {arm: dict(
        contracts_passed=sum(row['contract'] == 'pass' for row in report['results'] if row['arm'] == arm),
        cases=len(inputs), mean_quality=round(sum(row['ratings'][arm]['score'] for row in report['judgments']) / len(inputs), 3),
        critical=sum(bool(row['ratings'][arm]['critical']) for row in report['judgments']),
        preferred=sum(row['winner'] == arm for row in report['judgments'])) for arm in arms}
    report['requests'] = calls
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report['summary']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--baseline-dispatch', type=Path)
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--judge-model', default='gpt-5.6-luna-memoir-low')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    from apps.api import prompt_artifact
    published_loader = prompt_artifact.load_prompt_artifact
    def draft_source(path):
        path = Path(path)
        return path.read_text() if path.is_relative_to(ROOT / 'apps/api/prompts/mira') else published_loader(path)
    with patch.object(prompt_artifact, 'load_prompt_artifact', draft_source):
        inputs = cases()
        if not args.execute:
            print(json.dumps(dict(cases=len(inputs), generation_requests=2 * len(inputs),
                judge_requests=(len(inputs) + 3) // 4, synthetic=True, requests=0)))
            return
        args.output.parent.mkdir(parents=True, exist_ok=True)
        asyncio.run(asyncio.wait_for(evaluate(args, inputs), timeout=900))


if __name__ == '__main__':
    main()
