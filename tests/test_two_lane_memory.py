"""Issue 70: real local SQL, bounded fake provider, no paid dispatch."""
import asyncio
from copy import deepcopy
import json
from uuid import uuid4

import httpx
import pytest

from apps.api.lifetime_memory_continuity import governed_collector_schema, validate_governed_collector_result
from test_name_only_opening import proposal
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database
from test_agent_commit_postgres import database as base_database, OWNER, OTHER, OLD, as_user
from test_shared_memory_events_postgres import rpc, literal
from test_lifetime_composer_capacity import service


@pytest.fixture(scope='module')
def database():
    yield from base_database.__wrapped__(publication_tcp=True)


TEXT = 'I grew up in Hobart and walked by the river.'
PLACE = {'place':'Hobart','hierarchy':['Earth','Australia','Tasmania','Hobart'],
         'granularity':'city','latitude':None,'longitude':None}
QUESTION = {'question':'What do you remember about those walks?', 'topic':'river walks', 'quote':'walked by the river'}


def accept(sql, text=TEXT, project=None, turn=None):
    identity=rpc(sql,'resolve_lifetime_conversation',literal(project) if project else 'null')
    accepted=rpc(sql,'accept_two_lane_interview_turn',f"{literal(identity['project_id'])},'{turn or uuid4()}',{literal(text)}")
    return identity,accepted


def lane(sql, identity):
    # Acceptance atomically wakes the existing timeline lane even if the
    # separate composer receipt has not completed its bounded coverage scan.
    return sql(f"select id from public.user_memoir_lane where user_id='{OWNER}' and project_id={literal(identity['project_id'])} and skill='timeline';").stdout.strip()



def test_flag_is_off_and_foreground_optional_place_schema_is_removed_only_when_enabled(monkeypatch):
    from apps.api.two_lane_memory import two_lanes_enabled
    monkeypatch.delenv('MEMOIR_TWO_LANES',raising=False)
    assert not two_lanes_enabled()
    assert 'place_journeys' in governed_collector_schema()['required']
    context={'two_lane_memory':True,'source':{'id':str(uuid4()),'version':1,'text':TEXT,'status':'active'}}
    assert 'place_journeys' not in governed_collector_schema(context)['properties']
    output=proposal(mode='extract',name=None)
    output['place_journeys']=[{'bad':'optional data must not invalidate the public reply'}]
    assert validate_governed_collector_result(output,context)['place_journeys']==[]


def test_acceptance_is_idempotent_and_a_failed_reply_blocks_a_different_turn(sql):
    turn=str(uuid4())
    identity,accepted=accept(sql,turn=turn)
    again=rpc(sql,'accept_two_lane_interview_turn',f"{literal(identity['project_id'])},'{turn}',{literal(TEXT)}")
    assert again['source']['id']==accepted['source']['id']
    failed=rpc(sql,'accept_two_lane_interview_turn',f"{literal(identity['project_id'])},'{uuid4()}','another turn'",check=False)
    assert failed.returncode!=0
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='1'
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='0'
    assert sql('select count(*) from public.user_lifetime_two_lane_source;').stdout.strip()=='1'


def test_background_places_candidates_and_events_share_one_fenced_page(sql):
    identity,accepted=accept(sql)
    lane_id=lane(sql,identity)
    page=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
    assert page['two_lane']['schema_version']==1
    assert page['source']['id']==accepted['source']['id']
    result={'events':[],'place_journeys':[{k:v for k,v in {**PLACE,'schema_version':1}.items() if v is not None}], 'prepared_questions':[QUESTION]}
    saved=service(sql,'commit_lifetime_memoir_lane_page',f"'{lane_id}','{page['token']}',0,{literal(result)}")
    assert saved['status']=='page_saved'
    places=rpc(sql,'read_lifetime_place_journeys',literal(identity['project_id']))
    assert places[0]['place']=='Hobart'
    candidates=rpc(sql,'read_lifetime_prepared_questions',f"'{identity['conversation_id']}'")
    assert candidates[0]['question']==QUESTION['question']
    assert candidates[0]['source_version']==1 and candidates[0]['source_id']==accepted['source']['id']
    assert candidates[0]['topic']=='river walks'
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='0'
    assert sql('select count(*) from public.user_lifetime_reply;').stdout.strip()=='0'
    assert service(sql,'commit_lifetime_memoir_lane_page',f"'{lane_id}','{page['token']}',0,{literal(result)}")=={'status':'page_saved','replayed':True}
    service(sql,'complete_lifetime_memoir_lane',f"'{lane_id}','{page['token']}'")
    assert rpc(sql,'read_lifetime_prepared_questions',f"'{identity['conversation_id']}'",owner=OTHER,check=False).returncode!=0


