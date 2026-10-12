"""Offline contracts for the workspace browser's controlled turn/history boundary."""
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from apps.api.conversation_recovery import ConversationHistory
from apps.api.main import create_app
from browser_workspace_history import WorkspaceHistory, FixtureRejected, mock_workspace_turn


AUTH = {'authorization': 'Bearer browser-test-token'}
OWNER = 'demo-storyteller'


def project(project_id='project-one', **changes):
    return {'id': project_id, 'owner_id': OWNER, 'storyteller_id': OWNER, 'mode': 'self',
            'requires_supabase_auth': False, **changes}


def request(project_id='project-one', **changes):
    return SimpleNamespace(method='POST', url='http://fixture/api/v1/memoir/agent/turn',
        headers=dict(AUTH), post_data_json={'project_id': project_id, 'client_turn_id': str(uuid4()),
            'source_kind': 'narrator_chat', 'language': 'en-AU',
            'conversation_text': 'I grew up in Chengde. 我记得街道。',
            'text': 'Assembled prompt with photo/news context and instructions.', **changes})


def history_request(project_id='project-one', query='limit=100', **changes):
    return SimpleNamespace(method='GET',
        url=f'http://fixture/api/v1/memoir/user/projects/{project_id}/history?{query}',
        headers=dict(AUTH), **changes)


@pytest.fixture
def ledger():
    value = WorkspaceHistory()
    value.register_project(project())
    return value


def test_history_is_recorded_from_exact_narrator_text_and_receipts(ledger):
    req = request()
    reply = {'reply': 'Which street?', 'profile_updates': {'avatar_style': 'female'},
             'historical_context': None, 'place_journey': {'place': 'Chengde'}}
    events = ledger.turn_events(req, reply)
    assert [event['type'] for event in events] == ['source_accepted', 'conversation_saved', 'workspace_update', 'result']
    accepted, saved, workspace, result = [event['data'] for event in events]
    assert workspace == {'profile_updates': reply['profile_updates'], 'place_journey': reply['place_journey']}
    assert accepted['client_turn_id'] == req.post_data_json['client_turn_id']
    assert accepted['accepted_source_id'] == saved['accepted_source_id']
    assert saved['conversation_saved'] is True
    assert saved['profile_updates'] == reply['profile_updates']
    assert result == saved
    history = ConversationHistory.model_validate(ledger.history(history_request()))
    item, = history.items
    assert item.narrator_text == req.post_data_json['conversation_text']
    assert item.reply == reply['reply']
    assert item.client_turn_id == accepted['client_turn_id']
    assert item.source_id == accepted['accepted_source_id']
    assert item.server_turn_id == saved['server_turn_id']
    assert item.source_sequence == item.conversation_sequence == '1'
    assert item.source_version == '1'
    assert history.next_cursor is None
    assert req.post_data_json['text'] not in history.model_dump_json()
    reply['reply'] = 'mutated'
    saved['reply'] = 'mutated'
    assert ledger.history(history_request())['items'][0]['reply'] == 'Which street?'


def test_receipts_are_idempotent_and_cannot_rebind_existing_turn(ledger):
    req = request()
    events = ledger.turn_events(req, {'reply': 'Original answer'})
    assert ledger.turn_events(req, {'reply': 'Uncommitted later answer'}) == events
    assert len(ledger.history(history_request())['items']) == 1
    for change in [{'conversation_text': 'Different evidence'}, {'source_kind': 'narrator_transcript'},
                   {'language': 'zh-CN'}, {'project_id': 'project-two'}]:
        ledger.register_project(project('project-two'))
        forged = deepcopy(req)
        forged.post_data_json.update(change)
        with pytest.raises(FixtureRejected):
            ledger.turn_events(forged, {'reply': 'Must not replace receipt'})
    assert ledger.history(history_request())['items'][0]['reply'] == 'Original answer'


