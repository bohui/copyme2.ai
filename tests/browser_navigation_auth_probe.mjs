import fs from 'node:fs';
import vm from 'node:vm';
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
import {restoreLegacyBrowserSession} from '../apps/web/auth/browser.mjs';
import {createPreferenceSession} from '../apps/web/i18n/session.mjs';
import {readPreference,preferenceCookie} from '../apps/web/i18n/preference.mjs';
// Real SDK cookie/session and RPC behavior, with external HTTP fully controlled.
const {createBrowserClient}=createRequire(new URL('../apps/web/package.json',import.meta.url))('@supabase/ssr');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const source=fs.readFileSync(new URL('../apps/web/client/memoir/client.js',import.meta.url),'utf8');
const extract=name=>source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0];
const cookies=new Map([['copyme2_ui_locale','zh-CN'],['copyme2_ui_locale_source','fixed']]);
const stored=new Map(), document={querySelectorAll:()=>[]};
Object.defineProperty(document,'cookie',{
 get(){return [...cookies].map(([k,v])=>k+'='+v).join('; ')},
 set(text){const pair=text.split(';')[0],cut=pair.indexOf('=');cookies.set(pair.slice(0,cut),pair.slice(cut+1));},
});
const app={innerHTML:''},state={chat:[],navigationGeneration:0},timers=[],calls=[];
const storage={getItem:k=>stored.get(k)??null,setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)};
const context=vm.createContext({document,location:{protocol:'http:',reload(){throw Error('Unexpected principal reload')}},origin:'http://127.0.0.1:3139',
 localStorage:storage,sessionStorage:{getItem:()=>null},btoa:value=>Buffer.from(value,'binary').toString('base64'),setTimeout:fn=>timers.push(fn),
 state,uiPreferenceSession:createPreferenceSession(),restoreLegacyBrowserSession,readPreference,preferenceCookie,
 FALLBACK_STORY_PLANS:[],MEMOIR_ROUTES:{home:'/memoir',start:'/memoir/start',interview:'/memoir/interview'},
 memoirApiPath:p=>'/api/v1/memoir'+p.slice(3),translate:String,escapeHtml:String,
 $:selector=>selector==='#app'?app:null,persistChatHistory(){},authReminder:{tick(){}},refreshProfileMenu(){},
 currentPath:()=>'/memoir',savedProjectId:()=>null,guestTransfer:{complete:async()=>false},syncProfileUiLocale:async()=>{},
});
context.window=context;
for(const script of input.order==='context-first'?input.scripts:[...input.scripts].reverse()) vm.runInContext(script,context);
await new Promise(resolve=>setImmediate(resolve));
if(input.switchPrincipal) await context.fixtureSetPrincipal(input.switchPrincipal);
const current=(await context.supabase.createClient().auth.getSession()).data.session;
const cookie=JSON.parse(Buffer.from(cookies.get('sb-auth-auth-token').slice(7),'base64url').toString());
if(input.phase==='seed') {console.log(JSON.stringify({cookie,current}));process.exit(0);}
const responses=input.responses;
context.fetch=async(url,options={})=>{
 const headers=new Headers(options.headers||{}), path=String(url).replace('https://auth.test','');
 const args=options.body?JSON.parse(options.body):null;
 const key=JSON.stringify([path,options.method||'GET',headers.get('authorization')]);
 calls.push([...JSON.parse(key),args]);
 if(path==='/api/v1/memoir/agent/config') return new Response(JSON.stringify(input.config),{status:200,headers:{'Content-Type':'application/json'}});
 if(!(key in responses)) throw Error('Unexpected request '+key);
 const response=responses[key];assert.deepEqual(args,response.arguments);return new Response(JSON.stringify(response.body),{status:response.status,headers:{'Content-Type':'application/json'}});
};
context.createBrowserClient=(url,key,options)=>createBrowserClient(url,key,{...options,isSingleton:false,
 cookies:{getAll:()=>[...cookies].map(([name,value])=>({name,value})),setAll:updates=>updates.forEach(({name,value})=>cookies.set(name,value))},
 global:{fetch:context.fetch}});
for(const name of ['captureProjectScope','isCurrentProjectScope','invalidateProjectNavigation','readCookie','syncAccountUiLocale',
 'syncSupabaseSession','loadSupabaseConfig','ensureAuth','renderMemoirLanding','boot']) vm.runInContext(extract(name),context);
context.renderLanding=()=>context.renderMemoirLanding();
await context.boot();
context.state.supabase?.client?.auth.stopAutoRefresh();
console.log(JSON.stringify({cookie,current,clientUser:state.supabase?.user,calls,html:app.innerHTML}));