@pytest.mark.parametrize('change',['policy','source','generation','phase','lease'])
def test_background_cas_rejects_stale_results_and_candidate_reads(sql,change):
    identity,accepted=accept(sql)
    lane_id=lane(sql,identity)
    page=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
    if change=='policy':
        sql(as_user("update public.user_profile set profile=jsonb_build_object('memory_preferences',jsonb_build_object('excluded_topics',jsonb_build_array('river')));"))
    elif change=='source':
        rpc(sql,'change_user_narrator_source',f"{literal(identity['project_id'])},'{accepted['source']['id']}',1,'withdraw',null")
    elif change=='generation':
        sql('update public.user_lifetime_conversation set execution_generation=execution_generation+1;')
    elif change=='phase':
        rpc(sql,'change_user_conversation_phase',f"{literal(identity['project_id'])},'shape',0")
    else:
        sql('update public.user_memoir_lane set lease_until=clock_timestamp()-interval \'1 second\';')
    result={'events':[],'place_journeys':[{k:v for k,v in {**PLACE,'schema_version':1}.items() if v is not None}], 'prepared_questions':[QUESTION]}
    failed=sql(f"set role service_role;select public.commit_lifetime_memoir_lane_page('{lane_id}','{page['token']}',0,{literal(result)},'{page['page_digest']}');",check=False)
    assert failed.returncode!=0
    assert sql('select count(*) from public.user_lifetime_place_journey;').stdout.strip()=='0'
    assert rpc(sql,'read_lifetime_prepared_questions',f"'{identity['conversation_id']}'")==[]


def test_worker_capacity_reserves_an_interactive_slot_and_bounds_queue():
    from apps.api.two_lane_memory import RuntimeCapacity
    async def scenario():
        capacity=RuntimeCapacity(total=2,background=1,queue_limit=1)
        entered=asyncio.Event();release=asyncio.Event()
        async def background():
            async with capacity.slot(interactive=False):
                entered.set();await release.wait()
        running=asyncio.create_task(background());await entered.wait()
        waiting=asyncio.create_task(background());await asyncio.sleep(0)
        with pytest.raises(Exception,match='capacity'):
            async with capacity.slot(interactive=False):pass
        async with asyncio.timeout(1):
            async with capacity.slot(interactive=True):pass
        waiting.cancel();await asyncio.gather(waiting,return_exceptions=True)
        release.set();await running
        assert capacity.waiting==0
    asyncio.run(scenario())


