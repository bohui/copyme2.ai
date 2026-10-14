"""HTTP authority surface using synthetic external Auth/PostgREST responses."""
import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI

from apps.api.formal_memoir_routes import router

OWNER = '11111111-1111-4111-8111-111111111111'
RUN = '44444444-4444-4444-8444-444444444444'
EDITION = '55555555-5555-4555-8555-555555555555'
REQUEST = '66666666-6666-4666-8666-666666666666'


@pytest.fixture
def surface(monkeypatch):
    monkeypatch.setenv('SUPABASE_URL', 'https://synthetic.invalid')
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY', 'synthetic-public-key')
    observations = []
    replies = {'begin_formal_memoir': {'schema_version': 1, 'run_id': RUN, 'status': 'pending'}}

    def remote(request):
        assert request.url.host == 'synthetic.invalid'
        if request.url.path == '/auth/v1/user':
            assert request.headers['Authorization'] == 'Bearer synthetic-token'
            return httpx.Response(200, json={'id': OWNER, 'is_anonymous': False})
        name = request.url.path.removeprefix('/rest/v1/rpc/')
        assert request.headers['Authorization'] == ('Bearer synthetic-service' if name == 'claim_formal_memoir'
                                                   else 'Bearer synthetic-token')
        body = json.loads(request.content)
        observations.append((name, body))
        reply = replies[name]
        if isinstance(reply, httpx.Response):
            return reply
        return httpx.Response(200, json=reply)

    original = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kw: original(transport=httpx.MockTransport(remote), **kw))
    original_async = httpx.AsyncClient
    def async_client(**kwargs):
        return original_async(**{'transport': httpx.MockTransport(remote), **kwargs})
    monkeypatch.setattr(httpx, 'AsyncClient', async_client)
    app = FastAPI()
    app.include_router(router, prefix='/v1/agent')

    def request(method, path, *, signed=True, headers=None, **kwargs):
        async def send():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                auth = {'Authorization': 'Bearer synthetic-token'} if signed else {}
                return await client.request(method, path, headers={**auth, **(headers or {})}, **kwargs)
        return asyncio.run(send())
    return request, observations, replies


def test_begin_requires_authentication_and_uses_server_scope(surface):
    request, observations, _ = surface
    body = {'expected_phase_revision': 3, 'expected_revision': 0, 'request_id': REQUEST}
    path = '/v1/agent/projects/project/formal-memoir'
    assert request('POST', path, json=body, signed=False).status_code == 401
    response = request('POST', path, json=body)
    assert response.status_code == 202
    assert response.json() == {'schema_version': 1, 'run_id': RUN, 'status': 'pending'}
    assert response.headers['cache-control'] == 'no-store'
    assert observations == [('begin_formal_memoir', {
        'p_project_id': 'project', 'p_expected_phase_revision': 3,
        'p_expected_revision': 0, 'p_request_id': REQUEST})]


def test_exact_edition_consent_and_eligibility_remain_separate_from_runtime(surface):
    request, observations, replies = surface
    replies.update({
        'set_story_game_consent': {'revision': 2, 'status': 'active', 'edition_id': EDITION},
        'read_story_game_eligibility': {'authority_eligible': True, 'available': False,
                                      'reasons': ['runtime_unavailable'], 'consent_revision': 2},
        'read_formal_memoir_status': {'status': 'completed', 'edition_id': EDITION, 'revision': 1}})
    root = '/v1/agent/projects/project'
    response = request('PUT', root + '/story-game/consent', json={
        'edition_id': EDITION, 'expected_digest': 'a' * 64, 'expected_revision': 1, 'action': 'grant'})
    assert response.status_code == 200
    assert response.json()['status'] == 'active'
    assert observations[-1] == ('set_story_game_consent', {
        'p_project_id': 'project', 'p_edition_id': EDITION, 'p_expected_digest': 'a' * 64,
        'p_expected_revision': 1, 'p_action': 'grant'})
    eligible = request('GET', root + '/story-game/eligibility')
    assert eligible.status_code == 200
    assert eligible.json()['authority_eligible'] is True
    assert eligible.json()['available'] is False
    assert eligible.headers['cache-control'] == 'no-store'
    assert request('GET', root + '/formal-memoir').json()['edition_id'] == EDITION


@pytest.mark.parametrize('extra', [
    {'composition_complete': True}, {'owner_id': OWNER}, {'chapters': []},
    {'expected_revision': True}, {'expected_phase_revision': -1}])
def test_browser_cannot_supply_authority_or_content(surface, extra):
    request, observations, _ = surface
    response = request('POST', '/v1/agent/projects/project/formal-memoir', json={
        'expected_phase_revision': 3, 'expected_revision': 0, 'request_id': REQUEST, **extra})
    assert response.status_code == 422
    assert observations == []


@pytest.mark.parametrize('code,status,expected', [('40001', 400, 409), ('PT409', 409, 409), ('42501', 400, 403), ('XX000', 500, 503)])
def test_database_errors_do_not_leak_private_details(surface, code, status, expected):
    request, _, replies = surface
    replies['begin_formal_memoir'] = httpx.Response(status, json={'code': code, 'message': 'private synthetic testimony'})
    response = request('POST', '/v1/agent/projects/project/formal-memoir', json={
        'expected_phase_revision': 3, 'expected_revision': 0, 'request_id': REQUEST})
    assert response.status_code == expected
    assert 'private synthetic testimony' not in response.text


def test_expected_privacy_block_is_distinct_from_transient_storage_failure(surface):
    request, _, replies = surface
    replies['begin_formal_memoir'] = httpx.Response(400, json={
        'code': '55000', 'message': 'FORMAL_PRIVACY_REVIEW_REQUIRED'})
    response = request('POST', '/v1/agent/projects/project/formal-memoir', json={
        'expected_phase_revision': 3, 'expected_revision': 0, 'request_id': REQUEST})
    assert response.status_code == 409
    assert response.headers['x-error-code'] == 'FORMAL_PRIVACY_REVIEW_REQUIRED'
    assert response.json()['detail'] == 'Review memoir privacy choices before composing.'


def test_worker_advance_requires_existing_service_secret(surface, monkeypatch):
    request, observations, _ = surface
    monkeypatch.setenv('MEMORY_SPARK_CODEX_WORKER_SECRET', 'synthetic-internal-secret')
    response = request('POST', f'/v1/agent/internal/formal-memoirs/{RUN}/advance')
    assert response.status_code == 401
    assert observations == []


def test_formal_workflow_is_registered_in_product_router(surface):
    from apps.api.agent_routes import router as product_router
    app = FastAPI()
    app.include_router(product_router)
    async def call():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            return await client.get('/v1/agent/projects/project/formal-memoir')
    assert asyncio.run(call()).status_code == 401


def test_authorized_advance_returns_only_the_persisted_result(surface, monkeypatch):
    request, observations, replies = surface
    monkeypatch.setenv('MEMORY_SPARK_CODEX_WORKER_SECRET', 'synthetic-internal-secret')
    monkeypatch.setenv('SUPABASE_SECRET_KEY', 'synthetic-service')
    replies['claim_formal_memoir'] = {'status': 'completed', 'edition_id': EDITION, 'revision': 1}
    response = request('POST', f'/v1/agent/internal/formal-memoirs/{RUN}/advance',
                       headers={'X-Codex-Worker-Secret': 'synthetic-internal-secret'})
    assert response.status_code == 200
    assert response.json() == replies['claim_formal_memoir']
    assert observations == [('claim_formal_memoir', {'p_run_id': RUN, 'p_lease_seconds': 300})]
