"""Fixture interaction contracts, not a substitute for the real browser run.

The unchanged JS renders snapshots against actual fixture route responses.
Controlled locators expose delayed paints and entry actions to the real Python
browser helpers; they do not change app state or invent additional UI controls.
"""
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from browser_recovery_fixture import NAVIGATION_USERS
from test_browser_recovery_routes import BASE, navigation_runtime
import test_navigation_history_browser as browser

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client_proof(navigation_runtime):
    transport, _, _ = navigation_runtime
    project = transport.request('/projects', method='POST', token='fixture-guest', payload={'mode': 'self'}).body
    family = transport.request('/projects', method='POST', token='fixture-guest', payload={'mode': 'family'}).body
    history = transport.request(f'/user/projects/{project["id"]}/history?limit=100', token='fixture-guest')
    assert history.status == 200 and history.body['items'] == []
    fixture = {'project': project, 'familyProject': family, 'history': history.body,
               'owner': NAVIGATION_USERS['guest'], 'status': history.status}
    result = subprocess.run(['node', 'tests/browser_navigation_probe.mjs'], cwd=ROOT,
                            input=json.dumps(fixture), text=True, capture_output=True, check=True, timeout=30)
    return json.loads(result.stdout)


class Locator:
    def __init__(self, page, selector):
        self.page, self.selector = page, selector

    def count(self): return int(self.page.present(self.selector))
    def get_attribute(self, name): return self.page.attribute(self.selector, name)
    def click(self): self.page.click(self.selector)
    def fill(self, value): self.page.typed = value


class Expect:
    def __init__(self, target): self.target = target

    def check(self, predicate):
        page = self.target.page if isinstance(self.target, Locator) else self.target
        if not predicate() and hasattr(page, 'settle'): page.settle()
        assert predicate(), f'Unsatisfied browser interaction: {getattr(self.target, "selector", "URL")}'

    def to_be_visible(self, **_): self.check(lambda: self.target.page.visible(self.target.selector))
    def to_be_enabled(self, **_): self.to_be_visible()
    def to_have_count(self, value, **_): self.check(lambda: self.target.count() == value)
    def to_have_url(self, url, **_): self.check(lambda: self.target.url == url)
    def to_have_attribute(self, name, value, **_): self.check(lambda: self.target.get_attribute(name) == value)


class HistoryPaint:
    def __init__(self, proof, *, expanded=False):
        self.frames, self.index = proof['snapshots'], 2 if expanded else 0
    @property
    def html(self): return self.frames[self.index]['html']
    def locator(self, selector): return Locator(self, selector)
    def get_by_text(self, text, **_): return self.locator(text)
    def present(self, selector):
        return ('id="chat-input"' in self.html if selector == '#chat-input' else
                'toggle-chat-history' in self.html if 'toggle-chat-history' in selector else selector in self.html)
    def visible(self, selector):
        return self.present(selector) and (selector != 'Synthetic private garden memory.' or
                                          'class="chat-history" hidden' not in self.html)
    def attribute(self, selector, name):
        assert 'toggle-chat-history' in selector and name == 'aria-expanded'
        return 'false' if 'aria-expanded="false"' in self.html else 'true'
    def settle(self): self.index = max(self.index, 1)
    def click(self, selector):
        assert 'toggle-chat-history' in selector and self.present(selector)
        self.index = 2


@pytest.mark.parametrize('expanded', [False, True], ids=['delayed-collapsed', 'already-expanded'])
def test_show_history_waits_for_the_restored_toggle(monkeypatch, client_proof, expanded):
    monkeypatch.setattr(browser, 'expect', Expect)
    page = HistoryPaint(client_proof, expanded=expanded)
    browser.show_history(page)
    assert page.index == 2


