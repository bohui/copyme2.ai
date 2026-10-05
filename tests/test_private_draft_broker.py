"""Outbox recovery and current-authorization checks without real credentials."""
import asyncio
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from apps.api.main import create_app
from apps.api.private_draft_broker import PrivateDraftBroker
from apps.api.private_draft_jobs import PrivateDraftJobs
from test_private_drafts import snapshot


def packet():
    rounds,sources=snapshot(5)
    memories=[{'id':s['id'],'kind':'agent','project_id':'project','content':'Storyteller: Fixture memory\nMemory Spark: Fixture reply'} for s in sources]
    return {'event_id':'receipt','user_id':'owner','project_id':'project','rounds':rounds,'memories':memories,'completed':5,'locale':'en-AU'}


def test_outbox_replay_acknowledges_only_after_durable_job(tmp_path,monkeypatch):
    path=tmp_path/'jobs.sqlite';monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(path))
    monkeypatch.setenv('SUPABASE_URL','https://fixture.test');monkeypatch.setenv('SUPABASE_SECRET_KEY','fixture-only')
    calls=[]
    def handle(request):
        calls.append(request.method)
        if request.method=='GET':return httpx.Response(200,json=[{'id':'receipt'}])
        if request.method=='POST':return httpx.Response(200,json=packet())
        assert len(PrivateDraftJobs(path).pending_ids())==1
        return httpx.Response(204)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            broker=PrivateDraftBroker(client=client)
            await broker.drain_once();await broker.drain_once()
    asyncio.run(run())
    assert calls==['GET','POST','PATCH']*2
    assert len(PrivateDraftJobs(path).pending_ids())==1
    assert 'fixture-only' not in path.read_bytes().decode('latin1')


@pytest.mark.parametrize('change',['revoked','edited'])
def test_internal_validation_refuses_revoked_or_changed_source(tmp_path,monkeypatch,change):
    path=tmp_path/'jobs.sqlite';monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(path))
    monkeypatch.setenv('MEMORY_SPARK_CODEX_WORKER_SECRET','fixture-only')
    current=packet();PrivateDraftBroker.reconcile(current)
    queue=PrivateDraftJobs(path);job_id=queue.pending_ids()[0];queue.claim(job_id)
    class Broker:
        client=httpx.AsyncClient()
        async def snapshot(self,event):
            assert event=='receipt'
            if change=='revoked':return None
            current['memories'][0]['content']='Storyteller: Fixture correction\nMemory Spark: Reply'
            return current
        reconcile=staticmethod(PrivateDraftBroker.reconcile)
    monkeypatch.setattr('apps.api.private_draft_broker.PrivateDraftBroker',Broker)
    client=TestClient(create_app())
    url='/internal/private-drafts/validate/'+job_id
    assert client.post(url).status_code==401
    response=client.post(url,headers={'X-Codex-Worker-Secret':'fixture-only'})
    assert response.status_code==409 and queue.status(job_id)=='STALE'
    with queue._connect() as db:
        row=db.execute('select payload,checkpoint from private_draft_jobs where id=?',(job_id,)).fetchone()
        assert row['payload']=='{}' and row['checkpoint']=='{}'
