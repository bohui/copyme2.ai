"""Browser contract check with synthetic collection responses; no LLM or private memories."""
import argparse
from contextlib import contextmanager, ExitStack
from copy import deepcopy
import json
import re
import traceback
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright


COLLECTION_PROJECT = 'collection-fixture'


def install_collection_startup(page, locale):
    """Exact API boundaries used by Begin my story; unexpected calls fail closed.

    Keep the real client navigation, consent and background hydration flows.
    Collection/task routes are installed later and take Playwright precedence.
    """
    state = {'created': 0, 'consents': [], 'requests': [], 'unexpected': [],
             'request_details': [], 'failed_requests': [], 'browser_errors': []}
    profile = {'preferred_language': locale,
               'conversation_language': {'locale': locale, 'source': 'explicit', 'revision': 1}}
    project = {'id': COLLECTION_PROJECT, 'revision': 1, 'policy_epoch': 1,
        'mode': 'self', 'profile': profile, 'requires_supabase_auth': True,
        'owner_id': 'fixture-owner', 'storyteller_id': 'fixture-owner', 'home_region': 'au',
        'consent': {}, 'preferences': {'default_visibility': 'private'}, 'member_count': 1,
        'composition_stage': 0, 'workspace_unlocked': False, 'preview': None,
        'deletion_state': 'ACTIVE', 'created_at': '2026-10-12T00:00:00Z'}

    def startup(route):
        request = route.request
        parsed = urlparse(request.url)
        path = parsed.path.removeprefix('/api/v1/memoir')
        query = parse_qs(parsed.query)
        state['requests'].append((request.method, path))
        body = None
        status = 200
        if request.method == 'GET':
            if path == '/agent/config':
                body = {'auth_mode': 'test'}
            elif path in ('/agent/profile', '/user/profile'):
                body = profile
            elif path == '/projects/' + COLLECTION_PROJECT:
                body = project
            elif path == '/projects/' + COLLECTION_PROJECT + '/journey':
                body = {**project, 'active_session': None, 'memory_ids': [], 'next_action': 'start_memory'}
            elif path == '/story/state':
                body = {'family_features_enabled': False, 'payment_status': 'paid', 'payment_features': [],
                    'recall_status': {'rounds_completed': 0, 'free_rounds': 20, 'paid': True, 'payment_required': False}}
            elif path == '/story/readiness' and query == {'project_id': [COLLECTION_PROJECT]}:
                body = {'stages': {}}
            elif path == '/story/private-draft' and query == {'project_id': [COLLECTION_PROJECT], 'language': [locale]}:
                body = {'status': 'collecting', 'preview': None, 'updating': False, 'revision': 0}
        elif request.method == 'POST':
            payload = request.post_data_json
            if path == '/projects' and payload in ({'mode': 'self'}, {'mode': 'self', 'language': locale}):
                state['created'] += 1
                body, status = project, 201
            elif path == '/projects/' + COLLECTION_PROJECT + '/consents' and isinstance(payload, dict) \
                    and payload.get('purpose') in ('recording', 'storyteller_assent') \
                    and payload == {'purpose': payload['purpose'], 'granted': True, 'locale': locale}:
                state['consents'].append(payload['purpose'])
                body = {**payload, 'subject': 'fixture-owner', 'actor': 'fixture-owner',
                    'notice_version': 'notice-2026-09-21', 'timestamp': '2026-10-12T00:00:00Z', 'region': 'au', 'assistance_method': 'self'}
        if body is None:
            state['unexpected'].append((request.method, path + ('?' + parsed.query if parsed.query else '')))
            route.abort()
            return
        route.fulfill(status=status, json=body)

    def request_details(request):
        try:
            frame_url = request.frame.url
        except Exception:
            frame_url = None
        return {'method': request.method, 'url': request.url,
            'resource_type': request.resource_type, 'frame_url': frame_url}

    def record_request(request):
        if '/api/v1/memoir/' in request.url:
            state['request_details'].append(request_details(request))

    page.on('request', record_request)
    page.on('requestfailed', lambda request: state['failed_requests'].append({
        **request_details(request), 'failure': request.failure}))
    page.on('pageerror', lambda error: state['browser_errors'].append({
        'message': str(error), 'stack': getattr(error, 'stack', None)}))
    page.route('**/api/v1/memoir/**', startup)
    return state


