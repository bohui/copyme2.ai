from copy import deepcopy
from unittest.mock import Mock
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient

from apps.api import main, supabase_routes
from apps.api.photo_memories import PhotoMemoryInput, update_photo_memory
from apps.api.store import MemoryStore


PRINCIPALS = {label: str(UUID(int=index)) for index, label in enumerate(
    ('owner', 'storyteller', 'member', 'outsider'), start=1)}

PHOTO = {'asset_id': 'street', 'image_url': 'https://images.example/street.jpg',
         'source_url': 'https://archive.example/street', 'title': 'Old street',
         'date_expression': '1983', 'attribution': 'Public archive', 'place': 'Chengde'}


def _unmapped_identity(name, **parameters):
    assert name == 'read_lifetime_project_identity', 'Unexpected lifetime operation in legacy fixture'
    assert set(parameters) == {'p_project_id'}
    return None


def test_favorites_and_selection_survive_restart_and_remain_project_scoped(tmp_path):
    path = str(tmp_path / 'store.json')
    client = TestClient(main.create_app(MemoryStore(persistence_path=path)))
    headers = {'X-Account-Id': 'photo-owner'}
    project = client.post('/v1/projects', headers=headers, json={'mode': 'self'}).json()
    other = client.post('/v1/projects', headers=headers, json={'mode': 'self'}).json()
    url = f'/v1/projects/{project["id"]}/photo-memories'
    for _ in range(2):
        response = client.put(url, headers=headers, json={'action': 'select', 'photo': PHOTO})
        assert response.status_code == 200
        assert len(response.json()['favorites']) == 1
    selected = response.json()
    assert selected['selected'] == PHOTO['image_url']
    client = TestClient(main.create_app(MemoryStore(persistence_path=path)))
    profile = client.get(f'/v1/projects/{project["id"]}', headers=headers).json()['profile']
    assert profile['photo_memories'][project['id']] == selected
    assert 'photo_memories' not in client.get(f'/v1/projects/{other["id"]}', headers=headers).json()['profile']
    assert client.put(url, headers={'X-Account-Id': 'stranger'}, json={'action': 'clear'}).status_code == 403
    cleared = client.put(url, headers=headers, json={'action': 'clear'}).json()
    assert cleared['selected'] is None and len(cleared['favorites']) == 1
    removed = client.put(url, headers=headers, json={'action': 'unfavorite', 'photo': PHOTO}).json()
    assert removed['favorites'] == [] and removed['selected'] is None
    assert removed['selection_revision'] == cleared['selection_revision']


def test_supabase_save_uses_latest_profile_and_does_not_claim_success_on_failure(monkeypatch):
    saved = {'name': 'Storyteller', 'photo_memories': {'other': {'favorites': [], 'selected': None}}}
    service = Mock()
    service.user_id = PRINCIPALS['owner']
    service.lifetime_rpc = Mock(side_effect=_unmapped_identity)
    service.profile.side_effect = lambda: deepcopy(saved)
    service.save_profile.side_effect = lambda value: saved.update(deepcopy(value))
    service.acquire_agent_turn_lease.return_value = True
    service.renew_agent_turn_lease.return_value = True
    monkeypatch.setattr(main, 'authenticated_storage', lambda _: service)
    monkeypatch.setattr(supabase_routes, 'storage', lambda _: service)
    memory = MemoryStore()
    client = TestClient(main.create_app(memory))
    headers = {'X-Account-Id': PRINCIPALS['owner']}
    project = client.post('/v1/projects', headers=headers, json={'mode': 'self'}).json()
    memory.projects[project['id']]['supabase_owner_id'] = PRINCIPALS['owner']
    headers['Authorization'] = 'Bearer fixture-token'
    url = f'/v1/projects/{project["id"]}/photo-memories'
    response = client.put(url, headers=headers, json={'action': 'select', 'photo': PHOTO})
    assert response.status_code == 200
    assert saved['name'] == 'Storyteller' and 'other' in saved['photo_memories']
    assert client.get('/v1/user/profile').json()['photo_memories'][project['id']] == response.json()
    # A delayed generic workspace snapshot cannot undo photo commands.
    client.put('/v1/user/profile', json={'photo_memories': {}, 'name': 'New name'})
    assert saved['photo_memories'][project['id']]['selected'] == PHOTO['image_url']
    assert saved['name'] == 'New name'
    before = deepcopy(saved)
    service.acquire_agent_turn_lease.return_value = False
    assert client.put(url, headers=headers, json={'action': 'clear'}).status_code == 409
    assert saved == before
    service.acquire_agent_turn_lease.return_value = True
    service.save_profile.side_effect = httpx.ConnectError('fixture offline')
    assert client.put(url, headers=headers, json={'action': 'clear'}).status_code == 503
    assert 'photo_memories' not in memory.projects[project['id']]['profile']
    assert client.get(f'/v1/projects/{project["id"]}', headers=headers).json()['profile']['photo_memories'][project['id']]['selected'] == PHOTO['image_url']


