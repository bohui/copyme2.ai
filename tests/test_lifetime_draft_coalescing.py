"""Acknowledged, fenced prefix coverage plus bounded canonical intake deltas."""
import json
from uuid import uuid4

import pytest

from apps.api.private_draft_jobs import PrivateDraftJobs
from test_lifetime_draft_capacity import draft_page,ingest


def delta_page(n, *, after=None, records=None, epoch=1, preference=0, round_revision=0):
    after=n-1 if after is None else after
    return {**draft_page(snapshot=f'snapshot-{n}',source_revision=n,round_high_water=n,
        complete=True,next_cursor=None,records=records or [
            {'record_type':'source','source_id':f'source-{n}','sequence':n,'version':1,
             'char_start':0,'char_end':4,'text':'原文en','status':'active','kind':'narrator_chat','language':'zh-CN'},
            {'record_type':'round','turn_id':f'turn-{n}','ordinal':n,'memory_id':None}],epoch=epoch),
        'event_id':f'event-{n}','preference_revision':preference,'coverage_schema_version':1,
        'base_snapshot_id':f'snapshot-{after}' if after else None,
        'source_after':after,'round_after':after,'round_revision':round_revision}


def test_acknowledged_prefix_can_be_represented_without_reloading_local_history(tmp_path):
    queue=PrivateDraftJobs(tmp_path/'jobs.sqlite')
    page=delta_page(10000,after=10000);page['records']=[];page['snapshot_id']='coalesced'
    result=ingest(queue,page)
    assert result['retrieval_complete'] is True and result['record_count']==0
    assert result['source_after']==result['round_after']==10000
    assert result['base_snapshot_id']=='snapshot-10000'
    with queue._connect() as db:
        assert db.execute('select count(*) from private_draft_rounds').fetchone()[0]==0
        assert len(db.execute('select payload from private_draft_jobs').fetchone()[0])<2048


def test_incremental_source_and_round_tails_preserve_exact_counts_without_old_bytes(tmp_path):
    queue=PrivateDraftJobs(tmp_path/'jobs.sqlite')
    first=ingest(queue,delta_page(1))
    second=ingest(queue,delta_page(2))
    assert first['record_count']==second['record_count']==2
    assert second['source_after']==second['round_after']==1
    assert queue.page_resume('event-1')['complete'] is True
    assert queue.page_resume('event-2')['complete'] is True
    with queue._connect() as db:
        assert db.execute('select count(*) from private_draft_rounds').fetchone()[0]==2
        assert db.execute('select sum(record_count) from private_draft_page_receipts').fetchone()[0]==4
    assert '原文'.encode() not in (tmp_path/'jobs.sqlite').read_bytes()


@pytest.mark.parametrize('patch',[
    {'source_after':-1}, {'round_after':3}, {'source_after':True},
    {'base_snapshot_id':None}, {'coverage_schema_version':2}, {'round_revision':-1},
    {'source_after':0,'round_after':0,'base_snapshot_id':'unexpected'},
])
def test_unproven_or_invalid_inherited_coverage_is_rejected(tmp_path,patch):
    queue=PrivateDraftJobs(tmp_path/'jobs.sqlite')
    with pytest.raises(ValueError):ingest(queue,{**delta_page(2),**patch})


@pytest.mark.parametrize('field',['coverage_schema_version','base_snapshot_id','source_after','round_after','round_revision'])
def test_inherited_coverage_contract_must_be_complete(tmp_path,field):
    queue=PrivateDraftJobs(tmp_path/'jobs.sqlite');page=delta_page(1);del page[field]
    with pytest.raises(ValueError):ingest(queue,page)


def test_round_mutation_fence_prevents_delayed_receipt_downgrade(tmp_path):
    queue=PrivateDraftJobs(tmp_path/'jobs.sqlite')
    current=delta_page(1,round_revision=2);ingest(queue,current)
    stale={**delta_page(2,round_revision=1),'event_id':'stale-event'}
    with pytest.raises(ValueError):ingest(queue,stale)
    assert queue.page_resume('event-1')['complete'] is True


def test_replayed_prefix_metadata_is_immutable(tmp_path):
    queue=PrivateDraftJobs(tmp_path/'jobs.sqlite')
    page=delta_page(2);ingest(queue,page)
    assert ingest(queue,page)==ingest(queue,page)
    with pytest.raises(ValueError):ingest(queue,{**page,'base_snapshot_id':'another-proof'})


