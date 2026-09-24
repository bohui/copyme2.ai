from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("temporalio")

from apps.api.store import MemoryStore
from scripts.dispatch_outbox import dispatch_temporal_once


class FakeTemporalClient:
    def __init__(self) -> None:
        self.starts: list[tuple[object, str, str, str]] = []

    async def start_workflow(self, workflow: object, job_id: str, *, id: str, task_queue: str) -> None:
        self.starts.append((workflow, job_id, id, task_queue))


def test_temporal_dispatch_uses_stable_workflow_id_for_queued_job() -> None:
    store = MemoryStore()
    store.projects["project_temporal_dispatch"] = {"id": "project_temporal_dispatch"}
    job = store.queue_job("project_temporal_dispatch", "BuildFreePreview")
    client = FakeTemporalClient()

    result = asyncio.run(
        dispatch_temporal_once(
            store,
            client,
            task_queue="memory-spark",
            worker_id="test-temporal-dispatcher",
            limit=10,
            lease_seconds=30,
        )
    )

    assert result["workflow_started"] == 1
    assert result["workflow_deferred"] == 0
    assert len(client.starts) == 1
    workflow, job_id, workflow_id, task_queue = client.starts[0]
    assert getattr(workflow, "__qualname__", "").endswith("MemorySparkJob.run")
    assert job_id == job["id"]
    assert workflow_id == f"memory-spark:{job['id']}"
    assert task_queue == "memory-spark"
    assert store.jobs[job["id"]]["dispatch_state"] == "WORKFLOW_ACCEPTED"
