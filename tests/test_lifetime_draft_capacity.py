"""Bounded governed draft intake; completion never implies composition approval."""
import asyncio
import copy
import json
from uuid import uuid4

import httpx
import pytest

from apps.api.private_draft_jobs import PrivateDraftJobs
from apps.api.private_draft_broker import PrivateDraftBroker


def draft_page(*, cursor=None, next_cursor='next', complete=False, ordinal=0, epoch=1, snapshot='snapshot', records=None, source_revision=0, round_high_water=10000):
    return {'schema_version': 1, 'protocol': 'lifetime_draft_pages', 'snapshot_id': snapshot,
        'event_id': 'event', 'user_id': 'owner', 'project_id': 'project', 'conversation_id': 'conversation',
        'policy_epoch': epoch, 'preference_revision': 0, 'source_revision': source_revision, 'event_revision': 0,
        'round_high_water': round_high_water, 'completed': 20, 'locale': 'en-AU', 'cursor': cursor,
        'next_cursor': next_cursor, 'complete': complete, 'records': records or ([
            {'record_type': 'round', 'turn_id': str(ordinal), 'memory_id': None, 'ordinal': ordinal}
        ] if ordinal else [])}


def ingest(queue, page):
    return queue.synchronize_page(page, free_limit=20, cadence=5, enabled=True)


def test_page_receipts_survive_restart_replay_without_model_or_raw_history(tmp_path):
    path=tmp_path/'jobs.sqlite'; queue=PrivateDraftJobs(path)
    first=draft_page(source_revision=1,round_high_water=1,records=[{'record_type':'source','source_id':'source','version':1,'sequence':1,
        'char_start':0,'char_end':17,'text':'Sensitive 原文 data','status':'active','kind':'narrator_chat','language':'zh-CN'}])
    result=ingest(queue,first)
    assert result['retrieval_complete'] is False and result['next_cursor']=='next'
    assert queue.page_resume('event')['next_cursor']=='next'
    assert ingest(PrivateDraftJobs(path),first)==result
    last=draft_page(cursor='next',next_cursor=None,complete=True,ordinal=1,source_revision=1,round_high_water=1)
    final=ingest(queue,last)
    assert final['retrieval_complete'] is True and final['status']=='pending'
    assert final['error']=='LIFETIME_COMPOSER_PENDING'
    assert final['round_high_water']==1 and final['milestone']==0
    assert queue.pending_ids()==[]
    assert queue.claim(final['job_id']) is None
    assert 'Sensitive' not in path.read_bytes().decode('latin1')
    with queue._connect() as db:
        assert db.execute('select count(*) from private_draft_page_receipts').fetchone()[0]==2
        assert db.execute('select max(ordinal) from private_draft_rounds').fetchone()[0]==1
        payload=json.loads(db.execute('select payload from private_draft_jobs').fetchone()[0])
        assert payload['completed']==20 and payload['enabled'] is True
        assert 'sources' not in payload and 'rounds' not in payload


def test_ten_thousand_records_use_bounded_durable_pages_and_exact_rounds(tmp_path):
    queue=PrivateDraftJobs(tmp_path/'jobs.sqlite')
    for start in range(0,10000,32):
        end=min(start+32,10000)
        result=ingest(queue,draft_page(cursor=str(start) if start else None,
            next_cursor=str(end) if end<10000 else None,complete=end==10000,
            records=[{'record_type':'round','turn_id':str(n),'memory_id':None,'ordinal':n} for n in range(start+1,end+1)]))
        assert len(json.dumps(result))<2048
    assert result['record_count']==10000 and result['page_count']==313
    with queue._connect() as db:
        assert db.execute('select count(*) from private_draft_rounds').fetchone()[0]==10000
        assert db.execute('select length(checkpoint) from private_draft_jobs').fetchone()[0]<2048


@pytest.mark.parametrize('mutation',[
    {'complete':True,'next_cursor':'next'}, {'complete':False,'next_cursor':None},
    {'schema_version':2}, {'records':[{}]*33}, {'cursor':'out-of-order'},
    {'records':[{'record_type':'source','text':'x'*2049}]},
])
def test_malformed_partial_or_out_of_order_pages_cannot_publish(tmp_path,mutation):
    queue=PrivateDraftJobs(tmp_path/'jobs.sqlite')
    with pytest.raises(ValueError):ingest(queue,{**draft_page(),**mutation})
    assert queue.pending_ids()==[]


