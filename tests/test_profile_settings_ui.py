"""Exercise the profile dialog in Chromium with a controlled settings API."""
from pathlib import Path
from urllib.parse import urlparse

import pytest

playwright = pytest.importorskip('playwright.sync_api')
WEB = Path(__file__).resolve().parents[1] / 'apps/web'
FIELDS = ['name', 'birth_year', 'birth_date_expression', 'birth_place', 'childhood_place', 'avatar_style']


@pytest.fixture(scope='module')
def browser():
    with playwright.sync_playwright() as driver:
        instance = driver.chromium.launch()
        yield instance
        instance.close()


@pytest.fixture
def page(browser):
    page = browser.new_page(viewport={'width': 390, 'height': 844})
    html = '''<!doctype html><html lang="en-AU"><head><link rel="stylesheet" href="/styles.css"></head><body>
      <script type="module">
      import { openProfileSettings } from '/client/memoir/profile.js';
      window.sameScope = true; window.writes = []; window.saved = []; window.languages = [];
      window.settings = {name:'Avery', preferred_language:'en-AU', birth_date_expression:'around 1960',
        avatar_style:'female', profile_automation:{schema_version:1, revision:1, auto_enabled:true,
          stopped:false, manual_complete:false, field_locks:{}}};
      window.openSettings = () => openProfileSettings({
        isCurrent: () => window.sameScope,
        api: async (_path, options) => {
          if (!options) {
            if (window.holdLoad) await new Promise(resolve => window.resolveLoad = resolve);
            if (window.loadFailure) throw Error('Unavailable');
            return structuredClone(window.settings);
          }
          window.writes.push(JSON.parse(options.body));
          if (window.holdSave) await new Promise(resolve => window.resolveSave = resolve);
          if (window.saveFailure) throw Error('Unavailable');
          return structuredClone(window.nextSettings || window.settings);
        },
        onSave: async settings => {window.saved.push(settings); if (window.syncFailure) throw Error('Sync failed');},
        onLanguageChange: async locale => {window.languages.push(locale);},
      });
      </script></body></html>'''

    def route(request):
        path = urlparse(request.request.url).path
        if path == '/':
            request.fulfill(body=html, content_type='text/html')
        elif path.startswith(('/client/', '/messages/')) or path == '/styles.css':
            file = WEB / ('public/styles.css' if path == '/styles.css' else path.lstrip('/'))
            content_type = 'application/json' if file.suffix == '.json' else 'text/css' if file.suffix == '.css' else 'text/javascript'
            request.fulfill(path=file, content_type=content_type)
        else:
            request.abort()

    page.route('**/*', route)
    page.goto('http://profile.test/')
    page.wait_for_function('typeof openSettings === "function"')
    yield page
    page.close()


def open_settings(page):
    page.evaluate('openSettings()')
    return page.locator('[data-profile-settings]')


def test_settings_save_confirms_edited_fields_and_deliberate_blanks(page):
    dialog = open_settings(page)
    playwright.expect(dialog.locator('[name=avatar_style]')).to_have_value('female')
    dialog.locator('[name=name]').fill('')
    dialog.locator('[name=birth_date_expression]').fill(' about 1960 ')
    dialog.locator('[name=avatar_style]').select_option('male')
    dialog.locator('[name=confirm_childhood_place]').check()
    dialog.locator('[type=submit]').click()
    playwright.expect(dialog).to_have_count(0)
    assert page.evaluate('writes') == [{'preferred_language': 'en-AU', 'name': None,
        'birth_date_expression': 'about 1960', 'childhood_place': None, 'avatar_style': 'male'}]
    assert len(page.evaluate('saved')) == 1


def test_language_only_save_leaves_unconfirmed_profile_fields_eligible(page):
    dialog = open_settings(page)
    dialog.locator('[name=preferred_language]').select_option('zh-CN')
    dialog.locator('[type=submit]').click()
    playwright.expect(dialog).to_have_count(0)
    assert page.evaluate('writes') == [{'preferred_language': 'zh-CN'}]


def test_confirm_all_submits_supported_values_including_blanks_and_avatar(page):
    dialog = open_settings(page)
    dialog.locator('[data-confirm-all]').click()
    playwright.expect(dialog).to_have_count(0)
    patch = page.evaluate('writes[0]')
    assert set(patch) == set(FIELDS + ['preferred_language', 'profile_confirm_all'])
    assert patch['profile_confirm_all'] is True
    assert patch['birth_year'] is None and patch['birth_place'] is None
    assert patch['avatar_style'] == 'female'