@pytest.mark.parametrize('background_outcome',['blocked','failed'])
def test_actual_ndjson_a_is_saved_while_b_provider_is_blocked_or_failed(sql,tmp_path,monkeypatch,background_outcome):
    from types import SimpleNamespace
    from apps.api.codex_runtime import CodexRuntime
    from apps.api.lifetime_memory_composer import _extract
    from apps.api.lifetime_memory_lane_engine import LanePublication
    from apps.api.lifetime_memory_publication import TransactionalPublication
    from apps.api.lifetime_memory_runtime import LifetimePublicationContext
    from apps.api.lifetime_memory_transport import governed_turn_events, GovernedStreamingResponse
    from memoir_postgres_workflow import PostgresRest
    monkeypatch.setenv('MEMOIR_TWO_LANES','1')
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',sql.publication_dsn)
    monkeypatch.setenv('MEMORY_SPARK_SHOW_THINKING_STEPS','1')
    turn=str(uuid4());identity,accepted=accept(sql,turn=turn)
    lane_id=lane(sql,identity)
    page=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
    async def scenario():
        storage=PostgresRest(sql,OWNER).storage()
        started=asyncio.Event();release=asyncio.Event();calls=[];events=[]
        class Broker:
            async def rpc(self,name,**args):
                query=','.join(k+'=>'+literal(v) for k,v in args.items())
                return await asyncio.to_thread(lambda:json.loads(sql('set role service_role;select to_jsonb(public.'+name+'('+query+'));').stdout.splitlines()[-1]))
        async def provider(request):
            body=json.loads(request.content);calls.append(body)
            if body.get('bounded_lane'):
                started.set();await release.wait()
                if background_outcome=='failed':return httpx.Response(503)
                return httpx.Response(200,json={'reply':json.dumps({'events':[],'place_journeys':[PLACE],'prepared_questions':[QUESTION]}),'thread_id':'b','artifacts':[]})
            assert body['thread_id'] is None
            assert body['interview_context']['two_lane_memory'] is True
            assert 'place_journeys' not in governed_collector_schema(body['interview_context'])['properties']
            output=proposal(mode='extract',name=None,question='What would you like to remember about those walks?')
            output['plan']['conversation_phase']='explore'
            return httpx.Response(200,headers={'Content-Type':'application/x-ndjson'},content=json.dumps({'type':'result','data':{'reply':json.dumps(output),'thread_id':'a','artifacts':[]}})+'\n')
        transport=httpx.MockTransport(provider)
        worker=SimpleNamespace(broker=Broker(),worker_url='http://controlled.invalid',worker_secret='synthetic',
            worker_transport=transport,lane_publisher=LanePublication(sql.publication_dsn,authenticated_owner=OWNER))
        b=asyncio.create_task(_extract(page,worker))
        runtime=CodexRuntime(home_root=tmp_path,worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=transport)
        publication=LifetimePublicationContext()
        async def run(emit):
            publication.emitter=emit
            return await runtime.turn(storage,TEXT,project_id=identity['project_id'],client_turn_id=turn,
                lifetime_context=publication,on_delta=emit,on_event=emit.event)
        async def cleanup():
            await publication.close()
        response=GovernedStreamingResponse(governed_turn_events(run,cleanup=cleanup),
            publisher=TransactionalPublication(sql.publication_dsn,authenticated_owner=OWNER))
        async def send(message):
            if message.get('body'):
                for line in message['body'].splitlines():events.append(json.loads(line))
        try:
            async with asyncio.timeout(5):await started.wait()
            async with asyncio.timeout(10):await response.stream_response(send)
            assert not b.done(), 'The blocked B provider must still be waiting at the A save barrier'
            assert response.delivered
            saved=next(e['data'] for e in events if e['type']=='conversation_saved')
            result=next(e['data'] for e in events if e['type']=='result')
            assert saved['conversation_saved'] and saved['accepted_source_id']==accepted['source']['id']
            assert result['reply_id'] and result['reply_id']!=result['accepted_source_id']
            assert next(e['data'] for e in events if e['type']=='reply_complete')['reply_id']==result['reply_id']
            assert result['reply'].endswith('What would you like to remember about those walks?')
            assert ''.join(e['text'] for e in events if e['type']=='text_delta')==result['reply']
            assert not [e for e in events if e['type']=='error']
            assert len(calls)==2, 'One A call and one conditional B call; no classifier'
            assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='1'
            release.set()
            if background_outcome=='failed':
                with pytest.raises(httpx.HTTPStatusError):await b
            else:
                hints=await b
                # A changed the phase while B was in flight: that old page is
                # invalid; it must be retried from current authoritative pins.
                stale=sql(f"set role service_role;select public.commit_lifetime_memoir_lane_page('{lane_id}','{page['token']}',0,{literal(hints)},'{page['page_digest']}');",check=False)
                assert stale.returncode!=0
            assert sql('select count(*) from public.user_lifetime_place_journey;').stdout.strip()=='0'
        finally:
            release.set()
            if not b.done():b.cancel()
            await asyncio.gather(b,return_exceptions=True)
            await publication.close();storage.client.close()
    asyncio.run(scenario())


def test_complete_checkpoint20_tail21_tombstone22_current23_keeps_cursor_domains_separate():
    from uuid import UUID
    from apps.api.lifetime_memory_context import ContextCheckpoint,TailCoverage,build_context
    from apps.api.lifetime_memory_contracts import SourceManifest
    from test_lifetime_memory_context import IDENTITY,PINS,BUDGET,source
    checkpoint=ContextCheckpoint(checkpoint_id=UUID(int=700),identity=IDENTITY,policy_epoch=1,coverage_end=20,
        model=BUDGET.model,prompt_version='lifetime-v1',pinned=PINS,
        manifest=SourceManifest(identity=IDENTITY,policy_epoch=1,source_revision=20,sources=[]))
    result=build_context(identity=IDENTITY,policy_epoch=1,pinned=PINS,instructions='Current policy is authoritative.',
        current=source(23),tail=[source(21)],retrieved=[],budget=BUDGET,checkpoint=checkpoint,
        tail_coverage=TailCoverage(identity=IDENTITY,policy_epoch=1,after_sequence=20,through_sequence=22,complete=True,tombstones=[22]))
    assert result['coverage_end']==20 and [t['sequence'] for t in result['tail']]==[21]
    assert result['current']['sequence']==23 and result['current']['narrator']['version']==1
    assert not {'summary_source','summary_offset','summarised_through_seq'} & result.keys()
    with pytest.raises(ValueError,match='coverage'):
        build_context(identity=IDENTITY,policy_epoch=1,pinned=PINS,instructions='safe',current=source(23),
            tail=[],retrieved=[],budget=BUDGET,checkpoint=checkpoint,
            tail_coverage=TailCoverage(identity=IDENTITY,policy_epoch=1,after_sequence=20,through_sequence=22,complete=True,tombstones=[22]))