def test_page_replay_content_conflict_scope_conflict_and_epoch_fence(tmp_path):
    queue=PrivateDraftJobs(tmp_path/'jobs.sqlite')
    first=draft_page(ordinal=1);ingest(queue,first)
    altered=copy.deepcopy(first);altered['records'][0]['memory_id']='changed'
    with pytest.raises(ValueError):ingest(queue,altered)
    with pytest.raises(ValueError):ingest(queue,{**draft_page(cursor='next'), 'user_id':'other'})
    result=ingest(queue,draft_page(epoch=2,snapshot='replacement'))
    assert result['retrieval_complete'] is False
    with pytest.raises(ValueError):ingest(queue,first)
    with queue._connect() as db:
        assert db.execute("select status from private_draft_jobs where source_key='snapshot'").fetchone()[0]=='STALE'


def test_broker_bounds_each_drain_and_resumes_after_failure_before_ack(tmp_path,monkeypatch):
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(tmp_path/'jobs.sqlite'))
    monkeypatch.setenv('SUPABASE_URL','https://fixture.test');monkeypatch.setenv('SUPABASE_SECRET_KEY','synthetic')
    calls=[];fail=True
    def handle(request):
        nonlocal fail
        if request.method=='GET':return httpx.Response(200,json=[{'id':'event'}])
        if request.method=='PATCH':
            if fail:fail=False;return httpx.Response(503)
            calls.append('ack');return httpx.Response(204)
        args=json.loads(request.content);cursor=args.get('p_cursor');calls.append(cursor)
        n=int(cursor or 0);done=n==9
        return httpx.Response(200,json=draft_page(cursor=cursor,next_cursor=None if done else str(n+1),complete=done,ordinal=n+1,round_high_water=10))
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            broker=PrivateDraftBroker(client=client)
            await broker.drain_once()
            assert 'ack' not in calls and len(calls)<=8
            with pytest.raises(httpx.HTTPStatusError):await broker.drain_once()
            await broker.drain_once()
    asyncio.run(run())
    assert calls.count('ack')==1
    assert PrivateDraftJobs(tmp_path/'jobs.sqlite').page_resume('event')['complete'] is True


def test_governed_collection_and_preview_never_start_full_history_reads(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from apps.api.private_drafts import synchronize
    from apps.api.lifetime_memory_read_api import unsupported_collection_job
    from fastapi import HTTPException
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','true')
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(tmp_path/'jobs.sqlite'))
    def forbidden(*args,**kwargs):raise AssertionError('unbounded read attempted')
    head={'status':'pending','error':'LIFETIME_COMPOSER_PENDING','retrieval_complete':False}
    identity={'owner_id':'11111111-1111-4111-8111-111111111111',
        'conversation_id':'cccccccc-cccc-4ccc-8ccc-cccccccccccc','project_id':'project'}
    calls=[]
    def lifetime_rpc(name,**parameters):
        calls.append(name)
        assert parameters=={'p_project_id':'project'}
        if name=='read_lifetime_project_identity':return identity
        if name=='read_lifetime_private_draft_head':return head
        raise AssertionError('Unexpected lifetime RPC: '+name)
    storage=SimpleNamespace(user_id=identity['owner_id'],is_anonymous=False,
        lifetime_rpc=lifetime_rpc,private_draft_rounds=forbidden,
        memories=forbidden,all_memories=forbidden,composition_memories=forbidden)
    assert synchronize(storage,'project')==head
    with pytest.raises(HTTPException) as error:unsupported_collection_job(storage,'project')
    assert error.value.status_code==409
    assert error.value.headers['X-Error-Code']=='LIFETIME_COLLECTION_JOB_UNSUPPORTED'
    assert calls==['read_lifetime_private_draft_head','read_lifetime_project_identity']


