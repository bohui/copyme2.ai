import test from 'node:test';
import assert from 'node:assert/strict';
import {createInterviewPhotoState, responsePhotoCards} from '../../apps/web/client/memoir/interview-photo-turns.mjs';

function harness() {
 const state={project:{id:'p',profile:{photo_memories:{p:{favorites:[{key:'photo-a'}],selected:'photo-a',selection_revision:'r1'}}}},supabase:{user:{id:'owner'},accessToken:'token'},navigationGeneration:1,attachments:[],chat:[]};
 const storage=new Map(); let sequence=0;
 const deps={state,scope:()=>({projectId:state.project.id,ownerId:state.supabase.user.id,generation:state.navigationGeneration}),render(){},storage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},uuid:()=>`turn-${++sequence}`,api:async()=>({state:'not_found'})};
 const photos=createInterviewPhotoState(deps);return {state,storage,deps,photos};
}

test('acceptance consumes exactly the submitted cue and leaves favourites',()=>{
 const {state,photos}=harness();const turn=photos.prepare({text:'Original',conversationText:'Original',sourceKind:'narrator_chat'});
 assert.deepEqual(turn.photoSelection,{key:'photo-a',revision:'r1'});
 photos.accept(turn,{state:'pending',photo_cue:{consumed:true,key:'photo-a',revision:'r1'}});
 assert.equal(state.project.profile.photo_memories.p.selected,'photo-a');
 photos.accept(turn,{state:'source_accepted',photo_cue:{consumed:true,key:'photo-a',revision:'r1'}});
 assert.equal(state.project.profile.photo_memories.p.selected,null);
 assert.equal(state.project.profile.photo_memories.p.favorites.length,1);
});

test('delayed acceptance never clears a reselected same photo, newer photo, or another principal',()=>{
 for(const change of [s=>s.project.profile.photo_memories.p.selection_revision='r2',s=>s.project.profile.photo_memories.p.selected='photo-b',s=>s.supabase.user.id='other']){
 const {state,photos}=harness();const turn=photos.prepare({text:'Original',conversationText:'Original'});change(state);
 photos.accept(turn,{state:'source_accepted',photo_cue:{consumed:true,key:'photo-a',revision:'r1'}});
 assert.ok(state.project.profile.photo_memories.p.selected);
 }
});

test('retry and reload retain original photo snapshot and upload IDs',async()=>{
 const {state,photos,deps}=harness();
 state.attachments=[{privatePhoto:{id:'upload-a'},file:{name:'a.png'}}];
 const first=photos.prepare({text:'Original',conversationText:'Original',sourceKind:'narrator_transcript',attachments:state.attachments});
 state.project.profile.photo_memories.p.selected='photo-b';state.project.profile.photo_memories.p.selection_revision='r2';
 const reloaded=createInterviewPhotoState(deps);await reloaded.recover();
 const retry=reloaded.prepare({...first,retry:reloaded.pending()});
 assert.equal(retry.id,first.id);assert.deepEqual(retry.uploadedPhotoIds,['upload-a']);assert.deepEqual(retry.photoSelection,{key:'photo-a',revision:'r1'});
 assert.equal(retry.sourceKind,'narrator_transcript');
 state.supabase.user.id='other';assert.equal(reloaded.pending(),null);
});

test('private cards never retain display credentials, URLs or plan JSON',()=>{
 const [card]=responsePhotoCards([{photo_id:'upload:abc',kind:'private_upload',title:'Private',description:'Narrator says garden',content_url:'https://secret',image_url:'https://secret?token=x',plan:{question:'Hidden'}}]);
 assert.deepEqual(card,{photo_id:'upload:abc',kind:'private_upload',title:'Private',description:'Narrator says garden'});
 assert.deepEqual(responsePhotoCards([{kind:'private_upload',image_url:'https://secret'}]),[]);
});