def test_background_checkpoint_is_bounded_resumable_and_keeps_composer_fragment_cursor(sql):
    identity,accepted=accept(sql,text='A long memory '+('原文 '*3000))
    project=identity['project_id']
    # Accepted originals may outnumber completed rounds. Do not manufacture
    # replies merely to populate a checkpoint coverage test.
    for n in range(2,23):
        rpc(sql,'accept_user_narrator_source',f"{literal(project)},'{uuid4()}',{literal(('Original words '*5000) if n==2 else 'Memory '+str(n))}")
    rpc(sql,'change_user_narrator_source',f"{literal(project)},'{accepted['source']['id']}',1,'withdraw',null")
    lane_id=lane(sql,identity)
    page=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
    before=sql('select jsonb_build_array(summary_source,summary_offset) from public.user_lifetime_lane_snapshot;').stdout.strip()
    result=service(sql,'advance_two_lane_checkpoint',f"'{lane_id}','{page['token']}',1")
    assert result['complete'] is False
    while not result['complete']:
        result=service(sql,'advance_two_lane_checkpoint',f"'{lane_id}','{page['token']}',1")
    assert result['coverage_end']==22
    checkpoint=rpc(sql,'read_lifetime_checkpoint',f"'{identity['conversation_id']}',2,'gpt-5.6-luna-pooled','lifetime-v1'")
    assert checkpoint['coverage_end']==22
    assert checkpoint['manifest']['source_revision']==23
    assert sql('select count(distinct sequence) from public.user_lifetime_covered_evidence;').stdout.strip()=='22'
    assert sql("select count(*) from public.user_lifetime_covered_evidence where status in ('withdrawn','superseded');").stdout.strip()=='1'
    assert sql('select jsonb_build_array(summary_source,summary_offset) from public.user_lifetime_lane_snapshot;').stdout.strip()==before
    assert service(sql,'advance_two_lane_checkpoint',f"'{lane_id}','{page['token']}',1")['coverage_end']==22
    assert sql('select count(*) from public.user_lifetime_checkpoint;').stdout.strip()=='1'


