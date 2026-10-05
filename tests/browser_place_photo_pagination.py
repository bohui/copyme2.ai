"""Verify gallery scrolling, append/deduplication, retry and exhaustion."""
import argparse
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:3010')
    args = parser.parse_args()
    requests, errors = [], []
    journey = {'schema_version': 1, 'status': 'active', 'revision': 1, 'place': 'Chengde',
               'period': '1980s', 'hierarchy': ['Earth', 'China', 'Hebei', 'Chengde'],
               'granularity': 'city', 'latitude': 40.9515, 'longitude': 117.9634, 'duration_ms': 2800}

    def picture(index):
        host = ['flickr.com', 'commons.wikimedia.org', 'archive.example'][index % 3]
        return {'asset_id': f'photo-{index}', 'kind': 'image', 'title': f'Chengde street {index}',
                'image_url': f'/static/timeline_avatar_child_female.png?photo={index}',
                'source_url': f'https://{host}/photos/{index}', 'date_expression': '1983',
                'latitude': 40.9515, 'longitude': 117.9634,
                'allowed_actions': {'embed': True}}

    def photos(route):
        params = parse_qs(urlsplit(route.request.url).query, keep_blank_values=True)
        assert params['period'] == ['1980s'], params
        cursor = params.get('cursor', [None])[0]
        requests.append(cursor)
        if cursor is None:
            items, next_cursor = [picture(i) for i in range(1, 11)], 'page2'
        elif len(requests) == 2:
            route.fulfill(json={'status': 'UNAVAILABLE', 'items': []})
            return
        elif cursor == 'page2':
            items, next_cursor = [picture(i) for i in range(10, 21)], 'page3'
        else:
            assert cursor == 'page3', requests
            items, next_cursor = [picture(i) for i in range(20, 24)], None
        route.fulfill(json={'status': 'READY', 'items': items, 'next_cursor': next_cursor})

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 700}, locale='en-AU')
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('**/agent/config', lambda route: route.fulfill(json={'auth_mode': 'test'}))
        page.route('**/place-photos?**', photos)
        page.route('**/api/v1/memoir/agent/turn', lambda route: route.fulfill(json={
            'reply': 'What do you remember about Chengde?', 'trace': [], 'trace_mode': 'codex',
            'profile_updates': {'story_focus': {'when': '1980s'}}, 'place_journey': journey,
            'place_journey_change': {'changed': True, 'kind': 'created', 'revision': 1}}))
        page.goto(args.base_url + '/memoir', wait_until='networkidle')
        page.locator("[data-action='start-story'][data-mode='self']").click()
        expect(page.locator('main.chat-main')).to_be_visible()
        expect(page.locator('.message-streaming')).to_have_count(0, timeout=15000)
        page.locator('#chat-input').fill('I remember Chengde in the 1980s.')
        page.locator("#chat-form button[type='submit']").click()
        gallery = page.locator('.workspace-media-gallery .place-pictures')
        expect(gallery.locator('figure')).to_have_count(10, timeout=30000)
        expect(page.locator('.assistant-message .message-text').last).to_have_text('What do you remember about Chengde?')
        expect(page.locator('.message-streaming')).to_have_count(0, timeout=15000)
        gallery.evaluate('(node) => { node.scrollTop = node.scrollHeight; }')
        retry = page.locator('[data-photo-more]')
        expect(retry).to_have_text('Try loading more photos again', timeout=15000)
        expect(gallery.locator('figure')).to_have_count(10)
        page.wait_for_timeout(300)
        assert len(requests) == 2, requests  # No automatic failure/retry loop.
        retry.scroll_into_view_if_needed()
        before_append = page.evaluate("document.querySelector('.workspace-media-gallery .place-pictures').scrollTop")
        assert before_append > 0, 'Fixture must scroll before append preservation is exercised'
        retry.click()
        expect(gallery.locator('figure')).to_have_count(20, timeout=15000)
        after_append = page.evaluate("document.querySelector('.workspace-media-gallery .place-pictures').scrollTop")
        assert abs(after_append - before_append) < 2, f'Appending changed scroll from {before_append} to {after_append}'
        gallery.evaluate('(node) => { node.scrollTop = node.scrollHeight; }')
        expect(gallery.locator('figure')).to_have_count(23, timeout=15000)
        expect(page.locator('[data-photo-more]')).to_have_count(0)
        assert requests == [None, 'page2', 'page2', 'page3'], requests
        assert len(set(gallery.locator('img').evaluate_all('(nodes) => nodes.map(node => node.src)'))) == 23
        assert not errors, errors
        browser.close()
    print('PASS: scroll pagination, append/deduplication, scroll preservation, retry and exhaustion')


if __name__ == '__main__':
    main()
