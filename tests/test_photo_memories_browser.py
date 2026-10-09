"""Photo selection UI against synthetic, durable API state; no model calls."""
from copy import deepcopy

import pytest
from playwright.sync_api import expect

from apps.api.photo_memories import PhotoMemoryInput, update_photo_memory
from test_phone_map_albums_browser import album_page, pytestmark


@pytest.mark.parametrize('phone', [False, True])
def test_photo_selection_favorites_reload_clear_and_failed_save(album_page, phone):
    page, _, errors = album_page
    if not phone:
        page.set_viewport_size({'width':1440, 'height':960})
    project = page.evaluate("fetch('/api/v1/memoir/projects/album-project').then(r=>r.json())")
    profile = deepcopy(project['profile'])
    writes = []
    fail = False

    def api(route):
        nonlocal profile
        path = route.request.url.split('/api/v1/memoir')[-1].split('?')[0]
        if path == '/projects/album-project/photo-memories':
            writes.append(route.request.post_data_json)
            if fail:
                return route.fulfill(status=503, json={'detail':'Synthetic offline save'})
            profile, saved = update_photo_memory(profile, 'album-project', PhotoMemoryInput(**writes[-1]))
            return route.fulfill(json=saved)
        if path == '/projects/album-project' and route.request.method == 'GET':
            return route.fulfill(json={**project, 'profile':profile})
        if path == '/user/profile':
            return route.fulfill(json=profile)
        return route.fallback()

    page.route('**/api/v1/memoir/**', api)

    def gallery():
        if phone:
            page.locator('[data-photo-album]:visible').last.click()
            expect(page.get_by_role('dialog')).to_be_visible()
            return page.get_by_role('dialog')
        return page.locator('.workspace-media-gallery')

    wall = gallery()
    page.screenshot(path='/tmp/memoir-photo-before-'+str(phone)+'.png')
    choices = wall.locator('.photo-memory-select:visible')
    expect(choices).to_have_count(3)
    first = choices.first
    key = first.get_attribute('data-photo-key')
    first.focus()
    page.keyboard.press('Enter')
    expect(wall.locator(f'[data-photo-key="{key}"][data-photo-memory="select"]').last).to_have_attribute('aria-pressed','true')
    expect(wall.locator('[data-photo-memory="unfavorite"]:visible').first).to_be_enabled()
    assert writes[0]['action'] == 'select'
    assert len(profile['photo_memories']['album-project']['favorites']) == 1
    assert profile['photo_memories']['album-project']['selected'] == key
    # Source links are still independent from photo selection.
    expect(wall.locator('figcaption a').last).to_have_attribute('href','https://archive.example/photo')
    page.screenshot(path='/tmp/memoir-photo-selected-'+str(phone)+'.png')
    if phone:
        wall.locator('[data-close-photo-album]').click()
    expect(page.locator('.selected-photo-cue')).to_be_visible()
    page.locator('#chat-input').fill('This street reminds me of walking home.')
    # Reload reads the saved backend profile, with no browser favourite cache.
    page.reload(wait_until='networkidle')
    expect(page.locator('.selected-photo-cue')).to_be_visible()
    wall = gallery()
    wall.locator('.photo-favorites summary').click()
    expect(wall.locator('.photo-favorites .photo-memory-select')).to_have_attribute('aria-pressed','true')
    assert wall.locator('.photo-favorites .photo-favorite').bounding_box()['height'] >= 44
    fail = True
    wall.locator('.photo-favorites [data-photo-memory="unfavorite"]').click()
    expect(page.locator('#toast')).to_contain_text('未能保存')
    expect(wall.locator('.photo-favorites [data-photo-memory="unfavorite"]')).to_be_enabled()
    expect(wall.locator('.photo-favorites')).to_have_attribute('open','')
    assert profile['photo_memories']['album-project']['selected'] == key
    fail = False
    if phone:
        wall.locator('[data-close-photo-album]').click()
    page.locator('[data-photo-memory="clear"]').click()
    expect(page.locator('.selected-photo-cue')).to_have_count(0)
    assert len(profile['photo_memories']['album-project']['favorites']) == 1
    wall = gallery() if phone else wall
    if not wall.locator('.photo-favorites').evaluate('(details) => details.open'):
        wall.locator('.photo-favorites summary').click()
    wall.locator('.photo-favorites [data-photo-memory="unfavorite"]').click()
    expect(wall.locator('.photo-favorites')).to_have_count(0)
    saved = profile['photo_memories']['album-project']
    assert saved['favorites'] == [] and saved['selected'] is None
    assert saved['selection_revision']
    assert not errors
