"""Selected-source jobs are bounded durable references, never lifetime copies."""
import json
from uuid import uuid4

import pytest
from test_agent_commit_postgres import database, as_user, OWNER, OTHER
from test_guest_conversation_transfer import attachment_database
from test_private_rounds_postgres import private_database
from test_shared_memory_events_postgres import rpc, literal
from test_lifetime_memory_postgres import resolve
from pathlib import Path


@pytest.fixture(scope='module')
def event_database(private_database):
    baseline = (Path(__file__).resolve().parents[1] / 'supabase/migrations/202610010001_initial_schema.sql').read_text()
    start = baseline.index('create table if not exists public.story_entitlements (')
    private_database(baseline[start:baseline.index('commit;', start)])
    for path in sorted((Path(__file__).resolve().parents[1] / 'supabase/migrations').glob('*.sql')):
        if path.name >= '202610040001_shared_memory_events.sql':
            private_database(path.read_text())
    return private_database


@pytest.fixture
def sql(event_database):
    # The shared fixture starts after this older commercial table. Apply its
    # exact checked-in DDL rather than weakening the production paid gate.
    baseline = (Path(__file__).resolve().parents[1] / 'supabase/migrations/202610010001_initial_schema.sql').read_text()
    start = baseline.index('create table if not exists public.story_entitlements (')
    event_database(baseline[start:baseline.index('commit;', start)])
    event_database('truncate public.user_memoir_project cascade;')
    event_database('truncate public.user_memory, public.user_agent_turn_lease, public.user_agent_session, public.user_recall_usage, public.story_entitlements cascade;')
    event_database('update auth.users set is_anonymous=false;')
    event_database("update public.user_profile set profile='{}';")
    return event_database


def service_rpc(sql, name, arguments, check=True):
    result = sql(f"set role service_role; select coalesce(to_jsonb(public.{name}({arguments})), 'null'::jsonb);", check=check)
    return json.loads(result.stdout.splitlines()[-1]) if check else result


def source(sql, project, text='Original narrator testimony.', owner=OWNER):
    return rpc(sql, 'accept_user_narrator_source', f"{literal(project)},'{uuid4()}',{literal(text)}", owner=owner)


def create(sql, project, ids, kind='BuildSourceExport', revision=None):
    return rpc(sql, 'create_lifetime_collection_job', f"{literal(project)},'{kind}','Selected memories',{literal(ids)}::jsonb,{revision if revision is not None else 'null'},'en-AU'")


def claim(sql, job):
    return service_rpc(sql, 'claim_lifetime_collection_job', f"'{job['id']}',60")


def page(sql, job, token):
    return service_rpc(sql, 'read_lifetime_collection_job_page', f"'{job['id']}','{token}'")


def commit(sql, fence, output=None, check=True):
    return service_rpc(sql, 'commit_lifetime_collection_job_page', f"{literal(fence)}::jsonb,{literal(output) if output is not None else 'null'}::jsonb", check=check)


def test_selected_job_dedup_pagination_exact_words_and_no_full_copies(sql):
    identity = resolve(sql); project = identity['project_id']
    originals = [source(sql, project, '开头\n' + 'word ' * 1200), source(sql, project, 'Second original.')]
    job = create(sql, project, [row['id'] for row in originals])
    assert create(sql, project, [row['id'] for row in originals])['id'] == job['id']
    assert job['status'] == 'QUEUED' and job['result'] is None
    lease = claim(sql, job); count = 0
    while True:
        frozen = page(sql, job, lease['token'])
        if frozen['complete']:
            break
        assert len(frozen['sources']) == 1
        assert len(frozen['sources'][0]['text']) <= 2048
        commit(sql, frozen); count += 1
    assert count == 4
    first = rpc(sql, 'read_lifetime_collection_job', f"'{job['id']}',null,1")
    assert first['status'] == 'SUCCEEDED' and first['result']['coverage']['complete'] is True
    output = []; current = first
    while True:
        output.extend(current['result']['sources'])
        if current['complete']:
            break
        current = rpc(sql, 'read_lifetime_collection_job', f"'{job['id']}','{current['next_cursor']}',1")
    for original in originals:
        assert ''.join(row['content'] for row in output if row['id'] == original['id']) == original['text']
    assert sql("select count(*) from public.user_lifetime_collection_job_page where result is not null;").stdout.strip() == '0'
    assert rpc(sql, 'read_lifetime_collection_job', f"'{job['id']}',null,1", owner=OTHER, check=False).returncode != 0


def test_selected_job_source_change_fences_prompts_commits_reads_and_cursors(sql):
    project = resolve(sql)['project_id']; original = source(sql, project, 'original ' * 700)
    job = create(sql, project, [original['id']]); lease = claim(sql, job)
    frozen = page(sql, job, lease['token']); commit(sql, frozen)
    rpc(sql, 'change_user_narrator_source', f"{literal(project)},'{original['id']}',1,'withdraw',null")
    assert service_rpc(sql, 'read_lifetime_collection_job_page', f"'{job['id']}','{lease['token']}'", check=False).returncode != 0
    assert commit(sql, frozen, check=False).returncode != 0
    assert rpc(sql, 'read_lifetime_collection_job', f"'{job['id']}',null,1", check=False).returncode != 0


