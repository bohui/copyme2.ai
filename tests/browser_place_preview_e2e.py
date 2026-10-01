"""Verify a real map begins while the conversational stream remains open."""
import argparse

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:3010')
    args = parser.parse_args()
    errors = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 960}, locale='en-AU')
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('**/agent/config', lambda route: route.fulfill(json={
            'auth_mode': 'test', 'google_maps_browser_api_key': 'test-browser-key'}))
        def imagery(route):
            response = route.fetch()
            route.fulfill(response=response, body=response.text() + '''
                Cesium.Google2DImageryProvider.fromUrl = async () => new Cesium.GridImageryProvider();
            ''')
        page.route('**/Build/Cesium/Cesium.js', imagery)
        page.route('**/place-photos?**', lambda route: route.fulfill(json={'items': [], 'status': 'NO_MATCH'}))
        page.add_init_script('''
          const original = window.fetch.bind(window);
          window.fetch = async (url, options) => {
            if (!String(url).endsWith('/agent/turn')) return original(url, options);
            const {project_id} = JSON.parse(options.body);
            const journey = {schema_version: 1, place: 'Sydney', hierarchy: ['Earth', 'Australia', 'Sydney'],
              granularity: 'city', latitude: -33.8688, longitude: 151.2093, duration_ms: 5200};
            const encoder = new TextEncoder();
            return new Response(new ReadableStream({start(controller) {
              const emit = event => controller.enqueue(encoder.encode(JSON.stringify(event) + '\\n'));
              emit({type: 'text_delta', text: 'Sydney sounds like an important place. '});
              emit({type: 'place_preview', data: {project_id, source_sequence: 1, place_journey: journey}});
              window.finishReply = () => {
                const reply = 'Sydney sounds like an important place. What do you remember?';
                emit({type: 'text_delta', text: 'What do you remember?'});
                emit({type: 'conversation_saved', data: {project_id, reply, conversation_saved: true}});
                emit({type: 'workspace_update', data: {project_id, source_sequence: 1,
                  place_journey: {...journey, status: 'active', revision: 1},
                  place_journey_change: {changed: true, revision: 1}}});
                emit({type: 'result', data: {reply}});
                controller.close();
              };
            }}), {headers: {'Content-Type': 'application/x-ndjson'}});
          };
        ''')
        page.goto(args.base_url + '/memoir', wait_until='networkidle')
        page.locator("[data-action='start-story'][data-mode='self']").click()
        expect(page.locator('main.chat-main')).to_be_visible()
        expect(page.locator('.message-streaming')).to_have_count(0, timeout=15000)
        page.locator('#chat-input').fill('I grew up in Sydney.')
        page.locator("#chat-form button[type='submit']").click()
        expect(page.locator('.place-journey-scene.is-cesium-live')).to_be_visible(timeout=30000)
        expect(page.locator('.message-streaming')).to_have_count(1)
        expect(page.locator('.message-streaming .message-text')).to_contain_text('Sydney sounds')
        assert page.evaluate('typeof window.finishReply') == 'function'
        page.evaluate('window.finishReply()')
        expect(page.locator('.message-streaming')).to_have_count(0, timeout=10000)
        expect(page.locator('.place-journey-scene')).to_be_visible()
        assert not errors, errors
        browser.close()
    print('PASS: real map starts before reply completion; confirmed place remains visible')


if __name__ == '__main__':
    main()
