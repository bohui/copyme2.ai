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


@pytest.mark.parametrize('character',['x','忆','😀','\x01'])
def test_forty_queued_windows_fit_the_real_tool_budget_without_dropping_sources(sql,monkeypatch,character):
    import asyncio
    from apps.api.memoir_background_agent import BackgroundSkills, SOURCE_SKILLS
    from apps.api.memoir_skill_agent import SkillTools
    from test_background_profile_postgres import source
    monkeypatch.delenv('MEMORY_SPARK_HISTORICAL_NEWS',raising=False)
    identity,run=queued(sql)
    sources=[source(sql,identity,character*2048,index) for index in range(1,41)]
    sql(f"insert into public.user_memoir_lane(user_id,project_id,skill,target_source) "
        f"values('{OWNER}',{literal(identity['project_id'])},'timeline',40);")
    claim=service(sql,'claim_memoir_background_agent',p_id=run,p_run_seconds=300)
    class Broker:
        async def rpc(self,name,**arguments):return service(sql,name,**arguments)
    skills=BackgroundSkills(claim,Broker(),None)
    async def refresh():
        tools=SkillTools(SOURCE_SKILLS,work=skills.work)
        response=await tools.call({'tool':'memoir_pending_work','arguments':{}})
        assert response['success']
        payload=response['contentItems'][0]['text']
        assert len(payload.encode('utf-8'))<=49152
        return json.loads(payload)
    for remaining,original in zip(range(40,0,-1),sources):
        work=asyncio.run(refresh())
        page=work['source_work']
        assert page['source']['id']==original['id']
        assert page['source']['text']==original['text']
        assert [entry['sequence'] for entry in page['conversation_history']]==list(
            range(max(1,original['sequence']-20),original['sequence']))
        assert page['remaining_sources']==remaining
        assert 1<=len(page['sources'])<=4
        assert len(json.dumps(page['sources'],ensure_ascii=False).encode('utf-8'))<=16384
        assert page['has_more_sources']==(remaining>len(page['sources']))
        assert work['batch']['id']==claim['batch_id']
        assert work['batch']['coverage_end']==40
        assert work['batch']['client_turn_id']==sources[-1]['client_turn_id']
        sql(f"update public.user_narrator_source set processing_status='succeeded' where id='{original['id']}';")


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


@pytest.mark.parametrize('language,queued_language',[('zh-CN','en-AU'),('en-AU','zh-CN')])
def test_timeline_claim_resolves_current_language_before_source_skills(sql,language,queued_language):
    from test_background_profile_postgres import source
    identity,run=queued(sql)
    source(sql,identity,'我于1983年4月出生在承德。',1)
    sql(f"insert into public.user_profile(user_id,profile) values('{OWNER}',"
        f"jsonb_build_object('preferred_language',{literal(language)})) "
        "on conflict(user_id) do update set profile=excluded.profile;")
    sql(f"insert into public.user_memoir_lane(user_id,project_id,skill,target_source,locale) "
        f"values('{OWNER}',{literal(identity['project_id'])},'timeline',1,{literal(queued_language)});")
    claim=service(sql,'claim_memoir_background_agent',p_id=run,p_run_seconds=300)
    work=service(sql,'read_memoir_background_work',p_fence=claim)
    page=service(sql,'claim_memoir_lane',p_lane_id=work['lanes'][0]['id'],p_run_seconds=300)
    assert claim['locale']==page['preferences']['language']==language
    assert page['locale']==language, 'Nested skills must use the resolved profile language, not the queued default.'


def test_composer_claim_keeps_explicit_edition_after_resolving_conversation_language(sql):
    from test_background_profile_postgres import source
    identity,run=queued(sql)
    project=identity['project_id']
    original=source(sql,identity,'I grew up in Chengde.',1)
    event={'kind':'event','title':'Childhood','source_refs':[{'source_id':original['id'],
        'version':1,'quote':original['text'],'char_start':0,'char_end':len(original['text'])}]}
    rpc(sql,'apply_user_memory_events',f"{literal(project)},"
        f"{literal([{'id':original['id'],'version':1}])},{literal([event])}")
    sql(f"update public.user_profile set profile=jsonb_build_object('preferred_language','zh-CN') where user_id='{OWNER}';")
    sql(f"insert into public.user_memoir_lane(user_id,project_id,skill,target_source,target_milestone,locale) "
        f"values('{OWNER}',{literal(project)},'composer',1,1,'en-AU');")
    claim=service(sql,'claim_memoir_background_agent',p_id=run,p_run_seconds=300)
    work=service(sql,'read_memoir_background_work',p_fence=claim)
    page=service(sql,'claim_memoir_lane',p_lane_id=work['lanes'][0]['id'],p_run_seconds=300)
    assert page['preferences']['language']==claim['locale']=='zh-CN'
    assert page['locale']=='en-AU' and page['partition']


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


