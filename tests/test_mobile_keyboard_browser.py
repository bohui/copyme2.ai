"""Software-keyboard layout regression with synthetic API and viewport events.

These are browser-engine checks, not physical iOS keyboard/IME verification.
Run with MEMOIR_BROWSER_URL pointing at this checkout's isolated frontend.
"""
import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from browser_supabase_fixture import install_supabase_fixture

pytestmark = pytest.mark.skipif(not os.getenv('MEMOIR_BROWSER_URL'), reason='Requires isolated source frontend')
ARTIFACTS = Path(__file__).resolve().parents[1] / 'var' / 'mobile-keyboard'


@pytest.fixture(params=['chromium', 'webkit'])
def keyboard_page(request):
    with sync_playwright() as pw:
        launch = {}
        executable = os.getenv(f'MEMOIR_{request.param.upper()}_EXECUTABLE')
        if executable:
            launch['executable_path'] = executable
        browser = getattr(pw, request.param).launch(**launch)

        def open_page(*, touch=True, width=390, height=844):
            context = browser.new_context(viewport={'width': width, 'height': height},
                has_touch=touch, is_mobile=touch, reduced_motion='reduce', locale='zh-CN')
            base = os.environ['MEMOIR_BROWSER_URL']
            context.add_cookies([
                {'name': 'copyme2_ui_locale', 'value': 'zh-CN', 'url': base},
                {'name': 'copyme2_ui_locale_source', 'value': 'fixed', 'url': base},
            ])
            user = {'id': 'keyboard-fixture-owner', 'is_anonymous': False, 'user_metadata': {}}
            install_supabase_fixture(context, f"""window.supabase={{createClient:()=>({{auth:{{
                getSession:async()=>({{data:{{session:{{access_token:'fixture-only',user:{json.dumps(user)}}}}}}}),
                getUser:async()=>({{data:{{user:{json.dumps(user)}}}}}),onAuthStateChange:()=>({{}})
            }}}})}};""")
            place = dict(place='承德', hierarchy=['Earth', '中国', '河北', '承德'],
                granularity='city', latitude=40.97, longitude=117.93,
                revision=1, status='active', schema_version=1)
            profile = {'preferred_language': 'zh-CN', 'name': 'Fixture', 'memory_places': [place],
                'conversation_language': {'initialized': True, 'locale': 'zh-CN', 'source': 'explicit', 'version': 1, 'revision': 1}}

            def api(route):
                path = route.request.url.split('/api/v1/memoir')[-1].split('?')[0]
                data = {}
                if path == '/agent/config':
                    data = {'supabase_url': 'https://auth.test', 'supabase_publishable_key': 'public', 'auth_mode': 'supabase'}
                elif path in ('/agent/profile', '/user/profile'):
                    data = profile
                elif path == '/projects/keyboard-project':
                    data = {'id': 'keyboard-project', 'revision': 1, 'profile': profile, 'mode': 'self', 'workspace_unlocked': False}
                elif path == '/story/state':
                    data = {'family_features_enabled': False, 'recall_status': {'rounds_completed': 0, 'free_rounds': 200, 'paid': False, 'payment_required': False}}
                elif path == '/user/conversations':
                    data = {'items': []}
                elif path == '/user/projects/keyboard-project/history':
                    data = {'project_id': 'keyboard-project', 'policy_epoch': '1', 'items': [], 'next_cursor': None}
                elif path == '/projects/keyboard-project/journey':
                    data = {'active_session': None}
                elif path == '/agent/place-journey':
                    data = {'place_journey': None}
                elif path == '/agent/turn':
                    next_place = dict(place, place='悉尼', hierarchy=['Earth', 'Australia', 'Sydney'],
                        latitude=-33.87, longitude=151.21, revision=2)
                    profile['memory_places'] = [place, next_place]
                    data = {'reply': '后来在悉尼的生活是什么样的？', 'trace': [], 'trace_mode': 'codex',
                        'place_journey': next_place,
                        'place_journey_change': {'changed': True, 'kind': 'created', 'revision': 2}}
                elif path.endswith('/memory-sessions'):
                    return route.fulfill(status=403, content_type='application/json', body='{}')
                route.fulfill(content_type='application/json', body=json.dumps(data))

            context.route('**/api/v1/memoir/**', api)
            # Keep map failure deterministic; no real map imagery, provider or model calls.
            context.route('https://cesium.com/**', lambda route: route.abort())
            context.add_init_script("""(() => {
                localStorage.setItem('memory-spark-project', 'keyboard-project');
                sessionStorage.setItem('memory-spark-chat-history:keyboard-project', JSON.stringify([
                    {id:'opening',role:'assistant',text:'您最早记得的一段往事是什么？'},
                    {id:'memory',role:'user',text:'我小时候住在承德。'},
                    {id:'reply',role:'assistant',text:'讲讲那里的生活。'}
                ]));
                const viewport = new EventTarget();
                Object.assign(viewport, {height:innerHeight, width:innerWidth, offsetTop:0, scale:1});
                Object.defineProperty(window, 'visualViewport', {value:viewport, configurable:true});
                window.setKeyboardViewport = values => {
                    Object.assign(viewport, values);
                    viewport.dispatchEvent(new Event('resize'));
                    viewport.dispatchEvent(new Event('scroll'));
                };
            })();""")
            page = context.new_page()
            page.goto(base + '/memoir/interview/keyboard-project')
            expect(page.locator('#chat-input')).to_be_enabled(timeout=30000)
            # The mobile meta viewport is applied after init scripts run. Start
            # our synthetic viewport at the settled layout size, as Safari does.
            page.evaluate("setKeyboardViewport({height:innerHeight, width:innerWidth})")
            expect(page.locator('html')).to_have_css('--conversation-height', f"{height}px")
            expect(page.locator('.user-message')).to_have_count(1)
            expect(page.locator('#workspace-detail')).to_be_visible()
            expect(page.locator('.place-journey-scene')).to_be_visible()
            history_toggle = page.locator('[data-action="toggle-chat-history"]')
            if history_toggle.get_attribute('aria-expanded') == 'false':
                history_toggle.click()
            expect(page.locator('#chat-history')).to_be_visible()
            page.evaluate("document.querySelector('#chat-scroll').scrollTop = 1e9")
            page.evaluate("""() => {
                window.originalWorkspace = document.querySelector('#workspace-detail');
                window.originalScene = document.querySelector('.place-journey-scene');
            }""")
            return page

        yield open_page
        browser.close()


