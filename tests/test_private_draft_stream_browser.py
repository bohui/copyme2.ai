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
def test_thinking_steps_and_live_draft_panel_have_independent_flags(drafts, thinking):
    base = os.environ['MEMOIR_BROWSER_URL']
    project = {'id':'draft-debug-project', 'revision':1, 'mode':'self', 'profile':{'preferred_language':'zh-CN'}}
    history = StoryHistoryFixture(STAGE_OWNER, project['id'], 'fixture-only')
    catalog = json.loads((ROOT/'apps/web/messages/zh-CN.json').read_text())['Memoir']
    recall = {'rounds_completed':5, 'free_rounds':20, 'paid':False, 'payment_required':False}

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
        elif path == '/story/state': data = {'recall_status':recall, 'family_features_enabled':False}
        elif path == '/agent/place-journey': data = {'place_journey':None}
        elif path == '/agent/turn':
            saved = {'reply':'What do you remember about your garden?', 'conversation_saved':True, 'recall_status':recall}
            events = [{'type':'progress','data':{'id':'analysis','detail':'测试思考步骤','status':'completed'}},
                      {'type':'conversation_saved','data':saved}, {'type':'result','data':saved}]
            return route.fulfill(content_type='application/x-ndjson', body='\n'.join(json.dumps(e) for e in events)+'\n')
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
                if (options.headers.Accept !== 'application/x-ndjson') throw Error('Missing draft streaming Accept');
                const encoder = new TextEncoder();
                return new Response(new ReadableStream({start(controller) {
                    window.emitDraftEvent = event => {
                        const bytes = encoder.encode(JSON.stringify(event)+'\\n');
                        for (const byte of bytes) controller.enqueue(Uint8Array.of(byte));
                    };
                    window.emitDraft = (text, phase, updating=true) => window.emitDraftEvent({type:'draft_update',data:{
                        status:updating?'pending':'ready',snapshot_id:'debug-root',root_digest:text,
                        preview:text ? {title:'Garden draft',text} : null,covered_round:5,updating,
                        background_progress:{state:updating?'running':'finished',phase}
                    }});
                    window.emitDraft(null,'summarizing');
                    window.closeDraft = () => { window.emitDraftEvent({type:'complete'});controller.close(); };
                }}),{headers:{'Content-Type':'application/x-ndjson'}});
            };
        """)
        page.route('**/api/v1/memoir/**', api)
        page.goto(base+'/memoir/interview/draft-debug-project')
        expect(page.locator('#chat-input')).to_be_visible(timeout=30000)
        page.locator('#chat-input').fill('I remember our garden.')
        page.locator('.send-button').click()
        expect(page.locator('.assistant-message').last).to_contain_text('What do you remember about your garden?')
        if thinking:
            expect(page.locator('.assistant-message').last).to_contain_text('测试思考步骤')
            expect(page.locator('.assistant-message').last.locator('.agent-loop')).to_have_count(1)
        else:
            expect(page.locator('.assistant-message').last.locator('.agent-loop')).to_have_count(0)
        if drafts:
            expect(page.locator('.private-draft-status')).to_contain_text(catalog['workspace']['privateDraftUpdating'])
            expect(page.locator('.chat-main > .private-draft-status')).to_have_count(1)
            if not thinking:
                screenshot = ROOT/'output/preview-debug/draft-status-zh-CN.png'
                screenshot.parent.mkdir(parents=True, exist_ok=True)
                page.locator('.private-draft-status').screenshot(path=str(screenshot))
            page.evaluate("window.emitDraft('Initial 童年 draft','summarizing')")
            expect(page.locator('.private-draft-status')).to_contain_text('Garden draft')
            page.get_by_text(catalog['workspace']['readSavedDraft'], exact=True).click()
            expect(page.locator('.private-draft-status')).to_contain_text('Initial 童年 draft')
            page.evaluate("window.emitDraft('Updated 童年回忆 draft','drafting')")
            expect(page.locator('.private-draft-status')).to_contain_text('Updated 童年回忆 draft')
            expect(page.locator('.saved-draft-sections')).to_have_attribute('open', '')
            if thinking:
                expect(page.locator('.assistant-message').last).to_contain_text(catalog['trace']['backgroundDraft'])
            else:
                expect(page.locator('.assistant-message').last.locator('.agent-loop')).to_have_count(0)
            # Wait beyond the retired polling interval while the stream stays open.
            page.wait_for_timeout(2200)
            assert page.evaluate('window.draftCalls') == 1
            page.evaluate("window.emitDraft('Finished 童年回忆 draft','saving',false);window.closeDraft()")
            expect(page.locator('.private-draft-status')).to_contain_text('Finished 童年回忆 draft')
            expect(page.locator('.saved-draft-sections')).to_have_attribute('open', '')
            if thinking:
                expect(page.locator('.assistant-message').last).to_contain_text(catalog['trace']['backgroundSaved'])
            screenshot = ROOT/f'output/preview-debug/draft-ndjson-thinking-{thinking}.png'
            screenshot.parent.mkdir(parents=True, exist_ok=True)
            page.locator('.private-draft-status').screenshot(path=str(screenshot))
        else:
            expect(page.locator('.private-draft-status')).to_have_count(0)
            assert page.evaluate('window.draftCalls') == 0
        assert errors == []
        browser.close()
