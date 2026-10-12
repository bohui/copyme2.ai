import json
from uuid import uuid4
from test_lifetime_memory_postgres import sql,event_database,private_database,attachment_database,database
from test_agent_commit_postgres import OLD,as_user
from test_shared_memory_events_postgres import rpc,literal
from test_interview_work_plan_postgres import plan


def prepare(sql):
    identity=rpc(sql,'resolve_lifetime_conversation','null');turn=str(uuid4())
    accepted=rpc(sql,'accept_user_interview_turn',f"{literal(identity['project_id'])},'{turn}','My name is Joan','narrator_chat','en-AU'")
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    fence=rpc(sql,'capture_lifetime_fence',f"'{identity['conversation_id']}','{OLD}'")
    return identity,turn,accepted,fence


def commit(sql,turn,fence,check=True):
    value=plan(name='Joan');value['phase_update']={'expected_revision':fence['phase_revision'],'phase':'comfort'}
    return rpc(sql,'commit_lifetime_turn',f"{literal(fence)}::jsonb,'{turn}',{literal(value)}::jsonb,'[]','Hello Joan.','[]','fresh-engine','lifetime-v1','fixture-model'",check=check)


def test_atomic_reply_pointer_phase_and_replay(sql):
    identity,turn,accepted,fence=prepare(sql)
    saved=commit(sql,turn,fence)
    assert saved['memory'][0]['client_turn_id']==turn
    assert saved['fence']['identity']['conversation_id']==identity['conversation_id']
    assert saved['interview']['reply']=='Hello Joan.'
    assert commit(sql,turn,saved['fence'])['memory']==saved['memory']
    assert sql('select rounds_completed from public.user_recall_usage;').stdout.strip()=='1'
    assert sql('select count(*) from public.user_lifetime_reply;').stdout.strip()=='1'
    replay=rpc(sql,'read_lifetime_reply',f"'{identity['conversation_id']}','{turn}'")
    assert replay['reply']=='Hello Joan.' and replay['conversation_saved']


def test_stale_policy_cannot_commit_or_replay_personal_reply(sql):
    identity,turn,accepted,fence=prepare(sql)
    saved=commit(sql,turn,fence)
    rpc(sql,'change_user_narrator_source',f"{literal(identity['project_id'])},'{accepted['source']['id']}',1,'withdraw',null")
    assert commit(sql,turn,fence,check=False).returncode!=0
    replay=rpc(sql,'read_lifetime_reply',f"'{identity['conversation_id']}','{turn}'")
    assert replay['reply'] is None and replay['conversation_saved'] and replay['context_rebuild_required']


def test_conflicting_replay_cannot_replace_latest_execution_pointer(sql):
    identity,turn,accepted,fence=prepare(sql)
    saved=commit(sql,turn,fence)
    value=plan(name='Joan')
    conflict=rpc(sql,'commit_lifetime_turn',f"{literal(saved['fence'])}::jsonb,'{turn}',{literal(value)}::jsonb,'[]','Hello Joan.','[]','forged-thread','lifetime-v1','fixture-model'",check=False)
    assert conflict.returncode!=0
    assert sql('select thread_id from public.user_lifetime_conversation;').stdout.strip()=='fresh-engine'
    assert sql('select rounds_completed from public.user_recall_usage;').stdout.strip()=='1'


def test_tail_saved_exchange_keeps_valid_reply_and_drops_it_after_preference_change(sql):
    identity,turn,accepted,fence=prepare(sql)
    commit(sql,turn,fence)
    tail=rpc(sql,'read_lifetime_tail',f"'{identity['conversation_id']}',1,0,1")
    assert tail['complete'] and tail['records'][0]['assistant_reply']=='Hello Joan.'
    assert tail['records'][0]['conversation_saved'] and tail['records'][0]['reply_policy_epoch']==1
    sql(as_user("update public.user_profile set profile=profile||'{\"memory_preferences\":{\"excluded_topics\":[\"Joan\"]}}'::jsonb;"))
    tail=rpc(sql,'read_lifetime_tail',f"'{identity['conversation_id']}',1,0,1")
    assert 'assistant_reply' not in tail['records'][0]
    assert rpc(sql,'read_lifetime_reply',f"'{identity['conversation_id']}','{turn}'")['reply'] is None


def test_replay_identity_and_atomic_language_preserve_other_preferences(sql):
    identity,turn,accepted,fence=prepare(sql)
    assert rpc(sql,'validate_lifetime_replay_input',f"'{identity['conversation_id']}','{turn}','My name is Joan','narrator_chat'")
    assert rpc(sql,'validate_lifetime_replay_input',f"'{identity['conversation_id']}','{turn}','Different text','narrator_chat'",check=False).returncode!=0
    sql(as_user("update public.user_profile set profile='{\"name\":\"Joan\",\"memory_preferences\":{\"excluded_topics\":[\"school\"]}}';"))
    assert rpc(sql,'set_lifetime_language',f"{literal(fence)}::jsonb,'zh-CN',false",check=False).returncode!=0
    fresh=rpc(sql,'capture_lifetime_fence',f"'{identity['conversation_id']}','{OLD}'")
    assert rpc(sql,'set_lifetime_language',f"{literal(fresh)}::jsonb,'zh-CN',false")=='zh-CN'
    profile=json.loads(sql('select profile from public.user_profile;').stdout.strip())
    assert profile['name']=='Joan' and profile['memory_preferences']['excluded_topics']==['school']
