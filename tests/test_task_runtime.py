"""Canonical Temporal activities carry opaque IDs and close their clients."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip('temporalio')
from temporalio.exceptions import ApplicationError

from scripts import task_runtime


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
