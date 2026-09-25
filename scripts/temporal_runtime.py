#!/usr/bin/env python3
"""Workflow worker and dispatcher runtime for the legacy local adapter."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from temporalio import activity
from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.worker import Worker

from apps.api.store import MemoryStore, now_iso
from apps.api.temporal_workflows import MemorySparkJob


def _store_from_environment() -> MemoryStore:
    object_path = Path(os.environ.get("MEMORY_SPARK_OBJECT_STORE_PATH", "var/memory-spark/objects"))
    store_path = os.environ.get("MEMORY_SPARK_STORE_PATH")
    if store_path:
        return MemoryStore.from_path(store_path, object_store_path=object_path)
    return MemoryStore(object_store_path=object_path)


def _job_result(job: dict[str, Any]) -> dict[str, object]:
    result: dict[str, object] = {
        "job_id": job.get("id", ""),
        "status": job.get("status", "UNKNOWN"),
    }
    if job.get("result") is not None:
        result["result"] = job["result"]
    if job.get("error") is not None:
        result["error"] = job["error"]
    return result


@activity.defn(name="memory_spark.execute_job")
async def execute_memory_spark_job(job_id: str) -> dict[str, object]:
    """Execute one job under the same durable store transaction as the API."""

    # Import the deterministic domain handler only in the activity process.
    # The workflow sandbox never imports this module or the store.
    from scripts.worker import _process_job

    activity.heartbeat({"job_id": job_id, "stage": "loading"})
    store = _store_from_environment()
    with store.transaction():
        job = store.jobs.get(job_id)
        if job is None:
            return {"job_id": job_id, "status": "FAILED", "error": {"code": "JOB_NOT_FOUND"}}
        if job.get("status") in {"SUCCEEDED", "FAILED", "CANCELLED", "DELETION_BLOCKED", "SUPERSEDED", "WAITING_FOR_USER"}:
            return _job_result(job)
        job["dispatch_state"] = "WORKFLOW_ACCEPTED"
        job["updated_at"] = now_iso()
        _process_job(store, job)
        activity.heartbeat({"job_id": job_id, "stage": "committed"})
        return _job_result(job)


async def _dispatch_loop(
    store: MemoryStore,
    client: Client,
    task_queue: str,
    worker_id: str,
    interval: float,
    limit: int,
    lease_seconds: int,
) -> None:
    from scripts.dispatch_outbox import dispatch_temporal_once

    while True:
        try:
            await dispatch_temporal_once(
                store,
                client,
                task_queue=task_queue,
                worker_id=worker_id,
                limit=limit,
                lease_seconds=lease_seconds,
            )
        except Exception as exc:  # pragma: no cover - only reached on service outage
            print(f"Temporal dispatcher retrying: {type(exc).__name__}: {exc}", flush=True)
        await asyncio.sleep(interval)


async def run_temporal_worker(
    *,
    address: str,
    namespace: str,
    task_queue: str,
    worker_id: str,
    store: MemoryStore,
    interval: float,
    limit: int,
    lease_seconds: int,
) -> None:
    client = await Client.connect(address, namespace=namespace, identity=worker_id)
    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=[MemorySparkJob],
        activities=[execute_memory_spark_job],
        max_concurrent_activities=4,
    )
    async with worker:
        # ``async with Worker`` starts validation in a background task. Wait
        # for Core to finish initialization before the dispatcher uses the
        # same client; concurrent first calls can initialize the Rust bridge
        # task locals twice.
        while not worker._started:  # type: ignore[attr-defined]
            await asyncio.sleep(0.01)
        await _dispatch_loop(store, client, task_queue, worker_id, interval, limit, lease_seconds)


__all__ = ["MemorySparkJob", "execute_memory_spark_job", "run_temporal_worker", "WorkflowAlreadyStartedError"]
