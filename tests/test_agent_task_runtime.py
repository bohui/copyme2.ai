import asyncio
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from apps.api.codex_runtime import CodexRuntime
from apps.api.task_queue import configured_queue


@pytest.mark.parametrize('publisher_down', [False, True])
def test_collector_publishes_only_after_commit_and_invalidates_confirmation(monkeypatch, tmp_path, publisher_down):
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB', str(tmp_path / 'tasks.sqlite'))
    storage = Mock()
    storage.user_id = '11111111-1111-4111-8111-111111111111'
    storage.acquire_agent_turn_lease.return_value = True
    storage.renew_agent_turn_lease.return_value = True
    storage.release_agent_turn_lease.return_value = True
    storage.agent_session.return_value = None
    storage.memories.return_value = [{'id': 'school', 'kind': 'agent',
        'content': 'Storyteller: I went to school.\nMemory Spark: Which school?'}]
    storage.profile.return_value = {}
    storage.place_journey.return_value = None
    storage.story_entitlement.return_value = None
    storage.commit_agent_turn.return_value = {'id': 'new-turn'}
    queue = configured_queue()
    queue.update_collection(storage.user_id, 'project', expected_revision=0, periods={}, ready=True)
    runtime = CodexRuntime(worker_url='http://worker', worker_secret='test-key')
    runtime._worker_turn = AsyncMock(return_value={'thread_id': 'collector-thread', 'reply':
        'I can prepare that. [[MEMORY_SPARK_TASKS]][{"kind":"BuildSourceExport","memory_ids":["school"]}][[/MEMORY_SPARK_TASKS]]'})

    async def publish(owner, project, task):
        storage.commit_agent_turn.assert_called_once()
        assert queue.collection(owner, project)['ready'] is False
        assert task.sources[0].content == 'I went to school.'
        if publisher_down:
            raise httpx.ConnectError('publisher unavailable')
        return queue.submit(owner, project, task)

    runtime.publish_task = AsyncMock(side_effect=publish)
    result = asyncio.run(runtime.turn(storage, 'Export my memories', project_id='project'))
    assert result['reply'] == 'I can prepare that.'
    assert 'MEMORY_SPARK_TASKS' not in storage.commit_agent_turn.call_args.args[2]
    runtime.publish_task.assert_awaited_once()
    assert queue.collection(storage.user_id, 'project')['revision'] == 2
    if publisher_down:
        assert not result['tasks']
        assert result['task_errors'] == [{'kind': 'BuildSourceExport', 'code': 'TASK_NOT_QUEUED'}]
    else:
        assert result['tasks'][0]['status'] == 'QUEUED'
        assert not result['task_errors']


def test_collector_role_applies_before_the_first_saved_memory():
    from apps.api.agent_tasks import collection_task_instructions
    assert 'memory-collection agent' in collection_task_instructions([])
