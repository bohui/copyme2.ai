"""Incomplete policy review retries through the real HTTP and SQL turn boundary."""
import json
import logging
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from apps.api import agent_routes, policy_review
from apps.api.codex_runtime import CodexRuntime
from apps.api.main import create_app
from apps.api.model_request import complete_json
from apps.api.store import MemoryStore
from controlled_collector import worker_reply
from memoir_postgres_workflow import PostgresRest
from test_agent_commit_postgres import OWNER
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database, database
from test_name_only_opening import proposal


REASON = {'code': 'ambiguous_restriction', 'detail': 'The apparent restriction has an unclear referent.'}


@pytest.mark.parametrize('streaming,opening', [(False, False), (True, False), (True, True)])
@pytest.mark.parametrize('outcome', ['clear', 'restricted', 'incomplete', 'legacy'])
def test_inconclusive_review_retries_before_reply_and_keeps_audit(
        sql, tmp_path, monkeypatch, caplog, streaming, opening, outcome):
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL', sql.publication_dsn)
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_MODEL', 'gpt-5.6-luna-pooled')
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION', 'compact-v1')
    monkeypatch.setenv('MEMOIR_TWO_LANES', '0')
    monkeypatch.setenv('MEMORY_SPARK_EARLY_POLICY_ACK', '1' if opening else '0')
    logger = logging.getLogger('tests.policy_review_recovery')
    monkeypatch.setattr(policy_review, 'diagnostic_logger', logger, raising=False)
    caplog.set_level(logging.INFO, logger=logger.name)
    restriction = '以后请不要再提我的学校。'
    text = ('陈明以前叫陈小明。长大后学习忙了，我回去找伙伴的次数少了。'
            + (restriction if outcome == 'restricted' else ''))
    turn = str(uuid4())
    requests, collector_calls = [], []
    first_reason = None if outcome == 'legacy' else REASON
    acknowledgement = '您提到长大后回去找伙伴的次数慢慢少了。'

    def review_provider(request):
        body = json.loads(request.content)
        payload = json.loads(body['input'])
        assert 'reason' in body['text']['format']['schema']['required']
        requests.append((body, payload))
        incomplete = len(requests) == 1 or outcome == 'incomplete'
        controls = []
        if not incomplete and outcome == 'restricted':
            start = text.index(restriction)
            controls = [dict(kind='excluded_topic', quote=restriction,
                             char_start=start, char_end=start + len(restriction))]
        output = dict(complete=not incomplete, restrictions=controls,
                      reason=REASON if incomplete else None)
        if outcome == 'legacy' and len(requests) == 1:
            del output['reason']  # Replay the exact original complete:false shape.
        if opening:
            output['acknowledgement'] = None if incomplete else acknowledgement
        return httpx.Response(200, json=dict(id=f'policy-attempt-{len(requests)}', status='completed',
            output=[dict(type='message', status='completed',
                         content=[dict(type='output_text', text=json.dumps(output))])]))

    async def review(*args, **kwargs):
        kwargs.update(base_url='http://127.0.0.1:1/v1', api_key='controlled-policy-key',
                      transport=httpx.MockTransport(review_provider))
        return await complete_json(*args, **kwargs)

    def collector(request):
        assert len(requests) == 2
        body = json.loads(request.content)
        collector_calls.append(body)
        pending = sql('select count(*) from public.user_lifetime_pending_policy;').stdout.strip()
        assert pending == '0', 'Reply generation must wait for completed policy review'
        if outcome == 'restricted':
            assert restriction in json.dumps(body['interview_context'], ensure_ascii=False)
        output = proposal(mode='extract', name=None, question='您还记得小时候和伙伴一起做过什么吗？')
        output['acknowledgement'] = acknowledgement
        return worker_reply(request, dict(reply=json.dumps(output, ensure_ascii=False),
                                         thread_id='policy-recovery', artifacts=[]))

    monkeypatch.setattr(policy_review, 'complete_json', review)
    monkeypatch.setattr(agent_routes, 'authenticated_storage', lambda _: PostgresRest(sql, OWNER).storage())
    monkeypatch.setattr(agent_routes, 'runtime', CodexRuntime(home_root=tmp_path / 'homes',
        worker_url='http://controlled.invalid', worker_secret='synthetic',
        worker_transport=httpx.MockTransport(collector)))
    with TestClient(create_app(MemoryStore())) as client:
        response = client.post('/v1/agent/turn', headers={
            'Accept': 'application/x-ndjson' if streaming else 'application/json'},
            json=dict(client_turn_id=turn, text=text, language='zh-CN'))
        assert len(requests) == 2, response.text
        assert requests[0][1]['source'] == requests[1][1]['source']
        assert requests[1][1]['previous_review'] == dict(complete=False, restrictions=[], reason=first_reason)
        assert [body['metadata']['request_id'] for body, _ in requests] == [turn, turn]
        if outcome == 'incomplete':
            if streaming:
                events = [json.loads(line) for line in response.text.splitlines()]
                assert events[-1]['type'] == 'error'
                assert not any(event['type'] in {'text_delta', 'conversation_saved', 'result'} for event in events)
            else:
                assert response.status_code == 503
                assert response.headers['X-Error-Code'] == 'LIFETIME_POLICY_PENDING'
            assert collector_calls == []
            assert sql('select count(*) from public.user_lifetime_source_policy_receipt;').stdout.strip() == '0'
        else:
            assert response.status_code == 200, response.text
            if streaming:
                events = [json.loads(line) for line in response.text.splitlines()]
                assert not any(event['type'] == 'error' for event in events), events
                result = next(event['data'] for event in events if event['type'] == 'result')
            else:
                result = response.json()
            assert result['conversation_saved'] and len(collector_calls) == 1
            receipt = json.loads(sql('select review from public.user_lifetime_source_policy_receipt;').stdout)
            assert receipt['receipt']['policy_review_attempts'] == [
                dict(response_id='policy-attempt-1', complete=False, reason=first_reason),
                dict(response_id='policy-attempt-2', complete=True, reason=None)]
            assert 'reason' not in receipt['output']  # Keep the existing SQL review contract.
            # A saved retry must replay without another model call or duplicate source.
            replay = client.post('/v1/agent/turn', json=dict(project_id=result['project_id'],
                client_turn_id=turn, text=text, language='zh-CN'))
            assert replay.status_code == 200 and replay.json()['cached']
            assert len(requests) == 2 and len(collector_calls) == 1
        assert text not in str(caplog.text)
        assert REASON['detail'] not in caplog.text
        assert REASON['detail'] not in response.text
        records = [json.loads(record.message.split(' ', 1)[1]) for record in caplog.records
                   if record.name == logger.name]
        assert records[0]['event'] == 'policy_review_incomplete'
        assert records[0]['error_code'] == ('reason_missing' if first_reason is None else REASON['code'])
        assert records[0]['request_id'] == turn
        assert records[0]['status'] == 'retrying'
        if outcome == 'incomplete':
            assert len(records) == 2 and records[-1]['status'] == 'failed'
        assert sql('select count(*) from public.user_narrator_source;').stdout.strip() == '1'


@pytest.mark.parametrize('reason', [None, REASON])
def test_complete_review_never_carries_an_incomplete_reason(reason):
    output = dict(complete=True, restrictions=[], reason=reason)
    if reason is None:
        assert policy_review.validate_review(output, {'text': 'A memory.'}) == dict(complete=True, restrictions=[])
    else:
        with pytest.raises(ValueError):
            policy_review.validate_review(output, {'text': 'A memory.'})


@pytest.mark.parametrize('reason', [
    {'code': 'unknown', 'detail': 'Unrecognized reason.'},
    {'code': 'ambiguous_restriction', 'detail': ' '},
    {'code': 'ambiguous_restriction', 'detail': 'x' * 301},
    {'code': 'ambiguous_restriction', 'detail': 'Bounded reason.', 'private': 'extra'},
])
def test_audit_reason_is_bounded_and_typed(reason):
    with pytest.raises(ValueError):
        policy_review.PolicyReview.model_validate(dict(complete=False, restrictions=[], reason=reason))
