"""Source UI checks with synthetic auth, stages and saved private draft."""

from browser_supabase_fixture import install_supabase_fixture
from browser_story_history_fixture import StoryHistoryFixture, STAGE_OWNER
import json
import os
import re
from pathlib import Path
import pytest
from playwright.sync_api import expect,sync_playwright

pytestmark=pytest.mark.skipif(not os.getenv('MEMOIR_BROWSER_URL'),reason='Requires isolated source frontend')
ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('locale',['en-AU','zh-CN'])
@pytest.mark.parametrize('mapped',[False,True])
def test_stage_rings_and_saved_private_draft(locale,mapped):
    copy=json.loads((ROOT/f'apps/web/messages/{locale}.json').read_text())
    workspace=copy['Memoir']['workspace']
    project={'id':'stage-project','revision':1,'profile':{'preferred_language':locale},'workspace_unlocked':False,'mode':'self'}
    # Round-five opt-in draft access remains a documented product gap. This
    # compatibility case checks a genuinely eligible, paid round-20 draft.
    rounds = 20 if mapped else 5
    history = StoryHistoryFixture(STAGE_OWNER, project['id'], 'fixture-only')
    place={'place':'Chengde','hierarchy':['Earth','China','Hebei','Chengde'],'granularity':'city','life_stage':'childhood'}
    if mapped:
        place.update(latitude=40.9515,longitude=117.9634)
        project['profile']['memory_places']=[place]
    stages={'childhood':{'word_equivalents':100,'percent':10,'color':'red'},
            'midlife':{'word_equivalents':300,'percent':30,'color':'amber'},
            'later_life':{'word_equivalents':1001,'percent':50,'color':'green'}}
    def api(route):
        if history.serve(route):
            return
        path=route.request.url.split('/api/v1/memoir')[-1].split('?')[0]
        data={}
        if path=='/agent/config':
            data={'supabase_url':'https://auth.test','supabase_publishable_key':'public','auth_mode':'supabase'}
        elif path in ('/agent/profile','/user/profile'):
            if route.request.method=='PATCH': project['profile'].update(route.request.post_data_json)
            data=project['profile']
        elif path=='/projects/stage-project':
            if route.request.method=='PATCH': project.update(route.request.post_data_json)
            data=project
        elif path=='/projects/stage-project/journey': data={'active_session':None}
        elif path=='/story/state': data={'recall_status':{'rounds_completed':rounds,'free_rounds':20,'payment_required':False,'paid':mapped},'family_features_enabled':False}
        elif path=='/story/readiness': data={'project_id':'stage-project','stages':stages}
        elif path=='/story/private-draft': data={'status':'ready','preview':{'title':'The fixture garden','text':'A safe synthetic private draft.'},'covered_round':rounds,'milestone':rounds,'revision':1,'updating':False}
        elif path=='/agent/place-journey': data={'place_journey':place if mapped else None}
        elif path=='/agent/turn': data={'reply':'What do you remember about Chengde?',
                                      'place_journey':place,'place_journey_change':{'changed':True},
                                      'profile_updates':{'story_focus':{'life_stage':'childhood'}}}
        elif path.endswith('/place-map'): data={'status':'READY' if mapped else 'NO_MATCH','target':place if mapped else None}
        elif path=='/user/conversations' or path.startswith('/projects/stage-project/'): data={'items':[]}
        return route.fulfill(content_type='application/json',body=json.dumps(data))
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=os.getenv('MEMOIR_BROWSER_EXECUTABLE'))
        base=os.environ['MEMOIR_BROWSER_URL']
        context=browser.new_context(viewport={'width':1440,'height':1000})
        context.add_cookies([{'name':'copyme2_ui_locale','value':locale,'url':base},
                            {'name':'copyme2_ui_locale_source','value':'fixed','url':base}])
        page=context.new_page()
        page.add_init_script("localStorage.setItem('memory-spark-project','stage-project');")
        user={'id':STAGE_OWNER,'is_anonymous':False,'user_metadata':{'ui_locale':locale}}
        script=f"window.supabase={{createClient:()=>({{auth:{{getSession:async()=>({{data:{{session:{{access_token:'fixture-only',user:{json.dumps(user)}}}}}}}),getUser:async()=>({{data:{{user:{json.dumps(user)}}}}}),onAuthStateChange:()=>({{}})}}}})}};"
        install_supabase_fixture(page, script)
        page.route('**/api/v1/memoir/**',api)
        page.goto(base+'/memoir/interview/stage-project')
        if not mapped:
            expect(page.locator('#chat-input')).to_be_visible(timeout=30000)
            expect(page.locator('.life-stage-navigator')).to_have_count(0)
            page.locator('#chat-input').fill('I grew up in Chengde.')
            with page.expect_response(lambda response: response.url.endswith('/place-map')):
                page.locator('.send-button').click()
            expect(page.locator('.assistant-message').last).to_contain_text('What do you remember about Chengde?',timeout=30000)
            # A place cue opens the workspace before geocoding succeeds.
            expect(page.locator('.story-shell.context-visible')).to_be_visible()
            expect(page.locator('#workspace-detail')).to_be_visible()
            expect(page.locator('.workspace-media-map, .workspace-media-gallery')).to_have_count(2)
            expect(page.locator('.life-stage-navigator')).to_be_visible()
            expect(page.locator('.place-journey-card, [data-workspace-tab]')).to_have_count(0)
            # Observed compatibility limitation, not satisfaction of round-five opt-in access.
            expect(page.locator('.private-draft-status')).to_have_count(0)
            browser.close()
            return
        expect(page.locator('[data-life-stage-tab="childhood"]')).to_be_visible(timeout=30000)
        expect(page.locator('[data-life-stage-tab="childhood"] .life-stage-readiness')).to_have_attribute('style','--readiness:10%')
        expect(page.locator('[data-life-stage-tab="midlife"] .life-stage-readiness')).to_have_attribute('style','--readiness:30%')
        expect(page.locator('[data-life-stage-tab="later_life"] .life-stage-readiness')).to_have_attribute('style','--readiness:50%')
        assert 'readiness-red' in page.locator('[data-life-stage-tab="childhood"] .life-stage-readiness').get_attribute('class')
        assert 'readiness-amber' in page.locator('[data-life-stage-tab="midlife"] .life-stage-readiness').get_attribute('class')
        assert 'readiness-green' in page.locator('[data-life-stage-tab="later_life"] .life-stage-readiness').get_attribute('class')
        expect(page.locator('.life-stage-navigator small, .life-stage-navigator .readiness-note')).to_have_count(0)
        expect(page.locator('#chat-input')).to_be_visible()
        expect(page.locator('[role="dialog"]:visible')).to_have_count(0)
        page.get_by_text(workspace['readSavedDraft'],exact=True).click()
        expect(page.locator('.private-draft-status')).to_contain_text('safe synthetic private draft')
        destination=ROOT/f'output/preview-debug/stage-rings-{locale}.png'
        destination.parent.mkdir(parents=True,exist_ok=True)
        page.locator('#workspace-detail').screenshot(path=str(destination))
        browser.close()


