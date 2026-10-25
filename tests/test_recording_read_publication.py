"""Recording consent at the real frozen read-response/outer ASGI boundary."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
from uuid import uuid4

import httpx
import psycopg
import pytest

from apps.api.lifetime_memory_reads import ReadJSONResponse, ReadSnapshot
from test_lifetime_memory_reads import FENCE, SCOPE, Publisher, execute, receive
from test_recording_descriptor_publication import RECORDINGS
from test_recording_consent import (
    consent_workflow, grant, ENDPOINT, POLICY, database, workflow, approved,
    attachment_database, private_database, event_database, sql, media, upload, OWNER,
)


class RecordingPublisher(Publisher):
    def __init__(self, recordings):
        super().__init__()
        self.recordings = recordings
        self.identifiers = []

    @asynccontextmanager
    async def guard(self, fence, *, recording_ids=None):
        async with super().guard(fence):
            self.identifiers.append(recording_ids)
            yield self.recordings


@pytest.mark.parametrize('shape', ['source', 'history'])
@pytest.mark.parametrize('state', ['allowed', 'withdrawn', 'partial', 'empty', 'missing'])
def test_frozen_read_descriptors_are_reauthorized_without_changing_other_json(shape, state):
    async def scenario():
        records = [] if state == 'empty' else deepcopy(RECORDINGS)
        content = {'text': 'Original 原文'}
        if state != 'missing':
            content['recordings'] = records
        expected = deepcopy(content)
        current = records if state == 'allowed' else records[:1] if state == 'partial' else []
        if state in {'withdrawn', 'partial'}:
            expected['recordings'] = current
        if shape == 'history':
            content = {'items': [content, {'text': 'No recording', 'recordings': []}], 'next_cursor': 'next'}
            expected = {'items': [expected, {'text': 'No recording', 'recordings': []}], 'next_cursor': 'next'}
        original = deepcopy(content)
        publisher = RecordingPublisher(current)
        snapshot = ReadSnapshot(content, FENCE)
        frozen = snapshot.body
        response = ReadJSONResponse(snapshot, publisher=publisher,
            headers={'X-Read-Test': 'preserved'})
        messages = []

        async def send(message):
            assert publisher.active, 'Authorization must cover headers and actual body send'
            messages.append(message)

        await response(SCOPE, receive, send)
        assert json.loads(messages[1]['body']) == expected
        headers = dict(messages[0]['headers'])
        assert headers[b'cache-control'] == b'no-store'
        assert headers[b'content-type'] == b'application/json'
        assert headers[b'x-read-test'] == b'preserved'
        assert int(headers[b'content-length']) == len(messages[1]['body'])
        assert not messages[1]['body'].endswith(b'\n')
        assert snapshot.body == frozen and content == original
        ids = [record['id'] for record in RECORDINGS] if state not in {'empty', 'missing'} else None
        assert publisher.identifiers == [ids]
    execute(scenario())


@pytest.fixture(params=[False, True], ids=['single', 'two_lane'])
def recorded_read(consent_workflow, media, tmp_path, monkeypatch, request):
    from apps.api import agent_routes, supabase_routes
    from apps.api.codex_runtime import CodexRuntime
    from memoir_postgres_workflow import PostgresRest
    from test_name_only_opening import proposal
    from controlled_collector import worker_reply
    client, storage, sql, objects, calls, mode = consent_workflow
    assert grant(client).status_code == 200
    monkeypatch.setenv('MEMOIR_TWO_LANES', '1' if request.param else '0')
    sql('update public.lifetime_two_lane_rollout set enabled=' + ('true' if request.param else 'false') + ';')
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_MODEL', 'gpt-5.6-luna-pooled')
    monkeypatch.setenv('MEMORY_SPARK_FREE_RECALL_ROUNDS', '99')

    def provider(request):
        output = proposal(mode='extract', name=None, question='What do you remember about the garden?')
        output['acknowledgement'] = 'You remember the garden.'
        output['plan']['conversation_phase'] = 'explore'
        return worker_reply(request, {'reply': json.dumps(output), 'thread_id': 'synthetic', 'artifacts': []})

    monkeypatch.setattr(agent_routes, 'authenticated_storage', lambda _: PostgresRest(sql, OWNER).storage())
    monkeypatch.setattr(supabase_routes, 'storage', lambda _: PostgresRest(sql, OWNER).storage())
    monkeypatch.setattr(agent_routes, 'runtime', CodexRuntime(home_root=tmp_path/'homes',
        worker_url='http://controlled.invalid', worker_secret='synthetic', worker_transport=httpx.MockTransport(provider)))
    records = [upload(client, media).json()['recording'] for _ in range(2)]
    turn = str(uuid4())
    command = {'text': 'I remember the garden.', 'source_kind': 'narrator_transcript',
        'recording_ids': [record['id'] for record in reversed(records)], 'client_turn_id': turn}
    response = client.post('/api/v1/memoir/agent/turn', json=command)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['conversation_saved'] and len(result['recordings']) == 2
    project = result['project_id']
    paths = {
        'source': f"/api/v1/memoir/user/projects/{project}/sources/{result['accepted_source_id']}",
        'receipt': f'/api/v1/memoir/agent/turns/{turn}?project_id={project}',
        'history': f'/api/v1/memoir/user/projects/{project}/history',
    }
    return client, storage, sql, result, paths


@pytest.mark.parametrize('endpoint', ['source', 'receipt', 'history'])
@pytest.mark.parametrize('withdraw', [False, True], ids=['permitted', 'withdrawn'])
def test_actual_read_route_withdrawal_after_serialization_before_send(recorded_read, monkeypatch, endpoint, withdraw):
    client, storage, sql, result, paths = recorded_read
    original = ReadJSONResponse._send_response
    frozen = []
    leases = sql('select coalesce(jsonb_agg(to_jsonb(l)),\'[]\'::jsonb) from public.user_agent_turn_lease l;').stdout

    async def before_send(self, send):
        content = json.loads(self.snapshot.body)
        data = content['items'][0] if endpoint == 'history' else content
        assert data['recordings'] == result['recordings']
        frozen.append(content)
        if withdraw:
            revoked = await asyncio.to_thread(client.put, ENDPOINT,
                json={**POLICY, 'action': 'revoke', 'expected_revision': 1})
            assert revoked.status_code == 200, revoked.text
        await original(self, send)

    monkeypatch.setattr(ReadJSONResponse, '_send_response', before_send)
    response = client.get(paths[endpoint], headers={'X-Request-ID': 'recording-read-race', 'Origin': 'http://localhost:3000'})
    assert response.status_code == 200, response.text
    assert len(frozen) == 1
    expected = deepcopy(frozen[0])
    if withdraw:
        (expected['items'][0] if endpoint == 'history' else expected)['recordings'] = []
        assert storage.source_recordings(result['project_id'], result['accepted_source_id']) == []
        assert client.get(result['recordings'][0]['content_url']).status_code == 404
    assert response.json() == expected, 'A frozen read published withdrawn recording descriptors'
    assert int(response.headers['content-length']) == len(response.content)
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-request-id'] == 'recording-read-race'
    assert response.headers['access-control-allow-origin'] == 'http://localhost:3000'
    assert not response.content.endswith(b'\n')
    assert sql('select coalesce(jsonb_agg(to_jsonb(l)),\'[]\'::jsonb) from public.user_agent_turn_lease l;').stdout == leases


def test_permitted_history_page_retains_more_than_twenty_recordings_across_turns(recorded_read):
    from test_original_recordings_postgres import ready
    from test_shared_memory_events_postgres import as_user, literal
    from controlled_policy import complete_seed_policy
    client, storage, sql, result, paths = recorded_read
    records = [ready(sql) for _ in range(20)]
    turn = str(uuid4())
    accepted = storage.accept_interview_turn(result['project_id'], turn, 'Another original memory',
        kind='narrator_transcript', recording_ids=[record['id'] for record in records])
    sql(as_user("insert into public.user_memory(user_id,project_id,kind,content,client_turn_id,source_sequence) values("
        f"'{OWNER}',{literal(result['project_id'])},'agent','Storyteller: Another original memory',"
        f"'{turn}',{accepted['source']['sequence']});"))
    complete_seed_policy(sql, OWNER)
    response = client.get(paths['history'])
    assert response.status_code == 200, response.text
    items = response.json()['items']
    assert [record['id'] for item in items for record in item['recordings']] == [
        *[record['id'] for record in result['recordings']], *[record['id'] for record in records]]
    assert int(response.headers['content-length']) == len(response.content)


@pytest.mark.parametrize('outcome', ['sent', 'cancelled', 'timeout', 'error'])
def test_actual_source_read_send_holds_consent_and_releases_on_failure(recorded_read, monkeypatch, outcome):
    client, storage, sql, result, paths = recorded_read
    from apps.api.lifetime_memory_reads import ReadPublication
    original = ReadPublication.__init__
    if outcome == 'timeout':
        def init(self, *args, **kwargs):
            original(self, *args, **kwargs, send_timeout=.5)
        monkeypatch.setattr(ReadPublication, '__init__', init)

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        messages = []
        async def send(message):
            if message['type'] == 'http.response.body' and b'content_url' in message.get('body', b''):
                assert json.loads(message['body'])['recordings'] == result['recordings']
                entered.set()
                await release.wait()
                if outcome == 'error': raise OSError('controlled ASGI send failure')
            messages.append(message)
        scope = {'type':'http', 'asgi':{'version':'3.0','spec_version':'2.4'}, 'http_version':'1.1',
            'method':'GET', 'scheme':'http', 'path':paths['source'], 'raw_path':paths['source'].encode(),
            'query_string':b'', 'headers':[(b'authorization',b'Bearer synthetic')],
            'client':('127.0.0.1',1234), 'server':('test',80)}
        sending = asyncio.create_task(client.app(scope, receive, send))
        withdrawing = None
        try:
            async with asyncio.timeout(3): await entered.wait()
            withdrawing = asyncio.create_task(asyncio.to_thread(client.put, ENDPOINT,
                json={**POLICY,'action':'revoke','expected_revision':1}))
            async with await psycopg.AsyncConnection.connect(sql.publication_dsn, autocommit=True) as observer:
                async with asyncio.timeout(3):
                    while not (await (await observer.execute("select exists(select 1 from pg_stat_activity where wait_event_type='Lock' and query like 'select public.recording_server_operation%')")).fetchone())[0]:
                        assert not withdrawing.done(), 'Withdrawal committed during the actual read send'
                        await asyncio.sleep(.01)
            assert not withdrawing.done()
            if outcome == 'cancelled': sending.cancel()
            elif outcome != 'timeout': release.set()
            if outcome == 'sent':
                await sending
            else:
                with pytest.raises({'cancelled':asyncio.CancelledError, 'timeout':TimeoutError, 'error':OSError}[outcome]):
                    await sending
                assert not any(b'content_url' in message.get('body',b'') for message in messages)
            assert (await withdrawing).status_code == 200
        finally:
            sending.cancel()
            await asyncio.gather(sending, return_exceptions=True)
            if withdrawing is not None: await withdrawing
    asyncio.run(scenario())
    assert client.get(result['recordings'][0]['content_url']).status_code == 404
