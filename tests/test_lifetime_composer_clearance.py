"""Operator clearance defers bounded work without consuming generation attempts."""
import asyncio
import copy
import json
from contextlib import asynccontextmanager

import httpx
import pytest

from apps.api.lifetime_memory_activation import CanonicalActivationUnavailable
from apps.api.memory_event_worker import MemoryEventWorker
from test_lifetime_composer_capacity import page, Publisher
from test_canonical_composer_provenance import controlled_draft


@pytest.fixture(autouse=True)
def synthetic_generation(monkeypatch):
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','true')


def composer_page():
    current=page('composer');source=current['source']
    current['partition']=dict(id='event-clearance',revision=1,kind='event',life_stage='unplaced',status='active',title='Childhood',
        source_refs=[dict(source_id=source['id'],version=source['version'],quote=source['text'],char_start=source['char_start'],char_end=source['char_end'])])
    return current


@pytest.mark.parametrize('blocked_phase',['extract','prepare','draft','review'])
def test_remote_clearance_preserves_bounded_work_and_completed_phases(blocked_phase):
    current=page() if blocked_phase=='extract' else composer_page()
    original=copy.deepcopy(current['source']);checkpoints={};completed=[];blocked=True;failures=[];committed=False
    class Broker:
        async def rpc(self,name,**payload):
            nonlocal committed
            if name=='claim_memoir_lane':return current
            if name=='read_memoir_checkpoint':return copy.deepcopy(checkpoints.get(payload['p_key']))
            if name=='save_memoir_checkpoint':checkpoints[payload['p_key']]=copy.deepcopy(payload['p_value']);return True
            if name=='record_lifetime_lane_output':return True
            if name=='read_lifetime_lane_policy_source':return copy.deepcopy(original)
            if name=='defer_lifetime_memoir_lane':
                assert payload['p_reason']==CanonicalActivationUnavailable.code
                return {'status':'pending','error':payload['p_reason'],'retrieval_complete':False}
            if name=='fail_memoir_lane':failures.append(payload);return {'status':'retry_required'}
            if name=='commit_lifetime_memoir_lane_page':committed=True;return {'status':'page_saved'}
            if name=='read_lifetime_memoir_lane_page':return {**current,'complete':True,'source':None,'partition':None}
            if name=='complete_lifetime_memoir_lane':return {'status':'saved','retrieval_complete':True}
            raise AssertionError(name)
    def model(request):
        bounded=json.loads(request.content)['bounded_lane'];phase=bounded['phase'];payload=json.loads(bounded['packet'])['payload']
        if blocked and phase==blocked_phase:
            return httpx.Response(503,json={'detail':'Canonical generation deferred'},headers={'X-Error-Code':CanonicalActivationUnavailable.code})
        completed.append(phase)
        if phase=='extract':result={'events':[]}
        elif phase=='prepare':result=dict(event_id=current['partition']['id'],context='Prepared before clearance changed',source_refs=current['partition']['source_refs'])
        elif phase=='draft':result=controlled_draft(payload,original['text'],'Childhood')
        else:result=dict(ready_for_user_review=True,publication_approved=False,findings=[])
        return httpx.Response(200,json={'reply':json.dumps(result)})
    worker=MemoryEventWorker(Broker(),worker_url='https://synthetic.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(model))
    worker.lane_publisher=Publisher()
    result=asyncio.run(worker.execute_lane(current['lane_id']))
    assert result=={'status':'pending','error':CanonicalActivationUnavailable.code,'retrieval_complete':False}
    assert not failures and not committed and current['source']==original
    saved=copy.deepcopy(checkpoints);before=list(completed)
    blocked=False
    current={**current,'token':'00000000-0000-4000-8000-000000000017','page_digest':'4'*64}
    result=asyncio.run(worker.execute_lane(current['lane_id']))
    assert result['status']=='saved' and not failures
    assert completed==(['extract'] if blocked_phase=='extract' else ['prepare','draft','review'])
    assert completed[:len(before)]==before
    assert all(key in checkpoints for key in saved)


from test_lifetime_composer_capacity import (
    sql, event_database, private_database, attachment_database, database,  # noqa: F401 - pytest fixtures
    resolve, rpc, literal, service, create_lane, seeded_composer, OWNER,
)


@pytest.mark.parametrize('skill',['timeline','composer'])
def test_pg_provider_authority_wait_preserves_lane_and_source_checkpoints(sql,skill):
    if skill=='composer':
        identity,source,lane,claim=seeded_composer(sql)
        service(sql,'yield_lifetime_memoir_lane',f"'{lane}','{claim['token']}'")
    else:
        identity=resolve(sql);project=identity['project_id']
        source=rpc(sql,'accept_user_narrator_source',f"{literal(project)},'00000000-0000-4000-8000-000000000001','I grew up in Chengde.'")
        lane=create_lane(sql,identity)
    project=identity['project_id'];blocked=skill=='timeline';phases=[]
    originals=sql(f"select text||':'||version::text||':'||status from public.user_narrator_source where id='{source['id']}';").stdout
    obligations=sql(f"select id::text||':'||delivered::text from public.user_private_draft_outbox where user_id='{OWNER}' and project_id={literal(project)} order by id;").stdout
    assert obligations.strip()
    class Broker:
        async def rpc(self,name,**payload):
            nonlocal blocked
            assert name!='fail_memoir_lane', 'Operator clearance must not consume generation failure attempts'
            args=','.join(f'{key}=>{literal(value)}' if not isinstance(value,int) else f'{key}=>{value}' for key,value in payload.items())
            result=json.loads(sql(f"set role service_role;select coalesce(to_jsonb(public.{name}({args})),'null'::jsonb);").stdout.strip())
            if skill=='composer' and not blocked and name=='save_memoir_checkpoint' and payload['p_value'].get('draft'):
                # Actual prepare/draft are durably stored before the review gate closes.
                blocked=True
            return result
    def model(request):
        bounded=json.loads(request.content)['bounded_lane'];phase=bounded['phase'];payload=json.loads(bounded['packet'])['payload'];phases.append(phase)
        if phase=='extract':result={'events':[]}
        elif phase=='prepare':result=dict(event_id=bounded['fence']['partition']['id'],context='Persisted grounded preparation',source_refs=bounded['fence']['partition']['source_refs'])
        elif phase=='draft':result=controlled_draft(payload,source['text'],'Childhood')
        else:result=dict(ready_for_user_review=True,publication_approved=False,findings=[])
        return httpx.Response(200,json={'reply':json.dumps(result)})
    worker=MemoryEventWorker(Broker(),worker_url='https://synthetic.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(model))
    class Authority:
        @asynccontextmanager
        async def guard(self,fence):
            if blocked:raise CanonicalActivationUnavailable()
            yield
    worker.lane_publisher=Authority()
    try:
        saved_checkpoints=None
        for _ in range(4):
            sql(f"update public.user_memoir_lane set available_at=clock_timestamp()-interval '1 second' where id='{lane}';")
            result=asyncio.run(worker.execute_lane(lane))
            assert result=={'status':'pending','error':CanonicalActivationUnavailable.code,'retrieval_complete':False}
            state=json.loads(sql(f"select json_build_object('attempts',attempts,'pending',pending,'token',token,'error',error) from public.user_memoir_lane where id='{lane}';").stdout.strip())
            assert state=={'attempts':0,'pending':True,'token':None,'error':CanonicalActivationUnavailable.code}
            checkpoints=sql(f"select key||':'||value::text from public.user_memoir_checkpoint where lane_id='{lane}' order by key;").stdout
            if saved_checkpoints is None:saved_checkpoints=checkpoints
            assert checkpoints==saved_checkpoints
            assert sql(f"select text||':'||version::text||':'||status from public.user_narrator_source where id='{source['id']}';").stdout==originals
            assert sql(f"select id::text||':'||delivered::text from public.user_private_draft_outbox where user_id='{OWNER}' and project_id={literal(project)} order by id;").stdout==obligations
        assert phases==([] if skill=='timeline' else ['prepare','draft'])
        if skill=='composer':assert saved_checkpoints.strip()
        blocked=False
        sql(f"update public.user_memoir_lane set available_at=clock_timestamp()-interval '1 second' where id='{lane}';")
        result=asyncio.run(worker.execute_lane(lane))
        assert result['status']=='saved' and result['retrieval_complete']
        assert phases==(['extract'] if skill=='timeline' else ['prepare','draft','review'])
        assert sql(f"select processing_status from public.user_narrator_source where id='{source['id']}';").stdout.strip()=='succeeded'
    finally:
        blocked=False
