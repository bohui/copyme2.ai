"""Synthetic streams and app-server events only; no native/model calls."""
import asyncio
from contextvars import ContextVar
from copy import deepcopy
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from scripts.issue14_subscription_transport import SubscriptionLimits, SubscriptionRun, SubscriptionTransport, SubscriptionStopped

PRIVATE = 'PRIVATE_PROMPT_REPLY_REASONING_ARGUMENT_OUTPUT_HEADER'
TERMINAL = b'event: response.completed\r\ndata: {"type":"response.completed","response":{"private":"' + PRIVATE.encode() + b'"}}\r\n\r\n'


@pytest.mark.parametrize('mode,phase', [('headers', 'awaiting_headers'), ('body', 'reading_body'),
    ('terminal', 'awaiting_eof'), ('healthy', 'eof')])
def test_response_phases_survive_cancellation_with_no_forwarding_or_extra_send(tmp_path, mode, phase):
    async def scenario():
        run = SubscriptionRun.create(reservation_root=tmp_path, run_id=str(uuid4()),
            source_revision='a' * 40, limits=SubscriptionLimits(4, 5))
        transport = SubscriptionTransport.controlled(run=run, endpoint='http://127.0.0.1:12345/v1/responses')
        reached = asyncio.Event(); released = asyncio.Event(); closed = []
        calls = []
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                if mode == 'body':
                    yield b': private comment\n\n'
                elif mode in ('terminal', 'healthy'):
                    for byte in TERMINAL:  # Every CR/LF/JSON field can split across chunks.
                        yield bytes([byte])
                if mode != 'healthy':
                    reached.set()
                    await released.wait()
            async def aclose(self):
                closed.append(True)
        class Wire(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                calls.append(True)
                if mode == 'headers':
                    reached.set()
                    await released.wait()
                return httpx.Response(200, headers={'content-type':'text/event-stream', 'private':PRIVATE}, stream=Stream())
        await transport._wire.aclose(); transport._wire = Wire()
        try:
            async with httpx.AsyncClient(transport=transport) as client:
                task = asyncio.create_task(client.post(transport.endpoint, json={'input':PRIVATE},
                    headers={'authorization':'Bearer synthetic-token'}))
                if mode == 'healthy':
                    response = await task
                    assert response.content == TERMINAL
                else:
                    await reached.wait()
                    assert not task.done()  # Even terminal SSE is withheld until HTTP EOF.
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                    with pytest.raises(SubscriptionStopped):
                        await client.post(transport.endpoint, json={}, headers={'authorization':'Bearer synthetic-token'})
                snapshot = run.snapshot()
                observation = snapshot['attempts'][0]['response_observation']
                assert observation['phase'] == phase
                assert observation['failure_phase'] == (None if mode == 'healthy' else phase)
                assert observation['failure_class'] == (None if mode == 'healthy' else 'cancelled')
                assert observation['headers_received_at_monotonic'] is None if mode == 'headers' else observation['http_status'] == 200
                assert observation['first_byte_at_monotonic'] is None if mode == 'headers' else observation['first_byte_at_monotonic'] <= observation['last_byte_at_monotonic']
                assert observation['terminal_sse_category'] == ('response.completed' if mode in ('terminal','healthy') else None)
                assert (observation['eof_at_monotonic'] is not None) == (mode == 'healthy')
                assert observation['cleanup_status'] == ('not_received' if mode == 'headers' else 'closed')
                assert snapshot['client_requests_started'] == len(calls) == 1
                assert snapshot['completed_http_responses'] == (1 if mode == 'healthy' else 0)
                assert snapshot['unresolved_requests'] == (0 if mode == 'healthy' else 1)
                assert PRIVATE not in json.dumps(snapshot)
        finally:
            await transport.aclose(); run.close()
        assert closed == ([] if mode == 'headers' else [True])
        journal = (tmp_path / (run.run_id + '.jsonl')).read_text()
        assert 'response_observed' in journal and PRIVATE not in journal
        assert run.snapshot()['closed'] is True
    asyncio.run(scenario())


@pytest.mark.parametrize('data,invalid,terminal', [
    (b'data: {"type":"response.completed"}\n\n',0,'response.completed'),
    (b'\xef\xbb\xbfdata: {\ndata: "type":"response.completed"}\n\n',0,'response.completed'),
    (b'event: response.failed\ndata: {"type":"response.failed"}\n\n',0,'response.failed'),
    (b'data: {"type":"response.incomplete"}\n\n',0,'response.incomplete'),
    (b'data: {"type":"error","message":"private"}\n\n',0,'error'),
    (b'data: [DONE]\n\n',0,'done_marker'),
    (b'event: response.failed\ndata: {"type":"response.completed"}\n\n',1,None),
    (b'data: {"type":"response.completed","type":"response.failed"}\n\n',1,None),
    (b'data: {"type":"response.completed","number":NaN}\n\n',1,None),
    (b'data: malformed private\n\n',1,None),
    (b'data: {"type":"response.completed"}',1,None),
])
def test_sse_observer_classifies_complete_bounded_frames_and_rejects_malformed(data, invalid, terminal):
    from scripts.issue14_response_observation import ResponseObservation
    observation = ResponseObservation()
    observation.headers(200, True)
    for byte in data:
        observation.chunk(bytes([byte]))
    observation.eof()
    result = observation.snapshot()
    assert result['terminal_sse_category'] == terminal
    assert result['sse_invalid_events'] == invalid
    assert result['response_bytes_seen'] == len(data)
    assert result['response_chunks_seen'] == len(data)
    assert 'private' not in json.dumps(result)


def test_observers_bound_floods_seal_late_updates_and_reject_nonfinite_clocks(monkeypatch):
    from scripts import issue14_response_observation as wire
    from apps.api import codex_progress as protocol
    observation = wire.ResponseObservation()
    observation.headers(200, True)
    observation.chunk(b'data: ' + PRIVATE.encode() * 100000 + b'\n\n')
    assert observation.buffered_bytes <= 2 * wire.MAX_SSE_EVENT_BYTES
    observation.eof(); observation.close()
    before = observation.snapshot()
    observation.chunk(TERMINAL)
    assert observation.snapshot() == before
    assert before['sse_omitted_events'] == 1 and before['terminal_sse_category'] is None
    progress = protocol.WorkerProgress()
    progress.begin_turn(); progress.bind_turn('thread', 'turn')
    for ordinal in range(5000):
        progress.observe('item/started', {'threadId':'thread','turnId':'turn',
            'item':{'id':str(ordinal),'type':'dynamicToolCall','tool':PRIVATE,'arguments':PRIVATE}})
    result = progress.snapshot()
    assert progress.tracked_ids <= protocol.MAX_TRACKED_TOOL_IDS
    assert result['counts_truncated'] is True and result['distinct_tool_ids_exact'] is False
    assert PRIVATE not in json.dumps(result)
    progress.close(); before = progress.snapshot()
    progress.begin_turn(); progress.observe('item/completed', {})
    assert progress.snapshot() == before
    monkeypatch.setattr(wire.time, 'monotonic', lambda: float('nan'))
    observation = wire.ResponseObservation(); observation.headers(200, True); observation.chunk(TERMINAL)
    result = observation.snapshot()
    assert result['timestamps_valid'] is False
    json.dumps(result, allow_nan=False)
    progress = protocol.WorkerProgress();progress.begin_turn();progress.bind_turn('thread','turn')
    progress.observe('item/started', {'threadId':'thread','turnId':'turn',
        'item':{'id':'one','type':'dynamicToolCall','tool':'read_file'}})
    assert progress.snapshot()['timestamps_valid'] is False
    assert progress.snapshot()['progress_events'] == 0
    json.dumps(progress.snapshot(), allow_nan=False)


def test_real_worker_protocol_progress_survives_expiry_without_trajectory_or_payload(tmp_path, monkeypatch):
    from apps.api import codex_worker_service as workers
    from apps.api.codex_agent import CodexConnection
    from scripts import issue14_subscription_session as sessions
    from scripts.memoir_fifty_readback import FiftyReadback, case_plans_for_run
    cleanup = []
    class Connection(CodexConnection):
        async def __aenter__(self): return self
        async def __aexit__(self, *args): cleanup.append(True)
        async def request(self, method, params):
            return {'thread':{'id':'thread'}} if method == 'thread/start' else {'turn':{'id':'turn'}}
        async def receive(self):
            if self.synthetic_events:
                return self.synthetic_events.pop(0)
            await asyncio.Event().wait()
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.synthetic_events = []
            for method, item_id, status in [('item/started','one',None),('item/completed','one','completed'),('item/started','two',None)]:
                self.synthetic_events.append({'method':method, 'params':{'threadId':'thread','turnId':'turn',
                    'item':{'id':item_id,'type':'dynamicToolCall','tool':'read_file','status':status,
                        'arguments':PRIVATE,'output':PRIVATE}}})
            self.synthetic_events.append({'method':'item/started','params':{'threadId':'foreign','turnId':'turn',
                'item':{'id':'foreign','type':'dynamicToolCall','tool':PRIVATE}}})
    monkeypatch.setattr(workers, 'CodexConnection', Connection)
    async def scenario():
        run = SubscriptionRun.create(reservation_root=tmp_path, run_id=str(uuid4()),
            source_revision='a' * 40, limits=SubscriptionLimits(4,5))
        plans=case_plans_for_run(run.run_id); case=next(iter(plans)); plan=plans[case]
        bridge=FiftyReadback(case_id=case,run_id=run.run_id,project_id=plan['project_id'],source_revision=run.source_revision)
        ids=bridge.before_round(case,1)
        worker=workers.CodexWorker(home_root=tmp_path/'worker',timeout=.05,api_key='synthetic-token')
        monkeypatch.setattr(worker,'_home',lambda *a:tmp_path)
        monkeypatch.setattr(worker,'_run_command',lambda *a:['never-executed'])
        owner=SimpleNamespace(run=run,_active=(case,1),_plans=plans,_pending=set(),_worker_lock=asyncio.Lock(),
            _job_context=ContextVar('synthetic-job',default=None),_payload_type=workers.WorkerTurnInput,
            _worker_records=[],_worker_diagnostic_contexts=[],worker_url=sessions._WORKER_URL,
            bridge_for_case=lambda value:bridge,_workers={'collector':worker},
            _profile=SimpleNamespace(rounds=50,family_enabled_for_round=lambda *a:False))
        monkeypatch.setattr(sessions,'assert_owned_subscription_session',lambda value:None if value is owner else pytest.fail('Foreign owner'))
        try:
            async with httpx.AsyncClient(transport=sessions._WorkerTransport(owner),base_url=owner.worker_url) as client:
                with pytest.raises(TimeoutError):
                    await client.post('/internal/codex/turn',json={'user_id':plan['owner_id'],'project_id':plan['project_id'],
                        'language':plan['language'],'text':PRIVATE,'evaluation':ids})
            record=owner._worker_records[-1]
            progress=record['worker_progress']
            assert progress['appserver_turns_started']==1 and progress['appserver_turns_completed']==0
            assert progress['tools_by_operation']['dynamicToolCall']=={'started':2,'completed':1,'failed':0}
            assert progress['distinct_tool_ids']==2 and progress['repeated_allowlisted_name_starts']==1
            assert progress['last_progress_at_monotonic'] is not None and progress['sealed'] is True
            cause=sessions.OwnedSubscriptionSession.worker_failure_for(owner,ids)
            assert cause['worker_progress']==progress and cause['worker_deadline_expired'] is True
            assert PRIVATE not in json.dumps(record) and 'trajectory' not in record
            assert cleanup == [True]
            record['worker_progress']['appserver_turns_started']=99
            assert sessions.OwnedSubscriptionSession.worker_failure_for(owner,ids) is None
            assert run.snapshot()['client_requests_started']==0
        finally: run.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('mode,phase',[('headers','awaiting_headers'),('body','reading_body'),('terminal','awaiting_eof')])
def test_real_worker_deadline_after_two_responses_keeps_unresolved_phase_and_no_fourth(tmp_path,monkeypatch,mode,phase):
    from apps.api.codex_worker_service import CodexWorker, WorkerTurnInput
    async def scenario():
        run=SubscriptionRun.create(reservation_root=tmp_path,run_id=str(uuid4()),source_revision='a'*40,limits=SubscriptionLimits(4,5))
        transport=SubscriptionTransport.controlled(run=run,endpoint='http://127.0.0.1:12345/v1/responses')
        calls=[];cleanup=[]
        class Pending(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield TERMINAL if mode=='terminal' else b': synthetic\n\n'
                await asyncio.Event().wait()
            async def aclose(self):cleanup.append(True)
        class Wire(httpx.AsyncBaseTransport):
            async def handle_async_request(self,request):
                calls.append(True)
                if len(calls)==3:
                    if mode=='headers':await asyncio.Event().wait()
                    stream=Pending()
                else:stream=httpx.ByteStream(TERMINAL)
                return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=stream)
        await transport._wire.aclose();transport._wire=Wire()
        worker=CodexWorker(home_root=tmp_path/'worker',timeout=.05,api_key='synthetic-token')
        payload=WorkerTurnInput(user_id=str(uuid4()),project_id=str(uuid4()),text=PRIVATE)
        async def turn(*a,**k):
            async with httpx.AsyncClient(transport=transport) as client:
                for ordinal in range(4):
                    await client.post(transport.endpoint,json={},headers={'authorization':'Bearer synthetic-token'})
        monkeypatch.setattr(worker,'_turn',turn)
        try:
            with pytest.raises(TimeoutError):await worker.turn(payload)
            assert worker.execution_deadline_expired(payload) is True
            snapshot=run.snapshot()
            assert snapshot['client_requests_started']==3 and snapshot['completed_http_responses']==2
            assert snapshot['unresolved_requests']==1 and len(calls)==3
            observation=snapshot['attempts'][2]['response_observation']
            assert observation['failure_phase']==phase and observation['eof_observed'] is False
            assert cleanup==([] if mode=='headers' else [True])
            with pytest.raises(SubscriptionStopped):
                async with httpx.AsyncClient(transport=transport) as client:
                    await client.post(transport.endpoint,json={},headers={'authorization':'Bearer synthetic-token'})
            assert len(calls)==3
        finally:await transport.aclose();run.close()
        assert run.snapshot()['closed'] is True
    asyncio.run(scenario())


def test_worker_progress_readback_rejects_foreign_input_and_executing_task(tmp_path,monkeypatch):
    from apps.api.codex_worker_service import CodexWorker, WorkerTurnInput
    async def scenario():
        worker=CodexWorker(home_root=tmp_path/'worker',api_key='synthetic-token')
        payload=WorkerTurnInput(user_id=str(uuid4()),project_id=str(uuid4()),text=PRIVATE)
        async def completed(*a,**k):return {'reply':'synthetic'}
        monkeypatch.setattr(worker,'_turn',completed)
        await worker.turn(payload)
        assert worker.execution_progress(payload)['sealed'] is True
        assert worker.execution_progress(payload.model_copy()) is None
        async def foreign_task():return worker.execution_progress(payload)
        assert await asyncio.create_task(foreign_task()) is None
    asyncio.run(scenario())


def test_protocol_progress_is_scoped_counts_queued_items_once_and_records_completion(tmp_path):
    from apps.api.codex_agent import CodexConnection
    from apps.api.codex_progress import WorkerProgress
    async def scenario():
        progress=WorkerProgress()
        connection=CodexConnection(['never-executed'],tmp_path,progress=progress)
        async def request(method,params):
            await connection.handle_event({'method':'item/started','params':{'threadId':'thread','turnId':'turn',
                'item':{'id':'one','type':'commandExecution','tool':'shell','arguments':PRIVATE}}})
            return {'turn':{'id':'turn'}}
        events=[{'method':'item/agentMessage/delta','params':{'threadId':'thread','turnId':'turn','delta':PRIVATE}},
            {'method':'item/reasoning/textDelta','params':{'threadId':'thread','turnId':'turn','delta':PRIVATE}},
            {'method':'turn/completed','params':{'threadId':'thread','turn':{'id':'turn','status':'completed'}}}]
        async def receive(): return events.pop(0)
        connection.request=request; connection.receive=receive
        assert await connection.turn('thread',PRIVATE) == ''
        result=progress.snapshot()
        assert result['tools_by_operation']['commandExecution']['started']==1
        assert result['appserver_turns_started']==result['appserver_turns_completed']==1
        assert result['message_delta_events']==result['reasoning_delta_events']==1
        assert PRIVATE not in json.dumps(result)
    asyncio.run(scenario())


@pytest.mark.parametrize('mutation',[{'threadId':'foreign'},{'turnId':'foreign'},
    {'item':{'id':'bad private id','type':'dynamicToolCall'}},
    {'item':{'id':'one','type':PRIVATE}}, {'item':{'id':'one','type':'dynamicToolCall','status':PRIVATE}},
    {'item':{'id':'one','type':'dynamicToolCall','exitCode':float('nan')}}])
def test_foreign_or_malformed_protocol_metadata_cannot_supply_progress(mutation):
    from apps.api.codex_progress import WorkerProgress
    progress=WorkerProgress();progress.begin_turn();progress.bind_turn('thread','turn')
    before=progress.snapshot()
    progress.observe('item/started',{'threadId':'thread','turnId':'turn',
        'item':{'id':'one','type':'dynamicToolCall','tool':'read_file'},**mutation})
    assert progress.snapshot()==before


def test_split_oversized_sse_frame_cannot_resurrect_terminal_category():
    from scripts.issue14_response_observation import ResponseObservation, MAX_SSE_EVENT_BYTES
    observation=ResponseObservation();observation.headers(200,True)
    observation.chunk(b'data: '+b'x'*MAX_SSE_EVENT_BYTES)
    observation.chunk(b'\ndata: {"type":"response.completed"}\n\n')
    result=observation.snapshot()
    assert result['sse_omitted_events']==1 and result['terminal_sse_category'] is None


@pytest.mark.parametrize('mode',['body_error','cleanup_error','journal_error'])
def test_response_failure_cleanup_and_diagnostic_journal_failure_keep_charge(tmp_path,monkeypatch,mode):
    async def scenario():
        run=SubscriptionRun.create(reservation_root=tmp_path,run_id=str(uuid4()),source_revision='a'*40,limits=SubscriptionLimits(4,5))
        transport=SubscriptionTransport.controlled(run=run,endpoint='http://127.0.0.1:12345/v1/responses')
        calls=[]
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield TERMINAL
                raise httpx.ReadError(PRIVATE)
            async def aclose(self):
                if mode=='cleanup_error': raise RuntimeError(PRIVATE)
        class Wire(httpx.AsyncBaseTransport):
            async def handle_async_request(self,request):
                calls.append(True)
                return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=Stream())
        if mode=='journal_error':
            write=run._write
            def fail_observation(event,**fields):
                if event=='response_observed':
                    run._journal_durable=False;run._stop_reason='journal_unavailable'
                    raise SubscriptionStopped('journal_unavailable')
                return write(event,**fields)
            monkeypatch.setattr(run,'_write',fail_observation)
        await transport._wire.aclose();transport._wire=Wire()
        try:
            async with httpx.AsyncClient(transport=transport) as client:
                with pytest.raises(SubscriptionStopped):
                    await client.post(transport.endpoint,json={},headers={'authorization':'Bearer synthetic-token'})
                with pytest.raises(SubscriptionStopped):
                    await client.post(transport.endpoint,json={},headers={'authorization':'Bearer synthetic-token'})
            receipt=run.snapshot();observation=receipt['attempts'][0]['response_observation']
            assert receipt['client_requests_started']==receipt['unresolved_requests']==len(calls)==1
            assert receipt['completed_http_responses']==0
            assert observation['failure_phase']=='awaiting_eof'
            assert observation['eof_at_monotonic'] is None
            assert observation['cleanup_status']==('failed' if mode=='cleanup_error' else 'closed')
            assert PRIVATE not in json.dumps(receipt)
            assert receipt['journal_durable']==(mode!='journal_error')
        finally: await transport.aclose();run.close()
    asyncio.run(scenario())


