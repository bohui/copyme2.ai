"""Canonical memoir lanes and selected collection work through Temporal."""
import asyncio
import logging

from temporalio import activity
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy, WorkflowIDConflictPolicy
from temporalio.exceptions import ApplicationError
from temporalio.worker import Worker

from apps.api.task_queue import configured_queue
from apps.api.temporal_workflows import MemoirSkillLane, MemoirBackgroundAgent
from apps.api.lifetime_memory_collection_workflow import MemoirCollectionJob

log = logging.getLogger(__name__)
LANE_HEARTBEAT_SECONDS = 15


async def _heartbeat_lane_activity():
    while True:
        activity.heartbeat()
        await asyncio.sleep(LANE_HEARTBEAT_SECONDS)


@activity.defn(name='memoir.execute_lane')
async def execute_memoir_lane(lane_id: str) -> dict:
    from apps.api.memory_event_worker import MemoryEventWorker, MemoirLaneBroker
    broker = MemoirLaneBroker()
    heartbeat = asyncio.create_task(_heartbeat_lane_activity()) if activity.in_activity() else None
    try:
        result = await MemoryEventWorker(broker).execute_lane(lane_id)
        state = await broker.rpc('read_memoir_lane_state', p_lane_id=lane_id)
        return {'status': result['status'], 'pending': bool(state and state['pending'])}
    finally:
        if heartbeat:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
        await broker.client.aclose()


async def dispatch_memoir_lanes_once(client, broker, task_queue, *, single_attempt=False):
    if type(single_attempt) is not bool or (single_attempt and not task_queue.startswith('canary-')):
        raise ValueError('Single-attempt execution requires a task-owned canary queue')
    await broker.drain_once()
    lane_ids = await broker.rpc('pending_memoir_background_agents', p_limit=100)
    handles = []
    for lane_id in dict.fromkeys(lane_ids):
        handle = await client.start_workflow(MemoirBackgroundAgent.run,
            args=[lane_id, True] if single_attempt else [lane_id],
            id='memoir-background:' + lane_id, task_queue=task_queue,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            start_signal='notify', start_signal_args=[0])
        handles.append(handle)
        # Each canary agent must settle its own required work before continuing.
        if single_attempt:
            outcome = await handle.result()
            if outcome.get('status') != 'finished':
                raise RuntimeError('Canary lane did not settle on its first attempt')
    return handles


@activity.defn(name='memoir.execute_background_agent')
async def execute_background_agent(run_id: str) -> dict:
    from apps.api.memory_event_worker import MemoryEventWorker, MemoirLaneBroker
    broker = MemoirLaneBroker()
    heartbeat = asyncio.create_task(_heartbeat_lane_activity()) if activity.in_activity() else None
    try:
        return await MemoryEventWorker(broker).execute_background_agent(run_id)
    finally:
        if heartbeat:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
        await broker.client.aclose()


@activity.defn(name='memoir.execute_collection_job')
async def execute_collection_job(job_id: str) -> dict:
    from apps.api.memory_event_worker import MemoirLaneBroker
    from apps.api.lifetime_memory_collection_jobs import CollectionJobWorker
    broker = MemoirLaneBroker()
    try:
        return await CollectionJobWorker(broker).execute(job_id, page_limit=1)
    except Exception:
        # No model output, source content or raw database diagnostics in history.
        raise ApplicationError('Selected collection work needs a retry', type='CollectionJobRetry') from None
    finally:
        await broker.client.aclose()


async def dispatch_collection_jobs_once(client, broker, task_queue):
    from apps.api.lifetime_memory_runtime import lifetime_generation_paused
    jobs = await broker.rpc('pending_lifetime_collection_jobs', p_limit=4,
        p_include_outline=not lifetime_generation_paused())
    handles = []
    for job_id in jobs:
        handles.append(await client.start_workflow(MemoirCollectionJob.run, job_id,
            id='memoir-collection:' + job_id, task_queue=task_queue,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING))
    return handles


async def run_task_worker(address, namespace, task_queue, interval):
    configured_queue()
    # Mocker populates service aliases after processes start. Retrying also
    # lets this worker recover when Temporal starts later during deployment.
    while True:
        try:
            client = await Client.connect(address, namespace=namespace)
            break
        except (RuntimeError, OSError):
            log.warning('Waiting for Temporal connection')
            await asyncio.sleep(interval)
    from apps.api.memory_event_worker import MemoirLaneBroker
    broker = MemoirLaneBroker()
    try:
        async with Worker(client, task_queue=task_queue, workflows=[MemoirSkillLane, MemoirBackgroundAgent, MemoirCollectionJob],
                          activities=[execute_memoir_lane, execute_background_agent, execute_collection_job], max_concurrent_activities=4):
            while True:
                try:
                    await dispatch_memoir_lanes_once(client, broker, task_queue)
                except Exception:
                    log.warning('Memoir lane dispatch deferred')
                try:
                    await dispatch_collection_jobs_once(client, broker, task_queue)
                except Exception:
                    log.warning('Selected collection dispatch deferred')
                try:
                    from apps.api.lifetime_memory_maintenance import drain_lifetime_obligations_once
                    await drain_lifetime_obligations_once(broker, limit=4)
                except Exception:
                    log.warning('Required memory maintenance deferred')
                await asyncio.sleep(interval)
    finally:
        await broker.client.aclose()


async def readiness(address, namespace, task_queue):
    configured_queue()
    client = await Client.connect(address, namespace=namespace)
    # Health is contingent on a live Temporal connection, not an empty store.
    if not await client.service_client.check_health():
        raise RuntimeError('Temporal is unavailable')