def test_selected_job_crash_reclaims_only_unfinished_pages(sql):
    project = resolve(sql)['project_id']; original = source(sql, project, 'x' * 5000)
    job = create(sql, project, [original['id']]); lease = claim(sql, job)
    frozen = page(sql, job, lease['token']); commit(sql, frozen)
    sql(f"update public.user_lifetime_collection_job set lease_until=clock_timestamp()-interval '1 second' where id='{job['id']}';")
    replacement = claim(sql, job); assert replacement['token'] != lease['token']
    resumed = page(sql, job, replacement['token']); assert resumed['page_number'] == 1
    assert commit(sql, frozen, check=False).returncode != 0
    commit(sql, resumed)
    commit(sql, page(sql, job, replacement['token']))
    assert rpc(sql,'read_lifetime_collection_job',f"'{job['id']}',null,8")['status'] == 'SUCCEEDED'


def test_selection_confirmation_is_current_and_owner_scoped(sql):
    project = resolve(sql)['project_id']; original = source(sql, project)
    periods = {name:{'status':'skipped','memory_ids':[],'note':'Not covered'} for name in
        ('baby','toddler','childhood','adolescence','young_adulthood','midlife','later_life')}
    periods['childhood'] = {'status':'recorded','memory_ids':[original['id']],'note':''}
    arguments = f"{literal(project)},0,{literal(periods)}::jsonb,true"
    selected = rpc(sql,'set_lifetime_collection',arguments)
    assert selected['ready'] and selected['revision'] == 1
    assert rpc(sql,'set_lifetime_collection',arguments,check=False).returncode != 0
    assert rpc(sql,'set_lifetime_collection',arguments,owner=OTHER,check=False).returncode != 0
    assert create(sql,project,[original['id']])['kind'] == 'BuildSourceExport'
    assert rpc(sql,'create_lifetime_collection_job',f"{literal(project)},'BuildOutline','Book','[]'::jsonb,1,'en-AU'",check=False).returncode != 0


def paid(sql):
    sql(f"insert into public.story_entitlements(user_id,status,plan_key,book_count,amount_minor,currency,stripe_session_id) values('{OWNER}','paid','synthetic',1,1,'aud','synthetic-paid') on conflict(user_id) do update set status='paid';")


def confirm(sql, project, sources):
    periods = {name:{'status':'skipped','memory_ids':[],'note':'Not covered'} for name in
        ('baby','toddler','childhood','adolescence','young_adulthood','midlife','later_life')}
    periods['childhood'] = {'status':'recorded','memory_ids':[row['id'] for row in sources],'note':''}
    return rpc(sql,'set_lifetime_collection',f"{literal(project)},0,{literal(periods)}::jsonb,true")


def outline_result(frozen):
    if frozen['phase'] == 'leaf':
        return {'title':'A recurring theme','sections':[{'title':'A recurring theme','memory_ids':[frozen['sources'][0]['id']]}]}
    return {'title':'Globally grouped memories','sections':[{'title':'A recurring theme',
        'section_ids':[section['id'] for child in frozen['child_groups'] for section in child['sections']]}]}


def test_outline_hierarchy_preserves_complete_source_ancestry_and_global_grouping(sql):
    project = resolve(sql)['project_id']; originals = [source(sql,project,f'Theme in memory {i}.') for i in range(10)]
    confirm(sql,project,originals); paid(sql)
    job = create(sql,project,[],'BuildOutline',1); lease=claim(sql,job); phases=[]
    while True:
        frozen=page(sql,job,lease['token'])
        if frozen['complete']:break
        phases.append(frozen['phase'])
        if frozen['phase']=='merge':
            assert not frozen['sources'] and 2<=len(frozen['child_groups'])<=8
            assert len(json.dumps(frozen['child_groups'],ensure_ascii=False).encode())<=24004
        commit(sql,frozen,outline_result(frozen))
    assert phases.count('leaf')==10 and phases.count('merge')==9
    result=rpc(sql,'read_lifetime_collection_job',f"'{job['id']}',null,8")
    assert result['result']['title']=='Selected memories'
    assert result['result']['suggested_title']=='Globally grouped memories'
    assert result['result']['publication_approved'] is False
    assert len(result['result']['sections'])==1
    root=result['result']['sections'][0]['id']; all_sources=[]
    while True:
        all_sources.extend(result['result']['sources'])
        if result['complete']:break
        result=rpc(sql,'read_lifetime_collection_job',f"'{job['id']}','{result['next_cursor']}',8")
    assert {row['id'] for row in all_sources}=={row['id'] for row in originals}
    assert {row['root_section_id'] for row in all_sources}=={root}
    # Every non-root node belongs to exactly one parent; restart cannot fork it.
    assert sql(f"select count(*) from public.user_lifetime_collection_job_node where job_id='{job['id']}' and parent_id is null;").stdout.strip()=='1'


