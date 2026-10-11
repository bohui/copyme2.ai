import test from 'node:test';
import assert from 'node:assert/strict';
import { restoreLegacyBrowserSession, retireLegacyBrowserSession } from '../../apps/web/auth/browser.mjs';
const saved={access_token:'synthetic-access',refresh_token:'synthetic-refresh'};
const url='https://project.supabase.co', key='sb-project-auth-token';
const store=()=>{const map=new Map([[key,JSON.stringify(saved)]]);return {getItem:k=>map.get(k),setItem:(k,v)=>map.set(k,v),removeItem:k=>map.delete(k),map};};
test('legacy session imports once, verifies, then retires old storage',async()=>{
 const events=[],storage=store();const auth={getSession:async()=>({data:{session:null}}),setSession:async tokens=>{events.push(['set',tokens]);return {data:{session:saved}}},getUser:async()=>{events.push(['verify']);return {data:{user:{id:'a'}}}}};
 assert.equal(await restoreLegacyBrowserSession({auth},url,storage),saved);
 assert.deepEqual(events,[['set',saved],['verify']]);assert.equal(storage.getItem(key),undefined);assert.equal(storage.getItem(key+':cookie-migrated'),'1');
});
test('failed import preserves recovery data and does not create a replacement guest',async()=>{
 const storage=store();const auth={getSession:async()=>({data:{session:null}}),setSession:async()=>({error:{message:'expired'},data:{}})};
 await assert.rejects(restoreLegacyBrowserSession({auth},url,storage));assert.ok(storage.getItem(key));assert.equal(storage.getItem(key+':cookie-migrated'),undefined);
});
test('coexistence followed by logout cannot resurrect obsolete localStorage',async()=>{
 const storage=store();let session={user:{id:'b'}};const auth={getSession:async()=>({data:{session}}),getUser:async()=>({data:{user:{id:'b'}}}),setSession:()=>assert.fail('must not restore obsolete session')};
 assert.equal(await restoreLegacyBrowserSession({auth},url,storage),session);session=null;
 // A still-open old-version tab can write the retired key again.
 storage.setItem(key,JSON.stringify(saved));assert.equal(await restoreLegacyBrowserSession({auth},url,storage),null);
});
test('explicit logout retires a key even when no old session was present',async()=>{
 const storage=store();retireLegacyBrowserSession(url,storage);storage.setItem(key,JSON.stringify(saved));
 assert.equal(await restoreLegacyBrowserSession({auth:{getSession:async()=>({data:{session:null}})}},url,storage),null);
});
test('unverified coexisting session never destroys original recovery material',async()=>{
 const storage=store();await assert.rejects(restoreLegacyBrowserSession({auth:{getSession:async()=>({data:{session:saved}}),getUser:async()=>({error:{message:'invalid'},data:{}})}},url,storage));assert.ok(storage.getItem(key));
});
test('full or unavailable legacy storage cannot prevent SDK logout',async()=>{
 const {signOutBrowserSession}=await import('../../apps/web/auth/browser.mjs');
 for(const storage of [undefined,{setItem(){throw new Error('QuotaExceededError');},removeItem(){throw new Error('SecurityError');}}]){
  let revoked=false;const result=await signOutBrowserSession({auth:{signOut:async()=>{revoked=true;return {};}}},url,storage);
  assert.equal(revoked,true);assert.equal(result.legacyRetired,false);
 }
});
test('logout waits for an in-flight legacy import before final revocation',async()=>{
 const {signOutBrowserSession}=await import('../../apps/web/auth/browser.mjs');
 let release,live=null;const gate=new Promise(r=>{release=r;});const storage=store();
 const client={auth:{getSession:async()=>({data:{session:null}}),setSession:async()=>{await gate;live=saved;return {data:{session:saved}};},getUser:async()=>({data:{user:{id:'a'}}}),signOut:async()=>{live=null;return {};}}};
 const restoring=restoreLegacyBrowserSession(client,url,storage);await Promise.resolve();await Promise.resolve();
 const rejection=assert.rejects(restoring,/cancelled/);const logout=signOutBrowserSession(client,url,storage);release();
 await logout;await rejection;assert.equal(live,null);
});
