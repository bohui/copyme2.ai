"""Standalone game URLs, real sharing RPCs and isolated browser accounts."""
import json
import os
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from playwright.sync_api import expect, sync_playwright

from apps.api import story_game_pages
from browser_supabase_fixture import install_supabase_fixture
from memoir_postgres_workflow import PostgresRest
from test_agent_commit_postgres import OWNER, OTHER
from test_lifetime_memory_postgres import attachment_database, private_database, event_database
from test_shared_memory_events_postgres import sql
from test_story_game_pages_postgres import PROJECT, database, example

pytestmark = pytest.mark.skipif(not os.getenv('MEMOIR_BROWSER_URL'), reason='Requires current frontend')


@pytest.mark.parametrize('locale,width', [('en-AU', 1280), ('zh-CN', 390)])
def test_project_game_private_public_and_invited_friend(sql, example, monkeypatch, locale, width, tmp_path):
    base = os.environ['MEMOIR_BROWSER_URL']
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL', sql.publication_dsn)

    def storage(authorization):
        owner = {'Bearer fixture-owner': OWNER, 'Bearer fixture-friend': OTHER}.get(authorization)
        if owner is None:
            raise HTTPException(401, 'Sign in required')
        return PostgresRest(sql, owner).storage()

    monkeypatch.setattr(story_game_pages, 'authenticated_storage', storage)
    app = FastAPI()
    app.include_router(story_game_pages.router)
    copy = json.loads((Path(__file__).parents[1] / f'apps/web/messages/{locale}.json').read_text())['Memoir']['game']

    with TestClient(app) as client, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        contexts, errors = [], []

        def open_game(actor=None, suffix=''):
            context = browser.new_context(viewport={'width': width, 'height': 1000}, reduced_motion='reduce')
            contexts.append(context)
            context.add_cookies([{'name': 'copyme2_ui_locale', 'value': locale, 'url': base},
                                 {'name': 'copyme2_ui_locale_source', 'value': 'fixed', 'url': base}])
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base + '/') else route.abort())
            if actor:
                user = dict(id=OWNER if actor == 'owner' else OTHER, is_anonymous=False)
                session = dict(access_token='fixture-' + actor, user=user)
                install_supabase_fixture(page, 'window.supabase={createClient:()=>({auth:{getSession:async()=>({data:{session:'
                    + json.dumps(session) + '}})}})};')

            def api(route):
                path = route.request.url.split('/api/v1/memoir')[-1]
                if path == '/agent/config':
                    route.fulfill(json=dict(supabase_url='https://auth.test', supabase_publishable_key='public'))
                    return
                assert path.startswith('/story-games/'), path
                headers = {'Content-Type': 'application/json'}
                if route.request.headers.get('authorization'):
                    headers['Authorization'] = route.request.headers['authorization']
                response = client.request(route.request.method, '/v1' + path,
                    headers=headers, content=route.request.post_data_buffer)
                route.fulfill(status=response.status_code, headers=dict(response.headers), body=response.content)

            page.route('**/api/v1/memoir/**', api)
            page.goto(base + '/memoir/game/' + PROJECT + suffix)
            return page

        try:
            owner = open_game('owner')
            expect(owner.locator('iframe.story-game-frame')).to_be_visible(timeout=30000)
            visibility = owner.get_by_label(copy['whoCanPlay'])
            expect(visibility).to_have_value('private')
            expect(owner.get_by_text(copy['exampleNotice'])).to_be_visible()
            stranger = open_game()
            expect(stranger.get_by_role('alert')).to_have_text(copy['unavailable'], timeout=30000)
            expect(stranger.locator('iframe')).to_have_count(0)
            visibility.select_option('public')
            expect(visibility).to_be_enabled()
            stranger.reload()
            expect(stranger.locator('iframe.story-game-frame')).to_be_visible(timeout=30000)
            expect(stranger.locator('.game-sharing')).to_have_count(0)
            visibility.select_option('friends')
            expect(visibility).to_be_enabled()
            # Existing public viewers lose the game at the next access refresh.
            expect(stranger.locator('iframe')).to_have_count(0, timeout=15000)
            owner.get_by_label(copy['friendEmail']).fill('friend@example.test')
            owner.get_by_role('button', name=copy['createInvite']).click()
            invitation = owner.get_by_label(copy['inviteLink'])
            expect(invitation).to_be_visible()
            suffix = '?invite=' + invitation.input_value().split('?invite=')[1]
            wrong_account = open_game('owner', suffix)
            expect(wrong_account.get_by_role('alert')).to_have_text(copy['unavailable'], timeout=30000)
            expect(wrong_account.locator('iframe')).to_have_count(0)
            friend = open_game('friend', suffix)
            expect(friend.locator('iframe.story-game-frame')).to_be_visible(timeout=30000)
            expect(friend).to_have_url(base + '/memoir/game/' + PROJECT)
            expect(friend.locator('.game-sharing')).to_have_count(0)
            friend.reload()
            expect(friend.locator('iframe.story-game-frame')).to_be_visible(timeout=30000)
            owner.get_by_role('button', name=copy['removeInvite']).click()
            expect(friend.locator('iframe')).to_have_count(0, timeout=15000)
            expect(friend.get_by_role('alert')).to_have_text(copy['unavailable'])
            visibility.select_option('private')
            expect(visibility).to_be_enabled()
            owner.reload()
            expect(owner.locator('iframe.story-game-frame')).to_be_visible(timeout=30000)
            expect(owner.get_by_label(copy['whoCanPlay'])).to_have_value('private')
            assert not errors
            owner.screenshot(path=str(tmp_path / f'owner-game-{locale}.png'), full_page=True)
        finally:
            for context in contexts:
                context.close()
            browser.close()