def test_outline_rejects_duplicate_foreign_missing_children_and_late_edit(sql):
    project=resolve(sql)['project_id']; originals=[source(sql,project,f'Memory {i}') for i in range(2)]
    confirm(sql,project,originals);paid(sql);job=create(sql,project,[],'BuildOutline',1);lease=claim(sql,job)
    for _ in range(2):
        frozen=page(sql,job,lease['token']);commit(sql,frozen,outline_result(frozen))
    frozen=page(sql,job,lease['token']);good=outline_result(frozen)
    for bad_ids in [[],['foreign:1'],good['sections'][0]['section_ids']*2,good['sections'][0]['section_ids'][:1]]:
        assert commit(sql,frozen,{'title':'Bad','sections':[{'title':'Bad','section_ids':bad_ids}]},check=False).returncode!=0
    rpc(sql,'change_user_narrator_source',f"{literal(project)},'{originals[1]['id']}',1,'edit','Changed original.'")
    assert commit(sql,frozen,good,check=False).returncode!=0


def test_outline_rechecks_paid_entitlement_and_confirmation_on_frozen_page(sql):
    project=resolve(sql)['project_id']; original=source(sql,project);confirm(sql,project,[original]);paid(sql)
    job=create(sql,project,[],'BuildOutline',1);lease=claim(sql,job);frozen=page(sql,job,lease['token'])
    sql(f"update public.story_entitlements set status='revoked' where user_id='{OWNER}';")
    assert commit(sql,frozen,outline_result(frozen),check=False).returncode!=0
    paid(sql)
    doc=rpc(sql,'read_lifetime_collection_selection',literal(project))
    rpc(sql,'set_lifetime_collection',f"{literal(project)},1,{literal(doc['periods'])}::jsonb,false")
    assert commit(sql,frozen,outline_result(frozen),check=False).returncode!=0


def test_worker_resumes_in_bounded_runs_without_legacy_source_payload(monkeypatch):
    import asyncio
    from apps.api.lifetime_memory_collection_jobs import CollectionJobWorker
    monkeypatch.delenv('MEMOIR_LIFETIME_GENERATION_PAUSED',raising=False)
    class Broker:
        def __init__(self):self.calls=[];self.page=0
        async def rpc(self,name,**kwargs):
            self.calls.append((name,kwargs))
            if name=='claim_lifetime_collection_job':return {'id':kwargs['p_job_id'],'token':str(uuid4())}
            if name=='read_lifetime_collection_job_page':return {'complete':False,'kind':'BuildSourceExport','page_number':self.page}
            if name=='commit_lifetime_collection_job_page':
                assert kwargs['p_result'] is None
                self.page+=1
                return {'complete':False}
            if name=='release_lifetime_collection_job':return True
            raise AssertionError(name)
    broker=Broker();result=asyncio.run(CollectionJobWorker(broker).execute(str(uuid4())))
    assert result=={'status':'pending','processed':8}
    assert broker.calls[-1][0]=='release_lifetime_collection_job'
    assert all(not any(key in kwargs for key in ('memories','task_sources')) for _,kwargs in broker.calls)


def test_worker_pause_keeps_deterministic_work_and_defers_organiser_without_provider(monkeypatch):
    import asyncio
    from apps.api.lifetime_memory_collection_jobs import CollectionJobWorker,drain_collection_jobs_once
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','true');monkeypatch.setenv('MEMOIR_LIFETIME_GENERATION_PAUSED','true')
    class Broker:
        def __init__(self,kind):self.kind=kind;self.commits=0;self.releases=[]
        async def rpc(self,name,**kwargs):
            if name=='pending_lifetime_collection_jobs':
                assert kwargs['p_include_outline'] is False;return []
            if name=='claim_lifetime_collection_job':return {'id':kwargs['p_job_id'],'token':str(uuid4())}
            if name=='read_lifetime_collection_job_page':return {'complete':False,'kind':self.kind}
            if name=='commit_lifetime_collection_job_page':self.commits+=1;return {'complete':True}
            if name=='release_lifetime_collection_job':self.releases.append(kwargs['p_error']);return True
            pytest.fail(name)
    broker=Broker('BuildOutline')
    assert asyncio.run(drain_collection_jobs_once(broker))==[]
    assert asyncio.run(CollectionJobWorker(broker).execute(str(uuid4())))['status']=='deferred'
    assert broker.commits==0 and broker.releases==[None]
    broker=Broker('BuildSourceExport')
    assert asyncio.run(CollectionJobWorker(broker).execute(str(uuid4())))['status']=='succeeded'
    assert broker.commits==1


@pytest.mark.parametrize('clearance_closed', [True, False])
def test_worker_only_clearance_deferral_avoids_generation_failure(monkeypatch, clearance_closed):
    import asyncio
    from apps.api import lifetime_memory_job_engine
    from apps.api.lifetime_memory_activation import CanonicalActivationUnavailable
    from apps.api.lifetime_memory_collection_jobs import CollectionJobWorker
    from apps.api.lifetime_memory_publication import PublicationUnavailable
    from test_lifetime_memory_job_engine import page as bounded_page

    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY', 'true')
    monkeypatch.delenv('MEMOIR_LIFETIME_GENERATION_PAUSED', raising=False)
    releases = []

    class Broker:
        async def rpc(self, name, **kwargs):
            if name == 'claim_lifetime_collection_job':
                return {'id': kwargs['p_job_id'], 'token': str(uuid4())}
            if name == 'read_lifetime_collection_job_page':
                return bounded_page()
            if name == 'release_lifetime_collection_job':
                releases.append(kwargs['p_error'])
                return True
            pytest.fail(name)

    async def blocked(**kwargs):
        if clearance_closed:
            raise CanonicalActivationUnavailable()
        raise PublicationUnavailable('Unrelated authority failure')

    monkeypatch.setattr(lifetime_memory_job_engine, 'send_bounded_job_request', blocked)
    worker = CollectionJobWorker(Broker(), worker_url='http://synthetic.invalid', worker_secret='synthetic')
    if clearance_closed:
        assert asyncio.run(worker.execute(str(uuid4()))) == {'status': 'deferred', 'processed': 0}
        assert releases == [None]
    else:
        with pytest.raises(PublicationUnavailable, match='Unrelated authority failure'):
            asyncio.run(worker.execute(str(uuid4())))
        assert releases == ['BOUNDED_JOB_RETRY']