@pytest.mark.parametrize('changes', [
    {'image_url': 'javascript:alert(1)'}, {'source_url': 'http://unsafe.example/photo'},
    {'original_url': 'https://user:password@images.example/photo'}, {'image_url': '/static/../secret'},
    {'title': 'x' * 1001},
])
def test_photo_commands_validate_reference_metadata(changes):
    client = TestClient(main.create_app(MemoryStore()))
    project = client.post('/v1/projects', json={'mode': 'self'}, headers={'X-Account-Id': 'owner'}).json()
    response = client.put(f'/v1/projects/{project["id"]}/photo-memories',
        headers={'X-Account-Id': 'owner'}, json={'action': 'select', 'photo': {**PHOTO, **changes}})
    assert response.status_code == 422


def test_unfavoriting_selected_photo_clears_the_cue_but_favoriting_another_does_not_select_it():
    profile, _ = update_photo_memory({}, 'p', PhotoMemoryInput(action='select', photo=PHOTO))
    profile, state = update_photo_memory(profile, 'p', PhotoMemoryInput(action='favorite', photo={**PHOTO,
        'image_url': 'https://images.example/another.jpg'}))
    assert state['selected'] == PHOTO['image_url'] and len(state['favorites']) == 2
    _, state = update_photo_memory(profile, 'p', PhotoMemoryInput(action='unfavorite', photo=PHOTO))
    assert state['selected'] is None and len(state['favorites']) == 1


@pytest.fixture
def principal_photo_storage(monkeypatch):
    profiles = {user: {} for user in ('owner', 'storyteller', 'member', 'outsider')}
    services = {}
    for user in profiles:
        service = Mock()
        service.user_id = PRINCIPALS[user]
        service.lifetime_rpc = Mock(side_effect=_unmapped_identity)
        service.user = {'id': service.user_id, 'app_metadata': {}}
        service.profile.side_effect = lambda user=user: deepcopy(profiles[user])
        service.save_profile.side_effect = lambda value, user=user: profiles[user].update(deepcopy(value))
        service.acquire_agent_turn_lease.return_value = True
        service.renew_agent_turn_lease.return_value = True
        service.release_agent_turn_lease.return_value = True
        services[user] = service
    monkeypatch.setattr(main, 'authenticated_storage', lambda token: services[token.removeprefix('Bearer ')])
    return profiles, services


def test_legacy_contaminated_project_profile_is_never_a_photo_read_fallback(principal_photo_storage):
    profiles, services = principal_photo_storage
    store = MemoryStore()
    with TestClient(main.create_app(store)) as client:
        owner = {'Authorization': 'Bearer owner'}
        storyteller = {'Authorization': 'Bearer storyteller'}
        project = client.post('/v1/projects', headers=owner, json={
            'mode': 'family', 'storyteller_account_id': PRINCIPALS['storyteller']}).json()['id']
        leaked, _ = update_photo_memory({}, 'private', PhotoMemoryInput(action='select', photo=PHOTO))
        leaked, _ = update_photo_memory(leaked, project, PhotoMemoryInput(action='select', photo=PHOTO))
        store.projects[project]['profile'].update(leaked)
        for headers in (owner, storyteller):
            response = client.get(f'/v1/projects/{project}', headers=headers)
            assert response.status_code == 200
            assert PHOTO['image_url'] not in response.text
            assert 'private' not in response.json()['profile'].get('photo_memories', {})
        services['storyteller'].profile.side_effect = httpx.ConnectError('fixture offline')
        response = client.get(f'/v1/projects/{project}', headers=storyteller)
        assert response.status_code == 503
        assert PHOTO['image_url'] not in response.text