def test_http_body_eof_is_observed_before_httpx_automatic_close_failure(tmp_path):
    async def scenario():
        run=SubscriptionRun.create(reservation_root=tmp_path,run_id=str(uuid4()),source_revision='a'*40,limits=SubscriptionLimits(4,5))
        transport=SubscriptionTransport.controlled(run=run,endpoint='http://127.0.0.1:12345/v1/responses')
        cleanup=[]
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self): yield TERMINAL
            async def aclose(self):
                cleanup.append(True)
                raise RuntimeError(PRIVATE)
        class Wire(httpx.AsyncBaseTransport):
            async def handle_async_request(self,request):
                return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=Stream())
        await transport._wire.aclose();transport._wire=Wire()
        try:
            async with httpx.AsyncClient(transport=transport) as client:
                with pytest.raises(SubscriptionStopped):
                    await client.post(transport.endpoint,json={},headers={'authorization':'Bearer synthetic-token'})
            result=run.snapshot()['attempts'][0]['response_observation']
            assert result['eof_at_monotonic'] is not None
            assert result['failure_phase']=='closing_response'
            assert result['cleanup_status']=='failed' and result['cleanup_failure_class']=='runtime_error'
            assert cleanup==[True]
            assert run.snapshot()['completed_http_responses']==0
        finally:await transport.aclose();run.close()
    asyncio.run(scenario())


