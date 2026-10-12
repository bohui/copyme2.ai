"""Offline contracts for the storage seams used by browser recovery fixtures."""
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from apps.api import main, supabase_routes
from apps.api.store import MemoryStore
from browser_recovery_fixture import (RECOVERY_OWNER, RECOVERY_GUEST, NAVIGATION_USERS,
    account_recovery_storage, navigation_storage, set_recovery_principal)


@pytest.mark.parametrize('history_kind', ['memory', 'attachment'])
@pytest.mark.parametrize('adapter', ['missing', 'transferred-guest'])
def test_account_browser_storage_restores_exact_project_and_reviewed_sample(monkeypatch, history_kind, adapter):
    service = account_recovery_storage(history_kind, adapter, 21)
    monkeypatch.setattr(main, 'authenticated_storage', lambda _: service)
    monkeypatch.setattr(supabase_routes, 'storage', lambda _: service)
    monkeypatch.setattr(supabase_routes, '_queue_if_configured', lambda: None)
    store = MemoryStore()
    headers = {'Authorization': 'Bearer fixture-session'}
    with TestClient(main.create_app(store, story_storage_factory=lambda _: service)) as client:
        if adapter == 'transferred-guest':
            set_recovery_principal(service, guest=True)
            original = client.post('/v1/projects', headers=headers, json={})
            assert original.status_code == 201, original.text
            project = store.projects.pop(original.json()['id'])
            project['id'] = 'project_saved'
            store.projects['project_saved'] = project
            set_recovery_principal(service)
        for _ in range(2):
            restored = client.post('/v1/projects', headers=headers, json={'restore_project_id': 'project_saved'})
            assert restored.status_code == 201, restored.text
            assert restored.json()['id'] == 'project_saved'
            assert restored.json()['owner_id'] == RECOVERY_OWNER
            assert client.get('/v1/projects/project_saved', headers=headers).status_code == 200
        assert client.get('/v1/projects/unknown-project', headers=headers).status_code == 404
        assert client.post('/v1/projects', headers=headers, json={'restore_project_id': 'unknown-project'}).status_code == 404
        assert list(store.projects) == ['project_saved']
        assert store.projects['project_saved']['supabase_owner_id'] == RECOVERY_OWNER
        assert set(store.projects['project_saved']['members']) == {RECOVERY_OWNER}
        history = client.get('/v1/user/conversations', headers=headers)
        assert history.status_code == 200, history.text
        assert history.json()['resume_project_id'] == 'project_saved'
        sample = client.post('/v1/story/preview', headers=headers, json={'project_id': 'project_saved'})
        assert sample.status_code == 200, sample.text
        assert sample.json()['preview']['text'] == 'A familiar garden from my childhood.'
        service.retry_memoir_lane.assert_not_called()


@pytest.mark.parametrize('principal', ['guest', 'other'])
def test_navigation_browser_storage_preserves_verified_project_ownership(monkeypatch, principal):
    store = MemoryStore()
    services = {label: navigation_storage(label, store.projects) for label in NAVIGATION_USERS}
    monkeypatch.setattr(main, 'authenticated_storage', lambda authorization: services[authorization.removeprefix('Bearer fixture-')])
    headers = {'Authorization': 'Bearer fixture-' + principal}
    other = 'other' if principal == 'guest' else 'guest'
    with TestClient(main.create_app(store)) as client:
        created = client.post('/v1/projects', headers=headers, json={})
        assert created.status_code == 201, created.text
        project_id = created.json()['id']
        for _ in range(2):
            response = client.get('/v1/projects/' + project_id, headers=headers)
            assert response.status_code == 200, response.text
            assert response.json()['owner_id'] == NAVIGATION_USERS[principal]
        assert client.get('/v1/projects/' + project_id).status_code == 401
        assert client.get('/v1/projects/' + project_id, headers={'Authorization': 'Bearer fixture-' + other}).status_code == 403
        assert client.get('/v1/projects/unknown-project', headers=headers).status_code == 404
        assert client.post('/v1/projects', headers=headers, json={'restore_project_id': 'unknown-project'}).status_code == 404
        assert list(store.projects) == [project_id]


def test_browser_fixture_principals_are_stable_distinct_supabase_uuids():
    owners = [RECOVERY_OWNER, RECOVERY_GUEST, *NAVIGATION_USERS.values()]
    assert len(set(owners)) == len(owners)
    assert all(str(UUID(owner)) == owner for owner in owners)


@pytest.mark.parametrize('name,parameters', [
    ('resolve_lifetime_conversation', {}),
    ('capture_lifetime_read_fence', {'p_project_id': 'project_saved'}),
    ('read_lifetime_project_identity', {'project_id': 'project_saved'}),
    ('read_lifetime_project_identity', {'p_project_id': 'project_saved', 'extra': True}),
    ('read_lifetime_project_identity', {'p_project_id': 'unknown-project'}),
])
def test_unmapped_fixture_rejects_mutations_unknown_projects_and_unexpected_arguments(name, parameters):
    service = account_recovery_storage('memory', 'missing', 21)
    with pytest.raises(AssertionError):
        service.lifetime_rpc(name, **parameters)
    assert service.lifetime_rpc('read_lifetime_project_identity', p_project_id='project_saved') is None
    assert service.lifetime_rpc('read_lifetime_project_identity', p_project_id=None) is None


def test_guest_transfer_updates_the_complete_auth_principal_without_changing_history():
    service = account_recovery_storage('attachment', 'transferred-guest', 2)
    before = service.saved_memoir_draft.return_value.copy()
    for guest, owner in [(True, RECOVERY_GUEST), (False, RECOVERY_OWNER), (False, RECOVERY_OWNER)]:
        set_recovery_principal(service, guest=guest)
        assert service.user_id == owner
        assert service.user == {'id': owner, 'is_anonymous': guest}
        assert service.is_anonymous is guest
        assert service.saved_memoir_draft.return_value == before


@pytest.mark.parametrize('method,path', [
    ('POST', '/rest/v1/user_memoir_project'),
    ('GET', '/rest/v1/unexpected_table'),
    ('POST', '/rest/v1/rpc/resolve_lifetime_conversation'),
])
def test_recovery_storage_never_responds_with_generic_success(method, path):
    service = account_recovery_storage('memory', 'missing', 21)
    with pytest.raises(AssertionError):
        service.request(method, path, params={'user_id': 'eq.' + RECOVERY_OWNER})