@pytest.mark.parametrize('cancelled',[False,True])
def test_policy_arriving_after_a_background_lane_claim_releases_only_metadata(sql,monkeypatch,cancelled):
    import asyncio
    from apps.api.lifetime_memory_policy import PolicyUnavailable
    from apps.api.memoir_background_agent import AgentBroker, BackgroundAgentPublication
    from apps.api.memory_event_worker import MemoryEventWorker
    from test_background_profile_postgres import source
    monkeypatch.delenv('MEMORY_SPARK_HISTORICAL_NEWS',raising=False)
    identity,run=queued(sql)
    first=source(sql,identity,'I repaired bicycles in our garden.',1)
    lane=sql(f"insert into public.user_memoir_lane(user_id,project_id,skill,target_source) "
        f"values('{OWNER}',{literal(identity['project_id'])},'timeline',1) returning id;").stdout.strip()
    claim=service(sql,'claim_memoir_background_agent',p_id=run,p_run_seconds=300)
    current=service(sql,'read_memoir_background_work',p_fence=claim)
    class InterruptedBroker(AgentBroker):
        async def rpc(self,name,**arguments):
            if cancelled and name=='select_lifetime_source_skills':
                raise asyncio.CancelledError()
            result=await super().rpc(name,**arguments)
            if name=='claim_memoir_lane':
                # Raw acceptance leaves policy pending, as in the reported race.
                sql(as_user('select public.accept_user_narrator_source('+
                    literal(identity['project_id'])+','+literal(str(uuid4()))+",'My next memory.');"))
            return result
    async def scenario():
        broker=InterruptedBroker(BackgroundAgentPublication(sql.publication_dsn,claim))
        worker=MemoryEventWorker(broker,worker_url='http://synthetic.invalid',worker_secret='synthetic')
        async def execute():
            return await worker.execute_lane(lane,source_work={
                'source':current['source_work']['source'],'skills':['memoir-author-timeline']})
        if cancelled:
            with pytest.raises(asyncio.CancelledError):await execute()
        else:
            result=await execute()
            assert result['status']=='pending' and result['error']==PolicyUnavailable.code
        with pytest.raises(PolicyUnavailable):
            await broker.rpc('read_memoir_background_work',p_fence=claim)
    asyncio.run(scenario())
    assert sql("select (token is null)||':'||attempts||':'||coalesce(error,'') from public.user_memoir_lane;").stdout.strip()==\
        ('true:0:' if cancelled else 'true:0:LIFETIME_POLICY_PENDING')
    assert sql('select count(*) from public.user_memory_event;').stdout.strip()=='0'
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='2'
    assert sql(f"select processing_status from public.user_narrator_source where id='{first['id']}';").stdout.strip()=='pending'


def test_waiting_for_a_claimed_lane_does_not_exhaust_background_retries(sql):
    from test_background_profile_postgres import source
    identity,run=queued(sql)
    source(sql,identity,'An original memory.',1)
    lane=sql(f"insert into public.user_memoir_lane(user_id,project_id,skill,target_source) "
        f"values('{OWNER}',{literal(identity['project_id'])},'timeline',1) returning id;").stdout.strip()
    claim=service(sql,'claim_memoir_background_agent',p_id=run,p_run_seconds=300)
    service(sql,'claim_memoir_lane',p_lane_id=lane,p_run_seconds=300)
    for _ in range(4):
        assert service(sql,'read_memoir_background_work',p_fence=claim)['lanes']==[]
        result=service(sql,'finish_memoir_background_agent',p_id=run,p_token=claim['token'],p_success=True)
        assert result=={'status':'pending','pending':True}
        assert sql('select attempts from public.user_memoir_background_agent;').stdout.strip()=='0'
        sql('update public.user_memoir_background_agent set available_at=clock_timestamp();')
        claim=service(sql,'claim_memoir_background_agent',p_id=run,p_run_seconds=300)
        assert claim is not None


