"""Native plan authority, shadow isolation, version fences and delivered outcomes."""
import json
from uuid import uuid4
import pytest
from test_two_lane_memory import (database,sql,event_database,private_database,attachment_database,
    enable_only_disposable_database_rollout,accept,lane,service,QUESTION)
from test_shared_memory_events_postgres import rpc,literal
from test_agent_commit_postgres import OWNER,OTHER,as_user


def setup(sql,*,shadow=True,text='I cannot remember if the shop came before the move.'):
    sql("update public.lifetime_two_lane_rollout set strategy_enabled=true,strategy_shadow="+str(shadow).lower()+';')
    identity,accepted=accept(sql,text=text);lane_id=lane(sql,identity)
    page=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
    return identity,accepted,lane_id,page


def commit(sql,lane_id,page,strategy='shape',question='Was the shop before or after the move?'):
    result={'events':[],'place_journeys':[],'prepared_questions':[{'question':question,'topic':'chronology','quote':page['source']['text']}],
        'strategy_proposal':{'strategy':strategy,'objective':'clarify_order' if strategy=='shape' else 'follow_story','focus_event_ids':[]}}
    return service(sql,'commit_lifetime_memoir_lane_page',f"'{lane_id}','{page['token']}',{page['page_number']},{literal(result)}")


def test_shadow_plan_never_becomes_the_real_interview_strategy_or_a_preference(sql):
    identity,accepted,lane_id,page=setup(sql)
    commit(sql,lane_id,page)
    state=rpc(sql,'read_lifetime_strategy_context',f"'{identity['conversation_id']}'")
    assert state['mode']=='shadow' and state['plan'] is None
    assert rpc(sql,'read_lifetime_prepared_questions',f"'{identity['conversation_id']}'")==[], 'Shadow candidates must not reach the legacy foreground indirectly'
    assert sql('select shadow from public.user_lifetime_interview_strategy;').stdout.strip()=='t'
    assert sql("select count(*) from pg_tables where schemaname='public' and tablename='user_conversation_phase_archive';").stdout.strip()=='0'
    assert sql("select count(*) from public.user_memoir_lane where skill='composer';").stdout.strip()=='0'
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='0'


def test_automatic_internal_shape_is_persisted_without_a_user_mode_or_composition(sql):
    identity,accepted,lane_id,page=setup(sql,shadow=False)
    commit(sql,lane_id,page)
    state=rpc(sql,'read_lifetime_strategy_context',f"'{identity['conversation_id']}'")
    from apps.api.interview_strategy import InterviewStrategyPlan
    plan=InterviewStrategyPlan.model_validate(state['plan'])
    assert plan.strategy=='shape' and plan.plan_revision==1
    assert plan.based_on_sequence==accepted['source']['sequence']
    assert sql("select count(*) from pg_tables where schemaname='public' and tablename='user_conversation_phase_archive';").stdout.strip()=='0'
    # A later session and a finished worker reload the same durable plan.
    service(sql,'complete_lifetime_memoir_lane',f"'{lane_id}','{page['token']}'")
    assert rpc(sql,'read_lifetime_strategy_context',f"'{identity['conversation_id']}'")['plan']==state['plan']
    saved=json.loads(sql('select data from public.user_lifetime_interview_strategy;').stdout)
    assert saved['strategy']=='shape' and saved['objective']=='clarify_order'
    assert 'checkpoint_id' in saved and saved['snapshot_id']==page['snapshot_id']
    assert rpc(sql,'read_lifetime_strategy_context',f"'{identity['conversation_id']}'",owner=OTHER,check=False).returncode!=0
    assert sql(as_user('select * from public.user_lifetime_interview_strategy;'),check=False).returncode!=0
    assert sql("select count(*) from public.user_memoir_lane where skill='composer';").stdout.strip()=='0'