def test_complete_vertical_slice_background_hint_consumed_next_turn_and_replay_deduplicates(sql,tmp_path,monkeypatch):
    from types import SimpleNamespace
    from apps.api import agent_routes
    from apps.api.codex_runtime import CodexRuntime
    from apps.api.lifetime_memory_composer import execute_lifetime_lane
    from apps.api.lifetime_memory_lane_engine import LanePublication
    from apps.api.main import create_app
    from apps.api.store import MemoryStore
    from fastapi.testclient import TestClient
    from memoir_postgres_workflow import PostgresRest
    monkeypatch.setenv('MEMOIR_TWO_LANES','1');monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',sql.publication_dsn)
    packets=[]
    def provider(request):
        body=json.loads(request.content);context=body['interview_context'];packets.append(json.loads(body['governed']['packet']))
        output=proposal(mode='extract',name=None,question=QUESTION['question'])
        output['plan']['conversation_phase']='explore'
        if len(packets)>1:
            assert context['prepared_questions'][0]['source_id']==packets[0]['current']['narrator']['source_id']
            candidate=context['prepared_questions'][0]
            output['plan']['candidates'][0]['id']=candidate['id'];output['plan']['chosen_id']=candidate['id']
        return httpx.Response(200,json={'reply':json.dumps(output),'thread_id':'a-'+str(len(packets)),'artifacts':[]})
    monkeypatch.setattr(agent_routes,'authenticated_storage',lambda _:PostgresRest(sql,OWNER).storage())
    monkeypatch.setattr(agent_routes,'runtime',CodexRuntime(home_root=tmp_path,worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(provider)))
    with TestClient(create_app(MemoryStore(),story_storage_factory=lambda _:PostgresRest(sql,OWNER).storage())) as client:
        first=client.post('/v1/agent/turn',json={'text':TEXT,'client_turn_id':str(uuid4())})
        assert first.status_code==200,first.text
        project=first.json()['project_id'];identity=rpc(sql,'resolve_lifetime_conversation',literal(project))
        lane_id=lane(sql,identity);page=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
        class Broker:
            async def rpc(self,name,**args):
                query=','.join(k+'=>'+literal(v) for k,v in args.items())
                return await asyncio.to_thread(lambda:json.loads(sql('set role service_role;select to_jsonb(public.'+name+'('+query+'));').stdout.splitlines()[-1]))
        def background(request):
            assert json.loads(request.content)['bounded_lane']['phase']=='extract'
            return httpx.Response(200,json={'reply':json.dumps({'events':[],'place_journeys':[PLACE],'prepared_questions':[QUESTION]}),'thread_id':'b','artifacts':[]})
        worker=SimpleNamespace(broker=Broker(),worker_url='http://controlled.invalid',worker_secret='synthetic',
            worker_transport=httpx.MockTransport(background),lane_publisher=LanePublication(sql.publication_dsn,authenticated_owner=OWNER))
        settled=asyncio.run(execute_lifetime_lane(page,worker))
        assert settled['retrieval_complete'] is True
        read=client.get('/v1/story/readiness',params={'project_id':project})
        assert read.status_code==200,read.text
        assert read.json()['derived_workspace']['places'][0]['place']=='Hobart'
        turn=str(uuid4());payload={'project_id':project,'client_turn_id':turn,'text':'I remember the water.'}
        second=client.post('/v1/agent/turn',json=payload)
        assert second.status_code==200,second.text
        retry=client.post('/v1/agent/turn',json=payload)
        assert retry.status_code==200,retry.text
        assert retry.json()['reply_id']==second.json()['reply_id'] and retry.json()['cached']
        assert len(packets)==2
        assert rpc(sql,'read_lifetime_prepared_questions',f"'{identity['conversation_id']}'")==[]
        assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='2'
        assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='2'
        retried_b=client.post('/v1/story/memory/retry',json={'project_id':project})
        assert retried_b.status_code==200,retried_b.text
        assert retried_b.json()['status']=='pending'
        assert sql("select count(*) from public.user_memoir_lane where skill='composer';").stdout.strip()=='0'


def test_commit_failure_reports_pending_source_blocks_overlap_and_retries_same_source(sql,tmp_path,monkeypatch):
    from apps.api import agent_routes
    from apps.api.codex_runtime import CodexRuntime
    from apps.api.main import create_app
    from apps.api.store import MemoryStore
    from fastapi.testclient import TestClient
    from memoir_postgres_workflow import PostgresRest
    monkeypatch.setenv('MEMOIR_TWO_LANES','1');monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',sql.publication_dsn)
    monkeypatch.setattr(agent_routes,'authenticated_storage',lambda _:PostgresRest(sql,OWNER).storage())
    def provider(request):
        output=proposal(mode='extract',name=None);output['plan']['conversation_phase']='explore'
        return httpx.Response(200,json={'reply':json.dumps(output),'thread_id':'a','artifacts':[]})
    monkeypatch.setattr(agent_routes,'runtime',CodexRuntime(home_root=tmp_path,worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(provider)))
    sql("alter table public.user_memory add constraint issue70_save_failure check (kind<>'agent');")
    try:
        with TestClient(create_app(MemoryStore(),story_storage_factory=lambda _:PostgresRest(sql,OWNER).storage())) as client:
            payload={'text':TEXT,'client_turn_id':str(uuid4())}
            failed=client.post('/v1/agent/turn',json=payload)
            assert failed.status_code==503,failed.text
            assert failed.json()['detail']['state']=='source_accepted'
            source_id=failed.json()['detail']['accepted_source_id']
            assert sql('select count(*) from public.user_lifetime_reply;').stdout.strip()=='0'
            assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='0'
            other=client.post('/v1/agent/turn',json={**payload,'client_turn_id':str(uuid4())})
            assert other.status_code in {409,503}
            assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='1'
            sql('alter table public.user_memory drop constraint issue70_save_failure;')
            retried=client.post('/v1/agent/turn',json=payload)
            assert retried.status_code==200,retried.text
            assert retried.json()['accepted_source_id']==source_id
            assert retried.json()['reply_id']!=source_id
    finally:
        sql('alter table public.user_memory drop constraint if exists issue70_save_failure;')


