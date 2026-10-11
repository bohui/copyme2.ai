"""Real Next/Supabase-client contract. Only remote Auth/PostgREST is a fixture."""
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from urllib.parse import urljoin
import socket
import subprocess
import threading
import time

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.getenv('MEMOIR_LOCALE_HTTP') != '1', reason='Requires isolated Next/Auth HTTP fixture; enable MEMOIR_LOCALE_HTTP=1')

def b64(value):
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip('=')

def session_cookie(owner='a', expired=False):
    expiry = int(time.time()) + (-100 if expired else 3600)
    token = f'{b64({"alg":"HS256"})}.{b64({"sub":owner,"exp":expiry,"role":"authenticated"})}.fixture'
    user = {'id':owner, 'aud':'authenticated', 'user_metadata':{'ui_locale':'zh-CN'}, 'is_anonymous':False}
    return {'sb-127-auth-token':'base64-' + b64({'access_token':token,'refresh_token':owner,'expires_at':expiry,'expires_in':3600,'token_type':'bearer','user':user})}

def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

@pytest.fixture(scope='module')
def locale_server(tmp_path_factory):
    if not (ROOT/'apps/web/node_modules/next').is_dir(): pytest.skip('Requires installed Next frontend dependencies')
    preferences = {'a': {'locale':'zh-CN','source':'manual','revision':2}, 'b': {'locale':'en-AU','source':'manual','revision':2}}
    class Auth(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_OPTIONS(self):
            self.send_response(200); self.send_header('Access-Control-Allow-Origin','*'); self.send_header('Access-Control-Allow-Headers','authorization, apikey, content-type, x-client-info, x-supabase-api-version'); self.send_header('Access-Control-Allow-Methods','GET, POST, PUT, OPTIONS'); self.end_headers()
        def do_GET(self): self.respond()
        def do_POST(self): self.respond()
        def respond(self):
            token=self.headers.get('Authorization','').removeprefix('Bearer ')
            try: owner=json.loads(base64.urlsafe_b64decode(token.split('.')[1]+'==='))['sub']
            except Exception: owner=None
            if self.path.startswith('/auth/v1/token'):
                args=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
                valid = args.get('refresh_token') in ('a','b') or (args.get('auth_code')=='fixture-code' and args.get('code_verifier')=='fixture-verifier')
                if not valid:
                    self.send_response(400); self.end_headers(); self.wfile.write(b'{"message":"invalid session","error_code":"refresh_token_not_found"}'); return
                encoded=session_cookie(args.get('refresh_token','a'))['sb-127-auth-token'].removeprefix('base64-')
                body=json.loads(base64.urlsafe_b64decode(encoded+'==='))
            elif self.path.endswith('/agent/config'):
                body={'supabase_url':f'http://127.0.0.1:{self.server.server_port}','supabase_publishable_key':'fixture-public'}
            elif self.path.startswith('/api/v1/memoir/'):
                body={}
            elif self.path.startswith('/auth/v1/user') and owner in ('a','b','mismatch'):
                body={'id':owner,'aud':'authenticated','user_metadata':{'ui_locale':'zh-CN'} if owner=='mismatch' else {},'is_anonymous':False}
            elif self.path == '/rest/v1/rpc/read_ui_locale_preference' and owner=='mismatch':
                self.send_response(403); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(b'{"code":"42501","message":"Actor changed"}'); return
            elif self.path == '/rest/v1/rpc/read_ui_locale_preference' and owner in ('a','b'):
                body=preferences[owner]
            elif self.path == '/rest/v1/rpc/set_ui_locale_preference' and owner in ('a','b'):
                args=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
                if args['p_source']=='manual': preferences[owner]={'locale':args['p_locale'],'source':'manual','revision':preferences[owner]['revision']+1}
                body=preferences[owner]
            else:
                self.send_response(401); self.end_headers(); self.wfile.write(b'{"message":"invalid session"}'); return
            self.send_response(200); self.send_header('Access-Control-Allow-Origin','*'); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(json.dumps(body).encode())
    auth=ThreadingHTTPServer(('127.0.0.1',0),Auth)
    threading.Thread(target=auth.serve_forever,daemon=True).start()
    port=free_port(); log=(tmp_path_factory.mktemp('locale-http')/'next.log').open('w+')
    env={**os.environ,'SUPABASE_URL':f'http://127.0.0.1:{auth.server_port}','SUPABASE_PUBLISHABLE_KEY':'fixture-public','MEMORY_SPARK_API_ORIGIN':f'http://127.0.0.1:{auth.server_port}','NEXT_TELEMETRY_DISABLED':'1'}
    process=subprocess.Popen(['npm','run',os.getenv('MEMOIR_LOCALE_NEXT_MODE','dev'),'--','--hostname','127.0.0.1','--port',str(port)],cwd=ROOT/'apps/web',env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    base=f'http://127.0.0.1:{port}'
    try:
        for _ in range(100):
            if process.poll() is not None:
                log.seek(0); pytest.fail(log.read())
            try:
                if httpx.get(base+'/memoir',timeout=2,trust_env=False).status_code==200: break
            except httpx.HTTPError: pass
            time.sleep(.3)
        else:
            log.seek(0); pytest.fail(log.read())
        yield base
    finally:
        import signal
        os.killpg(process.pid,signal.SIGTERM); process.wait(timeout=15)
        auth.shutdown(); auth.server_close(); log.close()

def test_verified_account_precedes_stale_explicit_device_cookie(locale_server):
    cookies={**session_cookie(),'copyme2_ui_locale':'en-AU','copyme2_ui_locale_source':'fixed'}
    response=httpx.get(locale_server+'/memoir?account-locale=1',cookies=cookies,headers={'Accept-Language':'en-AU'},trust_env=False)
    assert response.status_code==200
    assert '<html lang="zh-CN"' in response.text
    # Next development replaces Cache-Control; production is checked separately.
    assert 'no-cache' in response.headers['cache-control'] or 'no-store' in response.headers['cache-control']
    if os.getenv('MEMOIR_LOCALE_NEXT_MODE') == 'start':
        assert 'private' in response.headers['cache-control'] and 'no-store' in response.headers['cache-control']
    assert 'refresh_token' not in response.text

def test_account_responses_are_isolated_and_invalid_identity_cannot_select_locale(locale_server):
    for owner,expected in [('a','zh-CN'),('b','en-AU'),('a','zh-CN'),('forged','en-AU')]:
        response=httpx.get(locale_server+'/memoir',cookies=session_cookie(owner),headers={'Accept-Language':'en-AU'},trust_env=False)
        assert response.status_code==200
        assert f'<html lang="{expected}"' in response.text

def test_legacy_fixed_locale_has_no_proven_explicit_intent(locale_server):
    response=httpx.get(locale_server+'/memoir',cookies={'copyme2_ui_locale':'zh-CN','copyme2_ui_locale_source':'fixed'},headers={'Accept-Language':'en-AU'},trust_env=False)
    assert '<html lang="en-AU"' in response.text


@pytest.mark.skipif(os.getenv('MEMOIR_LOCALE_BROWSER') != '1', reason='Requires runnable Chromium; enable MEMOIR_LOCALE_BROWSER=1')
def test_rendered_selector_persists_account_then_reload_and_other_viewer(locale_server):
    from playwright.sync_api import sync_playwright, expect
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=os.getenv('PLAYWRIGHT_CHROMIUM_EXECUTABLE','/usr/bin/chromium'),args=['--no-sandbox'])
        context=browser.new_context(locale='en-AU')
        context.route('https://**/*',lambda route:route.abort())
        context.add_cookies([{'name':name,'value':value,'url':locale_server} for name,value in session_cookie().items()])
        page=context.new_page()
        response=page.goto(locale_server+'/memoir?keep=1',wait_until='networkidle')
        assert '<html lang="zh-CN"' in response.text()
        expect(page.get_by_role('combobox',name='语言')).to_have_value('zh-CN')
        page.get_by_role('combobox',name='语言').select_option('en-AU')
        expect(page.locator('html')).to_have_attribute('lang','en-AU')
        page.reload(wait_until='networkidle')
        expect(page.get_by_role('combobox',name='Language')).to_have_value('en-AU')
        assert page.url==locale_server+'/memoir?keep=1'
        # A durable account selection wins even an otherwise valid stale cache.
        page.get_by_role('combobox',name='Language').select_option('zh-CN')
        expect(page.locator('html')).to_have_attribute('lang','zh-CN')
        context.add_cookies([{'name':name,'value':value,'url':locale_server} for name,value in session_cookie('b').items()])
        response=page.reload(wait_until='networkidle')
        assert '<html lang="en-AU"' in response.text()
        expect(page.locator('html')).to_have_attribute('lang','en-AU')
        browser.close()


def test_expired_session_is_refreshed_before_account_html(locale_server):
    response=httpx.get(locale_server+'/memoir',cookies=session_cookie('a',expired=True),headers={'Accept-Language':'en-AU'},trust_env=False)
    assert response.status_code==200
    assert '<html lang="zh-CN"' in response.text
    assert 'sb-127-auth-token=' in response.headers.get('set-cookie','')
    assert 'httponly' not in response.headers.get('set-cookie','').lower()  # official browser-coordinated SSR store
    if os.getenv('MEMOIR_LOCALE_NEXT_MODE')=='start':
        assert 'secure' in response.headers['set-cookie'].lower()
        assert 'private' in response.headers['cache-control'] and 'no-store' in response.headers['cache-control']

def test_rejected_expired_session_never_uses_unverified_account_metadata(locale_server):
    response=httpx.get(locale_server+'/memoir',cookies=session_cookie('forged',expired=True),headers={'Accept-Language':'en-AU'},trust_env=False)
    assert response.status_code==200
    assert '<html lang="en-AU"' in response.text

def test_pkce_callback_uses_existing_path_strips_code_and_never_open_redirects(locale_server):
    cookies={'sb-127-auth-token-code-verifier':'base64-'+b64('fixture-verifier')}
    response=httpx.get(locale_server+'/memoir/start?code=fixture-code&keep=1&next=https://attacker.invalid',cookies=cookies,trust_env=False)
    assert response.status_code==307
    assert urljoin(locale_server,response.headers['location'])==locale_server+'/memoir/start?keep=1&next=https%3A%2F%2Fattacker.invalid'
    assert 'sb-127-auth-token=' in response.headers.get('set-cookie','')
    assert 'private' in response.headers['cache-control'] and 'no-store' in response.headers['cache-control']

def test_code_without_pkce_verifier_does_not_create_session(locale_server):
    response=httpx.get(locale_server+'/memoir/start?code=fixture-code',trust_env=False)
    assert response.status_code==307
    assert urljoin(locale_server,response.headers['location'])==locale_server+'/memoir/start'
    assert not any('sb-127-auth-token=' in header and 'Max-Age=0' not in header for header in response.headers.get_list('set-cookie'))


def test_expected_viewer_mismatch_never_uses_legacy_account_metadata(locale_server):
    response=httpx.get(locale_server+'/memoir',cookies=session_cookie('mismatch'),headers={'Accept-Language':'en-AU'},trust_env=False)
    assert response.status_code==200
    assert '<html lang="en-AU"' in response.text
