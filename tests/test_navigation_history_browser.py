"""Real UI and project API; synthetic auth/history, with all provider calls intercepted."""
import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import expect, sync_playwright

from apps.api import main
from apps.api.store import MemoryStore

pytestmark = pytest.mark.skipif(not os.getenv('MEMOIR_BROWSER_URL'), reason='Requires isolated source frontend')
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(params=[(390, 844), (1440, 1000)], ids=['phone', 'desktop'])
def navigation_browser(monkeypatch, request):
    def authenticated(authorization):
        if authorization not in {'Bearer fixture-guest', 'Bearer fixture-other'}:
            raise main.HTTPException(401, 'Missing synthetic session')
        service = Mock()
        service.user_id = authorization.removeprefix('Bearer fixture-')
        service.profile.return_value = {'preferred_language': 'zh-CN'}
        service.request.return_value.json.return_value = []
        return service

    monkeypatch.setattr(main, 'authenticated_storage', authenticated)
    store = MemoryStore()
    with TestClient(main.create_app(store)) as client, sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(viewport={'width': request.param[0], 'height': request.param[1]}, reduced_motion='reduce')
        base = os.environ['MEMOIR_BROWSER_URL']
        context.add_cookies([{'name': 'copyme2_ui_locale', 'value': 'zh-CN', 'url': base},
                            {'name': 'copyme2_ui_locale_source', 'value': 'fixed', 'url': base}])
        script = """const fixtureSession=()=>{const id=localStorage.getItem('fixture-principal')||'guest';return {
          access_token:'fixture-'+id,refresh_token:'fixture-refresh-'+id,user:{id,is_anonymous:id==='guest'}}};
        window.fixtureSetPrincipal=id=>{localStorage.setItem('fixture-principal',id);window.fixtureAuthChanged?.('SIGNED_IN',fixtureSession())};
        window.supabase={createClient:()=>({auth:{
          getSession:async()=>({data:{session:fixtureSession()}}),
          getUser:async()=>({data:{user:fixtureSession().user}}),
          signInWithOAuth:async options=>{window.fixtureOauth=options;return {}},
          onAuthStateChange:callback=>{window.fixtureAuthChanged=callback;return {}}
        }})};"""
        context.route('https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2',
                      lambda r: r.fulfill(content_type='text/javascript', body=script))
        requests = []

        def api(route):
            path = route.request.url.split('/api/v1/memoir')[-1]
            endpoint = path.split('?')[0]
            if endpoint == '/projects' or endpoint.startswith('/projects/'):
                response = client.request(route.request.method, '/v1' + path,
                    headers={k: v for k, v in route.request.headers.items() if k in {'authorization', 'content-type'}},
                    content=route.request.post_data or None)
                requests.append((route.request.method, endpoint, response.status_code))
                return route.fulfill(status=response.status_code, content_type='application/json', body=response.text)
            data = {}
            if endpoint == '/agent/config':
                data = {'supabase_url': 'https://auth.test', 'supabase_publishable_key': 'public', 'auth_mode': 'supabase'}
            elif endpoint in ('/user/profile', '/agent/profile'): data = {'preferred_language': 'zh-CN'}
            elif endpoint == '/story/state':
                data = {'family_features_enabled': False, 'recall_status': {'rounds_completed': 0, 'free_rounds': 200, 'paid': False, 'payment_required': False}}
            elif endpoint == '/user/conversations': data = {'items': []}
            elif endpoint == '/agent/place-journey': data = {'place_journey': None}
            elif endpoint == '/agent/turn':
                return route.fulfill(content_type='application/x-ndjson', body=json.dumps({'type': 'result', 'data': {'reply': 'Synthetic garden reply.'}}) + '\n')
            route.fulfill(content_type='application/json', body=json.dumps(data))

        context.route('**/api/v1/memoir/**', api)
        # Keep this regression hermetic: remote models, data, media and auth cannot be contacted.
        context.route('https://**', lambda r: r.abort() if 'cdn.jsdelivr.net/npm/@supabase' not in r.request.url else r.fallback())
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        yield page, context, store, requests, request.node.callspec.id, client
        assert not errors, errors
        browser.close()


def start_conversation(page):
    page.goto(os.environ['MEMOIR_BROWSER_URL'] + '/memoir')
    page.locator('[data-action="start-story"][data-mode="self"]').click()
    expect(page.locator('#chat-input')).to_be_enabled(timeout=30000)
    page.locator('#chat-input').fill('Synthetic private garden memory.')
    page.locator('#chat-form button[type="submit"]').click()
    expect(page.get_by_text('Synthetic garden reply.', exact=True)).to_be_visible(timeout=30000)
    return page.url


