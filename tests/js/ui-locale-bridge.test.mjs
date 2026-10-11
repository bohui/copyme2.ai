import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { createPreferenceSession, firstReplyUiCandidate } from '../../apps/web/i18n/session.mjs';
const source=fs.readFileSync(new URL('../../apps/web/client/memoir/client.js',import.meta.url),'utf8');
function harness(){
 const calls=[],toasts=[],state={project:{id:'p',profile:{}},supabase:{user:{id:'a'},accessToken:'fixture'}};
 const session=createPreferenceSession();let fail=false;
 session.setSession({rpc:async(name,args)=>{calls.push(['rpc',args]);return fail?{error:{code:'offline'}}:{data:{locale:args.p_locale,source:args.p_source,revision:1}};}},state.supabase.user);
 const context=vm.createContext({state,uiPreferenceSession:session,firstReplyUiCandidate,UI_LOCALES:new Set(['en-AU','zh-CN']),
  toast:value=>toasts.push(value),translate:key=>key,currentUiPreference:()=>session.preference,profile:()=>state.project.profile,
  preserveConversationLocale:value=>value,storyApi:async(_path,options)=>{calls.push(['profile']);const language=JSON.parse(options.body).preferred_language;return {preferred_language:language,conversation_language:{source:'explicit'}};}});
 for(const name of ['installUiLocaleBridge','persistCommittedFirstReplyUiLocale']) vm.runInContext(source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0],context);
 context.installUiLocaleBridge();context.__copyme2SetUiLocale=async(locale,options)=>context.__copyme2BeforeUiLocaleChange(locale,options);
 return {state,session,context,calls,toasts,setFailure:value=>{fail=value;}};
}
test('partial profile success is explained and retry does not reapply profile action',async()=>{
 const h=harness();h.setFailure(true);assert.equal(await h.context.__copyme2BeforeUiLocaleChange('zh-CN'),false);
 assert.equal(h.state.project.profile.preferred_language,'zh-CN');assert.deepEqual(h.toasts,['Common.languagePartiallySaved']);
 h.setFailure(false);assert.equal((await h.context.__copyme2BeforeUiLocaleChange('zh-CN')).locale,'zh-CN');
 assert.equal(h.calls.filter(([kind])=>kind==='profile').length,1);
});
test('failed first-reply write is repairable from committed authoritative conversation on reload',async()=>{
 const h=harness();h.state.project=null;h.context.profile=()=>({});h.setFailure(true);
 assert.equal(await h.context.__copyme2BeforeUiLocaleChange('zh-CN',{source:'first_reply'}),false);
 const saved={conversation_language:{version:1,initialized:true,source:'first_reply',first_reply_locale:'zh-CN'}};
 h.setFailure(false);await h.context.persistCommittedFirstReplyUiLocale(saved);
 assert.equal(h.session.preference.locale,'zh-CN');assert.equal(h.session.preference.source,'first_reply');
 assert.equal(h.calls.filter(([kind])=>kind==='profile').length,0);
});
test('explicit or legacy conversation settings never become a new automatic UI signal',()=>{
 for(const kind of ['explicit','legacy']) assert.equal(firstReplyUiCandidate({conversation_language:{version:1,initialized:true,source:kind,first_reply_locale:'zh-CN'}}),null);
 assert.equal(firstReplyUiCandidate({conversation_language:{version:1,initialized:true,source:'first_reply',locale:'zh-CN',first_reply_locale:null}}),null);
});
test('recording guard prevents preference and profile writes',async()=>{
 const h=harness();h.state.recording=true;assert.equal(await h.context.__copyme2BeforeUiLocaleChange('zh-CN'),false);
 assert.deepEqual(h.calls,[]);assert.deepEqual(h.toasts,['Common.finishRecordingFirst']);
});
const deferred=()=>{let resolve;const promise=new Promise(r=>{resolve=r;});return {promise,resolve};};
test('project navigation during profile save releases pending intent',async()=>{
 const h=harness(),gate=deferred();h.context.storyApi=()=>gate.promise;
 const save=h.context.__copyme2BeforeUiLocaleChange('zh-CN');await Promise.resolve();
 h.state.project={id:'new',profile:{}};gate.resolve({preferred_language:'zh-CN'});
 assert.equal(await save,false);assert.equal(h.session.busy,false);
});
test('whole manual operation preserves newer profile and account choice',async()=>{
 const h=harness(),gates=[deferred(),deferred()],writes=[];let stored;
 h.context.storyApi=async(_path,options)=>{const language=JSON.parse(options.body).preferred_language;const gate=gates[writes.length];writes.push(language);await gate.promise;stored=language;return {preferred_language:language,conversation_language:{source:'explicit'}};};
 const older=h.context.__copyme2BeforeUiLocaleChange('en-AU');await Promise.resolve();
 const newer=h.context.__copyme2BeforeUiLocaleChange('zh-CN');await Promise.resolve();
 assert.deepEqual(writes,['en-AU']);gates[0].resolve();assert.equal(await older,false);
 await new Promise(r=>setImmediate(r));assert.deepEqual(writes,['en-AU','zh-CN']);gates[1].resolve();
 assert.equal((await newer).locale,'zh-CN');assert.equal(stored,'zh-CN');assert.equal(h.session.preference.locale,'zh-CN');assert.equal(h.session.busy,false);
});

test('same-project navigation generation cancels a pending profile intent',async()=>{
 const h=harness(),gate=deferred();h.context.storyApi=()=>gate.promise;
 h.state.navigationGeneration=1;const save=h.context.__copyme2BeforeUiLocaleChange('zh-CN');await Promise.resolve();
 h.state.navigationGeneration=2;gate.resolve({preferred_language:'zh-CN'});
 assert.equal(await save,false);assert.equal(h.session.busy,false);assert.equal(h.calls.length,0);
});
