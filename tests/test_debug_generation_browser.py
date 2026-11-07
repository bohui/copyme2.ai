"""The local generation controls through the source UI and a controlled API."""
import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from browser_atlas_fixture import install_atlas_fixture
from browser_story_history_fixture import STAGE_OWNER, StoryHistoryFixture
from browser_supabase_fixture import install_supabase_fixture
from test_story_game_runtime import webpage

pytestmark = pytest.mark.skipif(not os.getenv('MEMOIR_BROWSER_URL'), reason='Requires isolated source frontend')
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('locale,width,memoir_label,game_label,close_label', [
    ('en-AU', 1440, 'Generate my memoir', 'Story game', 'Back to map'),
    ('zh-CN', 390, '我的回忆录', '我的人生游戏', '返回地图'),
])
@pytest.mark.parametrize('anonymous', [True, False], ids=['guest', 'owner'])
def test_debug_footer_opens_a_playable_game_and_memoir(locale, width, memoir_label, game_label, close_label, anonymous):
    base = os.environ['MEMOIR_BROWSER_URL']
    project_id = 'debug-workspace'
    project_path = f'/agent/projects/{project_id}'
    place = dict(place='Chengde', hierarchy=['Earth', 'China', 'Hebei', 'Chengde'],
        granularity='city', life_stage='childhood', latitude=40.95, longitude=117.96, status='active', source_sequence=1)
    profile = {'preferred_language': locale, 'memory_places': [place]}
    history = StoryHistoryFixture(STAGE_OWNER, project_id, 'fixture-only')
    history.save(dict(project_id=project_id, client_turn_id='00000000-0000-4000-8000-000000000001',
        conversation_text='I grew up in Chengde.'), 'What do you remember about it?')
    game = json.loads((ROOT / 'skills/memoir-story-game/tests/fixtures/candidate.json').read_text())['game']
    game['webpage'] = webpage(locale)['html']
    game_path = project_path + '/story-game/' + game['package_id']
    draft_path = '/story/private-draft'
    languages, actions = [], []
    draft_checked, published = False, False
    digest = 'a' * 64
    title = '家属院里捉虫的日子' if locale == 'zh-CN' else 'The garden'
    paragraphs = ['一放学，我就和朋友到院里捉虫。', '雨后，我们在叶子上找到了蜗牛。'] if locale == 'zh-CN' else [
        'After school, I searched the garden for insects with my friends.', 'After rain, we found snails on the leaves.']
    passages = [dict(id=str(index), preview=dict(title=title, text=text)) for index,text in enumerate(paragraphs)]
    atlas = dict(project_id=project_id, profile=profile, current_mode=dict(project_id=project_id, mode='explore'),
        derived_workspace=dict(project_id=project_id, authoritative=True, policy_epoch=1, source_revision=1,
            places=[place], current_active_location=place))

    def api(route):
        nonlocal draft_checked
        if history.serve(route):
            return
        path = route.request.url.split('/api/v1/memoir', 1)[1].split('?')[0]
        method = route.request.method
        data = {}
        if path == '/agent/config':
            data = dict(auth_mode='supabase', supabase_url='https://auth.test', supabase_publishable_key='public',
                debug_early_generation=True)
        elif path in ('/agent/profile', '/user/profile'):
            data = profile
        elif path == f'/projects/{project_id}':
            data = dict(id=project_id, mode='self', revision=1, profile=profile)
        elif path.endswith('/journey'):
            data = {'active_session': None}
        elif path == '/story/state':
            data = {'recall_status': dict(rounds_completed=1, free_rounds=20, payment_required=False)}
        elif path == '/agent/place-journey':
            data = {'place_journey': place}
        elif path.endswith('/place-map'):
            data = dict(status='READY', target=place)
        elif path == '/story/atlas-events':
            data = atlas
        elif path == '/story/events':
            data = dict(events=[dict(id='saved-memory', revision=1, title='Looking for snails', kind='event', status='active',
                original_excerpt=paragraphs[1], uncertainty='The city is a weak guess.')])
        elif path == draft_path + '/generate':
            assert method == 'POST' and route.request.post_data_json['project_id'] == project_id
            payload = route.request.post_data_json
            assert payload.get('recompose', False) == (payload['language'] is not None)
            languages.append(payload['language'])
            return route.fulfill(status=202, json={'status': 'queued'})
        elif path == draft_path:
            if route.request.headers.get('accept') == 'application/x-ndjson':
                data = dict(status='ready', coverage_round=1, revision=1, updating=False,
                    snapshot_id='saved-draft', root_digest=digest, page_complete=False, next_cursor='next',
                    preview=passages[0]['preview'], first_record=passages[0])
                return route.fulfill(content_type='application/x-ndjson',
                    body=json.dumps({'type': 'draft_update', 'data': data}) + '\n{"type":"complete"}\n')
            draft_checked = True
            data = {'status': 'pending', 'updating': True}
        elif path == draft_path + '/page':
            data = dict(snapshot_id='saved-draft', complete=True, records=passages[1:])
        elif path == project_path + '/formal-memoir':
            actions.append('formal')
            data = dict(run_id='memoir-run', status='pending')
        elif path == project_path + '/formal-memoir/advance':
            actions.append('advance')
            data = dict(run_id='memoir-run', status='completed')
        elif path == project_path + '/story-game/consent':
            actions.append('consent')
            assert route.request.post_data_json['action'] == 'grant'
        elif path == project_path + '/story-game':
            if method == 'POST':
                actions.append('scenes')
                return route.fulfill(status=202, json={'status': 'pending'})
            edition = dict(edition_id='memoir-edition', manuscript_digest=digest) if 'advance' in actions else None
            reasons = [] if 'consent' in actions else ['adaptation_consent_required' if edition else 'completion_required']
            data = dict(composer_ready=draft_checked, eligibility=dict(available=not reasons, reasons=reasons,
                consent_revision=0), formal={'edition': edition})
            if 'scenes' in actions:
                status = 'published' if published else 'running' if 'build' in actions else 'selection_required'
                data['adaptation'] = dict(game_id=game['package_id'], status=status, pool_digest=digest)
        elif path == game_path + '/selection':
            actions.append('build')
            assert route.request.post_data_json == {'expected_pool_digest': digest, 'scene_ids': ['garden']}
            return route.fulfill(status=202, json={'status': 'pending'})
        elif path == game_path:
            data = dict(status='published', game=game) if published else dict(pool_digest=digest, pool={'scenes': [
                dict(id='garden', recommended=True), dict(id='workroom', recommended=False),
            ]})
        route.fulfill(json=data)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.getenv('MEMOIR_BROWSER_EXECUTABLE'))
        context = browser.new_context(viewport={'width': width, 'height': 900}, reduced_motion='reduce')
        context.add_cookies([{'name': 'copyme2_ui_locale', 'value': locale, 'url': base},
                             {'name': 'copyme2_ui_locale_source', 'value': 'fixed', 'url': base}])
        page = context.new_page()
        page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base + '/') else route.abort())
        user = dict(id=STAGE_OWNER, is_anonymous=anonymous, user_metadata={'ui_locale': locale})
        session = json.dumps(dict(access_token='fixture-only', user=user))
        install_supabase_fixture(page, 'window.supabase={createClient:()=>({auth:{getSession:async()=>({data:{session:'
            + session + '}}),onAuthStateChange:()=>({})}})};')
        install_atlas_fixture(page, lambda: atlas)
        page.route('**/api/v1/memoir/**', api)
        page.goto(base + '/memoir/interview/' + project_id)
        workspace = page.locator('#workspace-detail')
        footer = workspace.locator(':scope > .workspace-generation-bar')
        map_view = workspace.locator('.workspace-media-overview')
        close_view = workspace.get_by_role('button', name=close_label, exact=True)

        def expect_map_restored(opener):
            expect(map_view).to_be_visible()
            expect(workspace.locator('[data-story-game-workspace], [data-workspace-tab]')).to_have_count(0)
            expect(close_view).to_have_count(0)
            expect(opener).to_be_focused()

        expect(page.locator('.workspace-generation-bar')).to_have_count(1)
        expect(map_view).to_be_visible(timeout=15000)
        expect(close_view).to_have_count(0)
        expect(footer.get_by_role('button')).to_have_count(2)
        expect(footer).to_be_in_viewport(ratio=1)
        expect(workspace.locator('h2, [data-workspace-tab], .private-draft-status')).to_have_count(0)

        game_button = footer.get_by_role('button', name=game_label, exact=True)
        memoir_button = footer.get_by_role('button', name=memoir_label, exact=True)
        expect(memoir_button).to_be_visible()
        with page.expect_response(lambda response: response.url.endswith('/selection'), timeout=20000):
            game_button.click()
            expect(workspace.locator('.preview-spinner')).to_be_visible()
            expect(workspace.locator('.workspace-media-overview, [data-workspace-tab], iframe')).to_have_count(0)
        assert actions == ['formal', 'advance', 'consent', 'scenes', 'build']
        assert languages == [None]
        expect(page.locator('[data-auth-reminder-dialog], .story-game-modal, [data-scene-selection]')).to_have_count(0)
        expect(workspace.locator('.preview-spinner')).to_be_visible()
        expect(close_view).to_be_in_viewport(ratio=1)
        close_view.click()
        expect_map_restored(game_button)

        game_button.click()
        published = True
        iframe = workspace.locator('iframe.story-game-frame')
        expect(iframe).to_be_visible(timeout=15000)
        player = iframe.content_frame.locator('#memoir-game')
        expect(player).to_have_attribute('data-game-position', '80')
        iframe.content_frame.locator('.game-stage').focus()
        page.keyboard.down('ArrowRight')
        try:
            expect(player).not_to_have_attribute('data-game-position', '80')
        finally:
            page.keyboard.up('ArrowRight')
        frame_node = iframe.element_handle()
        page.locator('[data-action="toggle-chat-history"]').click()
        assert iframe.evaluate('(element, previous) => element === previous', frame_node)
        close_view.click()
        expect_map_restored(game_button)

        with page.expect_response(lambda response: draft_path + '/page?' in response.url, timeout=8000) as next_page:
            memoir_button.click()
        assert next_page.value.json()['records'] == passages[1:]
        expect(workspace.locator('[data-workspace-tab]')).to_have_count(3)
        expect(workspace.locator('.workspace-media-overview, iframe, [data-draft-locale], [data-action="retry-private-draft"]')).to_have_count(0)
        chapter = workspace.locator('.memoir-chapter')
        expect(chapter.get_by_role('heading')).to_have_text(title)
        expect(chapter.locator('p')).to_have_text(paragraphs)
        assert chapter.evaluate('(element) => getComputedStyle(element).borderTopWidth') == '0px'
        workspace.locator('[data-workspace-tab="timeline"]').click()
        expect(workspace.locator('.timeline-description')).to_have_text(paragraphs[1])
        expect(workspace.locator('.workspace-scroll h2')).to_have_count(0)
        expect(workspace.get_by_text('The city is a weak guess.')).to_have_count(0)
        expect(footer).to_be_in_viewport(ratio=1)
        assert languages == [None, locale]
        expect(close_view).to_be_in_viewport(ratio=1)
        close_view.click()
        expect_map_restored(memoir_button)

        game_button.click()
        expect(iframe).to_be_visible()
        expect(workspace.locator('[data-workspace-tab], .workspace-media-overview')).to_have_count(0)
        assert actions == ['formal', 'advance', 'consent', 'scenes', 'build']
        iframe.content_frame.locator('.game-stage').press('Escape')
        expect_map_restored(game_button)
        browser.close()
