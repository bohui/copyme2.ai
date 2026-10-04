import asyncio
import json

import pytest

from apps.api.turn_stream import VisibleText, turn_events
from apps.api.codex_agent import CodexConnection
from apps.api.codex_runtime import CodexRuntime
from apps.api.agent_lock import AgentTurnBusyError
from apps.api.trajectory_evaluation import TrajectoryRecorder
import httpx


def test_markers_hidden_at_every_chunk_boundary():
    text = 'Hello 承德! [[MEMORY_SPARK_PROFILE]]{"name":"private"}[[/MEMORY_SPARK_PROFILE]]'
    for boundary in range(len(text) + 1):
        visible = VisibleText()
        result = visible.feed(text[:boundary]) + visible.feed(text[boundary:]) + visible.feed('', final=True)
        assert result == 'Hello 承德! '
    visible = VisibleText()
    assert visible.feed('Hello [[MEMORY_S', final=True) == 'Hello '


def test_legacy_profile_comments_hidden_at_every_chunk_boundary():
    text = 'Hello 慧博! <!-- profile: {"who":"慧博","when":"1983年4月"} -->'
    for boundary in range(len(text) + 1):
        visible = VisibleText()
        result = visible.feed(text[:boundary]) + visible.feed(text[boundary:]) + visible.feed('', final=True)
        assert result == 'Hello 慧博! '


def test_text_arrives_before_persistence_and_result():
    async def run():
        saved = asyncio.Event()
        async def turn(emit):
            await emit('Hello')
            await saved.wait()
            return {'reply': 'Hello', 'profile_updates': {'name': 'Avery'}}
        stream = turn_events(turn)
        assert json.loads(await anext(stream))['type'] == 'started'
        assert json.loads(await asyncio.wait_for(anext(stream), 1)) == {'type': 'text_delta', 'text': 'Hello'}
        assert not saved.is_set()
        saved.set()
        assert json.loads(await anext(stream))['type'] == 'result'
        await stream.aclose()
    asyncio.run(run())


def test_saved_reply_event_can_precede_workspace_result():
    async def run():
        workspace_done = asyncio.Event()

        async def turn(emit):
            await emit('Hello')
            await emit.event({'type': 'reply_complete', 'data': {'reply': 'Hello'}})
            await emit.event({'type': 'conversation_saved', 'data': {'reply': 'Hello'}})
            await workspace_done.wait()
            await emit.event({'type': 'workspace_update', 'data': {'workspace_status': 'ready'}})
            return {'reply': 'Hello', 'workspace_status': 'ready'}

        stream = turn_events(turn)
        assert json.loads(await anext(stream))['type'] == 'started'
        assert json.loads(await anext(stream)) == {'type': 'text_delta', 'text': 'Hello'}
        assert json.loads(await anext(stream))['type'] == 'reply_complete'
        assert json.loads(await anext(stream))['type'] == 'conversation_saved'
        workspace_done.set()
        assert json.loads(await anext(stream))['type'] == 'workspace_update'
        assert json.loads(await anext(stream))['type'] == 'result'
        await stream.aclose()

    asyncio.run(run())


def test_disconnect_cancels_turn_and_closes_storage():
    async def run():
        cancelled = asyncio.Event()
        closed = asyncio.Event()
        async def turn(emit):
            try:
                await emit('Hello')
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        async def cleanup():
            closed.set()
        stream = turn_events(turn, cleanup)
        await anext(stream)
        await anext(stream)
        await stream.aclose()
        assert cancelled.is_set() and closed.is_set()
    asyncio.run(run())


def test_disconnect_after_conversation_saved_allows_workspace_to_settle():
    async def run():
        released = asyncio.Event()
        settled = asyncio.Event()

        async def turn(emit):
            await emit.event({'type': 'conversation_saved', 'data': {'reply': 'Hello'}})
            await released.wait()
            settled.set()
            return {'reply': 'Hello'}

        stream = turn_events(turn)
        await anext(stream)
        assert json.loads(await anext(stream))['type'] == 'conversation_saved'
        released.set()
        await stream.aclose()
        assert settled.is_set()

    asyncio.run(run())


