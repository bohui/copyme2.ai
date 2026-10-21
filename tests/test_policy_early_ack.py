"""The reviewed acknowledgement reaches HTTP before the collector can finish."""
import asyncio
import json
from uuid import uuid4

import httpx
import pytest

from apps.api import policy_review
from apps.api.codex_runtime import CodexRuntime
from apps.api.model_request import complete_json
from scripts.canonical_turn import canonical_turn, CanonicalTurnFailed
from memoir_postgres_workflow import PostgresRest
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database, database
from test_agent_commit_postgres import OWNER
from test_name_only_opening import proposal
from controlled_collector import worker_reply


@pytest.mark.parametrize('language,text,acknowledgement,question', [
    ('en-AU', 'My father repaired bicycles.', 'Your father repaired bicycles.', 'What tools did he use?'),
    ('zh-CN', '父亲常常修自行车。', '您提到父亲常常修自行车。', '您还记得父亲用过什么工具吗？'),
    ('zh-CN', 'Please reply in Chinese. My father repaired bicycles.', '您提到父亲修自行车。', '您还记得父亲用过什么工具吗？'),
])
@pytest.mark.parametrize('outcome', ['saved', 'collector_failure', 'save_failure'])
def test_reviewed_acknowledgement_precedes_blocked_collector_and_replays_once(
        sql, tmp_path, monkeypatch, language, text, acknowledgement, question, outcome):
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL', sql.publication_dsn)
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_MODEL', 'gpt-5.6-luna-pooled')
    monkeypatch.setenv('MEMORY_SPARK_EARLY_POLICY_ACK', '1')
    policy_calls = []

    async def review(name, payload, schema, **kwargs):
        assert payload['source']['text'] == text
        assert 'interview_language' not in payload['source']
        assert payload['interview_language'] == language
        assert payload['acknowledgement_requested'] is True
        assert 'context' not in payload and 'profile' not in payload
        policy_calls.append(payload)
        output = dict(complete=True, restrictions=[], acknowledgement='  ' + acknowledgement + '\n')
        def respond(request):
            return httpx.Response(200, json=dict(id='fixed-review=', status='completed', output=[dict(
                type='message', status='completed', content=[dict(type='output_text', text=json.dumps(output))])]))
        kwargs.update(base_url='http://127.0.0.1:1/v1', api_key='synthetic-policy-key',
                      transport=httpx.MockTransport(respond))
        return await complete_json(name, payload, schema, **kwargs)

    monkeypatch.setattr(policy_review, 'complete_json', review)

    async def run():
        storage = PostgresRest(sql, OWNER).storage()
        initial_language = 'en-AU' if text.startswith('Please reply') else language
        storage.save_profile({'preferred_language': initial_language})
        fault_active = outcome != 'saved'
        real_rpc = storage.lifetime_rpc
        def guarded_rpc(name, **arguments):
            if fault_active and outcome == 'save_failure' and name in {'commit_lifetime_turn', 'commit_lifetime_strategy_turn'}:
                raise RuntimeError('Controlled save failure')
            return real_rpc(name, **arguments)
        monkeypatch.setattr(storage, 'lifetime_rpc', guarded_rpc)
        entered, release = asyncio.Event(), asyncio.Event()
        calls, events = [], []
        async def provider(request):
            body = json.loads(request.content)
            assert body['interview_context']['reviewed_acknowledgement'] == acknowledgement
            calls.append(body)
            entered.set()
            await release.wait()
            if fault_active and outcome == 'collector_failure':
                return httpx.Response(503, json={'detail': 'Controlled provider failure'})
            output = proposal(mode='extract', name=None, question=question)
            output['acknowledgement'] = acknowledgement
            return worker_reply(request, dict(reply=json.dumps(output), thread_id='fixed-collector', artifacts=[]))
        runtime = CodexRuntime(home_root=tmp_path / 'homes', worker_url='http://controlled.invalid',
            worker_secret='synthetic', worker_transport=httpx.MockTransport(provider))
        turn = str(uuid4())
        task = asyncio.create_task(canonical_turn(runtime, storage, text,
            options=dict(client_turn_id=turn, language=language), on_event=events.append))
        try:
            await asyncio.wait_for(entered.wait(), timeout=20)
            assert ''.join(e.get('text', '') for e in events if e['type'] == 'text_delta') == acknowledgement
            assert not any(e['type'] in {'conversation_saved', 'reply_complete', 'question_validated'} for e in events)
            assert sql('select count(*) from public.user_interview_turn where collector is not null;').stdout.strip() == '0'
        finally:
            release.set()
        if outcome == 'saved':
            result = await task
        else:
            with pytest.raises(CanonicalTurnFailed):
                await task
            assert not any(e['type'] in {'conversation_saved', 'reply_complete', 'question_validated'} for e in events)
            assert sql('select count(*) from public.user_interview_turn where collector is not null;').stdout.strip() == '0'
            assert sql('select count(*) from public.user_narrator_source;').stdout.strip() == '1'
            fault_active = False
            events.clear()
            result = await canonical_turn(runtime, storage, text,
                options=dict(client_turn_id=turn, language=language), on_event=events.append)
        assert result['conversation_saved'] is True
        assert result['reply'] == acknowledgement + '\n\n' + question
        assert ''.join(e.get('text', '') for e in events if e['type'] == 'text_delta') == result['reply']
        replay = await canonical_turn(runtime, storage, text,
            options=dict(client_turn_id=turn, project_id=result['project_id'], language=language))
        assert replay['cached'] and replay['reply'] == result['reply']
        assert len(policy_calls) == 1
        assert len(calls) == (1 if outcome == 'saved' else 2)
        assert sql('select count(*) from public.user_narrator_source;').stdout.strip() == '1'
        storage.client.close()
    asyncio.run(run())


