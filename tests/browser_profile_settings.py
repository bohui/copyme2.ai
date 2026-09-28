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
        page.get_by_role('button', name='Begin my story').click()
        trigger = page.locator('[data-profile-trigger]')
        trigger.click()
        menu = page.locator('.profile-dropdown')
        expect(menu.locator('select')).to_have_count(0)
        expect(page.locator('#locale-switcher-root')).to_have_count(0)
        page.get_by_role('menuitem', name='Profile', exact=True).click()
        dialog = page.get_by_role('dialog', name='Your profile')
        expect(dialog.get_by_label('Name', exact=True)).to_have_value('慧博')
        expect(dialog.get_by_label('Preferred conversation language')).to_have_value('zh-CN')
        dialog.get_by_label('Name', exact=True).fill('Cancelled edit')
        dialog.get_by_role('button', name='Cancel').click()
        expect(dialog).to_have_count(0)
        expect(trigger).to_be_focused()
        assert writes == []
        trigger.click()
        page.get_by_role('menuitem', name='Profile', exact=True).click()
        dialog.get_by_label('Preferred conversation language').select_option('en-AU')
        dialog.get_by_label('Childhood place').fill('悉尼')
        dialog.get_by_role('button', name='Save changes').click()
        expect(dialog).to_have_count(0)
        assert writes[-1]['preferred_language'] == 'en-AU'
        assert writes[-1]['childhood_place'] == '悉尼'
        assert writes[-1]['name'] == '慧博'
        trigger.click()
        page.get_by_role('menuitem', name='Profile', exact=True).click()
        expect(dialog.get_by_label('Preferred conversation language')).to_have_value('en-AU')
        fail_save = True
        dialog.get_by_role('button', name='Save changes').click()
        expect(dialog.get_by_role('status')).to_contain_text('could not be saved')
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
