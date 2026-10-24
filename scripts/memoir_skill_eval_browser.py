"""Browser witnesses against the real frontend and disposable application routes."""
from pathlib import Path
import json
import time
from urllib.parse import urlsplit


def exercise_game(conversation, sql, item, base, executable, folder, sources, result):
    from playwright.sync_api import sync_playwright, expect
    from browser_supabase_fixture import install_supabase_fixture
    from browser_story_history_fixture import StoryHistoryFixture
    from memoir_postgres_workflow import PostgresRest
    from test_agent_commit_postgres import OWNER
    from apps.api import story_game_routes, formal_memoir_routes
    from unittest.mock import patch
    from fastapi import HTTPException

    origin = urlsplit(base)
    if origin.scheme != 'http' or origin.hostname not in {'127.0.0.1', 'localhost'} or origin.path not in {'', '/'}:
        raise ValueError('task_owned_browser_origin_required')
    base = base.rstrip('/')
    history = StoryHistoryFixture(OWNER, conversation.project, 'fixture-only')
    for source in sources:
        history.save(dict(project_id=conversation.project, client_turn_id=source['client_turn_id'],
            conversation_text=source['text']), result['reply'])
    project = dict(id=conversation.project, revision=1, mode='self',
                   profile=dict(preferred_language=item['locale']), workspace_unlocked=False)
    requests, errors, visits = [], [], []
    def storage(auth):
        if auth != 'Bearer fixture-only': raise HTTPException(401, 'Synthetic session required')
        return PostgresRest(sql, OWNER).storage()

    def api(route):
        if history.serve(route): return
        path = route.request.url.split('/api/v1/memoir')[-1]
        plain = path.split('?')[0]
        if plain.startswith('/agent/projects/') or plain == '/story/readiness':
            response = conversation.client.request(route.request.method, '/v1' + path,
                headers={'Authorization': 'Bearer fixture-only', 'Content-Type': 'application/json'},
                content=route.request.post_data_buffer)
            requests.append(dict(method=route.request.method, path=plain, status=response.status_code))
            return route.fulfill(status=response.status_code, headers=dict(response.headers), body=response.content)
        data = {}
        if plain == '/agent/config':
            data = dict(supabase_url='https://auth.test', supabase_publishable_key='public-fixture', auth_mode='supabase')
        elif plain in ('/agent/profile', '/user/profile'): data = project['profile']
        elif plain == '/projects/' + conversation.project: data = project
        elif plain.endswith('/journey'): data = dict(active_session=None)
        elif plain == '/story/state':
            data = dict(recall_status=dict(rounds_completed=2, free_rounds=20, payment_required=False, paid=True),
                        family_features_enabled=False)
        elif plain == '/agent/place-journey': data = dict(place_journey=None)
        route.fulfill(json=data)

    with patch.object(story_game_routes, 'authenticated_storage', storage), \
         patch.object(formal_memoir_routes, 'authenticated_storage', storage), sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=executable, headless=True)
        def context():
            ctx = browser.new_context(viewport=dict(width=390 if item['locale'] == 'zh-CN' else 1280, height=900),
                                      has_touch=True, reduced_motion='reduce')
            user = dict(id=OWNER, is_anonymous=False, user_metadata=dict(ui_locale=item['locale']))
            session = dict(access_token='fixture-only', user=user)
            ctx.add_cookies([dict(name='copyme2_ui_locale', value=item['locale'], url=base)])
            ctx.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base + '/') else route.abort())
            # External Auth is fulfilled by the SDK fixture; application calls use real local routes.
            # Install the fixture last so its Auth handler takes precedence over the network deny rule.
            install_supabase_fixture(ctx, 'window.supabase={createClient:()=>({auth:{getSession:async()=>({data:{session:'
                + json.dumps(session) + '}}),getUser:async()=>({data:{user:' + json.dumps(user)
                + '}}),onAuthStateChange:()=>({})}})};')
            ctx.route('**/api/v1/memoir/**', api)
            return ctx
        first = second = None
        try:
            first = context()
            page = first.new_page()
            page.on('pageerror', lambda error: errors.append(type(error).__name__))
            page.goto(base + '/memoir/interview/' + conversation.project)
            opener = page.locator('[data-story-game]').first
            expect(opener).to_be_visible(timeout=60000)
            opener.click()
            expect(page.locator('iframe.story-game-frame')).to_be_visible(timeout=30000)
            frame = page.frame_locator('iframe.story-game-frame')
            player = frame.locator('#memoir-game')
            expect(player).to_be_visible(timeout=30000)
            visits.append('initial')
            scene = player.get_attribute('data-game-scene')
            frame.locator('.game-stage').focus()
            page.keyboard.down('ArrowRight')
            try:
                deadline = time.monotonic() + 5
                while float(player.get_attribute('data-game-position')) <= 560:
                    if time.monotonic() >= deadline:
                        raise ValueError('browser_game_movement_timeout')
                    page.wait_for_timeout(25)
            finally:
                page.keyboard.up('ArrowRight')
            frame.locator('[data-game-interact]').click()
            expect(frame.locator('.game-dialogue')).to_be_visible()
            dialogue = frame.locator('.game-dialogue').inner_text()
            if not any(s['text'] in dialogue for s in sources): raise ValueError('browser_dialogue_not_original')
            page.screenshot(path=str(Path(folder) / 'play.png'))
            page.reload()
            opener = page.locator('[data-story-game]').first
            expect(opener).to_be_visible(timeout=30000)
            opener.click()
            expect(page.locator('[data-story-game-player]')).to_be_visible(timeout=30000)
            visits.append('reload')
            first.close(); first = None
            second = context()
            page = second.new_page()
            page.on('pageerror', lambda error: errors.append(type(error).__name__))
            page.goto(base + '/memoir/interview/' + conversation.project)
            opener = page.locator('[data-story-game]').first
            expect(opener).to_be_visible(timeout=30000)
            opener.click()
            expect(page.locator('[data-story-game-player]')).to_be_visible(timeout=30000)
            visits.append('new_context')
            page.locator('[data-revoke-game]').click()
            expect(page.locator('[data-story-game-player]')).to_have_count(0)
            expect(page.locator('[data-game-consent]')).to_be_visible(timeout=30000)
            page.screenshot(path=str(Path(folder) / 'revoked.png'))
            if errors: raise ValueError('browser_application_error')
            if not any(r['method'] == 'PUT' and r['path'].endswith('/consent') and r['status'] == 200 for r in requests):
                raise ValueError('browser_revocation_not_saved')
            return dict(verified=True, visits=visits, moved=True, dialogue=dialogue, scene_id=scene,
                revoked=True, requests=requests, external_network_allowed=False,
                screenshots=['play.png', 'revoked.png'])
        finally:
            if first: first.close()
            if second: second.close()
            browser.close()
