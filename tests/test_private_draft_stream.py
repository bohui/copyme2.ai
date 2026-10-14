import asyncio
from contextlib import asynccontextmanager
import json

import pytest

from apps.api.lifetime_memory_reads import ReadJSONResponse, ReadSnapshot
from test_lifetime_memory_reads import FENCE


def test_draft_stream_sends_changes_and_finishes_without_repeated_http_requests():
    from apps.api.private_draft_stream import PrivateDraftStreamResponse

    async def run():
        values = iter([
            {'updating': True, 'background_progress': {'phase': 'summarizing'}},
            {'updating': True, 'background_progress': {'phase': 'drafting'}},
            {'updating': False, 'preview': {'text': '童年回忆'}},
        ])
        sent, closed = [], []
        response = PrivateDraftStreamResponse(
            {'updating': True, 'background_progress': {'phase': 'summarizing'}},
            lambda: next(values), lambda: closed.append(True), poll_interval=0)
        await serve(response, sent.append)
        events = frames(sent)
        assert [e['type'] for e in events] == ['draft_update', 'draft_update', 'draft_update', 'complete']
        assert events[-2]['data']['preview']['text'] == '童年回忆'
        assert closed == [True]
        assert b'application/x-ndjson' in dict(sent[0]['headers'])[b'content-type']

    asyncio.run(run())


def test_draft_stream_guards_each_snapshot_at_send_and_never_leaks_stale_content():
    from apps.api.private_draft_stream import PrivateDraftStreamResponse
    from apps.api.lifetime_memory_publication import PublicationUnavailable

    async def run():
        guarded, sent = [], []
        @asynccontextmanager
        async def guard(fence):
            guarded.append(fence)
            if len(guarded) == 2:
                raise PublicationUnavailable('withdrawn private words')
            yield
        publisher = type('Publisher', (), {'guard': staticmethod(guard)})()
        first = ReadJSONResponse(ReadSnapshot({'updating': True}, FENCE), publisher=publisher)
        newer = ReadJSONResponse(ReadSnapshot({'updating': False, 'preview': {'text': 'withdrawn private words'}},
                                             {**FENCE, 'draft_revision': FENCE.get('draft_revision', 0) + 1}), publisher=publisher)
        response = PrivateDraftStreamResponse(first, lambda: newer, lambda: None, poll_interval=0)
        await serve(response, sent.append)
        assert len(guarded) == 2
        assert guarded[1]['draft_revision'] == guarded[0]['draft_revision'] + 1
        assert [event['type'] for event in frames(sent)] == ['draft_update', 'error']
        assert b'withdrawn private words' not in b''.join(m.get('body', b'') for m in sent)

    asyncio.run(run())


def test_draft_stream_disconnect_closes_storage_and_stops_reading():
    from apps.api.private_draft_stream import PrivateDraftStreamResponse

    async def run():
        sent, reads, closed = [], [], []
        disconnected = asyncio.Event()
        async def receive():
            await disconnected.wait()
            return {'type': 'http.disconnect'}
        async def send(message):
            sent.append(message)
            if message['type'] == 'http.response.body':
                disconnected.set()
        response = PrivateDraftStreamResponse({'updating': True}, lambda: reads.append(True),
                                             lambda: closed.append(True), poll_interval=60)
        await response({'type': 'http', 'asgi': {'spec_version': '2.3'}}, receive, send)
        assert not reads and closed == [True]

    asyncio.run(run())


def test_draft_stream_returns_safe_failure_when_the_read_fails():
    from apps.api.private_draft_stream import PrivateDraftStreamResponse
    def broken():
        raise RuntimeError('secret provider details')
    async def run():
        sent = []
        await serve(PrivateDraftStreamResponse({'updating': True}, broken, lambda: None, poll_interval=0), sent.append)
        assert frames(sent)[-1] == {'type': 'error', 'code': 'PRIVATE_DRAFT_UNAVAILABLE'}
        assert b'secret provider details' not in b''.join(m.get('body', b'') for m in sent)
    asyncio.run(run())


def test_unchanged_pending_draft_sends_heartbeats_without_repeating_the_snapshot():
    from apps.api.private_draft_stream import PrivateDraftStreamResponse
    async def run():
        values = iter([{'updating': True}, {'updating': False}])
        sent = []
        await serve(PrivateDraftStreamResponse({'updating': True}, lambda: next(values), lambda: None,
                                              poll_interval=0, heartbeat_interval=0), sent.append)
        assert [e['type'] for e in frames(sent)] == ['draft_update', 'heartbeat', 'draft_update', 'complete']
    asyncio.run(run())


async def serve(response, record):
    async def send(message):
        record(message)
    async def receive():
        await asyncio.Future()
    await response({'type': 'http', 'asgi': {'spec_version': '2.3'}}, receive, send)


def frames(messages):
    return [json.loads(line) for line in b''.join(m.get('body', b'') for m in messages).splitlines()]


@pytest.mark.parametrize('thinking,drafts,origin,allowed', [
    ('1', '1', 'http://localhost:3010', True),
    ('1', '1', 'http://127.0.0.1:3010', True),
    ('1', '1', 'http://[::1]:3010', True),
    ('0', '1', 'http://localhost:3010', True),
    ('1', '0', 'http://localhost:3010', False),
    ('1', '1', 'https://copyme2.ai', False),
])
def test_debug_stream_requires_its_own_flag_and_a_loopback_browser(mapped, monkeypatch, thinking, drafts, origin, allowed):
    client, _, calls, _ = mapped
    monkeypatch.setenv('MEMORY_SPARK_SHOW_THINKING_STEPS', thinking)
    monkeypatch.setenv('MEMORY_SPARK_SHOW_DRAFT_UPDATES', drafts)
    response = client.get('/v1/story/private-draft?project_id=read-project',
                          headers={'Accept': 'application/x-ndjson', 'Origin': origin})
    assert response.status_code == (200 if allowed else 404)
    if allowed:
        assert response.headers['content-type'].startswith('application/x-ndjson')
        assert json.loads(response.text.splitlines()[0])['type'] == 'draft_update'
        assert calls[-1][0] == 'actual_send_guard'
    else:
        assert calls == []


from test_lifetime_memory_read_api import mapped