def test_failure_after_partial_text_is_not_a_success():
    async def run():
        async def turn(emit):
            await emit('Hello')
            raise RuntimeError('private credential')
        events = [json.loads(line) async for line in turn_events(turn)]
        assert [e['type'] for e in events] == ['started', 'text_delta', 'error']
        assert 'private credential' not in str(events)
    asyncio.run(run())


def test_failure_stream_preserves_a_redacted_partial_trajectory_receipt():
    async def run():
        async def turn(emit):
            error = RuntimeError('worker failure')
            error.trajectory = {
                'schema_version': 'memoir-trajectory/1',
                'steps': [{'step_id': 'step-0001', 'action': 'worker.step'}],
                'final': {'status': 'failed', 'response': ''},
            }
            raise error

        events = [json.loads(line) async for line in turn_events(turn)]
        assert events[-1]['type'] == 'error'
        assert events[-1]['trajectory']['steps'][0]['step_id'] == 'step-0001'
        assert 'worker failure' not in str(events)

    asyncio.run(run())


def test_worker_stream_failure_preserves_outer_trace_lineage():
    async def run():
        partial = {
            'schema_version': 'memoir-trajectory/1',
            'steps': [{
                'step_id': 'worker-step-1',
                'sequence': 1,
                'phase': 'codex.turn',
                'action': 'tool.call',
                'tool_name': 'memory.search',
                'observation_id': 'worker-observation-1',
                'trace_id': 'worker-trace-1',
            }],
            'final': {'status': 'failed', 'response': None},
        }

        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield (json.dumps({'type': 'error', 'trajectory': partial}) + '\n').encode()

        def handle(request):
            return httpx.Response(200, stream=Body())

        outer = TrajectoryRecorder({'run_id': 'run-1', 'case_id': 'case-1'})
        runtime = CodexRuntime(
            worker_url='http://worker',
            worker_secret='secret',
            worker_transport=httpx.MockTransport(handle),
        )
        with pytest.raises(RuntimeError) as caught:
            await runtime._worker_turn(
                user_id='test', prior=None, memories=[], profile={}, place_journey={},
                family_enabled=False, family_context={}, project_id=None, text='Hi',
                language='en-AU', on_event=lambda _event: asyncio.sleep(0),
                trajectory=outer,
            )

        assert caught.value.trajectory['steps'][0]['observation_id'] == 'worker-observation-1'
        worker_step = next(step for step in outer.steps if step.get('source') == 'codex-worker-failure')
        assert worker_step['observation_id'] == 'worker-observation-1'
        assert worker_step['trace_id'] == 'worker-trace-1'
        assert outer.final['status'] == 'failed'

    asyncio.run(run())


def test_worker_nonstream_failure_preserves_outer_trace_lineage():
    async def run():
        partial = {
            'schema_version': 'memoir-trajectory/1',
            'steps': [{
                'step_id': 'worker-step-2',
                'sequence': 1,
                'phase': 'codex.turn',
                'action': 'tool.call',
                'tool_name': 'memory.search',
                'observation_id': 'worker-observation-2',
                'trace_id': 'worker-trace-2',
            }],
            'final': {'status': 'failed', 'response': None},
        }

        def handle(request):
            return httpx.Response(502, json={
                'detail': 'Codex worker failed',
                'trajectory': partial,
            })

        outer = TrajectoryRecorder({'run_id': 'run-2', 'case_id': 'case-2'})
        runtime = CodexRuntime(
            worker_url='http://worker',
            worker_secret='secret',
            worker_transport=httpx.MockTransport(handle),
        )
        with pytest.raises(RuntimeError) as caught:
            await runtime._worker_turn(
                user_id='test', prior=None, memories=[], profile={}, place_journey={},
                family_enabled=False, family_context={}, project_id=None, text='Hi',
                language='en-AU', trajectory=outer,
            )

        assert caught.value.trajectory['steps'][0]['observation_id'] == 'worker-observation-2'
        worker_step = next(step for step in outer.steps if step.get('source') == 'codex-worker-failure')
        assert worker_step['observation_id'] == 'worker-observation-2'
        assert worker_step['trace_id'] == 'worker-trace-2'
        assert outer.final['status'] == 'failed'
        assert 'worker failure' not in str(caught.value)

    asyncio.run(run())


