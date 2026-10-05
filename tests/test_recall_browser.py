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
    model = {'completed': 19, 'paid': False, 'turns': 0, 'checkouts': [], 'previews': 0}
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
        elif path == '/user/conversations':
            data = {'items': []}
        elif path == '/projects' or path == '/projects/recall-project':
            data = project
        elif path == '/projects/recall-project/journey':
            data = {'active_session': None}
        elif path == '/projects/recall-project/memory-sessions':
            return route.fulfill(status=403, content_type='application/json', body='{}')
        elif path == '/agent/place-journey':
            data = {'place_journey': None}
        elif path == '/agent/turn':
            assert route.request.post_data_json['conversation_text'] == 'A memory from the garden'
            assert 'The storyteller said:' in route.request.post_data_json['text']
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
        elif path == '/story/preview':
            model['previews'] += 1
            data = {'status': 'ready', 'preview': {
                'kind': 'sample_chapter', 'title': 'The garden' if locale == 'en-AU' else '那个花园',
                'text': 'I spent my childhood in that garden.' if locale == 'en-AU' else '我的童年在那个花园里度过。',
                'outline': [],
            }}
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
        expect(page.locator('.recall-preview')).to_contain_text('childhood' if locale == 'en-AU' else '童年')
        assert model['previews'] == 1
        assert page.locator('.recall-preview').evaluate('(el) => Boolean(el.compareDocumentPosition(document.querySelector(".recall-package-prompt")) & Node.DOCUMENT_POSITION_FOLLOWING)')
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


def test_account_history_and_busy_preview_resume_without_manual_retry():
    copy = json.loads((ROOT / 'apps/web/messages/en-AU.json').read_text())
    opening = copy['Memoir']['conversation']['opening']
    chinese_opening = json.loads((ROOT / 'apps/web/messages/zh-CN.json').read_text())['Memoir']['conversation']['opening']
    project = {'id': 'history-project', 'revision': 1, 'profile': {'name': 'Owner'}, 'mode': 'self'}
    model = {'ready': False, 'requests': 0}
    original = 'I remember my childhood garden.'
    wrapped = "The storyteller said: " + original + "\nThis is the storyteller's first answer to the shared profile-intake opening. Extract only explicit facts"

    def api(route):
        path = route.request.url.split('/api/v1/memoir')[-1]
        data = {}
        if path == '/agent/config':
            data = {'supabase_url': 'https://auth.test', 'supabase_publishable_key': 'public', 'auth_mode': 'supabase'}
        elif path in ('/agent/profile', '/user/profile'):
            data = project['profile']
        elif path == '/projects/history-project':
            data = project
        elif path == '/user/conversations':
            data = {'items': [
                {'id': 'account-conversation', 'created_at': '2026-09-30', 'messages': [
                    {'role': 'user', 'text': wrapped},
                    {'role': 'assistant', 'text': 'Tell me about that garden.'}]},
                {'id': 'guest', 'created_at': '2026-10-02', 'messages': [
                    {'role': 'assistant', 'text': opening}, {'role': 'assistant', 'text': opening}]},
            ]}
        elif path == '/story/state':
            data = {'recall_status': {'rounds_completed': 20, 'free_rounds': 20,
                                      'payment_required': True, 'paid': False}, 'family_features_enabled': False}
        elif path == '/story/preview':
            model['requests'] += 1
            if not model['ready']:
                return route.fulfill(status=409, headers={'X-Error-Code': 'AGENT_TURN_IN_PROGRESS'},
                                     content_type='application/json', body='{}')
            data = {'status': 'ready', 'preview': {'kind': 'sample_chapter', 'title': 'The garden',
                                                   'text': 'My childhood garden.', 'outline': []}}
        return route.fulfill(content_type='application/json', body=json.dumps(data))

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.clock.install()
        page.add_init_script('''
          localStorage.setItem('memory-spark-project', 'history-project');
        ''')
        page.add_init_script("sessionStorage.setItem('memory-spark-chat-history:history-project', JSON.stringify(" +
                             json.dumps([{'role': 'assistant', 'text': chinese_opening},
                                         {'role': 'user', 'text': wrapped}]) + "));")
        auth_script = '''window.supabase = {createClient: () => ({auth: {
          getSession: async () => ({data: {session: {access_token: 'token', user: {id: 'owner', is_anonymous: false}}}}),
          onAuthStateChange: () => ({})
        }})};'''
        page.route('https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2', lambda route: route.fulfill(
            content_type='text/javascript', body=auth_script))
        page.route('**/api/v1/memoir/**', api)
        page.goto(os.environ['MEMOIR_BROWSER_URL'] + '/memoir/interview/history-project')
        page.get_by_role('button', name='Show all history', exact=True).click(timeout=30000)
        expect(page.locator('#chat-history')).to_contain_text('I remember my childhood garden.')
        expect(page.locator('#chat-history')).to_contain_text('Tell me about that garden.')
        expect(page.locator('#chat-history')).not_to_contain_text("This is the storyteller's first")
        expect(page.locator('#chat-history')).not_to_contain_text('The storyteller said:')
        assert page.locator('#chat-history').inner_text().count(original) == 1
        assert 'assistant-message' in page.locator('#chat-history .chat-row').first.get_attribute('class').split()
        expect(page.locator('#chat-history .message-text').first).to_have_text(opening, use_inner_text=True)
        assert page.locator('#chat-history').inner_text().count('Hi, I’m Mira.') == 1
        assert '你好，我是 Mira。' not in page.locator('#chat-history').inner_text()
        expect(page.locator('.recall-preview')).to_contain_text(copy['Memoir']['recall']['previewPreparing'])
        expect(page.locator('[data-retry-recall-preview]')).to_have_count(0)
        assert model['requests'] == 1
        model['ready'] = True
        page.clock.fast_forward(15000)
        expect(page.locator('.recall-preview')).to_contain_text('My childhood garden.')
        assert model['requests'] == 2
        page.reload()
        page.get_by_role('button', name='Show all history', exact=True).click(timeout=30000)
        expect(page.locator('#chat-history .message-text').first).to_have_text(opening, use_inner_text=True)
        assert page.locator('#chat-history').inner_text().count('Hi, I’m Mira.') == 1
        browser.close()


