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


def test_new_narrations_wait_for_the_current_batch_then_arrive_together(sql):
    from test_background_profile_postgres import source
    identity, run = queued(sql)
    first = source(sql, identity, 'I was born in Hobart.', 1)
    sql(f"insert into public.user_memoir_lane(user_id,project_id,skill,target_source) "
        f"values('{OWNER}',{literal(identity['project_id'])},'timeline',1);")
    claim = service(sql,'claim_memoir_background_agent',p_id=run,p_run_seconds=300)
    second = source(sql, identity, 'We played in the school housing.', 2)
    third = source(sql, identity, 'Our favourite game was hide-and-seek.', 3)
    rpc(sql,'queue_user_memoir_background_agent',literal(identity['project_id']))
    assert service(sql,'claim_memoir_background_agent',p_id=run,p_run_seconds=300) is None
    current = service(sql,'read_memoir_background_work',p_fence=claim)
    assert [item['id'] for item in current['source_work']['sources']] == [first['id']]
    assert current['batch']['client_turn_id'] == first['client_turn_id']
    assert current['batch']['started_at']
    assert 'childhood_place' not in current['source_work']['profile_targets']

    # A retry keeps the old batch ahead of new arrivals, with a fresh lease.
    service(sql,'finish_memoir_background_agent',p_id=run,p_token=claim['token'],p_success=False)
    sql('update public.user_memoir_background_agent set available_at=clock_timestamp();')
    retry = service(sql,'claim_memoir_background_agent',p_id=run,p_run_seconds=300)
    assert retry['source_high_water'] == 1 and retry['batch_id'] == claim['batch_id']
    assert retry['token'] != claim['token']
    page = service(sql,'claim_memoir_lane',p_lane_id=current['lanes'][0]['id'],p_run_seconds=300)
    assert page['source_high_water'] == 1, 'Domain execution must share the frozen coordinator batch.'
    service(sql,'yield_lifetime_memoir_lane',p_lane_id=page['lane_id'],p_token=page['token'])
    sql(f"update public.user_narrator_source set processing_status='succeeded' where id='{first['id']}';")
    sql('update public.user_memoir_lane set successful_source=1,target_source=3,pending=true;')
    assert service(sql,'finish_memoir_background_agent',p_id=run,p_token=retry['token'],p_success=True)['pending']
    sql('update public.user_memoir_background_agent set available_at=clock_timestamp();')
    following = service(sql,'claim_memoir_background_agent',p_id=run,p_run_seconds=300)
    work = service(sql,'read_memoir_background_work',p_fence=following)
    assert following['batch_id'] != claim['batch_id']
    assert [item['id'] for item in work['source_work']['sources']] == [second['id'],third['id']]
    assert work['batch']['coverage_start'] == 2 and work['batch']['coverage_end'] == 3
    assert work['batch']['client_turn_id'] == third['client_turn_id']


def test_budget_stops_with_saved_progress_keep_the_same_batch_and_do_not_exhaust_retries(sql):
    from test_background_profile_postgres import source
    identity,run=queued(sql)
    sources=[source(sql,identity,f'Memory {index}.',index) for index in range(1,6)]
    batch=None
    for original in sources[:4]:
        sql('update public.user_memoir_background_agent set available_at=clock_timestamp();')
        claim=service(sql,'claim_memoir_background_agent',p_id=run,p_run_seconds=300)
        batch=batch or claim['batch_id']
        assert claim['batch_id']==batch
        sql(f"update public.user_narrator_source set processing_status='succeeded' where id='{original['id']}';")
        result=service(sql,'finish_memoir_background_agent',p_id=run,p_token=claim['token'],p_success=False)
        assert result=={'status':'pending','pending':True}
        assert sql('select attempts from public.user_memoir_background_agent;').stdout.strip()=='0'


def test_legacy_childhood_profile_locks_do_not_leak_through_settings_or_agent_targets(sql):
    identity,run=queued(sql)
    sql(f"select public.ensure_lifetime_profile_authority('{OWNER}');")
    sql(f"update public.user_lifetime_profile_authority set field_locks='{{\"childhood_place\":\"manual\"}}' where user_id='{OWNER}';")
    automation=rpc(sql,'read_lifetime_profile_automation','')
    assert 'childhood_place' not in automation['field_locks']


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
    assert sql(as_user("select public.select_lifetime_source_skills('00000000-0000-4000-8000-000000000000',"
        "'00000000-0000-4000-8000-000000000000','{}','[]');"),check=False).returncode != 0
    assert sql(as_user("select public.advance_memoir_background_profile('{}',"
        "'00000000-0000-4000-8000-000000000000','untrusted');"),check=False).returncode != 0
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


@pytest.mark.parametrize('table,column',[
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
