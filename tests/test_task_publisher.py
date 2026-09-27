from fastapi.testclient import TestClient

from apps.api.codex_worker_service import app
from apps.api.main import create_app
from apps.api.store import MemoryStore
from apps.api.task_queue import configured_queue


def test_private_publisher_auth_validation_and_deduplication(monkeypatch, tmp_path):
    from unittest.mock import AsyncMock
    import httpx
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB', str(tmp_path / 'tasks.sqlite'))
    monkeypatch.setenv('MEMORY_SPARK_CODEX_WORKER_SECRET', 'private-test-key')
    monkeypatch.setenv('MEMORY_SPARK_TASK_STORE_URL', 'http://api:8000')
    persistence = TestClient(create_app(MemoryStore()))
    async def forward(url, **kwargs):
        assert url == 'http://api:8000/internal/tasks'
        return persistence.post('/internal/tasks', **kwargs)
    monkeypatch.setattr(httpx.AsyncClient, 'post', AsyncMock(side_effect=forward))
    client = TestClient(app)
    payload = {'user_id': '11111111-1111-4111-8111-111111111111', 'project_id': 'project',
               'task': {'kind': 'BuildSourceExport', 'sources': [{'id': 'm1', 'content': 'A memory'}]}}
    assert client.post('/internal/tasks', json=payload).status_code == 401
    assert persistence.post('/internal/tasks', json=payload).status_code == 401
    headers = {'X-Codex-Worker-Secret': 'private-test-key'}
    result = client.post('/internal/tasks', json=payload, headers=headers)
    assert result.status_code == 202
    assert result.json()['status'] == 'QUEUED'
    assert client.post('/internal/tasks', json=payload, headers=headers).json()['id'] == result.json()['id']
    assert configured_queue().get('another-owner', result.json()['id']) is None
    payload['task']['kind'] = 'RunShell'
    assert client.post('/internal/tasks', json=payload, headers=headers).status_code == 422


def test_codex_container_has_no_task_database_mount():
    from pathlib import Path
    compose = Path('compose.yml').read_text()
    codex = compose.split('  codex-worker:', 1)[1].split('\n  worker:', 1)[0]
    assert 'memoir-tasks:' not in codex
    assert 'MEMORY_SPARK_TASK_DB:' not in codex
    assert 'MEMORY_SPARK_TASK_STORE_URL: http://api:8000' in codex


def test_publisher_does_not_acknowledge_failed_persistence(monkeypatch):
    from unittest.mock import AsyncMock
    import httpx
    monkeypatch.setenv('MEMORY_SPARK_CODEX_WORKER_SECRET', 'private-test-key')
    monkeypatch.setenv('MEMORY_SPARK_TASK_STORE_URL', 'http://api:8000')
    monkeypatch.setattr(httpx.AsyncClient, 'post', AsyncMock(side_effect=httpx.ConnectError('unavailable')))
    response = TestClient(app).post('/internal/tasks',
        headers={'X-Codex-Worker-Secret': 'private-test-key'},
        json={'user_id': '11111111-1111-4111-8111-111111111111', 'project_id': 'project',
              'task': {'kind': 'BuildSourceExport', 'sources': [{'id': 'm1', 'content': 'Synthetic'}]}})
    assert response.status_code == 503
    assert 'id' not in response.json()
