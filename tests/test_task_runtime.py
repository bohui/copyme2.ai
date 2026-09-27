import asyncio
from unittest.mock import Mock

import pytest

pytest.importorskip('temporalio')
from temporalio.exceptions import ApplicationError

from apps.api.memoir_tasks import MemoirTask
from apps.api.task_queue import configured_queue
from scripts import task_runtime


def test_activity_replay_uses_saved_result(monkeypatch, tmp_path):
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB', str(tmp_path / 'tasks.sqlite'))
    queue = configured_queue()
    entry = queue.submit('owner', 'project', MemoirTask(kind='BuildSourceExport',
        sources=[{'id': 'one', 'content': 'Private memory'}]))
    execute = Mock(wraps=task_runtime.execute_task)
    monkeypatch.setattr(task_runtime, 'execute_task', execute)
    first = asyncio.run(task_runtime.execute_memoir_task(entry['id']))
    second = asyncio.run(task_runtime.execute_memoir_task(entry['id']))
    assert first == second == {'task_id': entry['id'], 'status': 'SUCCEEDED'}
    execute.assert_called_once()
    assert 'Private memory' not in str(first)
    assert queue.get('owner', entry['id'])['result']['sources'][0]['content'] == 'Private memory'


def test_busy_activity_is_retryable_without_duplicate_execution(monkeypatch, tmp_path):
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB', str(tmp_path / 'tasks.sqlite'))
    queue = configured_queue()
    entry = queue.submit('owner', 'project', MemoirTask(kind='BuildSourceExport',
        sources=[{'id': 'one', 'content': 'Private memory'}]))
    queue.claim(task_id=entry['id'])
    with pytest.raises(ApplicationError) as error:
        asyncio.run(task_runtime.execute_memoir_task(entry['id']))
    assert error.value.type == 'TaskBusy'
    assert not error.value.non_retryable
    assert queue.get('owner', entry['id'])['attempts'] == 1