def test_ten_thousand_sequential_receipts_have_linear_intake_and_constant_checkpoint_size(tmp_path):
    queue=PrivateDraftJobs(tmp_path/'jobs.sqlite')
    for n in range(1,10001):
        result=ingest(queue,delta_page(n))
        assert result['record_count']==2
    with queue._connect() as db:
        assert db.execute('select count(*) from private_draft_rounds').fetchone()[0]==10000
        assert db.execute('select sum(record_count) from private_draft_page_receipts').fetchone()[0]==20000
        assert db.execute('select max(length(checkpoint)) from private_draft_jobs').fetchone()[0]<2048
        assert db.execute('select count(*) from private_draft_page_state').fetchone()[0]==1


from test_lifetime_memory_postgres import sql,event_database,private_database,attachment_database,database
from test_lifetime_draft_capacity import seed_draft,database_page
from test_shared_memory_events_postgres import rpc,literal
from test_agent_commit_postgres import OWNER,OTHER


def new_receipt(sql,project,owner=OWNER):
    return sql(f"insert into public.user_private_draft_outbox(user_id,project_id,change_kind) values('{owner}',{literal(project)},'round') returning id;").stdout.strip()


def scan_receipt(sql,event,queue=None):
    result=database_page(sql,event);first=result;count=chars=pages=0
    while True:
        count+=len(result['records']);pages+=1
        chars+=sum(len(record.get('text') or '') for record in result['records'])
        if queue is not None:ingest(queue,result)
        if result['complete']:break
        result=database_page(sql,event,result['next_cursor'])
    return {'first':first,'last':result,'records':count,'chars':chars,'pages':pages}


def acknowledge(sql,event,check=True):
    return sql(f"update public.user_private_draft_outbox set delivered=true where id='{event}';",check=check)


def test_database_only_acknowledged_complete_prefix_can_skip_history(sql,tmp_path):
    identity,event=seed_draft(sql,40);queue=PrivateDraftJobs(tmp_path/'jobs.sqlite')
    first=database_page(sql,event);ingest(queue,first)
    assert first['complete'] is False and first['base_snapshot_id'] is None
    assert acknowledge(sql,event,check=False).returncode!=0
    assert sql(f"select public.queue_memoir_receipt('{event}',5);",check=False).returncode!=0
    assert sql('select count(*) from public.user_memoir_lane;').stdout.strip()=='0'
    complete=scan_receipt(sql,event,queue)
    assert complete['records']==80
    unacked=new_receipt(sql,identity['project_id'])
    assert database_page(sql,unacked)['source_after']==0
    acknowledge(sql,event)
    repeated=new_receipt(sql,identity['project_id'])
    reused=scan_receipt(sql,repeated,queue)
    assert reused['records']==reused['chars']==0 and reused['pages']==1
    assert reused['first']['base_snapshot_id']==first['snapshot_id']
    assert reused['first']['source_after']==reused['first']['round_after']==40
    acknowledge(sql,repeated)
    # Already-frozen work never silently changes its range after another ACK.
    assert database_page(sql,unacked)['source_after']==0


def test_database_appended_turn_pages_only_new_source_and_round(sql,tmp_path):
    identity,event=seed_draft(sql,10000);queue=PrivateDraftJobs(tmp_path/'jobs.sqlite')
    initial=scan_receipt(sql,event,queue);acknowledge(sql,event)
    source=rpc(sql,'accept_user_narrator_source',f"{literal(identity['project_id'])},'{uuid4()}','Only the new 原文'")
    sql(f"insert into public.user_completed_round(user_id,project_id,turn_id,ordinal) values('{OWNER}',{literal(identity['project_id'])},'{uuid4()}',10001);")
    next_event=new_receipt(sql,identity['project_id']);delta=scan_receipt(sql,next_event,queue)
    assert initial['records']==20000 and initial['pages']==625
    assert delta['pages']==1 and delta['records']==2 and delta['chars']==len(source['text'])
    assert delta['first']['source_after']==delta['first']['round_after']==10000
    assert delta['first']['records'][0]['source_id']==source['id']
    assert delta['first']['records'][1]['ordinal']==10001
    assert queue.page_resume(next_event)['milestone']==10000
    with queue._connect() as db:
        assert db.execute('select count(*) from private_draft_rounds').fetchone()[0]==10001
        assert db.execute('select sum(record_count) from private_draft_page_receipts').fetchone()[0]==20002