@pytest.mark.parametrize('bad_status',[None,False,{},0,'unknown'])
def test_sql_confirmation_rejects_null_and_untyped_status(sql,bad_status):
    project=resolve(sql)['project_id']; original=source(sql,project)
    periods={name:{'status':'skipped','memory_ids':[],'note':'Skip'} for name in
        ('baby','toddler','childhood','adolescence','young_adulthood','midlife','later_life')}
    periods['childhood']={'status':bad_status,'memory_ids':[original['id']],'note':'Recorded'}
    assert rpc(sql,'set_lifetime_collection',f"{literal(project)},0,{literal(periods)}::jsonb,true",check=False).returncode!=0


def test_confirmed_source_order_is_period_then_explicit_selection_order(sql):
    project=resolve(sql)['project_id']; originals=sorted([source(sql,project,f'Memory {i}') for i in range(3)],key=lambda row:row['id'],reverse=True)
    confirm(sql,project,originals);paid(sql);job=create(sql,project,[],'BuildOutline',1);lease=claim(sql,job)
    observed=[]
    for _ in originals:
        frozen=page(sql,job,lease['token']);observed.append(frozen['sources'][0]['id']);commit(sql,frozen,outline_result(frozen))
    assert observed==[row['id'] for row in originals]


def test_typed_job_fences_match_exact_sql_pages_before_leaf_and_merge_publication(sql):
    from apps.api.lifetime_memory_contracts import ContextBudget
    from apps.api.lifetime_memory_job_engine import build_bounded_job_input,job_request_tokens
    identity=resolve(sql);project=identity['project_id']; originals=[source(sql,project,f'Memory {i}') for i in range(2)]
    control=source(sql,project,'Do not discuss the private school incident.')
    from test_agent_commit_postgres import OLD
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    data={'text':control['text'],'assertion':'asserted','source_refs':[{'source_id':control['id'],'version':1,
        'char_start':0,'char_end':len(control['text']),'quote':control['text']}]}
    rpc(sql,'save_lifetime_continuity',f"'{identity['conversation_id']}','privacy-exclusion','excluded_topic',0,1,'{OLD}',{literal(data)}::jsonb")
    confirm(sql,project,originals);paid(sql);job=create(sql,project,[],'BuildOutline',1);lease=claim(sql,job)
    budget=ContextBudget(model='synthetic-byte-bpe',context_window=131072,input_budget=65536,output_headroom=32768,framing_headroom=4096)
    phases=[]
    for _ in range(3):
        frozen=page(sql,job,lease['token']);bounded=build_bounded_job_input(frozen,budget=budget)
        fence=bounded.fence.model_dump(mode='json');phases.append(fence['phase'])
        assert job_request_tokens(bounded)<=65536
        assert control['text'] in json.loads(bounded.packet)['job_context']['preferences']['excluded_topics']
        assert bounded.fence.preferences.known_continuity[0].kind=='excluded_topic'
        assert rpc(sql,'lock_lifetime_collection_job_publication',f'{literal(fence)}::jsonb')>0
        import asyncio
        from apps.api.lifetime_memory_job_engine import JobPublication
        command=sql.command;dsn=f"host={command[command.index('-h')+1]} port={command[command.index('-p')+1]} user=postgres dbname=postgres"
        async def admitted():
            async with JobPublication(dsn,authenticated_owner=OWNER).guard(fence):
                return True
        assert asyncio.run(admitted())
        wrong={**fence,'page_number':fence['page_number']+1}
        assert rpc(sql,'lock_lifetime_collection_job_publication',f'{literal(wrong)}::jsonb',check=False).returncode!=0
        assert rpc(sql,'lock_lifetime_collection_job_publication',f'{literal(fence)}::jsonb',owner=OTHER,check=False).returncode!=0
        commit(sql,frozen,outline_result(frozen))
    assert phases==['leaf','leaf','merge']


def test_failed_crash_is_terminal_and_explicit_retry_resumes_frozen_frontier(sql):
    project=resolve(sql)['project_id'];original=source(sql,project);job=create(sql,project,[original['id']])
    for _ in range(3):
        lease=claim(sql,job)
        sql(f"update public.user_lifetime_collection_job set lease_until=clock_timestamp()-interval '1 second' where id='{job['id']}';")
    assert claim(sql,job) is None
    failed=rpc(sql,'read_lifetime_collection_job',f"'{job['id']}',null,8")
    assert failed['status']=='FAILED' and failed['error']=='BOUNDED_JOB_RETRY'
    retried=rpc(sql,'set_lifetime_collection_job_retry',f"'{job['id']}'")
    assert retried['status']=='QUEUED' and retried['attempts']==0
    lease=claim(sql,job);assert page(sql,job,lease['token'])['page_number']==0


