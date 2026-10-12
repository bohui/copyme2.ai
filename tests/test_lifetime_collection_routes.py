"""Mapped collection HTTP compatibility without legacy all-history/SQLite calls."""
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from apps.api import collection_routes,lifetime_memory_collection_jobs
from apps.api.main import create_app
from apps.api.store import MemoryStore
from test_lifetime_memory_reads import FENCE


@pytest.fixture
def mapped(monkeypatch):
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','true')
    monkeypatch.delenv('MEMOIR_LIFETIME_GENERATION_PAUSED',raising=False)
    monkeypatch.delenv('MEMORY_SPARK_TASK_DB',raising=False)
    storage=Mock();storage.user_id=FENCE['identity']['owner_id'];storage.is_anonymous=False
    storage.story_entitlement.return_value={'status':'paid'}
    storage.acquire_agent_turn_lease.return_value=True;storage.renew_agent_turn_lease.return_value=True;storage.release_agent_turn_lease.return_value=True
    calls=[];job=str(uuid4());source=str(uuid4());state={'status':'QUEUED'}
    def rpc(name,**kwargs):
        calls.append((name,kwargs))
        if name=='read_lifetime_project_identity':return deepcopy(FENCE['identity'])
        if name=='capture_lifetime_read_fence':return deepcopy(FENCE)
        if name=='set_lifetime_collection':return {'revision':kwargs['p_expected_revision']+1,'periods':kwargs['p_periods'],'ready':kwargs['p_ready']}
        if name=='create_lifetime_collection_job':return {'id':job,'project_id':'read-project','kind':kwargs['p_kind'],'status':state['status'],'result':None}
        if name=='read_lifetime_collection_job_scope':return {'id':job,'project_id':'read-project'}
        if name=='read_lifetime_collection_job':return {'id':job,'project_id':'read-project','kind':'BuildSourceExport','status':'SUCCEEDED','root_digest':'a'*64,
            'complete':False,'next_cursor':str(uuid4()),'result':{'sources':[{'id':source,'content':'Selected original'}]}}
        raise AssertionError(name)
    storage.lifetime_rpc=rpc
    def forbidden(*args,**kwargs):pytest.fail('canonical selected job crossed into legacy all-history state')
    storage.memories=storage.all_memories=forbidden
    monkeypatch.setattr(collection_routes,'authenticated_storage',lambda _:storage)
    monkeypatch.setattr(collection_routes,'_queue',forbidden)
    @asynccontextmanager
    async def guard(fence):
        calls.append(('actual_send',{'root':publisher.root_digest}));yield
    publisher=SimpleNamespace(root_digest=None,guard=guard)
    monkeypatch.setattr(lifetime_memory_collection_jobs,'CollectionResultPublication',lambda *args,**kwargs:publisher)
    return TestClient(create_app(MemoryStore())),calls,storage,source,job


def test_mapped_preview_and_export_admit_only_selected_ids_without_publisher_or_legacy_queue(mapped):
    client,calls,_,source,_=mapped
    for kind in ['BuildFreePreview','BuildSourceExport']:
        response=client.post('/v1/agent/collection/read-project/tasks',json={'kind':kind,'memory_ids':[source],'title':'Chosen title'})
        assert response.status_code==202,response.text
        sent=next(kwargs for name,kwargs in reversed(calls) if name=='create_lifetime_collection_job')
        assert sent['p_source_ids']==[source] and sent['p_title']=='Chosen title'
        assert 'sources' not in sent and sent['p_paused'] is False


def test_mapped_confirmation_and_paid_organisation_keep_exact_expected_revision(mapped):
    client,calls,storage,source,_=mapped
    periods={name:{'status':'skipped','note':'Skip'} for name in collection_routes.LIFE_STAGES}
    periods['childhood']={'status':'recorded','memory_ids':[source]}
    response=client.put('/v1/agent/collection/read-project',json={'expected_revision':4,'periods':periods,'confirm_ready':True})
    assert response.status_code==200 and response.json()['revision']==5
    response=client.post('/v1/agent/collection/read-project/organise',json={'expected_revision':5,'language':'zh-CN'})
    assert response.status_code==202,response.text
    sent=next(kwargs for name,kwargs in reversed(calls) if name=='create_lifetime_collection_job')
    assert sent['p_expected_revision']==5 and sent['p_locale']=='zh-CN' and sent['p_source_ids']==[]
    storage.story_entitlement.return_value={'status':'revoked'}
    calls.clear()
    assert client.post('/v1/agent/collection/read-project/organise',json={'expected_revision':5}).status_code==402
    assert not any(name=='create_lifetime_collection_job' for name,_ in calls)


def test_mapped_task_pages_capture_before_data_and_guard_exact_result_root(mapped):
    client,calls,_,_,job=mapped
    response=client.get(f'/v1/agent/tasks/{job}?limit=1')
    assert response.status_code==200,response.text
    names=[name for name,_ in calls]
    assert names.index('capture_lifetime_read_fence')<names.index('read_lifetime_collection_job')<names.index('actual_send')
    assert response.headers['cache-control']=='no-store'
    assert response.json()['complete'] is False
    assert calls[-1]==('actual_send',{'root':'a'*64})
    assert client.get(f'/v1/agent/tasks/{job}?limit=9').status_code==422


def test_generation_pause_is_bound_to_new_organiser_admission_but_exports_remain_available(mapped,monkeypatch):
    client,calls,_,source,_=mapped;monkeypatch.setenv('MEMOIR_LIFETIME_GENERATION_PAUSED','true')
    assert client.post('/v1/agent/collection/read-project/tasks',json={'kind':'BuildSourceExport','memory_ids':[source]}).status_code==202
    assert next(kwargs for name,kwargs in reversed(calls) if name=='create_lifetime_collection_job')['p_paused'] is False
    assert client.post('/v1/agent/collection/read-project/organise',json={'expected_revision':1}).status_code==202
    assert next(kwargs for name,kwargs in reversed(calls) if name=='create_lifetime_collection_job')['p_paused'] is True


def test_rollback_flag_false_keeps_mapped_selected_jobs_and_result_fences(mapped,monkeypatch):
    client,calls,_,source,job=mapped;monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','false')
    assert client.post('/v1/agent/collection/read-project/tasks',json={'kind':'BuildSourceExport','memory_ids':[source]}).status_code==202
    assert next(kwargs for name,kwargs in reversed(calls) if name=='create_lifetime_collection_job')['p_paused'] is False
    calls.clear()
    result=client.get(f'/v1/agent/tasks/{job}')
    assert result.status_code==200 and result.headers['cache-control']=='no-store'
    assert calls[-1][0]=='actual_send'


def test_collection_get_forwards_independent_task_and_source_cursors(mapped,monkeypatch):
    client,_,storage,_,_=mapped
    task_cursor=str(uuid4());source_cursor=str(uuid4());seen=[]
    monkeypatch.setattr(collection_routes,'read_mapped',lambda storage,project,read,legacy:read(None))
    def canonical(storage,project,**kwargs):
        seen.append(kwargs);return {'sources':[],'tasks':[],'tasks_complete':False,'tasks_next_cursor':task_cursor}
    monkeypatch.setattr(collection_routes,'canonical_collection',canonical)
    response=client.get(f'/v1/agent/collection/read-project?cursor={source_cursor}&task_cursor={task_cursor}&limit=2')
    assert response.status_code==200
    assert str(seen[0]['task_cursor'])==task_cursor and str(seen[0]['cursor'])==source_cursor
    assert seen[0]['limit']==2
