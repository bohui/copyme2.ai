import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createConversationPhase, conversationPhaseMarkup} from '../../apps/web/client/memoir/conversation-phase.mjs';

const phase = (overrides = {}) => ({schema_version:1, phase:'comfort', selection:'automatic', preferred_phase:null,
  paused:false, revision:0, reason:'initial', source_turn_id:null, ...overrides});
const envelope = value => ({conversation_phase:value});
const deferred = () => { let resolve, reject; const promise = new Promise((yes,no) => {resolve=yes;reject=no;}); return {promise,resolve,reject}; };
function harness(api = async () => envelope(phase())) {
  let scope = {ownerId:'owner',projectId:'project',generation:1};
  const calls = [], changes = [];
  const client = createConversationPhase({scope:() => ({...scope}), api:async (...args) => {calls.push(args);return api(...args);},
    onChange:() => changes.push(client.view())});
  return {client,calls,changes,setScope:next => {scope={...scope,...next};},scope:() => ({...scope})};
}

test('reload fetches authoritative phase; controls write only action and revision, never a narration turn', async () => {
  let saved = phase({phase:'shape',selection:'explicit',preferred_phase:'shape',revision:7});
  const h = harness(async (path,options) => {
    if (options.method === 'PATCH') { const body=JSON.parse(options.body); saved=phase({phase:body.action,selection:'explicit',preferred_phase:body.action,revision:8}); }
    return envelope(saved);
  });
  await h.client.ensure();
  assert.equal(h.client.view().value.phase,'shape');
  await h.client.act('comfort');
  assert.equal(h.client.view().value.phase,'comfort');
  assert.equal(h.calls[1][0],'/v1/agent/projects/project/conversation-phase');
  assert.deepEqual(JSON.parse(h.calls[1][1].body),{action:'comfort',expected_revision:7});
  assert.equal(h.calls[0][1].cache,'no-store');
  assert.equal(h.calls.length,2);
  const reload=harness(async () => envelope(saved));await reload.client.ensure();
  assert.equal(reload.client.view().value.revision,8);
});

test('all phase controls use the explicit action contract', async () => {
  for (const action of ['comfort','explore','shape','automatic','pause','resume','skip']) {
    const h=harness(async (_,options) => envelope(options.method==='PATCH' ? phase({revision:1,paused:action==='pause'}) : phase()));
    await h.client.ensure();await h.client.act(action);
    assert.deepEqual(JSON.parse(h.calls[1][1].body),{action,expected_revision:0});
  }
});

test('a stale tab reconciles 409 by GET without replaying its action', async () => {
  let read=0;
  const h=harness(async (_,options) => {
    if(options.method==='PATCH') throw Object.assign(new Error('stale'),{status:409});
    return envelope(++read===1 ? phase() : phase({revision:3,phase:'shape',paused:true}));
  });
  await h.client.ensure();await h.client.act('comfort');
  assert.deepEqual(h.calls.map(([,o])=>o.method),['GET','PATCH','GET']);
  assert.equal(h.client.view().value.revision,3);assert.equal(h.client.view().value.paused,true);
  assert.equal(h.client.view().notice,'conflict');assert.equal(h.client.view().busy,false);
});

test('delayed old project, owner and navigation responses never replace the current scope', async () => {
  for(const change of [{projectId:'other'},{ownerId:'other'},{generation:2}]) {
    const pending=deferred();let count=0;
    const h=harness(async()=>++count===1 ? pending.promise : envelope(phase({revision:2,phase:'explore'})));
    const old=h.client.ensure();h.setScope(change);
    assert.equal(h.client.view().value,null);
    await h.client.ensure();pending.resolve(envelope(phase({revision:90,phase:'shape',paused:true})));await old;
    assert.equal(h.client.view().value.phase,'explore');assert.equal(h.client.view().value.revision,2);
  }
});

