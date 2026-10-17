"""Native source-backed strategy turns; only the provider transport is controlled."""
import json
from uuid import uuid4
import httpx
import pytest
from test_interview_strategy_postgres import (database,sql,event_database,private_database,attachment_database,
    enable_only_disposable_database_rollout,setup,commit)
from test_two_lane_memory import accept,lane,service,proposal
from test_shared_memory_events_postgres import rpc,literal
from test_agent_commit_postgres import OWNER
from test_interview_strategy import wire


def client_fixture(sql,tmp_path,monkeypatch,provider):
    from apps.api import agent_routes
    from apps.api.codex_runtime import CodexRuntime
    from apps.api.main import create_app
    from apps.api.store import MemoryStore
    from fastapi.testclient import TestClient
    from memoir_postgres_workflow import PostgresRest
    monkeypatch.setenv('MEMOIR_TWO_LANES','1');monkeypatch.setenv('MEMOIR_INTERVIEW_STRATEGY','1')
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION','two-lane-v1')
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',sql.publication_dsn)
    sql('update public.lifetime_two_lane_rollout set strategy_enabled=true,strategy_shadow=false;')
    monkeypatch.setattr(agent_routes,'authenticated_storage',lambda _:PostgresRest(sql,OWNER).storage())
    def transport(request):
        response=provider(request)
        if request.headers.get('accept')=='application/x-ndjson' and response.status_code==200:
            output=response.json()
            return httpx.Response(200,headers={'content-type':'application/x-ndjson'},content='\n'.join(json.dumps(event) for event in [
                {'type':'text_delta','text':output['reply']},{'type':'provider_complete','data':output},{'type':'result','data':output}])+'\n')
        return response
    monkeypatch.setattr(agent_routes,'runtime',CodexRuntime(home_root=tmp_path,worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(transport)))
    return TestClient(create_app(MemoryStore()))


@pytest.mark.parametrize('text,language,place,mode,name',[
    ('I grew up in Hobart and walked by the river.','en-AU',
     {'place':'Hobart','hierarchy':['Earth','Australia','Hobart'],'granularity':'city','latitude':None,'longitude':None},'extract',None),
    ('我叫慧博，现在生活在悉尼，但是我于1983年4月出生在河北省承德市附属医院','zh-CN',
     {'place':'承德市','hierarchy':['Earth','中国','河北省','承德市'],'granularity':'city','latitude':None,'longitude':None},'extract',None),
    ('My name is Joan','en-AU',None,'reply_only','Joan'),
])
def test_strategy_prompt_preserves_work_routing_and_background_map(sql,tmp_path,monkeypatch,text,language,place,mode,name):
    from types import SimpleNamespace
    from apps.api.lifetime_memory_composer import _extract
    from apps.api.lifetime_memory_lane_engine import LanePublication
    calls=[]
    def provider(request):
        body=json.loads(request.content)
        instructions=json.loads(body['governed']['packet'])['instructions']
        assert 'Use "extract" when' in instructions
        assert 'work.mode' in instructions and 'work.name' in instructions
        assert 'plan.work' not in instructions
        output=wire(selection_reason='latest_story',work={'mode':mode,'name':name})
        return httpx.Response(200,json={'reply':json.dumps(output),'thread_id':'work-routing','artifacts':[]})
    with client_fixture(sql,tmp_path,monkeypatch,provider) as client:
        response=client.post('/v1/agent/turn',json={'text':text,'language':language,'client_turn_id':str(uuid4())})
        assert response.status_code==200,response.text
        assert response.json()['conversation_saved']
    identity=rpc(sql,'resolve_lifetime_conversation',literal(response.json()['project_id']))
    lane_id=lane(sql,identity);page=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
    assert page['two_lane']['work_mode']==mode
    class Broker:
        async def rpc(self,rpc_name,**args):
            query=','.join(k+'=>'+literal(v) for k,v in args.items())
            return json.loads(sql('set role service_role;select to_jsonb(public.'+rpc_name+'('+query+'));').stdout.splitlines()[-1])
    def background(request):
        calls.append(request)
        result={'events':[],'place_journeys':[place],'prepared_questions':[],
            'strategy_proposal':{'strategy':'explore','objective':'follow_story','focus_event_ids':[]}}
        return httpx.Response(200,json={'reply':json.dumps(result),'thread_id':'background-map','artifacts':[]})
    worker=SimpleNamespace(broker=Broker(),worker_url='http://controlled.invalid',worker_secret='synthetic',
        worker_transport=httpx.MockTransport(background),lane_publisher=LanePublication(sql.publication_dsn,authenticated_owner=OWNER))
    import asyncio
    result=asyncio.run(_extract(page,worker))
    assert len(calls)==(1 if place else 0)
    service(sql,'commit_lifetime_memoir_lane_page',f"'{lane_id}','{page['token']}',0,{literal(result)}")
    places=rpc(sql,'read_lifetime_place_journeys',literal(identity['project_id']))
    assert [item['place'] for item in places]==([place['place']] if place else [])


