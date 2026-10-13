"""Anonymous project creation must precede the first phase read and narration."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from apps.api import agent_routes, main
from apps.api.agent_storage import UserStorage
from apps.api.conversation_phase import PhaseState
from apps.api.store import MemoryStore


GUEST = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'


@pytest.fixture
def anonymous_project(monkeypatch):
    projects = set()
    calls = []
    unavailable = []

    def rest(request):
        owner = GUEST if request.headers['Authorization'] == 'Bearer guest' else OTHER
        path = request.url.path
        calls.append(path)
        if path == '/auth/v1/user':
            return httpx.Response(200, json={'id': owner, 'is_anonymous': True})
        if path == '/rest/v1/user_profile' and request.method == 'GET':
            return httpx.Response(200, json=[])
        payload = json.loads(request.content)
        key = owner, payload['p_project_id']
        if path == '/rest/v1/rpc/ensure_user_memoir_project':
            if unavailable:
                return httpx.Response(503, json={'message': 'Synthetic outage'})
            projects.add(key)
            return httpx.Response(200, json=None)
        if path == '/rest/v1/rpc/read_user_conversation_phase':
            if key not in projects:
                return httpx.Response(403, json={'code': '42501', 'message': 'project unavailable'})
            return httpx.Response(200, json=PhaseState().model_dump(mode='json'))
        pytest.fail(f'Unexpected persistence operation: {path}')

    def storage(authorization):
        return UserStorage('https://synthetic.invalid', 'synthetic-public-key',
                           authorization.removeprefix('Bearer '),
                           client=httpx.Client(transport=httpx.MockTransport(rest)))

    monkeypatch.setattr(main, 'authenticated_storage', storage)
    monkeypatch.setattr(agent_routes, 'authenticated_storage', storage)
    store = MemoryStore()
    with TestClient(main.create_app(store)) as client:
        yield client, store, projects, calls, unavailable


def test_anonymous_project_has_owned_phase_before_first_answer(anonymous_project):
    client, _, projects, calls, _ = anonymous_project
    headers = {'Authorization': 'Bearer guest', 'Idempotency-Key': 'start'}
    created = client.post('/v1/projects', headers=headers, json={})
    assert created.status_code == 201, created.text
    project_id = created.json()['id']
    phase = client.get(f'/v1/agent/projects/{project_id}/conversation-phase', headers=headers)
    assert phase.status_code == 200, phase.text
    assert phase.json()['conversation_phase']['phase'] == 'comfort'
    assert projects == {(GUEST, project_id)}
    assert client.post('/v1/projects', headers=headers, json={}).json()['id'] == project_id
    assert calls.count('/rest/v1/rpc/ensure_user_memoir_project') == 1
    assert client.get(f'/v1/agent/projects/{project_id}/conversation-phase',
                      headers={'Authorization': 'Bearer other'}).status_code == 403
    assert not any('accept_' in path for path in calls)


def test_persistence_failure_does_not_publish_a_local_project(anonymous_project):
    client, store, projects, _, unavailable = anonymous_project
    unavailable.append(True)
    response = client.post('/v1/projects', headers={'Authorization': 'Bearer guest'}, json={})
    assert response.status_code == 503, response.text
    assert not store.projects and not projects