test('late mutation and failure cannot leak into a new owner or project', async () => {
  for(const outcome of ['resolve','reject']) {
    const pending=deferred();const h=harness(async(_,options)=> options.method==='PATCH' ? pending.promise : envelope(phase()));
    await h.client.ensure();const mutation=h.client.act('pause');h.setScope({ownerId:'other',projectId:'other'});
    await h.client.ensure();
    if(outcome==='resolve')pending.resolve(envelope(phase({paused:true,revision:5})));
    else pending.reject(new Error('old account failure'));
    await mutation;assert.equal(h.client.view().value.paused,false);assert.equal(h.client.view().notice,null);
  }
});

test('saved turns are scoped and monotonic, even when an older GET is still pending', async () => {
  const pending=deferred();const h=harness(()=>pending.promise);const request=h.client.ensure();
  h.client.accept(h.scope(),phase({revision:4,phase:'explore'}));
  pending.resolve(envelope(phase({revision:2})));await request;
  assert.equal(h.client.view().value.phase,'explore');
  h.client.accept({...h.scope(),ownerId:'other'},phase({revision:9,phase:'shape'}));
  assert.equal(h.client.view().value.revision,4);
});

test('rapid repeated clicks serialize one write and unavailable reads remain recoverable', async () => {
  const pending=deferred();const h=harness(async(_,options)=> options.method==='PATCH' ? pending.promise : envelope(phase()));
  await h.client.ensure();const first=h.client.act('pause');await h.client.act('pause');await h.client.act('shape');
  assert.equal(h.calls.length,2);pending.resolve(envelope(phase({revision:1,paused:true})));await first;
  let fail=true;const retry=harness(async()=>{if(fail)throw new Error('offline');return envelope(phase());});
  await retry.client.ensure();assert.equal(retry.client.view().notice,'unavailable');
  await retry.client.act('pause');assert.equal(retry.calls.length,1);
  fail=false;await retry.client.refresh();assert.equal(retry.client.view().value.phase,'comfort');
});

test('failed mutation rechecks server before allowing another choice, without guessing an outcome', async () => {
  let reads=0;const h=harness(async(_,options)=>{
    if(options.method==='PATCH')throw new Error('connection ended after commit');
    return envelope(phase({paused:++reads>1,revision:reads-1}));
  });
  await h.client.ensure();await h.client.act('pause');
  assert.equal(h.client.view().value.paused,true);assert.equal(h.client.view().notice,'saveError');
  assert.deepEqual(h.calls.map(([,o])=>o.method),['GET','PATCH','GET']);
});

test('localized controls have accessible pressed states, pause/resume and no progress claims', () => {
  for(const locale of ['en-AU','zh-CN']) {
    const copy=JSON.parse(fs.readFileSync(new URL(`../../apps/web/messages/${locale}.json`,import.meta.url),'utf8')).Memoir.phase;
    assert.ok(copy);
    const html=conversationPhaseMarkup({value:phase({phase:'explore',selection:'explicit',preferred_phase:'explore'}),busy:false,notice:null},key=>copy[key]);
    for(const action of ['comfort','explore','shape','automatic','skip','pause'])assert.match(html,new RegExp(`data-phase-action="${action}"`));
    assert.match(html,/role="group"/);assert.match(html,/data-phase-action="explore"[^>]*aria-pressed="true"/);
    assert.match(html,/role="status"/);assert.doesNotMatch(html,/%|progressbar|stepper|wizard/i);
    const paused=conversationPhaseMarkup({value:phase({paused:true}),busy:false,notice:null},key=>copy[key]);
    assert.match(paused,/data-phase-action="resume"/);assert.doesNotMatch(paused,/data-phase-action="pause"/);
    assert.ok(html.includes(copy.comfort));assert.ok(paused.includes(copy.paused));
  }
});

test('the first saved turn initializes controls after project ownership becomes available', async () => {
  const h=harness(async()=>{throw Object.assign(new Error('project not persisted yet'),{status:403});});
  await h.client.ensure();assert.equal(h.client.view().notice,'unavailable');
  assert.equal(h.client.accept(h.scope(),phase({revision:1,phase:'explore'})),true);
  assert.equal(h.client.view().notice,null);assert.equal(h.client.view().value.phase,'explore');
});

