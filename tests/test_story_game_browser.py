"""Real UI, API routes and PostgreSQL; only external Auth and model are controlled."""
import json
import os
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException
from playwright.sync_api import expect, sync_playwright

from apps.api import formal_memoir_routes, story_game_routes, story_game_runtime, memory_event_worker
from browser_supabase_fixture import install_supabase_fixture
from browser_story_history_fixture import StoryHistoryFixture
from memoir_postgres_workflow import PostgresRest
from test_agent_commit_postgres import OWNER
from test_background_profile_workflow import Broker, database
from test_conversation_attribution import Conversation, empty, episode
from test_lifetime_memory_postgres import attachment_database, private_database, event_database
from test_shared_memory_events_postgres import sql, rpc, literal
from test_story_game_runtime_postgres import proposal_from_packet

pytestmark = pytest.mark.skipif(not os.getenv('MEMOIR_BROWSER_URL'), reason='Requires isolated source frontend')


@pytest.mark.parametrize('locale,width', [('en-AU', 1280), ('zh-CN', 390)])
def test_author_reviews_publishes_plays_recovers_and_revokes(sql, tmp_path, monkeypatch, locale, width):
    conversation = Conversation(sql, tmp_path, monkeypatch,
        lambda packet: {**empty(packet), 'events': [episode(packet, packet['sources'][0]['text'])]},
        strategy='shape')
    calls, requests = [], []

    class GameBroker(Broker):
        def __init__(self):
            super().__init__(sql)
            self.client = httpx.AsyncClient(trust_env=False)

    def storage(authorization):
        if authorization != 'Bearer fixture-only':
            raise HTTPException(401, 'Sign in required')
        return PostgresRest(sql, OWNER).storage()

    async def provider(packet):
        calls.append(packet['game_id'])
        return proposal_from_packet(packet), dict(status='completed', response_id='resp-controlled-game', model='controlled')

    monkeypatch.setattr(formal_memoir_routes, 'authenticated_storage', storage)
    monkeypatch.setattr(story_game_routes, 'authenticated_storage', storage)
    monkeypatch.setattr(memory_event_worker, 'MemoirLaneBroker', GameBroker)
    monkeypatch.setattr(story_game_runtime, 'propose_game', provider)
    copy = json.loads((Path(__file__).parents[1] / f'apps/web/messages/{locale}.json').read_text())['Memoir']['game']
    with conversation.client:
        history = None
        for text in ('My father repaired bicycles in our shed.', 'My mother grew roses in the garden.'):
            result = conversation.say(text)
            conversation.drain()
            history = history or StoryHistoryFixture(OWNER, conversation.project, 'fixture-only')
            turn = sql('select client_turn_id from public.user_narrator_source order by sequence desc limit 1;').stdout.strip()
            history.save(dict(project_id=conversation.project, client_turn_id=turn, conversation_text=text), result['reply'])
        project = dict(id=conversation.project, revision=1, mode='self', profile={'preferred_language': locale}, workspace_unlocked=False)
        assert 'completion_required' in rpc(sql, 'read_story_game_status', literal(conversation.project))['eligibility']['reasons']

        def api(route):
            if history.serve(route): return
            path = route.request.url.split('/api/v1/memoir')[-1]
            plain = path.split('?')[0]
            data = {}
            if plain.startswith('/agent/projects/') or plain == '/story/readiness':
                requests.append((route.request.method, path))
                response = conversation.client.request(route.request.method, '/v1' + path,
                    headers={'Authorization': 'Bearer fixture-only', 'Content-Type': 'application/json'},
                    content=route.request.post_data_buffer)
                assert response.status_code < 400, (path, response.status_code, response.text)
                return route.fulfill(status=response.status_code, headers=dict(response.headers), body=response.content)
            if plain == '/agent/config':
                data = dict(supabase_url='https://auth.test', supabase_publishable_key='public', auth_mode='supabase', show_draft_updates=False)
            elif plain in ('/agent/profile', '/user/profile'): data = project['profile']
            elif plain == '/projects/' + conversation.project: data = project
            elif plain.endswith('/journey'): data = {'active_session': None}
            elif plain == '/story/state':
                data = {'recall_status': dict(rounds_completed=2, free_rounds=20, payment_required=False, paid=True), 'family_features_enabled': False}
            elif plain == '/agent/place-journey': data = {'place_journey': None}
            route.fulfill(content_type='application/json', body=json.dumps(data))

        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=os.getenv('MEMOIR_BROWSER_EXECUTABLE'), headless=True)
            context = browser.new_context(viewport={'width': width, 'height': 900}, has_touch=True, reduced_motion='reduce')
            base = os.environ['MEMOIR_BROWSER_URL']
            context.add_cookies([{'name': 'copyme2_ui_locale', 'value': locale, 'url': base},
                                 {'name': 'copyme2_ui_locale_source', 'value': 'fixed', 'url': base}])
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base + '/') else route.abort())
            user = dict(id=OWNER, is_anonymous=False, user_metadata={'ui_locale': locale})
            session = dict(access_token='fixture-only', user=user)
            install_supabase_fixture(page, 'window.supabase={createClient:()=>({auth:{getSession:async()=>({data:{session:'
                + json.dumps(session) + '}}),getUser:async()=>({data:{user:' + json.dumps(user) + '}}),onAuthStateChange:()=>({})}})};')
            page.route('**/api/v1/memoir/**', api)
            try:
                page.goto(base + '/memoir/interview/' + conversation.project)
                opener = page.locator('[data-story-game]').first
                expect(opener).to_be_visible(timeout=30000)
                opener.click()
                expect(page.locator('[data-complete-memoir]')).to_be_visible()
                assert not calls
                page.locator('[data-complete-memoir]').click()
                expect(page.locator('[data-game-consent]')).to_be_visible(timeout=30000)
                page.locator('[data-generate-game]').click()
                assert not calls
                page.locator('[data-game-consent] input').check()
                page.locator('[data-generate-game]').click()
                expect(page.locator('[data-game-review]')).to_be_visible(timeout=30000)
                expect(page.locator('[data-story-game-player]')).to_have_count(0)
                assert len(calls) == 1
                expect(page.locator('[data-game-permission]')).to_have_count(2)
                page.locator('[data-publish-game]').click()
                assert sql("select count(*) from public.user_story_game where state='published';").stdout.strip() == '0'
                for checkbox in page.locator('[data-game-review] input').all(): checkbox.check()
                page.locator('[data-publish-game]').click()
                player = page.locator('[data-story-game-player]')
                expect(player).to_be_visible(timeout=30000)
                first_scene = player.get_attribute('data-game-scene')
                stage = page.locator('.game-stage')
                stage.focus()
                page.keyboard.down('ArrowRight')
                page.wait_for_function("Number(document.querySelector('[data-story-game-player]').dataset.gamePosition)>540")
                page.keyboard.up('ArrowRight')
                page.locator('[data-game-interact]').click()
                expect(page.locator('.game-dialogue')).to_contain_text('My father repaired bicycles')
                stage.focus()
                page.keyboard.down('ArrowRight')
                page.wait_for_function("first=>document.querySelector('[data-story-game-player]').dataset.gameScene!==first", arg=first_scene)
                page.keyboard.up('ArrowRight')
                # A real touch press holds movement, including after a scene transition.
                touch = context.new_cdp_session(page)
                bounds = page.locator('[data-game-move="1"]').bounding_box()
                point = {'x': bounds['x'] + bounds['width'] / 2, 'y': bounds['y'] + bounds['height'] / 2}
                touch.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [point]})
                page.wait_for_function("Number(document.querySelector('[data-story-game-player]').dataset.gamePosition)>550")
                touch.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
                page.locator('[data-game-interact]').tap()
                expect(page.locator('.game-dialogue')).to_contain_text('My mother grew roses')
                page.locator('.game-text-equivalent summary').click()
                expect(page.locator('.game-text-equivalent')).to_contain_text('My father repaired bicycles')
                page.keyboard.press('Escape')
                expect(page.locator('.story-game-modal')).to_have_count(0)
                expect(opener).to_be_focused()
                page.reload()
                expect(opener).to_be_visible(timeout=30000)
                opener.click()
                expect(player).to_be_visible(timeout=30000)
                assert len(calls) == 1
                output = Path('output/playwright'); output.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(output / f'story-game-{locale}.png'))
                held = []
                def hold_old_status(route):
                    if route.request.method != 'GET' or held:
                        return route.fallback()
                    response = conversation.client.get('/v1/agent/projects/' + conversation.project + '/story-game',
                        headers={'Authorization': 'Bearer fixture-only'})
                    assert response.status_code == 200
                    held.append((route, response))
                    page.evaluate('window.storyGamePollHeld = true')
                page.route('**/agent/projects/*/story-game', hold_old_status)
                page.wait_for_function('window.storyGamePollHeld === true', timeout=20000)
                page.locator('[data-revoke-game]').click()
                expect(player).to_have_count(0)
                expect(page.locator('[data-game-consent]')).to_be_visible(timeout=30000)
                reads = sum(method == 'GET' and '?review=true' in path for method, path in requests)
                old_route, old_response = held[0]
                old_route.fulfill(status=200, headers=dict(old_response.headers), body=old_response.content)
                page.wait_for_load_state('networkidle')
                assert sum(method == 'GET' and '?review=true' in path for method, path in requests) == reads
                expect(page.locator('.story-game-modal [role="alert"]')).to_have_count(0)
                assert sql('select count(*) from public.user_story_game where candidate is not null;').stdout.strip() == '0'
                assert not errors, errors
                assert any(method == 'POST' and path.endswith('/publish') for method, path in requests)
            finally:
                context.close(); browser.close()