@pytest.mark.parametrize('operation',['heartbeat_memoir_lane','fail_memoir_lane'])
def test_background_lifecycle_survives_policy_pending_without_releasing_story_content(sql,operation):
    import asyncio
    from apps.api.lifetime_memory_policy import PolicyUnavailable
    from apps.api.memoir_background_agent import AgentBroker, BackgroundAgentPublication
    from test_background_profile_postgres import source
    identity,run=queued(sql)
    first=source(sql,identity,'I repaired bicycles in our garden.',1)
    lane=sql(f"insert into public.user_memoir_lane(user_id,project_id,skill,target_source) "
        f"values('{OWNER}',{literal(identity['project_id'])},'timeline',1) returning id;").stdout.strip()
    claim=service(sql,'claim_memoir_background_agent',p_id=run,p_run_seconds=300)
    async def scenario():
        broker=AgentBroker(BackgroundAgentPublication(sql.publication_dsn,claim))
        page=await broker.rpc('claim_memoir_lane',p_lane_id=lane,p_run_seconds=300)
        sql("update public.user_memoir_lane set lease_until=clock_timestamp()+interval '10 seconds';")
        sql(as_user('select public.accept_user_narrator_source('+literal(identity['project_id'])+','+
            literal(str(uuid4()))+",'My next memory.');"))
        arguments=dict(p_lane_id=lane,p_token=page['token'])
        if operation=='fail_memoir_lane':arguments.update(p_error='MEMOIR_PROVIDER_UNAVAILABLE',p_retryable=True)
        result=await broker.rpc(operation,**arguments)
        if operation=='heartbeat_memoir_lane':
            assert result is True
            assert sql("select lease_until>clock_timestamp()+interval '30 seconds' from public.user_memoir_lane;").stdout.strip()=='t'
        else:
            assert result=={'status':'retry'}
            assert sql("select (token is null)||':'||error from public.user_memoir_lane;").stdout.strip()==\
                'true:MEMOIR_PROVIDER_UNAVAILABLE'
        with pytest.raises(PolicyUnavailable):
            await broker.rpc('read_memoir_background_work',p_fence=claim)
    asyncio.run(scenario())
    assert sql('select count(*) from public.user_lifetime_pending_policy;').stdout.strip()=='1'
    assert sql('select count(*) from public.user_memory_event;').stdout.strip()=='0'
    assert sql(f"select text from public.user_narrator_source where id='{first['id']}';").stdout.strip()==first['text']


def test_provider_failure_during_a_new_narrations_review_cannot_strand_its_lane(sql,monkeypatch):
    import asyncio
    import httpx
    from apps.api.memoir_background_agent import AgentBroker, BackgroundAgentPublication
    from apps.api.memory_event_worker import MemoryEventWorker
    from test_background_profile_postgres import source
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','1')
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',sql.publication_dsn)
    identity,run=queued(sql)
    source(sql,identity,'I repaired bicycles in our garden.',1)
    lane=sql(f"insert into public.user_memoir_lane(user_id,project_id,skill,target_source) "
        f"values('{OWNER}',{literal(identity['project_id'])},'timeline',1) returning id;").stdout.strip()
    claim=service(sql,'claim_memoir_background_agent',p_id=run,p_run_seconds=300)
    admitted=[]
    def provider(request):
        admitted.append(json.loads(request.content)['bounded_lane']['phase'])
        sql(as_user('select public.accept_user_narrator_source('+literal(identity['project_id'])+','+
            literal(str(uuid4()))+",'My next memory.');"))
        return httpx.Response(502,json={'detail':'Controlled provider failure'})
    async def scenario():
        broker=AgentBroker(BackgroundAgentPublication(sql.publication_dsn,claim))
        current=await broker.rpc('read_memoir_background_work',p_fence=claim)
        worker=MemoryEventWorker(broker,worker_url='http://synthetic.invalid',worker_secret='synthetic',
            worker_transport=httpx.MockTransport(provider))
        return await worker.execute_lane(lane,source_work={
            'source':current['source_work']['source'],'skills':['memoir-author-timeline']})
    assert asyncio.run(scenario())=={'status':'retry'}
    assert admitted==['extract']
    assert sql("select (token is null)||':'||pending||':'||error from public.user_memoir_lane;").stdout.strip()==\
        'true:true:MEMOIR_UNAVAILABLE'
    assert sql('select count(*) from public.user_lifetime_pending_policy;').stdout.strip()=='1'
    assert sql('select count(*) from public.user_memory_event;').stdout.strip()=='0'


