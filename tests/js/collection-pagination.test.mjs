import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../../apps/web/client/memoir/collection.js',import.meta.url),'utf8');
function load(name){
 const match=source.match(new RegExp(`export (?:async )?function ${name}\\([^]*?\\n\\}`));
 assert.ok(match,`${name} exists`);
 const context=vm.createContext({Set,Map,Error,encodeURIComponent,translate:key=>key});
 vm.runInContext(match[0].replace('export ',''),context);return context[name];
}
test('full export fetches every frozen page in order and preserves the requested title',async()=>{
 const collect=load('collectCollectionTaskResult');let calls=[];
 const api=async(path)=>{calls.push(path);return {id:'job',status:'SUCCEEDED',root_digest:'root',complete:calls.length===2,next_cursor:calls.length===1?'next':null,
 result:{title:'Selected title',coverage:{complete:true},sources:[{id:`s${calls.length}`,content:`page${calls.length}`}],sections:[{id:'root:1',title:'Global theme'}]}};};
 const result=await collect(api,'job');
 assert.deepEqual(Array.from(result.sources,row=>row.content),['page1','page2']);
 assert.equal(result.title,'Selected title');assert.equal(result.sections.length,1);
 assert.match(calls[1],/cursor=next/);
});
test('changed root, incomplete response and repeated cursor never produce a partial download',async()=>{
 const collect=load('collectCollectionTaskResult');
 for(const mode of ['changed','missing','repeated']){
  let count=0;
  await assert.rejects(collect(async()=>({id:'job',status:'SUCCEEDED',root_digest:mode==='changed'&&++count>1?'other':'root',complete:false,
   next_cursor:mode==='missing'?null:'same',result:{coverage:{complete:true},sources:[]}}),'job'));
 }
});
test('closing review during export stops later reads and does not create an artifact',async()=>{
 const collect=load('collectCollectionTaskResult');let active=true,calls=0;
 await assert.rejects(collect(async()=>{calls++;active=false;return {status:'SUCCEEDED',root_digest:'root',complete:false,next_cursor:'next',result:{sources:[]}};},'job',()=>active));
 assert.equal(calls,1);
});
test('selection changes preserve unloaded selected IDs and prior order',()=>{
 const merge=load('mergeCollectionSelection');
 assert.deepEqual(Array.from(merge(['later','first'],['first','second'],['second'])),['later','second']);
 assert.deepEqual(Array.from(merge(['later','first'],['first','second'],['first','second'])),['later','first','second']);
});
test('older task pages append once and reject repeated cursors or revision changes',()=>{
 const append=load('appendCollectionTaskPage');
 const previous={revision:4,source_fingerprint:'scope',tasks:[{id:'new'}],tasks_next_cursor:'new'};
 const next={revision:4,source_fingerprint:'scope',tasks:[{id:'new'},{id:'old'}],tasks_next_cursor:'old',tasks_complete:false};
 assert.deepEqual(Array.from(append(previous,next,'new').tasks,task=>task.id),['new','old']);
 assert.throws(()=>append(previous,{...next,tasks_next_cursor:'new'},'new'));
 assert.throws(()=>append(previous,{...next,revision:5},'new'));
});
test('only explicitly recoverable failures offer job retry',()=>{
 const retry=load('canRetryCollectionTask');
 assert.equal(retry({status:'FAILED',error:'BOUNDED_JOB_RETRY'}),true);
 for (const status of ['STALE','SUCCEEDED','RUNNING']) assert.equal(retry({status,error:'BOUNDED_JOB_RETRY'}),false);
 assert.equal(retry({status:'FAILED',error:'OTHER'}),false);
});