def test_database_ten_thousand_repeated_receipts_transmit_zero_old_source_bytes(sql):
    identity,event=seed_draft(sql,10000)
    initial=scan_receipt(sql,event);queue_until_delivered(sql,event,5)
    result=sql(f"""do $$ declare receipt uuid; page jsonb; bytes bigint:=0; records bigint:=0; begin
      for n in 1..10000 loop
        insert into public.user_private_draft_outbox(user_id,project_id,change_kind)
          values('{OWNER}',{literal(identity['project_id'])},'round') returning id into receipt;
        page:=public.private_draft_event_page(receipt);
        if not (page->>'complete')::boolean or (page->>'source_after')::bigint<>10000 or
            (page->>'round_after')::bigint<>10000 or page->'base_snapshot_id'='null'::jsonb then
          raise exception 'unproven coalesced coverage';end if;
        records:=records+jsonb_array_length(page->'records');bytes:=bytes+octet_length(page::text);
        if (public.queue_memoir_receipt(receipt,5)->>'coverage_pending')::boolean then
          raise exception 'milestone prefix was replayed';end if;
      end loop;
      if records<>0 then raise exception 'history was replayed';end if;
      create temporary table draft_receipt_metrics(payload_bytes bigint,records bigint);
      insert into draft_receipt_metrics values(bytes,records);
    end $$;select jsonb_build_object('payload_bytes',payload_bytes,'records',records) from draft_receipt_metrics;""")
    metrics=json.loads(result.stdout.strip())
    assert metrics['records']==0 and metrics['payload_bytes']<15000000
    assert initial['records']==20000
    assert sql('select count(*) from public.user_lifetime_draft_snapshot where scan_complete;').stdout.strip()=='10001'


def test_database_policy_preferences_and_round_mutations_restart_coverage(sql,tmp_path):
    identity,event=seed_draft(sql,3);queue=PrivateDraftJobs(tmp_path/'jobs.sqlite')
    scan_receipt(sql,event,queue);acknowledge(sql,event)
    original=sql(f"select id from public.user_narrator_source where user_id='{OWNER}' and sequence=1;").stdout.strip()
    rpc(sql,'change_user_narrator_source',f"{literal(identity['project_id'])},'{original}',1,'edit','Corrected early 原文'")
    corrected_event=new_receipt(sql,identity['project_id']);corrected=scan_receipt(sql,corrected_event,queue)
    assert corrected['first']['source_after']==corrected['first']['round_after']==0
    assert corrected['first']['policy_epoch']==2 and corrected['records']==7
    acknowledge(sql,corrected_event)
    sql(f"insert into public.user_profile(user_id,profile) values('{OWNER}','{{\"preferred_language\":\"zh-CN\"}}') on conflict(user_id) do update set profile=excluded.profile;")
    preference_event=new_receipt(sql,identity['project_id']);preferred=scan_receipt(sql,preference_event,queue)
    assert preferred['first']['source_after']==preferred['first']['round_after']==0
    assert preferred['first']['locale']=='zh-CN';acknowledge(sql,preference_event)
    memory=sql(f"insert into public.user_memory(user_id,kind,content) values('{OWNER}','memoir','Synthetic link') returning id;").stdout.strip()
    sql(f"update public.user_completed_round set memory_id='{memory}' where user_id='{OWNER}' and project_id={literal(identity['project_id'])} and ordinal=1;")
    changed_event=new_receipt(sql,identity['project_id']);changed=scan_receipt(sql,changed_event,queue)
    assert changed['first']['round_revision']==1
    assert changed['first']['source_after']==changed['first']['round_after']==0
    with queue._connect() as db:
        assert db.execute('select memory_id from private_draft_rounds where user_id=? and project_id=? and ordinal=1',
            (OWNER,identity['project_id'])).fetchone()[0]==memory