@pytest.mark.parametrize('change',['policy','generation','source','rollout','plan_revision'])
def test_late_planner_is_fenced_and_leaves_the_previous_plan_unchanged(sql,change):
    identity,accepted,lane_id,page=setup(sql,shadow=False)
    if change=='policy':sql(as_user("update public.user_profile set profile=jsonb_build_object('memory_preferences',jsonb_build_object('excluded_topics',jsonb_build_array('shop')));"))
    elif change=='generation':sql('update public.user_lifetime_conversation set execution_generation=execution_generation+1;')
    elif change=='source':rpc(sql,'change_user_narrator_source',f"{literal(identity['project_id'])},'{accepted['source']['id']}',1,'withdraw',null")
    elif change=='rollout':sql('update public.lifetime_two_lane_rollout set strategy_enabled=false;')
    else:sql("update public.lifetime_two_lane_rollout set strategy_shadow=true;")
    with pytest.raises(AssertionError):commit(sql,lane_id,page)
    assert sql('select count(*) from public.user_lifetime_interview_strategy;').stdout.strip()=='0'


def test_strategy_receipt_replays_full_proposal_and_rejects_changed_retry(sql):
    identity,accepted,lane_id,page=setup(sql,shadow=False)
    first=commit(sql,lane_id,page)
    replay=commit(sql,lane_id,page)
    assert replay=={'status':'page_saved','replayed':True}
    with pytest.raises(AssertionError):commit(sql,lane_id,page,strategy='explore')
    assert sql('select count(*) from public.user_lifetime_interview_strategy;').stdout.strip()=='1'
    assert sql('select count(*) from public.user_lifetime_source_extraction;').stdout.strip()=='1'


def test_out_of_order_plan_revision_is_in_the_exact_page_digest(sql):
    identity,accepted,lane_id,page=setup(sql,shadow=False)
    sql(f"insert into public.user_lifetime_strategy_frontier(user_id,project_id,revision) values('{OWNER}',{literal(identity['project_id'])},9);")
    with pytest.raises(AssertionError):commit(sql,lane_id,page)
    assert sql('select count(*) from public.user_lifetime_interview_strategy;').stdout.strip()=='0'


def test_empty_reply_only_plan_uses_no_background_provider(sql):
    import asyncio
    from types import SimpleNamespace
    from apps.api.lifetime_memory_composer import _extract
    identity,accepted,lane_id,page=setup(sql,shadow=False,text='My name is Joan')
    sql("update public.user_interview_turn set collector=jsonb_build_object('plan',jsonb_build_object('work',jsonb_build_object('mode','reply_only','name','Joan')));")
    page=service(sql,'read_lifetime_memoir_lane_page',f"'{lane_id}','{page['token']}'")
    result=asyncio.run(_extract(page,SimpleNamespace()))
    assert result['prepared_questions']==[] and result['events']==[]
    assert result['strategy_proposal'] is None
    service(sql,'commit_lifetime_memoir_lane_page',f"'{lane_id}','{page['token']}',0,{literal(result)}")
    assert rpc(sql,'read_lifetime_strategy_context',f"'{identity['conversation_id']}'")['plan'] is None


def test_pool_allows_five_grounded_candidates_without_a_filler_minimum(sql):
    identity,accepted,lane_id,page=setup(sql,shadow=False)
    result={'events':[],'place_journeys':[],'prepared_questions':[{'question':f'Which detail {n} do you recall?', 'topic':'shop','quote':page['source']['text']} for n in range(5)],
        'strategy_proposal':{'strategy':'explore','objective':'follow_story','focus_event_ids':[]}}
    service(sql,'commit_lifetime_memoir_lane_page',f"'{lane_id}','{page['token']}',0,{literal(result)}")
    assert len(rpc(sql,'read_lifetime_strategy_context',f"'{identity['conversation_id']}'")['plan']['candidates'])==5


def test_correction_or_privacy_invalidation_removes_plan_bytes_without_resetting_strategy_hint(sql):
    identity,accepted,lane_id,page=setup(sql,shadow=False)
    commit(sql,lane_id,page)
    rpc(sql,'change_user_narrator_source',f"{literal(identity['project_id'])},'{accepted['source']['id']}',1,'withdraw',null")
    state=rpc(sql,'read_lifetime_strategy_context',f"'{identity['conversation_id']}'")
    assert state['plan'] is None and state['planned_strategy_hint']=='shape'
    assert sql('select count(*) from public.user_lifetime_interview_strategy;').stdout.strip()=='0'


