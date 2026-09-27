"""Hold the final save event while asserting that real stream chunks are visible."""
import argparse
from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:3010')
    args = parser.parse_args()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('''
          const originalFetch = window.fetch.bind(window);
          window.turnCalls = 0;
          window.fetch = async (url, options) => {
            if (!String(url).endsWith('/agent/turn')) return originalFetch(url, options);
            window.turnCalls++;
            if (options.headers.Accept !== 'application/x-ndjson') throw Error('Missing streaming Accept');
            const encoder = new TextEncoder();
            return new Response(new ReadableStream({start(controller) {
              const emit = event => {
                // The proxy may concatenate JSON objects even though each
                // object arrives in its own streamed write.
                const bytes = encoder.encode(JSON.stringify(event));
                // Split every UTF-8 byte, including within Chinese characters.
                for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
              };
              emit({type: 'text_delta', text: 'Hello 承德'});
              window.finishTurn = () => {
                emit({type: 'text_delta', text: ', what do you remember?'});
                emit({type: 'result', data: {reply: 'Hello 承德, what do you remember?', trace: [], profile_updates: {name: 'Avery'}}});
                controller.close();
              };
              window.failTurn = () => {
                emit({type: 'error', message: 'The response could not be saved.'});
                controller.close();
              };
            }}), {headers: {'Content-Type': 'application/json'}});
          };
        ''')
        page.goto(args.base_url, wait_until='networkidle')
        page.get_by_role('button', name='Begin my story').click()
        expect(page.locator('.assistant-message .message-text').first).to_contain_text('First, what would you like me to call you?')
        expect(page.locator('.message-streaming')).to_have_count(0)
        assert page.evaluate('window.turnCalls') == 0
        page.get_by_role('textbox', name='Your message').fill('My name is Avery')
        page.get_by_role('button', name='Send message').click()
        expect(page.locator('.assistant-message .message-text').nth(1)).to_have_text('Hello 承德')
        expect(page.locator('.thinking')).to_have_count(0)
        expect(page.locator('.profile-trigger-name')).not_to_have_text('Avery')
        expect(page.get_by_role('button', name='Send message')).to_be_disabled()
        assert page.evaluate('window.turnCalls') == 1
        page.evaluate('window.finishTurn()')
        expect(page.locator('.message-streaming')).to_have_count(0)
        expect(page.locator('.assistant-message')).to_have_count(2)
        expect(page.locator('.profile-trigger-name')).to_have_text('Avery')
        expect(page.locator('.assistant-message .message-text').nth(1)).to_have_text('Hello 承德, what do you remember?')
        page.get_by_role('textbox', name='Your message').fill('Another memory')
        page.get_by_role('button', name='Send message').click()
        expect(page.locator('.assistant-message')).to_have_count(3)
        page.evaluate('window.failTurn()')
        expect(page.locator('.assistant-message [role="alert"]')).to_have_text('The response could not be saved.')
        expect(page.locator('.message-streaming')).to_have_count(0)
        expect(page.locator('.thinking')).to_have_count(0)
        print('PASS: partial text before save, UTF-8 chunks, late profile, no duplicate reply, serialized turns, visible save failure')
        browser.close()


if __name__ == '__main__':
    main()