def viewport(page, height, *, top=0, scale=1):
    page.evaluate('values => setKeyboardViewport(values)', {'height': height, 'offsetTop': top, 'scale': scale})
    # Wait for the existing requestAnimationFrame viewport controller.
    expected_height = height if scale == 1 else page.evaluate('innerHeight')
    expect(page.locator('html')).to_have_css('--conversation-height', f'{expected_height}px')


def usable_chat(page, height, top=0):
    expect(page.locator('#chat-history')).to_be_visible()
    # Keep real message text readable without forcing a particular scroll
    # position when the restored workspace changes the available chat height.
    page.wait_for_function("""() => {
        const history = document.querySelector('#chat-scroll').getBoundingClientRect();
        return [...document.querySelectorAll('.assistant-message .message-text')].some(node => {
            const text = node.getBoundingClientRect();
            const visible = Math.min(text.bottom, history.bottom) - Math.max(text.top, history.top);
            return text.height > 0 && visible >= Math.min(20, text.height / 2);
        });
    }""", timeout=5000)
    expect(page.locator('#chat-input')).to_be_visible()
    expect(page.locator('#chat-form .send-button')).to_be_visible()
    boxes = page.evaluate("""() => {
        const box = selector => document.querySelector(selector).getBoundingClientRect().toJSON();
        return {history:box('#chat-scroll'), input:box('#chat-input'), send:box('.send-button'),
            header:box('.story-topbar'), composer:box('.composer-wrap'),
            overflow:document.documentElement.scrollWidth > innerWidth};
    }""")
    assert boxes['header']['top'] == pytest.approx(top, abs=1), boxes
    assert boxes['history']['height'] > 20, boxes
    assert boxes['input']['height'] >= 36 and boxes['send']['height'] >= 36, boxes
    assert boxes['composer']['bottom'] <= height + top + 1, boxes
    assert not boxes['overflow'], boxes


def capture(page, name):
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(ARTIFACTS / f'{page.context.browser.browser_type.name}-{name}.png'))