def test_page_policy_settings_do_not_grant_composition_or_increment_rounds(tmp_path):
    queue=PrivateDraftJobs(tmp_path/'jobs.sqlite')
    page=draft_page(next_cursor=None,complete=True,round_high_water=5,records=[{'record_type':'round','turn_id':str(n),'ordinal':n} for n in range(1,6)])
    ingest(queue,page)
    result=queue.synchronize_page(page,free_limit=7,cadence=3,enabled=False)
    assert result['milestone']==3 and result['retrieval_complete'] is True
    assert queue.pending_ids()==[]
    with queue._connect() as db:
        assert db.execute('select count(*) from private_draft_rounds').fetchone()[0]==5
        payload=json.loads(db.execute('select payload from private_draft_jobs').fetchone()[0])
        assert payload['enabled'] is False and payload['completed']==20


# Real PostgreSQL is isolated and never reads configured accounts.
from test_lifetime_memory_postgres import sql,event_database,private_database,attachment_database,database
from test_agent_commit_postgres import OWNER,OTHER,as_user
from test_shared_memory_events_postgres import rpc,literal


def database_page(sql,event,cursor=None,limit=32,check=True):
    statement=f"select public.private_draft_event_page('{event}',"+('null' if cursor is None else f"'{cursor}'")+f",{limit});"
    result=sql(statement,check=check)
    return json.loads(result.stdout.strip()) if check else result


def seed_draft(sql,count=3):
    identity=rpc(sql,'resolve_lifetime_conversation','null');project=identity['project_id']
    sql(f"""insert into public.user_narrator_source(user_id,project_id,client_turn_id,sequence,text,kind,language)
        select '{OWNER}',{literal(project)},gen_random_uuid(),n,'English 中文 memory '||n,'narrator_chat',
        case when n%2=0 then 'en-AU' else 'zh-CN' end from generate_series(1,{count}) n;
        update public.user_memoir_project set source_sequence={count} where user_id='{OWNER}' and project_id={literal(project)};
        insert into public.user_completed_round(user_id,project_id,turn_id,ordinal)
        select '{OWNER}',{literal(project)},gen_random_uuid(),n from generate_series(1,{count}) n;
        insert into public.user_private_draft_outbox(user_id,project_id,change_kind) values('{OWNER}',{literal(project)},'round');""")
    # Explicitly reconcile this isolated synthetic bulk fixture through the real
    # literal parser. Production imports remain pending without approved review.
    sql(f"select public.apply_lifetime_literal_policy(user_id,project_id,id,version) from public.user_narrator_source where user_id='{OWNER}' and project_id={literal(project)};")
    event=sql(f"select id from public.user_private_draft_outbox where user_id='{OWNER}' and project_id={literal(project)} order by created_at desc,id desc limit 1;").stdout.strip()
    return identity,event


def test_database_ten_thousand_sources_rounds_complete_bounded_snapshot(sql,tmp_path):
    identity,event=seed_draft(sql,10000)
    queue=PrivateDraftJobs(tmp_path/'jobs.sqlite');result=database_page(sql,event)
    originals=[];rounds=[];maximum=0;pages=0
    while True:
        assert result['user_id']==OWNER and result['conversation_id']==identity['conversation_id']
        assert len(result['records'])<=32
        maximum=max(maximum,len(json.dumps(result,ensure_ascii=False).encode()));pages+=1
        originals.extend(record for record in result['records'] if record['record_type']=='source')
        rounds.extend(record for record in result['records'] if record['record_type']=='round')
        view=ingest(queue,result)
        if result['complete']:break
        result=database_page(sql,event,result['next_cursor'])
    assert [row['sequence'] for row in originals]==list(range(1,10001))
    assert [row['ordinal'] for row in rounds]==list(range(1,10001))
    assert sum(len(row['text']) for row in originals)>120000
    assert maximum<350000 and pages==625
    assert view['record_count']==20000 and view['milestone']==10000
    assert view['retrieval_complete'] is True and view['error']=='LIFETIME_COMPOSER_PENDING'
    assert not queue.pending_ids()