@pytest.mark.parametrize('changes', [
    {'owner_id': 'someone-else'}, {'storyteller_id': 'someone-else'}, {'mode': 'family'},
    {'requires_supabase_auth': True}, {'id': '../other'},
])
def test_project_registration_rejects_foreign_or_unsupported_scope(changes):
    ledger = WorkspaceHistory()
    with pytest.raises(FixtureRejected):
        ledger.register_project(project(**changes))
    with pytest.raises(FixtureRejected):
        ledger.history(history_request())


@pytest.mark.parametrize('changes', [
    {'project_id': 'unknown'}, {'client_turn_id': 'bad'}, {'conversation_text': None},
    {'conversation_text': ''}, {'source_kind': 'news'}, {'uploaded_photo_ids': ['unbound-photo']},
])
def test_turn_rejects_unbound_evidence_without_recording(ledger, changes):
    with pytest.raises(FixtureRejected):
        ledger.turn_events(request(**changes), {'reply': 'No receipt'})
    assert ledger.history(history_request())['items'] == []


@pytest.mark.parametrize('operation', ['turn', 'history'])
@pytest.mark.parametrize('headers', [{}, {'authorization': 'Bearer another-owner'},
    {'authorization': 'Bearer browser-test-token', 'x-account-id': 'someone-else'}])
def test_controlled_authority_rejects_missing_or_foreign_owner(ledger, operation, headers):
    req = request() if operation == 'turn' else history_request()
    req.headers = headers
    with pytest.raises(FixtureRejected):
        ledger.turn_events(req, {'reply': 'No receipt'}) if operation == 'turn' else ledger.history(req)


@pytest.mark.parametrize('query', ['limit=100&cursor=forged', 'limit=0', 'limit=101',
    'limit=100&limit=2', 'limit=100&owner_id=other'])
def test_history_rejects_unknown_cursor_or_query(ledger, query):
    with pytest.raises(FixtureRejected):
        ledger.history(history_request(query=query))


def test_history_pages_are_ordered_and_cursors_are_project_scoped(ledger):
    ledger.register_project(project('project-two'))
    for text in ['first', 'second', 'third']:
        ledger.turn_events(request(conversation_text=text), {'reply': f'after {text}'})
    latest = ledger.history(history_request(query='limit=2'))
    assert [item['narrator_text'] for item in latest['items']] == ['second', 'third']
    cursor = latest['next_cursor']
    assert cursor
    older = ledger.history(history_request(query=f'limit=2&cursor={cursor}'))
    assert [item['narrator_text'] for item in older['items']] == ['first']
    assert older['next_cursor'] is None
    with pytest.raises(FixtureRejected):
        ledger.history(history_request('project-two', f'limit=2&cursor={cursor}'))


class Route:
    def __init__(self, req, response=None):
        self.request, self.response, self.sent, self.fetched, self.continued = req, response, None, None, None

    def fetch(self, **kwargs):
        self.fetched = kwargs
        return self.response

    def fulfill(self, **kwargs):
        self.sent = kwargs

    def continue_(self, **kwargs):
        self.continued = kwargs


class Page:
    def __init__(self, history):
        self.workspace_history = history
        self.routes = []

    def route(self, pattern, handler):
        self.routes.append((pattern, handler))


def test_real_demo_creation_registers_only_successful_owned_response():
    with TestClient(create_app()) as client:
        created = client.post('/v1/projects', headers={'X-Account-Id': OWNER}, json={'mode': 'self'})
        assert created.status_code == 201
        ledger = WorkspaceHistory()
        route = Route(SimpleNamespace(method='POST', url='http://fixture/api/v1/memoir/projects', headers=AUTH),
                      SimpleNamespace(status=201, json=created.json))
        ledger.project_request(route)
        assert route.fetched == {'headers': {'x-account-id': OWNER}}
        assert route.sent == {'response': route.response}
        assert ledger.history(history_request(created.json()['id']))['items'] == []
        loaded = client.get('/v1/projects/' + created.json()['id'], headers={'X-Account-Id': OWNER})
        assert loaded.json()['id'] == created.json()['id']


