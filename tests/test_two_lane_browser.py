"""Issue 70 source frontend: B readiness follows an independently saved reply."""
import json
import os
import pytest
from playwright.sync_api import expect,sync_playwright
from browser_supabase_fixture import install_supabase_fixture
from browser_story_history_fixture import StoryHistoryFixture,STAGE_OWNER

pytestmark=pytest.mark.skipif(not os.getenv('MEMOIR_BROWSER_URL'),reason='Requires isolated source frontend')


@pytest.mark.parametrize('locale',['en-AU','zh-CN'])
@pytest.mark.parametrize('strategy',['comfort','explore','shape'])
def test_saved_reply_precedes_background_workspace(locale,strategy):
    project={'id':'issue70-browser','revision':1,'profile':{'preferred_language':locale, 'name':'Before background',
        'profile_automation':{'revision':1}},'mode':'self','workspace_unlocked':False}
    history=StoryHistoryFixture(STAGE_OWNER,project['id'],'fixture-only')
    place={'schema_version':1,'place':'Hobart','hierarchy':['Earth','Australia','Tasmania','Hobart'],
        'granularity':'city','latitude':-42.88,'longitude':147.32,'status':'active','source_sequence':1,'revision':1}
    reply=({'comfort':'Where would you like to begin?','explore':'What do you remember about the river?','shape':'Was that before or after the move?'}[strategy]
        if locale=='en-AU' else {'comfort':'您想从哪里聊起？','explore':'您还记得河边的什么？','shape':'那是在搬家之前还是之后？'}[strategy])
    saved=False;ready=False;withdrawn=False;reads=[]
    def api(route):
        nonlocal saved,reply
        path=route.request.url.split('/api/v1/memoir')[-1].split('?')[0]
        if history.serve(route):return
        if path=='/agent/config':data={'supabase_url':'https://auth.test','supabase_publishable_key':'public','auth_mode':'supabase','show_draft_updates':False}
        elif path=='/projects/issue70-browser':data=project
        elif path in ('/agent/profile','/user/profile'):data=project['profile']
        elif path=='/user/flow':data={'flow':None}
        elif path=='/story/access':data={'allowed':True,'completed_rounds':0,'payment_required':False}
        elif path=='/story/readiness':
            reads.append(saved);data={'stages':{},'pending':not ready}
            if ready:
                data['derived_workspace']={'project_id':project['id'],'source_revision':1,'policy_epoch':1,'places':[place],'authoritative':True}
                data['profile']=({'profile_automation':{'revision':3}} if withdrawn else
                    {'name':'After background','avatar_style':'female','profile_automation':{'revision':2}})
        elif path=='/story/private-draft':data={'status':'empty','preview':None,'milestone':None,'pending':False}
        elif path=='/agent/place-journey':data={'place_journey':place if ready else None}
        elif path=='/agent/turn':
            packet=route.request.post_data_json
            if history.rows:reply='What did you grow in your garden?' if locale=='en-AU' else '您的花园里种了什么？'
            record=history.save(packet,reply);saved=True
            data={'reply':reply,'project_id':project['id'],'client_turn_id':record['client_turn_id'],
                'accepted_source_id':record['_source']['id'],'reply_id':'saved-reply','conversation_saved':True}
            return route.fulfill(content_type='application/x-ndjson',body='\n'.join(json.dumps(e) for e in [
                {'type':'conversation_saved','data':data},{'type':'result','data':data}])+'\n')
        elif path.endswith('/place-map'):data={'status':'READY','target':place}
        elif path=='/user/conversations' or path.startswith('/projects/issue70-browser/'):data={'items':[]}
        else:return route.fulfill(status=503,content_type='application/json',body='{}')
        return route.fulfill(content_type='application/json',body=json.dumps(data))
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=os.getenv('MEMOIR_BROWSER_EXECUTABLE'))
        base=os.environ['MEMOIR_BROWSER_URL'];context=browser.new_context(viewport={'width':1440,'height':1000})
        context.add_cookies([{'name':'copyme2_ui_locale','value':locale,'url':base},
            {'name':'copyme2_ui_locale_source','value':'fixed','url':base}])
        page=context.new_page()
        page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(base+'/') else route.abort())
        page.add_init_script("localStorage.setItem('memory-spark-project','issue70-browser');")
        user={'id':STAGE_OWNER,'is_anonymous':False,'user_metadata':{'ui_locale':locale}}
        install_supabase_fixture(page,f"window.supabase={{createClient:()=>({{auth:{{getSession:async()=>({{data:{{session:{{access_token:'fixture-only',user:{json.dumps(user)}}}}}}}),getUser:async()=>({{data:{{user:{json.dumps(user)}}}}}),onAuthStateChange:()=>({{}})}}}})}};")
        page.route('**/api/v1/memoir/**',api)
        try:
            page.goto(base+'/memoir/interview/issue70-browser')
            expect(page.locator('#chat-input')).to_be_visible(timeout=30000)
            expect(page.locator('.profile-trigger-name')).to_have_text('Before background')
            page.locator('#chat-input').fill('I grew up in Hobart by the river.' if locale=='en-AU' else '我在霍巴特的河边长大。')
            page.locator('.send-button').click()
            expect(page.locator('.assistant-message').last).to_contain_text(reply,timeout=30000)
            expect(page.locator('.send-button')).to_be_enabled()
            assert saved and not ready and len(history.rows)==1
            page.locator('#chat-input').fill('An unfinished draft')
            ready=True
            expect(page.locator('.place-journey-heading')).to_contain_text('Hobart',timeout=30000)
            expect(page.locator('.profile-trigger-name')).to_have_text('After background')
            expect(page.locator('.life-stage-figure img').first).to_have_attribute('src', '/static/timeline_avatar_baby_female.png')
            expect(page.locator('#chat-input')).to_have_value('An unfinished draft')
            assert any(reads)
            expect(page.locator('.assistant-message').last).to_contain_text(reply)
            assert len(history.rows)==1
            # The strategy lives on the server; the chat exposes the response and
            # ordinary controls. A redirect can continue while B is already ready.
            for label in ['Comfort','Explore','Shape']:
                expect(page.get_by_role('button',name=label,exact=True)).to_have_count(0)
            withdrawn=True
            page.locator('#chat-input').fill("Let's talk about my garden." if locale=='en-AU' else '我想聊聊我的花园。')
            page.locator('.send-button').click()
            expect(page.locator('.assistant-message').last).to_contain_text('garden' if locale=='en-AU' else '花园',timeout=30000)
            expect(page.locator('.send-button')).to_be_enabled()
            expect(page.locator('.place-journey-heading')).to_contain_text('Hobart')
            expect(page.locator('.profile-trigger-name')).not_to_have_text('After background')
            expect(page.locator('.life-stage-figure img').first).to_have_attribute('src', '/static/timeline_avatar_baby_male.png')
            assert len(history.rows)==2
        finally:
            context.close();browser.close()
