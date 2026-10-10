"""Synthetic regressions for independent review; no provider/native calls."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from scripts.issue14_response_observation import ResponseObservation, MAX_SSE_EVENT_BYTES
from scripts import issue14_subscription_transport as budget

PRIVATE='SYNTHETIC_PRIVATE_PAYLOAD_HEADERS_OR_ERROR'


@pytest.mark.parametrize('encoding',['utf-16-le','utf-16-be','utf-32-le','utf-32-be'])
@pytest.mark.parametrize('width',[1,3])
def test_non_utf8_sse_data_cannot_forge_terminal_evidence(encoding,width):
    raw=b'data: '+json.dumps({'type':'response.completed'}).encode(encoding)+b'\n\n'
    observation=ResponseObservation();observation.headers(200,True)
    for offset in range(0,len(raw),width):observation.chunk(raw[offset:offset+width])
    result=observation.snapshot()
    assert result['terminal_sse_category'] is None
    assert result['sse_invalid_events']==1
    assert result['sse_event_counts']['response.completed']==0
    assert observation.buffered_bytes==0
    assert result['response_bytes_seen']==len(raw)


@pytest.mark.parametrize('bad',[b'\xff',b'\xc0\xaf',b'\xed\xa0\x80'])
def test_invalid_utf8_is_rejected_without_terminal_or_unbounded_retention(bad):
    raw=b'data: {"type":"response.completed","private":"'+bad+b'"}\n\n'
    observation=ResponseObservation();observation.headers(200,True)
    for byte in raw:observation.chunk(bytes([byte]))
    result=observation.snapshot()
    assert result['terminal_sse_category'] is None and result['sse_invalid_events']==1
    assert observation.buffered_bytes==0


@pytest.mark.parametrize('width',[1,2,7])
def test_valid_split_utf8_retains_terminal_and_existing_bounds(width):
    raw=b'data: '+json.dumps({'type':'response.completed','private':'你好 café'},ensure_ascii=False).encode('utf-8')+b'\n\n'
    observation=ResponseObservation();observation.headers(200,True)
    for offset in range(0,len(raw),width):
        observation.chunk(raw[offset:offset+width])
        assert observation.buffered_bytes<=2*MAX_SSE_EVENT_BYTES
    result=observation.snapshot()
    assert result['terminal_sse_category']=='response.completed' and result['sse_invalid_events']==0
    assert '你好' not in json.dumps(result,ensure_ascii=False)
    observation.chunk(b'data: '+b'x'*(MAX_SSE_EVENT_BYTES+1)+b'\n\n')
    assert observation.snapshot()['sse_omitted_events']==1 and observation.buffered_bytes==0


@pytest.mark.parametrize('terminal',['response.completed','response.failed','response.incomplete','error'])
@pytest.mark.parametrize('order',['typed_first','done_first'])
def test_done_marker_does_not_contradict_typed_terminal_and_has_separate_counts(terminal,order):
    typed=b'data: '+json.dumps({'type':terminal}).encode()+b'\n\n'
    done=b'data: [DONE]\n\n'
    observation=ResponseObservation();observation.headers(200,True)
    for block in ([typed,done,done] if order=='typed_first' else [done,done,typed]):observation.chunk(block)
    result=observation.snapshot()
    assert result['terminal_sse_category']==terminal
    assert result['done_markers']==2 and result['first_done_marker_at_monotonic'] is not None
    assert result['last_done_marker_at_monotonic']>=result['first_done_marker_at_monotonic']
    assert result['sse_event_counts'][terminal]==1
    assert result['phase']=='awaiting_eof' and result['eof_observed'] is False


def test_contrary_typed_terminals_remain_conflicting_despite_done():
    observation=ResponseObservation();observation.headers(200,True)
    observation.chunk(b'data: {"type":"response.completed"}\n\ndata: [DONE]\n\ndata: {"type":"response.failed"}\n\n')
    result=observation.snapshot()
    assert result['terminal_sse_category']=='conflicting' and result['done_markers']==1


@pytest.mark.parametrize('mode',['deadline','accounting_write_failure','correction_write_failure'])
def test_terminal_journal_correction_matches_failed_accounting_without_refund(tmp_path,monkeypatch,mode):
    now=[100.0];current=[None];observations=[];calls=[]
    monkeypatch.setattr(budget,'time',SimpleNamespace(monotonic=lambda:now[0]))
    async def scenario():
        run=budget.SubscriptionRun.create(reservation_root=tmp_path,run_id=str(uuid4()),source_revision='a'*40,
            limits=budget.SubscriptionLimits(4,5))
        transport=budget.SubscriptionTransport.controlled(run=run,endpoint='http://127.0.0.1:12345/v1/responses')
        class Wire(httpx.AsyncBaseTransport):
            async def handle_async_request(self,request):
                calls.append(True)
                return httpx.Response(200,headers={'content-type':'text/event-stream'},
                    stream=httpx.ByteStream(b'data: {"type":"response.completed"}\n\n'))
        await transport._wire.aclose();transport._wire=Wire()
        fsync=budget.os.fsync
        def faulty_fsync(fd):
            event,revision=current[0] or (None,None)
            if (mode=='accounting_write_failure' and event=='http_response_completed'
                    or mode=='correction_write_failure' and event=='response_observed' and revision==2):
                raise OSError(PRIVATE)
            return fsync(fd)
        monkeypatch.setattr(budget.os,'fsync',faulty_fsync)
        write=run._write
        def instrument(event,**fields):
            revision=fields.get('observation_revision',1)
            if event=='response_observed':
                observations.append(deepcopy(fields))
                if revision==1 and mode!='accounting_write_failure':now[0]+=6
            current[0]=(event,revision)
            try:return write(event,**fields)
            finally:current[0]=None
        monkeypatch.setattr(run,'_write',instrument)
        try:
            async with httpx.AsyncClient(transport=transport) as client:
                with pytest.raises(budget.SubscriptionStopped) as caught:
                    await client.post(transport.endpoint,json={},headers={'authorization':'Bearer synthetic-token'})
                if mode=='correction_write_failure':assert str(caught.value)=='elapsed_limit'
                with pytest.raises(budget.SubscriptionStopped):
                    await client.post(transport.endpoint,json={},headers={'authorization':'Bearer synthetic-token'})
            receipt=run.snapshot();result=receipt['attempts'][0]['response_observation']
            assert result['failure_phase']=='eof' and result['failure_class']=='exception'
            assert len(observations)==2 and [v['observation_revision'] for v in observations]==[1,2]
            assert observations[-1]['response_observation']==result
            assert receipt['client_requests_started']==receipt['unresolved_requests']==len(calls)==1
            assert receipt['completed_http_responses']==0 and run.global_deadline==105
            assert receipt['journal_durable']==(mode=='deadline')
            journal=[json.loads(line) for line in (tmp_path/(run.run_id+'.jsonl')).read_text().splitlines()]
            retained=[row for row in journal if row['event']=='response_observed']
            if mode!='correction_write_failure':assert retained[-1]['response_observation']==result
            assert PRIVATE not in json.dumps(journal)
        finally:await transport.aclose();run.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('prefix',[b'',b': ok\n\n'])
def test_rejected_final_chunk_retains_seen_bytes_and_times_without_parsing_or_forwarding(tmp_path,monkeypatch,prefix):
    monkeypatch.setattr(budget,'MAX_RESPONSE_BYTES',32)
    tail=(b'data: {"type":"response.completed","private":"'+PRIVATE.encode()+b'"}\n\n')
    calls=[];cleanup=[]
    async def scenario():
        run=budget.SubscriptionRun.create(reservation_root=tmp_path,run_id=str(uuid4()),source_revision='a'*40,
            limits=budget.SubscriptionLimits(4,5))
        transport=budget.SubscriptionTransport.controlled(run=run,endpoint='http://127.0.0.1:12345/v1/responses')
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                if prefix:yield prefix
                yield tail
            async def aclose(self):cleanup.append(True)
        class Wire(httpx.AsyncBaseTransport):
            async def handle_async_request(self,request):
                calls.append(True)
                return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=Stream())
        await transport._wire.aclose();transport._wire=Wire()
        try:
            async with httpx.AsyncClient(transport=transport) as client:
                with pytest.raises(budget.SubscriptionStopped,match='protocol_invalid'):
                    await client.post(transport.endpoint,json={},headers={'authorization':'Bearer synthetic-token'})
                with pytest.raises(budget.SubscriptionStopped):
                    await client.post(transport.endpoint,json={},headers={'authorization':'Bearer synthetic-token'})
            receipt=run.snapshot();result=receipt['attempts'][0]['response_observation']
            assert result['response_bytes_seen']==len(prefix)+len(tail)
            assert result['response_chunks_seen']==(2 if prefix else 1)
            assert result['first_byte_at_monotonic'] is not None and result['last_byte_at_monotonic']>=result['first_byte_at_monotonic']
            assert result['terminal_sse_category'] is None and result['sse_event_counts']['response.completed']==0
            assert result['sse_scan_truncated'] is True and result['sse_scan_truncation_reason']=='response_size_limit'
            assert result['eof_observed'] is False and result['cleanup_status']=='closed'
            assert receipt['client_requests_started']==receipt['unresolved_requests']==len(calls)==len(cleanup)==1
            assert receipt['completed_http_responses']==0 and PRIVATE not in json.dumps(receipt)
        finally:await transport.aclose();run.close()
    asyncio.run(scenario())
