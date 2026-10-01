import asyncio

from apps.api.codex_runtime import CodexRuntime


def test_place_update_precedes_optional_artifact_transfer(monkeypatch):
    monkeypatch.delenv('MEMORY_SPARK_TASK_DB', raising=False)

    class Storage:
        user_id = 'latency-test'

        def acquire_agent_turn_lease(self, *args):
            return True

        def release_agent_turn_lease(self, *args):
            return True

        def place_journey(self):
            return None

        def save_place_journey(self, token, journey, **kwargs):
            return {**journey, 'duration_ms': 5200, 'status': 'active', 'revision': 1,
                'source_sequence': 1, 'updated_at': '2026-10-01T00:00:00Z'}

    async def run():
        runtime = CodexRuntime()
        artifacts = asyncio.get_running_loop().create_future()
        place_ready = asyncio.Event()

        async def emit(event):
            if event.get('data', {}).get('place_journey_change', {}).get('changed'):
                place_ready.set()

        task = asyncio.create_task(runtime._persist_workspace(
            storage=Storage(), user_id='latency-test', project_id=None,
            family_enabled=False, existing_family_context=None,
            current_place_journey=None,
            parsed_place_journey={'schema_version': 1, 'place': 'Sydney',
                'hierarchy': ['Earth', 'Australia', 'Sydney'], 'granularity': 'city'},
            parsed_family_context=None, family_skills=[], profile={}, profile_updates=None,
            task_requests=[], memories=[], text='Sydney', language='en-AU', turn_sequence=1,
            deferred_artifacts=[], deferred_artifacts_task=artifacts, deferred_home=None,
            memory={}, legacy_markers=True, turn_id='test', on_event=emit, trajectory=None,
        ))
        try:
            await asyncio.wait_for(place_ready.wait(), 0.2)
            assert not artifacts.done()
        finally:
            artifacts.set_result([])
            await task

    asyncio.run(run())
