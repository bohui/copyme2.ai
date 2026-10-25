"""Actual JSON/NDJSON response sends, using deterministic consent barriers."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json

import pytest
from starlette.requests import ClientDisconnect

from apps.api.lifetime_memory_publication import PublicationDatabaseUnavailable
from apps.api.lifetime_memory_transport import (
    GovernedJSONResponse, GovernedStreamingResponse, governed_turn_events,
)
from test_lifetime_memory_transport import FENCE, SCOPE, Publisher, body_event, execute, no_disconnect


KINDS = ['json', 'source_accepted', 'result', 'reply_complete', 'conversation_saved']
RECORDINGS = [
    {'id': '00000000-0000-4000-8000-000000000005',
     'content_url': '/recordings/second/content', 'content_type': 'audio/mp4'},
    {'id': '00000000-0000-4000-8000-000000000004',
     'content_url': '/recordings/first/content', 'content_type': 'audio/webm'},
]


class RecordingPublisher(Publisher):
    def __init__(self):
        super().__init__(timeout=.5)
        self.recordings = deepcopy(RECORDINGS)
        self.recording_options = []
        self.unavailable = False

    @asynccontextmanager
    async def guard(self, fence, *, recording_ids=None):
        if self.unavailable:
            raise PublicationDatabaseUnavailable('controlled guard failure')
        async with super().guard(fence):
            self.recording_options.append(recording_ids)
            yield [deepcopy(record) for record in self.recordings
                   if recording_ids is not None and record['id'] in recording_ids]

    async def withdraw(self, remaining=()):
        async with self.lock:
            self.recordings = list(remaining)


def response_for(kind, content, publisher, *, cleanup=None, observed=None, queued=None, fence=FENCE):
    if kind == 'json':
        return GovernedJSONResponse(content, publisher=publisher, fence=fence,
            cleanup=cleanup, headers={'X-Recording-Test': 'preserved'})

    async def run(emit):
        emit.set_fence(fence)
        if kind != 'result':
            await emit.event({'type': kind, 'data': content})
        if queued is not None:
            queued.set()
        return emit.snapshot_result(content)

    return GovernedStreamingResponse(governed_turn_events(run, cleanup=cleanup),
        publisher=publisher, on_delivered=observed.append if observed is not None else None)


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('state', ['allowed', 'withdrawn', 'partial', 'empty', 'missing'])
def test_response_recordings_reauthorized_after_snapshot_before_actual_send(kind, state):
    async def scenario():
        publisher = RecordingPublisher()
        content = {'reply': '原来的 memory', 'conversation_saved': True}
        if state != 'missing':
            content['recordings'] = [] if state == 'empty' else deepcopy(RECORDINGS)
        original = deepcopy(content)
        queued = asyncio.Event()
        sent, observed, cleaned = [], [], []

        async def withdraw():
            if state in {'withdrawn', 'partial'}:
                await publisher.withdraw(RECORDINGS[:1] if state == 'partial' else ())

        async def cleanup():
            assert not publisher.active
            cleaned.append(True)

        response = response_for(kind, content, publisher, cleanup=cleanup,
            observed=observed, queued=queued)
        if kind == 'json':
            await withdraw()  # JSONResponse has already frozen the cached body.

        async def send(message):
            if kind != 'json' and (body_event(message) or {}).get('type') == 'started':
                await queued.wait()  # The producer has frozen the recording descriptors.
                await withdraw()
            if message['type'] == 'http.response.body' and message.get('body'):
                event = json.loads(message['body'])
                if kind == 'json' or event.get('type') != 'started':
                    assert publisher.active, 'Authorization must cover actual ASGI send'
            sent.append(message)

        await response(SCOPE, no_disconnect, send)
        expected = deepcopy(original)
        if state in {'withdrawn', 'partial'}:
            expected['recordings'] = RECORDINGS[:1] if state == 'partial' else []
        bodies = [m['body'] for m in sent if m['type'] == 'http.response.body' and m.get('body')]
        if kind == 'json':
            assert json.loads(bodies[0]) == expected
            assert not bodies[0].endswith(b'\n'), 'Ordinary JSON must keep its original framing'
            headers = dict(sent[0]['headers'])
            assert headers[b'content-type'] == b'application/json'
            assert headers[b'x-recording-test'] == b'preserved'
            assert int(headers[b'content-length']) == len(bodies[0])
        else:
            expected_kinds = [kind, 'result'] if kind != 'result' else ['result']
            personal = [json.loads(body) for body in bodies if json.loads(body)['type'] != 'started']
            assert [event['type'] for event in personal] == expected_kinds
            assert all(event['data'] == expected for event in personal)
            assert observed == personal, 'Delivery observers must see only filtered descriptors'
            assert all(body.endswith(b'\n') for body in bodies)
        assert content == original, 'Filtering must not mutate cached producer data'
        expected_ids = [record['id'] for record in RECORDINGS] if original.get('recordings') else None
        assert publisher.recording_options and all(ids == expected_ids for ids in publisher.recording_options)
        assert response.delivered and cleaned == [True]
    execute(scenario())


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('failure', ['guard', 'send', 'timeout', 'cancel'])
def test_recording_response_failure_releases_authority_and_cleanup(kind, failure):
    async def scenario():
        publisher = RecordingPublisher()
        publisher.unavailable = failure == 'guard'
        entered, withdrawal_started = asyncio.Event(), asyncio.Event()
        cleaned, observed, sent = [], [], []

        async def cleanup():
            assert not publisher.active
            cleaned.append(True)

        async def send(message):
            if message['type'] == 'http.response.body' and b'content_url' in message.get('body', b''):
                assert publisher.active
                entered.set()
                if failure == 'send':
                    raise OSError('controlled ASGI send failure')
                await asyncio.Event().wait()
            sent.append(message)

        response = response_for(kind, {'reply': 'memory', 'recordings': deepcopy(RECORDINGS)},
            publisher, cleanup=cleanup, observed=observed)
        if failure == 'guard':
            if kind == 'json':
                with pytest.raises(PublicationDatabaseUnavailable):
                    await response(SCOPE, no_disconnect, send)
            else:
                await response(SCOPE, no_disconnect, send)
                assert [body_event(m)['type'] for m in sent if body_event(m)] == ['started', 'error']
        else:
            sending = asyncio.create_task(response(SCOPE, no_disconnect, send))
            await entered.wait()

            async def withdraw():
                withdrawal_started.set()
                await publisher.withdraw()

            withdrawing = asyncio.create_task(withdraw())
            await withdrawal_started.wait()
            if failure != 'send':
                assert not withdrawing.done(), 'Withdrawal must wait until the actual send settles'
            if failure == 'cancel':
                sending.cancel()
            expected_error = {'send': OSError, 'timeout': TimeoutError, 'cancel': asyncio.CancelledError}[failure]
            if kind != 'json' and failure in {'send', 'timeout'}:
                expected_error = ClientDisconnect  # Starlette translates ASGI send failures.
            with pytest.raises(expected_error):
                await sending
            await withdrawing
        assert not any(b'content_url' in message.get('body', b'') for message in sent)
        assert not observed and not response.delivered
        assert cleaned == [True] and not publisher.active
    execute(scenario())
