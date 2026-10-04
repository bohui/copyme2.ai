"""Small browser contract: real local UI, real PostgreSQL story API.

Authentication/project metadata is controlled at the external API boundary.
Event edits and saved-draft reads go through the actual application router/RPC.
"""
import json
import os
import socketserver
import sys
import threading
import pytest
from playwright.sync_api import expect, sync_playwright

from test_shared_memory_events_postgres import (
    database, attachment_database, private_database, event_database, sql,
    rpc, five_rounds, run_controlled_composer, story_client, ROOT, OWNER,
)

pytestmark = pytest.mark.skipif(not os.getenv('MEMOIR_BROWSER_URL'), reason='Requires isolated source frontend')


@pytest.mark.parametrize('input_kind', ['typed', 'dictated'])
def test_authenticated_browser_send_persists_the_original_and_its_input_kind(sql, tmp_path, monkeypatch, input_kind):
    """Real page, agent router/runtime/worker and PG; external auth, audio and model are synthetic."""
    import httpx
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from apps.api import agent_routes
    from apps.api.codex_runtime import CodexRuntime
    from apps.api import codex_worker_service
    from apps.api.codex_worker_service import CodexWorker
    from memoir_postgres_workflow import PostgresRest

    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP', '1')
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB', str(tmp_path/'tasks.sqlite'))
    profile = {'preferred_language':'en-AU', 'conversation_language':{'locale':'en-AU','source':'explicit','revision':1}}
    PostgresRest(sql, OWNER).storage().save_profile(profile)
    control = tmp_path/'provider.json'
    control.write_text(json.dumps({'reply':'Tell me more about that afternoon.'}))

    class Readiness(socketserver.BaseRequestHandler):
        def handle(self):
            pass

    # The worker's provider readiness connection is task-owned, with no shared ports.
    with socketserver.TCPServer(('127.0.0.1', 0), Readiness) as readiness:
        threading.Thread(target=readiness.serve_forever, daemon=True).start()
        provider = CodexWorker(home_root=tmp_path/'worker-homes',
            base_url=f'http://127.0.0.1:{readiness.server_address[1]}/v1',
            command=[sys.executable, str(ROOT/'tests/fixtures/issue6_controlled_app_server.py'), str(control)])
        monkeypatch.setenv('MEMORY_SPARK_CODEX_WORKER_SECRET', 'synthetic')
        monkeypatch.setattr(codex_worker_service, 'worker', provider)

        monkeypatch.setattr(agent_routes, 'authenticated_storage', lambda authorization: PostgresRest(sql, OWNER).storage())
        monkeypatch.setattr(agent_routes, 'runtime', CodexRuntime(home_root=tmp_path/'api-homes',
            worker_url='http://synthetic-worker.invalid', worker_secret='synthetic',
            worker_transport=httpx.ASGITransport(app=codex_worker_service.app)))
        app = FastAPI()
        app.include_router(agent_routes.router)
        project = {'id':'project','revision':1,'profile':profile,'mode':'self','workspace_unlocked':False}
        original = 'An afternoon by the sea.'
        sent = []
        with TestClient(app) as client, sync_playwright() as pw:
            def api(route):
                path = route.request.url.split('/api/v1/memoir')[-1]
                endpoint = path.split('?')[0]
                if endpoint == '/agent/turn':
                    sent.append(json.loads(route.request.post_data))
                    response = client.post('/v1/agent/turn', headers={'Authorization':'Bearer synthetic-author','Accept':'application/x-ndjson','Content-Type':'application/json'},
                                           content=route.request.post_data)
                    if response.status_code != 200 or '"type": "error"' in response.text:
                        print('Synthetic agent response:', response.status_code, response.text)
                    return route.fulfill(status=response.status_code, content_type='application/x-ndjson', body=response.text)
                data = {}
                if endpoint == '/agent/config': data = {'supabase_url':'https://auth.test','supabase_publishable_key':'public','auth_mode':'supabase'}
                elif endpoint in ('/agent/profile','/user/profile'): data = profile
                elif endpoint == '/projects/project': data = project
                elif endpoint == '/projects/project/journey': data = {'active_session':None}
                elif endpoint == '/story/state': data = {'family_features_enabled':False,'payment_features':[],
                    'recall_status':{'rounds_completed':0,'free_rounds':20,'payment_required':False,'paid':False}}
                elif endpoint == '/agent/family-context': data = {'family_features_enabled':False,'family_context':None}
                elif endpoint == '/agent/place-journey': data = {'place_journey':None}
                elif endpoint == '/story/transcriptions': data = {'text':original,'source':{'language':'en'}}
                elif endpoint == '/user/conversations' or endpoint.startswith('/projects/project/'): data = {'items':[]}
                route.fulfill(content_type='application/json', body=json.dumps(data))

            browser = pw.chromium.launch()
            base = os.environ['MEMOIR_BROWSER_URL']
            context = browser.new_context()
            context.add_cookies([{'name':'copyme2_ui_locale','value':'en-AU','url':base},
                                {'name':'copyme2_ui_locale_source','value':'fixed','url':base}])
            user = {'id':OWNER,'is_anonymous':False,'user_metadata':{'ui_locale':'en-AU'}}
            script = f"window.supabase={{createClient:()=>({{auth:{{getSession:async()=>({{data:{{session:{{access_token:'synthetic-author',user:{json.dumps(user)}}}}}}}),getUser:async()=>({{data:{{user:{json.dumps(user)}}}}}),onAuthStateChange:()=>({{}})}}}})}};"
            context.route('https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2', lambda route:route.fulfill(content_type='text/javascript', body=script))
            context.route('**/api/v1/memoir/**', api)
            context.add_init_script("localStorage.setItem('memory-spark-project','project');sessionStorage.setItem('memory-spark-chat-history:project','[{\"role\":\"user\",\"text\":\"A saved synthetic memory.\"}]');")
            context.add_init_script("""
                Object.defineProperty(navigator, 'mediaDevices', {value:{getUserMedia:async()=>({getTracks:()=>[{stop(){}}]})}});
                window.MediaRecorder = class {
                    static isTypeSupported(){return true;}
                    constructor(){this.state='inactive';this.mimeType='audio/webm';this.listeners={};}
                    addEventListener(name, callback){this.listeners[name]=callback;}
                    start(){this.state='recording';}
                    stop(){this.state='inactive';queueMicrotask(()=>{this.listeners.dataavailable?.({data:new Blob(['synthetic audio'])});this.listeners.stop?.();});}
                };
                window.AudioContext = class {
                    createMediaStreamSource(){return {connect(){}};}
                    createAnalyser(){return {fftSize:512,getByteTimeDomainData(data){data.fill(128);}};}
                    close(){return Promise.resolve();}
                };
            """)
            page = context.new_page()
            page.goto(base+'/memoir/interview/project')
            expect(page.locator('#chat-input')).to_be_enabled(timeout=30000)
            if input_kind == 'typed':
                page.locator('#chat-input').fill(original)
                page.locator('#chat-form button[type="submit"]').click()
            else:
                page.locator('[data-action="dictate"]').click()
                expect(page.locator('[data-action="accept-dictation"]')).to_be_visible()
                page.locator('[data-action="accept-dictation"]').click()
            expect(page.locator('.chat-scroll')).to_contain_text('Tell me more about that afternoon.', timeout=15000)
            assert len(sent) == 1
            kind = 'narrator_transcript' if input_kind == 'dictated' else 'narrator_chat'
            assert sent[0]['source_kind'] == kind
            view = rpc(sql, 'read_user_memory_events', "'project'")
            assert len(view['sources']) == 1 and view['sources'][0]['text'] == original
            assert view['sources'][0]['kind'] == kind and view['completed_rounds'] == 1
            browser.close()
        readiness.shutdown()


