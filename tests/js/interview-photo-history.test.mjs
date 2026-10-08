import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {responsePhotoCards} from '../../apps/web/client/memoir/interview-photo-turns.mjs';

const source=fs.readFileSync(new URL('../../apps/web/client/memoir/client.js',import.meta.url),'utf8');
const card={photo_id:'upload:11111111-1111-4111-8111-111111111111',kind:'private_upload',title:'Your private photo'};
const exchange=(id,more={})=>({server_turn_id:`server-${id}`,client_turn_id:id,created_at:'2026-10-08T12:00:00Z',narrator_text:`Narration ${id}`,reply:`Question ${id}?`,response_photos:[card],...more});
function harness({anonymous=false,chat=[],pages=[{items:[exchange('turn')],next_cursor:null}],legacy=[]}={}){
 const state={supabase:{user:{id:'owner',is_anonymous:anonymous}},project:{id:'project'},navigationGeneration:1,chat,photoTurns:{cards:responsePhotoCards}};
 const paths=[];let count=0;
 const context=vm.createContext({state,openingMessages:['Welcome'],conversationMessage:()=> 'Welcome',cleanAssistantText:text=>text,persistChatHistory(){},
  storyApi:async path=>{paths.push(path);return path.startsWith('/v1/user/projects/')?{project_id:'project',policy_epoch:'1',...pages[count++]}:{items:legacy}}});
 for(const name of ['captureProjectScope','isCurrentProjectScope','originalConversationText','normalizeHistoryOpening','hydrateAccountHistory'])vm.runInContext(source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0],context);
 return {state,paths,context};
}

for(const anonymous of [false,true])test(`fresh ${anonymous?'guest':'account'} browser restores durable cards and turn identity without tab storage`,async()=>{
 const h=harness({anonymous});await h.context.hydrateAccountHistory();
 assert.equal(h.paths[0],'/v1/user/projects/project/history?limit=100');
 const reply=h.state.chat.find(m=>m.role==='assistant'&&m.clientTurnId==='turn');
 assert.equal(reply?.text,'Question turn?');assert.deepEqual(reply.responsePhotos,[{...card,description:''}]);
 if(anonymous)assert.equal(h.paths.length,1);
});

test('canonical pagination restores chronological exchanges and reuses opaque cursor',async()=>{
 const h=harness({anonymous:true,pages:[{items:[exchange('new')],next_cursor:'opaque+/='},{items:[exchange('old',{created_at:'2026-10-07T12:00:00Z'})],next_cursor:null}]});
 await h.context.hydrateAccountHistory();
 assert.equal(h.paths[1],'/v1/user/projects/project/history?limit=100&cursor=opaque%2B%2F%3D');
 assert.deepEqual(Array.from(h.state.chat.filter(m=>m.role==='user'),m=>m.text),['Narration old','Narration new']);
});

test('project imports remain visible without duplicating canonical turns or importing another project',async()=>{
 const h=harness({legacy:[{id:'attached',project_id:'project',messages:[{role:'user',text:'Legacy guest memory'},{role:'user',text:'Narration turn'},{role:'assistant',text:'Question turn?'}]},
 {id:'unrelated',project_id:'other',messages:[{role:'user',text:'Other project'}]},
 {id:'account-conversation',project_id:'account-conversation',messages:[{role:'user',text:'Old flattened account memory'}]}]});
 await h.context.hydrateAccountHistory();
 assert.equal(h.state.chat.filter(m=>m.text==='Question turn?').length,1);
 assert.ok(h.state.chat.some(m=>m.text==='Legacy guest memory'));
 assert.ok(!h.state.chat.some(m=>['Other project','Old flattened account memory'].includes(m.text)));
 assert.equal(h.state.chat.find(m=>m.text==='Question turn?').responsePhotos.length,1);
});

test('withdrawn canonical turns cannot be revived by cached photos or mapped guest transcripts',async()=>{
 const h=harness({pages:[{items:[exchange('turn',{narrator_text:null,reply:null,source_status:'withdrawn',response_photos:[]})],next_cursor:null}],
  chat:[{role:'assistant',text:'Question turn?',clientTurnId:'turn',responsePhotos:[card]}],
  legacy:[{id:'attached',project_id:'project',workspace:{memory_id_map:{old:'server-turn'}},messages:[{role:'assistant',text:'Question turn?'}]}]});
 await h.context.hydrateAccountHistory();
 assert.ok(!h.state.chat.some(m=>m.text==='Question turn?'));
});

