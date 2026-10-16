"""Second independent review: optional planner races and clause-scoped controls."""
import json
from uuid import uuid4
import httpx
import pytest
from test_interview_strategy_runtime import client_fixture
from test_interview_strategy_postgres import (database,sql,event_database,private_database,attachment_database,
    enable_only_disposable_database_rollout,commit)
from test_two_lane_memory import lane,service
from test_shared_memory_events_postgres import rpc,literal
from test_agent_commit_postgres import as_user
from test_interview_strategy import wire


def seed_plan(client,sql):
    response=client.post('/v1/agent/turn',json={'text':'The shop came before the move.','client_turn_id':str(uuid4())})
    assert response.status_code==200,response.text
    identity=rpc(sql,'resolve_lifetime_conversation',literal(response.json()['project_id']))
    lane_id=lane(sql,identity);page=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
    return identity,lane_id,page


@pytest.mark.parametrize('previous_plan',[False,True])
def test_optional_newer_planner_cannot_abort_a_turn_using_its_pinned_plan(sql,tmp_path,monkeypatch,previous_plan):
    calls=[];background={}
    def provider(request):
        body=json.loads(request.content);calls.append(body);state=body['interview_context']['strategy_context']
        if background.get('commit_during_a'):
            pinned=state['plan'];before=pinned['plan_revision'] if pinned else None
            commit(sql,background['lane_id'],background['page'],question='What happened after that move?')
            newest=rpc(sql,'read_lifetime_strategy_context',f"'{background['identity']['conversation_id']}'")['plan']
            assert newest['plan_revision']!=(before or 0)
            if previous_plan:
                question=pinned['candidates'][0]
                output=wire(question=question['question'],selected_candidate_id=question['id'],selection_reason='prepared_candidate',used_strategy='shape')
            else:output=wire(selection_reason='latest_story')
        else:output=wire(selection_reason='latest_story')
        return httpx.Response(200,json={'reply':json.dumps(output),'thread_id':'race-'+str(len(calls)),'artifacts':[]})
    with client_fixture(sql,tmp_path,monkeypatch,provider) as client:
        identity,lane_id,page=seed_plan(client,sql)
        if previous_plan:
            commit(sql,lane_id,page)
            service(sql,'complete_lifetime_memoir_lane',f"'{lane_id}','{page['token']}'")
            response=client.post('/v1/agent/turn',json={'project_id':identity['project_id'],'text':'The garden had roses.','client_turn_id':str(uuid4())})
            assert response.status_code==200,response.text
            page=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
            assert page['source']['sequence']==2
        background.update(commit_during_a=True,identity=identity,lane_id=lane_id,page=page)
        turn=str(uuid4())
        response=client.post('/v1/agent/turn',json={'project_id':identity['project_id'],'text':'Please go on.','client_turn_id':turn})
        assert response.status_code==200,response.text
        assert response.json()['conversation_saved']
    outcome=json.loads(sql(f"select to_jsonb(o) from public.user_lifetime_strategy_outcome o where client_turn_id='{turn}';").stdout.strip())
    assert outcome['plan_revision_seen']==(1 if previous_plan else None)
    assert outcome['delivered']
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()==('3' if previous_plan else '2')


def test_real_policy_change_still_aborts_a_pinned_turn(sql,tmp_path,monkeypatch):
    def provider(request):
        sql(as_user("update public.user_profile set profile=jsonb_build_object('memory_preferences',jsonb_build_object('excluded_topics',jsonb_build_array('garden')));"))
        return httpx.Response(200,json={'reply':json.dumps(wire(selection_reason='latest_story')),'thread_id':'restricted','artifacts':[]})
    with client_fixture(sql,tmp_path,monkeypatch,provider) as client:
        response=client.post('/v1/agent/turn',json={'text':'I remember the garden.','client_turn_id':str(uuid4())})
        assert response.status_code!=200,response.text
    assert sql('select count(*) from public.user_lifetime_reply;').stdout.strip()=='0'
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='0'


@pytest.mark.parametrize('text,reason',[
 ("My father said the shop was nearby. Let’s talk about my garden.",'user_redirect'),
 ('My father said it was nearby. Not today.','pause'),
 ('My father said it was nearby. I meant 1962, not 1960.','current_correction'),
 ('父亲说商店就在附近。我想聊聊我的花园。','user_redirect'),
 ('父亲说就在附近。今天不聊了。','pause'),
 ('父亲说就在附近。我说错了，是1962年。','current_correction'),
])
def test_reported_clause_cannot_suppress_later_direct_intent_in_the_real_api(sql,tmp_path,monkeypatch,text,reason):
    def provider(request):
        state=json.loads(request.content)['interview_context']['strategy_context']
        if state['plan'] is None:output=wire(selection_reason='latest_story')
        else:
            candidate=state['plan']['candidates'][0]
            output=wire(question=candidate['question'],selected_candidate_id=candidate['id'],selection_reason='prepared_candidate',used_strategy='shape')
        return httpx.Response(200,json={'reply':json.dumps(output),'thread_id':'scope','artifacts':[]})
    with client_fixture(sql,tmp_path,monkeypatch,provider) as client:
        identity,lane_id,page=seed_plan(client,sql);commit(sql,lane_id,page)
        turn=str(uuid4())
        response=client.post('/v1/agent/turn',json={'project_id':identity['project_id'],'text':text,'client_turn_id':turn},headers={'accept':'application/x-ndjson'})
        events=[json.loads(line) for line in response.text.splitlines()]
        assert not any(e['type']=='conversation_saved' for e in events),response.text
        assert events[-1]['type']=='error'
    assert sql('select count(*) from public.user_lifetime_reply;').stdout.strip()=='1'
    assert sql(f"select count(*) from public.user_lifetime_strategy_outcome where client_turn_id='{turn}';").stdout.strip()=='0'


@pytest.mark.parametrize('text,expected',[
 ("My father said nearby. Let’s talk about my garden.",{'override':'user_redirect'}),
 ('他说就在附近。今天不聊了。',{'no_question':True}),
 ('他说就在附近。我说错了，是1962年。',{'override':'current_correction'}),
 ('我说错了，是1962年。',{'override':'current_correction'}),
 ('He said, "Not today. Let’s talk about my garden."',{}),
 ('他说：“今天不聊了。我想聊花园。”',{}),
 ('He said:\nNot today.',{}),
 ('He said "Not today." Let’s talk about my garden.',{'override':'user_redirect'}),
 ('他说：“今天不聊了。”我想聊我的花园。',{'override':'user_redirect'}),
 ('I said 1960, I meant 1962.',{'override':'current_correction'}),
 ('父亲说就在附近，我想聊我的花园。',{'override':'user_redirect'}),
 ('My father said the shop was nearby, not today.',{'no_question':True}),
 ("He said, let’s talk about my garden.",{}),
])
def test_literal_controls_are_clause_scoped_and_quoted_controls_stay_untrusted(text,expected):
    from apps.api.interview_strategy import current_constraints
    assert current_constraints(text)==expected