def test_database_round_mutation_rejects_inflight_cursor_and_prefixes_are_owner_scoped(sql):
    identity,event=seed_draft(sql,40)
    first=database_page(sql,event)
    # Removing an already-covered round changes the frozen metadata generation.
    sql(f"delete from public.user_completed_round where user_id='{OWNER}' and project_id={literal(identity['project_id'])} and ordinal=1;")
    assert database_page(sql,event,first['next_cursor'],check=False).returncode!=0
    new=scan_receipt(sql,event);assert new['first']['round_revision']==1
    assert new['first']['snapshot_id']!=first['snapshot_id'];acknowledge(sql,event)
    other=rpc(sql,'resolve_lifetime_conversation','null',owner=OTHER)
    other_event=new_receipt(sql,other['project_id'],OTHER)
    foreign=database_page(sql,other_event)
    assert foreign['base_snapshot_id'] is None and foreign['source_after']==foreign['round_after']==0
    assert foreign['user_id']==OTHER


def queue_until_delivered(sql,event,cadence):
    """Exercise the broker's retry contract without claiming a pending ACK."""
    calls=0
    while True:
        before=int(sql('select count(*) from public.user_memoir_milestone;').stdout.strip())
        result=json.loads(sql(f"select public.queue_memoir_receipt('{event}',{cadence});").stdout)
        calls+=1
        after=int(sql('select count(*) from public.user_memoir_milestone;').stdout.strip())
        assert 0<=after-before<=128
        delivered=sql(f"select delivered from public.user_private_draft_outbox where id='{event}';").stdout.strip()=='t'
        if not result.get('coverage_pending'):
            assert delivered is True
            return calls,result
        assert delivered is False and result['timeline_lane_id'] is None and result['composer_lane_id'] is None
        assert calls<1000


def test_database_cadence_cursor_is_bounded_and_exact_across_retries_languages_and_editions(sql):
    identity,event=seed_draft(sql,1000);scan_receipt(sql,event)
    before=sql('select row_to_json(u) from public.user_recall_usage u;').stdout
    calls,_=queue_until_delivered(sql,event,3);assert calls==3
    assert queue_until_delivered(sql,event,3)[0]==1
    sql(f"update public.user_memoir_milestone set state=case when milestone=3 then 'completed' else 'proposed' end,covered_round=999,manuscript_revision=7 where milestone in(3,6);")
    # A different cadence adds its original multiples without resetting editions.
    cadence_event=new_receipt(sql,identity['project_id']);scan_receipt(sql,cadence_event)
    assert queue_until_delivered(sql,cadence_event,5)[0]==2
    expected=set(range(3,1001,3))|set(range(5,1001,5))
    actual=json.loads(sql("select jsonb_agg(milestone order by milestone) from public.user_memoir_milestone where locale='en-AU';").stdout)
    assert actual==sorted(expected)
    states=json.loads(sql("select jsonb_agg(jsonb_build_array(milestone,state,covered_round,manuscript_revision) order by milestone) from public.user_memoir_milestone where milestone in(3,6);").stdout)
    assert states==[[3,'completed',999,7],[6,'proposed',999,7]]
    sql(f"insert into public.user_profile(user_id,profile) values('{OWNER}','{{\"preferred_language\":\"zh-CN\"}}') on conflict(user_id) do update set profile=excluded.profile;")
    changed=new_receipt(sql,identity['project_id']);scan_receipt(sql,changed)
    assert queue_until_delivered(sql,changed,7)[0]==2
    chinese=json.loads(sql("select jsonb_agg(milestone order by milestone) from public.user_memoir_milestone where locale='zh-CN';").stdout)
    assert chinese==list(range(7,1001,7))
    assert sql('select row_to_json(u) from public.user_recall_usage u;').stdout==before
    # Removing then backfilling an old completed-round position changes the
    # metadata fence but never invents an extra milestone or alters identity.
    turn=sql("select turn_id from public.user_completed_round where ordinal=2;").stdout.strip()
    sql('delete from public.user_completed_round where ordinal=2;')
    sql(f"insert into public.user_completed_round(user_id,project_id,turn_id,ordinal) values('{OWNER}',{literal(identity['project_id'])},'{turn}',2);")
    late=new_receipt(sql,identity['project_id']);scan_receipt(sql,late)
    assert queue_until_delivered(sql,late,7)[0]==1
    assert json.loads(sql("select jsonb_agg(milestone order by milestone) from public.user_memoir_milestone where locale='zh-CN';").stdout)==chinese
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='1000'


