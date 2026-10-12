"""Offline calls through the actual handlers registered by recovery browsers.

Only Playwright transport is replaced. The fixtures still construct their real
FastAPI TestClient, auth principal, and API routing closures.
"""
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from apps.api import main
from apps.api.conversation_recovery import ConversationHistory, history_cursor
from browser_recovery_fixture import (RECOVERY_OWNER, NAVIGATION_USERS, save_navigation_turn, set_recovery_principal)
import test_account_recovery_browser as account_browser
import test_navigation_history_browser as navigation_browser


BASE = 'http://127.0.0.1:3139'


class Route:
    def __init__(self, path, *, method='GET', token='fixture-session', payload=None):
        self.request = SimpleNamespace(url=BASE + '/api/v1/memoir' + path, method=method,
            headers={**({'authorization': 'Bearer ' + token} if token else {}), 'content-type': 'application/json'},
            post_data=json.dumps(payload) if payload is not None else None)
        self.response = None

    def fulfill(self, **response):
        self.response = response

    @property
    def status(self):
        return self.response.get('status', 200)

    @property
    def body(self):
        return self.response.get('json') if 'json' in self.response else json.loads(self.response['body'])


class BrowserTransport:
    def __init__(self, visit=None):
        self.handlers = {}
        self.visit = visit

    def route(self, pattern, handler):
        self.handlers[pattern] = handler

    def request(self, path, **options):
        route = Route(path, **options)
        self.handlers['**/api/v1/memoir/**'](route)
        assert route.response is not None, 'Runtime route did not return a response'
        return route

    def add_cookies(self, cookies): pass
    def add_init_script(self, script): pass
    def on(self, *args): pass
    def new_context(self, **kwargs): return self
    def new_page(self): return self
    def close(self): pass
    def goto(self, url):
        assert url.startswith(BASE)
        self.visit(self)
        raise CapturedBrowserBoot


class CapturedBrowserBoot(Exception): pass


def replace_playwright(monkeypatch, module, transport):
    @contextmanager
    def playwright():
        yield SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kwargs: transport))
    monkeypatch.setattr(module, 'sync_playwright', playwright)
    monkeypatch.setenv('MEMOIR_BROWSER_URL', BASE)


@pytest.mark.parametrize('history_kind', ['memory', 'attachment'])
@pytest.mark.parametrize('adapter', ['missing', 'transferred-guest'])
def test_account_registered_route_returns_owned_authoritative_history(monkeypatch, history_kind, adapter):
    def visit(transport):
        restored = transport.request('/projects', method='POST', payload={'restore_project_id': 'project_saved'})
        assert restored.status == 201, restored.body
        response = transport.request('/user/projects/project_saved/history?limit=100')
        assert response.status == 200, response.body
        history = ConversationHistory.model_validate(response.body)
        assert history.project_id == 'project_saved' and history.policy_epoch == '1'
        assert history.next_cursor is None
        if history_kind == 'memory':
            assert [(item.narrator_text, item.reply) for item in history.items] == [
                ('My saved childhood', 'Tell me about the garden.')]
        else:
            assert history.items == []  # The separately owner-scoped attachment is still legacy.
            legacy = transport.request('/user/conversations').body
            assert legacy['items'][0]['project_id'] == 'project_saved'
            assert legacy['items'][0]['messages'][0]['text'] == 'My saved childhood'
        for path, method, token, status in [
            ('/user/projects/unknown-project/history?limit=100', 'GET', 'fixture-session', 404),
            ('/user/projects/project_saved/history?limit=100', 'GET', None, 401),
            ('/user/projects/project_saved/history?limit=100', 'GET', 'other-session', 401),
            ('/user/projects/project_saved/history?limit=100', 'POST', 'fixture-session', 405),
            ('/user/projects/project_saved/history?cursor=bad-cursor', 'GET', 'fixture-session', 422),
            ('/user/projects/project_saved/history?cursor=', 'GET', 'fixture-session', 422),
            ('/user/projects/project_saved/history?limit=1&limit=2', 'GET', 'fixture-session', 422),
        ]:
            denied = transport.request(path, method=method, token=token)
            assert denied.status == status and 'items' not in denied.body
        service = main.authenticated_storage('Bearer fixture-session')
        set_recovery_principal(service, guest=True)
        foreign = transport.request('/user/projects/project_saved/history?limit=100')
        assert foreign.status == 404 and 'items' not in foreign.body
        set_recovery_principal(service)
        assert transport.request('/user/projects/project_saved/history?limit=100').body == response.body
    transport = BrowserTransport(visit)
    replace_playwright(monkeypatch, account_browser, transport)
    with pytest.raises(CapturedBrowserBoot):
        account_browser.test_login_restores_original_project_and_serves_reviewed_sample(
            monkeypatch, 'saved-link', history_kind, adapter)