@pytest.mark.parametrize('strategy',['comfort','explore','shape'])
def test_active_full_turn_saves_one_question_and_records_only_actual_delivery(sql,tmp_path,monkeypatch,caplog,strategy):
    calls=[]
    def provider(request):
        body=json.loads(request.content);calls.append(body);context=body['interview_context']
        assert context['strategy_selector'] and context['active_strategy'] in {'comfort','explore','shape'}
        packet=json.loads(body['governed']['packet'])
        assert packet['instructions'].count('Active internal strategy:')==1
        return httpx.Response(200,json={'reply':json.dumps(wire(selection_reason='latest_story',used_strategy=strategy)), 'thread_id':'controlled','artifacts':[]})
    import logging
    caplog.set_level(logging.INFO,logger='memoir.strategy.metrics')
    with client_fixture(sql,tmp_path,monkeypatch,provider) as client:
        payload={'text':'The garden was by the river in Hobart.','client_turn_id':str(uuid4())}
        response=client.post('/v1/agent/turn',json=payload,headers={'accept':'application/x-ndjson'})
        assert response.status_code==200,response.text
        events=[json.loads(x) for x in response.text.splitlines()]
        assert events[-1]['type']=='result',response.text
        saved=events[-1]['data'];assert saved['conversation_saved']
        assert 'strategy' not in saved
        payload['project_id']=saved['project_id']
        retry=client.post('/v1/agent/turn',json=payload)
        assert retry.status_code==200 and retry.json()['cached'],retry.text
    assert len(calls)==1
    state=json.loads(sql('select to_jsonb(o) from public.user_lifetime_strategy_outcome o;').stdout.strip())
    assert state['delivered'] and state['question_delivered']=='What do you enjoy growing?'
    assert state['used_strategy']==strategy and state['selected_candidate_id'] is None
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='1'
    assert sql("select count(*) from public.user_memoir_lane where skill='composer';").stdout.strip()=='0'
    metrics=[json.loads(r.message) for r in caplog.records if r.name=='memoir.strategy.metrics']
    assert metrics and metrics[0]['delivered'] is True
    assert metrics[0]['time_to_first_meaningful_text_ms'] is not None
    assert 'Hobart' not in json.dumps(metrics) and 'growing' not in json.dumps(metrics)
    assert metrics[0]['actual_usage'] is None


@pytest.mark.parametrize('text,reason,strategy,question,stopped',[
 ('My name is Joan','no_plan','comfort','Where would you like to begin?',False),
 ('I grew up by the river and my mother planted a garden.','latest_story','explore','What did you grow?',False),
 ('Yes.','latest_story','explore','What happened next?',False),
 ("Let’s talk about my garden.",'user_redirect','explore','What did you grow?',False),
 ('Keep it gentle; a lighter question.','pacing','comfort','What colour do you remember?',False),
 ('Not today.','pause','comfort',None,True),
 ('I meant 1962, not 1960.','current_correction','shape','Was the shop before the move?',False),
 ('We can continue the garden story.','return_context','explore','What happened next?',False),
 ('What happens to my memories?','direct_answer','comfort',None,False),
 ('我小时候和母亲一起去河边散步。','latest_story','explore','您还记得河边的什么？',False),
 ('今天不聊了。','pause','comfort',None,True),
 ('He said, "organise my story".','latest_story','explore','What did he mean?',False),
 ("I'm done.",'direct_answer','comfort',None,False),
])
def test_current_intent_matrix_uses_one_call_without_composition_permissions(sql,tmp_path,monkeypatch,text,reason,strategy,question,stopped):
    calls=[]
    def provider(request):
        body=json.loads(request.content);calls.append(body)
        output=wire(question=question,selection_reason=reason,used_strategy=strategy,stopped=stopped)
        if reason in {'no_plan','pause','direct_answer'}:output['work']={'mode':'reply_only','name':'Joan' if text.startswith('My name') else None}
        return httpx.Response(200,json={'reply':json.dumps(output),'thread_id':'intent','artifacts':[]})
    with client_fixture(sql,tmp_path,monkeypatch,provider) as client:
        response=client.post('/v1/agent/turn',json={'text':text,'client_turn_id':str(uuid4())})
        assert response.status_code==200,response.text
        saved=response.json();assert saved['conversation_saved']
    assert len(calls)==1
    state=json.loads(sql('select to_jsonb(o) from public.user_lifetime_strategy_outcome o;').stdout.strip())
    assert state['delivered'] and state['selection_reason']==reason and state['used_strategy']==strategy
    assert state['question_delivered']==question
    assert sql("select count(*) from public.user_memoir_lane where skill='composer';").stdout.strip()=='0'
    if text=='Yes.':assert 'legacy_strategy' not in calls[0]['interview_context']