def show_history(page):
    expect(page.locator('#chat-input')).to_be_visible(timeout=30000)
    toggle = page.locator('[data-action="toggle-chat-history"]')
    if toggle.count() and toggle.get_attribute('aria-expanded') == 'false': toggle.click()
    expect(page.get_by_text('Synthetic private garden memory.', exact=True)).to_be_visible()


def capture(page, name):
    directory = ROOT / 'output/navigation-history'
    directory.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(directory / f'{name}.png'))


def test_logo_returns_home_and_begin_resumes_interview(navigation_browser):
    page, _, _, _, viewport, _ = navigation_browser
    interview_url = start_conversation(page)
    capture(page, f'{os.getenv("NAV_CAPTURE_PHASE", "after")}-{viewport}-interview')
    page.locator('.story-topbar .brand-mark').click()
    expect(page).to_have_url(os.environ['MEMOIR_BROWSER_URL'] + '/')
    expect(page.locator('.platform-landing')).to_be_visible()
    capture(page, f'{os.getenv("NAV_CAPTURE_PHASE", "after")}-{viewport}-logo-destination')
    page.locator('[data-action="open-memoir"]').click()
    expect(page).to_have_url(interview_url)
    expect(page.locator('#chat-input')).to_be_visible()


@pytest.mark.parametrize('provider', ['google', 'facebook'])
def test_login_returns_to_project_started_from_homepage(navigation_browser, provider):
    page, _, store, _, _, _ = navigation_browser
    page.goto(os.environ['MEMOIR_BROWSER_URL'] + '/', wait_until='networkidle')
    page.locator('[data-action="open-memoir"]').click()
    expect(page.locator('#chat-input')).to_be_enabled(timeout=30000)
    project_url = os.environ['MEMOIR_BROWSER_URL'] + '/memoir/interview/' + next(iter(store.projects))
    expect(page).to_have_url(project_url)
    page.locator('[data-profile-trigger]').click()
    page.locator('[data-profile-action="login"]').click()
    page.locator(f'[data-provider="{provider}"]').click()
    page.wait_for_function('Boolean(window.fixtureOauth)')
    assert page.evaluate('fixtureOauth.provider') == provider
    assert page.evaluate('fixtureOauth.options.redirectTo') == project_url


@pytest.mark.parametrize('principal', ['guest', 'other'], ids=['anonymous', 'account'])
def test_reentry_resumes_the_same_conversation(navigation_browser, principal):
    page, _, store, requests, _, _ = navigation_browser
    page.add_init_script(f"localStorage.setItem('fixture-principal',{json.dumps(principal)})")
    interview = start_conversation(page)
    page.locator('.story-topbar .brand-mark').click()
    page.locator('[data-action="open-memoir"]').click()
    page.locator('[data-action="start-story"][data-mode="self"]').click()
    expect(page).to_have_url(interview)
    show_history(page)
    assert len(store.projects) == 1
    assert sum(method == 'POST' and path == '/projects' for method, path, _ in requests) == 1


def test_anonymous_history_survives_reload_and_a_new_tab(navigation_browser):
    page, context, store, _, viewport, _ = navigation_browser
    interview = start_conversation(page)
    page.reload()
    show_history(page)
    second = context.new_page()
    second.goto(interview)
    show_history(second)
    page.close()
    second.reload()
    show_history(second)
    capture(second, f'after-{viewport}-recovered-new-tab')
    assert len(store.projects) == 1


def test_browser_created_anonymous_project_requires_its_verified_session(navigation_browser):
    page, _, _, _, _, client = navigation_browser
    project_id = start_conversation(page).rsplit('/', 1)[-1]
    path = '/v1/projects/' + project_id
    for headers, expected in [({}, 401), ({'X-Account-Id': 'demo-storyteller'}, 401),
                              ({'X-Account-Id': 'guest'}, 401),
                              ({'Authorization': 'Bearer fixture-other'}, 403),
                              ({'Authorization': 'Bearer fixture-other', 'X-Account-Id': 'guest'}, 403)]:
        response = client.get(path + '/journey', headers=headers)
        assert response.status_code == expected
        assert 'Synthetic private garden memory.' not in response.text
        assert client.patch(path, headers=headers, json={'profile': {'name': 'forged profile'}}).status_code == expected
    response = client.get(path, headers={'Authorization': 'Bearer fixture-guest'})
    assert response.status_code == 200
    assert response.json()['requires_supabase_auth'] is True
    assert response.json()['profile']['name'] != 'forged profile'