@pytest.fixture
def navigation_runtime(monkeypatch):
    transport = BrowserTransport()
    replace_playwright(monkeypatch, navigation_browser, transport)
    request = SimpleNamespace(param=(390, 844), node=SimpleNamespace(callspec=SimpleNamespace(id='phone')))
    fixture = navigation_browser.navigation_browser.__wrapped__(monkeypatch, request)
    values = next(fixture)
    try:
        yield transport, values[-1], values[2]
    finally:
        with pytest.raises(StopIteration): next(fixture)


@pytest.mark.parametrize('principal', ['guest', 'other'])
def test_navigation_registered_route_returns_only_its_projects_canonical_snapshot(navigation_runtime, principal):
    transport, _, _ = navigation_runtime
    token = 'fixture-' + principal
    created = transport.request('/projects', method='POST', token=token, payload={})
    assert created.status == 201, created.body
    project_id = created.body['id']
    for _ in range(2):  # The same fixture's reload/new-tab/reentry contract.
        response = transport.request('/user/projects/' + project_id + '/history?limit=100', token=token)
        assert response.status == 200, response.body
        history = ConversationHistory.model_validate(response.body)
        assert history.project_id == project_id and history.policy_epoch == '1'
        assert history.items == [] and history.next_cursor is None


@pytest.mark.parametrize('principal', ['guest', 'other'])
def test_navigation_saved_stream_turn_has_matching_canonical_source_and_receipt(navigation_runtime, principal):
    transport, client, _ = navigation_runtime
    token = 'fixture-' + principal
    project_id = transport.request('/projects', method='POST', token=token, payload={}).body['id']
    path = '/user/projects/' + project_id + '/history?limit=100'
    packet = {'project_id': project_id, 'client_turn_id': '60b00000-0000-4000-8000-000000000020',
              'conversation_text': 'A pending synthetic memory.'}
    # A result-only response is deliberately an unsaved local-cache scenario.
    result = transport.request('/agent/turn', method='POST', token=token, payload=packet)
    assert json.loads(result.response['body'])['type'] == 'result'
    assert transport.request(path, token=token).body['items'] == []
    row = save_navigation_turn(client.app.state.navigation_fixture_history, project_id, packet, 'A accepted partial reply.')
    for _ in range(2):
        history = ConversationHistory.model_validate(transport.request(path, token=token).body)
        assert len(history.items) == 1
        item = history.items[0]
        assert item.client_turn_id == packet['client_turn_id'] and item.server_turn_id == row['id']
        assert item.source_id == row['_source']['id'] and item.source_version == '1'
        assert item.source_status == 'active' and item.source_sequence == '1'
        assert item.narrator_text == packet['conversation_text'] and item.reply == 'A accepted partial reply.'
    other = 'other' if principal == 'guest' else 'guest'
    foreign = transport.request(path, token='fixture-' + other)
    assert foreign.status == 404 and 'pending synthetic memory' not in json.dumps(foreign.body)
    # Account switching back preserves only the original owner's saved row.
    assert transport.request(path, token=token).body['items'][0]['client_turn_id'] == packet['client_turn_id']
    row['_source'].update(version=2, text='The corrected original memory.')
    corrected = transport.request(path, token=token).body['items'][0]
    assert corrected['narrator_text'] == 'The corrected original memory.' and corrected['reply'] is None
    row['_source']['status'] = 'withdrawn'
    withdrawn = transport.request(path, token=token).body['items'][0]
    assert withdrawn['narrator_text'] is None and withdrawn['reply'] is None