class EntryPage:
    def __init__(self, proof):
        self.proof, self.stack, self.position = proof, [BASE + proof['stack'][0]], 0
        self.typed = ''
    @property
    def url(self): return self.stack[self.position]
    def add_init_script(self, _): pass
    def evaluate(self, _): pass
    def goto(self, url):
        self.stack = self.stack[:self.position + 1] + [url]
        self.position += 1
    def go_back(self): self.position -= 1
    def go_forward(self): self.position += 1
    def locator(self, selector): return Locator(self, selector)
    def get_by_text(self, text, **_): return self.locator(text)
    def present(self, selector):
        path = self.url.removeprefix(BASE)
        if selector == '.platform-landing': return path == '/'
        if selector == '[data-action="open-memoir"]': return path == '/'
        if 'start-story' in selector:
            return path == '/memoir' and any(b.get('mode') in selector for b in self.proof['memoir'] if b.get('mode'))
        if selector == 'Synthetic private garden memory.': return path == self.proof['stack'][0]
        if selector in ('.story-topbar .brand-mark', '#chat-input', '#chat-form button[type="submit"]'):
            return path.startswith('/memoir/interview/')
        if selector in ('Synthetic partial reply.', 'An interrupted synthetic memory.'):
            return path == self.proof['stack'][0] and self.typed == 'An interrupted synthetic memory.'
        raise AssertionError(f'Unexpected interaction selector: {selector}')
    visible = present
    def click(self, selector):
        assert self.present(selector), f'No actual entry control: {selector} at {self.url}'
        if selector == '.story-topbar .brand-mark': self.goto(BASE + '/')
        elif selector == '[data-action="open-memoir"]':
            assert self.proof['beginMode'] == 'self'
            self.goto(BASE + self.proof['stack'][0])
        elif 'start-story' in selector:
            assert 'family' in selector and self.proof['familyMode'] == 'family'
            self.stack[self.position] = BASE + self.proof['stack'][2]


@pytest.mark.parametrize('scenario', ['anonymous', 'account', 'interrupted', 'family'])
def test_navigation_scenarios_use_available_entry_controls(monkeypatch, client_proof, scenario):
    page = EntryPage(client_proof)
    project_count = 2 if scenario == 'family' else 1
    owner = NAVIGATION_USERS['other' if scenario == 'account' else 'guest']
    projects = {str(index): {'owner_id': owner} for index in range(project_count)}
    values = (page, None, SimpleNamespace(projects=projects), [('POST', '/projects', 201)], 'phone', None)
    monkeypatch.setattr(browser, 'expect', Expect)
    monkeypatch.setattr(browser, 'start_conversation', lambda _: BASE + client_proof['stack'][0])
    monkeypatch.setattr(browser, 'show_history', lambda p: None)
    if scenario in ('anonymous', 'account'):
        browser.test_reentry_resumes_the_same_conversation(values, 'guest' if scenario == 'anonymous' else 'other')
    elif scenario == 'interrupted':
        browser.test_leaving_during_a_reply_preserves_the_user_turn_and_partial_reply(values)
    else:
        browser.test_back_forward_restores_the_project_named_by_the_url(values)
        assert page.stack == [BASE + path for path in client_proof['stack']]


class GreetingPaint:
    def __init__(self, proof): self.frames, self.index = proof['startup'], 0
    def locator(self, selector): return Locator(self, selector)
    def present(self, selector):
        if selector == '#chat-form button[type="submit"]': return True
        assert selector == '#chat-history .assistant-message:not(.message-streaming)'
        return not self.frames[self.index]['streaming']
    visible = present
    def settle(self): self.index = len(self.frames) - 1
    def evaluate(self, expression, args):
        assert args[0] == NAVIGATION_USERS['guest'] and args[1] == 'project-b'
        assert 'localStorage.getItem' in expression
        return self.frames[self.index]['cache']


def test_cache_baseline_waits_for_normal_greeting_to_finish(monkeypatch, client_proof):
    assert client_proof['cacheBefore'] is None and client_proof['startup'][0]['cache'] == '[]'
    monkeypatch.setattr(browser, 'expect', Expect)
    page = GreetingPaint(client_proof)
    saved = browser.settled_history_cache(page, 'project-b')
    assert page.index == len(page.frames) - 1
    assert [item['text'] for item in json.loads(saved)] == ['Welcome back to B.']


@pytest.mark.parametrize('cache', [None, '[]', '[{"role":"user","text":"A private memory"}]'])
def test_cache_baseline_rejects_unsettled_or_cross_project_content(monkeypatch, client_proof, cache):
    monkeypatch.setattr(browser, 'expect', Expect)
    page = GreetingPaint(client_proof)
    page.frames[-1]['cache'] = cache
    with pytest.raises(AssertionError):
        browser.settled_history_cache(page, 'project-b')


def run_auth_probe(payload):
    result = subprocess.run(['node', 'tests/browser_navigation_auth_probe.mjs'], cwd=ROOT,
                            input=json.dumps(payload), text=True, capture_output=True, check=True, timeout=30)
    return json.loads(result.stdout)