@pytest.mark.parametrize('change',['withdraw','confirmation','entitlement'])
@pytest.mark.parametrize('cancel',[False,True])
def test_selected_result_actual_send_holds_all_authority_and_releases_on_cancel(sql,change,cancel):
    import asyncio
    import psycopg
    from apps.api.lifetime_memory_collection_jobs import CollectionResultPublication
    from apps.api.lifetime_memory_reads import ReadSnapshot,ReadJSONResponse
    from apps.api.lifetime_memory_publication import PublicationUnavailable
    project=resolve(sql)['project_id'];original=source(sql,project);doc=confirm(sql,project,[original]);paid(sql)
    job=create(sql,project,[],'BuildOutline',1);lease=claim(sql,job);frozen=page(sql,job,lease['token']);commit(sql,frozen,outline_result(frozen))
    result=rpc(sql,'read_lifetime_collection_job',f"'{job['id']}',null,8")
    fence=rpc(sql,'capture_lifetime_read_fence',literal(project))
    command=sql.command;dsn=f"host={command[command.index('-h')+1]} port={command[command.index('-p')+1]} user=postgres dbname=postgres"
    publisher=CollectionResultPublication(dsn,authenticated_owner=OWNER,job_id=job['id']);publisher.root_digest=result['root_digest']
    async def scenario():
        sending_entered=asyncio.Event();release=asyncio.Event();sent=[]
        async def send(message):
            if message['type']=='http.response.body':sending_entered.set();await release.wait()
            sent.append(message)
        async def receive():await asyncio.Event().wait()
        response=ReadJSONResponse(ReadSnapshot(result,fence),publisher=publisher)
        task=asyncio.create_task(response({'type':'http','asgi':{'spec_version':'2.4'}},receive,send))
        async with asyncio.timeout(3):await sending_entered.wait()
        writer=await psycopg.AsyncConnection.connect(dsn,autocommit=True);observer=await psycopg.AsyncConnection.connect(dsn,autocommit=True)
        try:
            if change=='entitlement':
                mutate=asyncio.create_task(writer.execute("update public.story_entitlements set status='revoked' where user_id=%s",(OWNER,)))
            else:
                await writer.execute('set role authenticated');await writer.execute("select set_config('request.jwt.claim.sub',%s,false)",(OWNER,))
                if change=='withdraw':mutate=asyncio.create_task(writer.execute("select public.change_user_narrator_source(%s,%s,1,'withdraw',null)",(project,original['id'])))
                else:
                    from psycopg.types.json import Jsonb
                    mutate=asyncio.create_task(writer.execute('select public.set_lifetime_collection(%s,1,%s,false)',(project,Jsonb(doc['periods']))))
            async with asyncio.timeout(2):
                while not (await (await observer.execute('select cardinality(pg_blocking_pids(%s))',(writer.info.backend_pid,))).fetchone())[0]:
                    assert not mutate.done(),'Authority changed during actual send'
            if cancel:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):await task
                assert not any(message['type']=='http.response.body' for message in sent)
            else:release.set();await task
            await mutate
            with pytest.raises(PublicationUnavailable):
                async with publisher.guard(fence):pytest.fail('stale result was published')
        finally:
            task.cancel();await asyncio.gather(task,return_exceptions=True);await writer.close();await observer.close()
    asyncio.run(scenario())


def test_outline_retains_one_hundred_sections_and_rejects_overbudget_cjk_titles(sql):
    project=resolve(sql)['project_id']
    sql(as_user(f"do $$ begin for n in 1..100 loop perform public.accept_user_narrator_source('{project}',gen_random_uuid(),'Memory '||n);end loop;end $$;"))
    originals=json.loads(sql(f"select jsonb_agg(jsonb_build_object('id',id) order by sequence) from public.user_narrator_source where project_id='{project}';").stdout.strip())
    confirm(sql,project,originals);paid(sql);job=create(sql,project,[],'BuildOutline',1);lease=claim(sql,job)
    sql(f"""set role service_role;do $proof$ declare frozen jsonb; output jsonb; sections jsonb; bad jsonb; begin loop
      frozen:=public.read_lifetime_collection_job_page('{job['id']}','{lease['token']}');
      exit when (frozen->>'complete')::boolean;
      if frozen->>'phase'='leaf' then
        output:=jsonb_build_object('title','Book','sections',jsonb_build_array(jsonb_build_object('title','Memory',
          'memory_ids',jsonb_build_array(frozen->'sources'->0->>'id'))));
      else
        select jsonb_agg(jsonb_build_object('title','Memory','section_ids',jsonb_build_array(s->>'id')) order by s->>'id') into sections
          from jsonb_array_elements(frozen->'child_groups')c cross join lateral jsonb_array_elements(c->'sections')s;
        output:=jsonb_build_object('title','Book','sections',sections);
        if jsonb_array_length(sections)=100 then
          select jsonb_build_object('title','Book','sections',jsonb_agg(s||jsonb_build_object('title',repeat('回',100)))) into bad from jsonb_array_elements(sections)s;
          begin
            perform public.commit_lifetime_collection_job_page(frozen,bad);
            raise exception 'over-budget CJK metadata was accepted';
          exception when program_limit_exceeded then null;end;
        end if;
      end if;
      perform public.commit_lifetime_collection_job_page(frozen,output);
    end loop;end $proof$;""")
    result=rpc(sql,'read_lifetime_collection_job',f"'{job['id']}',null,8")
    assert len(result['result']['sections'])==100
    assert result['result']['coverage']['source_count']==100
    assert len(result['result']['sources'])==8 and not result['complete']


