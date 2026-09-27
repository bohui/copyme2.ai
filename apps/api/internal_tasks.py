"""Authenticated persistence ingress; task storage is never mounted in Codex."""
import hmac
import os

from fastapi import APIRouter, Header, HTTPException

from .memoir_tasks import PublishTaskInput
from .task_queue import configured_queue

router = APIRouter()


@router.post('/internal/tasks', status_code=202, include_in_schema=False)
def persist_task(payload: PublishTaskInput, x_codex_worker_secret: str | None = Header(default=None)):
    expected = os.getenv('MEMORY_SPARK_CODEX_WORKER_SECRET', '')
    if not expected or not x_codex_worker_secret or not hmac.compare_digest(expected, x_codex_worker_secret):
        raise HTTPException(401, 'Invalid task publisher credentials')
    return configured_queue().submit(str(payload.user_id), payload.project_id, payload.task)
