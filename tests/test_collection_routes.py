from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from apps.api import collection_routes
from apps.api.agent_tasks import extract_task_requests, resolve_task
from apps.api.codex_runtime import CodexRuntime
from apps.api.main import create_app
from apps.api.memoir_tasks import MemorySource
from apps.api.profile_intake import LIFE_STAGES
from apps.api.store import MemoryStore
from apps.api.task_queue import configured_queue


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB', str(tmp_path / 'tasks.sqlite'))
    storage = Mock()
    storage.user_id = '11111111-1111-4111-8111-111111111111'
    storage.is_anonymous = False
    storage.all_memories.return_value = [{'id': 'one', 'kind': 'agent',
        'content': 'Storyteller: School in 1970.\nMemory Spark: Were you a teacher?'}]
    storage.story_entitlement.return_value = {'status': 'paid'}
    storage.acquire_agent_turn_lease.return_value = True
    storage.renew_agent_turn_lease.return_value = True
    storage.release_agent_turn_lease.return_value = True
    monkeypatch.setattr(collection_routes, 'authenticated_storage', lambda auth: storage)
    return TestClient(create_app(MemoryStore())), storage


def periods():
    result = {stage: {'status': 'skipped', 'note': 'I prefer not to include this period'} for stage in LIFE_STAGES}
    result['childhood'] = {'status': 'recorded', 'memory_ids': ['one']}
    return result


def test_confirmation_requires_coverage_and_owned_memories(setup):
    client, _ = setup
    path = '/v1/agent/collection/project'
    assert client.put(path, json={'expected_revision': 0, 'periods': {}, 'confirm_ready': True}).status_code == 422
    invalid = periods()
    invalid['childhood']['memory_ids'] = ['other-user']
    assert client.put(path, json={'expected_revision': 0, 'periods': invalid, 'confirm_ready': True}).status_code == 422
    response = client.put(path, json={'expected_revision': 0, 'periods': periods(), 'confirm_ready': True})
    assert response.status_code == 200
    assert response.json()['ready'] is True
    assert client.put(path, json={'expected_revision': 0, 'periods': periods()}).status_code == 409


def test_organiser_requires_current_confirmation_and_payment(setup):
    client, storage = setup
    path = '/v1/agent/collection/project'
    assert client.post(path + '/organise', json={'expected_revision': 1}).status_code == 409
    client.put(path, json={'expected_revision': 0, 'periods': periods(), 'confirm_ready': True})
    storage.story_entitlement.return_value = None
    assert client.post(path + '/organise', json={'expected_revision': 1}).status_code == 402


def test_collection_shows_only_storyteller_source_text(setup):
    client, _ = setup
    response = client.get('/v1/agent/collection/project')
    assert response.json()['sources'] == [{'id': 'one', 'content': 'School in 1970.'}]


def test_task_lookup_is_owner_scoped(setup):
    client, _ = setup
    from apps.api.memoir_tasks import MemoirTask
    task = configured_queue().submit('different-user', 'project', MemoirTask(
        kind='BuildSourceExport', sources=[{'id': 'private', 'content': 'private text'}]))
    response = client.get('/v1/agent/tasks/' + task['id'])
    assert response.status_code == 404
    assert 'private text' not in response.text


def test_agent_task_contract_drops_invalid_requests_and_rejects_unknown_sources():
    visible, requests = extract_task_requests('Hello [[MEMORY_SPARK_TASKS]][{"kind":"RunShell"}][[/MEMORY_SPARK_TASKS]]')
    assert visible == 'Hello' and requests == []
    visible, requests = extract_task_requests('Export queued [[MEMORY_SPARK_TASKS]][{"kind":"BuildSourceExport","memory_ids":["other"]}][[/MEMORY_SPARK_TASKS]]')
    with pytest.raises(ValueError, match='unavailable'):
        resolve_task(requests[0], [MemorySource(id='own', content='my memory')])


def test_generated_book_artifacts_are_not_reused_as_memory_evidence():
    rows = [
        {'id': 'chapter', 'kind': 'memoir', 'content': '{"chapter_number":1}', 'source_paths': ['story-chapter:1']},
        {'id': 'round', 'kind': 'memoir', 'content': '{"type":"story_round","answer":"My answer"}'},
    ]
    assert [source.model_dump() for source in CodexRuntime._task_sources(rows)] == [{'id': 'round', 'content': 'My answer'}]


def test_collection_review_is_serialized_with_agent_turns(setup):
    client, storage = setup
    storage.acquire_agent_turn_lease.return_value = False
    response = client.put('/v1/agent/collection/project', json={
        'expected_revision': 0, 'periods': periods(), 'confirm_ready': True})
    assert response.status_code == 409
    assert configured_queue().collection(storage.user_id, 'project')['ready'] is False


def test_memory_changes_invalidate_confirmation_even_if_notification_was_lost(setup):
    client, storage = setup
    path = '/v1/agent/collection/project'
    client.put(path, json={'expected_revision': 0, 'periods': periods(), 'confirm_ready': True})
    storage.all_memories.return_value[0]['content'] = 'Storyteller: A corrected memory.\nMemory Spark: Thanks'
    assert client.post(path + '/organise', json={'expected_revision': 1}).status_code == 409


@pytest.mark.parametrize('memory_id, expected_status', [('one', 202), ('invented', 502)])
def test_organiser_validates_sources_before_publishing(setup, monkeypatch, memory_id, expected_status):
    import httpx
    from unittest.mock import AsyncMock
    client, storage = setup
    path = '/v1/agent/collection/project'
    assert client.put(path, json={'expected_revision': 0, 'periods': periods(), 'confirm_ready': True}).status_code == 200
    monkeypatch.setenv('MEMORY_SPARK_CODEX_WORKER_URL', 'http://private-worker')
    monkeypatch.setenv('MEMORY_SPARK_CODEX_WORKER_SECRET', 'test-secret')
    response = httpx.Response(200, request=httpx.Request('POST', 'http://private-worker'), json={
        'reply': __import__('json').dumps({'title': 'My book', 'sections': [
            {'title': 'School days', 'memory_ids': [memory_id]}]})})
    post = AsyncMock(return_value=response)
    monkeypatch.setattr(httpx.AsyncClient, 'post', post)
    publish = AsyncMock(return_value={'id': 'queued-outline', 'status': 'QUEUED'})
    monkeypatch.setattr(CodexRuntime, 'publish_task', publish)
    result = client.post(path + '/organise', json={'expected_revision': 1})
    assert result.status_code == expected_status
    sent = post.call_args.kwargs['json']
    assert sent['agent_role'] == 'organiser' and 'thread_id' not in sent
    assert sent['task_sources'] == [{'id': 'one', 'content': 'School in 1970.'}]
    if expected_status == 202:
        owner, project, task = publish.call_args.args
        assert owner == storage.user_id and project == 'project'
        assert task.kind == 'BuildOutline'
        assert task.sections[0].memory_ids == ['one']
    else:
        publish.assert_not_called()
