"""Exercise the actual reminder module with a controlled clock and mocked auth."""
import json
import re
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


def assert_reminder_in_chat_flow(page):
    page.evaluate('''() => {
      conversation.messages.push(...Array.from({length: 20}, (_, index) => ({
        cacheId: `after-${index}`, text: `Later memory ${index}. ` + 'A familiar garden and a small path. '.repeat(8)
      })));
      paintHistory();
      document.querySelector('#chat-scroll').style.height = '350px';
      const composer = document.createElement('div');
      composer.className = 'composer-wrap';
      composer.innerHTML = '<textarea aria-label="Memory">Unsent memory</textarea>';
      document.querySelector('#chat-scroll').after(composer);
    }''')
    reminder = page.locator('[data-auth-reminder]')
    expect(reminder).to_have_count(1)
    assert reminder.evaluate('(node) => node.parentElement.id') == 'chat-history'
    assert reminder.evaluate('(node) => node.previousElementSibling.dataset.fixtureMessage') == 'before-1'
    assert reminder.evaluate('(node) => node.nextElementSibling.dataset.fixtureMessage') == 'after-0'

    for width, height in [(390, 844), (1440, 1000)]:
        page.set_viewport_size({'width': width, 'height': height})
        page.evaluate("document.querySelector('#chat-scroll').scrollTop = 1e9")
        assert reminder.evaluate('''node => node.getBoundingClientRect().bottom
          < document.querySelector('#chat-scroll').getBoundingClientRect().top''')
        page.evaluate('''() => {
          const scroll = document.querySelector('#chat-scroll');
          scroll.scrollTop += document.querySelector('[data-auth-reminder]').getBoundingClientRect().top
            - scroll.getBoundingClientRect().top - 20;
        }''')
        expect(reminder.get_by_role('button')).to_be_in_viewport()
        before = page.evaluate('''() => ({
          banner: document.querySelector('[data-auth-reminder]').getBoundingClientRect().top,
          bubble: document.querySelector('[data-fixture-message="before-1"]').getBoundingClientRect().top,
          composer: document.querySelector('.composer-wrap').getBoundingClientRect().top
        })''')
        page.evaluate("document.querySelector('#chat-scroll').scrollTop += 100")
        after = page.evaluate('''() => ({
          banner: document.querySelector('[data-auth-reminder]').getBoundingClientRect().top,
          bubble: document.querySelector('[data-fixture-message="before-1"]').getBoundingClientRect().top,
          composer: document.querySelector('.composer-wrap').getBoundingClientRect().top
        })''')
        assert abs(before['banner'] - after['banner'] - 100) < 1
        assert abs(before['bubble'] - after['bubble'] - 100) < 1
        assert abs(before['composer'] - after['composer']) < 1

    # Hydration replaces message objects and can prepend earlier history.
    page.evaluate('''() => {
      conversation.messages = [{cacheId: 'earlier', text: 'Earlier memory'},
        ...conversation.messages.map(message => ({...message}))];
      paintHistory();
    }''')
    assert reminder.evaluate('(node) => node.previousElementSibling.dataset.fixtureMessage') == 'before-1'
    assert reminder.evaluate('(node) => node.nextElementSibling.dataset.fixtureMessage') == 'after-0'
    page.evaluate('''() => {
      window.originalConversation = conversation;
      conversation = {id: 'other-project', messages: [{cacheId: 'other', text: 'Another conversation'}]};
      paintHistory();
      conversation.messages.push({cacheId: 'other-later', text: 'A later reply'});
      paintHistory();
    }''')
    assert reminder.evaluate('(node) => node.previousElementSibling.dataset.fixtureMessage') == 'other'
    assert reminder.evaluate('(node) => node.nextElementSibling.dataset.fixtureMessage') == 'other-later'
    page.evaluate('conversation = originalConversation; paintHistory(); reminder.mount()')
    expect(reminder).to_have_count(1)
    assert reminder.evaluate('(node) => node.previousElementSibling.dataset.fixtureMessage') == 'before-1'
    assert reminder.evaluate('(node) => node.nextElementSibling.dataset.fixtureMessage') == 'after-0'
    page.evaluate("document.querySelector('#chat-scroll').scrollTop = 1e9")