def test_project_adapter_does_not_fabricate_registration_from_failed_or_other_requests():
    ledger = WorkspaceHistory()
    failed = Route(SimpleNamespace(method='POST', url='http://fixture/api/v1/memoir/projects', headers=AUTH),
                   SimpleNamespace(status=503, json=lambda: project()))
    ledger.project_request(failed)
    assert failed.sent == {'response': failed.response}
    existing = Route(SimpleNamespace(method='GET', url='http://fixture/api/v1/memoir/projects/project-one', headers=AUTH))
    ledger.project_request(existing)
    assert existing.continued == {'headers': {'x-account-id': OWNER}}
    with pytest.raises(FixtureRejected):
        ledger.history(history_request())


def test_turn_wrapper_preserves_callback_and_transports_saved_receipt(ledger):
    import json
    page = Page(ledger)
    captured = []
    def answer(route):
        captured.append(route.request.post_data_json['text'])
        route.fulfill(content_type='application/json', body='{"reply":"Remembered answer"}')
    mock_workspace_turn(page, answer)
    pattern, handler = page.routes[0]
    assert pattern == '**/api/v1/memoir/agent/turn'
    route = Route(request())
    handler(route)
    assert captured == [route.request.post_data_json['text']]
    assert route.sent['content_type'] == 'application/x-ndjson'
    events = [json.loads(line) for line in route.sent['body'].splitlines()]
    assert events[1]['data']['conversation_saved'] is True
    assert ledger.history(history_request())['items'][0]['reply'] == 'Remembered answer'


def test_http_adapters_keep_rejections_and_never_return_generic_history_success(ledger):
    page = Page(ledger)
    mock_workspace_turn(page, lambda route: route.fulfill(status=503, json={'detail': 'Synthetic rejection'}))
    route = Route(request())
    page.routes[0][1](route)
    assert route.sent == {'status': 503, 'json': {'detail': 'Synthetic rejection'}}
    assert ledger.history(history_request())['items'] == []
    route = Route(history_request('foreign-project'))
    ledger.history_request(route)
    assert route.sent['status'] == 404
    assert 'items' not in route.sent['json']
    route = Route(request(project_id='foreign-project'))
    mock_workspace_turn(page, lambda route: route.fulfill(json={'reply': 'No receipt'}))
    page.routes[-1][1](route)
    assert route.sent['status'] == 404
    assert 'conversation_saved' not in route.sent['json']


@pytest.mark.parametrize('method,path', [
    ('POST', '/api/v1/memoir/user/projects/project-one/history'),
    ('GET', '/api/v1/memoir/user/projects/project-one/history/extra'),
    ('GET', '/api/v1/memoir/user/conversations'),
])
def test_history_adapter_rejects_other_operations_with_scope_diagnostics(ledger, capsys, method, path):
    req = history_request()
    req.method, req.url = method, 'http://user:secret@fixture' + path + '?limit=100&cursor=private-cursor-token'
    route = Route(req)
    ledger.history_request(route)
    assert route.sent['status'] == 400
    assert route.sent['headers']['Cache-Control'] == 'no-store'
    diagnostic = capsys.readouterr().out
    assert diagnostic.strip() == f'Workspace history fixture rejected {method} {path} (400)'
    assert 'secret' not in diagnostic and 'private-cursor-token' not in diagnostic
    assert AUTH['authorization'] not in diagnostic
    assert 'items' not in route.sent['json']


def test_turn_adapter_cannot_turn_a_greeting_into_narrator_evidence(ledger):
    req = request()
    req.url = 'http://fixture/api/v1/memoir/agent/greeting'
    with pytest.raises(FixtureRejected):
        ledger.turn_events(req, {'reply': 'Welcome'})
    assert ledger.history(history_request())['items'] == []