@pytest.mark.parametrize('operation',['yield_lifetime_memoir_lane_metadata','defer_lifetime_memoir_lane_policy'])
@pytest.mark.parametrize('field',['p_user_id','p_project_id','p_conversation_id','p_token'])
def test_background_metadata_release_rejects_foreign_scope_or_token(sql,operation,field):
    import asyncio
    from apps.api.lifetime_memory_publication import PublicationUnavailable
    from apps.api.memoir_background_agent import AgentBroker, BackgroundAgentPublication
    from test_background_profile_postgres import source
    identity,run=queued(sql)
    source(sql,identity,'An original memory.',1)
    lane=sql(f"insert into public.user_memoir_lane(user_id,project_id,skill,target_source) "
        f"values('{OWNER}',{literal(identity['project_id'])},'timeline',1) returning id;").stdout.strip()
    claim=service(sql,'claim_memoir_background_agent',p_id=run,p_run_seconds=300)
    broker=AgentBroker(BackgroundAgentPublication(sql.publication_dsn,claim))
    page=asyncio.run(broker.rpc('claim_memoir_lane',p_lane_id=lane,p_run_seconds=300))
    before=sql('select to_jsonb(l) from public.user_memoir_lane l;').stdout
    arguments=dict(p_lane_id=lane,p_token=page['token'],p_user_id=OWNER,
        p_project_id=identity['project_id'],p_conversation_id=identity['conversation_id'])
    arguments[field]='foreign' if field=='p_project_id' else OTHER
    with pytest.raises(PublicationUnavailable):
        asyncio.run(broker.rpc(operation,**arguments))
    assert sql('select to_jsonb(l) from public.user_memoir_lane l;').stdout==before


@pytest.mark.parametrize('operation',['heartbeat_memoir_lane','fail_memoir_lane',
    'yield_lifetime_memoir_lane_metadata','defer_lifetime_memoir_lane_policy'])
def test_background_lifecycle_requires_this_agents_claim_even_with_a_valid_lane_token(sql,operation):
    import asyncio
    from apps.api.lifetime_memory_publication import PublicationUnavailable
    from apps.api.memoir_background_agent import AgentBroker, BackgroundAgentPublication
    from test_background_profile_postgres import source
    identity,run=queued(sql)
    source(sql,identity,'An original memory.',1)
    lane=sql(f"insert into public.user_memoir_lane(user_id,project_id,skill,target_source) "
        f"values('{OWNER}',{literal(identity['project_id'])},'timeline',1) returning id;").stdout.strip()
    claim=service(sql,'claim_memoir_background_agent',p_id=run,p_run_seconds=300)
    page=service(sql,'claim_memoir_lane',p_lane_id=lane,p_run_seconds=300)
    before=sql('select to_jsonb(l) from public.user_memoir_lane l;').stdout
    arguments=dict(p_lane_id=lane,p_token=page['token'])
    if operation=='fail_memoir_lane':arguments.update(p_error='MEMOIR_UNAVAILABLE',p_retryable=True)
    if operation.endswith('_metadata') or operation.endswith('_policy'):
        arguments.update(p_user_id=OWNER,p_project_id=identity['project_id'],p_conversation_id=identity['conversation_id'])
    broker=AgentBroker(BackgroundAgentPublication(sql.publication_dsn,claim))
    with pytest.raises(PublicationUnavailable,match='not claimed by this agent'):
        asyncio.run(broker.rpc(operation,**arguments))
    assert sql('select to_jsonb(l) from public.user_memoir_lane l;').stdout==before


def test_background_foreign_lane_claim_is_rolled_back_before_recording_a_token(sql):
    import asyncio
    from apps.api.lifetime_memory_publication import PublicationUnavailable
    from apps.api.memoir_background_agent import AgentBroker, BackgroundAgentPublication
    _,run=queued(sql)
    other=resolve(sql,owner=OTHER)
    lane=sql(f"insert into public.user_memoir_lane(user_id,project_id,skill) "
        f"values('{OTHER}',{literal(other['project_id'])},'timeline') returning id;").stdout.strip()
    claim=service(sql,'claim_memoir_background_agent',p_id=run,p_run_seconds=300)
    broker=AgentBroker(BackgroundAgentPublication(sql.publication_dsn,claim))
    with pytest.raises(PublicationUnavailable,match='claim scope changed'):
        asyncio.run(broker.rpc('claim_memoir_lane',p_lane_id=lane,p_run_seconds=300))
    assert sql(f"select (token is null)||':'||attempts from public.user_memoir_lane where id='{lane}';").stdout.strip()=='true:0'
    assert sql(f"select count(*) from public.user_lifetime_lane_snapshot where lane_id='{lane}';").stdout.strip()=='0'


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
