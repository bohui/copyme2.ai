"""Real Temporal/PostgreSQL/private-worker integration; provider is controlled."""
import asyncio
import json
import sys
from pathlib import Path

import httpx
from fastapi import FastAPI
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporal_test_server import local_options
from temporalio.worker import Worker

from test_shared_memory_events_postgres import (
    database, attachment_database, private_database, event_database, sql,
    rpc, OWNER, TURN, ROOT,
)
from memoir_postgres_workflow import PostgresRest
import pytest




def test_real_temporal_dispatch_commits_evidence_without_story_text_in_history(sql, tmp_path, monkeypatch):
    from apps.api.codex_worker_service import CodexWorker, WorkerTurnInput
    from apps.api.memory_event_worker import MemoirLaneBroker, MemoryEventWorker
    from apps.api.temporal_workflows import MemoirSkillLane
    from scripts.task_runtime import dispatch_memoir_lanes_once
    secret = 'Private synthetic memory retained outside workflow history.'
    rpc(sql, 'accept_user_narrator_source', f"'project', '{TURN}', '{secret}'")
    control = tmp_path / 'provider.json'
    control.write_text(json.dumps({'reply': {'events': []}}))
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP', '1')
    provider_worker = CodexWorker(home_root=tmp_path / 'worker-homes',
        command=[sys.executable, str(ROOT / 'tests/fixtures/issue6_controlled_app_server.py'), str(control)])
    app = FastAPI()
    @app.post('/internal/codex/turn')
    async def worker_turn(payload: WorkerTurnInput):
        return await provider_worker.turn(payload)
    async def scenario():
        options = local_options(tmp_path / 'temporal.sqlite')
        async with await WorkflowEnvironment.start_local(**options) as env:
            transport = httpx.MockTransport(PostgresRest(sql, OWNER, service=True).handle)
            async with httpx.AsyncClient(transport=transport) as client:
                broker = MemoirLaneBroker(url='http://synthetic.invalid', key='synthetic-service', client=client)
                event_worker = MemoryEventWorker(broker, worker_url='http://controlled-worker.invalid',
                    worker_secret='synthetic-worker-secret', worker_transport=httpx.ASGITransport(app=app))
                @activity.defn(name='memoir.execute_lane')
                async def execute_lane(lane_id: str):
                    result = await event_worker.execute_lane(lane_id)
                    return {'status': result['status']}
                async with Worker(env.client, task_queue='issue6-synthetic', workflows=[MemoirSkillLane], activities=[execute_lane]):
                    handles = await dispatch_memoir_lanes_once(env.client, broker, 'issue6-synthetic')
                    assert len(handles) == 1
                    await asyncio.wait_for(handles[0].result(), 20)
                    assert rpc(sql, 'read_user_memory_events', "'project'")['processing']['extracted_through'] == 1
                    history = await handles[0].fetch_history()
                    assert secret.encode() not in b''.join(event.SerializeToString() for event in history.events)
    asyncio.run(scenario())




def test_configured_deadline_stops_hung_provider_and_exposes_bounded_retry(sql,tmp_path,monkeypatch):
    from test_shared_memory_events_postgres import story_client
    from apps.api.codex_worker_service import CodexWorker,WorkerTurnInput
    from apps.api.memory_event_worker import MemoirLaneBroker,MemoryEventWorker
    from apps.api.temporal_workflows import MemoirSkillLane
    from scripts.task_runtime import dispatch_memoir_lanes_once
    rpc(sql,'accept_user_narrator_source',f"'project','{TURN}','An original retained through timeout.'")
    gate=tmp_path/'hold'
    gate.touch()
    control=tmp_path/'provider.json'
    control.write_text(json.dumps({'mode':'timeline','reply':{'events':[]},'calls':str(tmp_path/'calls.jsonl'),'hold_phase':'timeline','gate':str(gate)}))
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP','1')
    monkeypatch.setenv('MEMORY_SPARK_MEMOIR_RUN_SECONDS','1')
    provider=CodexWorker(home_root=tmp_path/'worker',command=[sys.executable,str(ROOT/'tests/fixtures/issue6_controlled_app_server.py'),str(control)])
    app=FastAPI()
    @app.post('/internal/codex/turn')
    async def turn(payload:WorkerTurnInput): return await provider.turn(payload)
    async def scenario():
        options=local_options(tmp_path/'temporal.sqlite')
        async with await WorkflowEnvironment.start_local(**options) as env:
            async with httpx.AsyncClient(transport=httpx.MockTransport(PostgresRest(sql,OWNER,service=True).handle)) as client:
                broker=MemoirLaneBroker(url='http://synthetic.invalid',key='synthetic',client=client)
                worker=MemoryEventWorker(broker,worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=httpx.ASGITransport(app=app))
                @activity.defn(name='memoir.execute_lane')
                async def execute(lane_id:str):
                    result=await worker.execute_lane(lane_id)
                    state=await broker.rpc('read_memoir_lane_state',p_lane_id=lane_id)
                    return {'status':result['status'],'pending':state['pending']}
                async with Worker(env.client,task_queue='issue6-deadline',workflows=[MemoirSkillLane],activities=[execute]):
                    handle=(await dispatch_memoir_lanes_once(env.client,broker,'issue6-deadline'))[0]
                    assert (await asyncio.wait_for(handle.result(),30))['status']=='retry_required'
                    view=rpc(sql,'read_user_memory_events',"'project'")
                    assert view['sources'][0]['text']=='An original retained through timeout.'
                    assert view['processing']['extracted_through']==0 and view['completed_rounds']==0
                    saved=story_client(sql).get('/v1/story/private-draft?project_id=project',headers={'Authorization':'Bearer synthetic-author'}).json()
                    assert saved['progress']['extraction']['state']=='retry_required' and saved['error']
                    assert not saved['updating']
                    retry=story_client(sql).post('/v1/story/private-draft/retry',headers={'Authorization':'Bearer synthetic-author'},json={'project_id':'project'}).json()
                    assert retry['progress']['extraction']['state']=='pending'
    asyncio.run(scenario())