def test_background_correction_commits_without_republishing_the_invalidated_strategy(sql,tmp_path,monkeypatch):
    import httpx
    from test_interview_strategy_runtime import client_fixture
    from test_interview_strategy import wire
    def provider(request):
        source = json.loads(request.content)['interview_context']['source']['text']
        reason = 'current_correction' if source.startswith('Correction:') else 'latest_story'
        return httpx.Response(200,json={'reply':json.dumps(wire(selection_reason=reason)),'thread_id':'synthetic','artifacts':[]})
    client=client_fixture(sql,tmp_path,monkeypatch,provider)
    with client:
        response=client.post('/v1/agent/turn',json={'text':'I started school in 1960.','client_turn_id':str(uuid4())})
        assert response.status_code==200,response.text
        project=response.json()['project_id']
        lane_id=sql(f"select id from public.user_memoir_lane where project_id={literal(project)} and skill='timeline';").stdout.strip()
        first=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
        def ref(page):
            source=page['source']
            return {'source_id':source['id'],'version':source['version'],'quote':source['text'],
                'char_start':source['char_start'],'char_end':source['char_end']}
        event={'kind':'event','title':'School','source_refs':[ref(first)],'temporal':{
            'expression':'1960','precision':'year','year_start':1960,'year_end':1960,'basis':[ref(first)]}}
        result={'events':[event],'place_journeys':[],'prepared_questions':[],
            'strategy_proposal':{'strategy':'explore','objective':'follow_story','focus_event_ids':[]}}
        service(sql,'commit_lifetime_memoir_lane_page',f"'{lane_id}','{first['token']}',0,{literal(result)}")
        service(sql,'complete_lifetime_memoir_lane',f"'{lane_id}','{first['token']}'")
        response=client.post('/v1/agent/turn',json={'project_id':project,'text':'Correction: I started school in 1970.','client_turn_id':str(uuid4())})
        assert response.status_code==200,response.text
    page=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
    saved=page['events'][0]
    result['events']=[{**event,'existing_id':saved['id'],'expected_revision':saved['revision'],
        'source_refs':[ref(page)],'correction':ref(page),'temporal':{
            'expression':'1970','precision':'year','year_start':1970,'year_end':1970,'basis':[ref(page)]}}]
    saved=service(sql,'commit_lifetime_memoir_lane_page',
        f"'{lane_id}','{page['token']}',{page['page_number']},{literal(result)}")
    assert saved['status']=='page_saved' and saved['policy_changed'] is True
    assert sql("select data->'temporal'->>'year_start' from public.user_memory_event;").stdout.strip()=='1970'
    assert sql('select count(*) from public.user_lifetime_interview_strategy;').stdout.strip()=='0'
    release=f"'{lane_id}','{page['token']}','{OWNER}',{literal(project)},'{page['conversation_id']}'"
    with pytest.raises(AssertionError):
        service(sql,'read_lifetime_memoir_lane_page',f"'{lane_id}','{page['token']}'")
    service(sql,'yield_lifetime_memoir_lane_metadata',release)
    resumed=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
    assert resumed['policy_epoch']>page['policy_epoch'] and resumed['token']!=page['token']
    with pytest.raises(AssertionError):service(sql,'yield_lifetime_memoir_lane_metadata',release)


@pytest.mark.parametrize('invalid',['duplicate_questions','multiple_questions','duplicate_focus'])
def test_application_commit_rejects_malformed_candidate_pool_even_without_python_adapter(sql,invalid):
    identity,accepted,lane_id,page=setup(sql,shadow=False)
    question={'question':'Was it before the move?','topic':'move','quote':page['source']['text']}
    result={'events':[],'place_journeys':[],'prepared_questions':[question],
        'strategy_proposal':{'strategy':'explore','objective':'follow_story','focus_event_ids':[]}}
    if invalid=='duplicate_questions':result['prepared_questions'].append(question)
    elif invalid=='multiple_questions':result['prepared_questions'][0]['question']='Was it before? Or was it after?'
    else:
        # Duplicate nonexistent IDs are already rejected by scoped event lookup.
        result['strategy_proposal']['focus_event_ids']=['unknown','unknown']
    with pytest.raises(AssertionError):
        service(sql,'commit_lifetime_memoir_lane_page',f"'{lane_id}','{page['token']}',0,{literal(result)}")
    assert sql('select count(*) from public.user_lifetime_interview_strategy;').stdout.strip()=='0'
