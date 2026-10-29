"""Draft prompt evaluation uses fictional cases and validates judge output."""
import argparse
import asyncio
import json

import httpx
import pytest
from jsonschema import ValidationError, validate

from scripts.evaluate_mira_prompt import cases, lane_b_cases, emotional_cases, realtime_cases, judge_schema


def test_comparison_uses_existing_bilingual_cases_and_real_reply_projections():
    inputs = cases()
    assert len(inputs) == len({case['id'] for case in inputs}) == 36
    assert {case['view']['reply_language'] for case in inputs} == {'en-AU', 'zh-CN'}
    for case in inputs:
        assert case['view']['current']['narrator']['original'] == case['context']['source']['text']
        assert 'gold' not in case['view'] and 'criteria' not in case['view']


def test_judge_schema_rejects_unbounded_scores_and_unrecognized_winners():
    rating = dict(score=4, critical=[], reason='Follows the current memory.')
    row = dict(id='fictional-case', A=rating, B=rating, winner='tie')
    validate(dict(results=[row]), judge_schema())
    with pytest.raises(ValidationError):
        validate(dict(results=[{**row, 'A': {**rating, 'score': 5}}]), judge_schema())
    with pytest.raises(ValidationError):
        validate(dict(results=[{**row, 'winner': 'candidate'}]), judge_schema())


def test_realtime_probes_use_no_background_question_pool_and_append_optional_news_last():
    from apps.api.conversation_reply_transport import reply_messages
    inputs = realtime_cases()
    assert len(inputs) == len({case['id'] for case in inputs}) == 12
    for case in inputs:
        assert case['view']['brief']['hints'] == []
        messages = reply_messages(case['view'], '')
        if case['id'].split('/')[1].endswith('news'):
            assert json.loads(messages[-1]['content'])['background_deliveries'][-1]['skill']=='memoir-historical-news-research'
            assert json.loads(messages[-2]['content'])['current']['narrator']['original']==case['context']['source']['text']
        else:
            assert json.loads(messages[-1]['content'])['current']['narrator']['original']==case['context']['source']['text']
        assert 'criteria' not in json.dumps(case['view'])


def test_lane_b_probes_keep_prepared_hints_and_current_narration_in_the_real_packet():
    cases()  # Load the existing shared fixture modules.
    inputs = lane_b_cases()
    assert len(inputs) == 6
    for case in inputs:
        assert len(case['view']['brief']['hints']) == 2
        assert case['view']['current']['narrator']['original'] == case['context']['source']['text']


def test_emotional_probes_cover_both_languages_without_putting_judge_criteria_in_requests():
    cases()
    inputs = emotional_cases()
    assert len(inputs) == len({case['id'] for case in inputs}) == 16
    assert {case['view']['reply_language'] for case in inputs} == {'en-AU', 'zh-CN'}
    for case in inputs:
        assert case['view']['current']['narrator']['original'] == case['context']['source']['text']
        assert case['criteria']['required']
        assert 'criteria' not in case['view'] and 'gold' not in case['view']


def test_generation_and_judge_requests_keep_the_interviewer_trace_name(tmp_path, monkeypatch):
    from scripts.evaluate_mira_prompt import evaluate, ROOT
    from test_conversation_reply import proposal

    case = next(row for row in cases() if row['id'].endswith('/en-AU')
                and row['criteria'].get('facts', {}).get('question'))
    baseline = tmp_path / 'baseline.md'
    baseline.write_text((ROOT / 'apps/api/prompts/mira/system.md').read_text())
    env = tmp_path / '.env'
    env.write_text('MEMORY_SPARK_LLM_MODEL=fixture-model\n'
        'MEMORY_SPARK_LLM_REASONING_EFFORT=low\n'
        'MEMORY_SPARK_LLM_BASE_URL=https://gateway.invalid/v1\n'
        'MEMORY_SPARK_LLM_API_KEY=fixture-key\n')
    requests = []

    def gateway(request):
        body = json.loads(request.content)
        requests.append(body)
        if body['model'] == 'fixture-judge':
            rating = dict(score=4, critical=[], reason='Controlled tracing fixture.')
            value = dict(results=[dict(id=case['id'], A=rating, B=rating, winner='tie')])
        else:
            value = {**proposal(), 'question':'What stands out about that memory?'}
        return httpx.Response(200, json=dict(id=f'fixture-response-{len(requests)}',
            status='completed', output=[dict(type='message', content=[dict(
                type='output_text', text=json.dumps(value))])]))

    client_type = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs:
        client_type(transport=httpx.MockTransport(gateway), **kwargs))
    args = argparse.Namespace(env_file=env, baseline=baseline, baseline_dispatch=None,
        reuse_baseline=None, judge_model='fixture-judge', output=tmp_path / 'report.json')
    asyncio.run(evaluate(args, [case]))

    assert len(requests) == 3
    assert all(body.get('metadata', {}).get('trace_name') == 'memoir-interviewer' for body in requests)
    assert all(body['metadata']['generation_name'] == 'memoir-interviewer' for body in requests)
    report = json.loads(args.output.read_text())
    assert all(row['contract'] == 'pass' for row in report['results'])