test('accepted uploads clear only consumed pending attachments; failure preserves them',()=>{
 const {state,photos}=harness();const old={privatePhoto:{id:'a'}},newer={privatePhoto:{id:'b'}};state.attachments=[old];
 const turn=photos.prepare({text:'',conversationText:'',attachments:[old]});state.attachments.push(newer);
 photos.accept(turn,{state:'not_found'});assert.equal(state.attachments.length,2);
 photos.accept(turn,{state:'source_accepted',photo_cue:{consumed:true}});assert.deepEqual(state.attachments,[newer]);
});

test('listening to a saved reply speaks that visible reply, not the optional session question', async () => {
 const fs=await import('node:fs'),vm=await import('node:vm');
 const source=fs.readFileSync(new URL('../../apps/web/client/memoir/client.js',import.meta.url),'utf8');
 const calls=[];
 const context=vm.createContext({state:{session:{id:'optional-session'}},captureProjectScope:()=>({}),isCurrentProjectScope:()=>true,
  cleanAssistantText:text=>text,conversationLanguage:()=> 'en-AU',currentUiLocale:()=> 'en-AU',translate:x=>x,toast(){},
  storyApi:async(path,options)=>{calls.push({path,body:JSON.parse(options.body)});return {audio_url:'synthetic'}},
  api:async()=>{throw new Error('The optional session question must not be spoken')},
  playGeneratedAudio:async()=>{},window:{speechSynthesis:{cancel(){},speak(){}}},SpeechSynthesisUtterance:function(text){this.text=text}});
 vm.runInContext(source.match(/async function speakText\([^]*?\n\}/)[0],context);
 await context.speakText('You remembered the gate. Who went with you?');
 assert.equal(calls[0]?.path,'/v1/story/question-audio');
 assert.equal(calls[0]?.body.text,'You remembered the gate. Who went with you?');
});

test('private display requests authenticate each owned identity and revoke preview bytes on account change',async()=>{
 const {photos,state}=harness();
 const oldFetch=globalThis.fetch,oldRevoke=URL.revokeObjectURL;const requests=[],revoked=[];
 const image={dataset:{privateResponsePhoto:'11111111-1111-4111-8111-111111111111'},isConnected:true,hidden:true};
 try{
  globalThis.fetch=async(path,options)=>{requests.push({path,options});return new Response(new Blob(['synthetic'],{type:'image/png'}),{headers:{'Content-Type':'image/png'}})};
  URL.revokeObjectURL=url=>{revoked.push(url);oldRevoke(url)};
  await photos.bindImages({querySelectorAll:()=>[image]},{path:x=>x,errorText:'Unavailable'});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(requests[0].options.headers.Authorization,'Bearer token');
  assert.equal(requests[0].options.cache,'no-store');assert.match(image.src,/^blob:/);
  state.chat=[{attachments:[{url:'blob:old-upload-preview'}]}];
  photos.clearDisplay();
  assert.deepEqual(revoked,[image.src,'blob:old-upload-preview']);
 }finally{globalThis.fetch=oldFetch;URL.revokeObjectURL=oldRevoke}
});

test('a late private image response is discarded after principal change',async()=>{
 const {photos,state}=harness();const oldFetch=globalThis.fetch;let resolve;
 const image={dataset:{privateResponsePhoto:'11111111-1111-4111-8111-111111111111'},isConnected:true,hidden:true};
 try{
  globalThis.fetch=()=>new Promise(done=>resolve=done);
  await photos.bindImages({querySelectorAll:()=>[image]},{path:x=>x,errorText:'Unavailable'});
  state.supabase.user.id='other';photos.clearDisplay();
  resolve(new Response(new Blob(['synthetic'],{type:'image/png'}),{headers:{'Content-Type':'image/png'}}));
  await new Promise(done=>setImmediate(done));
  assert.equal(image.src,undefined);assert.equal(image.hidden,true);
 }finally{globalThis.fetch=oldFetch}
});