def start_collection_story(page, locale, *, timeout=10000):
    """Observe completed setup requests, not an already-idle landing document."""
    consent_path = '/api/v1/memoir/projects/' + COLLECTION_PROJECT + '/consents'
    required = [('/api/v1/memoir/projects', 'POST', None, 201),
        (consent_path, 'POST', 'recording', 200),
        (consent_path, 'POST', 'storyteller_assent', 200),
        ('/api/v1/memoir/projects/' + COLLECTION_PROJECT + '/journey', 'GET', None, 200)]
    def matches(request, path, method, purpose):
        if request.method != method or urlparse(request.url).path != path:
            return False
        return purpose is None or request.post_data_json.get('purpose') == purpose

    # Install every event barrier before the click: fast responses cannot be
    # missed, and delayed consent remains part of the same bounded startup.
    with ExitStack() as stack:
        completed = [(stack.enter_context(page.expect_request_finished(
            lambda request, path=path, method=method, purpose=purpose: matches(request, path, method, purpose),
            timeout=timeout)), status) for path, method, purpose, status in required]
        page.get_by_role('button', name='Begin my story' if locale == 'en-AU' else '开始讲我的故事').click(timeout=timeout)
    for event, status in completed:
        response = event.value.response()
        assert response is not None and response.status == status
    expect(page).to_have_url(re.compile('/memoir/interview/' + re.escape(COLLECTION_PROJECT) + r'(?:[?#].*)?$'), timeout=timeout)
    expect(page.locator('[data-profile-trigger]')).to_be_visible(timeout=timeout)


@contextmanager
def collection_diagnostics(page, startup, output, label):
    """Persist useful evidence before re-raising the original browser failure."""
    try:
        yield
    except Exception as error:
        frozen_startup = deepcopy(startup)
        evidence = {'error': str(error), 'error_stack': traceback.format_exc(),
            'page_url': page.url, 'frames': [{'name': frame.name, 'url': frame.url} for frame in page.frames],
            'startup': frozen_startup}
        try:
            page.screenshot(path=str(output / (label + '-failure.png')), full_page=True)
        except Exception as screenshot_error:
            evidence['screenshot_error'] = str(screenshot_error)
        try:
            (output / (label + '-failure.json')).write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
        except OSError as write_error:
            evidence['artifact_error'] = str(write_error)
        print(json.dumps({'fixture_failure': label, **evidence}, ensure_ascii=False), flush=True)
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:3010')
    args = parser.parse_args()
    output = Path(__file__).resolve().parents[1] / 'output/playwright'
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for locale in ['en-AU', 'zh-CN']:
            context = browser.new_context(viewport={'width': 1280, 'height': 900}, locale=locale)
            page = context.new_page()
            page.add_init_script(f"localStorage.setItem('copyme2_ui_locale', '{locale}')")
            startup = install_collection_startup(page, locale)
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
            with collection_diagnostics(page, startup, output, f'collection-{locale}'):
                page.goto(args.base_url, wait_until='networkidle')
                start_collection_story(page, locale)
                assert startup['created'] == 1 and set(startup['consents']) == {'recording', 'storyteller_assent'}
                assert not startup['unexpected'], startup['unexpected']
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
                page.screenshot(path=str(output / f'collection-{locale}.png'), full_page=True)
                dialog.locator('[data-close]').click()
                expect(dialog).to_have_count(0)
                assert not startup['unexpected'], startup['unexpected']
                assert not startup['browser_errors'], startup['browser_errors']
                print(f'PASS {locale}: explicit confirmation, seven periods, source selection, queued result, download')
            context.close()
        browser.close()


if __name__ == '__main__':
    main()
