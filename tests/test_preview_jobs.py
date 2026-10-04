import json
import os

from apps.api.preview_jobs import PreviewJobs


def test_private_queue_deduplicates_fences_and_recovers_checkpoint(tmp_path, monkeypatch):
    path = tmp_path / 'jobs.sqlite'
    queue = PreviewJobs(path)
    submitted = queue.submit('owner', 'project', 'snapshot', 'zh-CN', {'key': 'snapshot'})
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert queue.get('other-owner', submitted['id']) is None
    first = queue.claim('owner', submitted['id'], lease_seconds=10)
    assert queue.claim('owner', submitted['id']) is None
    assert queue.submit('owner', 'project', 'snapshot', 'zh-CN', {'key': 'snapshot'}, retry=True)['id'] == first['id']
    queue.checkpoint(first['id'], first['lease_token'], 'reviewing', {'draft': {'synthetic': True}})
    import apps.api.preview_jobs as module
    now = module.time.time()
    monkeypatch.setattr(module.time, 'time', lambda: now + 901)
    reopened = PreviewJobs(path)
    second = reopened.claim('owner', first['id'])
    assert second['checkpoint']['draft'] == {'synthetic': True}
    assert not queue.finish(first['id'], first['lease_token'])
    assert reopened.finish(second['id'], second['lease_token'], outcome='ready')
    assert reopened.get('owner', first['id'])['status'] == 'SUCCEEDED'
    # No auth data is part of the persisted contract.
    with reopened._connect() as db:
        row = dict(db.execute('SELECT * FROM preview_jobs').fetchone())
    assert not any(word in json.dumps(row).lower() for word in ('bearer', 'access_token', 'authorization'))


def test_retry_is_bounded_and_manual_retry_keeps_successful_phases(tmp_path, monkeypatch):
    queue = PreviewJobs(tmp_path / 'jobs.sqlite')
    job = queue.submit('owner', 'project', 'key', 'en-AU', {'key': 'key'})
    import apps.api.preview_jobs as module
    clock = [module.time.time()]
    monkeypatch.setattr(module.time, 'time', lambda: clock[0])
    for attempt in range(3):
        claim = queue.claim('owner', job['id'])
        assert claim
        queue.checkpoint(job['id'], claim['lease_token'], 'reviewing', {'draft': 'validated'})
        queue.finish(job['id'], claim['lease_token'], error='PREVIEW_TIMEOUT', retryable=True)
        clock[0] += 10
    assert queue.get('owner', job['id'])['status'] == 'FAILED'
    assert not queue.claim('owner', job['id'])
    retry = queue.submit('owner', 'project', 'key', 'en-AU', {'key': 'key'}, retry=True)
    assert retry['id'] == job['id']
    assert queue.claim('owner', job['id'])['checkpoint']['draft'] == 'validated'


def test_guest_transfer_waits_for_preview_without_copying_private_checkpoints(tmp_path):
    import pytest
    from apps.api.task_queue import TaskQueue
    path = tmp_path / 'jobs.sqlite'
    queue = PreviewJobs(path)
    queue.submit('guest', 'project', 'key', 'en-AU', {'key': 'key'})
    general = TaskQueue(path)
    assert general.has_pending_user_work('guest')
    assert not general.has_pending_user_work('other-user')
    with pytest.raises(ValueError, match='still being generated'):
        general.import_guest_results('guest', 'owner', 'transfer', {})


def test_busy_conversation_does_not_exhaust_composition_retries(tmp_path, monkeypatch):
    queue = PreviewJobs(tmp_path / 'jobs.sqlite')
    job = queue.submit('owner', 'project', 'key', 'en-AU', {'key': 'key'})
    import apps.api.preview_jobs as module
    clock = [module.time.time()]
    monkeypatch.setattr(module.time, 'time', lambda: clock[0])
    for _ in range(8):
        claim = queue.claim('owner', job['id'])
        assert claim
        queue.finish(job['id'], claim['lease_token'], error='AGENT_TURN_IN_PROGRESS', retryable=True)
        assert queue.get('owner', job['id'])['attempts'] == 0
        clock[0] += 16
    assert queue.get('owner', job['id'])['status'] == 'QUEUED'