@pytest.mark.parametrize('fault', ['source', 'version', 'version_type', 'language', 'question', 'oversized', 'disabled'])
def test_cached_acknowledgement_never_crosses_source_language_or_flag(monkeypatch, fault):
    source = dict(id='current-source', version=1)
    value = dict(source_id=source['id'], source_version=1, language='en-AU', text='A supported statement.')
    monkeypatch.setenv('MEMORY_SPARK_EARLY_POLICY_ACK', '1')
    if fault == 'source': value['source_id'] = 'another-source'
    if fault == 'version': value['source_version'] = 2
    if fault == 'version_type': value['source_version'] = True
    if fault == 'language': value['language'] = 'zh-CN'
    if fault == 'question': value['text'] = 'A new question?'
    if fault == 'oversized': value['text'] = 'x' * 501
    if fault == 'disabled': monkeypatch.setenv('MEMORY_SPARK_EARLY_POLICY_ACK', '0')
    assert policy_review.reviewed_acknowledgement(value, source, 'en-AU') is None


def test_collector_cannot_change_a_reviewed_acknowledgement():
    from test_interview_strategy import context, wire
    from apps.api.lifetime_memory_continuity import validate_governed_collector_result, governed_collector_schema
    ctx = context(text='My father repaired bicycles.')
    ctx['reviewed_acknowledgement'] = 'Your father repaired bicycles.'
    schema = governed_collector_schema(ctx)
    assert schema['properties']['acknowledgement']['enum'] == [ctx['reviewed_acknowledgement']]
    with pytest.raises(ValueError, match='cannot replace the streamed acknowledgement'):
        validate_governed_collector_result(wire(acknowledgement='A replacement.'), ctx)


def test_pending_policy_hides_a_previous_source_acknowledgement(sql):
    from test_lifetime_policy_atomic_postgres import accept, begin_review, status
    from test_lifetime_memory_postgres import resolve
    from test_shared_memory_events_postgres import literal
    identity = resolve(sql)
    source = accept(sql, identity, 'My father repaired bicycles.')['source']
    fence = begin_review(sql, identity)
    output = dict(complete=True, restrictions=[])
    receipt = dict(response_id='fixed-review=', acknowledgement='Your father repaired bicycles.',
                   acknowledgement_language='en-AU')
    sql(f"set role service_role; select public.complete_lifetime_policy_review({literal(fence)}::jsonb,'{source['id']}',1,{literal(output)}::jsonb,{literal(receipt)}::jsonb); reset role;")
    saved = status(sql, identity)['reviewed_acknowledgement']
    assert saved == dict(source_id=source['id'], source_version=1, language='en-AU', text=receipt['acknowledgement'])
    from test_agent_commit_postgres import as_user
    sql(as_user(f"select public.change_user_narrator_source({literal(identity['project_id'])},'{source['id']}',1,'edit','A changed narrator source.');"))
    pending = status(sql, identity)
    assert pending['pending'] is True and pending['reviewed_acknowledgement'] is None


def test_reviewed_acknowledgement_matches_rendered_reply_whitespace(monkeypatch):
    monkeypatch.setenv('MEMORY_SPARK_EARLY_POLICY_ACK', '1')
    source = dict(id='current-source', version=1)
    value = dict(source_id=source['id'], source_version=1, language='en-AU',
                 text='  Your father repaired bicycles.\n')
    assert policy_review.reviewed_acknowledgement(value, source, 'en-AU') == 'Your father repaired bicycles.'
