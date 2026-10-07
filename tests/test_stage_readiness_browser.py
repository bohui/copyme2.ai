"""Source UI checks with synthetic auth, stages and saved private draft."""
import json
import os
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
    place={'place':'Chengde','hierarchy':['Earth','China','Hebei','Chengde'],'granularity':'city','life_stage':'childhood'}
    if mapped:
        place.update(latitude=40.9515,longitude=117.9634)
        project['profile']['memory_places']=[place]
    stages={'childhood':{'word_equivalents':100,'percent':10,'color':'red'},
            'midlife':{'word_equivalents':300,'percent':30,'color':'amber'},
            'later_life':{'word_equivalents':1001,'percent':50,'color':'green'}}
    def api(route):
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
        elif path=='/story/state': data={'recall_status':{'rounds_completed':5,'free_rounds':20,'payment_required':False,'paid':False},'family_features_enabled':False}
        elif path=='/story/readiness': data={'project_id':'stage-project','stages':stages}
        elif path=='/story/private-draft': data={'status':'ready','preview':{'title':'The fixture garden','text':'A safe synthetic private draft.'},'milestone':5,'revision':1,'updating':False}
        elif path=='/agent/place-journey': data={'place_journey':place if mapped else None}
        elif path=='/agent/turn': data={'reply':'What do you remember about Chengde?',
                                      'place_journey':place,'place_journey_change':{'changed':True},
                                      'profile_updates':{'story_focus':{'life_stage':'childhood'}}}
        elif path.endswith('/place-map'): data={'status':'READY' if mapped else 'NO_MATCH','target':place if mapped else None}
        elif path=='/user/conversations' or path.startswith('/projects/stage-project/'): data={'items':[]}
        return route.fulfill(content_type='application/json',body=json.dumps(data))
    with sync_playwright() as pw:
        browser=pw.chromium.launch()
        base=os.environ['MEMOIR_BROWSER_URL']
        context=browser.new_context(viewport={'width':1440,'height':1000})
        context.add_cookies([{'name':'copyme2_ui_locale','value':locale,'url':base},
                            {'name':'copyme2_ui_locale_source','value':'fixed','url':base}])
        page=context.new_page()
        page.add_init_script("localStorage.setItem('memory-spark-project','stage-project');")
        user={'id':'fixture-owner','is_anonymous':False,'user_metadata':{'ui_locale':locale}}
        script=f"window.supabase={{createClient:()=>({{auth:{{getSession:async()=>({{data:{{session:{{access_token:'fixture-only',user:{json.dumps(user)}}}}}}}),getUser:async()=>({{data:{{user:{json.dumps(user)}}}}}),onAuthStateChange:()=>({{}})}}}})}};"
        page.route('https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2',lambda route:route.fulfill(content_type='text/javascript',body=script))
        page.route('**/api/v1/memoir/**',api)
        page.goto(base+'/memoir/interview/stage-project')
        if not mapped:
            expect(page.locator('#chat-input')).to_be_visible(timeout=30000)
            expect(page.locator('.life-stage-navigator')).to_have_count(0)
            page.locator('#chat-input').fill('I grew up in Chengde.')
            with page.expect_response(lambda response: response.url.endswith('/place-map')):
                page.locator('.send-button').click()
            expect(page.locator('.assistant-message').last).to_contain_text('What do you remember about Chengde?',timeout=30000)
            expect(page.locator('.story-shell.conversation-only')).to_be_visible()
            expect(page.locator('#workspace-detail, .life-stage-navigator, .workspace-media-overview')).to_have_count(0)
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
