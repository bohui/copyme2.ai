"""Source UI → real authenticated conversation/worker/readback; controlled model."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from playwright.sync_api import expect,sync_playwright

from browser_supabase_fixture import install_supabase_fixture
from browser_story_history_fixture import StoryHistoryFixture
from test_background_skill_workflow import database,sql,event_database,private_database,attachment_database
from test_conversation_attribution import Conversation,empty,episode
from test_agent_commit_postgres import OWNER

pytestmark=pytest.mark.skipif(not os.getenv('MEMOIR_BROWSER_URL'),reason='Requires isolated source frontend')


@pytest.mark.parametrize('locale,thinking',[('en-AU',True),('zh-CN',True),('en-AU',False)])
def test_late_skill_save_renders_on_real_turn_after_reload(sql,tmp_path,monkeypatch,locale,thinking):
    monkeypatch.setenv('MEMORY_SPARK_SHOW_THINKING_STEPS','1' if thinking else '0')
    sql('update public.lifetime_two_lane_rollout set strategy_enabled=false,strategy_shadow=false;')
    conversation=Conversation(sql,tmp_path,monkeypatch,
        lambda packet:{**empty(packet),'events':[episode(packet,packet['sources'][0]['text'])]},strategy='shape')
    with conversation.client:
        first=conversation.say('I repaired a bicycle in our shed.')
        project_id=conversation.project
        history=StoryHistoryFixture(OWNER,project_id,'fixture-only')
        turn=sql('select client_turn_id from public.user_narrator_source limit 1;').stdout.strip()
        history.save({'project_id':project_id,'client_turn_id':turn,'conversation_text':'I repaired a bicycle in our shed.'},first['reply'])
        project={'id':project_id,'revision':1,'mode':'self','profile':{'preferred_language':locale},'workspace_unlocked':False}
        reads=[]
        def api(route):
            if history.serve(route):return
            path=route.request.url.split('/api/v1/memoir')[-1].split('?')[0]
            data={}
            if path=='/agent/config':
                data={'supabase_url':'https://auth.test','supabase_publishable_key':'public','auth_mode':'supabase',
                    'show_thinking_steps':thinking,'show_draft_updates':False}
            elif path in ('/agent/profile','/user/profile'):data=project['profile']
            elif path=='/projects/'+project_id:data=project
            elif path.endswith('/journey'):data={'active_session':None}
            elif path=='/story/state':data={'recall_status':{'rounds_completed':1,'free_rounds':20,'payment_required':False,'paid':True},'family_features_enabled':False}
            elif path=='/agent/place-journey':data={'place_journey':None}
            elif path.endswith('/story-game'):
                data={'formal':{'run':None,'edition':None},'adaptation':None,
                    'eligibility':{'available':False,'reasons':['completion_required','adaptation_consent_required'],'revision':0,'consent_revision':0}}
            elif path=='/story/readiness':
                response=conversation.client.get('/v1/story/readiness',params={'project_id':project_id})
                assert response.status_code==200,response.text
                reads.append(response.json())
                return route.fulfill(status=response.status_code,content_type='application/json',body=response.text)
            elif path=='/agent/turn':
                packet=route.request.post_data_json
                response=conversation.client.post('/v1/agent/turn',json=packet)
                assert response.status_code==200,response.text
                history.save(packet,response.json()['reply'])
                return route.fulfill(content_type='application/json',body=response.text)
            elif path=='/story/game':
                response=conversation.client.post('/v1/story/game',json=route.request.post_data_json)
                assert response.status_code==200,response.text
                return route.fulfill(content_type='application/json',body=response.text)
            route.fulfill(content_type='application/json',body=json.dumps(data))
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=os.getenv('MEMOIR_BROWSER_EXECUTABLE'),headless=True)
            context=browser.new_context(viewport={'width':1280,'height':900},locale=locale)
            page=context.new_page()
            errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            base=os.environ['MEMOIR_BROWSER_URL']
            page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(base+'/') else route.abort())
            user={'id':OWNER,'is_anonymous':False,'user_metadata':{'ui_locale':locale}}
            session={'access_token':'fixture-only','user':user}
            install_supabase_fixture(page,"window.supabase={createClient:()=>({auth:{getSession:async()=>({data:{session:"
                +json.dumps(session)+"}}),getUser:async()=>({data:{user:"+json.dumps(user)+"}}),onAuthStateChange:()=>({})}})};")
            page.route('**/api/v1/memoir/**',api)
            page.goto(base+'/memoir/interview/'+project_id)
            page.wait_for_load_state('networkidle')
            expect(page.locator('#chat-input')).to_be_visible(timeout=30000)
            # No timeline model has executed; a restored history row has no trace.
            assert conversation.admissions==[]
            expect(page.locator('[data-step-status="saved"][data-execution="model"]')).to_have_count(0)
            # The browser sends a new actual A request before the delayed B run.
            page.locator('#chat-input').fill('I later painted that bicycle blue.')
            with page.expect_response(lambda response:'/api/v1/memoir/agent/turn' in response.url) as sent:
                page.locator('.send-button').click()
            assert sent.value.status==200
            expect(page.locator('.assistant-message').last).to_contain_text('What happened next?',timeout=30000)
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(conversation.drain).result(timeout=30)
            step=page.locator(f'[data-message-id="history-{history.rows[0]["id"]}-assistant"]').locator('[data-lane="B"][data-execution="model"][data-step-status="saved"]')
            if thinking:
                try:
                    expect(step.filter(has_text='memoir-author-timeline')).to_have_count(1,timeout=15000)
                except AssertionError as error:
                    raise AssertionError(json.dumps({'errors':errors,'progress':[item.get('skill_progress') for item in reads],
                        'messages':page.locator('.assistant-message').all_text_contents()},ensure_ascii=False)) from error
                expect(step.filter(has_text='memoir-memory-context')).to_have_count(1)
                assert any(item.get('skill_progress') for item in reads)
                assert 'question_pool' not in json.dumps(reads)
            else:
                expect(page.locator('.agent-loop')).to_have_count(0)
            count=len(conversation.admissions)
            expect(page.locator('[data-story-game]')).to_be_visible(timeout=30000)
            page.locator('[data-story-game]').click()
            copy=json.loads((Path(__file__).parents[1]/f'apps/web/messages/{locale}.json').read_text())
            expect(page.locator('.story-game-modal')).to_contain_text(copy['Memoir']['game']['completeIntro'])
            page.locator('[data-close-game]').click()
            assert len(conversation.admissions)==count
            page.reload()
            expect(page.locator('#chat-input')).to_be_visible(timeout=30000)
            if thinking:
                expect(page.locator('[data-lane="B"][data-step-status="saved"]').filter(has_text='memoir-author-timeline')).to_have_count(2,timeout=30000)
                expect(page.locator('[data-lane="B"][data-step-status="saved"]').first).to_contain_text(copy['Memoir']['trace']['status']['saved'])
            browser.close()