@pytest.mark.parametrize('locale,width', [('en-AU', 1440), ('zh-CN', 390)])
def test_preview_retry_shows_progress_polls_and_recovers(locale, width):
    """Exercise the real client with a slow credential-free job fixture."""
    from datetime import datetime, timedelta
    copy = json.loads((ROOT / f'apps/web/messages/{locale}.json').read_text())['Memoir']['recall']
    model = {'posts': 0, 'polls': 0, 'ready': False, 'poll_error': False, 'held': None, 'held_poll': None}
    project = {'id': 'preview-fixture', 'revision': 1, 'profile': {'preferred_language': locale}, 'mode': 'self'}

    def api(route):
        path = route.request.url.split('/api/v1/memoir')[-1]
        data = {}
        if path == '/agent/config':
            data = {'supabase_url': 'https://auth.test', 'supabase_publishable_key': 'public', 'auth_mode': 'supabase'}
        elif path in ('/agent/profile', '/user/profile'):
            data = project['profile']
        elif path == '/projects/preview-fixture':
            data = project
        elif path == '/user/conversations':
            data = {'items': []}
        elif path == '/story/state':
            data = {'recall_status': {'rounds_completed': 20, 'free_rounds': 20,
                                      'payment_required': True, 'paid': False}, 'family_features_enabled': False}
        elif path == '/story/preview':
            model['posts'] += 1
            if model['posts'] == 1:
                return route.fulfill(status=503, headers={'X-Error-Code': 'PREVIEW_UNAVAILABLE'},
                                     content_type='application/json', body='{}')
            model['held'] = route
            return
        elif path == '/story/preview/fixture-job':
            model['polls'] += 1
            if model['polls'] == 1:
                model['held_poll'] = route
                return
            if model['poll_error']:
                model['poll_error'] = False
                return route.fulfill(status=503, content_type='application/json', body='{}')
            data = {'status': 'ready', 'preview': {'kind': 'sample_chapter', 'title': 'A saved memory',
                    'text': 'A short sample from a synthetic story.', 'outline': []}} if model['ready'] else {
                    'status': 'pending', 'job': {'id': 'fixture-job', 'status': 'RUNNING'}, 'retry_after': 3}
        return route.fulfill(content_type='application/json', body=json.dumps(data))

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': width, 'height': 1000})
        base = os.environ['MEMOIR_BROWSER_URL']
        context.add_cookies([{'name': 'copyme2_ui_locale', 'value': locale, 'url': base},
                             {'name': 'copyme2_ui_locale_source', 'value': 'fixed', 'url': base}])
        page = context.new_page()
        page.clock.install()
        page.clock.pause_at(datetime.now() + timedelta(hours=1))
        page.add_init_script("localStorage.setItem('memory-spark-project', 'preview-fixture');")
        auth_script = '''window.supabase = {createClient: () => ({auth: {
          getSession: async () => ({data: {session: {access_token: 'test-fixture', user: {id: 'owner', is_anonymous: false}}}}),
          onAuthStateChange: () => ({})
        }})};'''
        page.route('https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2', lambda route: route.fulfill(
            content_type='text/javascript', body=auth_script))
        page.route('**/api/v1/memoir/**', api)
        page.goto(base + '/memoir/interview/preview-fixture')
        page.wait_for_load_state('networkidle')
        card = page.locator('.recall-preview')
        retry = page.get_by_role('button', name=copy['previewRetry'], exact=True)
        expect(retry).to_be_visible(timeout=30000)
        destination = ROOT / 'output/preview-debug'
        destination.mkdir(parents=True, exist_ok=True)
        card.screenshot(path=str(destination / f'before-{locale}.png'))
        retry.click()
        expect(card).to_have_attribute('aria-busy', 'true')
        expect(card.get_by_role('status')).to_contain_text(copy['previewPreparing'])
        expect(card.get_by_role('button', name=copy['previewWorking'], exact=True)).to_be_disabled()
        card.screenshot(path=str(destination / f'loading-{locale}.png'))
        assert model['posts'] == 2
        assert model['held'] is not None
        with page.expect_response(lambda response: response.url.endswith('/story/preview')
                                  and response.status == 202) as submitted:
            model['held'].fulfill(status=202, content_type='application/json', body=json.dumps({
                'status': 'pending', 'preview': None, 'job': {'id': 'fixture-job', 'status': 'RUNNING'}, 'retry_after': 3}))
        submitted.value.finished()
        # Hold the first pending HTTP poll while advancing the clock, then
        # complete that response before changing the fixture to its error phase.
        # Clock jumps alone do not wait for async fetch/response processing.
        with page.expect_request(lambda request: request.url.endswith('/story/preview/fixture-job')):
            page.clock.run_for(4000)
        page.clock.fast_forward(27000)
        assert model['held_poll'] is not None
        with page.expect_response(lambda response: response.url.endswith('/story/preview/fixture-job')
                                  and response.status == 200) as pending:
            model['held_poll'].fulfill(content_type='application/json', body=json.dumps({
                'status': 'pending', 'job': {'id': 'fixture-job', 'status': 'RUNNING'}, 'retry_after': 3}))
        pending.value.finished()
        expect(card.get_by_role('status')).to_contain_text(copy['previewSlow'])
        card.screenshot(path=str(destination / f'slow-{locale}.png'))
        assert model['posts'] == 2
        model['poll_error'] = True
        with page.expect_response(lambda response: response.url.endswith('/story/preview/fixture-job')
                                  and response.status == 503):
            page.clock.fast_forward(4000)
        expect(card.get_by_role('status')).to_contain_text(copy['previewReconnecting'])
        model['ready'] = True
        with page.expect_response(lambda response: response.url.endswith('/story/preview/fixture-job')
                                  and response.status == 200):
            page.clock.fast_forward(4000)
        expect(card).to_contain_text('A short sample from a synthetic story.')
        card.screenshot(path=str(destination / f'ready-{locale}.png'))
        assert model['posts'] == 2
        assert model['polls'] >= 3
        browser.close()