def test_database_chunk_boundaries_frozen_highwater_cursor_scope_and_policy(sql):
    identity,event=seed_draft(sql)
    first_id=sql(f"select id from public.user_narrator_source where user_id='{OWNER}' and sequence=1;").stdout.strip()
    original='Mixed English 中文 '*300
    rpc(sql,'change_user_narrator_source',f"{literal(identity['project_id'])},'{first_id}',1,'edit',{literal(original)}")
    first=database_page(sql,event,limit=1)
    assert first['complete'] is False and first['records'][0]['status']=='superseded'
    assert database_page(sql,event,limit=1)==first
    # A later append is not silently included in a frozen historical receipt.
    rpc(sql,'accept_user_narrator_source',f"{literal(identity['project_id'])},'{uuid4()}','Later source'")
    assert database_page(sql,event,limit=1)==first
    rows=[];page=first
    while True:
        rows.extend(page['records'])
        if page['complete']:break
        page=database_page(sql,event,page['next_cursor'],limit=1)
    assert ''.join(row['text'] or '' for row in rows if row.get('source_id')==first_id)==original
    assert len({(r.get('record_type'),r.get('sequence'),r.get('char_start'),r.get('ordinal')) for r in rows})==len(rows)
    assert all(r.get('sequence',0)<=4 for r in rows)
    assert database_page(sql,event,str(uuid4()),check=False).returncode!=0
    other=rpc(sql,'resolve_lifetime_conversation','null',owner=OTHER)
    other_event=sql(f"insert into public.user_private_draft_outbox(user_id,project_id,change_kind) values('{OTHER}',{literal(other['project_id'])},'round') returning id;").stdout.splitlines()[0]
    assert database_page(sql,other_event,first['next_cursor'],check=False).returncode!=0
    assert sql(as_user(f"select public.private_draft_event_page('{event}');"),check=False).returncode!=0
    assert sql(as_user('select * from public.user_lifetime_draft_cursor;'),check=False).returncode!=0
    rpc(sql,'change_user_narrator_source',f"{literal(identity['project_id'])},'{first_id}',2,'withdraw',null")
    assert database_page(sql,event,first['next_cursor'],check=False).returncode!=0
    replacement=database_page(sql,event)
    assert replacement['snapshot_id']!=first['snapshot_id'] and original not in json.dumps(replacement)


def test_database_dispatches_canonical_pages_and_leaves_unmapped_history_unavailable(sql):
    identity,event=seed_draft(sql)
    current=json.loads(sql(f"select public.private_draft_event_snapshot('{event}');").stdout.strip())
    assert current['protocol']=='lifetime_draft_pages'
    head=rpc(sql,'read_lifetime_private_draft_head',literal(identity['project_id']))
    assert head['error']=='LIFETIME_COMPOSITION_PENDING'
    assert rpc(sql,'read_lifetime_private_draft_head',literal('arbitrary-project'))['error']=='LIFETIME_PROJECT_REQUIRED'
    assert rpc(sql,'read_lifetime_private_draft_head',literal(identity['project_id']),owner=OTHER) is None
    lane=sql(f"insert into public.user_memoir_lane(user_id,project_id,skill,pending) values('{OWNER}',{literal(identity['project_id'])},'timeline',true) on conflict(user_id,project_id,skill) do update set pending=true returning id;").stdout.splitlines()[0]
    claim=json.loads(sql(f"select public.claim_memoir_lane('{lane}');").stdout.strip())
    assert claim['protocol']=='lifetime_composer_pages'
    assert len(claim['source']['text'])<=2304 and 'context_sources' not in claim
    assert claim['previous'] is None and claim['complete'] is False
    # Unmapped receipts have no fallback adapter or worker dispatch.
    legacy=rpc(sql,'accept_user_narrator_source',f"'historical','{uuid4()}','Existing legacy account'",owner=OTHER)
    old_event=sql(f"insert into public.user_private_draft_outbox(user_id,project_id,change_kind) values('{OTHER}','historical','accepted') returning id;").stdout.splitlines()[0]
    old=json.loads(sql(f"select coalesce(public.private_draft_event_snapshot('{old_event}'),'null'::jsonb);").stdout.strip())
    assert old is None
    assert sql(f"select count(*) from public.user_lifetime_conversation where user_id='{OTHER}';").stdout.strip()=='0'


