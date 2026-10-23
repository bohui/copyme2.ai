"""Canonical accepted summary maintenance, native PostgreSQL, controlled provider."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
from uuid import uuid4
import httpx
import pytest
from test_interview_strategy_runtime import client_fixture
from test_interview_strategy_postgres import (database,sql,event_database,private_database,attachment_database,
    enable_only_disposable_database_rollout)
from test_two_lane_memory import lane,service
from test_shared_memory_events_postgres import rpc,literal
from test_agent_commit_postgres import OWNER,OTHER,as_user
from test_interview_strategy import wire


class Broker:
    def __init__(self,sql):self.sql=sql
    async def rpc(self,name,**args):
        query=','.join(k+'=>'+literal(v) for k,v in args.items())
        return await asyncio.to_thread(lambda:json.loads(self.sql('set role service_role;select to_jsonb(public.'+name+'('+query+'));').stdout.splitlines()[-1]))


def setup_backlog(sql,tmp_path,monkeypatch,*,count=25):
    packets=[]
    def provider(request):
        body=json.loads(request.content);packets.append(body)
        return httpx.Response(200,json={'reply':json.dumps(wire(selection_reason='latest_story')),'thread_id':'a-'+str(len(packets)),'artifacts':[]})
    client=client_fixture(sql,tmp_path,monkeypatch,provider)
    with client:
        turn=str(uuid4());text='I remember the first shop.'
        response=client.post('/v1/agent/turn',json={'text':text,'client_turn_id':turn});assert response.status_code==200,response.text
    identity=rpc(sql,'resolve_lifetime_conversation',literal(response.json()['project_id']))
    for n in range(2,count+1):
        text_n='I remember the violet kite.' if n==10 else f'Original recollection number {n}.'
        rpc(sql,'accept_user_narrator_source',f"{literal(identity['project_id'])},'{uuid4()}',{literal(text_n)}")
    rpc(sql,'accept_two_lane_interview_turn',f"{literal(identity['project_id'])},'{turn}',{literal(text)}")
    sql("update public.user_narrator_source set processing_status='succeeded';")
    lane_id=lane(sql,identity);page=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
    assert page['complete'] and page['source'] is None
    service(sql,'advance_two_lane_checkpoint',f"'{lane_id}','{page['token']}',1")
    return identity,lane_id,service(sql,'read_lifetime_memoir_lane_page',f"'{lane_id}','{page['token']}'"),packets


def proposal(page):
    items=deepcopy(page['memory_summary']['prior']['items'])
    if 'violet kite' in (page.get('source') or {}).get('text',''):
        items.append({'text':'The narrator remembers a violet kite.','uncertainty':'Remembered testimony, not independently verified.',
            'source_refs':[{'source_id':page['source']['id'],'version':page['source']['version'],'quote':'violet kite','char_start':None,'char_end':None}]})
    return {'items':items}


def test_summary_wire_is_bounded_derived_context_and_rejects_unseen_evidence():
    from apps.api.lifetime_memory_summary import validate_summary
    page={'source':{'id':str(uuid4()),'version':1,'text':'A violet kite.','char_start':0},
        'memory_summary':{'prior':{'items':[]}}}
    value=proposal(page);accepted=validate_summary(value,page)
    assert accepted['items'][0]['source_refs'][0]['char_start']==2
    bad=deepcopy(value);bad['items'][0]['source_refs'][0]['source_id']=str(uuid4())
    with pytest.raises(ValueError):validate_summary(bad,page)
    bad=deepcopy(value);bad['items'][0]['text']='x'*9000
    with pytest.raises(ValueError):validate_summary(bad,page)


def test_summary_can_shorten_a_prior_quote_without_losing_its_original_span():
    from apps.api.lifetime_memory_summary import validate_summary
    prior = {'source_id': 'earlier-source', 'version': 1, 'quote': 'A violet kite.',
             'char_start': 10, 'char_end': 24}
    page = {'source': {'id': 'current-source', 'version': 1, 'text': 'Another memory.', 'char_start': 0},
            'memory_summary': {'prior': {'items': [{'text': 'A kite.', 'uncertainty': 'Remembered.',
                                                   'source_refs': [prior]}]}}}
    raw = {'items': [{'text': 'A kite.', 'uncertainty': 'Remembered.', 'source_refs': [
        {**prior, 'quote': 'violet kite', 'char_start': None, 'char_end': None}]}]}
    accepted = validate_summary(raw, page)
    assert accepted['items'][0]['source_refs'][0] == {
        **prior, 'quote': 'violet kite', 'char_start': 12, 'char_end': 23}
    raw['items'][0]['source_refs'][0]['quote'] = 'a red kite'
    with pytest.raises(ValueError):
        validate_summary(raw, page)


def test_database_accepts_only_exact_subspans_of_prior_summary_quotes(sql,tmp_path,monkeypatch):
    from apps.api.lifetime_memory_summary import validate_summary
    _,lane_id,page,_=setup_backlog(sql,tmp_path,monkeypatch)
    source=page['source']
    value={'items':[{'text':'The first shop.','uncertainty':'Remembered testimony.','source_refs':[
        {'source_id':source['id'],'version':source['version'],'quote':'first shop','char_start':None,'char_end':None}]}]}
    value=validate_summary(value,page)
    service(sql,'commit_lifetime_memory_summary_page',
        f"'{lane_id}','{page['token']}',{page['memory_summary']['revision']},{literal(value)},'{page['page_digest']}'")
    page=service(sql,'read_lifetime_memoir_lane_page',f"'{lane_id}','{page['token']}'")
    shortened=deepcopy(value);shortened['items'][0]['source_refs'][0].update(quote='shop',char_start=None,char_end=None)
    shortened=validate_summary(shortened,page)
    outside=deepcopy(shortened)
    outside['items'][0]['source_refs'][0].update(quote='remember',char_start=2,char_end=10)
    with pytest.raises(AssertionError):
        service(sql,'commit_lifetime_memory_summary_page',
            f"'{lane_id}','{page['token']}',{page['memory_summary']['revision']},{literal(outside)},'{page['page_digest']}'")
    assert service(sql,'commit_lifetime_memory_summary_page',
        f"'{lane_id}','{page['token']}',{page['memory_summary']['revision']},{literal(shortened)},'{page['page_digest']}'")['status']=='page_saved'


def test_semantic_summary_retry_carries_only_fixed_feedback(sql,tmp_path,monkeypatch):
    from apps.api.lifetime_memory_composer import _summarize
    _,_,page,_=setup_backlog(sql,tmp_path,monkeypatch)
    calls=[]
    def provider(request):
        body=json.loads(request.content);calls.append(body['bounded_lane'])
        if len(calls)==1:
            value={'items':[{'text':'An unsupported detail.','uncertainty':'Unverified.','source_refs':[
                {'source_id':page['source']['id'],'version':1,'quote':'invented quotation','char_start':None,'char_end':None}]}]}
        else:value={'items':[]}
        return httpx.Response(200,json={'reply':json.dumps(value),'artifacts':[]})
    assert asyncio.run(_summarize(page,summary_worker(sql,provider)))=={'items':[]}
    assert len(calls)==2
    first=json.loads(calls[0]['packet'])['payload'];second=json.loads(calls[1]['packet'])['payload']
    dialogue=page['attribution_context']['recent_dialogue']
    assert dialogue[0]['question']['personal_testimony'] is False
    assert dialogue[0]['response']['text']=='Original recollection number 2.'
    assert first['recent_dialogue']==dialogue
    assert second.pop('retry_reason')=='SUMMARY_EVIDENCE'
    assert second==first and calls[0]['fence']==calls[1]['fence']
    from apps.api.lifetime_memory_lane_engine import build_bounded_lane_input
    from apps.api.lifetime_memory_composer import lane_model_budget
    first['retry_reason']='private diagnostic instructions'
    with pytest.raises(ValueError,match='Unsupported summary retry reason'):
        build_bounded_lane_input(page,phase='summarize',packet=first,budget=lane_model_budget())


def test_summary_schema_limits_citations_to_exact_available_source_versions():
    from jsonschema import validate,ValidationError
    from apps.api.lifetime_memory_summary import summary_contract
    prior={'source_id':'prior','version':1,'quote':'Earlier testimony.','char_start':0,'char_end':18}
    item={'text':'Earlier testimony.','uncertainty':'Remembered.','source_refs':[prior]}
    _,schema=summary_contract({'source':{'id':'current','version':2},'memory_summary':{'prior':{'items':[item]}}})
    validate({'items':[item]},schema)
    bad=deepcopy(item);bad['source_refs'][0]['version']=2
    with pytest.raises(ValidationError):validate({'items':[bad]},schema)
    bad['source_refs'][0].update(source_id='unknown',version=1)
    with pytest.raises(ValidationError):validate({'items':[bad]},schema)


def test_summary_rejection_feedback_distinguishes_budget_without_private_text():
    from pydantic import ValidationError
    from apps.api.lifetime_memory_summary import SummaryProposal,summary_rejection_reason
    item={'text':'x'*500,'uncertainty':'y'*500,'source_refs':[
        {'source_id':'source','version':1,'quote':'text','char_start':0,'char_end':4}]}
    with pytest.raises(ValidationError) as error:SummaryProposal(items=[item]*16)
    assert summary_rejection_reason(error.value)=='SUMMARY_BUDGET'
    assert summary_rejection_reason(ValueError('private output and instructions'))=='OUTPUT_SCHEMA'


@pytest.mark.parametrize('change', ['none', 'source', 'policy', 'token', 'after_send_policy'])
def test_direct_summary_guards_actual_http_and_stale_commit(sql, tmp_path, monkeypatch, change):
    from apps.api.lifetime_memory_composer import lane_model_budget
    from apps.api.lifetime_memory_lane_engine import build_bounded_lane_input, run_bounded_lane, LanePublication
    from apps.api.lifetime_memory_summary import summary_packet, validate_summary
    from apps.api.lifetime_memory_policy import PolicyUnavailable
    from apps.api.lifetime_memory_publication import PublicationUnavailable
    from test_conversation_reply_transport import events, sse

    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY', 'true')
    identity, lane_id, page, _ = setup_backlog(sql, tmp_path, monkeypatch)
    budget = lane_model_budget()
    bounded = build_bounded_lane_input(page, phase='summarize', packet=summary_packet(page), budget=budget)
    sent = []

    def mutate():
        if change == 'source':
            rpc(sql, 'change_user_narrator_source', f"{literal(identity['project_id'])},'{page['source']['id']}',1,'withdraw',null")
        elif change in {'policy', 'after_send_policy'}:
            sql('update public.user_memoir_project set policy_epoch=policy_epoch+1;')
        elif change == 'token':
            sql('update public.user_memoir_lane set token=gen_random_uuid();')

    class Provider(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            if change != 'after_send_policy':
                mutate()
            async for chunk in request.stream:
                sent.append(chunk)
            if change == 'after_send_policy':
                mutate()
            return httpx.Response(200, content=sse(events(json.dumps(proposal(page)))))

    async def generate():
        return await run_bounded_lane(command=['must-not-start'], home_root=tmp_path / 'homes',
            base_url='https://provider.invalid/v1', api_key='fixture-summary-key', model=budget.model,
            bounded_lane=bounded, publisher=LanePublication(sql.publication_dsn, authenticated_owner=OWNER),
            provider_transport=Provider(), timeout=5)

    if change in {'none', 'after_send_policy'}:
        output = validate_summary(json.loads(asyncio.run(generate())['reply']), page)
        assert sent
        def commit():
            return service(sql, 'commit_lifetime_memory_summary_page',
                f"'{lane_id}','{page['token']}',{page['memory_summary']['revision']},{literal(output)},'{page['page_digest']}'")
        if change == 'none':
            assert commit()['status'] == 'page_saved'
        else:
            with pytest.raises(AssertionError):
                commit()
    else:
        with pytest.raises((PublicationUnavailable, PolicyUnavailable)):
            asyncio.run(generate())
        assert sent == []
    assert not (tmp_path / 'homes').exists()


def test_summary_repairs_unique_quote_offsets_but_rejects_ambiguous_matches():
    from apps.api.lifetime_memory_summary import validate_summary
    page = {'source': {'id': 'current-source', 'version': 1, 'text': '风筝是紫色的。', 'char_start': 20},
            'memory_summary': {'prior': {'items': []}}}
    raw = {'items': [{'text': '紫色的风筝。', 'uncertainty': '回忆。', 'source_refs': [
        {'source_id': 'current-source', 'version': 1, 'quote': '紫色', 'char_start': 3, 'char_end': 5}]}]}
    accepted = validate_summary(raw, page)
    assert accepted['items'][0]['source_refs'][0]['char_start'] == 23
    assert accepted['items'][0]['source_refs'][0]['char_end'] == 25
    page['source']['text'] += '紫色'
    with pytest.raises(ValueError):
        validate_summary(raw, page)


def test_every_window_is_processed_before_semantic_head_and_http_continuation(sql,tmp_path,monkeypatch):
    from apps.api.lifetime_memory_composer import execute_lifetime_lane
    from apps.api.lifetime_memory_lane_engine import LanePublication
    identity,lane_id,page,packets=setup_backlog(sql,tmp_path,monkeypatch)
    assert not page['complete'] and page['memory_summary']['revision']==0
    calls=[]
    def provider(request):
        body=json.loads(request.content);calls.append(body)
        bounded=body['bounded_lane'];assert bounded['phase']=='summarize'
        assert body['agent_role']=='author_timeline' and 'composer_phase' not in body
        assert len(bounded['packet'].encode())<65536
        return httpx.Response(200,json={'reply':json.dumps(proposal(bounded['fence'])),'thread_id':'summary','artifacts':[]})
    worker=SimpleNamespace(broker=Broker(sql),worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(provider),
        lane_publisher=LanePublication(sql.publication_dsn,authenticated_owner=OWNER))
    result=asyncio.run(execute_lifetime_lane(page,worker,page_quantum=2));assert result['status']=='pending'
    assert sql('select count(*) from public.user_lifetime_checkpoint;').stdout.strip()=='0'
    for _ in range(20):
        page=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
        result=asyncio.run(execute_lifetime_lane(page,worker,page_quantum=4))
        if result.get('retrieval_complete'):break
    assert result['retrieval_complete']
    checkpoint=rpc(sql,'read_lifetime_two_lane_checkpoint',f"'{identity['conversation_id']}',1,'gpt-5.6-luna-pooled','lifetime-v1'")
    assert checkpoint['coverage_end']==24
    assert checkpoint['memory_summary']['processed_windows']==24
    assert 'violet kite' in json.dumps(checkpoint)
    assert len(calls)==24
    def foreground(request):
        body=json.loads(request.content);packet=json.loads(body['governed']['packet'])
        assert packet['coverage_end']==24
        assert [r['sequence'] for r in packet['tail']]==[25]
        assert packet['current']['sequence']==26 and 'violet kite' in json.dumps(packet['checkpoint'])
        return httpx.Response(200,json={'reply':json.dumps(wire(selection_reason='latest_story')),'thread_id':'continued','artifacts':[]})
    with client_fixture(sql,tmp_path,monkeypatch,foreground) as client:
        response=client.post('/v1/agent/turn',json={'project_id':identity['project_id'],'text':'What else do I remember?','client_turn_id':str(uuid4())})
        assert response.status_code==200,response.text
        assert response.json()['conversation_saved']
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='2'
    assert sql("select count(*) from public.user_memoir_lane where skill='composer';").stdout.strip()=='0'


def test_summary_receipt_replay_and_expired_owner_resume_do_not_skip_windows(sql,tmp_path,monkeypatch):
    from apps.api.lifetime_memory_summary import validate_summary
    identity,lane_id,page,_=setup_backlog(sql,tmp_path,monkeypatch)
    value=validate_summary(proposal(page),page)
    args=f"'{lane_id}','{page['token']}',{page['memory_summary']['revision']},{literal(value)},'{page['page_digest']}'"
    service(sql,'commit_lifetime_memory_summary_page',args)
    assert service(sql,'commit_lifetime_memory_summary_page',args)['replayed']
    altered=deepcopy(value);altered['items']=[{'text':'Changed retry','uncertainty':'unknown','source_refs':[]}]
    with pytest.raises(AssertionError):service(sql,'commit_lifetime_memory_summary_page',f"'{lane_id}','{page['token']}',0,{literal(altered)},'{page['page_digest']}'")
    sql(f"update public.user_memoir_lane set lease_until=clock_timestamp()-interval '1 second' where id='{lane_id}';")
    resumed=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
    assert resumed['token']!=page['token'] and resumed['memory_summary']['revision']==1
    assert resumed['source']['sequence']==2
    with pytest.raises(AssertionError):service(sql,'commit_lifetime_memory_summary_page',args)


@pytest.mark.parametrize('change',['policy','source','generation','lease'])
def test_stale_summary_cannot_publish_or_resurrect_a_restricted_source(sql,tmp_path,monkeypatch,change):
    identity,lane_id,page,_=setup_backlog(sql,tmp_path,monkeypatch)
    assert page.get('memory_summary') is not None and page['source'] is not None
    if change=='policy':sql(as_user("update public.user_profile set profile=jsonb_build_object('memory_preferences',jsonb_build_object('excluded_topics',jsonb_build_array('shop')));"))
    elif change=='source':rpc(sql,'change_user_narrator_source',f"{literal(identity['project_id'])},'{page['source']['id']}',1,'withdraw',null")
    elif change=='generation':sql('update public.user_lifetime_conversation set execution_generation=execution_generation+1;')
    else:sql(f"update public.user_memoir_lane set lease_until=clock_timestamp()-interval '1 second' where id='{lane_id}';")
    with pytest.raises(AssertionError):service(sql,'commit_lifetime_memory_summary_page',f"'{lane_id}','{page['token']}',0,{literal({'items':[]})},'{page['page_digest']}'")
    assert sql('select count(*) from public.user_lifetime_checkpoint;').stdout.strip()=='0'


def summary_worker(sql,provider):
    from apps.api.lifetime_memory_lane_engine import LanePublication
    return SimpleNamespace(broker=Broker(sql),worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(provider),
        lane_publisher=LanePublication(sql.publication_dsn,authenticated_owner=OWNER))


def drain(sql,lane_id,page,worker,quantum=4):
    from apps.api.lifetime_memory_composer import execute_lifetime_lane
    for _ in range(100):
        result=asyncio.run(execute_lifetime_lane(page,worker,page_quantum=quantum))
        if result.get('retrieval_complete'):return result
        page=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
        assert page is not None
    raise AssertionError('Bounded summary test did not settle')


def test_long_unicode_original_uses_every_absolute_window_without_raw_overflow(sql,tmp_path,monkeypatch):
    from apps.api.codex_worker_service import WorkerTurnInput
    identity,lane_id,page,_=setup_backlog(sql,tmp_path,monkeypatch,count=3)
    # A supported import can exceed a foreground request. Correcting it revokes
    # every prior proof; prepare a new fenced claim over the exact long original.
    raw='开头。'+('原文'*9000)+'紫色风筝'+('结尾'*200)
    source=json.loads(sql("select to_jsonb(s) from public.user_narrator_source s where sequence=2;").stdout.strip())
    rpc(sql,'change_user_narrator_source',f"{literal(identity['project_id'])},'{source['id']}',1,'edit',{literal(raw)}")
    # New source position4 is the edited version; keep it current and summarize
    # the previous active long source by adding a final accepted raw position.
    rpc(sql,'accept_user_narrator_source',f"{literal(identity['project_id'])},'{uuid4()}','Newest original'")
    sql("update public.user_narrator_source set processing_status='succeeded';update public.user_memoir_lane set token=null,lease_until=null,run_deadline=null,pending=true;")
    turn=sql('select client_turn_id from public.user_narrator_source where sequence=1;').stdout.strip()
    rpc(sql,'accept_two_lane_interview_turn',f"{literal(identity['project_id'])},'{turn}','I remember the first shop.'")
    page=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
    for _ in range(10):
        state=service(sql,'advance_two_lane_checkpoint',f"'{lane_id}','{page['token']}',1")
        if state['complete']:break
    page=service(sql,'read_lifetime_memoir_lane_page',f"'{lane_id}','{page['token']}'")
    seen=[]
    def provider(request):
        body=json.loads(request.content);WorkerTurnInput.model_validate(body)
        fence=body['bounded_lane']['fence'];seen.append((fence['source']['id'],fence['source']['char_start']))
        output=deepcopy(fence['memory_summary']['prior'])
        if '紫色风筝' in fence['source']['text']:
            output['items'].append({'text':'叙述者记得紫色风筝。','uncertainty':'回忆，未独立证实。','source_refs':[
                {'source_id':fence['source']['id'],'version':fence['source']['version'],'quote':'紫色风筝','char_start':None,'char_end':None}]})
        return httpx.Response(200,json={'reply':json.dumps(output),'thread_id':'unicode','artifacts':[]})
    drain(sql,lane_id,page,summary_worker(sql,provider))
    checkpoint=rpc(sql,'read_lifetime_two_lane_checkpoint',f"'{identity['conversation_id']}',2,'gpt-5.6-luna-pooled','lifetime-v1'")
    assert checkpoint is not None
    cites=[r for item in checkpoint['memory_summary']['items'] for r in item['source_refs']]
    cite=next(r for r in cites if r['quote']=='紫色风筝')
    assert cite['char_start']==raw.index('紫色风筝') and cite['version']==2
    offsets=[offset for source_id,offset in seen if source_id==source['id']]
    assert offsets==list(range(0,len(raw),2000))
    assert len(json.dumps(checkpoint,ensure_ascii=False).encode())<12000


def test_new_checkpoint_extends_previous_summary_and_flag_rollback_reads_it(sql,tmp_path,monkeypatch):
    from test_name_only_opening import proposal as legacy_proposal
    calls=[]
    def provider(request):
        body=json.loads(request.content);fence=body['bounded_lane']['fence'];calls.append(fence['source']['sequence'])
        return httpx.Response(200,json={'reply':json.dumps(proposal(fence)),'thread_id':'incremental','artifacts':[]})
    identity,lane_id,page,_=setup_backlog(sql,tmp_path,monkeypatch)
    worker=summary_worker(sql,provider);drain(sql,lane_id,page,worker)
    first=rpc(sql,'read_lifetime_two_lane_checkpoint',f"'{identity['conversation_id']}',1,'gpt-5.6-luna-pooled','lifetime-v1'")
    assert first['coverage_end']==24
    def foreground(request):
        return httpx.Response(200,json={'reply':json.dumps(wire(question='What happened at the river?',selection_reason='latest_story')),'thread_id':'a-next','artifacts':[]})
    with client_fixture(sql,tmp_path,monkeypatch,foreground) as client:
        response=client.post('/v1/agent/turn',json={'project_id':identity['project_id'],'text':'I remember the river.','client_turn_id':str(uuid4())})
        assert response.status_code==200,response.text
    sql("update public.user_narrator_source set processing_status='succeeded';")
    page=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
    service(sql,'advance_two_lane_checkpoint',f"'{lane_id}','{page['token']}',1")
    page=service(sql,'read_lifetime_memoir_lane_page',f"'{lane_id}','{page['token']}'")
    assert page['source']['sequence']==25 and 'violet kite' in json.dumps(page['memory_summary']['prior'])
    calls.clear();drain(sql,lane_id,page,worker)
    second=rpc(sql,'read_lifetime_two_lane_checkpoint',f"'{identity['conversation_id']}',1,'gpt-5.6-luna-pooled','lifetime-v1'")
    assert second['coverage_end']==25 and second['predecessor_id']==first['checkpoint_id']
    assert second['memory_summary']['processed_windows']==25 and calls==[25]
    monkeypatch.setenv('MEMOIR_TWO_LANES','0');monkeypatch.setenv('MEMOIR_INTERVIEW_STRATEGY','0')
    sql('update public.lifetime_two_lane_rollout set enabled=false;')
    from apps.api import agent_routes
    from apps.api.codex_runtime import CodexRuntime
    def legacy(request):
        body=json.loads(request.content);packet=json.loads(body['governed']['packet'])
        assert packet['coverage_end']==25 and 'violet kite' in json.dumps(packet['checkpoint'])
        output={'reply':json.dumps(legacy_proposal(mode='extract',name=None)),'thread_id':'rollback','artifacts':[]}
        return httpx.Response(200,headers={'content-type':'application/x-ndjson'},content=json.dumps({'type':'result','data':output})+'\n')
    monkeypatch.setattr(agent_routes,'runtime',CodexRuntime(home_root=tmp_path,worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(legacy)))
    from apps.api.main import create_app
    from apps.api.store import MemoryStore
    from fastapi.testclient import TestClient
    with TestClient(create_app(MemoryStore())) as client:
        response=client.post('/v1/agent/turn',json={'project_id':identity['project_id'],'text':'Please continue.','client_turn_id':str(uuid4())})
        assert response.status_code==200,response.text
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='3'


def test_prior_summary_tampering_is_rejected_before_provider_bytes(sql,tmp_path,monkeypatch):
    from apps.api.lifetime_memory_lane_engine import build_bounded_lane_input,send_bounded_lane_request
    from apps.api.lifetime_memory_composer import lane_model_budget
    from apps.api.lifetime_memory_summary import summary_packet
    from apps.api.lifetime_memory_publication import PublicationUnavailable
    identity,lane_id,page,_=setup_backlog(sql,tmp_path,monkeypatch)
    forged=deepcopy(page)
    forged['memory_summary']['prior']['items']=[{'text':'Forged prior','uncertainty':'unverified','source_refs':[
        {'source_id':page['source']['id'],'version':1,'quote':'shop','char_start':21,'char_end':25}]}]
    bounded=build_bounded_lane_input(forged,phase='summarize',packet=summary_packet(forged),budget=lane_model_budget())
    called=[]
    def provider(request):called.append(request);return httpx.Response(500)
    worker=summary_worker(sql,provider)
    with pytest.raises(PublicationUnavailable):asyncio.run(send_bounded_lane_request(worker_url=worker.worker_url,worker_secret=worker.worker_secret,
        bounded_lane=bounded,worker_transport=worker.worker_transport,publisher=worker.lane_publisher))
    assert called==[] and sql('select summary_revision from public.user_lifetime_compaction;').stdout.strip()=='0'


def test_blocked_or_cancelled_summary_does_not_block_a_or_advance_coverage(sql,tmp_path,monkeypatch):
    from apps.api.lifetime_memory_composer import _summarize
    from apps.api.lifetime_memory_runtime import lifetime_http_turn
    from apps.api.codex_runtime import CodexRuntime
    from memoir_postgres_workflow import PostgresRest
    identity,lane_id,page,_=setup_backlog(sql,tmp_path,monkeypatch)
    async def scenario():
        started=asyncio.Event();release=asyncio.Event()
        async def provider(request):
            body=json.loads(request.content)
            if body.get('bounded_lane'):
                started.set();await release.wait()
                return httpx.Response(200,json={'reply':json.dumps(proposal(page)),'thread_id':'b','artifacts':[]})
            return httpx.Response(200,json={'reply':json.dumps(wire(question='What happened later?',selection_reason='latest_story')),'thread_id':'a','artifacts':[]})
        worker=summary_worker(sql,provider);task=asyncio.create_task(_summarize(page,worker))
        try:
            async with asyncio.timeout(5):await started.wait()
            runtime=CodexRuntime(home_root=tmp_path,worker_url=worker.worker_url,worker_secret=worker.worker_secret,worker_transport=worker.worker_transport)
            response=await lifetime_http_turn(runtime,PostgresRest(sql,OWNER).storage(),'Please go on.',accept='application/json',
                options={'project_id':identity['project_id'],'client_turn_id':str(uuid4())})
            async def send(_):pass
            async def receive():return {'type':'http.disconnect'}
            async with asyncio.timeout(10):await response({'type':'http','asgi':{'spec_version':'2.4'}},receive,send)
            assert response.delivered and not task.done()
            task.cancel();await asyncio.gather(task,return_exceptions=True)
        finally:
            release.set()
            if not task.done():task.cancel()
            await asyncio.gather(task,return_exceptions=True)
    asyncio.run(scenario())
    assert sql('select summary_revision from public.user_lifetime_compaction;').stdout.strip()=='0'
    assert sql('select count(*) from public.user_lifetime_checkpoint;').stdout.strip()=='0'
    resumed=service(sql,'read_lifetime_memoir_lane_page',f"'{lane_id}','{page['token']}'")
    assert resumed['memory_summary']['revision']==0 and resumed['source']['sequence']==1


def test_lossless_predecessor_is_processed_before_selective_summary_replaces_it(sql,tmp_path,monkeypatch):
    identity,lane_id,page,_=setup_backlog(sql,tmp_path,monkeypatch,count=15)
    assert page['complete']
    first=rpc(sql,'read_lifetime_two_lane_checkpoint',f"'{identity['conversation_id']}',1,'gpt-5.6-luna-pooled','lifetime-v1'")
    assert first['coverage_end']==14 and 'violet kite' in json.dumps(first)
    service(sql,'complete_lifetime_memoir_lane',f"'{lane_id}','{page['token']}'")
    for n in range(16,26):rpc(sql,'accept_user_narrator_source',f"{literal(identity['project_id'])},'{uuid4()}','Another original {n}'")
    turn=sql('select client_turn_id from public.user_narrator_source where sequence=1;').stdout.strip()
    rpc(sql,'accept_two_lane_interview_turn',f"{literal(identity['project_id'])},'{turn}','I remember the first shop.'")
    sql("update public.user_narrator_source set processing_status='succeeded';")
    page=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
    service(sql,'advance_two_lane_checkpoint',f"'{lane_id}','{page['token']}',1")
    page=service(sql,'read_lifetime_memoir_lane_page',f"'{lane_id}','{page['token']}'")
    assert page['source']['sequence']==1,'A verbatim prefix has no accepted semantic replacement yet'
    seen=[]
    def provider(request):
        fence=json.loads(request.content)['bounded_lane']['fence'];seen.append(fence['source']['sequence'])
        return httpx.Response(200,json={'reply':json.dumps(proposal(fence)),'thread_id':'prefix','artifacts':[]})
    drain(sql,lane_id,page,summary_worker(sql,provider))
    checkpoint=rpc(sql,'read_lifetime_two_lane_checkpoint',f"'{identity['conversation_id']}',1,'gpt-5.6-luna-pooled','lifetime-v1'")
    assert checkpoint['predecessor_id']==first['checkpoint_id'] and checkpoint['coverage_end']==24
    assert seen==list(range(1,25)) and 'violet kite' in json.dumps(checkpoint)
    assert rpc(sql,'read_lifetime_two_lane_checkpoint',f"'{identity['conversation_id']}',1,'gpt-5.6-luna-pooled','lifetime-v1'",owner=OTHER,check=False).returncode!=0


def test_summary_sql_rejects_unseen_foreign_evidence_even_with_a_real_quote(sql,tmp_path,monkeypatch):
    identity,lane_id,page,_=setup_backlog(sql,tmp_path,monkeypatch)
    foreign=rpc(sql,'resolve_lifetime_conversation','null',owner=OTHER)
    source=rpc(sql,'accept_user_narrator_source',f"{literal(foreign['project_id'])},'{uuid4()}','A private foreign kite.'",owner=OTHER)
    value={'items':[{'text':'The other owner has a kite.','uncertainty':'unknown','source_refs':[
        {'source_id':source['id'],'version':1,'quote':'private foreign kite','char_start':2,'char_end':22}]}]}
    with pytest.raises(AssertionError):service(sql,'commit_lifetime_memory_summary_page',f"'{lane_id}','{page['token']}',0,{literal(value)},'{page['page_digest']}'")
    assert sql('select summary_revision from public.user_lifetime_compaction;').stdout.strip()=='0'


def test_worker_checkpoint20_is_consumed_with_complete_tail21_22_current23(sql,tmp_path,monkeypatch):
    identity,lane_id,page,_=setup_backlog(sql,tmp_path,monkeypatch,count=21)
    rpc(sql,'accept_user_narrator_source',f"{literal(identity['project_id'])},'{uuid4()}','Original position twenty two.'")
    turn=str(uuid4());text='What do I remember about the kite?'
    rpc(sql,'accept_user_narrator_source',f"{literal(identity['project_id'])},'{turn}',{literal(text)}")
    assert page['source_high_water']==21,'The B snapshot stays pinned while new originals arrive'
    def provider(request):
        fence=json.loads(request.content)['bounded_lane']['fence']
        return httpx.Response(200,json={'reply':json.dumps(proposal(fence)),'thread_id':'k20','artifacts':[]})
    drain(sql,lane_id,page,summary_worker(sql,provider))
    def foreground(request):
        packet=json.loads(json.loads(request.content)['governed']['packet'])
        assert packet['coverage_end']==20
        assert [r['sequence'] for r in packet['tail']]==[21,22]
        assert packet['current']['sequence']==23
        assert 'violet kite' in json.dumps(packet['checkpoint'])
        return httpx.Response(200,json={'reply':json.dumps(wire(selection_reason='latest_story')),'thread_id':'a23','artifacts':[]})
    with client_fixture(sql,tmp_path,monkeypatch,foreground) as client:
        response=client.post('/v1/agent/turn',json={'project_id':identity['project_id'],'text':text,'client_turn_id':turn})
        assert response.status_code==200,response.text
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='23'
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='2'


def test_older_b_snapshot_cannot_move_a_newer_canonical_checkpoint_backwards(sql,tmp_path,monkeypatch):
    from test_agent_commit_postgres import OLD
    identity,lane_id,page,_=setup_backlog(sql,tmp_path,monkeypatch)
    rpc(sql,'accept_user_narrator_source',f"{literal(identity['project_id'])},'{uuid4()}','A newer accepted original'")
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    fence=rpc(sql,'capture_lifetime_fence',f"'{identity['conversation_id']}','{OLD}'")
    proof=rpc(sql,'begin_lifetime_compaction',f"{literal(fence)},25")
    while not proof['complete']:proof=rpc(sql,'step_lifetime_compaction',f"'{proof['id']}',{literal(fence)},{proof['revision']}")
    newer=rpc(sql,'create_lifetime_checkpoint',f"{literal(fence)},25,'gpt-5.6-luna-pooled','lifetime-v1','[]','{proof['id']}'")
    rpc(sql,'publish_lifetime_checkpoint',f"'{newer}',{literal(fence)}")
    sql(as_user(f"select public.release_user_agent_turn_lease('{OLD}');"))
    calls=[]
    def provider(request):
        calls.append(request)
        return httpx.Response(200,json={'reply':json.dumps({'items':[]}), 'thread_id':'older','artifacts':[]})
    page=service(sql,'read_lifetime_memoir_lane_page',f"'{lane_id}','{page['token']}'")
    drain(sql,lane_id,page,summary_worker(sql,provider))
    assert sql('select checkpoint_id from public.user_lifetime_conversation;').stdout.strip()==newer
    assert calls==[], 'An older snapshot must yield to the newer checkpoint frontier'


def test_old_pending_turn_can_retry_after_background_checkpoint_has_passed_it(sql,tmp_path,monkeypatch):
    from test_two_lane_memory import accept
    from memoir_postgres_workflow import PostgresRest
    sql_errors=[];original_handle=PostgresRest.handle
    def trace_sql_errors(self,request):
        response=original_handle(self,request)
        if response.status_code>=400:
            sql_errors.append(response.text)
        return response
    monkeypatch.setattr(PostgresRest,'handle',trace_sql_errors)
    identity,accepted=accept(sql,text='I remember the first shop.')
    for n in range(2,23):rpc(sql,'accept_user_narrator_source',f"{literal(identity['project_id'])},'{uuid4()}','Original {n}'")
    rpc(sql,'accept_two_lane_interview_turn',f"{literal(identity['project_id'])},'{accepted['client_turn_id']}','I remember the first shop.'")
    sql("update public.user_narrator_source set processing_status='succeeded';")
    lane_id=lane(sql,identity);page=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
    service(sql,'advance_two_lane_checkpoint',f"'{lane_id}','{page['token']}',1")
    page=service(sql,'read_lifetime_memoir_lane_page',f"'{lane_id}','{page['token']}'")
    def provider(request):return httpx.Response(200,json={'reply':json.dumps({'items':[]}), 'thread_id':'ahead','artifacts':[]})
    drain(sql,lane_id,page,summary_worker(sql,provider))
    assert sql('select coverage_end from public.user_lifetime_checkpoint;').stdout.strip()=='21'
    # The compatibility entry point still rejects old source snapshots; only
    # the canonical atomic commit can supply its freshly checked execution fence.
    from test_interview_work_plan_postgres import plan
    from test_agent_commit_postgres import OLD
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    legacy=rpc(sql,'save_user_interview_plan',f"{literal(identity['project_id'])},'{accepted['client_turn_id']}',{literal(plan())},'[]','{OLD}'",check=False)
    assert legacy.returncode!=0 and 'stale interview turn' in legacy.stderr
    sql("update public.user_agent_turn_lease set expires_at=clock_timestamp()-interval '1 second';")
    def foreground(request):
        packet=json.loads(json.loads(request.content)['governed']['packet'])
        assert packet['current']['sequence']==1 and packet['coverage_end']==0
        assert packet['current']['narrator']['original']=='I remember the first shop.'
        return httpx.Response(200,json={'reply':json.dumps(wire(selection_reason='latest_story')),'thread_id':'reconciled','artifacts':[]})
    with client_fixture(sql,tmp_path,monkeypatch,foreground) as client:
        response=client.post('/v1/agent/turn',json={'project_id':identity['project_id'],'text':'I remember the first shop.','client_turn_id':accepted['client_turn_id']})
        assert response.status_code==200,(response.text,sql_errors)
        retry=client.post('/v1/agent/turn',json={'project_id':identity['project_id'],'text':'I remember the first shop.','client_turn_id':accepted['client_turn_id']})
        assert retry.status_code==200 and retry.json()['cached'],retry.text
        assert retry.json()['reply_id']==response.json()['reply_id']
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='22'
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='1'


def test_foreground_keeps_explicitly_pinned_empty_checkpoint_during_preparation():
    from apps.api.lifetime_memory_service import LifetimeMemoryService
    from apps.api.lifetime_memory_context import TailCoverage
    from test_lifetime_memory_context import IDENTITY,PINS,BUDGET,source
    def rpc_call(name,**args):
        if name=='read_lifetime_pinned':return PINS.model_dump(mode='json')
        if name=='read_lifetime_source_page':return {'records':[],'complete':True}
        raise AssertionError('Optional checkpoint was re-read after pinning')
    current=source(1)
    fence={'identity':IDENTITY.model_dump(mode='json'),'policy_epoch':1}
    packet=LifetimeMemoryService(rpc_call,budget=BUDGET).assemble(fence=fence,current=current,instructions='Current policy is authoritative.',
        tail=[],tail_coverage=TailCoverage(identity=IDENTITY,policy_epoch=1,after_sequence=0,through_sequence=0,complete=True),
        interview_context={'two_lane_memory':True},accepted_checkpoint=None)
    assert packet['coverage_end']==0 and packet['checkpoint'] is None


def test_summary_transport_rejects_an_unbounded_original_window(sql,tmp_path,monkeypatch):
    from apps.api.lifetime_memory_lane_engine import build_bounded_lane_input
    from apps.api.lifetime_memory_summary import summary_packet
    from apps.api.lifetime_memory_composer import lane_model_budget
    identity,lane_id,page,_=setup_backlog(sql,tmp_path,monkeypatch)
    forged=deepcopy(page);forged['source']['text']='x'*2305
    forged['source']['char_end']=forged['source']['char_start']+2305
    forged['source']['original_length']=10000
    forged['memory_summary']['char_end']=forged['source']['char_end']
    with pytest.raises(ValueError):build_bounded_lane_input(forged,phase='summarize',packet=summary_packet(forged),budget=lane_model_budget())


def test_pending_retry_uses_current_policy_after_another_source_is_revoked(sql):
    from test_lifetime_memory_commit import prepare,commit
    identity,turn,accepted,old_fence=prepare(sql)
    other=rpc(sql,'accept_user_narrator_source',f"{literal(identity['project_id'])},'{uuid4()}','A different original'")
    rpc(sql,'change_user_narrator_source',f"{literal(identity['project_id'])},'{other['id']}',1,'withdraw',null")
    assert commit(sql,turn,old_fence,check=False).returncode!=0
    fresh=rpc(sql,'capture_lifetime_fence',f"'{identity['conversation_id']}','{old_fence['lease_token']}'")
    assert fresh['policy_epoch']>old_fence['policy_epoch']
    result=commit(sql,turn,fresh)
    assert result['memory'][0]['client_turn_id']==turn
    original=json.loads(sql('select to_jsonb(t) from public.user_interview_turn t;').stdout.strip())
    assert original['source_id']==accepted['source']['id'] and original['source_version']==1 and original['source_sequence']==1
    assert sql('select rounds_completed from public.user_recall_usage;').stdout.strip()=='1'