def test_selected_manifest_remains_bounded_as_history_grows_to_ten_thousand(sql):
    project=resolve(sql)['project_id']; first=source(sql,project,'Early selected original ' + '长' * 5000)
    job=create(sql,project,[first['id']]);lease=claim(sql,job);frozen=page(sql,job,lease['token'])
    assert len(frozen['sources'])==1 and len(frozen['sources'][0]['text'])==2048
    commit(sql,frozen)
    # An unrelated growing history never changes the frozen selected scope or
    # makes the next worker request include a prefix/all-history source copy.
    # Bound fixture transactions as well as job packets: one enormous hot-row
    # transaction measures tuple-chain churn, not growing-history recovery.
    for start in range(2,10001,500):
        end=min(start+499,10000)
        sql(as_user(f"set statement_timeout='90s';do $$ begin for n in {start}..{end} loop perform public.accept_user_narrator_source('{project}',gen_random_uuid(),'Unselected memory '||n);end loop;end $$;"))
    # Resume the durable checkpoint after a potentially long idle history build.
    sql(f"update public.user_lifetime_collection_job set lease_until=clock_timestamp()-interval '1 second' where id='{job['id']}';")
    lease=claim(sql,job)
    observed=[]
    while True:
        frozen=page(sql,job,lease['token'])
        if frozen['complete']:break
        assert len(json.dumps(frozen,ensure_ascii=False).encode())<20000
        observed.extend(row['id'] for row in frozen['sources']);commit(sql,frozen)
    assert set(observed)=={first['id']}
    assert sql(f"select count(*) from public.user_narrator_source where project_id='{project}';").stdout.strip()=='10000'
    assert sql(f"select count(*) from public.user_lifetime_collection_job_source where job_id='{job['id']}';").stdout.strip()=='1'
    all_words=[];cursor='null'
    while True:
        result=rpc(sql,'read_lifetime_collection_job',f"'{job['id']}',{cursor},1")
        all_words.extend(row['content'] for row in result['result']['sources'])
        if result['complete']:break
        cursor=literal(result['next_cursor'])
    assert ''.join(all_words)==first['text']
    assert result['result']['coverage']['scope']=='selected_sources' and result['result']['coverage']['source_count']==1


def test_real_worker_dispatches_fenced_leaf_and_merge_without_legacy_history(sql,monkeypatch):
    import asyncio
    import httpx
    from apps.api.lifetime_memory_collection_jobs import CollectionJobWorker
    from apps.api.lifetime_memory_contracts import ContextBudget
    from apps.api.lifetime_memory_job_engine import JobPublication
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','true')
    monkeypatch.delenv('MEMOIR_LIFETIME_GENERATION_PAUSED',raising=False)
    project=resolve(sql)['project_id'];originals=[source(sql,project,f'Memory {i}') for i in range(2)]
    confirm(sql,project,originals);paid(sql);job=create(sql,project,[],'BuildOutline',1)
    command=sql.command;dsn=f"host={command[command.index('-h')+1]} port={command[command.index('-p')+1]} user=postgres dbname=postgres"
    class Broker:
        async def rpc(self,name,**kwargs):
            def encode(value):
                if isinstance(value,(dict,list)):return literal(value)+'::jsonb'
                if value is None:return 'null'
                if isinstance(value,bool):return 'true' if value else 'false'
                if isinstance(value,int):return str(value)
                return literal(value)
            return await asyncio.to_thread(service_rpc,sql,name,','.join(f'{key}=>{encode(value)}' for key,value in kwargs.items()))
    phases=[]
    async def transport(request):
        wire=json.loads(await request.aread())
        assert 'task_sources' not in wire and 'memories' not in wire
        bounded=wire['bounded_job'];fence=bounded['fence'];phases.append(fence['phase'])
        assert len(bounded['packet'].encode())<65536
        return httpx.Response(200,json={'reply':json.dumps(outline_result(fence)),'thread_id':str(uuid4()),'artifacts':[]})
    budget=ContextBudget(model='synthetic-byte-bpe',context_window=131072,input_budget=65536,output_headroom=32768,framing_headroom=4096)
    worker=CollectionJobWorker(Broker(),worker_url='http://synthetic-worker.invalid',worker_secret='synthetic',
        worker_transport=httpx.MockTransport(transport),publisher=JobPublication(dsn,authenticated_owner=OWNER),budget=budget)
    assert asyncio.run(worker.execute(job['id']))=={'status':'succeeded','processed':3}
    assert phases==['leaf','leaf','merge']
    assert rpc(sql,'read_lifetime_collection_job',f"'{job['id']}',null,8")['status']=='SUCCEEDED'


