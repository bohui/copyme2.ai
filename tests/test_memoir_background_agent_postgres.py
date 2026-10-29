"""Real database ownership, coalescing, expiry and required-work contracts."""
import json
from uuid import uuid4

import pytest

from test_agent_commit_postgres import OWNER, OTHER, as_user, database
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database, resolve
from test_shared_memory_events_postgres import literal, rpc


def service(sql, name, **arguments):
    fields = ','.join(key + '=>' + literal(value) for key,value in arguments.items())
    result = sql('set role service_role;select coalesce(to_jsonb(public.' + name + '(' + fields + ")), 'null'::jsonb);")
    return json.loads(result.stdout.strip().splitlines()[-1])


def queued(sql):
    identity = resolve(sql)
    run = rpc(sql, 'queue_user_memoir_background_agent', literal(identity['project_id']))
    return identity, run


def test_agent_claim_is_separate_from_foreground_and_coalesces_by_project(sql):
    identity, run = queued(sql)
    assert rpc(sql,'queue_user_memoir_background_agent',literal(identity['project_id'])) == run
    assert service(sql,'pending_memoir_background_agents') == [run]
    claim = service(sql,'claim_memoir_background_agent',p_id=run,p_run_seconds=300)
    assert claim['user_id'] == OWNER and claim['project_id'] == identity['project_id']
    assert service(sql,'claim_memoir_background_agent',p_id=run,p_run_seconds=300) is None
    assert service(sql,'read_memoir_background_work',p_fence=claim)['lanes'] == []
    assert sql('select count(*) from public.user_agent_turn_lease;').stdout.strip() == '0'
    assert service(sql,'finish_memoir_background_agent',p_id=run,p_token=claim['token'],p_success=True) == {
        'status':'finished','pending':False}


@pytest.mark.parametrize('language,expected',[('zh-CN','zh-CN'),('en-US','en-AU')])
def test_agent_claim_uses_a_supported_workspace_locale(sql,language,expected):
    _,run=queued(sql)
    sql(f"insert into public.user_profile(user_id,profile) values('{OWNER}',jsonb_build_object('preferred_language',{literal(language)})) on conflict(user_id) do update set profile=excluded.profile;")
    assert service(sql,'claim_memoir_background_agent',p_id=run,p_run_seconds=300)['locale']==expected


def test_background_scope_rejects_other_owner_new_source_and_expired_tokens(sql):
    identity, run = queued(sql)
    claim = service(sql,'claim_memoir_background_agent',p_id=run,p_run_seconds=300)
    for patch in ({'user_id':OTHER},{'project_id':'foreign'},{'token':'00000000-0000-4000-8000-000000000000'}):
        result = sql('set role service_role;select public.read_memoir_background_work(' + literal({**claim,**patch}) + ');',check=False)
        assert result.returncode != 0
    sql(f"update public.user_memoir_background_agent set lease_until=clock_timestamp()-interval '1 second' where id='{run}';")
    assert not service(sql,'heartbeat_memoir_background_agent',p_id=run,p_token=claim['token'])
    assert sql('set role service_role;select public.read_memoir_background_work(' + literal(claim) + ');',check=False).returncode != 0


def test_model_completion_cannot_discard_pending_domain_work(sql):
    identity, run = queued(sql)
    sql(f"insert into public.user_memoir_lane(user_id,project_id,skill) values('{OWNER}',{literal(identity['project_id'])},'timeline');")
    claim = service(sql,'claim_memoir_background_agent',p_id=run,p_run_seconds=300)
    assert service(sql,'read_memoir_background_work',p_fence=claim)['lanes'][0]['skill'] == 'timeline'
    result = service(sql,'finish_memoir_background_agent',p_id=run,p_token=claim['token'],p_success=True)
    assert result == {'status':'pending','pending':True}
    assert sql("select pending from public.user_memoir_lane;").stdout.strip() == 't'


def test_background_operations_are_private_and_deletion_removes_claims(sql):
    identity, run = queued(sql)
    claim=service(sql,'claim_memoir_background_agent',p_id=run,p_run_seconds=300)
    assert sql(as_user('select * from public.user_memoir_background_agent;',OTHER),check=False).returncode != 0
    assert sql(as_user('select public.pending_memoir_background_agents();'),check=False).returncode != 0
    sql('delete from public.user_lifetime_conversation where user_id=' + literal(OWNER) + ' and project_id=' + literal(identity['project_id']) + ';')
    assert sql('set role service_role;select public.read_memoir_background_work(' + literal(claim) + ');',check=False).returncode!=0
    sql('delete from public.user_memoir_project where user_id=' + literal(OWNER) + ' and project_id=' + literal(identity['project_id']) + ';')
    assert service(sql,'claim_memoir_background_agent',p_id=run,p_run_seconds=300) is None


