"""Canonical Temporal activities carry opaque IDs and close their clients."""
import asyncio
from pathlib import Path
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip('temporalio')
from temporalio.exceptions import ApplicationError

from scripts import task_runtime


@pytest.mark.parametrize('dispatch_available', [False, True])
def test_readiness_requires_background_dispatch_and_closes_broker(monkeypatch, dispatch_available):
    from apps.api import memory_event_worker
    monkeypatch.setattr(task_runtime, 'configured_queue', lambda: None)
    client = SimpleNamespace(service_client=SimpleNamespace(check_health=AsyncMock(return_value=True)))
    monkeypatch.setattr(task_runtime.Client, 'connect', AsyncMock(return_value=client))
    broker = SimpleNamespace(client=SimpleNamespace(aclose=AsyncMock()), rpc=AsyncMock(
        return_value=[], side_effect=None if dispatch_available else RuntimeError('Background schema unavailable')))
    monkeypatch.setattr(memory_event_worker, 'MemoirLaneBroker', lambda: broker)

    if dispatch_available:
        asyncio.run(task_runtime.readiness('temporal:7233', 'default', 'memoir-tasks'))
    else:
        with pytest.raises(RuntimeError, match='Background schema unavailable'):
            asyncio.run(task_runtime.readiness('temporal:7233', 'default', 'memoir-tasks'))
    broker.rpc.assert_awaited_once_with('pending_memoir_background_agents', p_limit=1)
    broker.client.aclose.assert_awaited_once()


def test_api_and_worker_keep_sqlite_caches_on_separate_vm_volumes():
    compose = (Path(__file__).resolve().parents[1] / 'compose.yml').read_text()
    volumes = []
    for service in ('api', 'worker'):
        section = re.search(rf'(?ms)^  {service}:\n(.*?)(?=^  \S|\Z)', compose)[1]
        path = re.search(r'MEMORY_SPARK_TASK_DB: (\S+)', section)[1]
        mount = re.search(rf'(?m)^      - ([\w-]+):{re.escape(str(Path(path).parent))}$', section)[1]
        volumes.append(mount)
    assert volumes[0] != volumes[1], 'SQLite WAL must not be shared between Linux VMs'


def test_lane_activity_heartbeats_without_content_and_stops_after_completion(monkeypatch):
    from apps.api import memory_event_worker
    calls=[]
    monkeypatch.setattr(task_runtime,'LANE_HEARTBEAT_SECONDS',0.01,raising=False)
    monkeypatch.setattr(task_runtime.activity,'in_activity',lambda:True)
    monkeypatch.setattr(task_runtime.activity,'heartbeat',lambda *args:calls.append(args))
    broker=SimpleNamespace(client=SimpleNamespace(aclose=AsyncMock()),rpc=AsyncMock(return_value={'pending':False}))
    async def execute(_):
        while len(calls)<2:await asyncio.sleep(0.001)
        return {'status':'saved'}
    monkeypatch.setattr(memory_event_worker,'MemoirLaneBroker',lambda:broker)
    monkeypatch.setattr(memory_event_worker,'MemoryEventWorker',lambda _:SimpleNamespace(execute_lane=execute))
    async def scenario():
        assert await asyncio.wait_for(task_runtime.execute_memoir_lane('opaque-lane'),0.5)=={'status':'saved','pending':False}
        count=len(calls);await asyncio.sleep(0.03)
        assert len(calls)==count
    asyncio.run(scenario())
    assert len(calls)>=2 and all(args==() for args in calls)
    broker.client.aclose.assert_awaited_once()


def test_lane_workflow_bounds_recovery_from_worker_loss(monkeypatch):
    from datetime import timedelta
    from temporalio import workflow
    from apps.api.temporal_workflows import MemoirSkillLane
    execute=AsyncMock(return_value={'status':'finished','pending':False})
    monkeypatch.setattr(workflow,'execute_activity',execute)
    assert asyncio.run(MemoirSkillLane().run('opaque-lane'))=={'status':'finished'}
    assert execute.await_args.kwargs['heartbeat_timeout']==timedelta(seconds=60)


@pytest.mark.parametrize('fails',[False,True])
def test_lane_activity_closes_broker_after_success_or_failure(monkeypatch,fails):
    from apps.api import memory_event_worker
    broker=SimpleNamespace(client=SimpleNamespace(aclose=AsyncMock()),
        rpc=AsyncMock(return_value={'pending':False}))
    execute=AsyncMock(return_value={'status':'saved'},
        side_effect=RuntimeError('private diagnostic') if fails else None)
    monkeypatch.setattr(memory_event_worker,'MemoirLaneBroker',lambda:broker)
    monkeypatch.setattr(memory_event_worker,'MemoryEventWorker',
        lambda received:SimpleNamespace(execute_lane=execute))
    if fails:
        with pytest.raises(RuntimeError):asyncio.run(task_runtime.execute_memoir_lane('opaque-lane'))
    else:
        assert asyncio.run(task_runtime.execute_memoir_lane('opaque-lane'))=={'status':'saved','pending':False}
        broker.rpc.assert_awaited_once_with('read_memoir_lane_state',p_lane_id='opaque-lane')
    execute.assert_awaited_once_with('opaque-lane')
    broker.client.aclose.assert_awaited_once()


@pytest.mark.parametrize('fails',[False,True])
def test_collection_activity_is_bounded_and_sanitizes_failure(monkeypatch,fails):
    from apps.api import memory_event_worker,lifetime_memory_collection_jobs
    broker=SimpleNamespace(client=SimpleNamespace(aclose=AsyncMock()))
    execute=AsyncMock(return_value={'status':'yielded','processed':1},
        side_effect=RuntimeError('private original testimony') if fails else None)
    monkeypatch.setattr(memory_event_worker,'MemoirLaneBroker',lambda:broker)
    monkeypatch.setattr(lifetime_memory_collection_jobs,'CollectionJobWorker',
        lambda received:SimpleNamespace(execute=execute))
    if fails:
        with pytest.raises(ApplicationError) as error:
            asyncio.run(task_runtime.execute_collection_job('opaque-job'))
        assert error.value.type=='CollectionJobRetry'
        assert 'private' not in str(error.value) and not error.value.non_retryable
    else:
        assert asyncio.run(task_runtime.execute_collection_job('opaque-job'))=={'status':'yielded','processed':1}
    execute.assert_awaited_once_with('opaque-job',page_limit=1)
    broker.client.aclose.assert_awaited_once()
