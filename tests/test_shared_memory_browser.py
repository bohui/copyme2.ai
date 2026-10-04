"""Small browser contract: real local UI, real PostgreSQL story API.

Authentication/project metadata is controlled at the external API boundary.
Event edits and saved-draft reads go through the actual application router/RPC.
"""
import json
import os
import pytest
from playwright.sync_api import expect, sync_playwright

from test_shared_memory_events_postgres import (
    database, attachment_database, private_database, event_database, sql,
    rpc, five_rounds, run_controlled_composer, story_client, ROOT, OWNER,
)

pytestmark = pytest.mark.skipif(not os.getenv('MEMOIR_BROWSER_URL'), reason='Requires isolated source frontend')


def test_saved_coverage_and_timeline_tag_edit_survive_browser_reload(sql, tmp_path, monkeypatch):
    sources, lanes = five_rounds(sql)
    assert run_controlled_composer(sql, tmp_path, monkeypatch, lanes['composer_lane_id'])['status'] == 'saved'
    rpc(sql, 'retry_user_memoir_lane', "'project','composer'")
    event = rpc(sql, 'read_user_memory_events', "'project'")['events'][0]
    monkeypatch.setenv('STRIPE_PRICE_FAMILY','synthetic-price')
    entitlement = {'status':'paid','plan_key':'family_memoir_v1','family_tree':True,'timeline':True,'stripe_price_id':'synthetic-price'}
    client = story_client(sql, entitlement=entitlement)
    copy = json.loads((ROOT/'apps/web/messages/en-AU.json').read_text())['Memoir']['workspace']
    project = {'id':'project','revision':1,'profile':{'preferred_language':'en-AU'},'mode':'self','workspace_unlocked':False}
    def api(route):
        path = route.request.url.split('/api/v1/memoir')[-1]
        endpoint = path.split('?')[0]
        if endpoint.startswith('/story/private-draft') or endpoint.startswith('/story/events'):
            response = client.request(route.request.method, '/v1'+path, headers={'Authorization':'Bearer synthetic-author','Content-Type':'application/json'},
                                      content=route.request.post_data or None)
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
        context = browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
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
        page.locator('[data-workspace-tab="timeline"]').click()
        page.locator(f'[data-edit-memory-event="{event["id"]}"]').click()
        page.locator('#event-life-stage').select_option('adolescence')
        page.locator('#event-date-expression').fill('1966')
        page.locator('#event-date-precision').select_option('year')
        page.locator('#event-year-start').fill('1966')
        page.locator('#event-year-end').fill('1966')
        page.locator('#event-correction-statement').fill('I was an adolescent in 1966.')
        page.locator('#memory-event-edit-form button[type="submit"]').click()
        expect(page.locator('.timeline-list')).to_contain_text('1966')
        page.reload()
        page.locator('[data-workspace-tab="timeline"]').click()
        expect(page.locator('.timeline-list')).to_contain_text('1966')
        assert rpc(sql,'read_user_memory_events',"'project'")['events'][0]['id']==event['id']
        assert rpc(sql,'read_user_memory_events',"'project'")['completed_rounds']==5
        expect(page.locator('.private-draft-status details')).to_have_count(0)
        destination=ROOT/'output/preview-debug/issue6-event-edit.png'
        destination.parent.mkdir(parents=True,exist_ok=True)
        page.locator('#workspace-detail').screenshot(path=str(destination))
        browser.close()
