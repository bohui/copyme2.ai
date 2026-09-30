import json

import httpx
import pytest

from apps.api.agent_storage import UserStorage
from apps.api.memoir_tasks import MemoirTask, execute_task
from apps.api.task_queue import TaskQueue
from apps.api.workspace_merge import import_guest_files


GUEST = '11111111-1111-4111-8111-111111111111'
OWNER = '22222222-2222-4222-8222-222222222222'


def test_generated_deliveries_and_collection_citations_import_once(tmp_path):
    queue = TaskQueue(tmp_path / 'tasks.sqlite')
    task = MemoirTask(kind='BuildChapter', sources=[{'id': 'old-memory', 'content': 'My childhood'}])
    source_task = queue.submit(GUEST, 'project-guest', task)
    claim = queue.claim()
    queue.finish(source_task['id'], claim['lease_token'], result=execute_task(claim['task']))
    queue.update_collection(GUEST, 'project-guest', periods={'childhood': {'status': 'recorded', 'memory_ids': ['old-memory']}}, ready=True, expected_revision=0)
    queue.update_collection(OWNER, 'project-guest', periods={'childhood': {'status': 'recorded', 'memory_ids': ['existing-memory']}}, ready=True, expected_revision=0)
    existing_task = queue.submit(OWNER, 'project-other', task)
    queue.import_guest_results(GUEST, OWNER, 'transfer', {'old-memory': 'new-memory'})
    imported = queue.list(OWNER, 'project-guest')
    assert len(imported) == 1
    assert imported[0]['result']['source_memory_ids'] == ['new-memory']
    assert imported[0]['result']['blocks'][0]['source_memory_ids'] == ['new-memory']
    assert queue.get(OWNER, existing_task['id']) is not None
    assert queue.get(GUEST, source_task['id'])['result']['source_memory_ids'] == ['old-memory']
    assert queue.collection(OWNER, 'project-guest')['periods']['childhood']['memory_ids'] == ['existing-memory', 'new-memory']
    assert queue.collection(OWNER, 'project-guest')['ready'] is False
    revision = queue.collection(OWNER, 'project-guest')['revision']
    queue.import_guest_results(GUEST, OWNER, 'transfer', {'old-memory': 'new-memory'})
    assert len(queue.list(OWNER, 'project-guest')) == 1
    assert queue.collection(OWNER, 'project-guest')['revision'] == revision


def test_merge_waits_for_pending_generated_work(tmp_path):
    queue = TaskQueue(tmp_path / 'tasks.sqlite')
    queue.submit_workspace(GUEST, 'project', 'turn', {})
    assert queue.has_pending_user_work(GUEST)
    with pytest.raises(ValueError, match='still being generated'):
        queue.import_guest_results(GUEST, OWNER, 'transfer', {})
    assert queue.list(OWNER, 'project') == []


def test_file_copy_uses_target_authorization_and_keeps_source_files():
    calls = []
    def server(request):
        calls.append(request)
        if request.url.path == '/auth/v1/user':
            return httpx.Response(200, json={'id': OWNER})
        if request.method == 'GET':
            return httpx.Response(200, content=b'generated document', headers={'content-type': 'application/pdf'})
        return httpx.Response(200, json={})
    service = UserStorage('https://example.supabase.co', 'public', 'target-session',
                          client=httpx.Client(transport=httpx.MockTransport(server)))
    source = f'{GUEST}/agent/memories/outline.pdf'
    import_guest_files(service, GUEST, [{'name': source}])
    assert calls[-2].url.path.endswith(source)
    assert calls[-1].url.path.endswith(f'{OWNER}/agent/memories/imports/{GUEST}/outline.pdf')
    assert calls[-1].content == b'generated document'
    assert calls[-1].headers['authorization'] == 'Bearer target-session'
    assert calls[-1].headers['content-type'] == 'application/pdf'
    assert calls[-1].headers['x-upsert'] == 'true'
    assert all(request.method != 'DELETE' for request in calls)
    with pytest.raises(ValueError):
        import_guest_files(service, GUEST, [{'name': f'{OWNER}/attachment/private.png'}])