@pytest.mark.parametrize('width',[1440,390])
@pytest.mark.parametrize('correction', ['both', 'stage_only', 'date_only', 'stale'])
def test_saved_coverage_and_timeline_tag_edit_survive_browser_reload(sql, tmp_path, monkeypatch,width,correction):
    sources, lanes = five_rounds(sql)
    if correction in ('stage_only', 'stale'):
        initial = rpc(sql, 'read_user_memory_events', "'project'")['events'][0]
        rpc(sql, 'correct_user_memory_event', f"'project','{initial['id']}',1,'{{\"temporal\":{{\"expression\":\"1964\",\"precision\":\"year\",\"year_start\":1964,\"year_end\":1964}}}}'::jsonb,'The year was 1964.'")
    assert run_controlled_composer(sql, tmp_path, monkeypatch, lanes['composer_lane_id'])['status'] == 'saved'
    rpc(sql, 'retry_user_memoir_lane', "'project','composer'")
    event = rpc(sql, 'read_user_memory_events', "'project'")['events'][0]
    monkeypatch.setenv('STRIPE_PRICE_FAMILY','synthetic-price')
    entitlement = {'status':'paid','plan_key':'family_memoir_v1','family_tree':True,'timeline':True,'stripe_price_id':'synthetic-price'}
    client = story_client(sql, entitlement=entitlement)
    copy = json.loads((ROOT/'apps/web/messages/en-AU.json').read_text())['Memoir']['workspace']
    project = {'id':'project','revision':1,'profile':{'preferred_language':'en-AU'},'mode':'self','workspace_unlocked':False}
    concurrent_edit = []
    def api(route):
        path = route.request.url.split('/api/v1/memoir')[-1]
        endpoint = path.split('?')[0]
        if endpoint.startswith('/story/private-draft') or endpoint.startswith('/story/events'):
            if correction=='stale' and route.request.method=='PATCH' and not concurrent_edit:
                concurrent_edit.append(rpc(sql, 'correct_user_memory_event', f"'project','{event['id']}',{event['revision']},'{{\"life_stage\":\"young_adulthood\"}}'::jsonb,'I was a young adult then.'"))
            response = client.request(route.request.method, '/v1'+path, headers={'Authorization':'Bearer synthetic-author','Content-Type':'application/json'},
                                      content=route.request.post_data or None)
            if correction=='stale' and route.request.method=='PATCH':
                assert response.status_code==409 and response.headers['X-Error-Code']=='EVENT_REVISION_CONFLICT'
            if response.status_code >= 400:
                print('Synthetic story API response:',route.request.method,endpoint,response.status_code,response.text)
            return route.fulfill(status=response.status_code,content_type='application/json',body=response.text)
        data = {}
        if endpoint=='/agent/config': data={'supabase_url':'https://auth.test','supabase_publishable_key':'public','auth_mode':'supabase'}
        elif endpoint in ('/agent/profile','/user/profile'): data=project['profile']
        elif endpoint=='/projects/project': data=project
        elif endpoint=='/projects/project/journey': data={'active_session':None}
        elif endpoint=='/story/state': data={'family_features_enabled':True,'payment_features':['family_tree','timeline'],
            'recall_status':{'rounds_completed':5,'free_rounds':20,'payment_required':False,'paid':True}}
        elif endpoint=='/agent/family-context': data={'family_features_enabled':True,'family_context':{'project_id':'project','revision':0,'people':[],'relationships':[],'timeline':[]}}
        elif endpoint=='/agent/place-journey': data={'place_journey':None}
        elif endpoint=='/user/conversations' or endpoint.startswith('/projects/project/'): data={'items':[]}
        route.fulfill(content_type='application/json',body=json.dumps(data))
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        base = os.environ['MEMOIR_BROWSER_URL']
        context = browser.new_context(viewport={'width':width,'height':1000},reduced_motion='reduce')
        context.add_cookies([{'name':'copyme2_ui_locale','value':'en-AU','url':base},{'name':'copyme2_ui_locale_source','value':'fixed','url':base}])
        user={'id':OWNER,'is_anonymous':False,'user_metadata':{'ui_locale':'en-AU'}}
        script=f"window.supabase={{createClient:()=>({{auth:{{getSession:async()=>({{data:{{session:{{access_token:'synthetic-author',user:{json.dumps(user)}}}}}}}),getUser:async()=>({{data:{{user:{json.dumps(user)}}}}}),onAuthStateChange:()=>({{}})}}}})}};"
        context.route('https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2',lambda route:route.fulfill(content_type='text/javascript',body=script))
        context.route('**/api/v1/memoir/**',api)
        context.add_init_script("localStorage.setItem('memory-spark-project','project');sessionStorage.setItem('memory-spark-chat-history:project','[{\"role\":\"user\",\"text\":\"A saved synthetic memory.\"}]');")
        page=context.new_page()
        page.on('pageerror',lambda error: print('Browser error:',error))
        page.goto(base+'/memoir/interview/project')
        status=page.locator('.private-draft-status')
        expect(status).to_contain_text(copy['privateDraftSaved'].replace('{round}','5'),timeout=30000)
        expect(status).to_contain_text(copy['privateDraftUpdating'])
        expect(page.locator('#chat-input')).to_be_enabled()
        if width==390:
            page.screenshot(path='/tmp/issue6-before-mobile-tabs.png')
        page.locator('[data-workspace-tab="timeline"]').click()
        page.locator(f'[data-edit-memory-event="{event["id"]}"]').click()
        if correction!='date_only':
            page.locator('#event-life-stage').select_option('adolescence')
        if correction in ('both', 'date_only'):
            page.locator('#event-date-expression').fill('1966')
            page.locator('#event-date-precision').select_option('year')
            page.locator('#event-year-start').fill('1966')
            page.locator('#event-year-end').fill('1966')
        statement = 'I was an adolescent then.' if correction in ('stage_only','stale') else 'The year was 1966.' if correction=='date_only' else 'I was an adolescent in 1966.'
        page.locator('#event-correction-statement').fill(statement)
        box=page.locator('#memory-event-edit-form').bounding_box()
        assert box['x']>=0 and box['x']+box['width']<=width
        destination=ROOT/f'output/preview-debug/issue6-event-edit-form-{width}.png'
        destination.parent.mkdir(parents=True,exist_ok=True)
        page.locator('#workspace-detail').screenshot(path=str(destination))
        page.locator('#memory-event-edit-form button[type="submit"]').click()
        expect(page.locator('#memory-event-edit-form')).to_have_count(0)
        expected_year = '1964' if correction in ('stage_only','stale') else '1966'
        expect(page.locator('.timeline-list')).to_contain_text(expected_year)
        page.reload()
        page.locator('[data-workspace-tab="timeline"]').click()
        expect(page.locator('.timeline-list')).to_contain_text(expected_year)
        updated = rpc(sql,'read_user_memory_events',"'project'")['events'][0]
        expected_stage = 'young_adulthood' if correction=='stale' else event['life_stage'] if correction=='date_only' else 'adolescence'
        assert updated['id']==event['id'] and updated['life_stage']==expected_stage
        if correction in ('stage_only','stale'):
            assert updated['temporal']==event['temporal']
        assert rpc(sql,'read_user_memory_events',"'project'")['completed_rounds']==5
        expect(page.locator('.private-draft-status details')).to_have_count(0)
        destination=ROOT/'output/preview-debug/issue6-event-edit.png'
        destination.parent.mkdir(parents=True,exist_ok=True)
        page.locator('#workspace-detail').screenshot(path=str(destination))
        browser.close()