@pytest.mark.parametrize('path,method,token,status', [
    ('/user/projects/unknown-project/history?limit=100', 'GET', 'fixture-guest', 404),
    ('/user/projects', 'GET', 'fixture-guest', 404),
    ('/user/projects/{project}/history?limit=100', 'GET', None, 401),
    ('/user/projects/{project}/source', 'GET', 'fixture-guest', 404),
    ('/user/projects/{project}/history?limit=100', 'POST', 'fixture-guest', 405),
    ('/user/projects/{project}/history?limit=0', 'GET', 'fixture-guest', 422),
    ('/user/projects/{project}/history?limit=101', 'GET', 'fixture-guest', 422),
    ('/user/projects/{project}/history?limit=10&limit=10', 'GET', 'fixture-guest', 422),
    ('/user/projects/{project}/history?cursor=', 'GET', 'fixture-guest', 422),
    ('/user/projects/{project}/history?unknown=1', 'GET', 'fixture-guest', 422),
    ('/user/projects/{project}/history?cursor=unissued', 'GET', 'fixture-guest', 422),
    ('/user/projects/{project}/history?limit=100', 'GET', 'unknown-session', 401),
    ('/user/projects/{project}/history?limit=100', 'GET', 'fixture-other', 404),
])
def test_navigation_history_runtime_rejects_unknown_scope_method_and_cursor(navigation_runtime, path, method, token, status):
    transport, _, _ = navigation_runtime
    project_id = transport.request('/projects', method='POST', token='fixture-guest', payload={}).body['id']
    response = transport.request(path.format(project=project_id), method=method, token=token)
    assert response.status == status, response.body
    assert 'items' not in response.body


def test_navigation_history_cursor_is_owner_project_scoped_and_known_to_this_ledger(navigation_runtime):
    transport, client, _ = navigation_runtime
    project_id = transport.request('/projects', method='POST', token='fixture-guest', payload={}).body['id']
    path = '/user/projects/' + project_id + '/history?limit=1'
    packet = {'project_id': project_id, 'client_turn_id': '60b00000-0000-4000-8000-000000000020',
              'conversation_text': 'The first saved memory.'}
    first = save_navigation_turn(client.app.state.navigation_fixture_history, project_id, packet, 'First saved reply.')
    second = {**first, 'id': '60b00000-0000-4000-8000-000000000030',
              'client_turn_id': '60b00000-0000-4000-8000-000000000031',
              'created_at': '2026-10-07T12:01:00+00:00', 'content': 'Storyteller: Second memory.\nMemory Spark: Second reply.',
              '_source': {**first['_source'], 'id': '60b00000-0000-4000-8000-000000000032',
                          'client_turn_id': '60b00000-0000-4000-8000-000000000031', 'text': 'Second memory.', 'sequence': 2}}
    client.app.state.navigation_fixture_history[project_id].append(second)
    latest = transport.request(path, token='fixture-guest').body
    assert latest['items'][0]['server_turn_id'] == second['id'] and latest['next_cursor']
    earlier = transport.request(path + '&cursor=' + latest['next_cursor'], token='fixture-guest').body
    assert earlier['items'][0]['server_turn_id'] == first['id'] and earlier['next_cursor'] is None
    for owner, project, row in [
        (NAVIGATION_USERS['other'], project_id, second),
        (NAVIGATION_USERS['guest'], 'foreign-project', second),
        (NAVIGATION_USERS['guest'], project_id, {**second, 'id': '60b00000-0000-4000-8000-000000000099'}),
    ]:
        forged = history_cursor(owner, project, row)
        response = transport.request(path + '&cursor=' + forged, token='fixture-guest')
        assert response.status == 422 and 'items' not in response.body