test('Pause remains available during a generated reply while other guidance choices wait', () => {
  const html=conversationPhaseMarkup({value:phase(),busy:false,notice:null},key=>key,true);
  assert.doesNotMatch(html.match(/<button[^>]*data-phase-action="pause"[^>]*>/)[0],/disabled/);
  assert.match(html.match(/<button[^>]*data-phase-action="shape"[^>]*>/)[0],/disabled/);
});

test('pausing a delayed generated reply aborts transport and ignores every late question token', async () => {
  const vm=await import('node:vm');
  const source=fs.readFileSync(new URL('../../apps/web/client/memoir/client.js',import.meta.url),'utf8');
  const pending=deferred();let delta;
  const scope={ownerId:'owner',projectId:'project',generation:1};
  const state={project:{id:'project'},supabase:{accessToken:'fixture',user:{id:'owner'}},chat:[],loading:true,dictationStatus:'off',conversationStreams:new Set()};
  const model=createConversationPhase({scope:()=>scope,api:async()=>envelope(phase()),onChange:()=>context.synchronizeConversationPhase()});
  state.conversationPhase=model;
  const context=vm.createContext({state,AbortController,captureProjectScope:()=>scope,isCurrentProjectScope:()=>true,
    conversationLanguage:()=> 'en-AU',simulatedLoopTrace:()=>[],render(){},updateStreamingAssistantMessage(){},nextAssistantMessageId:()=> 'reply',
    streamAgentTurn:async(_,onDelta,onEvent,language,first,original,id,action,kind,request)=>{
      delta=onDelta;state.conversationStreams.add(request.controller);return pending.promise;
    }});
  for(const name of ['synchronizeConversationPhase','agentTurn'])vm.runInContext(source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0],context);
  await model.ensure();
  const turn=context.agentTurn('A memory','fallback');await delta('I hear you.');
  model.accept(scope,phase({paused:true,revision:1}));
  assert.equal(state.loading,false);assert.equal(state.chat[0].streaming,false);
  await delta(' What happened next?');pending.resolve({reply:'What happened next?',conversation_phase:phase()});
  assert.equal((await turn).detached,true);assert.equal(state.chat[0].text,'I hear you.');
  assert.equal(model.view().value.paused,true);assert.equal(state.conversationStreams.size,0);
});

test('paused text composer still submits natural-language Resume through the same collector', async () => {
  const vm=await import('node:vm');
  const source=fs.readFileSync(new URL('../../apps/web/client/memoir/client.js',import.meta.url),'utf8');
  const calls=[],input={value:'Resume when you’re ready'};
  const state={conversationPhase:{view:()=>({value:phase({paused:true})})},chat:[{role:'user',text:'Earlier words'}],
    attachments:[],dictationStatus:'off',audioTranscript:'',audioTranscriptKind:'narrator_chat',profileIntakePending:false};
  const context=vm.createContext({state,captureProjectScope:()=>({}),isCurrentProjectScope:()=>true,$:()=>input,render(){},
    conversationScroll:{follow(){}},conversationMessage:key=>key,conversationLanguage:()=> 'en-AU',
    profile:()=>({conversation_language:{initialized:true}}),ensureMemorySession:async()=>null,
    agentTurn:async(...args)=>{calls.push(args);return {reply:'We can continue.'};},streamAssistantMessage:async()=>{},refreshFamilyContext(){}});
  vm.runInContext(source.match(/async function sendChatMessage\([^]*?\n\}/)[0],context);
  await context.sendChatMessage();
  assert.equal(calls.length,1);assert.equal(calls[0][5],'Resume when you’re ready');
  assert.equal(state.loading,false);
});