def test_observation_journal_overhead_cannot_extend_original_deadline(tmp_path,monkeypatch):
    from scripts import issue14_subscription_transport as budget
    now=[100.0]
    monkeypatch.setattr(budget,'time',SimpleNamespace(monotonic=lambda:now[0]))
    async def scenario():
        run=SubscriptionRun.create(reservation_root=tmp_path,run_id=str(uuid4()),source_revision='a'*40,limits=SubscriptionLimits(4,5))
        transport=SubscriptionTransport.controlled(run=run,endpoint='http://127.0.0.1:12345/v1/responses')
        calls=[]
        class Wire(httpx.AsyncBaseTransport):
            async def handle_async_request(self,request):
                calls.append(True)
                return httpx.Response(200,stream=httpx.ByteStream(TERMINAL))
        await transport._wire.aclose();transport._wire=Wire()
        write=run._write
        def slow_observation(event,**fields):
            if event=='response_observed':now[0]+=6
            return write(event,**fields)
        monkeypatch.setattr(run,'_write',slow_observation)
        try:
            async with httpx.AsyncClient(transport=transport) as client:
                for ordinal in range(2):
                    with pytest.raises(SubscriptionStopped,match='elapsed_limit'):
                        await client.post(transport.endpoint,json={},headers={'authorization':'Bearer synthetic-token'})
            receipt=run.snapshot()
            assert receipt['client_requests_started']==receipt['unresolved_requests']==len(calls)==1
            assert receipt['completed_http_responses']==0 and run.global_deadline==105
            assert receipt['attempts'][0]['response_observation']['eof_observed'] is True
        finally:await transport.aclose();run.close()
    asyncio.run(scenario())
