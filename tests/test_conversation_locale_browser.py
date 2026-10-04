"""Real browser locale lifecycle; auth/model boundaries use synthetic fixtures."""
import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

pytestmark = pytest.mark.skipif(not os.getenv('MEMOIR_BROWSER_URL'), reason='Requires isolated source frontend')
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('locale,anonymous', [('zh-CN', True), ('en-AU', False)])
def test_first_reply_locale_survives_followups_reload_and_explicit_choice(locale, anonymous):
    opposite = 'en-AU' if locale == 'zh-CN' else 'zh-CN'
    project = {'id':'locale-project', 'revision':1, 'profile':{}, 'mode':'self', 'workspace_unlocked':False}
    private = {}
    turns = []
    profile_reads = []
    history = []
    def status():
        return {'rounds_completed':len(turns), 'free_rounds':20, 'paid':False, 'payment_required':False}
    def record(language, source='first_reply'):
        old = private.get('conversation_language', {})
        return {'version':1, 'initialized':True, 'revision':old.get('revision',0)+1,
                'locale':language, 'source':source, 'first_reply_locale':old.get('first_reply_locale',locale),
                'first_reply_id':old.get('first_reply_id','fixture-first')}
    def api(route):
        path = route.request.url.split('/api/v1/memoir')[-1].split('?')[0]
        data = {}
        if path == '/agent/config':
            data = {'supabase_url':'https://auth.test', 'supabase_publishable_key':'public', 'auth_mode':'supabase'}
        elif path in ('/agent/profile','/user/profile'):
            if route.request.method == 'PATCH':
                language = route.request.post_data_json['preferred_language']
                private.update(preferred_language=language, conversation_language=record(language,'explicit'))
            profile_reads.append(path)
            data = private
        elif path == '/story/state':
            data = {'recall_status':status(), 'family_features_enabled':False}
        elif path == '/projects/locale-project':
            # This older demo mirror deliberately omits the private locale.
            if route.request.method == 'PATCH': project['revision'] += 1
            data = project
        elif path == '/projects/locale-project/journey': data = {'active_session':None}
        elif path == '/user/conversations': data = {'items':history}
        elif path == '/projects/locale-project/memory-sessions':
            return route.fulfill(status=403, content_type='application/json', body='{}')
        elif path == '/agent/place-journey': data = {'place_journey':None}
        elif path == '/agent/turn':
            packet = route.request.post_data_json
            expected = private.get('preferred_language',locale)
            assert packet.get('language') == expected
            if not private:
                private.update(preferred_language=locale, conversation_language=record(locale))
            turns.append(packet)
            reply = f'合成回复第{len(turns)}条。' if expected == 'zh-CN' else f'Synthetic reply {len(turns)}.'
            history.append({'id':f'fixture-{len(turns)}', 'kind':'agent',
                'content':f"Storyteller: {packet['conversation_text']}\nMemory Spark: {reply}",
                'created_at':f'2026-10-02T00:00:0{len(turns)}Z'})
            events = [{'type':'text_delta','text':reply},
                      {'type':'conversation_saved','data':{'reply':reply, 'conversation_saved':True,
                        'profile_updates':private.copy(), 'recall_status':status()}},
                      # A legacy background marker cannot change a saved choice.
                      {'type':'workspace_update','data':{'profile_updates':{'preferred_language':opposite}}},
                      {'type':'result','data':{'reply':reply}}]
            return route.fulfill(content_type='application/x-ndjson', body='\n'.join(map(json.dumps,events)))
        return route.fulfill(content_type='application/json', body=json.dumps(data))

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        base = os.environ['MEMOIR_BROWSER_URL']
        context = browser.new_context(viewport={'width':1440,'height':1000})
        context.add_cookies([{'name':'copyme2_ui_locale','value':locale,'url':base},
                            {'name':'copyme2_ui_locale_source','value':'fixed','url':base}])
        user = {'id':'fixture-locale-owner','is_anonymous':anonymous,'user_metadata':{}}
        script = f"""window.supabase={{createClient:()=>({{auth:{{
          getSession:async()=>({{data:{{session:{{access_token:'fixture-only',user:{json.dumps(user)}}}}}}}),
          getUser:async()=>({{data:{{user:{json.dumps(user)}}}}}),onAuthStateChange:()=>({{}}),
          updateUser:async()=>({{data:{{user:{json.dumps(user)}}}}})
        }}}})}};"""
        context.route('https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2', lambda route:route.fulfill(content_type='text/javascript',body=script))
        context.route('**/api/v1/memoir/**', api)
        context.add_init_script("localStorage.setItem('memory-spark-project','locale-project');")
        page = context.new_page()
        page.goto(base+'/memoir/interview/locale-project')
        def send(text):
            field = page.locator('#chat-input')
            expect(field).to_be_enabled(timeout=30000)
            field.fill(text)
            page.locator('#chat-form button[type="submit"]').click()
            expect(field).to_be_enabled(timeout=30000)
        first = '我记得小时候的花园。' if locale == 'zh-CN' else 'I remember the garden from childhood.'
        second = 'An English follow-up.' if locale == 'zh-CN' else '后来我又回到花园。'
        send(first)
        expect(page.locator('.assistant-message .message-text').last).to_contain_text('第1条' if locale=='zh-CN' else 'reply 1')
        send(second)
        expect(page.locator('.assistant-message .message-text').last).to_contain_text('第2条' if locale=='zh-CN' else 'reply 2')
        destination = ROOT / f'output/locale-debug/stable-{locale}.png'
        destination.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(destination), full_page=True)
        page.reload()
        send('后来 again 我想起 another detail。')
        expect(page.locator('.assistant-message .message-text').last).to_contain_text('第3条' if locale=='zh-CN' else 'reply 3')
        assert '/user/profile' in profile_reads  # Includes anonymous-session resume.
        assert [turn.get('language') for turn in turns] == [locale]*3
        page.locator('[data-profile-trigger]').click()
        page.locator('[data-profile-action="settings"]').click()
        dialog = page.locator('[data-profile-settings]')
        dialog.locator('select[name="preferred_language"]').select_option(opposite)
        dialog.locator('button[type="submit"]').click()
        expect(dialog).to_have_count(0)
        send(first)
        expect(page.locator('.assistant-message .message-text').last).to_contain_text('第4条' if opposite=='zh-CN' else 'reply 4')
        assert turns[-1]['language'] == opposite
        assert private['conversation_language']['source'] == 'explicit'
        assert private['conversation_language']['first_reply_locale'] == locale
        page.reload()
        send('后来 again 我想起 another detail。')
        expect(page.locator('.assistant-message .message-text').last).to_contain_text('第5条' if opposite=='zh-CN' else 'reply 5')
        assert turns[-1]['language'] == opposite
        browser.close()