def test_name_only_reply_only_skips_the_background_model_and_does_not_mark_a_question_delivered(sql,tmp_path,monkeypatch):
    from apps.api.lifetime_memory_composer import _extract
    from types import SimpleNamespace
    identity,accepted=accept(sql,text='My name is Joan')
    # A's ordinary validator is the sole work-decision authority; represent its
    # already validated and saved plan, without running another classifier.
    output=proposal(name='Joan')
    sql(f"update public.user_interview_turn set collector=jsonb_build_object('plan',{literal(output['plan'])}::jsonb);")
    lane_id=lane(sql,identity);page=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
    assert page['two_lane']['work_mode']=='reply_only'
    assert asyncio.run(_extract(page,SimpleNamespace()))=={'events':[],'place_journeys':[],'prepared_questions':[]}
    assert sql('select count(*) from public.user_lifetime_reply;').stdout.strip()=='0'
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='0'


def test_background_waits_for_the_single_collector_decision_and_recovers_after_a_failure(sql):
    from apps.api.lifetime_memory_composer import execute_lifetime_lane
    from types import SimpleNamespace
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    identity,accepted=accept(sql,text='My name is Joan')
    lane_id=lane(sql,identity);page=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
    assert page['two_lane']['work_mode']=='pending'
    class Broker:
        async def rpc(self,name,**args):
            query=','.join(k+'=>'+literal(v) for k,v in args.items())
            return json.loads(sql('set role service_role;select to_jsonb(public.'+name+'('+query+'));').stdout.splitlines()[-1])
    assert asyncio.run(execute_lifetime_lane(page,SimpleNamespace(broker=Broker())))['status']=='pending'
    assert sql('select count(*) from public.user_lifetime_source_extraction;').stdout.strip()=='0'
    sql(as_user(f"select public.release_user_agent_turn_lease('{OLD}');"))
    resumed=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
    assert resumed['two_lane']['work_mode']=='extract', 'Failed A still leaves a durable accepted source for B'


def test_burst_coalescing_concurrent_claim_crash_restart_and_old_token_are_idempotent(sql):
    from concurrent.futures import ThreadPoolExecutor
    turn=str(uuid4());identity,accepted=accept(sql,turn=turn)
    project=identity['project_id']
    for n in range(2,5):rpc(sql,'accept_user_narrator_source',f"{literal(project)},'{uuid4()}','Additional accepted original {n}'")
    # A retry wakes the same durable owner at the newest requested sequence.
    accept(sql,project=project,turn=turn)
    lane_id=lane(sql,identity)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims=list(pool.map(lambda _:service(sql,'claim_memoir_lane',f"'{lane_id}',300"),range(2)))
    assert sum(page is not None for page in claims)==1
    first=next(page for page in claims if page)
    assert first['source_high_water']==4
    service(sql,'commit_lifetime_memoir_lane_page',f"'{lane_id}','{first['token']}',0,{literal({'events':[],'place_journeys':[],'prepared_questions':[]})}")
    sql(f"update public.user_memoir_lane set lease_until=clock_timestamp()-interval '1 second' where id='{lane_id}';")
    resumed=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
    assert resumed['token']!=first['token'] and resumed['page_number']==1
    assert resumed['source']['sequence']==2
    stale=sql(f"set role service_role;select public.commit_lifetime_memoir_lane_page('{lane_id}','{first['token']}',0,'{{\"events\":[]}}','{first['page_digest']}');",check=False)
    assert stale.returncode!=0
    while not resumed['complete']:
        service(sql,'commit_lifetime_memoir_lane_page',f"'{lane_id}','{resumed['token']}',{resumed['page_number']},'{json.dumps({'events':[]})}'")
        resumed=service(sql,'read_lifetime_memoir_lane_page',f"'{lane_id}','{resumed['token']}'")
    service(sql,'complete_lifetime_memoir_lane',f"'{lane_id}','{resumed['token']}'")
    assert sql(f"select target_source||':'||successful_source from public.user_memoir_lane where id='{lane_id}';").stdout.strip()=='4:4'
    assert sql('select count(*) from public.user_lifetime_source_extraction;').stdout.strip()=='4'
    assert sql("select count(*) from public.user_lifetime_memory_obligation where kind='source_projection';").stdout.strip()=='4'
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='0'
