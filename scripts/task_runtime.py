"""Temporal execution of deterministic memoir tasks from the durable outbox."""
import asyncio
import logging

from temporalio import activity
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError
from temporalio.worker import Worker

from apps.api.memoir_tasks import execute_task
from apps.api.task_queue import configured_queue
from apps.api.temporal_workflows import MemoirTaskWorkflow, PrivateMemoirDraftWorkflow
from apps.api.private_draft_jobs import PrivateDraftJobs

log = logging.getLogger(__name__)


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
    async with Worker(client, task_queue=task_queue, workflows=[MemoirTaskWorkflow,PrivateMemoirDraftWorkflow],
                      activities=[execute_memoir_task,execute_private_draft], max_concurrent_activities=4):
        while True:
            for draft_id in await asyncio.to_thread(drafts.pending_ids):
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
