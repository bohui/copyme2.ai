"""Deterministic ASGI barriers for governed queued publication; no database."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json

import pytest

from apps.api.lifetime_memory_publication import PublicationUnavailable
from apps.api.lifetime_memory_transport import (
    GovernedJSONResponse, GovernedStreamingResponse, governed_turn_events,
)


FENCE = {
    'identity': {
        'owner_id': '00000000-0000-4000-8000-000000000001',
        'conversation_id': '00000000-0000-4000-8000-000000000002',
        'project_id': 'memoir-test',
    },
    'policy_epoch': 1, 'source_revision': 1, 'execution_generation': 1,
    'phase_revision': 0, 'preference_revision': 0,
    'lease_token': '00000000-0000-4000-8000-000000000003',
}
SCOPE = {'type': 'http', 'asgi': {'spec_version': '2.4'}}


class Publisher:
    def __init__(self, *, timeout=1):
        self.current = 1
        self.lock = asyncio.Lock()
        self.active = False
        self.send_timeout = timeout
        self.fences = []
        self.entered = asyncio.Event()

    @asynccontextmanager
    async def guard(self, fence):
        async with self.lock:
            if fence['execution_generation'] != self.current:
                raise PublicationUnavailable('stale lifetime fence')
            self.fences.append(deepcopy(fence))
            self.active = True
            self.entered.set()
            try:
                async with asyncio.timeout(self.send_timeout):
                    yield
            finally:
                self.active = False

    async def correct(self):
        async with self.lock:
            self.current += 1


async def no_disconnect():
    await asyncio.Event().wait()


def body_event(message):
    if message['type'] == 'http.response.body' and message.get('body'):
        return json.loads(message['body'])
    return None


def execute(coroutine):
    async def bounded():
        async with asyncio.timeout(3):
            return await coroutine
    return asyncio.run(bounded())


def test_personal_bodies_sent_under_guard_and_cleanup_after_final_send():
    async def scenario():
        publisher = Publisher()
        events = []
        state = {'cleaned': False, 'final_sent': False}

        async def run(emit):
            emit.set_fence(FENCE)
            await emit('Hello')
            await emit.event({'type': 'conversation_saved', 'data': {'reply': 'Hello'}})
            return {'reply': 'Hello'}

        async def send(message):
            assert not state['cleaned'], 'lease must remain alive through actual send'
            event = body_event(message)
            if event:
                events.append(event)
                assert publisher.active == (event['type'] != 'started')
            if message['type'] == 'http.response.body' and not message['more_body']:
                state['final_sent'] = True

        async def cleanup():
            assert not publisher.active
            assert state['final_sent']
            state['cleaned'] = True

        stream = governed_turn_events(run, cleanup=cleanup)
        await GovernedStreamingResponse(stream, publisher=publisher)(SCOPE, no_disconnect, send)
        assert state['cleaned']
        assert [event['type'] for event in events] == ['started', 'text_delta', 'conversation_saved', 'result']
        assert len(publisher.fences) == 3
    execute(scenario())


def test_queued_cancelled_revision_never_reappears_after_replacement():
    async def scenario():
        publisher=Publisher();draft=Publisher();events=[];queued=asyncio.Event()
        async def run(emit):
            emit.set_fence(FENCE)
            await emit.begin_revision(draft=True)
            await emit('Cancelled text.')
            await emit.begin_revision(draft=False)
            await emit('Replacement.')
            queued.set()
            return {'reply':'Replacement.'}
        async def send(message):
            event=body_event(message)
            if event:
                events.append(event)
                if event['type']=='started': await queued.wait()
        stream=governed_turn_events(run)
        await GovernedStreamingResponse(stream,publisher=publisher,draft_publisher=draft)(SCOPE,no_disconnect,send)
        assert [e.get('text') for e in events if e['type']=='text_delta']==['Replacement.']
        assert [e['data']['revision'] for e in events if e['type']=='reply_revision']==[1]
        assert not draft.fences
    execute(scenario())


def test_policy_rejection_of_a_queued_draft_does_not_block_its_reset_or_final_reply():
    from apps.api.lifetime_memory_policy import PolicyUnavailable
    class RejectedDraft(Publisher):
        @asynccontextmanager
        async def guard(self,fence):
            raise PolicyUnavailable()
            yield
    async def scenario():
        publisher=Publisher();events=[]
        async def run(emit):
            emit.set_fence(FENCE)
            await emit.begin_revision(draft=True)
            await emit('Now restricted.')
            await emit.flush()
            await emit.begin_revision(draft=False)
            await emit('Replacement.')
            return {'reply':'Replacement.'}
        async def send(message):
            if event:=body_event(message):events.append(event)
        stream=governed_turn_events(run)
        await GovernedStreamingResponse(stream,publisher=publisher,draft_publisher=RejectedDraft())(SCOPE,no_disconnect,send)
        assert not any(e['type']=='error' for e in events)
        assert [e.get('text') for e in events if e['type']=='text_delta']==['Replacement.']
        assert events[-1]['type']=='result'
    execute(scenario())


@pytest.mark.parametrize('kind',['question_validated','reply_complete'])
def test_milestone_metadata_never_uses_the_unfenced_generic_exemption(kind):
    async def scenario():
        publisher=Publisher();events=[]
        async def run(emit):
            await emit.event({'type':kind,'data':{'has_question':True}})
            return {'reply':'Unfenced'}
        async def send(message):
            if event:=body_event(message):events.append(event)
        await GovernedStreamingResponse(governed_turn_events(run),publisher=publisher)(SCOPE,no_disconnect,send)
        assert [e['type'] for e in events]==['started','error']
        assert not publisher.fences
    execute(scenario())


def test_database_connection_timeout_ends_stream_with_retry_message(monkeypatch):
    from apps.api.lifetime_memory_publication import TransactionalPublication
    from psycopg import AsyncConnection

    async def connect(*args, **kwargs):
        await asyncio.Event().wait()
    monkeypatch.setattr(AsyncConnection, 'connect', connect)

    async def scenario():
        publisher = TransactionalPublication('synthetic',
            authenticated_owner=FENCE['identity']['owner_id'], lock_timeout=.01)
        messages = []
        cleaned = []

        async def run(emit):
            emit.set_fence(FENCE)
            await emit('private place cue')
            await emit.flush()

        async def send(message):
            messages.append(message)

        async def cleanup():
            cleaned.append(True)

        await GovernedStreamingResponse(governed_turn_events(run, cleanup),
            publisher=publisher)(SCOPE, no_disconnect, send)
        events = [body_event(message) for message in messages if body_event(message)]
        assert [event['type'] for event in events] == ['started', 'error']
        assert 'Please try again' in events[-1]['message']
        assert 'private place cue' not in str(messages)
        assert messages[-1]['more_body'] is False and cleaned == [True]

    execute(scenario())


@pytest.mark.parametrize('database_code,expected_code', [
    ('22023', '22023'), ('private-credential', 'HTTPStatusError'), (None, 'HTTPStatusError'),
])
def test_producer_failure_records_safe_stage_and_database_code(monkeypatch, database_code, expected_code):
    import httpx
    from apps.api import diagnostics, lifetime_memory_transport as transport

    records = []

    class Sink:
        def info(self, template, body):
            records.append(json.loads(body))

    def capture(logger, event, request_id, **fields):
        diagnostics.log_diagnostic(Sink(), event, request_id, **fields)

    monkeypatch.setattr(transport, 'log_diagnostic', capture, raising=False)

    async def scenario():
        events = []

        async def run(emit):
            emit.set_fence(FENCE)
            await emit.event({'type': 'progress', 'turn_id': 'diagnostic-save-1',
                'data': {'id': 'save', 'status': 'running'}})
            response = httpx.Response(400, json={'code': database_code,
                'message': 'private story and credential'},
                request=httpx.Request('POST', 'https://private.example/rpc?token=secret'))
            raise httpx.HTTPStatusError('private exception',
                request=response.request, response=response)

        async def send(message):
            if event := body_event(message):
                events.append(event)

        await GovernedStreamingResponse(governed_turn_events(run),
            publisher=Publisher())(SCOPE, no_disconnect, send)
        assert events[-1] == {'type': 'error', 'message': transport._ERROR}

    execute(scenario())
    assert records == [{'event': 'governed_turn_failed', 'request_id': 'diagnostic-save-1',
        'component': 'memoir.lifetime_memory_transport', 'status': 'failed',
        'call_type': 'save', 'failure_class': 'http_rejected',
        'error_code': expected_code, 'http_status': 400}]
    assert 'private' not in json.dumps(records)


def test_publication_failure_is_logged_without_private_exception(monkeypatch):
    from apps.api import lifetime_memory_transport as transport

    records = []
    monkeypatch.setattr(transport, 'log_diagnostic',
        lambda logger, event, request_id, **fields: records.append(fields))

    class RejectedPublisher(Publisher):
        @asynccontextmanager
        async def guard(self, fence):
            error = RuntimeError('private publication details')
            error.sqlstate = '40001'
            raise error
            yield

    async def scenario():
        events = []

        async def run(emit):
            emit.set_fence(FENCE)
            await emit('private reply')

        async def send(message):
            if event := body_event(message):
                events.append(event)

        await GovernedStreamingResponse(governed_turn_events(run),
            publisher=RejectedPublisher())(SCOPE, no_disconnect, send)
        assert [event['type'] for event in events] == ['started', 'error']

    execute(scenario())
    assert len(records) == 1
    assert records[0]['call_type'] == 'publication' and records[0]['error_code'] == '40001'
    assert 'private' not in json.dumps(records)


@pytest.mark.parametrize('kind', ['text_delta', 'conversation_saved', 'result'])
def test_queued_old_payload_is_not_blessed_by_later_fence(kind):
    async def scenario():
        publisher = Publisher()
        queued = asyncio.Event()
        messages = []
        newer = deepcopy(FENCE)
        newer['execution_generation'] = 2

        async def run(emit):
            emit.set_fence(FENCE)
            if kind == 'text_delta':
                await emit('withdrawn text')
            elif kind == 'conversation_saved':
                await emit.event({'type': kind, 'data': {'reply': 'withdrawn text'}})
            old_result = emit.snapshot_result({'reply': 'withdrawn text'})
            emit.set_fence(newer)
            publisher.current = 2
            queued.set()
            return old_result

        async def send(message):
            messages.append(message)
            event = body_event(message)
            if event and event['type'] == 'started':
                await queued.wait()

        response = GovernedStreamingResponse(governed_turn_events(run), publisher=publisher)
        with pytest.raises(PublicationUnavailable, match='stale'):
            await response(SCOPE, no_disconnect, send)
        assert 'withdrawn text' not in str(messages)
        assert not publisher.active
    execute(scenario())


def test_event_and_fence_are_frozen_when_enqueued():
    async def scenario():
        publisher = Publisher()
        queued = asyncio.Event()
        events = []
        source_fence = deepcopy(FENCE)
        event = {'type': 'conversation_saved', 'data': {'reply': 'original'}}

        async def run(emit):
            emit.set_fence(source_fence)
            await emit.event(event)
            event['data']['reply'] = 'mutated secret'
            source_fence['execution_generation'] = 999
            source_fence['identity']['project_id'] = 'other'
            result = emit.snapshot_result({'reply': 'original'})
            queued.set()
            return result

        async def send(message):
            event = body_event(message)
            if event:
                events.append(event)
                if event['type'] == 'started':
                    await queued.wait()

        await GovernedStreamingResponse(governed_turn_events(run), publisher=publisher)(SCOPE, no_disconnect, send)
        assert events[1]['data']['reply'] == 'original'
        assert all(fence['identity']['project_id'] == 'memoir-test' for fence in publisher.fences)
    execute(scenario())


def test_flush_waits_for_send_and_allows_mutation_without_lock_deadlock():
    async def scenario():
        publisher = Publisher()
        entered_send = asyncio.Event()
        release_send = asyncio.Event()
        flush_requested = asyncio.Event()
        corrected = asyncio.Event()
        events = []

        async def run(emit):
            emit.set_fence(FENCE)
            await emit('old output')
            flush_requested.set()
            await emit.flush()
            assert not publisher.active
            await publisher.correct()
            corrected.set()
            newer = deepcopy(FENCE)
            newer['execution_generation'] = 2
            emit.set_fence(newer)
            return {'reply': 'new output'}

        async def send(message):
            event = body_event(message)
            if event:
                events.append(event)
                if event['type'] == 'text_delta':
                    entered_send.set()
                    await release_send.wait()

        response = asyncio.create_task(GovernedStreamingResponse(governed_turn_events(run), publisher=publisher)(SCOPE, no_disconnect, send))
        await entered_send.wait()
        await flush_requested.wait()
        assert not corrected.is_set()
        release_send.set()
        await response
        assert corrected.is_set()
        assert [fence['execution_generation'] for fence in publisher.fences] == [1, 2]
    execute(scenario())


def test_correction_waits_for_actual_send_and_stale_remaining_output_is_blocked():
    async def scenario():
        publisher = Publisher()
        send_entered = asyncio.Event()
        send_release = asyncio.Event()
        correction_started = asyncio.Event()
        messages = []

        async def run(emit):
            emit.set_fence(FENCE)
            await emit('first')
            await emit('stale second')
            return {'reply': 'stale result'}

        async def send(message):
            event = body_event(message)
            if event and event['type'] == 'text_delta':
                send_entered.set()
                await send_release.wait()
            messages.append(message)

        async def correct():
            correction_started.set()
            await publisher.correct()

        response = asyncio.create_task(GovernedStreamingResponse(governed_turn_events(run), publisher=publisher)(SCOPE, no_disconnect, send))
        await send_entered.wait()
        correction = asyncio.create_task(correct())
        await correction_started.wait()
        assert not correction.done()
        send_release.set()
        with pytest.raises(PublicationUnavailable):
            await response
        await correction
        assert 'first' in str(messages)
        assert 'stale second' not in str(messages)
        assert 'stale result' not in str(messages)
    execute(scenario())


@pytest.mark.parametrize('mode', ['cancel', 'disconnect', 'timeout'])
def test_send_failure_releases_guard_cancels_producer_and_cleans_up(mode):
    async def scenario():
        publisher = Publisher(timeout=.02 if mode == 'timeout' else 1)
        entered = asyncio.Event()
        producer_stopped = asyncio.Event()
        cleaned = asyncio.Event()

        async def run(emit):
            try:
                emit.set_fence(FENCE)
                await emit('private')
                await asyncio.Event().wait()
            finally:
                producer_stopped.set()

        async def send(message):
            event = body_event(message)
            if event and event['type'] == 'text_delta':
                entered.set()
                if mode == 'disconnect':
                    raise OSError('disconnected')
                await asyncio.Event().wait()

        async def cleanup():
            assert not publisher.active
            assert producer_stopped.is_set()
            cleaned.set()

        task = asyncio.create_task(GovernedStreamingResponse(governed_turn_events(run, cleanup=cleanup), publisher=publisher)(SCOPE, no_disconnect, send))
        await entered.wait()
        if mode == 'cancel':
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(Exception):
                await task
        assert cleaned.is_set() and not publisher.active
        await publisher.correct()
    execute(scenario())


def test_legacy_asgi_disconnect_settles_producer_and_cleanup():
    async def scenario():
        publisher = Publisher()
        started = asyncio.Event()
        producer_stopped = asyncio.Event()
        cleanups = []

        async def run(emit):
            try:
                emit.set_fence(FENCE)
                started.set()
                await asyncio.Event().wait()
            finally:
                producer_stopped.set()

        async def receive():
            await started.wait()
            return {'type': 'http.disconnect'}

        async def send(message):
            pass

        async def cleanup():
            cleanups.append(True)

        await GovernedStreamingResponse(governed_turn_events(run, cleanup=cleanup), publisher=publisher)({'type': 'http', 'asgi': {'spec_version': '2.0'}}, receive, send)
        assert producer_stopped.is_set() and cleanups == [True]
    execute(scenario())


@pytest.mark.parametrize('event', [
    {'type': 'conversation_saved', 'data': {'reply': 'private'}},
    {'type': 'progress', 'data': {'id': 'reply', 'status': 'running', 'detail': 'private'}},
    {'type': 'started', 'secret': 'private'},
    {'type': 'error', 'message': 'private'},
])
def test_personal_events_without_fence_rejected_before_enqueue(event):
    async def scenario():
        publisher = Publisher()
        captured = []

        async def run(emit):
            with pytest.raises(PublicationUnavailable):
                await emit.event(event)
            with pytest.raises(PublicationUnavailable):
                await emit('private')
            with pytest.raises(PublicationUnavailable):
                emit.snapshot_result({'reply': 'private'})
            raise RuntimeError('private credentials')

        async def send(message):
            value = body_event(message)
            if value:
                captured.append(value)

        await GovernedStreamingResponse(governed_turn_events(run), publisher=publisher)(SCOPE, no_disconnect, send)
        assert [item['type'] for item in captured] == ['started', 'error']
        assert 'private' not in str(captured)
        assert publisher.fences == []
    execute(scenario())


def test_generic_events_are_allowed_without_a_fence():
    async def scenario():
        publisher = Publisher()
        captured = []
        generic = [
            {'type': 'started'}, {'type': 'heartbeat'},
            {'type': 'progress', 'data': {'id': 'context', 'status': 'running'}},
        ]

        async def run(emit):
            for event in generic:
                await emit.event(event)
            emit.set_fence(FENCE)
            return {'reply': 'done'}

        async def send(message):
            event = body_event(message)
            if event:
                captured.append(event)
                if event['type'] != 'result':
                    assert not publisher.active

        await GovernedStreamingResponse(governed_turn_events(run), publisher=publisher)(SCOPE, no_disconnect, send)
        assert captured[1:4] == generic
        assert len(publisher.fences) == 1
    execute(scenario())


def test_queue_backpressure_is_bounded_and_cancellation_unblocks_put():
    async def scenario():
        publisher = Publisher()
        saturated = asyncio.Event()
        producer_stopped = asyncio.Event()
        enqueued = []

        async def run(emit):
            try:
                emit.set_fence(FENCE)
                for index in range(65):
                    if index == 64:
                        saturated.set()
                    await emit(str(index))
                    enqueued.append(index)
            finally:
                producer_stopped.set()

        async def send(message):
            if (body_event(message) or {}).get('type') == 'started':
                await asyncio.Event().wait()

        response = asyncio.create_task(GovernedStreamingResponse(governed_turn_events(run), publisher=publisher)(SCOPE, no_disconnect, send))
        await saturated.wait()
        assert len(enqueued) == 64
        response.cancel()
        with pytest.raises(asyncio.CancelledError):
            await response
        assert producer_stopped.is_set()
    execute(scenario())


def test_json_snapshot_is_immutable_guarded_and_cleanup_after_completed_send():
    async def scenario():
        publisher = Publisher()
        source_fence = deepcopy(FENCE)
        content = {'reply': 'original'}
        sent = []
        cleanup_count = []

        async def cleanup():
            assert not publisher.active and len(sent) == 2
            cleanup_count.append(True)

        response = GovernedJSONResponse(content, publisher=publisher, fence=source_fence, cleanup=cleanup)
        content['reply'] = 'mutated'
        source_fence['execution_generation'] = 2

        async def send(message):
            if message['type'] == 'http.response.body':
                assert publisher.active
            assert not cleanup_count
            sent.append(message)

        await response(SCOPE, no_disconnect, send)
        assert json.loads(sent[-1]['body']) == {'reply': 'original'}
        assert cleanup_count == [True]
    execute(scenario())


def test_json_rejects_stale_snapshot_and_still_releases_caller_cleanup():
    async def scenario():
        publisher = Publisher()
        cleaned = []
        sent = []

        async def cleanup():
            cleaned.append(True)

        response = GovernedJSONResponse({'reply': 'withdrawn'}, publisher=publisher, fence=FENCE, cleanup=cleanup)
        publisher.current = 2

        async def send(message):
            sent.append(message)

        with pytest.raises(PublicationUnavailable):
            await response(SCOPE, no_disconnect, send)
        assert not any(message['type'] == 'http.response.body' for message in sent)
        assert cleaned == [True]
    execute(scenario())


def test_plain_result_snapshot_precedes_blocked_queue_and_later_setter():
    async def scenario():
        publisher = Publisher()
        result_returning = asyncio.Event()
        newer = deepcopy(FENCE)
        newer['execution_generation'] = 2
        stream = None

        async def run(emit):
            emit.set_fence(FENCE)
            for index in range(64):
                await emit(str(index))
            result_returning.set()
            return {'reply': 'old result'}

        async def send(message):
            if (body_event(message) or {}).get('type') == 'started':
                await result_returning.wait()
                # The producer has returned; result queueing is blocked behind
                # the 64 entries. A new setter cannot relabel that result.
                assert stream._queue.qsize() == 64
                stream.emitter.set_fence(newer)

        stream = governed_turn_events(run)
        await GovernedStreamingResponse(stream, publisher=publisher)(SCOPE, no_disconnect, send)
        assert len(publisher.fences) == 65
        assert {fence['execution_generation'] for fence in publisher.fences} == {1}
    execute(scenario())


def test_stale_guard_cancels_producer_waiting_at_flush():
    async def scenario():
        publisher = Publisher()
        flushing = asyncio.Event()
        stopped = asyncio.Event()
        cleaned = []

        async def run(emit):
            try:
                emit.set_fence(FENCE)
                await emit('stale')
                flushing.set()
                await emit.flush()
                pytest.fail('failed send must not permit plan mutation')
            finally:
                stopped.set()

        async def send(message):
            if (body_event(message) or {}).get('type') == 'started':
                await flushing.wait()
                publisher.current = 2

        async def cleanup():
            cleaned.append(True)

        with pytest.raises(PublicationUnavailable):
            await GovernedStreamingResponse(governed_turn_events(run, cleanup), publisher=publisher)(SCOPE, no_disconnect, send)
        assert stopped.is_set() and cleaned == [True]
    execute(scenario())


def test_final_empty_send_finishes_before_cleanup_releases_lease():
    async def scenario():
        publisher = Publisher()
        final_entered = asyncio.Event()
        release_final = asyncio.Event()
        cleaned = asyncio.Event()

        async def run(emit):
            emit.set_fence(FENCE)
            return {'reply': 'done'}

        async def send(message):
            if message['type'] == 'http.response.body' and not message['more_body']:
                final_entered.set()
                await release_final.wait()

        async def cleanup():
            cleaned.set()

        response = asyncio.create_task(GovernedStreamingResponse(governed_turn_events(run, cleanup), publisher=publisher)(SCOPE, no_disconnect, send))
        await final_entered.wait()
        assert not cleaned.is_set()
        release_final.set()
        await response
        assert cleaned.is_set()
    execute(scenario())


def test_repeated_cancellation_waits_for_single_cleanup():
    async def scenario():
        publisher = Publisher()
        entered = asyncio.Event()
        cleanup_entered = asyncio.Event()
        cleanup_release = asyncio.Event()
        cleanups = []

        async def run(emit):
            emit.set_fence(FENCE)
            await emit('private')
            await asyncio.Event().wait()

        async def send(message):
            if (body_event(message) or {}).get('type') == 'text_delta':
                entered.set()
                await asyncio.Event().wait()

        async def cleanup():
            cleanup_entered.set()
            await cleanup_release.wait()
            cleanups.append(True)

        response = asyncio.create_task(GovernedStreamingResponse(governed_turn_events(run, cleanup), publisher=publisher)(SCOPE, no_disconnect, send))
        await entered.wait()
        response.cancel()
        await cleanup_entered.wait()
        response.cancel()
        assert not response.done()
        cleanup_release.set()
        with pytest.raises(asyncio.CancelledError):
            await response
        assert cleanups == [True] and not publisher.active
    execute(scenario())


def test_json_blocked_send_holds_correction_and_cancellation_releases_cleanup():
    async def scenario():
        publisher = Publisher()
        entered = asyncio.Event()
        correction_started = asyncio.Event()
        cleaned = []

        async def send(message):
            if message['type'] == 'http.response.body':
                entered.set()
                await asyncio.Event().wait()

        async def cleanup():
            assert not publisher.active
            cleaned.append(True)

        async def correct():
            correction_started.set()
            await publisher.correct()

        response = asyncio.create_task(GovernedJSONResponse({'reply': 'private'}, publisher=publisher, fence=FENCE, cleanup=cleanup)(SCOPE, no_disconnect, send))
        await entered.wait()
        correction = asyncio.create_task(correct())
        await correction_started.wait()
        assert not correction.done()
        response.cancel()
        with pytest.raises(asyncio.CancelledError):
            await response
        await correction
        assert cleaned == [True]
    execute(scenario())