def test_active_lane_broker_checkpoints_governed_pages_before_acknowledging(tmp_path,monkeypatch):
    from apps.api.memory_event_worker import MemoirLaneBroker
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(tmp_path/'jobs.sqlite'))
    calls=[]
    class Broker(MemoirLaneBroker):
        def __init__(self):pass
        async def rpc(self,name,**payload):
            calls.append((name,payload))
            if name=='pending_memoir_receipts':return ['event']
            if name=='read_memoir_receipt_scope':return {'conversation_id':'conversation','change_kind':'round'}
            if name=='private_draft_event_page':
                n=int(payload.get('p_cursor') or 0);done=n==9
                return draft_page(cursor=payload.get('p_cursor'),next_cursor=None if done else str(n+1),complete=done,ordinal=n+1,round_high_water=10)
            if name=='queue_memoir_receipt':
                assert PrivateDraftJobs(tmp_path/'jobs.sqlite').page_resume('event')['complete']
                return {'timeline_lane_id':'timeline','composer_lane_id':'composer'}
            raise AssertionError(name)
    async def run():
        broker=Broker()
        assert await broker.drain_once()==[]
        assert sum(name=='private_draft_event_page' for name,_ in calls)==8
        assert await broker.drain_once()==['timeline','composer']
    asyncio.run(run())
    assert sum(name=='queue_memoir_receipt' for name,_ in calls)==1


def test_database_active_dispatch_restarts_without_early_ack_or_commercial_mutation(sql,tmp_path,monkeypatch):
    from apps.api.memory_event_worker import MemoirLaneBroker
    from memoir_postgres_workflow import PostgresRest
    identity,event=seed_draft(sql,300)
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(tmp_path/'jobs.sqlite'))
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(PostgresRest(sql,OWNER,service=True).handle)) as client:
            assert await MemoirLaneBroker(url='http://synthetic.invalid',key='synthetic',client=client).drain_once()==[]
            assert sql(f"select delivered from public.user_private_draft_outbox where id='{event}';").stdout.strip()=='f'
            assert await MemoirLaneBroker(url='http://synthetic.invalid',key='synthetic',client=client).drain_once()==[]
            lanes=await MemoirLaneBroker(url='http://synthetic.invalid',key='synthetic',client=client).drain_once()
            assert len(lanes)==2
            assert sql(f"select delivered from public.user_private_draft_outbox where id='{event}';").stdout.strip()=='t'
            assert PrivateDraftJobs(tmp_path/'jobs.sqlite').page_resume(event)['record_count']==600
            assert await MemoirLaneBroker(url='http://synthetic.invalid',key='synthetic',client=client).drain_once()==[]
    asyncio.run(run())
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='300'
    assert sql('select count(*) from public.user_recall_usage;').stdout.strip()=='0'
    assert sql('select count(*) from public.user_memoir_edition;').stdout.strip()=='0'
    assert sql('select max(target_milestone) from public.user_memoir_lane;').stdout.strip()=='300'


def test_active_broker_missing_durable_store_keeps_receipt_pending(monkeypatch):
    from apps.api.memory_event_worker import MemoirLaneBroker
    monkeypatch.delenv('MEMORY_SPARK_TASK_DB',raising=False)
    class Broker(MemoirLaneBroker):
        def __init__(self):pass
        async def rpc(self,name,**parameters):
            if name=='pending_memoir_receipts':return ['event']
            if name=='read_memoir_receipt_scope':return {'conversation_id':'conversation','change_kind':'round'}
            raise AssertionError('receipt must not be acknowledged')
    with pytest.raises(RuntimeError,match='store unavailable'):asyncio.run(Broker().drain_once())


def test_completion_cannot_be_claimed_without_both_frozen_highwaters(tmp_path):
    queue=PrivateDraftJobs(tmp_path/'jobs.sqlite')
    with pytest.raises(ValueError,match='coverage is incomplete'):
        ingest(queue,draft_page(complete=True,next_cursor=None))
    with pytest.raises(ValueError,match='coverage is incomplete'):
        ingest(queue,draft_page(complete=True,next_cursor=None,round_high_water=0,source_revision=2))
    assert queue.page_resume('event') is None


