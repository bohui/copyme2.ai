"""Incomplete-policy maintenance must preserve queued canonical work."""
import asyncio
import copy
import json

import httpx
import pytest

from apps.api.lifetime_memory_policy import PolicyUnavailable
from apps.api.memory_event_worker import MemoryEventWorker
from test_lifetime_composer_clearance import composer_page, Publisher
from test_lifetime_composer_capacity import page
from test_canonical_composer_provenance import controlled_draft


@pytest.fixture(autouse=True)
def synthetic_generation(monkeypatch):
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','true')


def policy_error(code='55000',message='LIFETIME_POLICY_PENDING'):
    request=httpx.Request('POST','https://synthetic.invalid/rest/v1/rpc/authority')
    response=httpx.Response(400,json={'code':code,'message':message},request=request)
    return httpx.HTTPStatusError('private authority diagnostics',request=request,response=response)


@pytest.mark.parametrize('stage',['claim','policy_source','extract','checkpoint','prepare_checkpoint','prepare','draft','review','commit','complete'])
def test_policy_pending_at_any_lane_boundary_is_safe_metadata_deferral(stage):
    current=page() if stage in {'policy_source','extract'} else composer_page()
    failures=[];checkpoints={};reads=0;deferred=[]
    class Broker:
        async def rpc(self,name,**payload):
            nonlocal reads
            if name=='claim_memoir_lane':
                if stage=='claim':raise policy_error()
                return current
            if name=='read_memoir_checkpoint':
                reads+=1
                if stage=='checkpoint' or stage=='prepare_checkpoint' and reads==2:raise policy_error()
                return copy.deepcopy(checkpoints.get(payload['p_key']))
            if name=='save_memoir_checkpoint':checkpoints[payload['p_key']]=copy.deepcopy(payload['p_value']);return True
            if name=='record_lifetime_lane_output':return True
            if name=='read_lifetime_lane_policy_source':
                if stage=='policy_source':raise policy_error()
                return copy.deepcopy(current['source'])
            if name=='commit_lifetime_memoir_lane_page':
                if stage=='commit':raise policy_error()
                return {'status':'page_saved'}
            if name=='read_lifetime_memoir_lane_page':return {**current,'complete':True,'source':None,'partition':None}
            if name=='complete_lifetime_memoir_lane':raise policy_error()
            if name=='defer_lifetime_memoir_lane_policy':
                assert payload==dict(p_lane_id=current['lane_id'],p_token=current['token'],p_user_id=current['user_id'],
                    p_project_id=current['project_id'],p_conversation_id=current['conversation_id'])
                deferred.append(payload)
                return {'status':'pending','error':PolicyUnavailable.code,'retrieval_complete':False}
            if name=='fail_memoir_lane':failures.append(payload);return {'status':'retry_required'}
            raise AssertionError(name)
    def model(request):
        bounded=json.loads(request.content)['bounded_lane'];phase=bounded['phase'];packet=json.loads(bounded['packet'])['payload']
        if phase==stage:raise PolicyUnavailable()
        if phase=='prepare':result=dict(event_id=current['partition']['id'],context='Source-grounded',source_refs=current['partition']['source_refs'])
        elif phase=='draft':result=controlled_draft(packet,current['source']['text'],'Childhood')
        else:result=dict(ready_for_user_review=True,publication_approved=False,findings=[])
        return httpx.Response(200,json={'reply':json.dumps(result)})
    worker=MemoryEventWorker(Broker(),worker_url='https://synthetic.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(model))
    worker.lane_publisher=Publisher()
    result=asyncio.run(worker.execute_lane(current['lane_id']))
    assert result=={'status':'pending','error':PolicyUnavailable.code,'retrieval_complete':False}
    assert not failures and len(deferred)==(0 if stage=='claim' else 1)


@pytest.mark.parametrize('code,message',[('42501','LIFETIME_POLICY_PENDING'),('55000','prefix LIFETIME_POLICY_PENDING'),('55000','Unrelated state')])
def test_claim_does_not_reclassify_other_authority_errors(code,message):
    class Broker:
        async def rpc(self,name,**payload):raise policy_error(code,message)
    worker=MemoryEventWorker(Broker(),worker_url='https://synthetic.invalid',worker_secret='synthetic')
    with pytest.raises(httpx.HTTPStatusError):asyncio.run(worker.execute_lane('synthetic'))


from test_lifetime_composer_capacity import (
    sql, event_database, private_database, attachment_database, database,
    seeded_composer, resolve, rpc, literal, service, OWNER, OTHER,
)


def mark_inventory_pending(sql,identity):
    sql(f"insert into public.user_lifetime_policy_inventory_pending values('{identity['owner_id']}',{literal(identity['project_id'])},'{identity['conversation_id']}','literal-v1') on conflict do nothing;")


def metadata_defer(sql,lane,claim,*,owner=None,project=None,conversation=None,token=None,check=True,role='service_role'):
    return sql(f"set role {role};select public.defer_lifetime_memoir_lane_policy('{lane}','{token or claim['token']}',\
        '{owner or claim['user_id']}',{literal(project or claim['project_id'])},'{conversation or claim['conversation_id']}');",check=check)


@pytest.mark.parametrize('pending_kind',['source','inventory'])
def test_pg_policy_pending_owners_do_not_starve_other_lane_or_receipt_polling(sql,pending_kind):
    # The generic project fixture intentionally retains outbox history; isolate
    # this global scheduler assertion from receipts for already removed projects.
    sql('truncate public.user_private_draft_outbox cascade;')
    identity,source,lane,claim=seeded_composer(sql);project=identity['project_id']
    service(sql,'yield_lifetime_memoir_lane',f"'{lane}','{claim['token']}'")
    if pending_kind=='inventory':mark_inventory_pending(sql,identity)
    else:sql(f"insert into public.user_lifetime_pending_policy values('{OWNER}',{literal(project)},'{identity['conversation_id']}','{source['id']}',1,'00000000-0000-4000-8000-000000000001','literal-v1');")
    ready=resolve(sql,owner=OTHER)
    rpc(sql,'accept_user_narrator_source',f"{literal(ready['project_id'])},'00000000-0000-4000-8000-000000000002','An unrelated safe memory'",owner=OTHER)
    ready_lane=sql(f"insert into public.user_memoir_lane(user_id,project_id,skill,pending) values('{OTHER}',{literal(ready['project_id'])},'timeline',true) returning id;").stdout.splitlines()[0]
    sql(f"update public.user_memoir_lane set available_at=clock_timestamp()-interval '1 day' where id='{lane}';")
    assert service(sql,'pending_memoir_lanes','1')==[ready_lane]
    receipts=service(sql,'pending_memoir_receipts','1')
    assert len(receipts)==1
    assert sql(f"select user_id from public.user_private_draft_outbox where id='{receipts[0]}';").stdout.strip()==OTHER
    assert sql(f"select count(*) from public.user_private_draft_outbox where user_id='{OWNER}' and project_id={literal(project)} and not delivered;").stdout.strip()!='0'
    assert sql("set role authenticated;select public.pending_memoir_lanes(1);",check=False).returncode!=0


@pytest.mark.parametrize('wrong',['owner','project','conversation','token','superseded','expired','expired_deadline','authenticated'])
def test_pg_policy_metadata_release_rejects_foreign_or_expired_authority(sql,wrong):
    identity,source,lane,claim=seeded_composer(sql);mark_inventory_pending(sql,identity)
    if wrong=='expired':sql(f"update public.user_memoir_lane set lease_until=clock_timestamp()-interval '1 second' where id='{lane}';")
    if wrong=='expired_deadline':sql(f"update public.user_memoir_lane set run_deadline=clock_timestamp()-interval '1 second' where id='{lane}';")
    if wrong=='superseded':sql(f"update public.user_memoir_lane set token=gen_random_uuid() where id='{lane}';")
    before=sql(f"select to_jsonb(l)::text from public.user_memoir_lane l where id='{lane}';").stdout
    changes={'owner':{'owner':OTHER},'project':{'project':'foreign'},'conversation':{'conversation':'00000000-0000-4000-8000-000000000099'},
        'token':{'token':'00000000-0000-4000-8000-000000000099'},'superseded':{},'expired':{},'expired_deadline':{},'authenticated':{'role':'authenticated'}}[wrong]
    assert metadata_defer(sql,lane,claim,check=False,**changes).returncode!=0
    assert sql(f"select to_jsonb(l)::text from public.user_memoir_lane l where id='{lane}';").stdout==before


def test_pg_policy_release_preserves_work_even_when_original_page_is_stale(sql):
    identity,source,lane,claim=seeded_composer(sql);mark_inventory_pending(sql,identity)
    before=sql('select coalesce(jsonb_agg(to_jsonb(r)),\'[]\') from public.user_private_draft_outbox r;').stdout
    sql(f"update public.user_lifetime_conversation set preference_revision=preference_revision+1 where user_id='{OWNER}';")
    assert sql(f"set role service_role;select public.read_lifetime_memoir_lane_page('{lane}','{claim['token']}');",check=False).returncode!=0
    result=json.loads(metadata_defer(sql,lane,claim).stdout.strip())
    assert result=={'status':'pending','error':PolicyUnavailable.code,'retrieval_complete':False}
    assert sql(f"select attempts||':'||pending||':'||(token is null) from public.user_memoir_lane where id='{lane}';").stdout.strip()=='0:true:true'
    assert sql('select coalesce(jsonb_agg(to_jsonb(r)),\'[]\') from public.user_private_draft_outbox r;').stdout==before
    assert sql(f"select text from public.user_narrator_source where id='{source['id']}';").stdout.strip()==source['text']


def test_pg_claim_policy_rejection_rolls_back_attempt_and_mid_review_can_resume(sql):
    import psycopg
    from apps.api.lifetime_memory_lane_engine import LanePublication
    from apps.api.lifetime_memory_policy import is_policy_pending
    identity,source,lane,claim=seeded_composer(sql);project=identity['project_id'];phases=[];blocked=False
    service(sql,'yield_lifetime_memoir_lane',f"'{lane}','{claim['token']}'")
    command=sql.command;dsn=f"host={command[command.index('-h')+1]} port={command[command.index('-p')+1]} user=postgres dbname=postgres"
    class Broker:
        async def rpc(self,name,**payload):
            nonlocal blocked
            assert name!='fail_memoir_lane'
            args=','.join(f'{key}=>{literal(value)}' if not isinstance(value,int) else f'{key}=>{value}' for key,value in payload.items())
            try:
                with psycopg.connect(dsn) as conn:
                    conn.execute('set local role service_role')
                    result=conn.execute(f"select coalesce(to_jsonb(public.{name}({args})),'null'::jsonb)").fetchone()[0]
            except psycopg.Error as error:
                if is_policy_pending(error):raise PolicyUnavailable() from None
                raise
            if not blocked and name=='save_memoir_checkpoint' and payload['p_value'].get('draft'):
                blocked=True;mark_inventory_pending(sql,identity)
            return result
    def model(request):
        bounded=json.loads(request.content)['bounded_lane'];phase=bounded['phase'];packet=json.loads(bounded['packet'])['payload'];phases.append(phase)
        if phase=='prepare':result=dict(event_id=bounded['fence']['partition']['id'],context='Preserved grounded preparation',source_refs=bounded['fence']['partition']['source_refs'])
        elif phase=='draft':result=controlled_draft(packet,source['text'],'Childhood')
        else:result=dict(ready_for_user_review=True,publication_approved=False,findings=[])
        return httpx.Response(200,json={'reply':json.dumps(result)})
    worker=MemoryEventWorker(Broker(),worker_url='https://synthetic.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(model))
    worker.lane_publisher=LanePublication(dsn,authenticated_owner=OWNER)
    result=asyncio.run(worker.execute_lane(lane))
    assert result=={'status':'pending','error':PolicyUnavailable.code,'retrieval_complete':False}
    assert phases==['prepare','draft']
    saved=sql(f"select key||':'||value::text from public.user_memoir_checkpoint where lane_id='{lane}' order by key;").stdout
    assert saved.strip()
    sql(f"update public.user_memoir_lane set available_at=clock_timestamp()-interval '1 second' where id='{lane}';")
    before=sql(f"select to_jsonb(l)::text from public.user_memoir_lane l where id='{lane}';").stdout
    for _ in range(4):
        assert asyncio.run(worker.execute_lane(lane))['error']==PolicyUnavailable.code
        assert sql(f"select to_jsonb(l)::text from public.user_memoir_lane l where id='{lane}';").stdout==before
        assert sql(f"select key||':'||value::text from public.user_memoir_checkpoint where lane_id='{lane}' order by key;").stdout==saved
    # A synthetic reviewed inventory repair; production has no automatic bypass.
    sql(f"delete from public.user_lifetime_policy_inventory_pending where user_id='{OWNER}' and project_id={literal(project)};")
    result=asyncio.run(worker.execute_lane(lane))
    assert result['status']=='saved' and phases==['prepare','draft','review']
    assert sql(f"select text from public.user_narrator_source where id='{source['id']}';").stdout.strip()==source['text']
