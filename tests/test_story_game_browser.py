"""Real UI, API routes and PostgreSQL; only external Auth and model are controlled."""
import json
import asyncio
import os
import time
from urllib.parse import quote
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
from test_story_game_runtime_postgres import proposal_from_packet, pool_from_packet, compose_game_chapters, MEMORIES
from test_story_game_runtime import webpage, receipt

pytestmark = pytest.mark.skipif(not os.getenv('MEMOIR_BROWSER_URL'), reason='Requires isolated source frontend')


def wait_for_position(player, predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate(float(player.get_attribute('data-game-position'))):
            return
        player.page.wait_for_timeout(25)
    raise AssertionError('game_movement_timeout')


@pytest.mark.parametrize('locale,width', [('en-AU', 1280), ('zh-CN', 390)])
def test_scene_selection_pauses_before_astra_then_opens_for_play_and_revokes(sql, tmp_path, monkeypatch, locale, width):
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB', str(tmp_path / 'game-browser-tasks.sqlite3'))
    conversation = Conversation(sql, tmp_path, monkeypatch,
        lambda packet: {**empty(packet), 'events': [episode(packet, packet['sources'][0]['text'])]},
        strategy='shape')
    calls, requests, generated_quotes = [], [], []

    class GameBroker(Broker):
        def __init__(self):
            super().__init__(sql)
            self.client = httpx.AsyncClient(trust_env=False)

    def storage(authorization):
        if authorization != 'Bearer fixture-only':
            raise HTTPException(401, 'Sign in required')
        return PostgresRest(sql, OWNER).storage()

    async def provider(packet, *, token):
        calls.append('scenes')
        scenes = proposal_from_packet(packet)
        generated_quotes.extend(scene['quote'] for scene in scenes['scenes'])
        return pool_from_packet(packet), dict(status='completed', response_id='resp-controlled-game', model='controlled')

    async def builder(packet, proposal, *, token):
        calls.append('higgsfield')
        assert len(proposal['scenes']) == 2
        return webpage(packet['authority']['locale']), {**receipt('higgsfield'), 'requested_model': 'gpt-6-astra',
            'skill': 'higgsfield-websites', 'skill_sha256': 'a'*64}

    async def composer(packet, proposal, *, token):
        calls.append('brief')
        assert len(proposal['scenes']) == 2
        return dict(design_brief='A coherent private memory journey.', scene_indices=[0,1]), receipt('brief')

    monkeypatch.setattr(story_game_runtime, 'compose_game_brief', composer)
    monkeypatch.setattr(formal_memoir_routes, 'authenticated_storage', storage)
    monkeypatch.setattr(story_game_routes, 'authenticated_storage', storage)
    monkeypatch.setattr(memory_event_worker, 'MemoirLaneBroker', GameBroker)
    monkeypatch.setattr(story_game_runtime, 'propose_game', provider)
    monkeypatch.setattr(story_game_runtime, 'build_game', builder)
    copy = json.loads((Path(__file__).parents[1] / f'apps/web/messages/{locale}.json').read_text())['Memoir']['game']
    with conversation.client:
        history = None
        for text in MEMORIES:
            result = conversation.say(text)
            conversation.drain()
            history = history or StoryHistoryFixture(OWNER, conversation.project, 'fixture-only')
            turn = sql('select client_turn_id from public.user_narrator_source order by sequence desc limit 1;').stdout.strip()
            history.save(dict(project_id=conversation.project, client_turn_id=turn, conversation_text=text), result['reply'])
        asyncio.run(compose_game_chapters(conversation))
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
                data = {'recall_status': dict(rounds_completed=5, free_rounds=20, payment_required=False, paid=True), 'family_features_enabled': False}
            elif plain == '/agent/place-journey': data = {'place_journey': None}
            route.fulfill(content_type='application/json', body=json.dumps(data))

        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=os.getenv('MEMOIR_BROWSER_EXECUTABLE'), headless=True)
            context = browser.new_context(viewport={'width': width, 'height': 900}, has_touch=True, reduced_motion='reduce')
            base = os.environ['MEMOIR_BROWSER_URL']
            context.add_cookies([{'name':'copyme2_ui_preference_v1','value':quote(json.dumps({'version':1,'locale':locale,'source':'manual','viewer':None})),'url':base},
                                 {'name': 'copyme2_ui_locale', 'value': locale, 'url': base},
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
                expect(page.locator('[data-generate-game]')).to_be_visible()
                assert not calls
                page.locator('[data-generate-game]').click()
                expect(page.locator('[data-scene-selection]')).to_be_visible(timeout=30000)
                expect(page.locator('[data-scene-option]')).to_have_count(len(MEMORIES))
                expect(page.locator('.game-cost-hint')).to_have_text(copy['sceneCost'])
                expect(page.locator('iframe.story-game-frame')).to_have_count(0)
                assert calls == ['scenes']
                page.reload()
                expect(opener).to_be_visible(timeout=30000)
                opener.click()
                expect(page.locator('[data-scene-selection]')).to_be_visible(timeout=30000)
                assert calls == ['scenes']
                page.locator('[data-scene-count]').fill('2')
                page.locator('[data-scene-count]').press('Tab')
                expect(page.locator('[data-scene-option]:checked')).to_have_count(2)
                output = Path('output/playwright'); output.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(output / f'story-game-selection-{locale}.png'))
                page.locator('[data-confirm-scenes]').click()
                expect(page.locator('iframe.story-game-frame')).to_be_visible(timeout=30000)
                expect(page.locator('[data-game-review]')).to_have_count(0)
                expect(page.locator('[data-publish-game]')).to_have_count(0)
                assert calls == ['scenes', 'brief', 'higgsfield']
                assert page.locator('iframe.story-game-frame').get_attribute('sandbox') == 'allow-scripts'
                frame = page.frame_locator('iframe.story-game-frame')
                assert frame.locator('body').evaluate("() => {try {return !!parent.document.body;} catch {return false;}}") is False
                player = frame.locator('#memoir-game')
                first_scene = player.get_attribute('data-game-scene')
                stage = frame.locator('.game-stage')
                stage.focus()
                page.keyboard.down('ArrowRight')
                wait_for_position(player, lambda position: position > 540)
                page.keyboard.up('ArrowRight')
                frame.locator('[data-game-interact]').click()
                expect(frame.locator('.game-dialogue')).to_contain_text(generated_quotes[0])
                for key, direction in [('Enter', 1), ('Space', -1)]:
                    frame.locator('[data-game-interact]').click()
                    start = float(player.get_attribute('data-game-position'))
                    frame.locator(f'[data-game-move="{direction}"]').focus()
                    page.keyboard.down(key)
                    try:
                        wait_for_position(player, lambda position: (position - start) * direction > 12, timeout=1.5)
                    finally:
                        page.keyboard.up(key)
                    expect(frame.locator('.game-dialogue')).to_be_hidden()
                stage.focus()
                page.keyboard.down('ArrowRight')
                expect(player).not_to_have_attribute('data-game-scene', first_scene)
                page.keyboard.up('ArrowRight')
                # A real touch press holds movement, including after a scene transition.
                touch = context.new_cdp_session(page)
                bounds = frame.locator('[data-game-move="1"]').bounding_box()
                point = {'x': bounds['x'] + bounds['width'] / 2, 'y': bounds['y'] + bounds['height'] / 2}
                touch.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [point]})
                wait_for_position(player, lambda position: position > 550)
                touch.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
                frame.locator('[data-game-interact]').tap()
                expect(frame.locator('.game-dialogue')).to_contain_text(generated_quotes[1])
                frame.locator('.game-text-equivalent summary').click()
                for passage in generated_quotes[:2]:
                    expect(frame.locator('.game-text-equivalent')).to_contain_text(passage)
                expect(frame.locator('.game-text-equivalent')).not_to_contain_text(generated_quotes[2])
                page.keyboard.press('Escape')
                expect(page.locator('.story-game-modal')).to_have_count(0)
                expect(opener).to_be_focused()
                page.reload()
                expect(opener).to_be_visible(timeout=30000)
                opener.click()
                expect(page.locator('iframe.story-game-frame')).to_be_visible(timeout=30000)
                assert calls == ['scenes', 'brief', 'higgsfield']
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
                expect(page.locator('iframe.story-game-frame')).to_have_count(0)
                expect(page.locator('[data-game-consent]')).to_be_visible(timeout=30000)
                reads = sum(method == 'GET' and '/story-game/' in path for method, path in requests)
                old_route, old_response = held[0]
                old_route.fulfill(status=200, headers=dict(old_response.headers), body=old_response.content)
                page.wait_for_load_state('networkidle')
                assert sum(method == 'GET' and '/story-game/' in path for method, path in requests) == reads
                expect(page.locator('.story-game-modal [role="alert"]')).to_have_count(0)
                assert sql('select count(*) from public.user_story_game where candidate is not null;').stdout.strip() == '0'
                assert not errors, errors
                assert not any(method == 'POST' and path.endswith('/publish') for method, path in requests)
            finally:
                context.close(); browser.close()