def test_switching_accounts_hides_private_history_and_retains_the_guests_cache(navigation_browser):
    page, _, _, _, _, _ = navigation_browser
    interview = start_conversation(page)
    page.evaluate("fixtureSetPrincipal('other')")
    expect(page.locator('.hero-actions')).to_be_visible(timeout=15000)
    expect(page.get_by_text('Synthetic private garden memory.', exact=True)).to_have_count(0)
    page.goto(os.environ['MEMOIR_BROWSER_URL'] + '/memoir')
    page.locator('[data-action="start-story"][data-mode="self"]').click()
    expect(page.locator('#chat-input')).to_be_visible()
    assert page.url != interview
    expect(page.get_by_text('Synthetic private garden memory.', exact=True)).to_have_count(0)
    page.evaluate("fixtureSetPrincipal('guest')")
    expect(page.locator('.hero-actions')).to_be_visible(timeout=15000)
    page.goto(interview)
    show_history(page)


def test_a_stale_tab_cannot_overwrite_newer_history(navigation_browser):
    page, context, _, _, _, _ = navigation_browser
    interview = start_conversation(page)
    second = context.new_page()
    second.goto(interview)
    show_history(second)
    page.locator('#chat-input').fill('A second synthetic garden memory.')
    page.locator('#chat-form button[type="submit"]').click()
    expect(page.locator('#chat-form button[type="submit"]')).to_be_enabled()
    # Toggling in the older tab renders its older snapshot and used to truncate durable history.
    second.locator('[data-action="toggle-chat-history"]').click()
    second.reload()
    show_history(second)
    expect(second.get_by_text('A second synthetic garden memory.', exact=True)).to_be_visible()


def test_back_forward_restores_the_project_named_by_the_url(navigation_browser):
    page, _, store, _, _, _ = navigation_browser
    interview = start_conversation(page)
    page.locator('.story-topbar .brand-mark').click()
    page.locator('[data-action="open-memoir"]').click()
    page.locator('[data-action="start-story"][data-mode="family"]').click()
    expect(page.locator('#chat-input')).to_be_visible()
    family_interview = page.url
    assert family_interview != interview
    page.go_back()
    expect(page.locator('.platform-landing')).to_be_visible()
    page.go_back()
    expect(page).to_have_url(interview)
    show_history(page)
    page.go_forward()
    expect(page.locator('.platform-landing')).to_be_visible()
    page.go_forward()
    expect(page).to_have_url(family_interview)
    expect(page.locator('#chat-input')).to_be_visible()
    expect(page.get_by_text('Synthetic private garden memory.', exact=True)).to_have_count(0)
    assert len(store.projects) == 2


def test_leaving_during_a_reply_preserves_the_user_turn_and_partial_reply(navigation_browser):
    page, _, store, _, _, _ = navigation_browser
    interview = start_conversation(page)
    page.evaluate("""()=>{const nativeFetch=window.fetch;window.fetch=(url,options)=>{
      if(!String(url).endsWith('/agent/turn')) return nativeFetch(url,options);
      const stream=new ReadableStream({start(controller){controller.enqueue(new TextEncoder().encode(
        JSON.stringify({type:'text_delta',text:'Synthetic partial reply.'})+'\\n'));}});
      return Promise.resolve(new Response(stream,{headers:{'Content-Type':'application/x-ndjson'}}));
    }}""")
    page.locator('#chat-input').fill('An interrupted synthetic memory.')
    page.locator('#chat-form button[type="submit"]').click()
    expect(page.get_by_text('Synthetic partial reply.', exact=True)).to_be_visible()
    page.locator('.story-topbar .brand-mark').click()
    page.locator('[data-action="open-memoir"]').click()
    page.locator('[data-action="start-story"][data-mode="self"]').click()
    expect(page).to_have_url(interview)
    show_history(page)
    expect(page.get_by_text('An interrupted synthetic memory.', exact=True)).to_be_visible()
    expect(page.get_by_text('Synthetic partial reply.', exact=True)).to_be_visible()
    assert len(store.projects) == 1


def test_unavailable_durable_storage_falls_back_to_the_tab_cache(navigation_browser):
    page, _, _, _, _, _ = navigation_browser
    page.add_init_script("""Object.defineProperty(window,'localStorage',{configurable:true,value:{
      getItem:()=>null,setItem:()=>{throw new DOMException('Storage blocked','SecurityError')},
      removeItem:()=>{throw new DOMException('Storage blocked','SecurityError')}
    }});""")
    page.goto(os.environ['MEMOIR_BROWSER_URL'] + '/memoir')
    expect(page.locator('.hero-actions')).to_be_visible(timeout=5000)
    interview = start_conversation(page)
    page.reload()
    expect(page).to_have_url(interview)
    show_history(page)


