"""Verify the real gallery renders early photos before a photo stream finishes."""
import argparse

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:3010')
    parser.add_argument('--blocked', action='store_true', help='Verify blocked-source error and manual retry')
    args = parser.parse_args()
    errors = []
    journey = {'schema_version': 1, 'status': 'active', 'revision': 1, 'place': 'Chengde',
               'period': '1980s', 'hierarchy': ['Earth', 'China', 'Hebei', 'Chengde'],
               'granularity': 'city', 'latitude': 40.9515, 'longitude': 117.9634, 'duration_ms': 2800}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 960}, locale='en-AU')
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('**/agent/config', lambda route: route.fulfill(json={'auth_mode': 'test'}))
        page.route('**/api/v1/memoir/agent/turn', lambda route: route.fulfill(json={
            'reply': 'What do you remember about Chengde?', 'trace': [], 'trace_mode': 'codex',
            'place_journey': journey, 'place_journey_change': {'changed': True, 'revision': 1}}))
        page.add_init_script('''
          const original = window.fetch.bind(window);
          window.photoCalls = 0;
          window.fetch = async (url, options) => {
            if (!String(url).includes('/place-photos?')) return original(url, options);
            window.photoCalls++;
            if (window.photoBlockedTest && window.photoCalls === 1) {
              return new Response(JSON.stringify({items: [], status: 'UNAVAILABLE', searching: false,
                failures: [{provider: 'google', reason: 'verification_required'}]}) + '\\n',
                {headers: {'Content-Type': 'application/x-ndjson'}});
            }
            if (options.headers.Accept !== 'application/x-ndjson') throw Error('Missing photo streaming Accept');
            const picture = index => ({asset_id: 'photo-' + index, title: 'Chengde street ' + index,
              image_url: '/static/timeline_avatar_child_female.png?photo=' + index,
              source_url: 'https://archive.example/' + index, date_expression: '1983',
              latitude: 40.9515, longitude: 117.9634,
              allowed_actions: {embed: true}});
            const encoder = new TextEncoder();
            return new Response(new ReadableStream({start(controller) {
              const emit = page => controller.enqueue(encoder.encode(JSON.stringify(page) + '\\n'));
              emit({items: [], status: 'SEARCHING', searching: true});
              emit({items: [picture(1)], status: 'PARTIAL', searching: true, next_cursor: null});
              window.finishPhotoSearch = () => {
                emit({items: [picture(1), picture(2)], status: 'PARTIAL', searching: false, next_cursor: null});
                controller.close();
              };
            }}), {headers: {'Content-Type': 'application/x-ndjson'}});
          };
        ''')
        page.add_init_script('window.photoBlockedTest = ' + ('true' if args.blocked else 'false'))
        page.goto(args.base_url + '/memoir', wait_until='networkidle')
        page.locator("[data-action='start-story'][data-mode='self']").click()
        expect(page.locator('main.chat-main')).to_be_visible()
        expect(page.locator('.message-streaming')).to_have_count(0, timeout=15000)
        page.locator('#chat-input').fill('I remember Chengde in the 1980s.')
        page.locator("#chat-form button[type='submit']").click()
        gallery = page.locator('.workspace-media-gallery .place-pictures')
        if args.blocked:
            empty = page.locator('.workspace-media-gallery')
            expect(empty.locator('[role=status]')).to_have_text(
                'Photo sources blocked automated access. You can try again later.', timeout=20000)
            expect(empty.locator('figure')).to_have_count(0)
            expect(page.locator("#chat-form button[type='submit']")).to_be_enabled()
            empty.locator('[data-photo-retry]').click()
        expect(gallery.locator('figure')).to_have_count(1, timeout=20000)
        expect(gallery.locator('[role=status]')).to_have_text('Finding more photos…')
        expect(page.locator("#chat-form button[type='submit']")).to_be_enabled()
        assert page.evaluate('window.photoCalls') == (2 if args.blocked else 1)
        page.evaluate('window.finishPhotoSearch()')
        expect(gallery.locator('figure')).to_have_count(2)
        expect(gallery.locator('[role=status]')).to_have_count(0)
        assert not errors, errors
        browser.close()
    print('PASS: blocked-source error and retry' if args.blocked else
          'PASS: first photo visible before completion, loading continues, final batch deduplicated')


if __name__ == '__main__':
    main()
