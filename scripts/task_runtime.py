"""Temporal execution of deterministic memoir tasks from the durable outbox."""
import asyncio
import logging
import os

from temporalio import activity
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.common import WorkflowIDReusePolicy, WorkflowIDConflictPolicy
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError
from temporalio.worker import Worker

from apps.api.memoir_tasks import execute_task
from apps.api.task_queue import configured_queue
from apps.api.temporal_workflows import MemoirTaskWorkflow, PrivateMemoirDraftWorkflow, MemoirSkillLane
from apps.api.private_draft_jobs import PrivateDraftJobs

log = logging.getLogger(__name__)


@activity.defn(name='memoir.execute_lane')
async def execute_memoir_lane(lane_id: str) -> dict:
    from apps.api.memory_event_worker import MemoryEventWorker, MemoirLaneBroker
    broker = MemoirLaneBroker()
    try:
        result = await MemoryEventWorker(broker).execute_lane(lane_id)
        state = await broker.rpc('read_memoir_lane_state', p_lane_id=lane_id)
        return {'status': result['status'], 'pending': bool(state and state['pending'])}
    finally:
        await broker.client.aclose()


async def dispatch_memoir_lanes_once(client, broker, task_queue, *, single_attempt=False):
    if type(single_attempt) is not bool or (single_attempt and not task_queue.startswith('canary-')):
        raise ValueError('Single-attempt execution requires a task-owned canary queue')
    lane_ids = await broker.drain_once()
    lane_ids.extend(await broker.rpc('pending_memoir_lanes', p_limit=100))
    handles = []
    for lane_id in dict.fromkeys(lane_ids):
        handle = await client.start_workflow(MemoirSkillLane.run,
            args=[lane_id, True] if single_attempt else [lane_id],
            id='memoir-lane:' + lane_id, task_queue=task_queue,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            start_signal='notify', start_signal_args=[0])
        handles.append(handle)
        # The canary broker returns timeline before composer. Await each lane
        # so a composer cannot consume its sole attempt before extraction.
        if single_attempt:
            outcome = await handle.result()
            if outcome.get('status') != 'finished':
                raise RuntimeError('Canary lane did not settle on its first attempt')
    return handles


@activity.defn(name='memoir.private_draft')
async def execute_private_draft(job_id: str) -> dict:
    from apps.api.private_drafts import execute
    result = await execute(job_id)
    if result['status'] in {'deferred','retry'}:
        raise ApplicationError('Private draft is waiting for its project lease',type='DraftBusy')
    if result['status']=='failed':
        raise ApplicationError('Private draft needs an explicit retry',type='DraftFailed',non_retryable=True)
    return result


@activity.defn(name='memoir.execute_task')
async def execute_memoir_task(task_id: str) -> dict:
    # Only the opaque ID enters Temporal history; private input and artifact
    # content stay in the application task store.
    queue = configured_queue()
    claimed = await asyncio.to_thread(queue.claim, task_id=task_id, lease_seconds=30)
    if claimed is None:
        status = await asyncio.to_thread(queue.status, task_id)
        if status == 'SUCCEEDED':
            return {'task_id': task_id, 'status': 'SUCCEEDED'}
        if status in {'QUEUED', 'RUNNING'}:
            raise ApplicationError('Task lease busy', type='TaskBusy')
        raise ApplicationError('Task missing or failed', type='TaskFailed', non_retryable=True)
    try:
        result = await asyncio.to_thread(execute_task, claimed['task'])
    except Exception:
        await asyncio.to_thread(queue.finish, task_id, claimed['lease_token'], error='TASK_EXECUTION_FAILED')
        raise ApplicationError('Deterministic task failed', type='TaskExecutionFailed') from None
    saved = await asyncio.to_thread(queue.finish, task_id, claimed['lease_token'], result=result)
    if not saved:
        raise ApplicationError('Task lease expired', type='TaskLeaseExpired')
    return {'task_id': task_id, 'status': 'SUCCEEDED'}


async def run_task_worker(address, namespace, task_queue, interval):
    queue = configured_queue()
    # Mocker populates service aliases after processes start. Retrying also
    # lets this worker recover when Temporal starts later during deployment.
    while True:
        try:
            client = await Client.connect(address, namespace=namespace)
            break
        except (RuntimeError, OSError):
            log.warning('Waiting for Temporal connection')
            await asyncio.sleep(interval)
    drafts=PrivateDraftJobs(queue.path)
    from apps.api.memory_event_worker import MemoirLaneBroker
    broker = MemoirLaneBroker() if os.getenv('SUPABASE_URL') and os.getenv('SUPABASE_SECRET_KEY') else None
    async with Worker(client, task_queue=task_queue, workflows=[MemoirTaskWorkflow,PrivateMemoirDraftWorkflow,MemoirSkillLane],
                      activities=[execute_memoir_task,execute_private_draft,execute_memoir_lane], max_concurrent_activities=4):
        while True:
            if broker is not None:
                try:
                    await dispatch_memoir_lanes_once(client, broker, task_queue)
                except Exception:
                    log.warning('Memoir lane dispatch deferred')
            for draft_id in await asyncio.to_thread(drafts.pending_ids) if broker is None else []:
                try:
                    await client.start_workflow(PrivateMemoirDraftWorkflow.run,draft_id,id=f'memoir-private-draft:{draft_id}',
                        task_queue=task_queue,id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY)
                except WorkflowAlreadyStartedError:
                    pass
                except Exception:
                    log.warning('Private draft dispatch deferred')
            for task_id in await asyncio.to_thread(queue.pending_ids):
                try:
                    await client.start_workflow(
                        MemoirTaskWorkflow.run, task_id, id=f'memoir-task:{task_id}',
                        task_queue=task_queue,
                        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                    )
                except WorkflowAlreadyStartedError:
                    try:
                        execution = await client.get_workflow_handle(f'memoir-task:{task_id}').describe()
                        if execution.status in {
                            WorkflowExecutionStatus.FAILED, WorkflowExecutionStatus.CANCELED,
                            WorkflowExecutionStatus.TERMINATED, WorkflowExecutionStatus.TIMED_OUT,
                        }:
                            await asyncio.to_thread(queue.fail_dispatch, task_id)
                    except Exception:
                        log.warning('Temporal status check deferred for task %s', task_id)
                except Exception:
                    # Keep the outbox row for a later start; never acknowledge
                    # uncertain delivery or log the memory snapshot.
                    log.warning('Temporal dispatch deferred for task %s', task_id)
            await asyncio.sleep(interval)


async def readiness(address, namespace, task_queue):
    configured_queue()
    client = await Client.connect(address, namespace=namespace)
    # Health is contingent on a live Temporal connection, not an empty store.
    if not await client.service_client.check_health():
        raise RuntimeError('Temporal is unavailable')