def test_memoir_name_links_to_the_landing_page_without_losing_history(navigation_browser):
    page, _, store, _, _, _ = navigation_browser
    interview = start_conversation(page)
    page.get_by_role('link', name='回忆', exact=True).click()
    expect(page).to_have_url(os.environ['MEMOIR_BROWSER_URL'] + '/memoir')
    expect(page.locator('.hero-actions')).to_be_visible()
    page.locator('[data-action="start-story"][data-mode="self"]').click()
    expect(page).to_have_url(interview)
    show_history(page)
    assert len(store.projects) == 1


def test_unverified_legacy_history_is_retained_without_a_replacement_project(navigation_browser):
    page, _, store, _, _, client = navigation_browser
    project = client.post('/v1/projects', json={'storyteller_name': 'Legacy synthetic narrator'}).json()
    history = json.dumps([{'role': 'user', 'text': 'A legacy synthetic private memory.'}])
    key = 'memory-spark-chat-history:' + project['id']
    page.add_init_script(f"localStorage.setItem('memory-spark-project',{json.dumps(project['id'])});sessionStorage.setItem({json.dumps(key)},{json.dumps(history)})")
    page.goto(os.environ['MEMOIR_BROWSER_URL'] + '/memoir/interview/' + project['id'])
    expect(page.locator('.hero-actions')).to_be_visible()
    expect(page.get_by_text('A legacy synthetic private memory.', exact=True)).to_have_count(0)
    page.locator('[data-action="start-story"][data-mode="self"]').click()
    expect(page.locator('#toast')).to_have_class('toast show')
    assert len(store.projects) == 1
    assert page.evaluate(f"sessionStorage.getItem({json.dumps(key)})") == history
    assert page.evaluate("localStorage.getItem('memory-spark-project')") == project['id']
    assert client.get('/v1/projects/' + project['id']).json()['owner_id'] == 'demo-storyteller'


@pytest.mark.parametrize('ending', ['final', 'error', 'workspace-tail'])
def test_back_forward_detaches_a_reply_and_keeps_each_projects_history(navigation_browser, ending):
    page, _, _, _, _, client = navigation_browser
    interview_a = start_conversation(page)
    project_b = client.post('/v1/projects', headers={'Authorization': 'Bearer fixture-guest'},
                            json={'mode': 'family', 'storyteller_name': 'Synthetic B'}).json()['id']
    interview_b = os.environ['MEMOIR_BROWSER_URL'] + '/memoir/interview/' + project_b
    page.evaluate("""()=>{const nativeFetch=window.fetch;window.fetch=(url,options)=>{
      if(!String(url).endsWith('/agent/turn')) return nativeFetch(url,options);
      window.fixtureStreamSignal=options.signal;
      let deliver;
      const reader={read:()=>new Promise(resolve=>{deliver=resolve}),cancel:async()=>{window.fixtureCanceled=true},releaseLock(){}};
      window.fixtureEvent=event=>deliver({done:false,value:new TextEncoder().encode(JSON.stringify(event)+'\\n')});
      return Promise.resolve({ok:true,status:200,body:{getReader:()=>reader}});
    }}""")
    page.locator('#chat-input').fill('A pending synthetic memory.')
    page.locator('#chat-form button[type="submit"]').click()
    page.wait_for_function('window.fixtureEvent !== undefined')
    page.evaluate("fixtureEvent({type:'text_delta',text:'A accepted partial reply.'})")
    expect(page.get_by_text('A accepted partial reply.', exact=True)).to_be_visible()
    if ending == 'workspace-tail':
        page.evaluate("fixtureEvent({type:'conversation_saved',data:{conversation_saved:true,reply:'A accepted partial reply.'}})")
        expect(page.locator('#chat-form button[type="submit"]')).to_be_enabled()
    # Add B once, then exercise actual Back/Forward events in this document.
    page.evaluate("url=>{history.pushState({},'',url);dispatchEvent(new PopStateEvent('popstate'))}", interview_b)
    expect(page.locator('#chat-input')).to_be_enabled()
    assert page.evaluate('fixtureStreamSignal.aborted') is True
    assert page.evaluate('fixtureCanceled') is True
    before_b = page.evaluate("id=>localStorage.getItem('memory-spark-chat-history:guest:'+id)", project_b)
    late = {'type': 'error', 'message': 'A late synthetic error'} if ending == 'error' else {
        'type': 'result', 'data': {'conversation_saved': True, 'reply': 'A late complete reply.',
                                 'composition_stage': 3, 'recall_status': {'payment_required': True}}}
    page.evaluate('event=>fixtureEvent(event)', late)
    expect(page.get_by_text('A late complete reply.', exact=True)).to_have_count(0)
    expect(page.get_by_text('A late synthetic error', exact=True)).to_have_count(0)
    expect(page.locator('#chat-input')).to_be_enabled()
    assert page.evaluate("id=>localStorage.getItem('memory-spark-chat-history:guest:'+id)", project_b) == before_b
    page.go_back()
    expect(page).to_have_url(interview_a)
    show_history(page)
    expect(page.get_by_text('A pending synthetic memory.', exact=True)).to_be_visible()
    expect(page.get_by_text('A accepted partial reply.', exact=True)).to_be_visible()
    page.go_forward()
    expect(page).to_have_url(interview_b)
    expect(page.locator('#chat-input')).to_be_enabled()
    expect(page.get_by_text('A pending synthetic memory.', exact=True)).to_have_count(0)
    page.reload()
    expect(page.locator('#chat-input')).to_be_enabled()
    expect(page.get_by_text('A accepted partial reply.', exact=True)).to_have_count(0)