from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database, database, resolve


@pytest.mark.parametrize('locale', ['en-AU', 'zh-CN'])
@pytest.mark.parametrize('recovery', ['ready', 'delayed-fences'])
def test_canonical_stage_rings_render_saved_words_and_reload(sql, monkeypatch, locale, recovery):
    """Real source frontend, HTTP readiness route and isolated PostgreSQL.

    Only auth and unrelated workspace services are synthetic browser seams.
    Stage totals are never mocked: replies use the canonical commit RPC and
    exact stage evidence is persisted at the extraction boundary.
    """
    from io import BytesIO
    import math
    from PIL import Image
    from fastapi.testclient import TestClient
    from apps.api.main import create_app
    from apps.api.store import MemoryStore
    from memoir_postgres_workflow import PostgresRest
    from stage_progress_fixture import save_stage_source, link_stage
    from test_agent_commit_postgres import OWNER

    project_id = resolve(sql)['project_id']
    command = sql.command
    port = f" port={command[command.index('-p')+1]}" if '-p' in command else ''
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',
        f"host={command[command.index('-h')+1]}{port} user=postgres dbname=postgres")
    client = TestClient(create_app(MemoryStore(), story_storage_factory=lambda _: PostgresRest(sql, OWNER).storage()))
    place = {'place':'Synthetic Garden','hierarchy':['Earth','Australia','Synthetic Garden'],
             'granularity':'city','life_stage':'childhood','latitude':-33.8,'longitude':151.2}
    project = {'id':project_id,'revision':1,'mode':'self','profile':{
        'preferred_language':locale,'memory_places':[place]},'workspace_unlocked':False}
    history = StoryHistoryFixture(OWNER, project_id, 'fixture-only')
    reads = []
    delayed = {'source':None, 'pending_seen':False, 'faults':[], 'sent':[]}

    def save(stage, words):
        source = save_stage_source(sql, project_id, '忆' * words)
        link_stage(sql, project_id, source, stage)
        # A completed synthetic extractor; no worker/provider is invoked.
        sql("update public.user_narrator_source set processing_status='succeeded';")

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
            data = {'recall_status':{'rounds_completed':1,'free_rounds':20,'payment_required':False,'paid':True},
                    'family_features_enabled':False}
        elif path == '/story/readiness':
            if delayed['pending_seen'] and delayed['faults']:
                status = delayed['faults'].pop(0)
                delayed['sent'].append(status)
                return route.fulfill(status=status, content_type='application/json',
                    headers={'X-Error-Code':'LIFETIME_READ_STALE' if status == 409 else 'LIFETIME_READ_UNAVAILABLE'},
                    body=json.dumps({'detail':'Synthetic revision-fence change'}))
            response = client.get('/v1/story/readiness', params={'project_id':project_id})
            assert response.status_code == 200, response.text
            assert response.headers['cache-control'] == 'no-store'
            reads.append(response.json())
            if delayed['source'] and response.json().get('pending'):
                delayed['pending_seen'] = True
            return route.fulfill(status=response.status_code, content_type='application/json', body=response.text)
        elif path == '/agent/place-journey':
            data = {'place_journey':place}
        elif path == '/agent/turn':
            if recovery == 'delayed-fences':
                delayed['source'] = save_stage_source(sql, project_id, '忆' * 57)
                delayed['faults'] = [409,503]
            else:
                save('childhood', 57)
            data = {'conversation_saved':True,'reply':'A synthetic saved reply.'}
        elif path == '/user/conversations' or path.startswith('/projects/' + project_id + '/'):
            data = {'items':[]}
        route.fulfill(content_type='application/json', body=json.dumps(data))

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.getenv('MEMOIR_BROWSER_EXECUTABLE'))
        base = os.environ['MEMOIR_BROWSER_URL']
        context = browser.new_context(viewport={'width':1440,'height':1000})
        page = context.new_page()
        # All nonlocal requests are blocked except the synthetic SDK auth seam.
        page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base + '/') else route.abort())
        page.add_init_script("localStorage.setItem('memory-spark-project'," + json.dumps(project_id) + ");")
        user = {'id':OWNER,'is_anonymous':False,'user_metadata':{'ui_locale':locale}}
        install_supabase_fixture(page, "window.supabase={createClient:()=>({auth:{getSession:async()=>({data:{session:"
            + json.dumps({'access_token':'fixture-only','user':user})
            + "}}),getUser:async()=>({data:{user:" + json.dumps(user) + "}}),onAuthStateChange:()=>({})}})};")
        page.route('**/api/v1/memoir/**', api)
        page.goto(base + '/memoir/interview/' + project_id)
        ring = lambda stage: page.locator(f'[data-life-stage-tab="{stage}"] .life-stage-readiness')
        expect(ring('childhood')).to_be_visible(timeout=30000)
        expect(ring('childhood')).to_have_attribute('style', '--readiness:0%')
        assert reads and all(item['percent'] == 0 for item in reads[-1]['stages'].values())

        for stage, words in [('childhood',100),('midlife',300),('later_life',1000),('adolescence',157)]:
            save(stage, words)
        page.reload()
        expected = {'childhood':(10,'red',(185,72,67)), 'midlife':(30,'amber',(183,122,24)),
                    'later_life':(50,'green',(57,118,80)), 'adolescence':(15.7,'red',(185,72,67)),
                    'baby':(0,'red',(185,72,67))}

        def check_rings(values):
            page.wait_for_load_state('networkidle')
            boxes = {}
            for stage, (percent, color, rgb) in values.items():
                node = ring(stage)
                expect(node).to_have_attribute('style', f'--readiness:{percent}%')
                expect(node).to_have_class('life-stage-readiness readiness-' + color)
                expect(node).to_have_css('background-image', re.compile(r'conic-gradient\(.+'))
                boxes[stage] = node.bounding_box()
            # Take one viewport snapshot: hydration can replace individual DOM
            # nodes between Playwright's element screenshot/scroll operations.
            image = Image.open(BytesIO(page.screenshot())).convert('RGB')
            for stage, (percent, color, rgb) in values.items():
                box = boxes[stage]
                center = (box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
                radius = min(box['width'], box['height']) / 2 - 2
                pixels = [image.getpixel((int(center[0] + radius * math.sin(i * math.tau / 720)),
                                         int(center[1] - radius * math.cos(i * math.tau / 720)))) for i in range(720)]
                fraction = sum(max(abs(a-b) for a,b in zip(pixel,rgb)) < 25 for pixel in pixels) / len(pixels)
                assert fraction == pytest.approx(percent / 100, abs=.04), (stage, fraction, percent)

        check_rings(expected)
        if recovery == 'delayed-fences':
            page.clock.install()
        page.locator('#chat-input').fill('A synthetic childhood memory.')
        page.locator('.send-button').click()
        expect(page.locator('.assistant-message').last).to_contain_text('A synthetic saved reply.')
        if recovery == 'delayed-fences':
            page.wait_for_load_state('networkidle')
            assert delayed['pending_seen'] and reads[-1]['pending']
            with page.expect_response(lambda response: '/story/readiness?' in response.url and response.status == 409) as stale:
                page.clock.fast_forward(120_000)
            stale.value.finished()
            assert delayed['sent'] == [409]
            expect(ring('childhood')).to_have_attribute('style', '--readiness:10%')
            with page.expect_response(lambda response: '/story/readiness?' in response.url and response.status == 503) as unavailable:
                page.clock.fast_forward(120_000)
            unavailable.value.finished()
            assert delayed['sent'] == [409,503]
            expect(ring('childhood')).to_have_attribute('style', '--readiness:10%')
            link_stage(sql, project_id, delayed['source'], 'childhood')
            sql("update public.user_narrator_source set processing_status='succeeded';")
            with page.expect_response(lambda response: '/story/readiness?' in response.url and response.status == 200) as recovered:
                page.clock.fast_forward(16_000)
            recovered.value.finished()
        expected['childhood'] = (15.7,'red',(185,72,67))
        check_rings(expected)
        before_reload = reads[-1]['stages']
        page.reload()
        check_rings(expected)
        assert reads[-1]['stages'] == before_reload
        destination = ROOT / f'output/preview-debug/canonical-stage-rings-{locale}-{recovery}.png'
        destination.parent.mkdir(parents=True, exist_ok=True)
        page.locator('.life-stage-navigator').screenshot(path=str(destination))
        browser.close()
    client.close()
