"""Only opaque collection job identifiers enter bounded Temporal histories."""
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn(name='MemoirCollectionJob')
class MemoirCollectionJob:
    @workflow.run
    async def run(self, job_id: str) -> dict:
        # Canonical SQL owns progress. Each activity admits at most one model
        # request; continue-as-new bounds orchestration history independently.
        for _ in range(64):
            result = await workflow.execute_activity('memoir.execute_collection_job', job_id,
                start_to_close_timeout=timedelta(seconds=360),
                retry_policy=RetryPolicy(initial_interval=timedelta(seconds=2),
                    maximum_interval=timedelta(seconds=30), maximum_attempts=3))
            if result['status'] != 'pending':
                return {'status': result['status']}
        workflow.continue_as_new(job_id)
