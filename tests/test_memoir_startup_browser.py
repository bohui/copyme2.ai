"""Landing and saved-interview startup on the real frontend with controlled API replies."""
import os
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright


@pytest.mark.skipif(not os.getenv('MEMOIR_BROWSER_URL'), reason='Requires an isolated frontend')
def test_saved_interview_loads_on_begin_and_keeps_chat_stable():
    project_id = 'startup-fixture'
    project_path = f'/projects/{project_id}'
    history_path = f'/user{project_path}/history'
    place = dict(place='Chengde', granularity='city', latitude=40.95, longitude=117.96,
                 hierarchy=['Earth', 'China', 'Hebei', 'Chengde'])
    profile = dict(name='Saved narrator', preferred_language='en-AU', memory_places=[place])
    responses = {
        '/agent/config': {'auth_mode': 'test', 'google_maps_browser_api_key': 'synthetic'},
        '/agent/profile': profile,
        '/user/profile': profile,
        project_path: {'id': project_id, 'mode': 'self', 'profile': profile},
        f'{project_path}/journey': {'active_session': None},
        history_path: {'project_id': project_id, 'items': [
            {'server_turn_id': 'saved-turn', 'narrator_text': 'I remember Chengde.',
             'reply': 'What did your street look like?'}
        ]},
        '/agent/pending-turn': {'turn': None},
        '/story/state': {'family_features_enabled': False},
        f'/agent/places/{project_id}/photos': {'items': [], 'status': 'COMPLETE'},
    }
    requests, delayed, provider_requests = [], {}, []
    prefix = '/api/v1/memoir'

    def api(route):
        path = urlsplit(route.request.url).path.removeprefix(prefix)
        requests.append(path)
        if path == '/story/atlas-events' and path not in delayed:
            delayed[path] = route
        else:
            route.fulfill(json=responses.get(path, {}))

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 900}, locale='en-AU')
        page.route('https://**', lambda route: route.abort())
        page.on('request', lambda request: provider_requests.append(request.url)
                if urlsplit(request.url).path.endswith('/Cesium.js') else None)
        page.route(f'**{prefix}/**', api)
        page.add_init_script(f"localStorage.setItem('memory-spark-project', '{project_id}')")
        page.goto(os.environ['MEMOIR_BROWSER_URL'].rstrip('/'), wait_until='networkidle')
        assert set(requests) <= {'/agent/config', '/agent/profile'}
        assert not provider_requests

        with page.expect_request('**/story/atlas-events?**'):
            page.locator('[data-action="open-memoir"]').click()
        expect(page.locator('#chat-history')).to_contain_text('I remember Chengde.')
        assert requests.count(history_path) == 1
        expect(page.locator('#chat-scroll .chat-heading')).to_be_visible()
        expect(page.locator('.chat-main > .composer-wrap')).to_be_visible()

        composer = page.locator('#chat-input')
        composer.fill('My unsent draft')
        composer.evaluate("input => input.setSelectionRange(3, 8)")
        page.evaluate("""() => {
          window.startupNodes = ['.story-shell', '#chat-scroll', '#chat-input'].map(selector => document.querySelector(selector));
        }""")
        # The Atlas snapshot can arrive after the user has started typing.
        delayed['/story/atlas-events'].fulfill(json={
            'project_id': project_id, 'profile': {**profile, 'name': 'Updated narrator'}, 'map_photos': [],
        })
        expect(page.locator('.profile-trigger-name')).to_have_text('Updated narrator')
        expect(composer).to_be_focused()
        assert page.evaluate("""() => {
          const [shell, scroll, input] = startupNodes;
          return shell.isConnected && scroll.isConnected && input.isConnected
            && input.value === 'My unsent draft' && input.selectionStart === 3 && input.selectionEnd === 8;
        }""")
        assert len(provider_requests) == 1
        browser.close()