def test_a_late_failed_back_recovery_cannot_clear_the_forward_project(navigation_browser):
    page, _, _, _, _, client = navigation_browser
    interview_a = start_conversation(page)
    project_a = interview_a.rsplit('/', 1)[-1]
    project_b = client.post('/v1/projects', headers={'Authorization': 'Bearer fixture-guest'},
                            json={'mode': 'family', 'storyteller_name': 'Synthetic B'}).json()['id']
    interview_b = os.environ['MEMOIR_BROWSER_URL'] + '/memoir/interview/' + project_b
    page.evaluate("url=>{history.pushState({},'',url);dispatchEvent(new PopStateEvent('popstate'))}", interview_b)
    expect(page.locator('#chat-input')).to_be_enabled()
    page.evaluate("""id=>{const nativeFetch=window.fetch;window.fetch=(url,options)=>{
      if(String(url).endsWith('/projects/'+id)&&!window.fixtureRecoveryHeld){window.fixtureRecoveryHeld=true;
        return new Promise((_resolve,reject)=>{window.fixtureRejectRecovery=()=>reject(new Error('Late recovery error'))})}
      return nativeFetch(url,options);
    }}""", project_a)
    page.go_back()
    page.wait_for_function('window.fixtureRecoveryHeld === true')
    page.go_forward()
    expect(page).to_have_url(interview_b)
    expect(page.locator('#chat-input')).to_be_enabled()
    page.evaluate('fixtureRejectRecovery()')
    expect(page.locator('#chat-input')).to_be_enabled()
    expect(page.locator('.hero-actions')).to_have_count(0)
    page.go_back()
    show_history(page)


def test_readable_durable_history_and_pointer_survive_write_quota(navigation_browser):
    page, _, _, _, _, _ = navigation_browser
    interview = start_conversation(page)
    quota = """(()=>{const save=Storage.prototype.setItem;Storage.prototype.setItem=function(key,value){
      if(this===localStorage && key.startsWith('memory-spark-')) throw new DOMException('Full','QuotaExceededError');
      return save.call(this,key,value);
    }})()"""
    page.add_init_script(quota)
    page.evaluate(quota)
    page.locator('#chat-input').fill('A newer quota fallback memory.')
    page.locator('#chat-form button[type="submit"]').click()
    expect(page.locator('#chat-form button[type="submit"]')).to_be_enabled()
    page.reload()
    show_history(page)
    expect(page.get_by_text('A newer quota fallback memory.', exact=True)).to_be_visible()
    page.get_by_role('link', name='回忆', exact=True).click()
    page.locator('[data-action="start-story"][data-mode="family"]').click()
    expect(page.locator('#chat-input')).to_be_enabled()
    newer_interview = page.url
    assert newer_interview != interview
    page.goto(os.environ['MEMOIR_BROWSER_URL'] + '/memoir/start')
    expect(page).to_have_url(newer_interview)
    expect(page.locator('#chat-input')).to_be_enabled()
    page.goto(interview)
    show_history(page)
    expect(page.get_by_text('A newer quota fallback memory.', exact=True)).to_be_visible()