test('canonical cards remain authoritative when a local matching reply has stale photo metadata',async()=>{
 const h=harness({pages:[{items:[exchange('turn',{response_photos:[]})],next_cursor:null}],chat:[{role:'assistant',text:'Question turn?',clientTurnId:'turn',responsePhotos:[card],cacheId:'cached'}]});
 await h.context.hydrateAccountHistory();const reply=h.state.chat.find(m=>m.clientTurnId==='turn'&&m.role==='assistant');
 assert.deepEqual(Array.from(reply.responsePhotos),[]);assert.equal(reply.cacheId,'cached');
});

test('principal change while canonical history is loading discards the entire snapshot',async()=>{
 const h=harness();h.context.storyApi=async()=>{h.state.supabase.user.id='other';return {project_id:'project',items:[exchange('private')]}};
 await h.context.hydrateAccountHistory();assert.equal(h.state.chat.length,0);
});

test('a denied canonical project history never falls back to aggregate private history',async()=>{
 const h=harness();h.context.storyApi=async path=>{h.paths.push(path);throw Object.assign(new Error('Denied'),{status:403})};
 await assert.rejects(h.context.hydrateAccountHistory(),/Denied/);assert.equal(h.paths.length,1);assert.equal(h.state.chat.length,0);
});

test('legacy-only projects retain scoped guest imports but omit unscoped account history',async()=>{
 const h=harness({pages:[{items:[],next_cursor:null}],legacy:[{id:'attached',project_id:'project',messages:[{role:'user',text:'My older guest memory'}]},{id:'account-conversation',project_id:'account-conversation',messages:[{role:'user',text:'Unscoped account memory'}]}]});
 await h.context.hydrateAccountHistory();assert.ok(h.state.chat.some(m=>m.text==='My older guest memory'));assert.ok(!h.state.chat.some(m=>m.text==='Unscoped account memory'));
});

for(const status of [401,403,404,503,undefined])test(`canonical ${status||'network'} failure hides cached replies instead of falling back`,async()=>{
 const h=harness({chat:[{role:'assistant',text:'Old private description',clientTurnId:'turn',responsePhotos:[card]}]});
 h.context.storyApi=async path=>{h.paths.push(path);throw Object.assign(new Error('Unavailable'),{status})};
 await assert.rejects(h.context.hydrateAccountHistory(),/Unavailable/);
 assert.equal(h.state.chat.length,0);assert.equal(h.paths.length,1);
});

test('source correction replaces old narrator text and removes its superseded cached photo reply',async()=>{
 const h=harness({pages:[{items:[exchange('turn',{narrator_text:'Corrected recollection',reply:null,source_version:'2',response_photos:[]})]}],
  chat:[{role:'user',text:'Narration turn',clientTurnId:'turn'},{role:'assistant',text:'Question turn?',clientTurnId:'turn',responsePhotos:[card]}],
  legacy:[{project_id:'project',messages:[{role:'assistant',text:'Question turn?'}]}]});
 await h.context.hydrateAccountHistory();
 assert.equal(h.state.chat.filter(m=>m.text==='Corrected recollection').length,1);
 assert.ok(!h.state.chat.some(m=>m.text==='Narration turn'||m.text==='Question turn?'));
});

test('a repeated new pending answer does not merge into an older canonical turn with the same wording',async()=>{
 const h=harness({chat:[{role:'user',text:'Narration turn',clientTurnId:'different-pending-turn'}]});
 await h.context.hydrateAccountHistory();assert.equal(h.state.chat.filter(m=>m.text==='Narration turn').length,2);
});

test('an owner switch on a later page cannot replace the new owners history',async()=>{
 const h=harness({anonymous:true});let calls=0;
 h.context.storyApi=async()=>{
  if(++calls===1)return {project_id:'project',policy_epoch:'1',items:[exchange('private')],next_cursor:'next'};
  h.state.supabase.user.id='other';h.state.chat=[{role:'user',text:'Other owner memory'}];
  return {project_id:'project',policy_epoch:'1',items:[exchange('older')],next_cursor:null};
 };
 await h.context.hydrateAccountHistory();assert.deepEqual(Array.from(h.state.chat,m=>m.text),['Other owner memory']);
});

test('mixed project or policy-epoch pages are rejected without displaying a partial stale snapshot',async()=>{
 for(const second of [{project_id:'other'},{policy_epoch:'2'}]){
  const h=harness({anonymous:true,pages:[{items:[exchange('private')],next_cursor:'next'},{items:[exchange('older')],...second}],chat:[{role:'user',text:'Old cache'}]});
  await assert.rejects(h.context.hydrateAccountHistory(),/Project history changed/);assert.equal(h.state.chat.length,0);
 }
});