def test_provider_deferral_preserves_committed_outline_and_resumes(sql, monkeypatch):
    import asyncio
    import httpx
    from apps.api.lifetime_memory_collection_jobs import CollectionJobWorker
    from contextlib import asynccontextmanager
    from apps.api.lifetime_memory_activation import CanonicalActivationUnavailable

    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY', 'true')
    monkeypatch.delenv('MEMOIR_LIFETIME_GENERATION_PAUSED', raising=False)
    project = resolve(sql)['project_id']
    originals = [source(sql, project, f'Original memory {n}') for n in range(2)]
    confirm(sql, project, originals)
    paid(sql)
    job = create(sql, project, [], 'BuildOutline', 1)
    lease = claim(sql, job)
    frozen = page(sql, job, lease['token'])
    commit(sql, frozen, outline_result(frozen))
    service_rpc(sql, 'release_lifetime_collection_job', f"'{job['id']}','{lease['token']}',null")

    def checkpoint():
        # Everything except the mutable lease/failure state must survive pause.
        saved = sql(f"select to_jsonb(j)-array['state','token','lease_until','attempts','error'] "
                    f"from public.user_lifetime_collection_job j where id='{job['id']}';").stdout
        for table, order in [('source', 'ordinal'), ('page', 'page_number'), ('node', 'ordinal')]:
            saved += sql(f"select jsonb_agg(to_jsonb(v) order by {order}) "
                         f"from public.user_lifetime_collection_job_{table} v where job_id='{job['id']}';").stdout
        return saved

    accepted = checkpoint()

    class Broker:
        async def rpc(self, name, **kwargs):
            def encode(value):
                if isinstance(value, (dict, list)):
                    return literal(value) + '::jsonb'
                if value is None:
                    return 'null'
                if isinstance(value, int):
                    return str(value)
                return literal(value)
            return await asyncio.to_thread(service_rpc, sql, name,
                ','.join(f'{key}=>{encode(value)}' for key, value in kwargs.items()))

    pages_sent = []

    async def transport(request):
        fence = json.loads(await request.aread())['bounded_job']['fence']
        pages_sent.append((fence['phase'], fence['page_number']))
        return httpx.Response(200, json={'reply': json.dumps(outline_result(fence))})

    class ProviderAuthority:
        blocked = True

        @asynccontextmanager
        async def guard(self, fence):
            if self.blocked:
                raise CanonicalActivationUnavailable()
            yield

    authority = ProviderAuthority()
    worker = CollectionJobWorker(Broker(), worker_url='http://synthetic.invalid', worker_secret='synthetic',
        worker_transport=httpx.MockTransport(transport), publisher=authority)
    for _ in range(4):  # More deferrals than the ordinary failure limit.
        assert asyncio.run(worker.execute(job['id'])) == {'status': 'deferred', 'processed': 0}
        state = json.loads(sql(f"select jsonb_build_object('state',state,'attempts',attempts,'token',token,'error',error) "
                               f"from public.user_lifetime_collection_job where id='{job['id']}';").stdout)
        assert state == {'state': 'QUEUED', 'attempts': 0, 'token': None, 'error': None}
        assert checkpoint() == accepted
    assert pages_sent == []
    export = create(sql, project, [row['id'] for row in originals])
    assert asyncio.run(worker.execute(export['id'])) == {'status': 'succeeded', 'processed': 2}
    assert pages_sent == []
    authority.blocked = False

    assert asyncio.run(worker.execute(job['id'])) == {'status': 'succeeded', 'processed': 2}
    assert pages_sent == [('leaf', 1), ('merge', 2)]
    result = rpc(sql, 'read_lifetime_collection_job', f"'{job['id']}',null,8")
    assert result['status'] == 'SUCCEEDED'
    assert {item['id'] for item in result['result']['sources']} == {row['id'] for row in originals}


def test_canonical_polling_limits_outlines_and_keeps_exports_visible(sql):
    project = resolve(sql)['project_id']
    original = source(sql, project)
    confirm(sql, project, [original])
    paid(sql)
    outlines = [rpc(sql, 'create_lifetime_collection_job',
                    f"{literal(project)},'BuildOutline','Outline {n}','[]'::jsonb,1,'en-AU'")
                for n in range(4)]
    export = create(sql, project, [original['id']])
    assert service_rpc(sql, 'pending_lifetime_collection_jobs', '4,true') == [job['id'] for job in outlines]
    assert service_rpc(sql, 'pending_lifetime_collection_jobs', '4,false') == [export['id']]
    for limit in (0, 33):
        assert service_rpc(sql, 'pending_lifetime_collection_jobs', f'{limit},true', check=False).returncode != 0
    assert rpc(sql, 'pending_lifetime_collection_jobs', '4,true', check=False).returncode != 0
    assert sql('set role anon; select public.pending_lifetime_collection_jobs(4,true);', check=False).returncode != 0
    assert sql("select to_regclass('public.lifetime_realtime_clearance') is null;").stdout.strip() == 't'