test('reload receipt recovery keeps response cards and never issues a second turn',async()=>{
 const h=harness();const turn=h.photos.prepare({text:'Original',conversationText:'Original'});const recovered=[];const paths=[];
 const photos=createInterviewPhotoState({...h.deps,api:async path=>{paths.push(path);return {state:'conversation_saved',reply:'Who joined you?',photo_cue:{consumed:true,key:'photo-a',revision:'r1'},response_photos:[{photo_id:'public:gate',kind:'public_reference',title:'Gate'}]}},onRecovered:(saved,data)=>recovered.push({saved,data})});
 await photos.recover();assert.equal(paths[0],`/v1/agent/turns/${turn.id}?project_id=p`);
 assert.equal(recovered[0].data.response_photos.length,1);assert.equal(h.state.project.profile.photo_memories.p.selected,null);
 assert.equal(photos.pending(),null);assert.equal(h.storage.size,0);
});

test('the shipped stream sends saved photo identity and acknowledges acceptance before reply',async()=>{
 const fs=await import('node:fs'),vm=await import('node:vm');
 const source=fs.readFileSync(new URL('../../apps/web/client/memoir/client.js',import.meta.url),'utf8');
 const sent=[],events=[],deltas=[];let controller;
 const state={project:{id:'p'},supabase:{user:{id:'owner'},accessToken:'token'},navigationGeneration:1};
 const context=vm.createContext({state,AbortController,TextDecoder,TextEncoder,Response,
  captureProjectScope:()=>({projectId:'p',ownerId:'owner',generation:1}),isCurrentProjectScope:()=>true,
  conversationLanguage:()=> 'en-AU',memoirApiPath:x=>x,readCookie:()=>'',localizedErrorMessage:()=> 'error',
  fetch:async(path,options)=>{sent.push(JSON.parse(options.body));return new Response(new ReadableStream({start:c=>controller=c}))}});
 vm.runInContext(source.match(/async function streamAgentTurn\([^]*?\n\}/)[0],context);
 const turn={id:'stable-id',text:'saved wrapper',conversationText:'Original words',sourceKind:'narrator_transcript',uploadedPhotoIds:['owned-id'],photoSelection:{key:'photo-a',revision:'r1'}};
 const pending=context.streamAgentTurn('different text',x=>deltas.push(x),x=>events.push(x),undefined,false,'wrong narration',turn.id,null,'narrator_chat',{turn});
 await new Promise(resolve=>setImmediate(resolve));
 const emit=event=>controller.enqueue(new TextEncoder().encode(JSON.stringify(event)+'\n'));
 emit({type:'source_accepted',data:{photo_cue:{consumed:true,key:'photo-a',revision:'r1'}}});
 await new Promise(resolve=>setImmediate(resolve));assert.equal(events[0].type,'source_accepted');
 emit({type:'private_plan',data:{candidates:[{question:'Never show this'}]}});
 emit({type:'text_delta',text:'Who joined you?'});
 emit({type:'conversation_saved',data:{conversation_saved:true,reply:'Who joined you?',response_photos:[]}});controller.close();
 const result=await pending;assert.equal(result.reply,'Who joined you?');assert.deepEqual(deltas,['Who joined you?']);
 assert.equal(sent[0].conversation_text,'Original words');assert.equal(sent[0].source_kind,'narrator_transcript');
 assert.deepEqual(sent[0].photo_selection,{key:'photo-a',revision:'r1'});assert.deepEqual(sent[0].uploaded_photo_ids,['owned-id']);
 assert.equal(events.some(event=>event.type==='private_plan'),false);
});

test('legacy selections without a revision use null and still fence a newer UUID selection',()=>{
 for(const reselected of [false,true]){
  const {state,photos}=harness();delete state.project.profile.photo_memories.p.selection_revision;
  const turn=photos.prepare({text:'Original',conversationText:'Original'});
  assert.deepEqual(turn.photoSelection,{key:'photo-a',revision:null});
  if(reselected)state.project.profile.photo_memories.p.selection_revision='new-selection';
  photos.accept(turn,{state:'source_accepted',photo_cue:{consumed:true,key:'photo-a',revision:null}});
  assert.equal(state.project.profile.photo_memories.p.selected,reselected?'photo-a':null);
 }
});
