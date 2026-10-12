"""Authenticated persistence ingress; task storage is never mounted in Codex."""
import hmac
import os
import sqlite3

from fastapi import APIRouter, Header, HTTPException

from .memoir_tasks import PublishTaskInput
from .lifetime_memory_legacy import (LegacyPublication, LegacyJSONResponse,
    LegacyMappingConflict, LegacyAuthorityUnavailable)
from .task_queue import configured_queue

router = APIRouter()


@router.post('/internal/tasks', status_code=202, include_in_schema=False)
async def persist_task(payload: PublishTaskInput, x_codex_worker_secret: str | None = Header(default=None)):
    expected = os.getenv('MEMORY_SPARK_CODEX_WORKER_SECRET', '')
    if not expected or not x_codex_worker_secret or not hmac.compare_digest(expected, x_codex_worker_secret):
        raise HTTPException(401, 'Invalid task publisher credentials')
    # Detach and validate before taking authority. This bounded synchronous
    # SQLite transaction cannot continue in a background thread after timeout
    # or cancellation has released the PostgreSQL adoption lock.
    payload = PublishTaskInput.model_validate(payload.model_dump(mode='json'))
    publisher = LegacyPublication(os.getenv('MEMOIR_PUBLICATION_DATABASE_URL'), authenticated_owner=payload.user_id)
    try:
        async with publisher.guard():
            result = configured_queue(busy_timeout=.25).submit(str(payload.user_id), payload.project_id, payload.task)
        return LegacyJSONResponse(result,publisher=publisher,status_code=202)
    except LegacyMappingConflict:
        raise HTTPException(409,'This owner requires governed execution',
            headers={'X-Error-Code':LegacyMappingConflict.code}) from None
    except (LegacyAuthorityUnavailable, TimeoutError):
        raise HTTPException(503,'Legacy task authority is unavailable',
            headers={'X-Error-Code':LegacyAuthorityUnavailable.code}) from None
    except (OSError,sqlite3.Error):
        raise HTTPException(503,'Task persistence unavailable; retry the same task') from None


@router.post('/internal/private-drafts/validate/{job_id}',include_in_schema=False)
async def validate_private_draft(job_id: str,x_codex_worker_secret: str | None = Header(default=None)):
    expected=os.getenv('MEMORY_SPARK_CODEX_WORKER_SECRET','')
    if not expected or not x_codex_worker_secret or not hmac.compare_digest(expected,x_codex_worker_secret):
        raise HTTPException(401,'Invalid task publisher credentials')
    from .private_draft_jobs import PrivateDraftJobs
    from .private_draft_broker import PrivateDraftBroker
    queue=PrivateDraftJobs(os.environ['MEMORY_SPARK_TASK_DB'])
    event=queue.authorization_event(job_id)
    if not event:
        raise HTTPException(409,'Private draft authorization is no longer current')
    broker=PrivateDraftBroker()
    try:
        snapshot=await broker.snapshot(event)
        if not snapshot:
            queue.revoke(job_id)
            raise HTTPException(409,'Private draft authorization was revoked')
        broker.reconcile(snapshot)
        if queue.status(job_id)!='RUNNING':
            raise HTTPException(409,'Private draft source snapshot changed')
        return {'authorized':True}
    finally:
        await broker.client.aclose()
