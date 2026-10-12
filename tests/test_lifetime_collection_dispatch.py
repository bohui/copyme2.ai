"""Collection scheduling never blocks the shared poller on model generation."""
import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest


def test_dispatch_schedules_opaque_ids_without_waiting_for_provider(monkeypatch):
    from scripts import task_runtime
    from apps.api import lifetime_memory_collection_jobs
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','true')
    monkeypatch.setattr(lifetime_memory_collection_jobs,'CollectionJobWorker',lambda *args,**kwargs: (_ for _ in ()).throw(AssertionError('poller executed model work')))
    jobs=[str(uuid4()),str(uuid4())]
    class Broker:
        async def rpc(self,name,**kwargs):
            assert name=='pending_lifetime_collection_jobs' and kwargs['p_limit']==4
            return jobs
    client=type('Client',(),{'start_workflow':AsyncMock(side_effect=['a','b'])})()
    assert asyncio.run(task_runtime.dispatch_collection_jobs_once(client,Broker(),'memoir-tasks'))==['a','b']
    for call,job in zip(client.start_workflow.call_args_list,jobs):
        assert call.args[1]==job and call.kwargs['id']=='memoir-collection:'+job
        assert set(call.kwargs)=={'id','task_queue','id_reuse_policy','id_conflict_policy'}


def test_collection_workflow_continues_pages_and_returns_only_safe_status(monkeypatch):
    from apps.api.lifetime_memory_collection_workflow import MemoirCollectionJob
    from temporalio import workflow
    execute=AsyncMock(side_effect=[{'status':'pending','processed':1},{'status':'succeeded','processed':1}])
    monkeypatch.setattr(workflow,'execute_activity',execute)
    assert asyncio.run(MemoirCollectionJob().run('opaque-job'))=={'status':'succeeded'}
    assert execute.await_count==2
    assert all(call.args==('memoir.execute_collection_job','opaque-job') for call in execute.call_args_list)


def test_collection_workflow_defers_without_activity_retry_then_resumes(monkeypatch):
    from apps.api.lifetime_memory_collection_workflow import MemoirCollectionJob
    from apps.api import lifetime_memory_collection_jobs, memory_event_worker
    from scripts.task_runtime import execute_collection_job
    from temporalio import workflow

    close = AsyncMock()
    broker = type('Broker', (), {'client': type('Client', (), {'aclose': close})()})()
    execute = AsyncMock(side_effect=[
        {'status': 'deferred', 'processed': 0},
        {'status': 'succeeded', 'processed': 1},
    ])
    worker = type('Worker', (), {'execute': execute})()
    monkeypatch.setattr(memory_event_worker, 'MemoirLaneBroker', lambda: broker)
    monkeypatch.setattr(lifetime_memory_collection_jobs, 'CollectionJobWorker', lambda value: worker)

    async def activity_adapter(name, job_id, **options):
        assert name == 'memoir.execute_collection_job'
        return await execute_collection_job(job_id)

    activity = AsyncMock(side_effect=activity_adapter)
    monkeypatch.setattr(workflow, 'execute_activity', activity)
    assert asyncio.run(MemoirCollectionJob().run('opaque-job')) == {'status': 'deferred'}
    assert activity.await_count == 1
    # The ordinary poller can start this completed opaque workflow again after
    # readiness changes; no failed activity or private exception enters history.
    assert asyncio.run(MemoirCollectionJob().run('opaque-job')) == {'status': 'succeeded'}
    assert activity.await_count == 2 and close.await_count == 2
    assert all(call.args == ('opaque-job',) and call.kwargs == {'page_limit': 1}
               for call in execute.call_args_list)


@pytest.mark.parametrize('initial_outcome', ['retry', 'deferred'])
def test_real_temporal_collection_retries_without_private_payload_or_blocking_poller(tmp_path,monkeypatch,initial_outcome):
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker
    from temporal_test_server import local_options
    from apps.api import lifetime_memory_collection_jobs,memory_event_worker
    from apps.api.lifetime_memory_collection_workflow import MemoirCollectionJob
    from scripts.task_runtime import dispatch_collection_jobs_once,execute_collection_job
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','true')
    job=str(uuid4());secret='Private selected source and generated title never enter orchestration history.'
    class Broker:
        def __init__(self):self.client=type('Client',(),{'aclose':AsyncMock()})()
        async def rpc(self,name,**kwargs):return [job]
    async def scenario():
        entered=asyncio.Event();release=asyncio.Event();attempts=[]
        class ControlledWorker:
            def __init__(self,broker):pass
            async def execute(self,job_id,*,page_limit):
                assert job_id==job and page_limit==1
                attempts.append(job_id)
                if len(attempts)==1:
                    entered.set();await release.wait()
                    if initial_outcome == 'deferred':
                        return {'status': 'deferred', 'processed': 0}
                    raise RuntimeError(secret)
                return {'status':'pending' if len(attempts)==2 else 'succeeded','processed':1}
        monkeypatch.setattr(memory_event_worker,'MemoirLaneBroker',Broker)
        monkeypatch.setattr(lifetime_memory_collection_jobs,'CollectionJobWorker',ControlledWorker)
        async with await WorkflowEnvironment.start_local(**local_options(tmp_path/'temporal.sqlite')) as env:
            async with Worker(env.client,task_queue='collection-test',workflows=[MemoirCollectionJob],activities=[execute_collection_job],max_concurrent_activities=4):
                handles=await asyncio.wait_for(dispatch_collection_jobs_once(env.client,Broker(),'collection-test'),5)
                await asyncio.wait_for(entered.wait(),5)
                duplicate=await asyncio.wait_for(dispatch_collection_jobs_once(env.client,Broker(),'collection-test'),5)
                assert handles[0].id==duplicate[0].id and len(attempts)==1
                release.set()
                if initial_outcome == 'deferred':
                    assert await asyncio.wait_for(handles[0].result(), 5) == {'status': 'deferred'}
                    assert len(attempts) == 1
                    history = await handles[0].fetch_history()
                    from temporalio.api.enums.v1 import EventType
                    assert not any(event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_FAILED
                                   for event in history.events)
                    assert secret.encode() not in b''.join(event.SerializeToString() for event in history.events)
                    # Readiness allows the poller to restart the same completed
                    # opaque workflow, rather than consuming activity retries.
                    handles = await asyncio.wait_for(dispatch_collection_jobs_once(env.client, Broker(), 'collection-test'), 5)
                assert await asyncio.wait_for(handles[0].result(),15)=={'status':'succeeded'}
                assert len(attempts)==3
                history=await handles[0].fetch_history()
                serialized=b''.join(event.SerializeToString() for event in history.events)
                assert secret.encode() not in serialized and job.encode() in serialized
    asyncio.run(scenario())
