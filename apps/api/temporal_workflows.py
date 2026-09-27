"""Deterministic Temporal workflow definitions for Memory Spark jobs."""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn(name="MemorySparkJob")
class MemorySparkJob:
    """Run one durable, idempotent job activity.

    The workflow carries only a job identifier. Sensitive memoir content is
    loaded by the activity from the authorised application store.
    """

    @workflow.run
    async def run(self, job_id: str) -> dict[str, object]:
        return await workflow.execute_activity(
            "memory_spark.execute_job",
            job_id,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


@workflow.defn(name='MemoirTask')
class MemoirTaskWorkflow:
    @workflow.run
    async def run(self, task_id: str) -> dict[str, object]:
        return await workflow.execute_activity(
            'memoir.execute_task', task_id,
            start_to_close_timeout=timedelta(seconds=45),
            retry_policy=RetryPolicy(initial_interval=timedelta(seconds=2),
                                     maximum_interval=timedelta(seconds=15),
                                     maximum_attempts=10),
        )
