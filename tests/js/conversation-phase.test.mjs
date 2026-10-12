import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createConversationPhase, conversationPhaseMarkup} from '../../apps/web/client/memoir/conversation-phase.mjs';

const phase = (overrides = {}) => ({schema_version:1, phase:'comfort', selection:'automatic', preferred_phase:null,
  revision:0, reason:'initial', source_turn_id:null, ...overrides});
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
  for (const action of ['comfort','explore','shape','automatic','skip']) {
    const h=harness(async (_,options) => envelope(options.method==='PATCH' ? phase({revision:1}) : phase()));
    await h.client.ensure();await h.client.act(action);
    assert.deepEqual(JSON.parse(h.calls[1][1].body),{action,expected_revision:0});
  }
});

test('a stale tab reconciles 409 by GET without replaying its action', async () => {
  let read=0;
  const h=harness(async (_,options) => {
    if(options.method==='PATCH') throw Object.assign(new Error('stale'),{status:409});
    return envelope(++read===1 ? phase() : phase({revision:3,phase:'shape',selection:'explicit',preferred_phase:'shape'}));
  });
  await h.client.ensure();await h.client.act('comfort');
  assert.deepEqual(h.calls.map(([,o])=>o.method),['GET','PATCH','GET']);
  assert.equal(h.client.view().value.revision,3);assert.equal(h.client.view().value.phase,'shape');
  assert.equal(h.client.view().notice,'conflict');assert.equal(h.client.view().busy,false);
});

test('delayed old project, owner and navigation responses never replace the current scope', async () => {
  for(const change of [{projectId:'other'},{ownerId:'other'},{generation:2}]) {
    const pending=deferred();let count=0;
    const h=harness(async()=>++count===1 ? pending.promise : envelope(phase({revision:2,phase:'explore'})));
    const old=h.client.ensure();h.setScope(change);
    assert.equal(h.client.view().value,null);
    await h.client.ensure();pending.resolve(envelope(phase({revision:90,phase:'shape',selection:'explicit',preferred_phase:'shape'})));await old;
    assert.equal(h.client.view().value.phase,'explore');assert.equal(h.client.view().value.revision,2);
  }
});

