"""Deterministic Temporal workflow definitions for Memory Spark jobs."""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
import asyncio


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


@workflow.defn(name='PrivateMemoirDraft')
class PrivateMemoirDraftWorkflow:
    @workflow.run
    async def run(self, job_id: str) -> dict[str, object]:
        return await workflow.execute_activity('memoir.private_draft', job_id,
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(maximum_attempts=3))


@workflow.defn(name='MemoirSkillLane')
class MemoirSkillLane:
    """One stable project/skill workflow; PostgreSQL is the input authority."""
    def __init__(self):
        self.notified = False

    @workflow.signal(name='notify')
    def notify(self, change_sequence: int = 0):
        # Only safe sequence metadata is accepted. Content stays in the activity.
        self.notified = True

    @workflow.run
    async def run(self, lane_id: str, single_attempt: bool = False) -> dict:
        # The isolated canary explicitly opts out of activity redelivery and
        # workflow-loop retry. Existing production histories retain defaults.
        if type(single_attempt) is not bool:
            raise ValueError('single_attempt must be a boolean')
        for _ in range(100):
            self.notified = False
            result = await workflow.execute_activity('memoir.execute_lane', lane_id,
                start_to_close_timeout=timedelta(seconds=300 if single_attempt else 1860),
                retry_policy=RetryPolicy(initial_interval=timedelta(seconds=2),
                    maximum_interval=timedelta(seconds=30), maximum_attempts=1 if single_attempt else 3))
            if result['status'] == 'retry_required':
                return {'status': 'retry_required'}
            if result['status'] in {'saved', 'proposed', 'finished'} and not result.get('pending') and not self.notified:
                return {'status': 'finished'}
            if single_attempt:
                return {'status': 'retry_required'}
            try:
                await workflow.wait_condition(lambda: self.notified, timeout=timedelta(seconds=5))
            except asyncio.TimeoutError:
                pass
        workflow.continue_as_new(lane_id)