@pytest.mark.parametrize('streaming', [False, True])
@pytest.mark.parametrize('status_code', [409, 502])
def test_worker_http_status_errors_map_after_reading_streamed_error_body(status_code, streaming):
    async def run():
        partial = {
            'schema_version': 'memoir-trajectory/1',
            'steps': [{
                'step_id': 'worker-http-step',
                'sequence': 1,
                'phase': 'codex.turn',
                'action': 'tool.call',
                'tool_name': 'memory.search',
                'observation_id': 'worker-http-observation',
                'trace_id': 'worker-http-trace',
            }],
            'final': {'status': 'failed', 'response': None},
        }
        body = json.dumps({
            'detail': 'private credential must not escape',
            'trajectory': partial,
        }).encode()

        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield body

        def handle(request):
            if streaming:
                return httpx.Response(status_code, stream=Body(), request=request)
            return httpx.Response(status_code, content=body, request=request)

        outer = TrajectoryRecorder({'run_id': 'run-http', 'case_id': 'case-http'})
        runtime = CodexRuntime(
            worker_url='http://worker',
            worker_secret='secret',
            worker_transport=httpx.MockTransport(handle),
        )
        kwargs = {
            'user_id': 'test', 'prior': None, 'memories': [], 'profile': {},
            'place_journey': {}, 'family_enabled': False, 'family_context': {},
            'project_id': None, 'text': 'Hi', 'language': 'en-AU',
            'trajectory': outer,
        }
        if streaming:
            async def emit(_event):
                return None
            kwargs['on_event'] = emit

        expected = AgentTurnBusyError if status_code == 409 else RuntimeError
        with pytest.raises(expected) as caught:
            await runtime._worker_turn(**kwargs)

        if status_code == 409:
            assert isinstance(caught.value, AgentTurnBusyError)
        else:
            assert str(caught.value) == 'Codex worker rejected the turn: HTTP 502'
        assert caught.value.trajectory['steps'][0]['observation_id'] == 'worker-http-observation'
        assert outer.final['status'] == 'failed'
        assert 'private credential' not in str(caught.value)
        assert 'ResponseNotRead' not in str(caught.value)

    asyncio.run(run())


@pytest.mark.parametrize('streaming', [False, True])
@pytest.mark.parametrize('body', [
    b'not-json private credential',
    b'{"detail":"private credential ' + (b'x' * 131072) + b'"}',
])
def test_worker_malformed_or_oversized_error_body_still_maps_status(streaming, body):
    async def run():
        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield body

        def handle(request):
            if streaming:
                return httpx.Response(502, stream=Body(), request=request)
            return httpx.Response(502, content=body, request=request)

        runtime = CodexRuntime(
            worker_url='http://worker',
            worker_secret='secret',
            worker_transport=httpx.MockTransport(handle),
        )
        kwargs = {
            'user_id': 'test', 'prior': None, 'memories': [], 'profile': {},
            'place_journey': {}, 'family_enabled': False, 'family_context': {},
            'project_id': None, 'text': 'Hi', 'language': 'en-AU',
        }
        if streaming:
            async def emit(_event):
                return None
            kwargs['on_event'] = emit
        with pytest.raises(RuntimeError) as caught:
            await runtime._worker_turn(**kwargs)

        assert str(caught.value) == 'Codex worker rejected the turn: HTTP 502'
        assert 'private credential' not in str(caught.value)
        assert 'ResponseNotRead' not in str(caught.value)

    asyncio.run(run())


