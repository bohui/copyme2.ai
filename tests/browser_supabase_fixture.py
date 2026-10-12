"""Remote Auth/PostgREST seam for the bundled SSR SDK (synthetic data only).

Legacy browser scenarios keep their small declarative account/session scripts as
fixture data. Those scripts no longer replace the application's SDK: this adapter
seeds a session cookie and serves the network boundary the real SDK consumes.
The newer account SSR test instead runs a real HTTP Auth fixture visible to Next.
"""
import json
from urllib.parse import urlparse, parse_qs


def install_supabase_fixture(target, session_script):
    preferences = {}
    target.add_init_script(session_script + r'''
      (() => {
        const fixture = window.supabase;
        if (!fixture?.createClient) return;
        // Playwright also injects into blank and sandboxed opaque documents.
        // Only HTTP(S) documents with a real security origin can own our cookies.
        // Do not catch cookie exceptions on eligible documents: those are failures.
        const canSeedDocument = () => ['http:', 'https:'].includes(location.protocol) && window.origin !== 'null';
        const seed = async () => {
          if (!canSeedDocument()) return;
          const {data} = await fixture.createClient().auth.getSession();
          if (!data?.session || !canSeedDocument()) return;
          const session = {...data.session, refresh_token:data.session.refresh_token || 'fixture-refresh',
            expires_at:Math.floor(Date.now()/1000)+3600, expires_in:3600, token_type:'bearer'};
          const encode = value => btoa(unescape(encodeURIComponent(JSON.stringify(value)))).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
          document.cookie = 'sb-auth-auth-token=base64-'+encode(session)+'; Path=/; SameSite=Lax';
          const legacy = document.cookie.split('; ').find(c=>c.startsWith('copyme2_ui_locale='));
          if (legacy && !document.cookie.includes('copyme2_ui_preference_v1=')) {
            const locale=decodeURIComponent(legacy.split('=')[1]);
            document.cookie='copyme2_ui_preference_v1='+encodeURIComponent(JSON.stringify({version:1,locale,source:'manual',viewer:null}))+'; Path=/; SameSite=Lax';
          }
        };
        seed();
        // These existing scenarios model a provider principal replacement. A
        // fresh navigation consumes the new cookie through the real SDK.
        for (const name of ['fixtureSetPrincipal','fixturePrincipal']) {
          const original=window[name];
          if(original) window[name]=async id=>{original(id);await seed();setTimeout(()=>location.reload(),0);};
        }
      })();
    ''')

    def auth(route):
        url=urlparse(route.request.url)
        headers={'Access-Control-Allow-Origin':'*', 'Access-Control-Allow-Headers':'authorization,apikey,content-type,x-client-info,x-supabase-api-version'}
        if route.request.method=='OPTIONS':
            route.fulfill(status=200,headers=headers,body=''); return
        if url.path.endswith('/authorize'):
            query=parse_qs(url.query)
            payload={'provider':query.get('provider',[None])[0], 'options':{'redirectTo':query.get('redirect_to',[None])[0]}}
            route.fulfill(content_type='text/html',body='<script>window.fixtureOauth='+json.dumps(payload)+'</script>'); return
        session=route.request.frame.evaluate('async () => (await window.supabase.createClient().auth.getSession()).data.session')
        user=session['user']; owner=user['id']
        if route.request.headers.get('authorization') != 'Bearer '+session['access_token']:
            route.fulfill(status=401,headers=headers,json={'message':'Invalid synthetic session'}); return
        if url.path.endswith('/user'):
            route.fulfill(headers=headers,json=user); return
        args=route.request.post_data_json or {}
        if args.get('p_expected_viewer') != owner:
            route.fulfill(status=403,headers=headers,json={'code':'42501','message':'Actor changed'}); return
        legacy=user.get('user_metadata',{}).get('ui_locale')
        current=preferences.get(owner) or ({'locale':legacy,'source':'manual','revision':0} if legacy in ('en-AU','zh-CN') else None)
        if url.path.endswith('/set_ui_locale_preference'):
            if not current or args['p_source']=='manual':
                current={'locale':args['p_locale'],'source':args['p_source'],'revision':(current or {}).get('revision',0)+1}
                preferences[owner]=current
        elif not url.path.endswith('/read_ui_locale_preference'):
            route.fulfill(status=404,headers=headers,json={'message':'Unknown synthetic endpoint'}); return
        route.fulfill(headers=headers,json=current)

    target.route('https://auth.test/**',auth)
