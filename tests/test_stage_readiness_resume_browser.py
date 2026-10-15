"""Actual saved-project Begin navigation with durable, provider-free extraction."""
import json
import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import expect, sync_playwright

from apps.api.main import create_app
from apps.api.store import MemoryStore
from browser_story_history_fixture import StoryHistoryFixture
from browser_supabase_fixture import install_supabase_fixture
from memoir_postgres_workflow import PostgresRest
from stage_progress_fixture import save_stage_source
from test_agent_commit_postgres import OWNER
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database, database, resolve
from test_shared_memory_events_postgres import literal, rpc


pytestmark = pytest.mark.skipif(not os.getenv('MEMOIR_BROWSER_URL'), reason='Requires isolated source frontend')
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('locale', ['en-AU', 'zh-CN'])
def test_saved_project_begin_keeps_pending_stage_recovery_alive(sql, monkeypatch, locale):
    project_id = resolve(sql)['project_id']

    def extract(source):
        ref = {'source_id':source['id'], 'version':source['version'], 'quote':source['text'],
               'char_start':0, 'char_end':len(source['text'])}
        cue = {**ref, 'quote':source['text'][:2], 'char_end':2}
        proposal = {'kind':'event', 'title':'Synthetic childhood', 'life_stage':'childhood',
                    'source_refs':[ref], 'stage_evidence':[cue]}
        rpc(sql, 'apply_user_memory_events', f"{literal(project_id)},"
            f"{literal([{'id':source['id'],'version':source['version']}])}::jsonb,{literal([proposal])}::jsonb")

    extract(save_stage_source(sql, project_id, '童' * 100))
    pending_source = save_stage_source(sql, project_id, '学' * 200)
    command = sql.command
    port = f" port={command[command.index('-p')+1]}" if '-p' in command else ''
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',
        f"host={command[command.index('-h')+1]}{port} user=postgres dbname=postgres")
    place = {'place':'Synthetic Garden', 'hierarchy':['Earth','Australia','Synthetic Garden'],
             'granularity':'city', 'life_stage':'childhood', 'latitude':-33.8, 'longitude':151.2}
    project = {'id':project_id, 'revision':1, 'mode':'self', 'workspace_unlocked':False,
               'profile':{'preferred_language':locale, 'memory_places':[place]}}
    history = StoryHistoryFixture(OWNER, project_id, 'fixture-only')
    reads = []

    with TestClient(create_app(MemoryStore(), story_storage_factory=lambda _: PostgresRest(sql, OWNER).storage())) as client:
        def api(route):
            if history.serve(route):
                return
            path = route.request.url.split('/api/v1/memoir')[-1].split('?')[0]
            data = {}
            if path == '/agent/config':
                data = {'supabase_url':'https://auth.test','supabase_publishable_key':'public','auth_mode':'supabase'}
            elif path in ('/agent/profile','/user/profile'):
                data = project['profile']
            elif path == '/projects/' + project_id:
                data = project
            elif path.endswith('/journey'):
                data = {'active_session':None}
            elif path == '/story/state':
                data = {'recall_status':{'rounds_completed':2,'free_rounds':20,'payment_required':False,'paid':True},
                        'family_features_enabled':False}
            elif path == '/story/readiness':
                response = client.get('/v1/story/readiness', params={'project_id':project_id})
                assert response.status_code == 200, response.text
                assert response.headers['cache-control'] == 'no-store'
                data = response.json()
                reads.append(data)
            elif path == '/agent/place-journey':
                data = {'place_journey':place}
            elif path == '/user/conversations':
                data = {'items':[], 'resume_project_id':project_id}
            assert not (path == '/projects' and route.request.method == 'POST'), 'Resume must preserve the saved project'
            assert path != '/agent/turn', 'Navigation must not create another narrator turn'
            route.fulfill(content_type='application/json', body=json.dumps(data))

        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=os.getenv('MEMOIR_BROWSER_EXECUTABLE'))
            base = os.environ['MEMOIR_BROWSER_URL']
            page = browser.new_page(viewport={'width':1440,'height':1000})
            page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base + '/') else route.abort())
            page.add_init_script("localStorage.setItem('memory-spark-project'," + json.dumps(project_id) + ");")
            user = {'id':OWNER, 'is_anonymous':False, 'user_metadata':{'ui_locale':locale}}
            install_supabase_fixture(page, "window.supabase={createClient:()=>({auth:{getSession:async()=>({data:{session:"
                + json.dumps({'access_token':'fixture-only','user':user})
                + "}}),getUser:async()=>({data:{user:" + json.dumps(user)
                + "}}),onAuthStateChange:()=>({})}})};")
            page.route('**/api/v1/memoir/**', api)
            with page.expect_response(lambda response: '/story/readiness?' in response.url) as boot_read:
                page.goto(base + '/memoir')
            boot_read.value.finished()
            begin = page.locator('[data-action="start-story"][data-mode="self"]')
            expect(begin).to_be_visible(timeout=30000)
            page.wait_for_load_state('networkidle')
            assert reads and reads[-1]['pending'] and reads[-1]['stages']['childhood']['percent'] == 10
            begin.click()
            expect(page).to_have_url(re.compile('/memoir/interview/' + project_id + '$'))
            ring = page.locator('[data-life-stage-tab="childhood"] .life-stage-readiness')
            expect(ring).to_have_attribute('style', '--readiness:10%')
            page.wait_for_load_state('networkidle')
            extract(pending_source)  # Real extraction finishes after the resume navigation.
            # Boot already scheduled native timers. Installing a fake clock
            # here mixes timer implementations, and virtual jumps can expire
            # the read timeout before real Auth/HTTP work finishes. Exercise
            # the actual recovery timer with the same 60-second bound.
            expect(ring).to_have_attribute('style', '--readiness:30%', timeout=60000)
            after_resume = ring.get_attribute('style')
            after_color = ring.get_attribute('class')
            # Characterize the failure completely: reload reads 30 immediately,
            # even when the cancelled resume path never resumed polling.
            page.reload()
            expect(ring).to_have_attribute('style', '--readiness:30%')
            page.wait_for_load_state('networkidle')
            assert after_resume == '--readiness:30%', f'Resume stayed at {after_resume}; reload recovered 30%; reads={reads}'
            assert 'readiness-amber' in after_color
            assert reads[-1]['stages']['childhood']['word_equivalents'] == 300
            destination = ROOT / f'output/preview-debug/stage-rings-resume-{locale}.png'
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Hydration may replace the navigator node while screenshot waits
            # for fonts. Capture viewport pixels using its current bounds.
            page.screenshot(path=str(destination), clip=page.locator('.life-stage-navigator').bounding_box())
            browser.close()
