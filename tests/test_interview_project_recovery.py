from unittest.mock import Mock

from fastapi.testclient import TestClient

from apps.api import main
from apps.api.store import MemoryStore


def test_authenticated_history_recovers_original_project_shell_after_restart(monkeypatch):
    storage = Mock()
    storage.user_id = 'owner'
    storage.request.return_value.json.return_value = [{'project_id': 'project_saved'}]
    storage.profile.return_value = {'name': 'Saved narrator', 'preferred_language': 'zh-CN'}
    monkeypatch.setattr(main, 'authenticated_storage', lambda _: storage)
    store = MemoryStore()
    with TestClient(main.create_app(store)) as client:
        response = client.post('/v1/projects', headers={'Authorization': 'Bearer saved-session'},
                               json={'restore_project_id': 'project_saved'})
        assert response.status_code == 201
        assert response.json()['id'] == 'project_saved'
        assert response.json()['profile']['name'] == 'Saved narrator'
        assert client.get('/v1/projects/project_saved').status_code == 200
        repeated = client.post('/v1/projects', headers={'Authorization': 'Bearer saved-session'},
                               json={'restore_project_id': 'project_saved'})
        assert repeated.json()['id'] == 'project_saved'
        assert list(store.projects) == ['project_saved']
    assert storage.request.call_args.kwargs['params']['user_id'] == 'eq.owner'
    storage.client.close.assert_called()


def test_project_shell_recovery_requires_owned_persisted_history(monkeypatch):
    storage = Mock()
    storage.user_id = 'owner'
    storage.request.return_value.json.return_value = []
    monkeypatch.setattr(main, 'authenticated_storage', lambda _: storage)
    store = MemoryStore()
    with TestClient(main.create_app(store)) as client:
        response = client.post('/v1/projects', headers={'Authorization': 'Bearer owner-session'},
                               json={'restore_project_id': 'project_other'})
    assert response.status_code == 404
    assert not store.projects


def test_recovery_without_a_supabase_session_is_rejected(monkeypatch):
    monkeypatch.setenv('SUPABASE_URL', 'https://auth.test')
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY', 'public')
    with TestClient(main.create_app(MemoryStore())) as client:
        response = client.post('/v1/projects', json={'restore_project_id': 'project_saved'})
    assert response.status_code == 401
