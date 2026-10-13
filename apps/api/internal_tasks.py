"""Authenticated persistence ingress; task storage is never mounted in Codex."""
import hmac
import os

from fastapi import APIRouter, Header, HTTPException


router = APIRouter()


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