def test_enable_and_field_release_are_separate_actions_and_preserve_other_drafts(page):
    page.evaluate('''settings.profile_automation = {schema_version:1, revision:2, auto_enabled:false,
      stopped:true, manual_complete:true, field_locks:{name:'manual', avatar_style:'manual'}};''')
    dialog = open_settings(page)
    dialog.locator('[name=birth_place]').fill('Sydney')
    page.evaluate('nextSettings = {...settings, profile_automation:{...settings.profile_automation, revision:3, stopped:false}}')
    dialog.locator('[data-enable]').click()
    playwright.expect(dialog.locator('[data-automation-status]')).to_contain_text('enabled')
    playwright.expect(dialog.locator('[name=confirm_name]')).to_be_checked()
    playwright.expect(dialog.locator('[name=birth_place]')).to_have_value('Sydney')
    playwright.expect(dialog.locator('[name=confirm_birth_place]')).to_be_checked()
    page.evaluate('nextSettings.profile_automation = {schema_version:1, revision:4, stopped:false, field_locks:{name:"manual"}}')
    dialog.locator('[data-release=avatar_style]').click()
    playwright.expect(dialog.locator('[data-release=avatar_style]')).to_be_hidden()
    playwright.expect(dialog.locator('[name=confirm_avatar_style]')).not_to_be_checked()
    playwright.expect(dialog.locator('[name=avatar_style]')).to_have_value('female')
    assert page.evaluate('writes') == [{'profile_auto_enabled': True}, {'profile_release_fields': ['avatar_style']}]
    dialog.locator('[type=submit]').click()
    playwright.expect(dialog).to_have_count(0)
    assert page.evaluate('writes[2]') == {'preferred_language': 'en-AU', 'name': 'Avery', 'birth_place': 'Sydney'}


@pytest.mark.parametrize('pending', ['load', 'save'])
def test_pending_settings_response_after_account_switch_has_no_callbacks(page, pending):
    if pending == 'load':
        page.evaluate('holdLoad = true; void openSettings()')
        page.wait_for_function('typeof resolveLoad === "function"')
    else:
        dialog = open_settings(page)
        page.evaluate('holdSave = true; languages = []')
        dialog.locator('[type=submit]').click()
        page.wait_for_function('typeof resolveSave === "function"')
    page.evaluate(f'sameScope = false; resolve{pending.title()}()')
    playwright.expect(page.locator('[data-profile-settings]')).to_have_count(0)
    assert page.evaluate('saved') == []
    assert page.evaluate('languages') == []


def test_failed_save_keeps_values_and_pending_save_blocks_cancel_and_double_submit(page):
    dialog = open_settings(page)
    dialog.locator('[name=name]').fill('New name')
    page.evaluate('holdSave = true; saveFailure = true')
    dialog.locator('[type=submit]').click()
    page.wait_for_function('typeof resolveSave === "function"')
    page.keyboard.press('Escape')
    playwright.expect(dialog).to_be_visible()
    playwright.expect(dialog.locator('[type=submit]')).to_be_disabled()
    dialog.locator('[data-cancel]').click()
    playwright.expect(dialog).to_be_visible()
    page.evaluate('resolveSave()')
    playwright.expect(dialog.locator('[data-status]')).to_contain_text('could not be saved')
    playwright.expect(dialog.locator('[name=name]')).to_have_value('New name')
    assert len(page.evaluate('writes')) == 1
    page.evaluate('holdSave = false; saveFailure = false')
    dialog.locator('[type=submit]').click()
    playwright.expect(dialog).to_have_count(0)


def test_dialog_labels_fit_mobile_and_load_legacy_profile_without_controls(page):
    page.evaluate('document.documentElement.lang = "zh-CN"')
    dialog = open_settings(page)
    playwright.expect(dialog.locator('h2')).to_have_text('个人资料')
    assert dialog.evaluate('(node) => node.scrollWidth <= node.clientWidth')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    dialog.locator('[data-cancel]').click()
    playwright.expect(dialog).to_have_count(0)
    page.evaluate('delete settings.profile_automation')
    dialog = open_settings(page)
    playwright.expect(dialog.locator('[data-automation]')).to_be_hidden()
    playwright.expect(dialog.locator('[name=birth_date_expression]')).to_have_value('around 1960')
    dialog.locator('[name=avatar_style]').select_option('male')
    dialog.locator('[type=submit]').click()
    playwright.expect(dialog).to_have_count(0)
    assert page.evaluate('writes[0].avatar_style') == 'male'
