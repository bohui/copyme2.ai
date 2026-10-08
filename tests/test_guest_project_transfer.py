"""A successful guest attachment must leave its interview usable after login."""
from copy import deepcopy
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from apps.api import main, supabase_routes
from apps.api.store import MemoryStore

GUEST = '11111111-1111-4111-8111-111111111111'
OWNER = '22222222-2222-4222-8222-222222222222'
OTHER = '33333333-3333-4333-8333-333333333333'


@pytest.fixture
def transfer(monkeypatch):
    services = {}
    attached = {}
    for user in ('guest', 'owner', 'other'):
        user_id = {'guest': GUEST, 'owner': OWNER, 'other': OTHER}[user]
        service = Mock(user_id=user_id, is_anonymous=user == 'guest')
        service.user = {'id': user_id, 'is_anonymous': user == 'guest'}
        service.profile.return_value = {'name': f'{user} narrator'}

        def request(method, path, *, user=user, **kwargs):
            if path.endswith('/prepare_guest_conversation_transfer'):
                attached['project_id'] = kwargs['json']['p_project_id']
                return Mock(json=lambda: {'prepared': True})
            if path.endswith('/attach_guest_conversation'):
                attached['owner'] = user
                return Mock(json=lambda: {'attached': True, 'conversation_id': 'attachment',
                    'guest_user_id': GUEST, 'project_id': attached['project_id'], 'storage_objects': []})
            if method == 'GET' and path.endswith('/user_conversation_attachment') and attached.get('owner') == user:
                return Mock(json=lambda: [{'project_id': attached['project_id'],
                    'workspace': {'guest_user_id': GUEST}}])
            return Mock(json=lambda: [])

        service.request.side_effect = request
        services[user] = service

    def authenticated(authorization):
        user = (authorization or '').removeprefix('Bearer ')
        if user not in services:
            raise HTTPException(401, 'Invalid session')
        return services[user]

    monkeypatch.setattr(main, 'authenticated_storage', authenticated)
    monkeypatch.setattr(supabase_routes, 'storage', authenticated)
    monkeypatch.setattr(supabase_routes, '_queue_if_configured', lambda: None)
    store = MemoryStore()
    with TestClient(main.create_app(store)) as client:
        yield client, store, attached


def test_login_attachment_preserves_the_interview_and_authorizes_its_new_owner(transfer):
    client, store, _ = transfer
    guest = {'Authorization': 'Bearer guest'}
    owner = {'Authorization': 'Bearer owner'}
    created = client.post('/v1/projects', headers=guest, json={'mode': 'self'}).json()
    project_id = created['id']
    path = f'/v1/projects/{project_id}'
    client.patch(path, headers=guest, json={'profile': {'birth_place': 'Guest hometown'}})
    before = store.projects[project_id]
    assert client.post('/v1/user/conversation-transfer', headers=guest, json={
        'token': 'ab' * 32, 'project_id': project_id, 'messages': [],
    }).status_code == 200
    assert client.post('/v1/user/conversation-transfer/attach', headers=owner,
                       json={'token': 'ab' * 32}).status_code == 200

    response = client.get(path, headers=owner)
    assert response.status_code == 200, response.json()
    assert response.json()['owner_id'] == OWNER
    assert response.json()['storyteller_id'] == OWNER
    assert response.json()['profile']['birth_place'] == 'Guest hometown'
    assert store.projects[project_id] is before
    assert client.get(path + '/journey', headers=owner).status_code == 200
    assert client.post('/v1/projects', headers=owner,
                       json={'mode': 'self', 'restore_project_id': project_id}).status_code == 201
    assert client.get(path, headers=guest).status_code == 403
    assert client.get(path, headers={'Authorization': 'Bearer other'}).status_code == 403
    assert client.get(path).status_code == 401
    assert list(store.projects) == [project_id]
    revision = before['revision']
    assert client.post('/v1/user/conversation-transfer/attach', headers=owner,
                       json={'token': 'ab' * 32}).status_code == 200
    assert before['revision'] == revision


def test_recovery_repairs_an_attachment_completed_before_local_ownership_was_updated(transfer):
    client, store, attached = transfer
    created = client.post('/v1/projects', headers={'Authorization': 'Bearer guest'}, json={}).json()
    project_id = created['id']
    # Durable transfer committed before this code was installed (or before a crash).
    attached.update(owner='owner', project_id=project_id)
    assert client.get(f'/v1/projects/{project_id}', headers={'Authorization': 'Bearer owner'}).status_code == 403
    response = client.post('/v1/projects', headers={'Authorization': 'Bearer owner'},
                           json={'mode': 'self', 'restore_project_id': project_id})
    assert response.status_code == 201, response.json()
    assert response.json()['id'] == project_id
    assert store.projects[project_id]['supabase_owner_id'] == OWNER
    assert client.get(f'/v1/projects/{project_id}', headers={'Authorization': 'Bearer owner'}).status_code == 200
    assert client.get(f'/v1/projects/{project_id}', headers={'Authorization': 'Bearer guest'}).status_code == 403


@pytest.mark.parametrize('conflict', ['another-owner', 'family', 'unbound', 'shared'])
def test_attachment_cannot_reassign_an_unrelated_or_shared_local_project(transfer, conflict):
    client, store, attached = transfer
    project_id = client.post('/v1/projects', headers={'Authorization': 'Bearer guest'}, json={}).json()['id']
    attached['project_id'] = project_id
    project = store.projects[project_id]
    if conflict == 'another-owner':
        project.update(supabase_owner_id=OTHER, owner_id=OTHER, storyteller_id=OTHER,
                       members={OTHER: project['members'][GUEST]})
    elif conflict == 'family':
        project['mode'] = 'family'
    elif conflict == 'unbound':
        del project['supabase_owner_id']
    else:
        project['members'][OTHER] = {'role': 'contributor', 'capabilities': ['record']}
    before = deepcopy(project)
    response = client.post('/v1/user/conversation-transfer/attach', headers={'Authorization': 'Bearer owner'},
                           json={'token': 'ab' * 32})
    assert response.status_code == 409
    assert project == before
    recovery = client.post('/v1/projects', headers={'Authorization': 'Bearer owner'},
                           json={'restore_project_id': project_id})
    assert recovery.status_code == (409 if conflict == 'unbound' else 403)
    assert project == before