test('late mutation and failure cannot leak into a new owner or project', async () => {
  for(const outcome of ['resolve','reject']) {
    const pending=deferred();const h=harness(async(_,options)=> options.method==='PATCH' ? pending.promise : envelope(phase()));
    await h.client.ensure();const mutation=h.client.act('shape');h.setScope({ownerId:'other',projectId:'other'});
    await h.client.ensure();
    if(outcome==='resolve')pending.resolve(envelope(phase({phase:'shape',revision:5})));
    else pending.reject(new Error('old account failure'));
    await mutation;assert.equal(h.client.view().value.phase,'comfort');assert.equal(h.client.view().notice,null);
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
  await h.client.ensure();const first=h.client.act('shape');await h.client.act('shape');await h.client.act('shape');
  assert.equal(h.calls.length,2);pending.resolve(envelope(phase({revision:1,phase:'shape'})));await first;
  let fail=true;const retry=harness(async()=>{if(fail)throw new Error('offline');return envelope(phase());});
  await retry.client.ensure();assert.equal(retry.client.view().notice,'unavailable');
  await retry.client.act('shape');assert.equal(retry.calls.length,1);
  fail=false;await retry.client.refresh();assert.equal(retry.client.view().value.phase,'comfort');
});

test('failed mutation rechecks server before allowing another choice, without guessing an outcome', async () => {
  let reads=0;const h=harness(async(_,options)=>{
    if(options.method==='PATCH')throw new Error('connection ended after commit');
    return envelope(phase({phase:++reads>1?'shape':'comfort',revision:reads-1}));
  });
  await h.client.ensure();await h.client.act('shape');
  assert.equal(h.client.view().value.phase,'shape');assert.equal(h.client.view().notice,'saveError');
  assert.deepEqual(h.calls.map(([,o])=>o.method),['GET','PATCH','GET']);
});

test('localized controls have accessible pressed states without pause/resume or progress claims', () => {
  for(const locale of ['en-AU','zh-CN']) {
    const copy=JSON.parse(fs.readFileSync(new URL(`../../apps/web/messages/${locale}.json`,import.meta.url),'utf8')).Memoir.phase;
    assert.ok(copy);
    const html=conversationPhaseMarkup({value:phase({phase:'explore',selection:'explicit',preferred_phase:'explore'}),busy:false,notice:null},key=>copy[key]);
    for(const action of ['comfort','explore','shape','automatic','skip'])assert.match(html,new RegExp(`data-phase-action="${action}"`));
    assert.match(html,/role="group"/);assert.match(html,/data-phase-action="explore"[^>]*aria-pressed="true"/);
    assert.match(html,/role="status"/);assert.doesNotMatch(html,/%|progressbar|stepper|wizard/i);
    assert.doesNotMatch(html,/data-phase-action="(?:pause|resume)"/);
    assert.ok(html.includes(copy.comfort));
  }
});

test('the first saved turn initializes controls after project ownership becomes available', async () => {
  const h=harness(async()=>{throw Object.assign(new Error('project not persisted yet'),{status:403});});
  await h.client.ensure();assert.equal(h.client.view().notice,'unavailable');
  assert.equal(h.client.accept(h.scope(),phase({revision:1,phase:'explore'})),true);
  assert.equal(h.client.view().notice,null);assert.equal(h.client.view().value.phase,'explore');
});

test('generated replies finish before guidance changes; removed pause/resume actions never write', async () => {
  const html=conversationPhaseMarkup({value:phase(),busy:false,notice:null},key=>key,true);
  for(const action of ['comfort','explore','shape','automatic','skip']) {
    assert.match(html.match(new RegExp(`<button[^>]*data-phase-action="${action}"[^>]*>`))[0],/disabled/);
  }
  const h=harness();await h.client.ensure();
  await h.client.act('pause');await h.client.act('resume');
  assert.equal(h.calls.length,1);
});

test('a saved mode finalizes its reply, round status, cards and receipt without interrupting the flow', async () => {
  const vm=await import('node:vm');
  const {createInterviewPhotoState}=await import('../../apps/web/client/memoir/interview-photo-turns.mjs');
  const source=fs.readFileSync(new URL('../../apps/web/client/memoir/client.js',import.meta.url),'utf8');
  const scope={ownerId:'owner',projectId:'project',generation:1};
  const state={project:{id:'project',profile:{}},supabase:{accessToken:'fixture',user:{id:'owner'}},chat:[],attachments:[],loading:true,dictationStatus:'off',conversationStreams:new Set()};
  const cache=new Map();let persisted=[],draftReads=0,controller;
  const render=()=>{persisted=JSON.parse(JSON.stringify(state.chat));};
  const model=createConversationPhase({scope:()=>scope,api:async()=>envelope(phase()),onChange:render});
  state.conversationPhase=model;
  state.photoTurns=createInterviewPhotoState({state,scope:()=>scope,render,api:async()=>({}),uuid:()=> 'story-turn',
    storage:{getItem:key=>cache.get(key),setItem:(key,value)=>cache.set(key,value),removeItem:key=>cache.delete(key)}});
  const saved={conversation_saved:true,reply:'We can review the memories you shared.',recall_status:{rounds_completed:5,payment_required:false},
    conversation_phase:phase({phase:'shape',selection:'explicit',preferred_phase:'shape',revision:1,reason:'narrator_choice',source_turn_id:'story-turn'}),
    response_photos:[{photo_id:'reference:garden',kind:'public_reference',title:'Garden reference'}]};
  const context=vm.createContext({state,AbortController,captureProjectScope:()=>scope,isCurrentProjectScope:()=>true,
    conversationLanguage:()=> 'en-AU',simulatedLoopTrace:()=>[],render,updateStreamingAssistantMessage(){},nextAssistantMessageId:()=> 'reply',
    applyCommittedConversationLocale:async()=>{},refreshPrivateDraft:()=>{draftReads++;},
    streamAgentTurn:async(_,onDelta,onEvent,language,first,original,id,action,kind,request)=>{
      controller=request.controller;state.conversationStreams.add(controller);
      await onDelta('We can review');await onEvent({type:'conversation_saved',data:saved});return saved;
    }});
  for(const name of ['agentTurn'])vm.runInContext(source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0],context);
  await model.ensure();
  const result=await context.agentTurn('Shape my story','fallback');
  assert.notEqual(result.detached,true);assert.equal(controller.signal.aborted,false);
    assert.equal(state.recallStatus.rounds_completed,5);assert.equal(draftReads,1);
  assert.equal(state.pendingConversationTurn,null);assert.equal(state.photoTurns.pending(),null);assert.equal(cache.size,0);
  assert.equal(result.reply,saved.reply);assert.equal(persisted[0].text,saved.reply);
  assert.equal(persisted[0].responsePhotos[0].photo_id,'reference:garden');assert.equal(model.view().value.phase,'shape');
});

test('the recall boundary retains guidance controls without unlocking paid narration or drafts', async () => {
  const vm=await import('node:vm');
  const source=fs.readFileSync(new URL('../../apps/web/client/memoir/client.js',import.meta.url),'utf8');
  const state={project:{id:'project'},supabase:{accessToken:'fixture'},recallStatus:{rounds_completed:20,payment_required:true},
    conversationPhase:{view:()=>({value:phase(),busy:false,notice:null})},privateDraft:{status:'ready',text:'Private draft remains gated'}};
  const context=vm.createContext({state,conversationPhaseMarkup,translate:key=>key});
  vm.runInContext(source.match(/function chatComposer\([^]*?\n\}/)[0],context);
  const html=context.chatComposer();
  for(const action of ['comfort','explore','shape','automatic','skip'])assert.match(html,new RegExp(`data-phase-action="${action}"`));
  assert.doesNotMatch(html,/chat-input|chat-form|type="submit"|Private draft remains gated/);
  assert.equal(state.recallStatus.payment_required,true);assert.equal(state.recallStatus.rounds_completed,20);
});