def test_parallel_same_epoch_receipts_do_not_cancel_each_others_pagination(tmp_path):
    queue=PrivateDraftJobs(tmp_path/'jobs.sqlite')
    first=draft_page(snapshot='one',ordinal=1,round_high_water=2)
    second={**draft_page(snapshot='two',ordinal=1,round_high_water=2),'event_id':'second-event'}
    ingest(queue,first);ingest(queue,second)
    assert queue.page_resume('event')['complete'] is False
    for page in (first,second):
        final={**page,'cursor':'next','next_cursor':None,'complete':True,
            'records':[{'record_type':'round','turn_id':'2','ordinal':2}]}
        assert ingest(queue,final)['retrieval_complete'] is True
    with queue._connect() as db:
        assert db.execute('select count(*) from private_draft_rounds').fetchone()[0]==2
        assert db.execute("select count(*) from private_draft_jobs where status='BLOCKED'").fetchone()[0]==2


@pytest.mark.parametrize('older_revision',[1,2])
def test_delayed_preference_or_conflicting_locale_cannot_revoke_newer_snapshot(tmp_path,older_revision):
    queue=PrivateDraftJobs(tmp_path/'jobs.sqlite')
    current={**draft_page(snapshot='current'), 'event_id':'current-event','preference_revision':2,'locale':'zh-CN'}
    delayed={**draft_page(snapshot='delayed'),'preference_revision':older_revision,'locale':'en-AU'}
    ingest(queue,current)
    with pytest.raises(ValueError):ingest(queue,delayed)
    assert queue.page_resume('current-event')['snapshot_id']=='current'
    assert ingest(queue,current)['retrieval_complete'] is False


def test_maximum_source_page_includes_json_escape_expansion(tmp_path):
    queue=PrivateDraftJobs(tmp_path/'jobs.sqlite')
    page=draft_page(complete=True,next_cursor=None,round_high_water=0,source_revision=1,
        records=[{'record_type':'source','source_id':'source','sequence':1,'version':1,
            'char_start':n*2048,'char_end':(n+1)*2048,'text':'\x01'*2048,'status':'active',
            'kind':'narrator_chat','language':'en-AU'} for n in range(32)])
    assert len(json.dumps(page,ensure_ascii=False).encode())>350000
    assert ingest(queue,page)['retrieval_complete'] is True


def test_revocation_retries_purge_legacy_bytes_without_destroying_current_page_receipt(tmp_path,monkeypatch):
    from apps.api.memory_event_worker import MemoirLaneBroker
    from test_private_drafts import sync
    path=tmp_path/'jobs.sqlite';queue=PrivateDraftJobs(path);sync(queue,5)
    old_job=queue.pending_ids()[0]
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(path))
    requested=[];acknowledged=0
    class Broker(MemoirLaneBroker):
        def __init__(self):pass
        async def rpc(self,name,**parameters):
            nonlocal acknowledged
            if name=='pending_memoir_receipts':return ['event']
            if name=='read_memoir_receipt_scope':return {'conversation_id':'conversation',
                'change_kind':'revocation','user_id':'owner','project_id':'project'}
            if name=='private_draft_event_page':
                n=int(parameters.get('p_cursor') or 0);requested.append(n)
                return draft_page(cursor=parameters.get('p_cursor'),next_cursor=None if n==9 else str(n+1),
                    complete=n==9,ordinal=n+1,round_high_water=10)
            if name=='queue_memoir_receipt':
                acknowledged+=1
                if acknowledged==1:
                    httpx.Response(503,request=httpx.Request('POST','https://fixture.invalid')).raise_for_status()
                return {'timeline_lane_id':'timeline'}
            raise AssertionError(name)
    async def run():
        broker=Broker()
        assert await broker.drain_once()==[]
        with pytest.raises(httpx.HTTPStatusError):await broker.drain_once()
        assert await broker.drain_once()==['timeline']
    asyncio.run(run())
    assert requested==list(range(10)) and queue.page_resume('event')['complete'] is True
    with queue._connect() as db:
        old=db.execute('select status,payload,checkpoint from private_draft_jobs where id=?',(old_job,)).fetchone()
        assert tuple(old)==('STALE','{}','{}')
        assert db.execute('select payload from private_draft_projects').fetchone()[0]=='{}'