@pytest.mark.parametrize('direction', ['back', 'forward'])
def test_navigation_closes_game_and_aborts_requests_before_slow_or_failed_recovery(direction):
    from uuid import uuid4

    base = os.environ['MEMOIR_BROWSER_URL']
    project_id, unavailable = 'game-navigation-a', 'game-navigation-b'
    profile = dict(preferred_language='en-AU', name='Test Author', birth_year=1960)
    history = StoryHistoryFixture(OWNER, project_id, 'fixture-only')
    history.save(dict(project_id=project_id, client_turn_id=str(uuid4()), conversation_text='An invented garden memory.'),
        'A saved garden reply.')
    game = json.loads((Path(__file__).parents[1] / 'skills/memoir-story-game/tests/fixtures/candidate.json').read_text())['game']
    held, recovery = [], []
    holding = False

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(reduced_motion='reduce')
        context.add_cookies([{'name': 'copyme2_ui_locale', 'value': 'en-AU', 'url': base},
                             {'name': 'copyme2_ui_locale_source', 'value': 'fixed', 'url': base}])
        user = dict(id=OWNER, is_anonymous=False)
        install_supabase_fixture(context, 'window.supabase={createClient:()=>({auth:{getSession:async()=>({data:{session:'
            + json.dumps(dict(access_token='fixture-only', user=user)) + '}}),getUser:async()=>({data:{user:'
            + json.dumps(user) + '}}),onAuthStateChange:()=>({})}})};')
        context.add_init_script("""window.gameRequestSignals=[];const originalFetch=window.fetch;
            window.fetch=(url,options={})=>{if(String(url).includes('/story-game')&&options.signal)
                window.gameRequestSignals.push(options.signal);return originalFetch(url,options)};""")
        context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base + '/') else route.abort())

        def api(route):
            if history.serve(route): return
            path = route.request.url.split('/api/v1/memoir')[-1].split('?')[0]
            if path == '/projects/' + unavailable:
                recovery.append(route)
                return
            if path.endswith('/story-game') and holding:
                held.append(route)
                return
            data = {}
            if path == '/agent/config': data = dict(supabase_url='https://auth.test', supabase_publishable_key='public', auth_mode='supabase')
            elif path in ('/agent/profile', '/user/profile'): data = profile
            elif path == '/projects/' + project_id: data = dict(id=project_id, revision=1, mode='self', profile=profile)
            elif path.endswith('/journey'): data = {'active_session': None}
            elif path == '/story/state': data = {'recall_status': dict(rounds_completed=1, free_rounds=20, payment_required=False, paid=True)}
            elif path == '/story/readiness': data = dict(pending=False, profile=profile, current_mode=dict(project_id=project_id, mode='shape'))
            elif path == '/agent/place-journey': data = {'place_journey': None}
            elif path.endswith('/story-game'): data = dict(eligibility=dict(available=True, reasons=[]),
                formal={'edition': {'status': 'completed'}}, adaptation=dict(game_id=game['package_id'], status='published'))
            elif '/story-game/' in path: data = dict(game_id=game['package_id'], status='published', game=game)
            route.fulfill(json=data)

        context.route('**/api/v1/memoir/**', api)
        page = context.new_page()
        try:
            page.goto(base + '/memoir/interview/' + project_id)
            opener = page.locator('[data-story-game]').first
            expect(opener).to_be_visible(timeout=30000)
            if direction == 'back':
                page.evaluate("([a,b])=>{history.replaceState({},'',b);history.pushState({},'',a)}",
                    ['/memoir/interview/' + project_id, '/memoir/interview/' + unavailable])
            else:
                page.evaluate("b=>history.pushState({},'',b)", '/memoir/interview/' + unavailable)
                page.go_back()
            opener.click()
            expect(page.locator('[data-story-game-player]')).to_be_visible()
            holding = True
            count = page.evaluate('window.gameRequestSignals.length')
            with page.expect_request('**/api/v1/memoir/agent/projects/' + project_id + '/story-game'):
                page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
            page.wait_for_function('count=>window.gameRequestSignals.length>count', arg=count)
            with page.expect_request('**/api/v1/memoir/projects/' + unavailable):
                getattr(page, 'go_' + direction)()
                expect(page.locator('.story-game-modal')).to_have_count(0, timeout=1500)
                assert page.evaluate('window.gameRequestSignals.every(signal=>signal.aborted)')
            expect(page.locator('#app .loading')).to_be_visible()
            assert recovery and held
            recovery[0].fulfill(status=503, json={'detail': 'Recovery unavailable'})
            held[0].fulfill(json=dict(eligibility={'available': True}, adaptation={'status': 'published'}))
            page.wait_for_load_state('networkidle')
            expect(page.locator('.story-game-modal')).to_have_count(0)
        finally:
            context.close(); browser.close()
