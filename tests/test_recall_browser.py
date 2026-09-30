"""Exercise the actual interview UI against mocked auth/model/payment boundaries."""
import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

pytestmark = pytest.mark.skipif(not os.environ.get('MEMOIR_BROWSER_URL'), reason='Requires a selected local source frontend')
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('locale', ['en-AU', 'zh-CN'])
@pytest.mark.parametrize('anonymous', [False, True])
def test_final_reply_package_selection_refresh_and_payment(locale, anonymous):
    copy = json.loads((ROOT / f'apps/web/messages/{locale}.json').read_text())
    model = {'completed': 19, 'paid': False, 'turns': 0, 'checkouts': []}
    project = {'id': 'recall-project', 'revision': 1, 'profile': {'preferred_language': locale}, 'mode': 'self'}

    def status():
        return {'rounds_completed': model['completed'], 'free_rounds': 20,
                'payment_required': model['completed'] >= 20 and not model['paid'], 'paid': model['paid']}

    def api(route):
        path = route.request.url.split('/api/v1/memoir')[-1]
        data = {}
        if path == '/agent/config':
            data = {'supabase_url': 'https://auth.test', 'supabase_publishable_key': 'public', 'auth_mode': 'supabase'}
        elif path == '/story/state':
            data = {'recall_status': status(), 'family_features_enabled': False}
        elif path == '/agent/profile' or path == '/user/profile':
            data = project['profile']
        elif path == '/projects' or path == '/projects/recall-project':
            data = project
        elif path == '/projects/recall-project/journey':
            data = {'active_session': None}
        elif path == '/projects/recall-project/memory-sessions':
            return route.fulfill(status=403, content_type='application/json', body='{}')
        elif path == '/agent/place-journey':
            data = {'place_journey': None}
        elif path == '/agent/turn':
            model['turns'] += 1
            model['completed'] += 1
            reply = 'I remember the garden.' if locale == 'en-AU' else '我记得那个花园。'
            events = [{'type': 'text_delta', 'text': reply},
                      {'type': 'conversation_saved', 'data': {'reply': reply, 'conversation_saved': True,
                                                            'recall_status': status()}},
                      {'type': 'result', 'data': {'reply': reply}}]
            return route.fulfill(content_type='application/x-ndjson', body='\n'.join(map(json.dumps, events)))
        elif path == '/story/checkout':
            model['checkouts'].append(route.request.post_data_json)
            data = {'message': 'Checkout prepared.'}
        return route.fulfill(content_type='application/json', body=json.dumps(data))

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(viewport={'width': 390 if locale == 'zh-CN' else 1440, 'height': 900})
        base = os.environ['MEMOIR_BROWSER_URL']
        context.add_cookies([{'name': 'copyme2_ui_locale', 'value': locale, 'url': base},
                             {'name': 'copyme2_ui_locale_source', 'value': 'fixed', 'url': base}])
        page = context.new_page()
        page.set_default_timeout(10000)
        user = {'id': 'recall-user', 'is_anonymous': anonymous, 'user_metadata': {'ui_locale': locale}}
        auth_script = f"""window.supabase = {{createClient: () => ({{auth: {{
          getSession: async () => ({{data: {{session: {{access_token: 'token', user: {json.dumps(user)}}}}}}}),
          getUser: async () => ({{data: {{user: {json.dumps(user)}}}}}),
          onAuthStateChange: () => ({{}}), updateUser: async () => ({{}})
        }}}})}};"""
        page.route('https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2', lambda route: route.fulfill(
            content_type='text/javascript', body=auth_script))
        page.route('**/api/v1/memoir/**', api)
        page.goto(base + '/memoir')
        expect(page.get_by_text(copy['Memoir']['landing']['connectSummary'], exact=True)).to_be_visible(timeout=30000)
        page.locator('.agent-connect summary').click()
        expect(page.locator('.agent-connect')).to_contain_text(copy['Memoir']['landing']['connectDescription'])
        assert not any(name in page.locator('#app').inner_text().lower() for name in ('codex', 'supabase', 'five free', '五轮', '20'))
        page.locator('[data-action="start-story"][data-mode="self"]').click()
        send = page.get_by_role('button', name=copy['Memoir']['story']['send'], exact=True)
        expect(send).to_be_enabled(timeout=30000)
        page.locator('#chat-input').fill('A memory from the garden')
        send.click()
        prompt = page.locator('.recall-package-prompt')
        expect(prompt).to_be_visible(timeout=30000)
        expect(page.locator('.assistant-message .message-text').last).to_contain_text('garden' if locale == 'en-AU' else '花园')
        expect(page.locator('#chat-input')).to_have_count(0)
        assert model['turns'] == 1
        assert not any(name in prompt.inner_text().lower() for name in ('codex', 'supabase', '20 free', '五轮'))
        assert '20' not in copy['Memoir']['recall']['description']
        page.reload()
        expect(prompt).to_be_visible(timeout=30000)
        assert model['turns'] == 1
        page.locator('.story-plan-card:has(input[value="family_memoir_v1"])').click()
        page.locator('#story-book-count').select_option('4')
        destination = ROOT / f'output/playwright/recall-packages-{locale}-{anonymous}.png'
        destination.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(destination), full_page=True)
        page.get_by_role('button', name=copy['Memoir']['storyFlow']['continueCheckout']).click()
        if anonymous:
            expect(page.locator('[data-auth-reminder-dialog]')).to_be_visible()
            assert model['checkouts'] == []
        else:
            expect(prompt.get_by_text('Checkout prepared.', exact=True)).to_be_visible()
            assert model['checkouts'] == [{'plan_key': 'family_memoir_v1', 'book_count': 4}]
            assert json.loads(page.evaluate('sessionStorage.getItem("memoir-package-choice")')) == {'plan': 'family_memoir_v1', 'books': 4}
            page.reload()
            expect(page.locator('input[value="family_memoir_v1"]')).to_be_checked(timeout=30000)
            expect(page.locator('#story-book-count')).to_have_value('4')
            model['paid'] = True
            page.get_by_role('button', name=copy['Memoir']['recall']['checkPayment']).click()
            expect(page.locator('.recall-package-prompt')).to_have_count(0)
            expect(page.locator('#chat-input')).to_be_visible()
        destination = ROOT / f'output/playwright/recall-{locale}-{anonymous}.png'
        destination.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(destination), full_page=True)
        browser.close()