def test_database_precoverage_cursor_envelope_stays_immutable_after_upgrade(sql):
    identity,event=seed_draft(sql,40)
    first=database_page(sql,event)
    sql(f"update public.user_lifetime_draft_snapshot set coverage_schema_version=0 where id='{first['snapshot_id']}';")
    old_fields={'coverage_schema_version','base_snapshot_id','source_after','round_after','round_revision'}
    expected={k:v for k,v in first.items() if k not in old_fields}
    assert database_page(sql,event)==expected
    result=scan_receipt(sql,event)
    assert result['records']==80 and not old_fields.intersection(result['last'])
    assert database_page(sql,event)==expected
    acknowledge(sql,event)
    repeated=database_page(sql,new_receipt(sql,identity['project_id']))
    assert repeated['base_snapshot_id']==first['snapshot_id'] and repeated['records']==[]


def test_upgrade_bootstraps_monotonic_generation_fence_without_resetting_receipts(tmp_path):
    queue=PrivateDraftJobs(tmp_path/'jobs.sqlite')
    newest=delta_page(1,epoch=4,preference=5,round_revision=6);ingest(queue,newest)
    with queue._connect() as db:db.execute('delete from private_draft_page_state')
    with pytest.raises(ValueError):ingest(queue,delta_page(2,epoch=4,preference=4,round_revision=6))
    current=delta_page(2,epoch=4,preference=5,round_revision=6);ingest(queue,current)
    with queue._connect() as db:
        assert db.execute('select count(*) from private_draft_page_state').fetchone()[0]==1
    assert queue.page_resume('event-1')['complete'] is True


def test_database_missing_middle_position_cannot_attest_full_coverage(sql):
    identity,event=seed_draft(sql,3)
    sql('delete from public.user_lifetime_source_position where sequence=2;')
    assert database_page(sql,event,check=False).returncode!=0
    assert acknowledge(sql,event,check=False).returncode!=0
    assert sql('select count(*) from public.user_lifetime_draft_snapshot where scan_complete;').stdout.strip()=='0'


def test_database_ungoverned_history_without_positions_requires_inventory(sql):
    identity,event=seed_draft(sql,3)
    sql('delete from public.user_lifetime_source_position;')
    assert database_page(sql,event,check=False).returncode!=0
    assert acknowledge(sql,event,check=False).returncode!=0


def test_missing_middle_position_cannot_complete_a_local_receipt(tmp_path):
    queue=PrivateDraftJobs(tmp_path/'jobs.sqlite');page=delta_page(3,after=0)
    with pytest.raises(ValueError):ingest(queue,page)


from test_consolidated_migration_upgrade import consolidated_database,ROOT


def test_database_actual_preposition_upgrade_does_not_claim_legacy_history_coverage(consolidated_database):
    sql=consolidated_database
    migrations=sorted(ROOT.glob('*.sql'))
    cut=next(i for i,path in enumerate(migrations) if path.name.startswith('202610120006_'))
    for path in migrations[:cut]:sql(path.read_text())
    rpc(sql,'accept_user_narrator_source',f"'historical-project','{uuid4()}','Untouched historical 原文'")
    # Synthetic operator mapping only. The additive deployment never maps or
    # inventories pre-existing evidence on an owner's behalf.
    sql(f"insert into public.user_lifetime_conversation(user_id,project_id) values('{OWNER}','historical-project');")
    before=sql('select row_to_json(s) from public.user_narrator_source s;').stdout
    for path in migrations[cut:]:sql(path.read_text())
    assert sql('select row_to_json(s) from public.user_narrator_source s;').stdout==before
    assert sql('select count(*) from public.user_lifetime_source_position;').stdout.strip()=='0'
    event=new_receipt(sql,'historical-project')
    assert database_page(sql,event,check=False).returncode!=0
    assert acknowledge(sql,event,check=False).returncode!=0


