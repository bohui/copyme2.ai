import test from 'node:test';
import assert from 'node:assert/strict';
import { createPreferenceSession } from '../../apps/web/i18n/session.mjs';
const deferred = () => { let resolve; const promise = new Promise(r => resolve=r); return {promise,resolve}; };
const manual = locale => ({locale,source:'manual',revision:1});
test('late account read cannot overwrite a fresh manual choice',async()=>{
 const old=deferred(); const state=createPreferenceSession();
 state.setSession({rpc:async name=>name==='read_ui_locale_preference'?old.promise:{data:manual('zh-CN')}},{id:'a'});
 const read=state.refresh(); await state.choose('zh-CN','manual'); old.resolve({data:manual('en-AU')});
 assert.equal(await read,null); assert.equal(state.preference.locale,'zh-CN');
});
test('late preference write cannot apply after A to B or logout',async()=>{
 for(const next of [{id:'b'},null]) { const response=deferred(); const state=createPreferenceSession();
 state.setSession({rpc:()=>response.promise},{id:'a'}); const write=state.choose('zh-CN','manual');
 state.setSession(null,next); response.resolve({data:manual('zh-CN')}); assert.equal(await write,null); assert.equal(state.preference,null); }
});
test('first reply persists with distinct provenance and uses authoritative winner',async()=>{
 const calls=[]; const state=createPreferenceSession();
 state.setSession({rpc:async(name,args)=>{calls.push([name,args]);return {data:manual('en-AU')}}},{id:'a'});
 const result=await state.choose('zh-CN','first_reply'); assert.equal(result.locale,'en-AU');
 assert.deepEqual(calls,[['set_ui_locale_preference',{p_locale:'zh-CN',p_source:'first_reply',p_expected_viewer:'a'}]]);
});
test('failed persistence never reports durable success',async()=>{
 const state=createPreferenceSession(); state.setSession({rpc:async()=>({error:{message:'fixture'}})},{id:'a'});
 await assert.rejects(state.choose('zh-CN','manual')); assert.equal(state.preference,null);
});
test('manual intent fences account read before asynchronous profile persistence',async()=>{
 const read=deferred(); const state=createPreferenceSession();state.setSession({rpc:()=>read.promise},{id:'a'});
 const pending=state.refresh();state.beginIntent();read.resolve({data:manual('en-AU')});
 assert.equal(await pending,null);
});
test('refresh during a pending manual write cannot install its older snapshot',async()=>{
 const write=deferred(),read=deferred();const state=createPreferenceSession();
 state.setSession({rpc: name=>name==='read_ui_locale_preference'?read.promise:write.promise},{id:'a'});
 const choosing=state.choose('zh-CN','manual');const refreshing=state.refresh();
 write.resolve({data:{locale:'zh-CN',source:'manual',revision:2}});await choosing;
 read.resolve({data:{locale:'en-AU',source:'manual',revision:1}});await refreshing;
 assert.equal(state.preference.locale,'zh-CN');
});
test('authorization mismatch never falls back to stale legacy account locale',async()=>{
 const state=createPreferenceSession();state.setSession({rpc:async()=>({error:{code:'42501'}})},{id:'a',user_metadata:{ui_locale:'zh-CN'}});
 assert.equal(await state.refresh(),null);assert.equal(state.preference,null);
});
test('only missing migration may read established legacy metadata',async()=>{
 for(const code of ['PGRST202','42883','503']) { const state=createPreferenceSession();
 state.setSession({rpc:async()=>({error:{code}})},{id:'a',user_metadata:{ui_locale:'zh-CN'}});
 assert.equal((await state.refresh())?.locale,code==='503'?undefined:'zh-CN'); }
});
test('stale network rejection after account switch cannot become a current error',async()=>{
 let reject;const promise=new Promise((_,r)=>reject=r);const state=createPreferenceSession();
 state.setSession({rpc:()=>promise},{id:'a'});const pending=state.choose('zh-CN','manual');await Promise.resolve();state.setSession(null,{id:'b'});reject(new Error('old failure'));
 assert.equal(await pending,null);
});
test('manual writes serialize so the latest action also wins persisted state',async()=>{
 const calls=[];const state=createPreferenceSession();state.setSession({rpc:(_name,args)=>{const request=deferred();calls.push({args,...request});return request.promise;}},{id:'a'});
 const first=state.choose('en-AU','manual');await Promise.resolve();
 const second=state.choose('zh-CN','manual');await Promise.resolve();assert.equal(calls.length,1);
 calls[0].resolve({data:{locale:'en-AU',source:'manual',revision:1}});assert.equal(await first,null);
 await Promise.resolve();assert.equal(calls.length,2);assert.equal(calls[1].args.p_locale,'zh-CN');
 calls[1].resolve({data:{locale:'zh-CN',source:'manual',revision:2}});await second;
 assert.equal(state.preference.locale,'zh-CN');assert.equal(state.preference.revision,2);
});