def main():
    output = ROOT / 'output/playwright'
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        messages = json.loads((ROOT / 'apps/web/messages/en-AU.json').read_text())['AuthReminder']
        chinese_messages = json.loads((ROOT / 'apps/web/messages/zh-CN.json').read_text())['AuthReminder']

        def serve(route):
            path = route.request.url.split('http://reminder.test')[-1]
            if path == '/':
                route.fulfill(content_type='text/html', body='<link rel="stylesheet" href="/public/styles.css"><div id="chat-scroll" class="chat-scroll"><div id="chat-history"></div></div>')
            elif path == '/public/styles.css':
                route.fulfill(content_type='text/css', body=(ROOT / 'apps/web/public/styles.css').read_text())
            elif path == '/client/i18n.js':
                route.fulfill(content_type='text/javascript', body=f'const copies = {json.dumps({"en-AU": messages, "zh-CN": chinese_messages})}; export const translate = key => copies[window.__locale || "en-AU"][key.split(".").at(-1)];')
            else:
                route.fulfill(content_type='text/javascript', body=(ROOT / 'apps/web' / path.lstrip('/')).read_text())

        page.route('http://reminder.test/**', serve)
        page.goto('http://reminder.test/', wait_until='networkidle')
        page.clock.install()
        page.evaluate('''async () => {
          const { createAuthReminder } = await import('/client/memoir/auth-reminder.js');
          window.calls = [];
          window.conversation = {id: 'guest-project', messages: Array.from({length: 2}, (_, index) => ({
            cacheId: `before-${index}`, text: `Earlier memory ${index}. ` + 'A familiar garden and a small path. '.repeat(8)
          }))};
          window.paintHistory = () => {
            document.querySelector('#chat-history').replaceChildren(...conversation.messages.map(message => {
              const row = document.createElement('article');
              row.className = 'chat-row assistant-message';
              row.dataset.fixtureMessage = message.cacheId;
              const bubble = document.createElement('div');
              bubble.className = 'chat-bubble';
              bubble.textContent = message.text;
              row.append(bubble);
              return row;
            }));
            window.reminder?.mount();
          };
          paintHistory();
          window.serverUser = {id: 'guest-1', is_anonymous: true};
          window.account = {user: {id: 'guest-1', is_anonymous: true}, client: {auth: {
            getUser: async () => ({data: {user: serverUser}}),
            updateUser: async (...args) => { calls.push(['email', ...args]); return {}; },
            linkIdentity: async (...args) => { calls.push(['social', ...args]); return {}; }
          }}};
          window.reminder = createAuthReminder({getAuth: () => account,
            getConversation: () => conversation, busy: () => false});
          reminder.tick();
        }''')
        page.clock.run_for(599000)
        expect(page.locator('dialog')).to_have_count(0)
        page.clock.run_for(1000)
        expect(page.get_by_role('dialog')).to_be_visible()
        expect(page.locator('[data-auth-reminder]')).to_contain_text('lose access')
        page.evaluate("window.__locale = 'zh-CN'; reminder.mount()")
        expect(page.locator('[data-auth-reminder]')).to_contain_text('我们已经聊了 10 分钟')
        expect(page.get_by_role('button', name='登录以保留聊天记录')).to_be_visible()
        page.evaluate("window.__locale = 'en-AU'; reminder.mount()")
        page.get_by_label('Email address').fill('guest@example.com')
        page.get_by_role('button', name='Continue with email').click()
        expect(page.get_by_role('status')).to_contain_text('Check your email')
        assert page.evaluate('calls[0][1]') == {'email': 'guest@example.com'}
        page.get_by_role('button', name='Not now').click()
        page.clock.run_for(5000)
        expect(page.locator('dialog')).to_have_count(0)
        assert_reminder_in_chat_flow(page)
        page.locator('[data-auth-reminder]').scroll_into_view_if_needed()
        if not page.locator('dialog[open]').count():
            page.get_by_role('button', name='Sign in to keep your history').click()
        page.get_by_role('button', name='Continue with Google').click()
        expect(page.get_by_role('status')).to_contain_text('Opening')
        assert page.evaluate('calls[1][1].provider') == 'google'
        assert page.evaluate('calls[1][1].options.queryParams') == {
            'prompt': 'consent select_account'
        }
        assert page.evaluate('calls[1][1].options.redirectTo') == 'http://reminder.test/'
        page.get_by_role('button', name='Continue with Facebook').click()
        assert page.evaluate('calls[2][1]') == {
            'provider': 'facebook', 'options': {'redirectTo': 'http://reminder.test/'}
        }
        page.evaluate("serverUser = {id: 'guest-1', is_anonymous: false}; window.dispatchEvent(new Event('focus'))")
        expect(page.locator('dialog')).to_have_count(0)
        expect(page.locator('[data-auth-reminder]')).to_have_count(0)
        page.clock.run_for(600000)
        expect(page.locator('dialog')).to_have_count(0)
        # A provider error is not a successful login: retain history and explain it.
        page.evaluate('''async () => {
          history.replaceState({}, '', '/?error=server_error&error_code=identity_already_exists');
          sessionStorage.setItem('memoir-link-provider', 'google');
          account.user = {id: 'guest-1', is_anonymous: true};
          const {createAuthReminder} = await import('/client/memoir/auth-reminder.js');
          window.retryReminder = createAuthReminder({getAuth: () => account, busy: () => false,
            signInExisting: async provider => { calls.push(['existing', provider]); }
          });
          retryReminder.tick();
        }''')
        expect(page.get_by_role('dialog')).to_be_visible()
        expect(page.get_by_role('status')).to_contain_text('already belongs to a Memoir account')
        expect(page.get_by_role('status')).to_contain_text('choose a different account')
        expect(page.get_by_role('button', name='Sign in and attach conversation')).to_be_visible()
        expect(page.get_by_role('button', name='Choose a different account')).to_be_visible()
        expect(page.get_by_role('button', name='Continue with Google')).to_be_hidden()
        expect(page.get_by_label('Email address')).to_be_hidden()
        page.get_by_role('button', name='Sign in and attach conversation').click()
        expect(page.get_by_role('status')).to_contain_text('Opening')
        assert page.evaluate('calls.at(-1)') == ['existing', 'google']
        # A direct provider rejection has the same useful retry instructions.
        page.evaluate('''account.client.auth.linkIdentity = async () => ({
          error: {code: 'identity_already_exists'}
        })''')
        page.get_by_role('button', name='Choose a different account').click()
        expect(page.get_by_role('status')).to_contain_text('choose a different account')
        page.screenshot(path=str(output / 'auth-choice.png'))
        # Supabase implicit callbacks can carry errors in the fragment too.
        page.get_by_role('button', name='Not now').click()
        page.evaluate('''async () => {
          history.replaceState({}, '', '/#error=server_error&error_code=identity_already_exists');
          const {createAuthReminder} = await import('/client/memoir/auth-reminder.js');
          window.hashReminder = createAuthReminder({getAuth: () => account, busy: () => false});
          hashReminder.tick();
        }''')
        expect(page.get_by_role('status')).to_contain_text('choose a different account')
        # Choosing an unused social identity converts the same guest user.
        page.evaluate('''account.client.auth.linkIdentity = async (options) => {
          calls.push(['retry', options]);
          return {data: {user: {id: 'guest-1', is_anonymous: false}}};
        }''')
        page.get_by_role('button', name='Choose a different account').click()
        expect(page.locator('dialog')).to_have_count(0)
        expect(page.locator('[data-auth-reminder]')).to_have_count(0)
        assert page.evaluate('account.user.id') == 'guest-1'
        assert page.evaluate('account.user.is_anonymous') is False
        assert page.evaluate('calls.at(-1)[1].options.queryParams.prompt') == 'consent select_account'
        page.evaluate('''account.user = {id: 'guest-1', is_anonymous: true};
          history.replaceState({}, '', '/');
          hashReminder.tick(); hashReminder.mount();''')
        if not page.locator('dialog[open]').count():
            page.get_by_role('button', name='Sign in to keep your history').click()
        # Open a fresh reminder without a callback conflict for the email path.
        page.get_by_role('button', name='Not now').click()
        page.evaluate('''async () => {
          const {createAuthReminder} = await import('/client/memoir/auth-reminder.js');
          createAuthReminder({getAuth: () => account, busy: () => false}).tick();
        }''')
        # A confirmed update response also clears both surfaces immediately.
        page.evaluate('''account.client.auth.updateUser = async () => ({data: {
          user: {id: 'guest-1', is_anonymous: false}
        }})''')
        page.get_by_label('Email address').fill('confirmed@example.com')
        page.get_by_role('button', name='Continue with email').click()
        expect(page.locator('dialog')).to_have_count(0)
        expect(page.locator('[data-auth-reminder]')).to_have_count(0)
        page.evaluate('reminder.mount(); retryReminder.mount()')
        expect(page.locator('[data-auth-reminder]')).to_have_count(0)
        # Attached transcripts render as text and can be read on another device.
        page.evaluate('''async () => {
          const {openAttachedConversations} = await import('/client/memoir/conversation-attachments.js');
          await openAttachedConversations(async () => ({items: [{project_id: 'guest-project', messages: [
            {role: 'user', text: '<img src=x onerror=alert(1)> Childhood'},
            {role: 'assistant', text: 'Tell me more.'}
          ]}]}));
        }''')
        page.locator('summary').click()
        expect(page.get_by_role('dialog')).to_contain_text('Tell me more.')
        expect(page.locator('dialog img')).to_have_count(0)
        page.get_by_role('button', name='Not now').click()
        # Profile-menu login enters an existing OAuth account directly, rather
        # than attempting to link its identity to the anonymous account.
        page.evaluate('''async () => {
          history.replaceState({}, '', '/');
          account.user = {id: 'guest-1', is_anonymous: true};
          const {createAuthReminder} = await import('/client/memoir/auth-reminder.js');
          window.loginReminder = createAuthReminder({getAuth: () => account, busy: () => false,
            signInExisting: async provider => { calls.push(['login', provider]); }
          });
          loginReminder.open({signIn: true});
        }''')
        expect(page.get_by_role('dialog')).to_contain_text('access your saved conversations')
        expect(page.get_by_label('Email address')).to_be_hidden()
        page.get_by_role('button', name='Continue with Google').click()
        assert page.evaluate('calls.at(-1)') == ['login', 'google']
        expect(page.get_by_role('status')).to_contain_text('Opening')
        page.get_by_role('button', name='Not now').click()
        # Exercise the real menu replacement and event bindings while leaving
        # the active conversation/composer DOM intact.
        page.evaluate("account.user = {id: 'owner', is_anonymous: false}; document.querySelectorAll('dialog').forEach(dialog => dialog.close())")
        source = (ROOT / 'apps/web/client/memoir/client.js').read_text()
        functions = '\n'.join(re.search(r'function ' + name + r'\(.*?\n\}', source, re.S).group(0)
                              for name in ['profileDetails', 'profileMenu', 'closeProfileMenu',
                                           'refreshProfileMenu', 'bindProfileMenu', 'syncSupabaseSession',
                                           'captureProjectScope', 'isCurrentProjectScope'])
        page.evaluate('''functions => {
          window.state = {supabase: {user: {id: 'guest-1', is_anonymous: true}}};
          window.$ = selector => document.querySelector(selector);
          window.profile = () => ({});
          window.escapeHtml = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');
          window.translate = key => key;
          window.UI_LOCALES = new Set();
          window.uiPreferenceSession = {setSession() {}};
          window.authReminder = {tick() {}, open() {}};
          window.signOut = () => {};
          window.reviewCollection = () => {};
          (0, eval)(functions);
          document.body.innerHTML = profileMenu() + '<textarea id="chat-input">Unsent memory</textarea>';
          bindProfileMenu();
        }''', functions)
        page.locator('[data-profile-trigger]').click()
        expect(page.locator('[data-profile-action="login"]')).to_be_visible()
        page.evaluate('''syncSupabaseSession({access_token: 'test-token', user: {
          id: 'guest-1', email: 'owner@example.com', is_anonymous: false
        }})''')
        expect(page.locator('[data-profile-action="login"]')).to_have_count(0)
        expect(page.locator('[data-profile-action="logout"]')).to_be_visible()
        expect(page.locator('[data-profile-action="attached-history"]')).to_be_visible()
        expect(page.locator('[data-profile-trigger]')).to_contain_text('owner@example.com')
        expect(page.locator('#chat-input')).to_have_value('Unsent memory')
        page.locator('#chat-input').focus()
        page.evaluate('''syncSupabaseSession({access_token: 'refreshed-token', user: {
          id: 'guest-1', email: 'owner@example.com', is_anonymous: false
        }})''')
        assert page.evaluate('document.activeElement.id') == 'chat-input'
        browser.close()
        print('PASS: inline reminder placement, desktop/mobile scrolling, rerenders, history hydration, project isolation, timing, email/social linking, callback errors, retry, signed-in suppression')


if __name__ == '__main__':
    main()
