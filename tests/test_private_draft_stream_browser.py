"""Built frontend checks with controlled, incremental draft and chat transport."""
import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from browser_supabase_fixture import install_supabase_fixture
from browser_story_history_fixture import StoryHistoryFixture, STAGE_OWNER

pytestmark = pytest.mark.skipif(not os.getenv('MEMOIR_BROWSER_URL'), reason='Requires isolated source frontend')
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('drafts', [False, True])
@pytest.mark.parametrize('thinking', [False, True])
def test_progressive_composer_drafts_live_inside_collapsible_thinking_steps(drafts, thinking):
    base = os.environ['MEMOIR_BROWSER_URL']
    project = {'id':'draft-debug-project', 'revision':1, 'mode':'self', 'profile':{'preferred_language':'zh-CN'}}
    history = StoryHistoryFixture(STAGE_OWNER, project['id'], 'fixture-only')
    catalog = json.loads((ROOT/'apps/web/messages/zh-CN.json').read_text())['Memoir']
    recall = {'rounds_completed':5, 'free_rounds':20, 'paid':False, 'payment_required':False}
    retries = []
    place = {'place':'Chengde', 'latitude':40.9515, 'longitude':117.9634,
             'hierarchy':['Earth','China','Hebei','Chengde'], 'granularity':'city', 'life_stage':'childhood',
             'period':'1980s', 'research_period':'1980s'}
    picture = {'title':'Chengde garden', 'image_url':'/static/timeline_avatar_child_male.png',
               'source_url':'https://archive.example/garden', 'date_expression':'1983-04-01',
               'latitude':place['latitude'], 'longitude':place['longitude'], 'allowed_actions':{'embed':True}}
    place['pictures'] = [picture]
    project['profile']['memory_places'] = [place]

    def api(route):
        if history.serve(route): return
        path = route.request.url.split('/api/v1/memoir')[-1].split('?')[0]
        data = {}
        if path == '/agent/config':
            data = {'supabase_url':'https://auth.test', 'supabase_publishable_key':'public', 'auth_mode':'supabase',
                    'show_thinking_steps':thinking, 'show_draft_updates':drafts}
        elif path in ('/agent/profile','/user/profile'): data = project['profile']
        elif path == '/projects/draft-debug-project': data = project
        elif path == '/projects/draft-debug-project/journey': data = {'active_session':None}
        elif path == '/story/state': data = {'recall_status':recall,
            'family_features_enabled':project.get('workspace_unlocked', False), 'payment_features':['family_tree','timeline']}
        elif path == '/agent/family-context': data = {'family_features_enabled':True, 'family_context':{'people':[], 'relationships':[], 'timeline':[]}}
        elif path == '/agent/place-journey': data = {'place_journey':place}
        elif path.endswith('/place-map'): data = {'status':'READY', 'target':place}
        elif path.endswith('/photos'): data = {'status':'READY', 'items':[picture], 'complete':True}
        elif path == '/agent/turn':
            saved = {'reply':'What do you remember about your garden?', 'conversation_saved':True, 'recall_status':recall}
            events = [{'type':'progress','data':{'id':'analysis','detail':'测试思考步骤','status':'completed'}},
                      {'type':'conversation_saved','data':saved}, {'type':'result','data':saved}]
            return route.fulfill(content_type='application/x-ndjson', body='\n'.join(json.dumps(e) for e in events)+'\n')
        elif path == '/story/private-draft/retry': retries.append(route.request.post_data_json)
        elif path.startswith('/projects/draft-debug-project/') or path == '/user/conversations': data = {'items':[]}
        return route.fulfill(content_type='application/json', body=json.dumps(data))

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width':1440,'height':1000})
        context.add_cookies([{'name':'copyme2_ui_locale','value':'zh-CN','url':base},
                            {'name':'copyme2_ui_locale_source','value':'fixed','url':base}])
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        user = {'id':STAGE_OWNER, 'is_anonymous':False, 'user_metadata':{'ui_locale':'zh-CN'}}
        install_supabase_fixture(page, f"window.supabase={{createClient:()=>({{auth:{{getSession:async()=>({{data:{{session:{{access_token:'fixture-only',user:{json.dumps(user)}}}}}}}),getUser:async()=>({{data:{{user:{json.dumps(user)}}}}}),onAuthStateChange:()=>({{}})}}}})}};")
        page.add_init_script("""
            localStorage.setItem('memory-spark-project','draft-debug-project');
            const originalFetch = window.fetch.bind(window);
            window.draftCalls = 0;
            window.fetch = async (url, options) => {
                if (!String(url).includes('/story/private-draft?')) return originalFetch(url,options);
                window.draftCalls++;
                const error = sessionStorage.getItem('composer-error-fixture');
                if (options.headers.Accept !== 'application/x-ndjson') {
                    if (!error) throw Error('Missing draft streaming Accept');
                    return new Response(JSON.stringify({error:'DRAFT_UNAVAILABLE',updating:false}),{headers:{'Content-Type':'application/json'}});
                }
                const encoder = new TextEncoder();
                return new Response(new ReadableStream({start(controller) {
                    window.emitDraftEvent = event => {
                        const bytes = encoder.encode(JSON.stringify(event)+'\\n');
                        for (const byte of bytes) controller.enqueue(Uint8Array.of(byte));
                    };
                    window.emitDraft = (text, phase, updating=true) => window.emitDraftEvent({type:'draft_update',data:{
                        status:updating?'pending':'ready',snapshot_id:'debug-root',root_digest:text,
                        preview:text ? {title:'Garden draft',text} : null,covered_round:5,updating,
                        first_record:text ? {id:'garden-section',event_id:'garden-event',preview:{title:'Garden draft',text}} : null,
                        background_progress:{state:updating?'running':'finished',phase}
                    }});
                    window.closeDraft = () => { window.emitDraftEvent({type:'complete'});controller.close(); };
                    if (error) {
                        window.emitDraftEvent({type:'draft_update',data:{error:'DRAFT_UNAVAILABLE',updating:false}});
                        window.closeDraft();
                    } else window.emitDraft(null,'summarizing');
                }}),{headers:{'Content-Type':'application/x-ndjson'}});
            };
        """)
        page.route('**/api/v1/memoir/**', api)
        page.goto(base+'/memoir/interview/draft-debug-project')
        expect(page.locator('#chat-input')).to_be_visible(timeout=30000)
        page.locator('#chat-input').fill('I remember our garden.')
        page.locator('.send-button').click()
        expect(page.locator('.assistant-message').last).to_contain_text('What do you remember about your garden?')
        expect(page.locator('.workspace-media-map, .workspace-media-gallery')).to_have_count(2)
        expect(page.locator('.private-draft-status, [data-action="retry-private-draft"]')).to_have_count(0)
        if thinking:
            expect(page.locator('.assistant-message').last).to_contain_text('测试思考步骤')
            expect(page.locator('.assistant-message').last.locator('.agent-loop')).to_have_count(1)
        else:
            expect(page.locator('.assistant-message').last.locator('.agent-loop')).to_have_count(0)
        if thinking or drafts:
            page.evaluate("window.emitDraft('Initial 童年 draft','summarizing')")
            draft = page.locator('.assistant-message').last.locator('.agent-loop .agent-composer-draft')
            if thinking:
                expect(draft).to_have_count(1)
                expect(draft).not_to_have_attribute('open', '')
                expect(page.locator('.assistant-message').last.locator('.agent-loop')).not_to_have_attribute('open', '')
                page.locator('.assistant-message').last.locator('.agent-loop > summary').click()
                draft.locator('summary').click()
                expect(draft.locator('[data-event-id="garden-event"]')).to_be_visible()
                expect(draft).to_contain_text('Initial 童年 draft')
            else:
                expect(draft).to_have_count(0)
            page.evaluate("window.emitDraft('Updated 童年回忆 draft','drafting')")
            if thinking:
                expect(draft).to_contain_text('Updated 童年回忆 draft')
                expect(draft).to_have_attribute('open', '')
                expect(page.locator('.assistant-message').last.locator('.agent-loop')).to_have_attribute('open', '')
                expect(page.locator('.assistant-message').last).to_contain_text(catalog['trace']['backgroundDraft'])
                draft.locator('summary').click()
                page.evaluate("window.emitDraft('Reviewed 童年回忆 draft','reviewing')")
                expect(draft).to_contain_text('Reviewed 童年回忆 draft')
                expect(draft).not_to_have_attribute('open', '')
            else:
                expect(page.locator('.assistant-message').last.locator('.agent-loop')).to_have_count(0)
            # Wait beyond the retired polling interval while the stream stays open.
            page.wait_for_timeout(2200)
            assert page.evaluate('window.draftCalls') == 1
            page.evaluate("window.emitDraft('Finished 童年回忆 draft','saving',false);window.closeDraft()")
            if thinking:
                expect(draft).to_contain_text('Finished 童年回忆 draft')
                expect(draft).not_to_have_attribute('open', '')
                expect(page.locator('.assistant-message').last).to_contain_text(catalog['trace']['backgroundSaved'])
                draft.locator('summary').click()
                screenshot = ROOT/f'output/preview-debug/draft-thinking-drafts-{drafts}.png'
                screenshot.parent.mkdir(parents=True, exist_ok=True)
                page.locator('.assistant-message').last.screenshot(path=str(screenshot))
        else:
            assert page.evaluate('window.draftCalls') == 0
        expect(page.locator('.private-draft-status, [data-action="retry-private-draft"]')).to_have_count(0)
        saved_chat = page.evaluate("JSON.stringify(Object.fromEntries(Object.entries(localStorage).filter(([key])=>key.startsWith('memory-spark-chat-history:'))))")
        assert 'Finished 童年回忆 draft' not in saved_chat
        project['workspace_unlocked'] = True
        recall.update(rounds_completed=20, paid=True)
        page.evaluate("sessionStorage.setItem('composer-error-fixture','1')")
        page.reload()
        expect(page.locator('.story-shell.workspace-visible')).to_be_visible(timeout=30000)
        expect(page.locator('[data-workspace-tab]')).to_have_count(3)
        retry = page.locator('#workspace-detail [data-action="retry-private-draft"]')
        expect(retry).to_be_visible()
        expect(page.locator('.workspace-media-overview, .chat-main .private-draft-status')).to_have_count(0)
        retry.click()
        expect(retry).to_be_visible()
        assert len(retries) == 1
        assert retries[0]['project_id'] == project['id']
        assert errors == []
        browser.close()
