import { readMemoirClientSource } from './helpers/memoir-source.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';

const phase = (overrides = {}) => ({phase:'comfort', selection:'automatic', ...overrides});

test('switching draft editions discards the old rewrite form before it can submit', async () => {
  const vm=await import('node:vm');
  const source=readMemoirClientSource();
  const scope={ownerId:'owner',projectId:'project',generation:1};
  const record={id:'section',preview:{title:'English',text:'Original English prose.'}};
  const state={privateDraftLocale:'en-AU',privateDraft:{locale:'en-AU',snapshot_id:'english-snapshot',root_digest:'english-root',first_record:record}};
  const calls=[];
  const context=vm.createContext({state,crypto:{randomUUID:()=> 'request'},$:()=>null,
    captureProjectScope:()=>scope,isCurrentProjectScope:()=>true,render(){},
    storyApi:async(path,options)=>calls.push({path,payload:JSON.parse(options.body)}),
    refreshPrivateDraft:async()=>{state.privateDraft={locale:'zh-CN',snapshot_id:'chinese-snapshot',root_digest:'chinese-root',first_record:record};}});
  for (const name of ['currentSectionRework','openSectionRework','selectPrivateDraftLocale','submitSectionRework']) {
    vm.runInContext(source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0],context);
  }
  context.openSectionRework(record.id);
  state.sectionRework.instruction='Keep this short.';
  await context.selectPrivateDraftLocale('zh-CN');
  await context.submitSectionRework({preventDefault(){}});
  assert.deepEqual(calls,[],'the English snapshot must not be rewritten after switching to Chinese');
  assert.equal(context.currentSectionRework(),null);
});

test('an old edition response cannot mark a new rewrite form queued or refresh its draft', async () => {
  const vm=await import('node:vm');
  const source=readMemoirClientSource();
  const scope={ownerId:'owner',projectId:'project',generation:1};
  const record={id:'section',preview:{title:'English',text:'Original prose.'}};
  const state={privateDraftLocale:'en-AU',privateDraft:{locale:'en-AU',snapshot_id:'english-snapshot',root_digest:'english-root',first_record:record}};
  let resolveRequest,reads=0;
  const context=vm.createContext({state,crypto:{randomUUID:()=> 'request'},$:()=>null,
    captureProjectScope:()=>scope,isCurrentProjectScope:()=>true,render(){},
    storyApi:()=>new Promise(resolve=>{resolveRequest=resolve;}),
    refreshPrivateDraft:async()=>{reads++;state.privateDraft={locale:'zh-CN',snapshot_id:'chinese-snapshot',root_digest:'chinese-root',first_record:record};}});
  for (const name of ['currentSectionRework','openSectionRework','selectPrivateDraftLocale','submitSectionRework']) {
    vm.runInContext(source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0],context);
  }
  context.openSectionRework(record.id);
  state.sectionRework.instruction='Old edition instruction.';
  const pending=context.submitSectionRework({preventDefault(){}});
  await context.selectPrivateDraftLocale('zh-CN');
  context.openSectionRework(record.id);
  const current=state.sectionRework;
  resolveRequest({status:'pending'});
  await pending;
  assert.equal(context.currentSectionRework(),current);
  assert.equal(current.queued,undefined);
  assert.equal(reads,1,'the old response must not trigger a refresh in the new edition');
});

test('saved receipt recovery consumes its workspace focus and preserves a later selection', async () => {
  const vm=await import('node:vm');
  const source=readMemoirClientSource();
  const scope={ownerId:'owner',projectId:'project',generation:1};
  const value={kind:'add_memory',life_stage:'childhood'};
  const state={chat:[],workspaceMemoryFocus:{...scope,value}};
  const context=vm.createContext({state,isCurrentProjectScope:()=>true,
    nextAssistantMessageId:()=> 'reply',persistChatHistory(){}});
  for (const name of ['currentWorkspaceMemoryFocus','workspaceTurnFocus','markWorkspaceFocusStarted']) {
    vm.runInContext(source.match(new RegExp(`function ${name}\\([^]*?\\n\\}`))[0],context);
  }
  const recover=vm.runInContext(`(${source.match(/onRecovered: (async \(turn, receipt\) => \{[^]*?\n  \}),/)[1]})`,context);
  const turn={id:'accepted-turn',workspaceFocus:value};
  await recover(turn,{reply:'Tell me about that time.'});
  assert.equal(context.workspaceTurnFocus(),null);
  assert.equal(state.chat[0].clientTurnId,turn.id);
  state.workspaceMemoryFocus={...scope,value:{kind:'add_memory',life_stage:'later_life'}};
  await recover(turn,{reply:'Tell me about that time.'});
  assert.equal(context.workspaceTurnFocus().life_stage,'later_life');
  assert.equal(state.chat.length,1);
});

