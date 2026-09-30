"""Exercise the actual reminder module with a controlled clock and mocked auth."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        messages = json.loads((ROOT / 'apps/web/messages/en-AU.json').read_text())['AuthReminder']

        def serve(route):
            path = route.request.url.split('http://reminder.test')[-1]
            if path == '/':
                route.fulfill(content_type='text/html', body='<div id="chat-scroll"></div>')
            elif path == '/client/i18n.js':
                route.fulfill(content_type='text/javascript', body=f'const copy = {json.dumps(messages)}; export const translate = key => copy[key.split(".").at(-1)];')
            else:
                route.fulfill(content_type='text/javascript', body=(ROOT / 'apps/web' / path.lstrip('/')).read_text())

        page.route('http://reminder.test/**', serve)
        page.goto('http://reminder.test/', wait_until='networkidle')
        page.clock.install()
        page.evaluate('''async () => {
          const { createAuthReminder } = await import('/client/memoir/auth-reminder.js');
          window.calls = [];
          window.serverUser = {id: 'guest-1', is_anonymous: true};
          window.account = {user: {id: 'guest-1', is_anonymous: true}, client: {auth: {
            getUser: async () => ({data: {user: serverUser}}),
            updateUser: async (...args) => { calls.push(['email', ...args]); return {}; },
            linkIdentity: async (...args) => { calls.push(['social', ...args]); return {}; }
          }}};
          window.reminder = createAuthReminder({getAuth: () => account, busy: () => false});
          reminder.tick();
        }''')
        page.clock.run_for(599000)
        expect(page.locator('dialog')).to_have_count(0)
        page.clock.run_for(1000)
        expect(page.get_by_role('dialog')).to_be_visible()
        expect(page.locator('[data-auth-reminder]')).to_contain_text('lose access')
        page.get_by_label('Email address').fill('guest@example.com')
        page.get_by_role('button', name='Continue with email').click()
        expect(page.get_by_role('status')).to_contain_text('Check your email')
        assert page.evaluate('calls[0][1]') == {'email': 'guest@example.com'}
        page.get_by_role('button', name='Not now').click()
        page.clock.run_for(5000)
        expect(page.locator('dialog')).to_have_count(0)
        page.get_by_role('button', name='Sign in to keep your history').click()
        page.get_by_role('button', name='Continue with Google').click()
        expect(page.get_by_role('status')).to_contain_text('Opening')
        assert page.evaluate('calls[1][1].provider') == 'google'
        page.evaluate("serverUser = {id: 'guest-1', is_anonymous: false}; window.dispatchEvent(new Event('focus'))")
        expect(page.locator('dialog')).to_have_count(0)
        expect(page.locator('[data-auth-reminder]')).to_have_count(0)
        page.clock.run_for(600000)
        expect(page.locator('dialog')).to_have_count(0)
        # A provider error is not a successful login: retain history and explain it.
        page.evaluate('''async () => {
          history.replaceState({}, '', '/?error=server_error&error_code=identity_already_exists');
          account.user = {id: 'guest-1', is_anonymous: true};
          const {createAuthReminder} = await import('/client/memoir/auth-reminder.js');
          window.retryReminder = createAuthReminder({getAuth: () => account, busy: () => false});
          retryReminder.tick();
        }''')
        expect(page.get_by_role('dialog')).to_be_visible()
        expect(page.get_by_role('status')).to_contain_text('sign-in did not complete')
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
        browser.close()
        print('PASS: timing, chat reminder, dismissal/reopen, email/social linking, signed-in suppression')


if __name__ == '__main__':
    main()