@pytest.mark.parametrize('planned_strategy',['comfort','explore','shape'])
def test_accepted_plan_is_selected_once_and_a_redirect_does_not_rewrite_it(sql,tmp_path,monkeypatch,planned_strategy):
    calls=[]
    def provider(request):
        body=json.loads(request.content);calls.append(body);state=body['interview_context']['strategy_context']
        if len(calls)==1:
            output=wire(selection_reason='latest_story')
        elif len(calls)==2:
            assert state['plan']['strategy']==planned_strategy
            assert body['interview_context']['active_strategy']==planned_strategy
            assert state['prior_delivered_question']=='What do you enjoy growing?'
            output=wire(question=plan['candidates'][0]['question'],selected_candidate_id=plan['candidates'][0]['id'],selection_reason='prepared_candidate',used_strategy=planned_strategy)
        else:
            assert not (state['plan'] or {}).get('candidates')
            output=wire()
        return httpx.Response(200,json={'reply':json.dumps(output),'thread_id':'select-'+str(len(calls)),'artifacts':[]})
    with client_fixture(sql,tmp_path,monkeypatch,provider) as client:
        first=client.post('/v1/agent/turn',json={'text':'The shop came before the move.','client_turn_id':str(uuid4())})
        assert first.status_code==200,first.text
        identity=rpc(sql,'resolve_lifetime_conversation',literal(first.json()['project_id']))
        lane_id=lane(sql,identity);page=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
        commit(sql,lane_id,page,strategy=planned_strategy)
        plan=rpc(sql,'read_lifetime_strategy_context',f"'{identity['conversation_id']}'")['plan']
        for text in ['Please go on.',"Let's talk about my garden."]:
            response=client.post('/v1/agent/turn',json={'project_id':identity['project_id'],'text':text,'client_turn_id':str(uuid4())})
            assert response.status_code==200,response.text
    assert len(calls)==3
    assert sql('select count(*) from public.user_lifetime_interview_strategy;').stdout.strip()=='1'
    assert sql("select data->>'strategy' from public.user_lifetime_interview_strategy;").stdout.strip()==planned_strategy
    assert sql("select count(*) from public.user_lifetime_strategy_outcome where delivered and selected_candidate_id is not null;").stdout.strip()=='1'


def test_saved_but_failed_send_does_not_mark_candidate_asked_and_retry_recovers(sql,tmp_path,monkeypatch):
    import asyncio
    from apps.api.codex_runtime import CodexRuntime
    from apps.api.lifetime_memory_runtime import lifetime_http_turn
    from memoir_postgres_workflow import PostgresRest
    calls=[]
    def provider(request):
        body=json.loads(request.content);calls.append(body)
        plan=(body['interview_context'].get('strategy_context') or {}).get('plan')
        output=wire(selection_reason='latest_story') if plan is None else wire(question=plan['candidates'][0]['question'],
            selected_candidate_id=plan['candidates'][0]['id'],selection_reason='prepared_candidate',used_strategy='shape')
        return httpx.Response(200,json={'reply':json.dumps(output),'thread_id':'delivery-'+str(len(calls)),'artifacts':[]})
    with client_fixture(sql,tmp_path,monkeypatch,provider) as client:
        first=client.post('/v1/agent/turn',json={'text':'The shop came before the move.','client_turn_id':str(uuid4())})
        assert first.status_code==200,first.text
        identity=rpc(sql,'resolve_lifetime_conversation',literal(first.json()['project_id']))
        lane_id=lane(sql,identity);page=service(sql,'claim_memoir_lane',f"'{lane_id}',300");commit(sql,lane_id,page)
        turn=str(uuid4());options={'project_id':identity['project_id'],'client_turn_id':turn}
        runtime=CodexRuntime(home_root=tmp_path,worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(provider))
        async def scenario():
            response=await lifetime_http_turn(runtime,PostgresRest(sql,OWNER).storage(),'Please go on.',accept='application/json',options=options)
            assert sql(f"select delivered from public.user_lifetime_strategy_outcome where client_turn_id='{turn}';").stdout.strip()=='f'
            async def receive():return {'type':'http.disconnect'}
            async def send(message):
                if message['type']=='http.response.body':raise OSError('synthetic closed socket')
            with pytest.raises(OSError):await response({'type':'http','asgi':{'spec_version':'2.4'}},receive,send)
            assert not response.delivered
        asyncio.run(scenario())
        state=rpc(sql,'read_lifetime_strategy_context',f"'{identity['conversation_id']}'")
        assert len(state['plan']['candidates'])==1,'Saved but undelivered question must not count as asked'
        retry=client.post('/v1/agent/turn',json={**options,'text':'Please go on.'})
        assert retry.status_code==200 and retry.json()['cached'],retry.text
    assert len(calls)==2
    assert sql(f"select delivered from public.user_lifetime_strategy_outcome where client_turn_id='{turn}';").stdout.strip()=='t'
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='2'


