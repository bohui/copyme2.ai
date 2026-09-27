from concurrent.futures import ThreadPoolExecutor

import pytest

from apps.api.memoir_tasks import MemoirTask, execute_task
from apps.api.task_queue import TaskQueue


def task():
    return MemoirTask(kind='BuildChapter', sources=[{'id': 'm1', 'content': 'A memory'}])


def test_task_survives_reopen_and_duplicate_submission(tmp_path):
    path = tmp_path / 'tasks.sqlite'
    original = TaskQueue(path).submit('owner', 'project', task())
    reopened = TaskQueue(path)
    assert reopened.submit('owner', 'project', task())['id'] == original['id']
    claimed = reopened.claim()
    assert reopened.finish(claimed['id'], claimed['lease_token'], result=execute_task(claimed['task']))
    assert TaskQueue(path).get('owner', original['id'])['status'] == 'SUCCEEDED'
    assert TaskQueue(path).get('other', original['id']) is None


def test_concurrent_workers_claim_only_once(tmp_path):
    path = tmp_path / 'tasks.sqlite'
    TaskQueue(path).submit('owner', 'project', task())
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: TaskQueue(path).claim(), range(8)))
    assert sum(value is not None for value in results) == 1


def test_expired_worker_cannot_overwrite_recovered_result(tmp_path, monkeypatch):
    queue = TaskQueue(tmp_path / 'tasks.sqlite')
    monkeypatch.setattr('apps.api.task_queue.time.time', lambda: 100)
    queued = queue.submit('owner', 'project', task())
    old = queue.claim(lease_seconds=10)
    monkeypatch.setattr('apps.api.task_queue.time.time', lambda: 111)
    current = queue.claim(lease_seconds=10)
    assert not queue.finish(old['id'], old['lease_token'], result={'wrong': True})
    assert queue.finish(current['id'], current['lease_token'], result={'right': True})
    assert queue.get('owner', queued['id'])['result'] == {'right': True}


def test_failures_retry_then_stop(tmp_path, monkeypatch):
    queue = TaskQueue(tmp_path / 'tasks.sqlite')
    queued = queue.submit('owner', 'project', task())
    for attempt in range(3):
        monkeypatch.setattr('apps.api.task_queue.time.time', lambda: 9_000_000_000 + attempt * 100)
        claim = queue.claim()
        assert claim
        assert queue.finish(claim['id'], claim['lease_token'], error='TASK_EXECUTION_FAILED')
    assert queue.get('owner', queued['id'])['status'] == 'FAILED'
    assert queue.claim() is None


def test_collection_optimistic_revision_and_new_memory_invalidates_ready(tmp_path):
    queue = TaskQueue(tmp_path / 'tasks.sqlite')
    queue.update_collection('owner', 'project', periods={}, ready=True, expected_revision=0)
    with pytest.raises(ValueError):
        queue.update_collection('owner', 'project', periods={}, ready=True, expected_revision=0)
    queue.invalidate_readiness('owner', 'project')
    assert queue.collection('owner', 'project') == {'revision': 2, 'ready': False, 'periods': {}}
    assert queue.collection('other', 'project')['revision'] == 0


def test_task_database_is_private_even_in_world_readable_mount(tmp_path):
    tmp_path.chmod(0o755)
    path = tmp_path / 'tasks.sqlite'
    queue = TaskQueue(path)
    queue.submit('owner', 'project', task())
    assert path.stat().st_mode & 0o777 == 0o600
    path.chmod(0o644)
    TaskQueue(path)
    assert path.stat().st_mode & 0o777 == 0o600


def test_failed_temporal_execution_fences_late_activity(tmp_path):
    queue = TaskQueue(tmp_path / 'tasks.sqlite')
    entry = queue.submit('owner', 'project', task())
    claim = queue.claim()
    queue.fail_dispatch(entry['id'])
    assert queue.status(entry['id']) == 'FAILED'
    assert not queue.finish(entry['id'], claim['lease_token'], result={})
    assert queue.pending_ids() == []
