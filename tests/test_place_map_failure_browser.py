"""Production frontend; all API/Auth/model boundaries are synthetic and isolated."""
import json
import os
from pathlib import Path
from urllib.parse import quote, urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright


pytestmark = pytest.mark.skipif(not os.getenv('MEMOIR_BROWSER_URL'),
    reason='Requires an explicitly selected running source frontend')


@pytest.mark.parametrize('locale,message', [
    ('en-AU', 'Map could not be loaded.'), ('zh-CN', '地图暂时无法加载。'),
])
def test_map_failure_preserves_workspace_and_retries_only_on_request(locale, message):
    base = os.environ['MEMOIR_BROWSER_URL'].rstrip('/')
    project_id = 'map-failure-browser-fixture'
    place = dict(schema_version=1, status='active', revision=1, source_sequence=1,
        place='Chengde', hierarchy=['Earth', 'China', 'Hebei', 'Chengde'],
        granularity='city', latitude=40.9515, longitude=117.9634)
    profile = dict(name='Synthetic map test', preferred_language=locale, memory_places=[place])
    project = dict(id=project_id, mode='self', revision=1, profile=profile, workspace_unlocked=False)
    model_turns = []

    def api(route):
        path = urlsplit(route.request.url).path.split('/api/v1/memoir', 1)[-1]
        if path == '/agent/config':
            body = dict(auth_mode='test', geo_provider='google', google_maps_browser_api_key='synthetic-only')
        elif path in {'/agent/profile', '/user/profile'}:
            body = profile
        elif path.startswith('/projects'):
            body = project
        elif path.endswith('/history'):
            body = dict(schema_version=1, project_id=project_id, policy_epoch='1', items=[dict(
                server_turn_id='00000000-0000-4000-8000-000000000001',
                client_turn_id='00000000-0000-4000-8000-000000000002', kind='agent',
                created_at='2026-10-18T10:00:00Z', source_sequence='1',
                narrator_text='I grew up in Chengde.', reply='What do you remember about Chengde?')], next_cursor=None)
        elif path == '/story/state':
            body = dict(family_features_enabled=False,
                recall_status=dict(rounds_completed=1, free_rounds=20, payment_required=False))
        elif path == '/agent/place-journey':
            body = dict(place_journey=place)
        elif path.endswith('/photos'):
            body = dict(status='READY', searching=False, photos=[], items=[])
        elif path.endswith('/groups'):
            body = dict(places=[])
        elif path == '/agent/turn':
            model_turns.append(path)
            return route.fulfill(status=418, json={'detail': 'Model calls forbidden in this fixture'})
        else:
            body = {}
        route.fulfill(json=body)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={'width': 1440, 'height': 960}, reduced_motion='reduce')
            preference = dict(version=1, locale=locale, source='manual', viewer=None)
            context.add_cookies([dict(name='copyme2_ui_preference_v1', value=quote(json.dumps(preference)), url=base)])
            page = context.new_page()
            page.route('**/*', lambda route: route.continue_()
                if route.request.url.startswith(base + '/') else route.abort())
            page.route('**/api/v1/memoir/**', api)
            page.add_init_script('window.mapRenderAttempts=0;window.Cesium={WebMercatorProjection:class{},'
                "Viewer:class{constructor(){window.mapRenderAttempts++;throw new Error('Synthetic WebGL unavailable');}}};")
            page.goto(base + '/memoir/interview/' + project_id, wait_until='networkidle')
            expect(page.locator('.workspace-media-map')).to_be_visible()
            retry = page.locator('[data-map-retry]')
            expect(retry).to_be_visible()
            expect(retry).to_have_css('color', 'rgb(255, 253, 248)')
            expect(page.locator('.place-journey-fallback [role="status"]')).to_contain_text(message)
            assert page.evaluate('window.mapRenderAttempts') == 1
            retry.click()
            expect(retry).to_be_visible()
            page.wait_for_function('window.mapRenderAttempts===2')
            assert not model_turns
            output = Path('output/playwright') / f'map-failure-{locale}.png'
            output.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(output), full_page=True)
        finally:
            browser.close()