def test_codex_deltas_forwarded_before_turn_completed():
    async def run():
        connection = CodexConnection([], '.')
        deltas = []
        async def request(method, params):
            connection.events.extend([
                {'method': 'item/agentMessage/delta', 'params': {'threadId': 't', 'itemId': 'm', 'delta': 'Hello'}},
                {'method': 'item/completed', 'params': {'threadId': 't', 'item': {'id': 'm', 'type': 'agentMessage', 'text': 'Hello'}}},
            ])
            return {'turn': {'id': 'turn'}}
        async def receive():
            assert deltas == ['Hello']
            return {'method': 'turn/completed', 'params': {'threadId': 't', 'turn': {'id': 'turn', 'status': 'completed'}}}
        async def emit(text):
            deltas.append(text)
        connection.request = request
        connection.receive = receive
        assert await connection.turn('t', 'Hi', on_delta=emit) == 'Hello'
        assert deltas == ['Hello']
    asyncio.run(run())


def test_worker_http_stream_forwards_delta_before_final_artifacts(monkeypatch):
    async def run():
        chunks = []
        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'{"type":"text_delta","text":"Hello"}\n'
                assert chunks == ['Hello']
                yield b'{"type":"result","data":{"thread_id":"t","reply":"Hello","artifacts":[]}}\n'
        def handle(request):
            assert request.headers['accept'] == 'application/x-ndjson'
            return httpx.Response(200, stream=Body())
        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        monkeypatch.setattr('apps.api.codex_runtime.httpx.AsyncClient', lambda **kwargs: client)
        async def emit(text):
            chunks.append(text)
        runtime = CodexRuntime(worker_url='http://worker', worker_secret='test-secret')
        result = await runtime._worker_turn(user_id='test', prior=None, memories=[], profile={},
            place_journey={}, family_enabled=False, family_context={}, project_id=None,
            text='Hi', language='en-AU', on_delta=emit)
        assert result['reply'] == 'Hello'
    asyncio.run(run())


def test_codex_activity_is_scoped_and_excludes_private_content():
    from apps.api.turn_progress import TurnProgress

    async def run():
        connection = CodexConnection([], '.')
        events = []
        async def emit(event):
            events.append(event)
        progress = TurnProgress(emit, 'round', 'project', 'en-AU')
        async def request(method, params):
            for thread, turn, kind, identity in [('other', 'turn', 'mcpToolCall', 'other'),
                    ('t', 'old', 'mcpToolCall', 'old'), ('t', 'turn', 'reasoning', 'private'),
                    ('t', 'turn', 'mcpToolCall', 'call')]:
                for method in ('item/started', 'item/completed'):
                    connection.events.append({'method': method, 'params': {
                        'threadId': thread, 'turnId': turn, 'item': {
                            'id': identity, 'type': kind, 'tool': 'memory.search',
                            'arguments': 'secret input', 'result': 'secret output', 'text': 'private reasoning'}}})
            connection.events.append({'method': 'turn/completed', 'params': {
                'threadId': 't', 'turn': {'id': 'turn', 'status': 'completed'}}})
            return {'turn': {'id': 'turn'}}
        connection.request = request
        await connection.turn('t', 'Hi', on_event=progress.harness_event)
        assert [event['data']['status'] for event in events] == ['running', 'completed']
        assert all(event['data']['id'] == 'codex:t:turn:call' for event in events)
        assert progress.steps[0]['detail'] == 'memory.search · Completed'
        assert 'secret' not in str(events) and 'private reasoning' not in str(events)
    asyncio.run(run())


def test_worker_stream_forwards_harness_activity_without_text_callback():
    async def run():
        events = []
        activity = {'type': 'codex_activity', 'data': {
            'id': 'call', 'label': 'memory.search', 'status': 'completed'}}
        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield (json.dumps(activity) + '\n').encode()
                yield b'{"type":"result","data":{"thread_id":"t","reply":"Hello","artifacts":[]}}\n'
        def handle(request):
            return httpx.Response(200, stream=Body())
        async def emit(event):
            events.append(event)
        runtime = CodexRuntime(worker_url='http://worker', worker_secret='secret',
                               worker_transport=httpx.MockTransport(handle))
        result = await runtime._worker_turn(user_id='test', prior=None, memories=[], profile={},
            place_journey={}, family_enabled=False, family_context={}, project_id=None,
            text='Hi', language='en-AU', on_event=emit)
        await result['_artifact_task']
        assert events == [activity]
    asyncio.run(run())
