"""Shipped UI + real recovery/history/sample routes; external auth/data are fixtures."""
import json
import os
import time
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import expect, sync_playwright

from apps.api import main, supabase_routes
from apps.api.agent_storage import UserStorage
from apps.api.store import MemoryStore

pytestmark = pytest.mark.skipif(not os.getenv('MEMOIR_BROWSER_URL'), reason='Requires source frontend')


@pytest.mark.parametrize('entry', ['saved-link', 'landing'])
@pytest.mark.parametrize('history_kind', ['memory', 'attachment'])
@pytest.mark.parametrize('adapter', ['missing', 'transferred-guest'])
def test_login_restores_original_project_and_serves_reviewed_sample(monkeypatch, entry, history_kind, adapter, rounds=21):
    project_id = 'project_saved'
    profile = {'name': 'Fixture narrator', 'preferred_language': 'en-AU'}
    storage = Mock(spec=UserStorage)
    storage.user_id = 'fixture-owner'
    storage.user = {'id': 'fixture-owner', 'is_anonymous': False}
    storage.client = Mock()
    storage.is_anonymous = False
    storage.profile.return_value = profile
    storage.recall_rounds_completed.return_value = rounds
    storage.story_entitlement.return_value = None
    storage.all_memories.return_value = [{
        'id': 'saved-turn', 'kind': 'agent', 'project_id': project_id, 'created_at': '2026-10-07',
        'content': 'Storyteller: My saved childhood\nMemory Spark: Tell me about the garden.',
    }]
    storage.request.side_effect = lambda method, path, **_: Mock(json=lambda:
        [{'project_id': project_id}] if path == '/rest/v1/user_memoir_project' and history_kind == 'memory' else
        [{'id': 'legacy-attachment', 'project_id': project_id, 'created_at': '2026-10-07',
          'workspace': {'guest_user_id': 'fixture-guest'},
          'messages': [{'role': 'user', 'text': 'My saved childhood'},
                       {'role': 'assistant', 'text': 'Tell me about the garden.'}]
                      if history_kind == 'attachment' else []}]
        if path == '/rest/v1/user_conversation_attachment' and (history_kind == 'attachment' or adapter == 'transferred-guest') else [])
    if history_kind == 'attachment':
        storage.all_memories.return_value = []
    storage.saved_memoir_draft.return_value = {
        'status': 'ready', 'preview': {'kind': 'sample_storyline', 'title': 'My reviewed sample',
                                      'text': 'A familiar garden from my childhood.'},
        'revision': 2, 'covered_round': 10, 'updating': True, 'error': None,
    }
    def authenticated(authorization):
        if authorization != 'Bearer fixture-session':
            raise main.HTTPException(401, 'Missing fixture session')
        return storage
    monkeypatch.setattr(main, 'authenticated_storage', authenticated)
    monkeypatch.setattr(supabase_routes, 'storage', lambda _: storage)
    monkeypatch.setattr(supabase_routes, '_queue_if_configured', lambda: None)
    store = MemoryStore()
    with TestClient(main.create_app(store, story_storage_factory=lambda _: storage)) as client, sync_playwright() as pw:
        if adapter == 'transferred-guest':
            storage.user_id = 'fixture-guest'
            original = client.post('/v1/projects', headers={'Authorization': 'Bearer fixture-session'}, json={}).json()
            project = store.projects.pop(original['id'])
            project['id'] = project_id
            store.projects[project_id] = project
            storage.user_id = 'fixture-owner'
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(reduced_motion='reduce')
        base = os.environ['MEMOIR_BROWSER_URL']
        context.add_cookies([{'name': 'copyme2_ui_locale', 'value': 'en-AU', 'url': base},
                            {'name': 'copyme2_ui_locale_source', 'value': 'fixed', 'url': base}])
        auth_script = """window.supabase={createClient:()=>({auth:{
          getSession:async()=>({data:{session:{access_token:'fixture-session',user:{id:'fixture-owner',is_anonymous:false}}}}),
          getUser:async()=>({data:{user:{id:'fixture-owner',is_anonymous:false}}}),onAuthStateChange:()=>({})
        }})};"""
        context.route('https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2',
                      lambda r: r.fulfill(content_type='text/javascript', body=auth_script))
        sample_times = []
        requests = []
        def api(route):
            path = route.request.url.split('/api/v1/memoir')[-1]
            endpoint = path.split('?')[0]
            if endpoint == '/projects' or endpoint.startswith('/projects/') or endpoint in ('/user/conversations', '/story/preview'):
                started = time.monotonic()
                response = client.request(route.request.method, '/v1' + path,
                    headers={key: value for key, value in route.request.headers.items()
                             if key in {'authorization', 'content-type'}},
                    content=route.request.post_data or None)
                requests.append((route.request.method, endpoint, response.status_code))
                if endpoint == '/story/preview':
                    assert json.loads(route.request.post_data)['project_id'] == project_id
                    sample_times.append(time.monotonic() - started)
                return route.fulfill(status=response.status_code, content_type='application/json', body=response.text)
            data = {}
            if endpoint == '/agent/config':
                data = {'supabase_url': 'https://auth.test', 'supabase_publishable_key': 'public', 'auth_mode': 'supabase'}
            elif endpoint in ('/user/profile', '/agent/profile'): data = profile
            elif endpoint == '/story/state':
                data = {'family_features_enabled': False, 'payment_features': [], 'recall_status': {
                    'rounds_completed': rounds, 'free_rounds': 20, 'payment_required': rounds >= 20, 'paid': False}}
            elif endpoint == '/agent/place-journey': data = {'place_journey': None}
            elif endpoint == '/story/private-draft': data = storage.saved_memoir_draft.return_value
            route.fulfill(content_type='application/json', body=json.dumps(data))
        context.route('**/api/v1/memoir/**', api)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(base + (f'/memoir/interview/{project_id}' if entry == 'saved-link' else '/memoir'))
        page.wait_for_load_state('networkidle')
        if entry == 'landing': page.locator('[data-action="start-story"][data-mode="self"]').click()
        try:
            if rounds >= 20:
                expect(page.locator('.recall-preview').get_by_text('A familiar garden from my childhood.', exact=True)).to_be_visible(timeout=15000)
            else:
                expect(page.locator('#chat-input')).to_be_visible(timeout=15000)
        except AssertionError:
            print('Browser recovery requests:', requests, 'errors:', errors)
            raise
        assert page.url.endswith('/memoir/interview/' + project_id)
        expect(page.get_by_role('main', name='Mira conversation')).to_be_visible()
        if entry == 'saved-link': page.locator('[data-action="toggle-chat-history"]').click()
        expect(page.get_by_text('My saved childhood', exact=True)).to_be_visible()
        assert list(store.projects) == [project_id]
        if rounds >= 20:
            assert len(sample_times) == 1 and sample_times[0] < 1
        storage.retry_memoir_lane.assert_not_called()
        if sample_times:
            print(f'{entry}: reviewed sample response {sample_times[0]*1000:.1f}ms')
        browser.close()


@pytest.mark.parametrize('entry', ['saved-link', 'landing'])
def test_transferred_guest_chatbox_reopens_after_login(monkeypatch, entry):
    test_login_restores_original_project_and_serves_reviewed_sample(
        monkeypatch, entry, 'attachment', 'transferred-guest', rounds=2)
