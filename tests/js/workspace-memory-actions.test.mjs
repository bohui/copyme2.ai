import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const phase = (overrides = {}) => ({phase:'comfort', selection:'automatic', ...overrides});

test('saved receipt recovery consumes its workspace focus and preserves a later selection', async () => {
  const vm=await import('node:vm');
  const source=fs.readFileSync(new URL('../../apps/web/client/memoir/client.js',import.meta.url),'utf8');
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
  const source=fs.readFileSync(new URL('../../apps/web/client/memoir/client.js',import.meta.url),'utf8');
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
    applyCommittedConversationLocale:async()=>{},refreshPrivateDraft:()=>{draftReads++;},
    streamAgentTurn:async(_,onDelta,onEvent,language,first,original,id,action,kind,request)=>{
      controller=request.controller;state.conversationStreams.add(controller);
      await onDelta('We can review');await onEvent({type:'conversation_saved',data:saved});return saved;
    }});
  for(const name of ['agentTurn'])vm.runInContext(source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0],context);
  const result=await context.agentTurn('Shape my story','fallback');
  assert.notEqual(result.detached,true);assert.equal(controller.signal.aborted,false);
  assert.equal(state.recallStatus.rounds_completed,5);assert.equal(draftReads,1);
  assert.equal(state.pendingConversationTurn,null);assert.equal(state.photoTurns.pending(),null);assert.equal(cache.size,0);
  assert.equal(result.reply,saved.reply);assert.equal(persisted[0].text,saved.reply);
  assert.equal(persisted[0].responsePhotos[0].photo_id,'reference:garden');
});

test('the recall boundary keeps paid narration gated without mode controls', async () => {
  const vm=await import('node:vm');
  const source=fs.readFileSync(new URL('../../apps/web/client/memoir/client.js',import.meta.url),'utf8');
  const state={project:{id:'project'},supabase:{accessToken:'fixture'},recallStatus:{rounds_completed:20,payment_required:true},
    conversationPhase:{view:()=>({value:phase(),busy:false,notice:null})},privateDraft:{status:'ready',text:'Private draft remains gated'}};
  const context=vm.createContext({state,workspaceMemoryFocusMarkup:()=>'',translate:key=>key});
  vm.runInContext(source.match(/function chatComposer\([^]*?\n\}/)[0],context);
  const html=context.chatComposer();
  assert.doesNotMatch(html,/data-phase-action/);
  assert.doesNotMatch(html,/chat-input|chat-form|type="submit"|Private draft remains gated/);
  assert.equal(state.recallStatus.payment_required,true);assert.equal(state.recallStatus.rounds_completed,20);
});