@pytest.mark.parametrize('width,height,keyboard_height', [(390,844,460), (844,390,220)])
def test_keyboard_hides_workspace_restores_same_scene_and_reopens(keyboard_page, width, height, keyboard_height):
    page = keyboard_page(width=width, height=height)
    field = page.locator('#chat-input')
    field.fill('我的童年回忆')
    expect(page.locator('#workspace-detail')).to_be_visible()  # Hardware focus alone.
    capture(page, f'{width}-before')
    viewport(page, keyboard_height, top=24)
    expect(page.locator('#workspace-detail')).to_be_hidden()
    usable_chat(page, keyboard_height, 24)
    expect(field).to_be_focused()
    field.press('End')
    field.press('!')
    expect(field).to_have_value('我的童年回忆!')
    capture(page, f'{width}-keyboard')
    viewport(page, height)
    expect(page.locator('#workspace-detail')).to_be_visible()
    expect(field).to_be_focused()  # iOS can dismiss the keyboard without blurring.
    assert page.evaluate('document.querySelector("#workspace-detail") === originalWorkspace')
    assert page.evaluate('document.querySelector(".place-journey-scene") === originalScene')
    expect(page.locator('[data-action="toggle-workspace"]')).to_have_attribute('aria-expanded', 'true')
    usable_chat(page, height)
    capture(page, f'{width}-dismissed')
    viewport(page, keyboard_height)
    expect(page.locator('#workspace-detail')).to_be_hidden()
    viewport(page, height)
    expect(page.locator('#workspace-detail')).to_be_visible()
    expect(field).to_have_value('我的童年回忆!')


def test_place_update_during_keyboard_keeps_workspace_hidden(keyboard_page):
    page = keyboard_page()
    # A new place normally reveals a manually collapsed workspace.
    page.locator('[data-action="toggle-workspace"]').click()
    expect(page.locator('#workspace-detail')).to_have_class('workspace-detail is-collapsed')
    page.locator('#chat-input').fill('后来我搬到了悉尼。')
    viewport(page, 460)
    expect(page.locator('#workspace-detail')).to_be_hidden()
    page.locator('#chat-form').dispatch_event('submit')
    expect(page.get_by_text('后来在悉尼的生活是什么样的？', exact=True)).to_be_visible()
    expect(page.locator('.message-streaming')).to_have_count(0)
    expect(page.locator('#workspace-detail')).to_be_hidden()
    usable_chat(page, 460)
    page.locator('#chat-input').fill('我还记得那条街。')
    viewport(page, 844)
    expect(page.locator('#workspace-detail')).to_be_visible()
    expect(page.locator('[data-action="toggle-workspace"]')).to_have_attribute('aria-expanded', 'true')
    expect(page.locator('#chat-input')).to_have_value('我还记得那条街。')


def test_keyboard_preserves_manual_collapse(keyboard_page):
    page = keyboard_page()
    page.locator('[data-action="toggle-workspace"]').click()
    page.locator('#chat-input').fill('回忆')
    viewport(page, 460)
    expect(page.locator('#workspace-detail')).to_be_hidden()
    viewport(page, 844)
    expect(page.locator('#workspace-detail')).to_be_visible()
    expect(page.locator('[data-action="toggle-workspace"]')).to_have_attribute('aria-expanded', 'false')
    expect(page.locator('.place-journey-scene')).to_have_count(0)


def test_toolbar_pinch_zoom_unfocused_viewport_and_hardware_focus_do_not_hide(keyboard_page):
    page = keyboard_page()
    viewport(page, 460)  # No typing intent.
    expect(page.locator('#workspace-detail')).to_be_visible()
    viewport(page, 844)
    page.locator('#chat-input').focus()
    viewport(page, 760)  # Browser toolbar, not a software keyboard.
    expect(page.locator('#workspace-detail')).to_be_visible()
    viewport(page, 460, scale=2)
    expect(page.locator('#workspace-detail')).to_be_visible()
    viewport(page, 844)
    expect(page.locator('#workspace-detail')).to_be_visible()


@pytest.mark.parametrize('width', [390, 844, 1440])
def test_desktop_focused_input_does_not_suppress_workspace(keyboard_page, width):
    page = keyboard_page(touch=False, width=width)
    page.locator('#chat-input').fill('Typed with a physical keyboard.')
    viewport(page, 460)
    expect(page.locator('#workspace-detail')).to_be_visible()
    viewport(page, 844)
    expect(page.locator('#workspace-detail')).to_be_visible()


def test_rotation_while_keyboard_open_and_focus_before_resize(keyboard_page):
    page = keyboard_page()
    # Safari can dispatch the viewport event before the focus event.
    viewport(page, 460)
    expect(page.locator('#workspace-detail')).to_be_visible()
    page.locator('#chat-input').focus()
    expect(page.locator('#workspace-detail')).to_be_hidden()
    page.set_viewport_size({'width': 844, 'height': 390})
    viewport(page, 220)
    expect(page.locator('#workspace-detail')).to_be_hidden()
    usable_chat(page, 220)
    viewport(page, 390)
    expect(page.locator('#workspace-detail')).to_be_visible()
    assert page.evaluate('document.querySelector(".place-journey-scene") === originalScene')
