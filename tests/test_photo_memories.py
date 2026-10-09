from copy import deepcopy
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from apps.api import main, supabase_routes
from apps.api.codex_runtime import build_conversation_system_prompt
from apps.api.photo_memories import PhotoMemoryInput, update_photo_memory
from apps.api.store import MemoryStore


PHOTO = {'asset_id': 'street', 'image_url': 'https://images.example/street.jpg',
         'source_url': 'https://archive.example/street', 'title': 'Old street',
         'date_expression': '1983', 'attribution': 'Public archive', 'place': 'Chengde'}


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
    service.user_id = 'owner'
    service.profile.side_effect = lambda: deepcopy(saved)
    service.save_profile.side_effect = lambda value: saved.update(deepcopy(value))
    service.acquire_agent_turn_lease.return_value = True
    service.renew_agent_turn_lease.return_value = True
    monkeypatch.setattr(main, 'authenticated_storage', lambda _: service)
    monkeypatch.setattr(supabase_routes, 'storage', lambda _: service)
    memory = MemoryStore()
    client = TestClient(main.create_app(memory))
    headers = {'X-Account-Id': 'owner'}
    project = client.post('/v1/projects', headers=headers, json={'mode': 'self'}).json()
    memory.projects[project['id']]['supabase_owner_id'] = 'owner'
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


def test_photo_cue_enters_only_its_project_prompt_and_clear_stops_photo_followups():
    profile, _ = update_photo_memory({}, 'current', PhotoMemoryInput(action='select', photo=PHOTO))
    profile, _ = update_photo_memory(profile, 'other', PhotoMemoryInput(action='select', photo={**PHOTO,
        'title': 'Unrelated interview', 'image_url': 'https://images.example/other.jpg'}))
    prompt = build_conversation_system_prompt('(none)', profile, project_id='current')
    assert 'Old street' in prompt and 'Chengde' in prompt
    assert 'Unrelated interview' not in prompt
    assert 'Only metadata is supplied' in prompt
    assert 'does not establish that the storyteller was there' in prompt
    profile, _ = update_photo_memory(profile, 'current', PhotoMemoryInput(action='clear'))
    assert 'Old street' not in build_conversation_system_prompt('(none)', profile, project_id='current')
    assert 'Old street' not in build_conversation_system_prompt('(none)', profile)


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
        service.user_id = user
        service.user = {'id': user, 'app_metadata': {}}
        service.profile.side_effect = lambda user=user: deepcopy(profiles[user])
        service.save_profile.side_effect = lambda value, user=user: profiles[user].update(deepcopy(value))
        service.acquire_agent_turn_lease.return_value = True
        service.renew_agent_turn_lease.return_value = True
        service.release_agent_turn_lease.return_value = True
        services[user] = service
    monkeypatch.setattr(main, 'authenticated_storage', lambda token: services[token.removeprefix('Bearer ')])
    return profiles, services