def test_prefix_proof_cannot_disappear_halfway_through_a_local_receipt(tmp_path):
    queue=PrivateDraftJobs(tmp_path/'jobs.sqlite');page=delta_page(2)
    page.update(complete=False,next_cursor='next',records=page['records'][:1]);ingest(queue,page)
    final={k:v for k,v in page.items() if k not in {'coverage_schema_version','base_snapshot_id','source_after','round_after','round_revision'}}
    final.update(cursor='next',next_cursor=None,complete=True,records=[{'record_type':'round','turn_id':'turn-2','ordinal':2,'memory_id':None}])
    with pytest.raises(ValueError):ingest(queue,final)


@pytest.mark.parametrize('mutation',['policy','preferences','round'])
def test_database_scope_change_after_complete_page_requires_fresh_intake_before_ack(sql,mutation):
    identity,event=seed_draft(sql,3);old=scan_receipt(sql,event)
    if mutation=='policy':
        original=sql('select id from public.user_narrator_source where sequence=1;').stdout.strip()
        rpc(sql,'change_user_narrator_source',f"{literal(identity['project_id'])},'{original}',1,'edit','Newly corrected source'")
    elif mutation=='preferences':
        sql(f"insert into public.user_profile(user_id,profile) values('{OWNER}','{{\"preferred_language\":\"zh-CN\"}}') on conflict(user_id) do update set profile=excluded.profile;")
    else:sql('delete from public.user_completed_round where ordinal=1;')
    for command in (f"select public.queue_memoir_receipt('{event}',5);",f"update public.user_private_draft_outbox set delivered=true where id='{event}';"):
        failure=sql(command,check=False)
        assert failure.returncode!=0 and 'private draft receipt scope stale' in failure.stderr
    current=scan_receipt(sql,event)
    assert current['first']['snapshot_id']!=old['first']['snapshot_id']
    assert current['first']['base_snapshot_id'] is None
    assert queue_until_delivered(sql,event,5)[1]['timeline_lane_id']


import asyncio
import httpx


@pytest.mark.parametrize('active',[False,True])
@pytest.mark.parametrize('primed',[False,True])
def test_broker_restarts_complete_receipt_after_authoritative_scope_conflict(tmp_path,monkeypatch,active,primed):
    from apps.api.private_draft_broker import PrivateDraftBroker
    from apps.api.memory_event_worker import MemoirLaneBroker
    path=tmp_path/'jobs.sqlite';queue=PrivateDraftJobs(path)
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(path));monkeypatch.setenv('SUPABASE_URL','https://synthetic.invalid')
    monkeypatch.setenv('SUPABASE_SECRET_KEY','synthetic-fixture-key')
    old=delta_page(1);current={**delta_page(1,epoch=2),'snapshot_id':'replacement'}
    if primed:ingest(queue,old)
    calls={'page':0,'ack':0}
    def handler(request):
        name=request.url.path.split('/')[-1]
        if request.method=='GET':return httpx.Response(200,json=[{'id':'event-1'}])
        if name=='pending_memoir_receipts':return httpx.Response(200,json=['event-1'])
        if name=='read_memoir_receipt_scope':return httpx.Response(200,json={'conversation_id':'conversation','change_kind':'round'})
        if name in {'private_draft_event_page','private_draft_event_snapshot'}:
            calls['page']+=1
            return httpx.Response(200,json=current if calls['ack'] else old)
        if request.method=='PATCH' or name=='queue_memoir_receipt':
            calls['ack']+=1
            return httpx.Response(500,json={'code':'40001','message':'private draft receipt scope stale'}) if calls['ack']==1 else httpx.Response(200,json={})
        raise AssertionError(name)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            broker=MemoirLaneBroker(client=client) if active else PrivateDraftBroker(client=client)
            await broker.drain_once()
            assert queue.page_resume('event-1') is None
            await broker.drain_once()
    asyncio.run(run())
    assert calls=={'page':1 if primed else 2,'ack':2}
    assert queue.page_resume('event-1')['snapshot_id']=='replacement'
    assert queue.page_resume('event-1')['complete'] is True