def test_failed_domain_work_requires_retry_and_the_existing_retry_action_restarts_the_agent(sql):
    identity,run=queued(sql)
    sql(f"insert into public.user_memoir_lane(user_id,project_id,skill,attempts) values('{OWNER}',{literal(identity['project_id'])},'timeline',3);")
    claim=service(sql,'claim_memoir_background_agent',p_id=run,p_run_seconds=300)
    result=service(sql,'finish_memoir_background_agent',p_id=run,p_token=claim['token'],p_success=True)
    assert result=={'status':'retry_required','pending':True}
    assert service(sql,'pending_memoir_background_agents')==[]
    assert rpc(sql,'retry_user_memoir_lane',literal(identity['project_id'])+",'timeline'")['queued']
    assert service(sql,'pending_memoir_background_agents')==[run]


@pytest.mark.parametrize('table,column',[('user_memoir_project','source_sequence'),
    ('user_memoir_project','policy_epoch'),('user_lifetime_conversation','preference_revision')])
def test_changed_authority_fences_the_agent_and_requeues_with_a_fresh_snapshot(sql,table,column):
    identity,run=queued(sql)
    claim=service(sql,'claim_memoir_background_agent',p_id=run,p_run_seconds=300)
    sql(f"update public.{table} set {column}={column}+1 where user_id='{OWNER}' and project_id={literal(identity['project_id'])};")
    assert sql('set role service_role;select public.read_memoir_background_work(' + literal(claim) + ');',check=False).returncode!=0
    assert service(sql,'finish_memoir_background_agent',p_id=run,p_token=claim['token'],p_success=False)['status']=='pending'
    sql(f"update public.user_memoir_background_agent set available_at=clock_timestamp() where id='{run}';")
    fresh=service(sql,'claim_memoir_background_agent',p_id=run,p_run_seconds=300)
    assert fresh['token']!=claim['token']
    assert service(sql,'read_memoir_background_work',p_fence=fresh)['lanes']==[]


def test_crashed_agent_and_expired_domain_leases_are_reclaimed(sql):
    identity,run=queued(sql)
    original=service(sql,'claim_memoir_background_agent',p_id=run,p_run_seconds=300)
    sql(f"update public.user_memoir_background_agent set lease_until=clock_timestamp()-interval '1 second' where id='{run}';")
    assert service(sql,'pending_memoir_background_agents')==[run]
    fresh=service(sql,'claim_memoir_background_agent',p_id=run,p_run_seconds=300)
    assert fresh['token']!=original['token']
    lane=str(uuid4())
    sql(f"insert into public.user_memoir_lane(id,user_id,project_id,skill,pending,token,lease_until,run_deadline) values('{lane}','{OWNER}',{literal(identity['project_id'])},'timeline',false,'{uuid4()}',clock_timestamp()-interval '1 second',clock_timestamp()+interval '1 minute');")
    assert service(sql,'read_memoir_background_work',p_fence=fresh)['lanes']==[{'id':lane,'skill':'timeline'}]


def test_repeated_agent_failure_exposes_required_work_through_existing_retry_state(sql):
    identity,run=queued(sql)
    sql(f"insert into public.user_memoir_lane(user_id,project_id,skill) values('{OWNER}',{literal(identity['project_id'])},'timeline');")
    sql(f"insert into public.user_memoir_lane(user_id,project_id,skill) values('{OWNER}',{literal(identity['project_id'])},'composer');")
    for attempt in range(3):
        sql(f"update public.user_memoir_background_agent set available_at=clock_timestamp() where id='{run}';")
        claim=service(sql,'claim_memoir_background_agent',p_id=run,p_run_seconds=300)
        result=service(sql,'finish_memoir_background_agent',p_id=run,p_token=claim['token'],p_success=False)
        assert result['status']==('retry_required' if attempt==2 else 'pending')
    assert sql("select bool_and(attempts=3 and pending and error='MEMOIR_UNAVAILABLE') from public.user_memoir_lane;").stdout.strip()=='t'
    assert rpc(sql,'retry_user_memoir_lane',literal(identity['project_id'])+",'timeline'")['queued']
    assert service(sql,'pending_memoir_background_agents')==[run]
    assert sql("select bool_and(attempts=0 and pending and error is null) from public.user_memoir_lane;").stdout.strip()=='t'