@pytest.mark.parametrize('principal', ['guest', 'other'], ids=['anonymous', 'account'])
@pytest.mark.parametrize('order', ['context-first', 'page-first'])
def test_initial_principal_cookie_and_auth_route_agree_in_either_script_order(monkeypatch, principal, order):
    from test_browser_recovery_routes import BrowserTransport, Route, replace_playwright

    class AuthTransport(BrowserTransport):
        def __init__(self): super().__init__(); self.scripts = []
        def add_init_script(self, script): self.scripts.append(script)

    class BeforeInitialNavigation(Exception): pass

    def stop_before_navigation(_page): raise BeforeInitialNavigation

    transport = AuthTransport()
    replace_playwright(monkeypatch, browser, transport)
    request = SimpleNamespace(param=(390, 844), node=SimpleNamespace(
        callspec=SimpleNamespace(id='phone', params={'principal': principal})))
    fixture = browser.navigation_browser.__wrapped__(monkeypatch, request)
    values = next(fixture)
    try:
        monkeypatch.setattr(browser, 'start_conversation', stop_before_navigation)
        with pytest.raises(BeforeInitialNavigation):
            browser.test_reentry_resumes_the_same_conversation(values, principal)
        # Before the fix, these were two independently ordered context/page
        # scripts. Both allowed orders must now yield the intended SDK principal.
        payload = {'scripts': transport.scripts, 'order': order, 'phase': 'seed'}
        seeded = run_auth_probe(payload)
        current, cookie = seeded['current'], seeded['cookie']

        def auth_request(path, token, arguments):
            route = Route('', method='POST', token=token, payload=arguments)
            route.request.url = 'https://auth.test' + path
            route.request.post_data_json = arguments

            def current_session(expression):
                assert expression == 'async () => (await window.supabase.createClient().auth.getSession()).data.session'
                return current

            route.request.frame = SimpleNamespace(evaluate=current_session)
            transport.handlers['https://auth.test/**'](route)
            return {'status': route.status, 'body': route.body, 'arguments': arguments}

        responses = {}
        for rpc, arguments in [
            ('read_ui_locale_preference', {'p_expected_viewer': cookie['user']['id']}),
            ('set_ui_locale_preference', {'p_locale': 'zh-CN', 'p_source': 'manual',
                                          'p_expected_viewer': cookie['user']['id']}),
        ]:
            path = '/rest/v1/rpc/' + rpc
            key = json.dumps([path, 'POST', 'Bearer ' + cookie['access_token']], separators=(',', ':'))
            responses[key] = auth_request(path, cookie['access_token'], arguments)
        payload.update(phase='boot', responses=responses, config=transport.request('/agent/config').body)
        result = run_auth_probe(payload)
        assert 'data-action="start-story" data-mode="self"' in result['html'], result['html']
        assert current['user']['id'] == cookie['user']['id'] == result['clientUser']['id'] == NAVIGATION_USERS[principal]
        assert current['user']['is_anonymous'] == (principal == 'guest')
        assert all(response['status'] == 200 for response in responses.values())
        wrong_token = 'fixture-other' if principal == 'guest' else 'fixture-guest'
        denied = auth_request('/rest/v1/rpc/read_ui_locale_preference', wrong_token,
                              {'p_expected_viewer': NAVIGATION_USERS[principal]})
        assert denied['status'] == 401 and denied['body'] == {'message': 'Invalid synthetic session'}
        wrong_owner = NAVIGATION_USERS['other' if principal == 'guest' else 'guest']
        denied = auth_request('/rest/v1/rpc/read_ui_locale_preference', current['access_token'],
                              {'p_expected_viewer': wrong_owner})
        assert denied['status'] == 403 and denied['body']['code'] == '42501'
        switched_principal = 'other' if principal == 'guest' else 'guest'
        switched = run_auth_probe({**payload, 'phase': 'seed', 'switchPrincipal': switched_principal})
        assert switched['current']['user']['id'] == switched['cookie']['user']['id'] == NAVIGATION_USERS[switched_principal]
        assert switched['current']['user']['is_anonymous'] == (switched_principal == 'guest')
    finally:
        with pytest.raises(StopIteration): next(fixture)


def test_initial_navigation_principal_must_be_explicitly_known(monkeypatch):
    request = SimpleNamespace(param=(390, 844), node=SimpleNamespace(
        callspec=SimpleNamespace(id='phone', params={'principal': 'unknown'})))
    fixture = browser.navigation_browser.__wrapped__(monkeypatch, request)
    with pytest.raises(AssertionError, match='Unsupported navigation fixture principal'):
        next(fixture)