@pytest.mark.parametrize('active',[False,True])
def test_unrelated_ack_failure_preserves_completed_receipt_for_retry(tmp_path,monkeypatch,active):
    from apps.api.private_draft_broker import PrivateDraftBroker
    from apps.api.memory_event_worker import MemoirLaneBroker
    path=tmp_path/'jobs.sqlite';queue=PrivateDraftJobs(path);ingest(queue,delta_page(1))
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(path));monkeypatch.setenv('SUPABASE_URL','https://synthetic.invalid')
    monkeypatch.setenv('SUPABASE_SECRET_KEY','synthetic-fixture-key')
    calls=[]
    def handler(request):
        name=request.url.path.split('/')[-1];calls.append(name)
        if request.method=='GET':return httpx.Response(200,json=[{'id':'event-1'}])
        if name=='pending_memoir_receipts':return httpx.Response(200,json=['event-1'])
        if name=='read_memoir_receipt_scope':return httpx.Response(200,json={'conversation_id':'conversation','change_kind':'round'})
        if request.method=='PATCH' or name=='queue_memoir_receipt':return httpx.Response(500,json={'code':'XX000','message':'retry later'})
        raise AssertionError('completed receipt must not reload sources')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            broker=MemoirLaneBroker(client=client) if active else PrivateDraftBroker(client=client)
            with pytest.raises(httpx.HTTPStatusError):await broker.drain_once()
    asyncio.run(run())
    assert queue.page_resume('event-1')['complete'] is True
    assert not any(name.startswith('private_draft_event_') for name in calls)


def test_database_concurrent_distinct_receipts_share_one_exact_milestone_cursor(sql):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    identity,event=seed_draft(sql,20);scan_receipt(sql,event)
    other=new_receipt(sql,identity['project_id']);scan_receipt(sql,other)
    barrier=Barrier(2)
    def dispatch(receipt):
        barrier.wait(timeout=5)
        return sql(f"set statement_timeout='3s';select public.queue_memoir_receipt('{receipt}',5);",check=False)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(dispatch,[event,other]))
    assert all(result.returncode==0 for result in results),[result.stderr for result in results]
    assert sql('select count(*) from public.user_lifetime_milestone_cursor;').stdout.strip()=='1'
    assert sql('select count(*) from public.user_memoir_milestone;').stdout.strip()=='4'
    assert sql('select count(*) from public.user_memoir_lane;').stdout.strip()=='2'
    assert sql(f"select count(*) from public.user_private_draft_outbox where id in('{event}','{other}') and delivered;").stdout.strip()=='2'


@pytest.mark.parametrize('active',[False,True])
def test_inflight_sqlstate_conflict_restarts_even_when_transport_status_is_500(tmp_path,monkeypatch,active):
    from apps.api.private_draft_broker import PrivateDraftBroker
    from apps.api.memory_event_worker import MemoirLaneBroker
    path=tmp_path/'jobs.sqlite';queue=PrivateDraftJobs(path)
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(path));monkeypatch.setenv('SUPABASE_URL','https://synthetic.invalid')
    monkeypatch.setenv('SUPABASE_SECRET_KEY','synthetic-fixture-key')
    old=delta_page(1);old.update(complete=False,next_cursor='old-cursor',round_high_water=2);ingest(queue,old)
    current={**old,'snapshot_id':'current','policy_epoch':2,'next_cursor':None,'complete':True,
        'records':old['records']+[{'record_type':'round','turn_id':'turn-2','ordinal':2,'memory_id':None}]}
    pages=[]
    def handler(request):
        name=request.url.path.split('/')[-1]
        if request.method=='GET':return httpx.Response(200,json=[{'id':'event-1'}])
        if name=='pending_memoir_receipts':return httpx.Response(200,json=['event-1'])
        if name=='read_memoir_receipt_scope':return httpx.Response(200,json={'conversation_id':'conversation','change_kind':'round'})
        if name in {'private_draft_event_page','private_draft_event_snapshot'}:
            cursor=json.loads(request.content).get('p_cursor');pages.append(cursor)
            return httpx.Response(500,json={'code':'40001','message':'stale private draft snapshot'}) if cursor else httpx.Response(200,json=current)
        if request.method=='PATCH' or name=='queue_memoir_receipt':return httpx.Response(200,json={})
        raise AssertionError(name)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            broker=MemoirLaneBroker(client=client) if active else PrivateDraftBroker(client=client)
            await broker.drain_once()
    asyncio.run(run())
    assert pages==['old-cursor',None]
    assert queue.page_resume('event-1')['snapshot_id']=='current'
    assert queue.page_resume('event-1')['complete'] is True
