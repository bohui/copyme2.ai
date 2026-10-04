"""Real Temporal/PostgreSQL/private-worker integration; provider is controlled."""
import asyncio
import json
import sys
from pathlib import Path

import httpx
from fastapi import FastAPI
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from test_shared_memory_events_postgres import (
    database, attachment_database, private_database, event_database, sql,
    rpc, OWNER, TURN, ROOT,
)
from memoir_postgres_workflow import PostgresRest


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
        options = {'download_dest_dir': '/tmp/memoir-issue6-temporal',
                   'dev_server_database_filename': str(tmp_path / 'temporal.sqlite'), 'ip': '127.0.0.1', 'ui': False}
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
