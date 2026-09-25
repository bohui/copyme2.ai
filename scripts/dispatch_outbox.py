#!/usr/bin/env python3
"""Dispatch Memory Spark outbox events with a crash-safe lease.

The prototype has deterministic in-process job handlers, so normal requests
acknowledge their outbox event when their result is committed. This command
covers the remaining recovery path: a process that dies after the domain
commit can lease the event, attach a deterministic workflow id, and safely
acknowledge an already-terminal job or hand a queued job to the local worker
boundary. Re-running the command is safe because the event and job IDs are
stable.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.api.store import MemoryStore, now_iso


TERMINAL_JOB_STATES = {"SUCCEEDED", "FAILED", "CANCELLED", "DELETION_BLOCKED", "SUPERSEDED", "WAITING_FOR_USER"}


def _expired(value: str | None) -> bool:
    if not value:
        return True
    return datetime.fromisoformat(value) <= datetime.now(timezone.utc)


def dispatch_once(store: MemoryStore, worker_id: str, limit: int, lease_seconds: int) -> dict[str, int]:
    leased = 0
    acknowledged = 0
    accepted = 0
    with store.transaction():
        now = datetime.now(timezone.utc)
        for event in store.outbox:
            if event.get("status") == "LEASED" and _expired(event.get("lease_until")):
                event["status"] = "PENDING"
                event["lease_owner"] = None
                event["lease_until"] = None

        for event in store.outbox:
            if leased >= limit or event.get("status", "PENDING") != "PENDING":
                continue
            leased += 1
            event["status"] = "LEASED"
            event["attempts"] = int(event.get("attempts", 0)) + 1
            event["lease_owner"] = worker_id
            event["lease_until"] = (now + timedelta(seconds=lease_seconds)).isoformat()
            job_id = event.get("job_id")
            job = store.jobs.get(job_id)
            if not job:
                event["status"] = "FAILED"
                event["failure_code"] = "JOB_NOT_FOUND"
                event["acknowledged_at"] = now_iso()
                event["lease_owner"] = None
                event["lease_until"] = None
                acknowledged += 1
                continue

            workflow_id = job.setdefault("workflow_id", f"memory-spark:{job_id}")
            job["dispatch_state"] = "WORKFLOW_ACCEPTED"
            job["workflow_id"] = workflow_id
            job["updated_at"] = now_iso()
            if job.get("status") in TERMINAL_JOB_STATES:
                event["delivery"] = "terminal-job-reconciled"
                acknowledged += 1
            else:
                event["delivery"] = "local-workflow-accepted"
                accepted += 1
            event["status"] = "ACKED"
            event["acknowledged_at"] = now_iso()
            event["lease_owner"] = None
            event["lease_until"] = None

    return {"leased": leased, "acknowledged": acknowledged, "workflow_accepted": accepted}


async def dispatch_temporal_once(
    store: MemoryStore,
    client: object,
    *,
    task_queue: str,
    worker_id: str,
    limit: int,
    lease_seconds: int,
) -> dict[str, int]:
    """Accept outbox work and start deterministic Temporal workflows.

    The existing lease/ack adapter remains the fast local path. This bridge
    scans accepted queued jobs after the lease transaction and starts each
    workflow with its stable job ID. If a process dies after the outbox ack,
    the accepted job is found again on the next pass; Temporal's workflow ID
    makes the repeated start safe.
    """

    from apps.api.temporal_workflows import MemorySparkJob
    from temporalio.exceptions import WorkflowAlreadyStartedError

    dispatch_result = dispatch_once(store, worker_id, limit, lease_seconds)
    with store.transaction():
        candidates = [
            (job["id"], job.setdefault("workflow_id", f"memory-spark:{job['id']}"))
            for job in store.jobs.values()
            if job.get("status") == "QUEUED"
            and job.get("dispatch_state") in {"WORKFLOW_ACCEPTED", "WORKFLOW_PENDING"}
        ][:limit]

    started = 0
    already_started = 0
    deferred = 0
    for job_id, workflow_id in candidates:
        try:
            await client.start_workflow(
                MemorySparkJob.run,
                job_id,
                id=workflow_id,
                task_queue=task_queue,
            )
        except WorkflowAlreadyStartedError:
            already_started += 1
            started += 1
        except Exception:
            deferred += 1
            with store.transaction():
                job = store.jobs.get(job_id)
                if job and job.get("status") == "QUEUED":
                    job["dispatch_state"] = "WORKFLOW_PENDING"
                    job["updated_at"] = now_iso()
        else:
            started += 1
            with store.transaction():
                job = store.jobs.get(job_id)
                if job and job.get("status") == "QUEUED":
                    job["dispatch_state"] = "WORKFLOW_ACCEPTED"
                    job["workflow_id"] = workflow_id
                    job["updated_at"] = now_iso()

    return {
        **dispatch_result,
        "workflow_started": started,
        "workflow_already_started": already_started,
        "workflow_deferred": deferred,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", type=Path, default=os.environ.get("MEMORY_SPARK_STORE_PATH"), help=argparse.SUPPRESS)
    parser.add_argument("--objects", type=Path, default=Path(os.environ.get("MEMORY_SPARK_OBJECT_STORE_PATH", "var/memory-spark/objects")))
    parser.add_argument("--worker-id", default=os.environ.get("MEMORY_SPARK_WORKER_ID", "local-dispatcher"))
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--lease-seconds", type=int, default=60)
    args = parser.parse_args()
    if args.limit < 1 or args.lease_seconds < 1:
        raise SystemExit("--limit and --lease-seconds must be positive")
    if args.store:
        store = MemoryStore.from_path(args.store, object_store_path=args.objects)
    else:
        raise SystemExit("MEMORY_SPARK_STORE_PATH must be configured for the legacy outbox dispatcher")
    result = dispatch_once(store, args.worker_id, args.limit, args.lease_seconds)
    print(f"Outbox dispatcher: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