@pytest.mark.parametrize('revoke',['source','preference','collection','entitlement'])
def test_privacy_revocation_purges_derived_titles_atomically_without_starving_other_jobs(sql,revoke):
    phrase='Unique private editorial phrase never retained'
    project=resolve(sql)['project_id'];original=source(sql,project,'Original testimony')
    doc=confirm(sql,project,[original]);paid(sql);job=create(sql,project,[],'BuildOutline',1);lease=claim(sql,job)
    frozen=page(sql,job,lease['token']);commit(sql,frozen,{'title':phrase,'sections':[{'title':phrase,'memory_ids':[original['id']]}]})
    other_identity=resolve(sql,owner=OTHER);other_source=source(sql,other_identity['project_id'],'Other tenant original',owner=OTHER)
    other_job=rpc(sql,'create_lifetime_collection_job',f"{literal(other_identity['project_id'])},'BuildSourceExport','Other',{literal([other_source['id']])}::jsonb,null,'en-AU'",owner=OTHER)
    if revoke=='source':rpc(sql,'change_user_narrator_source',f"{literal(project)},'{original['id']}',1,'withdraw',null")
    elif revoke=='preference':
        sql(as_user("insert into public.user_profile(user_id,profile) values(auth.uid(),'{\"memory_preferences\":{\"excluded_topics\":[\"school\"]}}') on conflict(user_id) do update set profile=excluded.profile;"))
    elif revoke=='collection':rpc(sql,'set_lifetime_collection',f"{literal(project)},1,{literal(doc['periods'])}::jsonb,false")
    else:sql(f"update public.story_entitlements set status='revoked' where user_id='{OWNER}';")
    assert sql(f"select state from public.user_lifetime_collection_job where id='{job['id']}';").stdout.strip()=='STALE'
    assert sql(f"select count(*) from public.user_lifetime_collection_job_node where job_id='{job['id']}';").stdout.strip()=='0'
    assert phrase not in sql('select coalesce(jsonb_agg(row_to_json(n)),\'[]\') from public.user_lifetime_collection_job_node n;').stdout
    pending=service_rpc(sql,'pending_lifetime_collection_jobs','1,true')
    assert pending==[other_job['id']]
    other_lease=claim(sql,other_job);assert page(sql,other_job,other_lease['token'])['sources'][0]['text']=='Other tenant original'


def test_collection_job_guard_matches_existing_auth_then_project_lock_order(sql):
    import asyncio
    import psycopg
    from apps.api.lifetime_memory_collection_jobs import CollectionResultPublication
    project=resolve(sql)['project_id'];original=source(sql,project);confirm(sql,project,[original]);paid(sql)
    job=create(sql,project,[],'BuildOutline',1);lease=claim(sql,job);frozen=page(sql,job,lease['token']);commit(sql,frozen,outline_result(frozen))
    result=rpc(sql,'read_lifetime_collection_job',f"'{job['id']}',null,8");fence=rpc(sql,'capture_lifetime_read_fence',literal(project))
    command=sql.command;dsn=f"host={command[command.index('-h')+1]} port={command[command.index('-p')+1]} user=postgres dbname=postgres"
    async def scenario():
        writer=await psycopg.AsyncConnection.connect(dsn);observer=await psycopg.AsyncConnection.connect(dsn,autocommit=True)
        publisher=CollectionResultPublication(dsn,authenticated_owner=OWNER,job_id=job['id']);publisher.root_digest=result['root_digest']
        try:
            await writer.execute('select id from auth.users where id=%s for update',(OWNER,))
            async def publish():
                async with publisher.guard(fence):return True
            sending=asyncio.create_task(publish())
            # While publication waits on auth, the established guest/account
            # path can still take the project/profile lock without inversion.
            async with asyncio.timeout(1):
                await writer.execute('select project_id from public.user_memoir_project where user_id=%s and project_id=%s for update',(OWNER,project))
                await writer.execute('select user_id from public.user_profile where user_id=%s for update',(OWNER,))
            await writer.rollback()
            assert await sending is True
        finally:await writer.close();await observer.close()
    asyncio.run(scenario())


def test_task_head_pages_reach_older_jobs_without_foreign_cursor_or_full_history_count(sql):
    project=resolve(sql)['project_id']; original=source(sql,project)
    jobs=[rpc(sql,'create_lifetime_collection_job',f"{literal(project)},'BuildSourceExport','Selected {index}',{literal([original['id']])}::jsonb") for index in range(19)]
    # Identical timestamps exercise the stable ID tie-breaker.
    sql("update public.user_lifetime_collection_job set created_at='2026-01-01T00:00:00Z';")
    seen=[];cursor='null'
    while True:
        result=rpc(sql,'read_lifetime_collection_selection',f"{literal(project)},{cursor},8")
        assert len(result['tasks'])<=8
        assert all(task['result'] is None and 'title' not in task for task in result['tasks'])
        seen.extend(task['id'] for task in result['tasks'])
        if result['tasks_complete']:break
        assert result['tasks_next_cursor'] and result['tasks_next_cursor'] not in seen[:-1]
        cursor=f"'{result['tasks_next_cursor']}'"
    assert len(seen)==19 and set(seen)=={job['id'] for job in jobs}
    assert seen==sorted(seen,reverse=True)
    foreign=resolve(sql,owner=OTHER)['project_id']
    assert rpc(sql,'read_lifetime_collection_selection',f"{literal(foreign)},'{jobs[0]['id']}',8",owner=OTHER,check=False).returncode!=0
    assert rpc(sql,'read_lifetime_collection_selection',f"{literal(project)},null,9",check=False).returncode!=0