def test_authenticated_family_photos_belong_to_principal_and_project_after_reload(tmp_path, principal_photo_storage):
    profiles, services = principal_photo_storage
    path = str(tmp_path / 'projects.json')
    store = MemoryStore(persistence_path=path)
    headers = lambda user: {'Authorization': f'Bearer {user}'}
    private_photo = {**PHOTO, 'title': 'PRIVATE OTHER PROJECT', 'image_url': 'https://images.example/private.jpg'}
    storyteller_photo = {**PHOTO, 'title': 'STORYTELLER CUE', 'image_url': 'https://images.example/storyteller.jpg'}
    with TestClient(main.create_app(store)) as client:
        private = client.post('/v1/projects', headers=headers('owner'), json={'mode': 'self'}).json()['id']
        shared = client.post('/v1/projects', headers=headers('owner'), json={
            'mode': 'family', 'storyteller_account_id': 'storyteller'}).json()['id']
        store.projects[shared]['members']['member'] = {'role': 'collaborator', 'capabilities': ['read']}
        store.save()
        for project, actor, photo in [(private, 'owner', private_photo), (shared, 'owner', PHOTO),
                                       (shared, 'storyteller', storyteller_photo)]:
            response = client.put(f'/v1/projects/{project}/photo-memories', headers=headers(actor),
                                  json={'action': 'select', 'photo': photo})
            assert response.status_code == 200
            if project == shared and actor == 'owner':
                # Reproduce the original private-A/shared-B leak before a
                # second principal gets a chance to overwrite the bad cache.
                view = client.get(f'/v1/projects/{shared}', headers=headers('storyteller'))
                assert view.status_code == 200
                assert 'PRIVATE OTHER PROJECT' not in view.text
                assert PHOTO['image_url'] not in view.text
        before = deepcopy(profiles)
        assert profiles['owner']['photo_memories'][shared]['selected'] == PHOTO['image_url']
        assert profiles['storyteller']['photo_memories'][shared]['selected'] == storyteller_photo['image_url']
        for actor in ('member', 'outsider'):
            assert client.put(f'/v1/projects/{shared}/photo-memories', headers=headers(actor),
                              json={'action': 'clear'}).status_code == 403
        for h, status in [({}, 401), ({'X-Account-Id': 'owner'}, 401),
                          (headers('outsider'), 403), ({**headers('outsider'), 'X-Account-Id': 'owner'}, 403)]:
            assert client.put(f'/v1/projects/{private}/photo-memories', headers=h,
                              json={'action': 'clear'}).status_code == status
        assert profiles == before
    # Each response is a view of the caller's authoritative account profile;
    # reloading the project store cannot publish another member's cached cue.
    reloaded = MemoryStore(persistence_path=path)
    with TestClient(main.create_app(reloaded)) as client:
        for actor, photo in [('owner', PHOTO), ('storyteller', storyteller_photo), ('member', None)]:
            for suffix in ('', '/journey'):
                response = client.get(f'/v1/projects/{shared}{suffix}', headers=headers(actor))
                assert response.status_code == 200
                assert 'PRIVATE OTHER PROJECT' not in response.text
                memories = response.json()['profile'].get('photo_memories', {})
                assert set(memories) <= {shared}
                actual = memories.get(shared, {'favorites': [], 'selected': None})
                assert actual['selected'] == (photo['image_url'] if photo else None)
                if photo:
                    assert actual['favorites'][0]['title'] == photo['title']
            assert client.get(f'/v1/projects/{private}', headers=headers(actor)).status_code == (200 if actor == 'owner' else 403)
        assert 'photo_memories' not in reloaded.projects[shared]['profile']
        assert 'photo_memories' not in reloaded.projects[private]['profile']
        assert 'Old street' in build_conversation_system_prompt('(none)', profiles['owner'], project_id=shared)
        assert 'PRIVATE OTHER PROJECT' not in build_conversation_system_prompt('(none)', profiles['owner'], project_id=shared)
        assert 'STORYTELLER CUE' in build_conversation_system_prompt('(none)', profiles['storyteller'], project_id=shared)
        assert 'PRIVATE OTHER PROJECT' not in build_conversation_system_prompt('(none)', profiles['storyteller'], project_id=shared)
        assert 'Old street' not in build_conversation_system_prompt('(none)', profiles['member'], project_id=shared)
        # Clearing one principal's selection must not clear another's selection.
        cleared = client.put(f'/v1/projects/{shared}/photo-memories', headers=headers('storyteller'),
                             json={'action': 'clear'})
        assert cleared.status_code == 200 and cleared.json()['selected'] is None
        owner_view = client.get(f'/v1/projects/{shared}', headers=headers('owner')).json()
        assert owner_view['profile']['photo_memories'][shared]['selected'] == PHOTO['image_url']


def test_legacy_contaminated_project_profile_is_never_a_photo_read_fallback(principal_photo_storage):
    profiles, services = principal_photo_storage
    store = MemoryStore()
    with TestClient(main.create_app(store)) as client:
        owner = {'Authorization': 'Bearer owner'}
        storyteller = {'Authorization': 'Bearer storyteller'}
        project = client.post('/v1/projects', headers=owner, json={
            'mode': 'family', 'storyteller_account_id': 'storyteller'}).json()['id']
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
