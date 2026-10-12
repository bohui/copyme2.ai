"""Execute the auth init script against explicit document-origin boundaries."""
import json
import subprocess
from types import SimpleNamespace

import pytest

from browser_supabase_fixture import install_supabase_fixture


def run_seed(protocol, origin, *, denied=False):
    scripts = []
    install_supabase_fixture(SimpleNamespace(add_init_script=scripts.append, route=lambda *args: None), """
      window.supabase={createClient:()=>({auth:{getSession:async()=>({data:{session:{
        access_token:'synthetic-session',user:{id:'synthetic-owner'}
      }}})}})};
    """)
    program = r'''
      const vm = require('node:vm');
      const input = JSON.parse(process.argv[1]);
      const failures = []; let reads = 0; let writes = 0;
      process.on('unhandledRejection', error => failures.push(String(error.message)));
      const cookies = new Map([['copyme2_ui_locale', 'zh-CN']]);
      const document = {};
      Object.defineProperty(document, 'cookie', {
        get() { reads++; if(input.denied) throw new Error('HTTP cookie access denied');
          return [...cookies].map(([key,value])=>key+'='+value).join('; '); },
        set(value) { writes++; if(input.denied) throw new Error('HTTP cookie access denied');
          const pair=value.split(';')[0], split=pair.indexOf('='); cookies.set(pair.slice(0,split),pair.slice(split+1)); },
      });
      const context=vm.createContext({document,location:{protocol:input.protocol},origin:input.origin,
        btoa:value=>Buffer.from(value,'binary').toString('base64'),setTimeout});
      context.window=context;
      vm.runInContext(input.script,context);
      setImmediate(()=>process.stdout.write(JSON.stringify({cookies:Object.fromEntries(cookies),reads,writes,failures})));
    '''
    result = subprocess.run(['node', '-e', program, json.dumps({'script': scripts[0],
        'protocol': protocol, 'origin': origin, 'denied': denied})], check=True,
        text=True, capture_output=True)
    return json.loads(result.stdout)


@pytest.mark.parametrize('protocol,origin', [
    ('about:', 'null'), ('data:', 'null'), ('https:', 'null'),
    # An inherited-origin about:blank still isn't an HTTP fixture document.
    ('about:', 'https://fixture.test'),
])
def test_non_http_or_opaque_documents_never_touch_auth_cookies(protocol, origin):
    result = run_seed(protocol, origin, denied=True)
    assert result['reads'] == result['writes'] == 0
    assert result['failures'] == []


@pytest.mark.parametrize('protocol,origin', [
    ('http:', 'http://127.0.0.1:3139'), ('https:', 'https://fixture.test'),
])
def test_http_documents_seed_real_sdk_session_and_locale_cookies(protocol, origin):
    result = run_seed(protocol, origin)
    assert result['cookies']['sb-auth-auth-token'].startswith('base64-')
    assert 'copyme2_ui_preference_v1' in result['cookies']
    assert result['failures'] == []


def test_actual_http_cookie_failures_are_not_swallowed():
    result = run_seed('http:', 'http://127.0.0.1:3139', denied=True)
    assert result['writes'] == 1
    assert result['failures'] == ['HTTP cookie access denied']