test('a workspace task finalizes its reply, round status, cards and receipt without interrupting the flow', async () => {
  const vm=await import('node:vm');
  const {createInterviewPhotoState}=await import('../../apps/web/client/memoir/interview-photo-turns.mjs');
  const source=readMemoirClientSource();
  const scope={ownerId:'owner',projectId:'project',generation:1};
  const state={project:{id:'project',profile:{}},supabase:{accessToken:'fixture',user:{id:'owner'}},chat:[],attachments:[],loading:true,dictationStatus:'off',conversationStreams:new Set()};
  const cache=new Map();let persisted=[],draftReads=0,controller;
  const render=()=>{persisted=JSON.parse(JSON.stringify(state.chat));};
  state.photoTurns=createInterviewPhotoState({state,scope:()=>scope,render,api:async()=>({}),uuid:()=> 'story-turn',
    storage:{getItem:key=>cache.get(key),setItem:(key,value)=>cache.set(key,value),removeItem:key=>cache.delete(key)}});
  const saved={conversation_saved:true,reply:'We can review the memories you shared.',recall_status:{rounds_completed:5,payment_required:false},
    conversation_phase:phase({phase:'shape',selection:'explicit',preferred_phase:'shape',revision:1,reason:'narrator_choice',source_turn_id:'story-turn'}),
    response_photos:[{photo_id:'reference:garden',kind:'public_reference',title:'Garden reference'}]};
  const context=vm.createContext({state,AbortController,captureProjectScope:()=>scope,isCurrentProjectScope:()=>true,
    workspaceTurnFocus:()=>({kind:'add_memory',life_stage:'childhood'}), markWorkspaceFocusStarted:()=>{},
    conversationLanguage:()=> 'en-AU',simulatedLoopTrace:()=>[],render,updateStreamingAssistantMessage(){},nextAssistantMessageId:()=> 'reply',
    applyCommittedConversationLocale:async()=>{},refreshStageReadiness:async()=>{},refreshPrivateDraft:()=>{draftReads++;},
    streamAgentTurn:async(_,onDelta,onEvent,language,first,original,id,action,kind,request)=>{
      controller=request.controller;state.conversationStreams.add(controller);
      await onDelta('We can review');await onEvent({type:'conversation_saved',data:saved});return saved;
    }});
  for(const name of ['freeRecallFinished','agentTurn'])vm.runInContext(source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0],context);
  const result=await context.agentTurn('Shape my story','fallback');
  assert.notEqual(result.detached,true);assert.equal(controller.signal.aborted,false);
  assert.equal(state.recallStatus.rounds_completed,5);assert.equal(draftReads,1);
  assert.equal(state.pendingConversationTurn,null);assert.equal(state.photoTurns.pending(),null);assert.equal(cache.size,0);
  assert.equal(result.reply,saved.reply);assert.equal(persisted[0].text,saved.reply);
  assert.equal(persisted[0].responsePhotos[0].photo_id,'reference:garden');
});

test('the recall boundary keeps paid narration gated without mode controls', async () => {
  const vm=await import('node:vm');
  const source=readMemoirClientSource();
  const state={project:{id:'project'},supabase:{accessToken:'fixture'},recallStatus:{rounds_completed:20,payment_required:true},
    conversationPhase:{view:()=>({value:phase(),busy:false,notice:null})},privateDraft:{status:'ready',text:'Private draft remains gated'}};
  const context=vm.createContext({state,workspaceMemoryFocusMarkup:()=>'',translate:key=>key});
  vm.runInContext(source.match(/function chatComposer\([^]*?\n\}/)[0],context);
  const html=context.chatComposer();
  assert.doesNotMatch(html,/data-phase-action/);
  assert.doesNotMatch(html,/chat-input|chat-form|type="submit"|Private draft remains gated/);
  assert.equal(state.recallStatus.payment_required,true);assert.equal(state.recallStatus.rounds_completed,20);
});
