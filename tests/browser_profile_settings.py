"""Profile menu and dialog checks against the local dev app (mock private profile API)."""
import os
from playwright.sync_api import expect, sync_playwright


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1280, 'height': 900})
        saved = {'name': '慧博', 'birth_year': 1983, 'birth_place': '开封',
                 'childhood_place': None, 'preferred_language': 'zh-CN'}
        writes = []
        fail_save = False

        def profile_api(route):
            if route.request.method == 'PATCH':
                if fail_save:
                    route.fulfill(status=503, json={'detail': 'unavailable'})
                    return
                writes.append(route.request.post_data_json)
                saved.update(writes[-1])
            route.fulfill(json=saved)

        page.route('**/api/v1/memoir/agent/profile', profile_api)
        page.goto(os.getenv('MEMOIR_TEST_URL', 'http://127.0.0.1:3010/memoir'), wait_until='networkidle')
        expect(page.locator('html')).to_have_attribute('lang', 'zh-CN')
        page.locator("[data-action='start-story'][data-mode='self']").click()
        trigger = page.locator('[data-profile-trigger]')
        trigger.click()
        menu = page.locator('.profile-dropdown')
        expect(menu.locator('select')).to_have_count(0)
        expect(page.locator('#locale-switcher-root')).to_have_count(0)
        menu.locator("[data-profile-action='settings']").click()
        dialog = page.locator('[data-profile-settings]')
        expect(dialog.locator('[name=name]')).to_have_value('慧博')
        expect(dialog.locator('[name=preferred_language]')).to_have_value('zh-CN')
        expect(page.locator('html')).to_have_attribute('lang', 'zh-CN')
        dialog.locator('[name=name]').fill('Cancelled edit')
        dialog.locator('[data-cancel]').click()
        expect(dialog).to_have_count(0)
        expect(trigger).to_be_focused()
        assert writes == []
        trigger.click()
        page.locator('.profile-dropdown [data-profile-action=settings]').click()
        dialog.locator('[name=preferred_language]').select_option('en-AU')
        dialog.locator('[name=childhood_place]').fill('悉尼')
        dialog.locator('[type=submit]').click()
        expect(dialog).to_have_count(0)
        assert writes[-1]['preferred_language'] == 'en-AU'
        assert writes[-1]['childhood_place'] == '悉尼'
        assert writes[-1]['name'] == '慧博'
        expect(page.locator('html')).to_have_attribute('lang', 'en-AU')
        page.reload(wait_until='networkidle')
        expect(page.locator('html')).to_have_attribute('lang', 'en-AU')
        trigger.click()
        page.locator('.profile-dropdown [data-profile-action=settings]').click()
        expect(dialog.locator('[name=preferred_language]')).to_have_value('en-AU')
        fail_save = True
        dialog.locator('[type=submit]').click()
        expect(dialog.locator('[data-status]')).to_contain_text('could not be saved')
        expect(dialog).to_be_visible()
        fail_save = False
        page.screenshot(path='/tmp/memoir-profile-desktop.png')
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert dialog.evaluate('e => e.scrollWidth <= e.clientWidth')
        page.screenshot(path='/tmp/memoir-profile-mobile.png')
        page.keyboard.press('Escape')
        expect(dialog).to_have_count(0)
        browser.close()
        print('Profile menu, saved values, cancel, focus, save, failure, Escape and mobile layout passed.')


if __name__ == '__main__':
    main()
