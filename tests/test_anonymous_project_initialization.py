"""Anonymous project creation owns identity without initializing a mode preference."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from apps.api import agent_routes, main
from apps.api.agent_storage import UserStorage
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
        if path == '/rest/v1/rpc/read_lifetime_project_identity':
            return httpx.Response(200, content='null', headers={'Content-Type':'application/json'})
        payload = json.loads(request.content)
        if path == '/rest/v1/rpc/resolve_lifetime_conversation':
            if unavailable:
                return httpx.Response(503, json={'message': 'Synthetic outage'})
            project_id='memoir-'+owner[:8]
            projects.add((owner,project_id))
            return httpx.Response(200, json={'outcome':'resolved','schema_version':1,'owner_id':owner,
                'conversation_id':'33333333-3333-4333-8333-333333333333','product':'memoir','project_id':project_id})
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


def test_anonymous_project_needs_no_phase_before_first_answer(anonymous_project):
    client, _, projects, calls, _ = anonymous_project
    headers = {'Authorization': 'Bearer guest', 'Idempotency-Key': 'start'}
    created = client.post('/v1/projects', headers=headers, json={})
    assert created.status_code == 201, created.text
    project_id = created.json()['id']
    phase = client.get(f'/v1/agent/projects/{project_id}/conversation-phase', headers=headers)
    assert phase.status_code == 404, phase.text
    assert projects == {(GUEST, project_id)}
    assert client.post('/v1/projects', headers=headers, json={}).json()['id'] == project_id
    assert calls.count('/rest/v1/rpc/resolve_lifetime_conversation') == 2
    assert client.get(f'/v1/agent/projects/{project_id}/conversation-phase',
                      headers={'Authorization': 'Bearer other'}).status_code == 404
    assert not any('accept_' in path for path in calls)


def test_persistence_failure_does_not_publish_a_local_project(anonymous_project):
    client, store, projects, _, unavailable = anonymous_project
    unavailable.append(True)
    response = client.post('/v1/projects', headers={'Authorization': 'Bearer guest'}, json={})
    assert response.status_code == 503, response.text
    assert not store.projects and not projects