test('a durable natural pause finalizes its own reply, round status, cards and receipt', async () => {
  const vm=await import('node:vm');
  const {createInterviewPhotoState}=await import('../../apps/web/client/memoir/interview-photo-turns.mjs');
  const source=fs.readFileSync(new URL('../../apps/web/client/memoir/client.js',import.meta.url),'utf8');
  const scope={ownerId:'owner',projectId:'project',generation:1};
  const state={project:{id:'project',profile:{}},supabase:{accessToken:'fixture',user:{id:'owner'}},chat:[],attachments:[],loading:true,dictationStatus:'off',conversationStreams:new Set()};
  const cache=new Map();let persisted=[],draftReads=0,controller;
  const render=()=>{persisted=JSON.parse(JSON.stringify(state.chat));};
  const model=createConversationPhase({scope:()=>scope,api:async()=>envelope(phase()),onChange:change=>context.synchronizeConversationPhase(change)});
  state.conversationPhase=model;
  state.photoTurns=createInterviewPhotoState({state,scope:()=>scope,render,api:async()=>({}),uuid:()=> 'pause-turn',
    storage:{getItem:key=>cache.get(key),setItem:(key,value)=>cache.set(key,value),removeItem:key=>cache.delete(key)}});
  const saved={conversation_saved:true,reply:'We can pause. Your memories are saved.',recall_status:{rounds_completed:5,payment_required:false},
    conversation_phase:phase({paused:true,revision:1,reason:'pause',source_turn_id:'pause-turn'}),
    response_photos:[{photo_id:'reference:garden',kind:'public_reference',title:'Garden reference'}]};
  const context=vm.createContext({state,AbortController,captureProjectScope:()=>scope,isCurrentProjectScope:()=>true,
    conversationLanguage:()=> 'en-AU',simulatedLoopTrace:()=>[],render,updateStreamingAssistantMessage(){},nextAssistantMessageId:()=> 'reply',
    applyCommittedConversationLocale:async()=>{},refreshPrivateDraft:()=>{draftReads++;},
    streamAgentTurn:async(_,onDelta,onEvent,language,first,original,id,action,kind,request)=>{
      controller=request.controller;state.conversationStreams.add(controller);
      await onDelta('We can pause.');await onEvent({type:'conversation_saved',data:saved});return saved;
    }});
  for(const name of ['synchronizeConversationPhase','agentTurn'])vm.runInContext(source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0],context);
  await model.ensure();
  const result=await context.agentTurn('Please pause','fallback');
  assert.notEqual(result.detached,true);assert.equal(controller.signal.aborted,false);
  assert.equal(state.conversationInterrupt || 0,0);
  assert.equal(state.recallStatus.rounds_completed,5);assert.equal(draftReads,1);
  assert.equal(state.pendingConversationTurn,null);assert.equal(state.photoTurns.pending(),null);assert.equal(cache.size,0);
  assert.equal(result.reply,saved.reply);assert.equal(persisted[0].text,saved.reply);
  assert.equal(persisted[0].responsePhotos[0].photo_id,'reference:garden');assert.equal(model.view().value.paused,true);
});

test('the recall boundary retains guidance controls without unlocking paid narration or drafts', async () => {
  const vm=await import('node:vm');
  const source=fs.readFileSync(new URL('../../apps/web/client/memoir/client.js',import.meta.url),'utf8');
  const state={project:{id:'project'},supabase:{accessToken:'fixture'},recallStatus:{rounds_completed:20,payment_required:true},
    conversationPhase:{view:()=>({value:phase(),busy:false,notice:null})},privateDraft:{status:'ready',text:'Private draft remains gated'}};
  const context=vm.createContext({state,conversationPhaseMarkup,translate:key=>key});
  vm.runInContext(source.match(/function chatComposer\([^]*?\n\}/)[0],context);
  const html=context.chatComposer();
  for(const action of ['comfort','explore','shape','automatic','skip','pause'])assert.match(html,new RegExp(`data-phase-action="${action}"`));
  assert.doesNotMatch(html,/chat-input|chat-form|type="submit"|Private draft remains gated/);
  assert.equal(state.recallStatus.payment_required,true);assert.equal(state.recallStatus.rounds_completed,20);
});
