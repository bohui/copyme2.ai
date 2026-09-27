"""Browser contract check with synthetic collection responses; no LLM or private memories."""
import argparse
import json

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:3010')
    args = parser.parse_args()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for locale in ['en-AU', 'zh-CN']:
            context = browser.new_context(viewport={'width': 1280, 'height': 900}, locale=locale)
            page = context.new_page()
            page.add_init_script(f"localStorage.setItem('copyme2_ui_locale', '{locale}')")
            page.route('**/agent/config', lambda route: route.fulfill(json={'auth_mode': 'test'}))
            writes = []
            def collection(route):
                if route.request.method == 'PUT':
                    payload = route.request.post_data_json
                    writes.append(payload)
                    route.fulfill(json={'revision': len(writes), 'periods': payload['periods'], 'ready': payload['confirm_ready']})
                else:
                    route.fulfill(json={'revision': 0, 'periods': {}, 'ready': False, 'tasks': [],
                        'sources': [{'id': 'school', 'content': 'I attended school in 1970. <script>bad()</script>'}]})
            page.route('**/agent/collection/*', collection)
            proposed = []
            def organise(route):
                proposed.append(route.request.post_data_json)
                route.fulfill(json={'id': 'outline', 'kind': 'BuildOutline', 'status': 'QUEUED', 'result': None})
            page.route('**/agent/collection/*/organise', organise)
            page.route('**/agent/tasks/outline', lambda route: route.fulfill(json={
                'id': 'outline', 'kind': 'BuildOutline', 'status': 'SUCCEEDED',
                'result': {'title': 'School days', 'sections': [{'title': 'Growing up', 'memory_ids': ['school']}]}}))
            page.goto(args.base_url, wait_until='networkidle')
            page.get_by_role('button', name='Begin my story' if locale == 'en-AU' else '开始讲我的故事').click()
            page.locator('[data-profile-trigger]').click()
            page.locator('[data-profile-action="collection"]').click()
            dialog = page.get_by_role('dialog')
            expect(dialog).to_be_visible()
            expect(dialog.locator('fieldset')).to_have_count(7)
            assert 'Collection.' not in dialog.inner_text()
            dialog.locator('[type=submit]').click()
            expect(dialog.locator('[data-status-message]')).not_to_be_empty()
            assert not writes and not proposed
            dialog.locator('[data-confirm]').check()
            dialog.locator('[type=submit]').click()
            assert not writes and not proposed
            for fieldset in dialog.locator('fieldset').all():
                fieldset.locator('[data-status]').select_option('skipped')
                fieldset.locator('[data-note]').fill('I prefer to skip this period.')
            school = dialog.locator('[data-stage=childhood]')
            school.locator('[data-status]').select_option('recorded')
            school.locator('[data-memories]').select_option('school')
            dialog.locator('[type=submit]').click()
            expect(dialog.locator('.collection-task h3')).to_have_text('School days', timeout=15000)
            assert len(writes) == 1 and writes[0]['confirm_ready'] is True
            assert len(proposed) == 1 and proposed[0]['expected_revision'] == 1
            assert proposed[0]['language'] == locale
            with page.expect_download() as download:
                dialog.locator('[data-download]').click()
            with open(download.value.path()) as artifact:
                assert json.load(artifact)['sections'][0]['memory_ids'] == ['school']
            page.screenshot(path=f'/tmp/memoir-collection-{locale}.png', full_page=True)
            dialog.locator('[data-close]').click()
            expect(dialog).to_have_count(0)
            print(f'PASS {locale}: explicit confirmation, seven periods, source selection, queued result, download')
            context.close()
        browser.close()


if __name__ == '__main__':
    main()