@pytest.mark.parametrize('rollback',['shadow','python_flag','database_flag'])
def test_rollback_uses_collector_schema_without_restoring_user_modes(sql,tmp_path,monkeypatch,rollback):
    calls=[]
    def provider(request):
        body=json.loads(request.content);calls.append(body)
        assert not body['interview_context'].get('strategy_selector')
        assert 'conversation_phase' not in body['interview_context']
        return httpx.Response(200,json={'reply':json.dumps(proposal(mode='extract',name=None)), 'thread_id':'legacy','artifacts':[]})
    with client_fixture(sql,tmp_path,monkeypatch,provider) as client:
        identity=rpc(sql,'resolve_lifetime_conversation','null')
        if rollback=='shadow':sql('update public.lifetime_two_lane_rollout set strategy_shadow=true;')
        elif rollback=='database_flag':sql('update public.lifetime_two_lane_rollout set strategy_enabled=false;')
        else:monkeypatch.setenv('MEMOIR_INTERVIEW_STRATEGY','0')
        response=client.post('/v1/agent/turn',json={'project_id':identity['project_id'],'text':'The garden had roses.','client_turn_id':str(uuid4())})
        assert response.status_code==200,response.text
    assert len(calls)==1
    assert sql('select count(*) from public.user_lifetime_strategy_outcome;').stdout.strip()=='0'
    assert sql('select count(*) from public.user_conversation_phase_archive;').stdout.strip()=='0'


@pytest.mark.parametrize('background',['blocked','failed'])
def test_active_selector_finishes_actual_send_while_planner_transport_is_stalled(sql,tmp_path,monkeypatch,background):
    import asyncio
    from types import SimpleNamespace
    from apps.api.codex_runtime import CodexRuntime
    from apps.api.lifetime_memory_runtime import lifetime_http_turn
    from apps.api.lifetime_memory_composer import _extract
    from apps.api.lifetime_memory_lane_engine import LanePublication
    from memoir_postgres_workflow import PostgresRest
    monkeypatch.setenv('MEMOIR_TWO_LANES','1');monkeypatch.setenv('MEMOIR_INTERVIEW_STRATEGY','1')
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION','two-lane-v1')
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',sql.publication_dsn)
    identity,accepted,lane_id,page=setup(sql,shadow=False,text='The shop came before the move.')
    async def scenario():
        started=asyncio.Event();release=asyncio.Event();calls=[]
        async def provider(request):
            body=json.loads(request.content);calls.append(body)
            if body.get('bounded_lane'):
                started.set();await release.wait()
                if background=='failed':return httpx.Response(503)
                output={'events':[],'place_journeys':[],'prepared_questions':[],
                    'strategy_proposal':{'strategy':'shape','objective':'clarify_order','focus_event_ids':[]}}
            else:
                assert body['thread_id'] is None and body['interview_context']['strategy_selector']
                output=wire(selection_reason='latest_story')
            return httpx.Response(200,json={'reply':json.dumps(output),'thread_id':'barrier','artifacts':[]})
        class Broker:
            async def rpc(self,name,**args):
                query=','.join(k+'=>'+literal(v) for k,v in args.items())
                return await asyncio.to_thread(lambda:json.loads(sql('set role service_role;select to_jsonb(public.'+name+'('+query+'));').stdout.splitlines()[-1]))
        transport=httpx.MockTransport(provider)
        worker=SimpleNamespace(broker=Broker(),worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=transport,
            lane_publisher=LanePublication(sql.publication_dsn,authenticated_owner=OWNER))
        job=asyncio.create_task(_extract(page,worker))
        try:
            async with asyncio.timeout(5):await started.wait()
            runtime=CodexRuntime(home_root=tmp_path,worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=transport)
            response=await lifetime_http_turn(runtime,PostgresRest(sql,OWNER).storage(),page['source']['text'],accept='application/json',
                options={'project_id':identity['project_id'],'client_turn_id':accepted['client_turn_id']})
            async def send(_):pass
            async def receive():return {'type':'http.disconnect'}
            await response({'type':'http','asgi':{'spec_version':'2.4'}},receive,send)
            assert response.delivered and not job.done()
            assert sql('select delivered from public.user_lifetime_strategy_outcome;').stdout.strip()=='t'
            assert len(calls)==2
            release.set()
            if background=='failed':
                with pytest.raises(httpx.HTTPStatusError):await job
            else:assert (await job)['strategy_proposal']['strategy']=='shape'
        finally:
            release.set()
            if not job.done():job.cancel()
            await asyncio.gather(job,return_exceptions=True)
    asyncio.run(scenario())
