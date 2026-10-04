"""Run local browser checks with an explicit network boundary.

Set MEMOIR_BROWSER_URL and MEMORY_SPARK_API_ORIGIN to task-owned origins,
then run this file with ``pytest ...`` or a browser script plus its arguments.
Existing route.fulfill mocks remain at the external boundary. Unmocked traffic
may reach only those local origins or read the public UI asset hosts below.
MEMOIR_BROWSER_PROFILE_FIXTURE=1 additionally controls private profile and
external photo lookup defaults for the standalone journeys.
"""
import json
import os
from pathlib import Path
import runpy
import sys
from urllib.parse import urlsplit
import weakref

from playwright.sync_api import APIRequestContext, Browser, Route


origins = {value.rstrip('/') for key in ('MEMOIR_BROWSER_URL', 'MEMORY_SPARK_API_ORIGIN')
           if (value := os.getenv(key))}
assert origins, 'Explicit task-owned browser/API origins are required'
public_assets = {'unpkg.com', 'cdn.jsdelivr.net', 'cesium.com',
                 'fonts.googleapis.com', 'fonts.gstatic.com'}
contexts = weakref.WeakSet()
blocked = []
offline_profile = os.getenv('MEMOIR_BROWSER_PROFILE_FIXTURE') == '1'


def allowed(url, method='GET'):
    parsed = urlsplit(url)
    if parsed.scheme in ('about', 'blob', 'data'):
        return True
    origin = f'{parsed.scheme}://{parsed.netloc}'
    if origin in origins:
        return True
    return parsed.scheme == 'https' and parsed.hostname in public_assets and method in ('GET', 'HEAD')


def reject(url, method):
    parsed = urlsplit(url)
    # Never record query strings, headers or bodies.
    blocked.append({'origin': f'{parsed.scheme}://{parsed.netloc}',
                    'path': parsed.path, 'method': method})


def install(context):
    if context in contexts:
        return
    contexts.add(context)
    profile = {}
    def guard(route):
        request = route.request
        if allowed(request.url, request.method):
            if offline_profile and urlsplit(request.url).path.endswith('/place-photos') and request.method == 'GET':
                # Standalone journeys control external research. A scenario's
                # own page/context route takes precedence over this default.
                return route.fulfill(json={'items': [], 'status': 'NO_MATCH', 'searching': False})
            if offline_profile and urlsplit(request.url).path in (
                '/api/v1/memoir/agent/profile', '/api/v1/memoir/user/profile'):
                if request.method == 'PATCH':
                    profile.update(request.post_data_json)
                return route.fulfill(json=profile)
            route.continue_()
        else:
            reject(request.url, request.method)
            route.abort('blockedbyclient')
    context.route('**/*', guard)


new_context = Browser.new_context
new_page = Browser.new_page
route_fetch = Route.fetch
route_continue = Route.continue_
request_fetch = APIRequestContext.fetch


def guarded_context(browser, *args, **kwargs):
    context = new_context(browser, *args, **kwargs)
    install(context)
    return context


def guarded_page(browser, *args, **kwargs):
    page = new_page(browser, *args, **kwargs)
    install(page.context)
    return page


def guarded_route(operation, route, *args, **kwargs):
    url = kwargs.get('url') or route.request.url
    method = kwargs.get('method') or route.request.method
    if not allowed(url, method):
        reject(url, method)
        raise RuntimeError('Browser network guard rejected an unapproved destination')
    if operation is route_fetch:
        kwargs['max_redirects'] = 0
    return operation(route, *args, **kwargs)


def guarded_request(request, url_or_request, **kwargs):
    url = url_or_request if isinstance(url_or_request, str) else url_or_request.url
    method = kwargs.get('method') or getattr(url_or_request, 'method', 'GET')
    if not allowed(url, method):
        reject(url, method)
        raise RuntimeError('Browser API request guard rejected an unapproved destination')
    kwargs['max_redirects'] = 0
    return request_fetch(request, url_or_request, **kwargs)


def guarded_request_method(operation, method):
    def call(request, url, **kwargs):
        if not allowed(url, method):
            reject(url, method)
            raise RuntimeError('Browser API request guard rejected an unapproved destination')
        kwargs['max_redirects'] = 0
        return operation(request, url, **kwargs)
    return call


Browser.new_context = guarded_context
Browser.new_page = guarded_page
Route.fetch = lambda route, *args, **kwargs: guarded_route(route_fetch, route, *args, **kwargs)
Route.continue_ = lambda route, *args, **kwargs: guarded_route(route_continue, route, *args, **kwargs)
APIRequestContext.fetch = guarded_request
for verb in ('get', 'post', 'put', 'patch', 'delete', 'head'):
    setattr(APIRequestContext, verb, guarded_request_method(getattr(APIRequestContext, verb), verb.upper()))


if __name__ == '__main__':
    output = Path(__file__).resolve().parents[2] / 'output/mac-validation'
    output.mkdir(parents=True, exist_ok=True)
    result = 0
    try:
        if sys.argv[1] == 'pytest':
            import pytest
            result = pytest.main(sys.argv[2:])
        elif sys.argv[1] == '--check':
            from playwright.sync_api import sync_playwright
            assert all(not allowed('http://127.0.0.1:8000/api/v1/memoir/projects', method)
                       for method in ('GET', 'POST', 'PATCH', 'DELETE'))
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page()
                page.goto('about:blank')
                page.evaluate("fetch('https://blocked.test/task-guard-canary').catch(() => null)")
                browser.close()
            assert blocked == [{'origin':'https://blocked.test',
                                'path':'/task-guard-canary','method':'GET'}], blocked
            print('PASS: unapproved network request aborted; shared API origin rejected for every method')
        else:
            sys.argv = sys.argv[1:]
            sys.path.insert(0, str(Path(sys.argv[0]).resolve().parent))
            runpy.run_path(sys.argv[0], run_name='__main__')
    finally:
        (output / (os.getenv('MEMOIR_NETWORK_RECEIPT', 'browser-network-guard') + '.json')).write_text(
            json.dumps({'allowed_origins': sorted(origins), 'public_read_asset_hosts': sorted(public_assets),
                        'synthetic_profile_fixture': offline_profile,
                        'synthetic_photo_lookup_fixture': offline_profile,
                        'blocked': blocked}, indent=2) + '\n')
    sys.exit(result)
