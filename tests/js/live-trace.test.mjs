import { readMemoirClientSource } from './helpers/memoir-source.mjs';
import test from 'node:test';
import { escapeHtml } from '../../apps/web/client/memoir/dom.mjs';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {createReplyRevision} from '../../apps/web/client/memoir/reply-revision.mjs';
const source=readMemoirClientSource();
const extract = name => ['captureProjectScope', 'isCurrentProjectScope', 'currentWorkspaceMemoryFocus', 'workspaceTurnFocus', 'markWorkspaceFocusStarted', 'readBrowserValues', 'mergeChatHistoryCopies'].map(helper => source.match(new RegExp(`(?:async )?function ${helper}\\([^]*?\\n\}`))[0]).join('\n') + '\n' + (source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0]);

test('revision events discard old and untagged tokens without ending the reply stream', async () => {
 const events=[{type:'reply_revision',data:{revision:0}}, {type:'text_delta',text:'Draft.',revision:0},
  {type:'reply_revision',data:{revision:1}}, {type:'text_delta',text:'Late cancelled tokens.',revision:0},
  {type:'text_delta',text:'Untagged cancelled tokens.'}, {type:'text_delta',text:'Replacement.',revision:1},
  {type:'reply_revision',data:{revision:0}},
  {type:'conversation_saved',data:{reply:'Replacement.',conversation_saved:true}},
  {type:'reply_revision',data:{revision:2}}, {type:'text_delta',text:'After save.',revision:2},
  {type:'result',data:{reply:'Replacement.',conversation_saved:true}}];
 const seen=[];
 const body=new ReadableStream({start(controller){controller.enqueue(new TextEncoder().encode(events.map(JSON.stringify).join('\n')));controller.close();}});
 const context=vm.createContext({fetch:async()=>({ok:true,status:200,body}),state:{supabase:{accessToken:'test'},project:{id:'p'}},
  memoirApiPath:p=>p,readCookie:()=>'',TextDecoder,conversationLanguage:()=> 'en-AU'});
 vm.runInContext(extract('streamAgentTurn'),context);
 const result=await context.streamAgentTurn('A memory',async(text,revision)=>seen.push([text,revision]),
  async event=>{if(event.type==='reply_revision')seen.push(event.data.revision);});
 await new Promise(resolve=>setImmediate(resolve));
 assert.deepEqual(seen,[0,['Draft.',0],1,['Replacement.',1]]);
 assert.equal(result.reply,'Replacement.');
});

for (const fail of [false,true]) test(`chat revises an immediately visible draft and clears it on ${fail?'failure':'save'}`, async () => {
 const frames=[];
 const context=vm.createContext({state:{supabase:{accessToken:'test'},project:{id:'p'},chat:[]},
  conversationLanguage:()=> 'en-AU', simulatedLoopTrace:()=>[], nextAssistantMessageId:()=> 'm', render:()=>{},
  updateStreamingAssistantMessage:message=>frames.push(message.text),toast:()=>{},
  createReplyRevision:options=>createReplyRevision({...options,reducedMotion:()=>false,schedule:setImmediate,cancel:clearImmediate}),
  refreshPrivateDraft:async()=>{},refreshStageReadiness:async()=>{},
  streamAgentTurn:async(_text,onDelta,onEvent)=>{
    await onEvent({type:'reply_revision',data:{revision:0}});
    await onDelta('An unreviewed family detail.',0);
    assert.equal(context.state.chat.at(-1).text,'An unreviewed family detail.');
    assert.equal(context.state.chat.at(-1).provisional,true);
    await onEvent({type:'reply_revision',data:{revision:1}});
    await onDelta('LATE OLD TOKENS',0);
    if(fail)throw new Error('Review unavailable');
    await onDelta('We can change the subject.',1);
    return {reply:'We can change the subject.',conversation_saved:true};
  }});
 vm.runInContext(extract('agentTurn'),context);
 const result=await context.agentTurn('Please leave my family out.');
 assert.equal(result.failed,fail?true:undefined);
 assert.equal(result.streamedMessage.text,fail?'':'We can change the subject.');
 assert.equal(result.streamedMessage.provisional,false);
 assert.ok(frames.includes(''));
 assert.equal(frames.some(text=>text.includes('LATE OLD')),false);
});
for (const completion of [{cached:false,has_question:true},
 {cached:false,has_question:true,reply:'A memory. What happened next?'},
 {cached:false,has_question:true,reply:'A memory. What happened next?',conversation_saved:true}]) {
 test(`reply completion without a save or terminal receipt rejects clean EOF: ${JSON.stringify(completion)}`,async()=>{
  const events=[{type:'text_delta',text:'A memory. '},{type:'question_validated',data:{has_question:true}},
    {type:'text_delta',text:'What happened next?'},{type:'reply_complete',data:completion}];
  const body=new ReadableStream({start(controller){controller.enqueue(new TextEncoder().encode(events.map(JSON.stringify).join('\n')+'\n'));controller.close();}});
  const received=[];
  const context=vm.createContext({fetch:async()=>({ok:true,status:200,body}),state:{supabase:{accessToken:'test'},project:{id:'p'}},
    memoirApiPath:p=>p,readCookie:()=>'',TextDecoder,conversationLanguage:()=> 'en-AU',localizedErrorMessage:()=> 'Incomplete streaming response'});
  vm.runInContext(extract('streamAgentTurn'),context);
  await assert.rejects(context.streamAgentTurn('A memory',async text=>received.push(text),async()=>{}),/Incomplete streaming response/);
  assert.deepEqual(received,['A memory. ','What happened next?']);
 });
}
test('public milestone metadata cannot unlock the next answer before conversation save', async()=>{
 let controller;
 const body=new ReadableStream({start(value){controller=value;}});
 const seen=[];
 const context=vm.createContext({fetch:async()=>({ok:true,status:200,body}),state:{supabase:{accessToken:'test'},project:{id:'p'}},
   memoirApiPath:p=>p,readCookie:()=>'',TextDecoder,conversationLanguage:()=> 'en-AU'});
 vm.runInContext(extract('streamAgentTurn'),context);
 let ready=false;
 const pending=context.streamAgentTurn('A memory',async text=>seen.push(text),async()=>{}).then(result=>{ready=true;return result;});
 const emit=events=>controller.enqueue(new TextEncoder().encode(events.map(JSON.stringify).join('\n')+'\n'));
 try{
   emit([{type:'text_delta',text:'A memory. '},{type:'question_validated',data:{has_question:true}},
     {type:'text_delta',text:'What happened next?'},{type:'reply_complete',data:{cached:false,has_question:true}}]);
   await new Promise(resolve=>setImmediate(resolve));
   assert.equal(ready,false);
   assert.deepEqual(seen,['A memory. ','What happened next?']);
   emit([{type:'conversation_saved',data:{reply:'A memory. What happened next?',conversation_saved:true}},
     {type:'result',data:{reply:'A memory. What happened next?',conversation_saved:true}}]);
   const result=await pending;
   assert.equal(ready,true);
   assert.equal(result.conversation_saved,true);
   assert.equal(result.reply,'A memory. What happened next?');
 }finally{controller.close();}
});
test('forwards progress before text and skill events after conversation save', async () => {
 const seen=[];
 const events=[{type:'progress',data:{id:'context',label:'Loading context'}},{type:'text_delta',text:'Hello'}, {type:'conversation_saved',data:{reply:'Hello',conversation_saved:true}}, {type:'progress',data:{id:'place',skill:'memoir-place-journey'}},{type:'result',data:{reply:'Hello'}}];
 const body=new ReadableStream({start(controller){controller.enqueue(new TextEncoder().encode(events.map(JSON.stringify).join('\n')));controller.close();}});
 const context=vm.createContext({fetch:async()=>({ok:true,status:200,body}),state:{supabase:{accessToken:'test'},project:{id:'p'}},memoirApiPath:p=>p,readCookie:()=>'',TextDecoder,conversationLanguage:()=> undefined});
 vm.runInContext(extract('streamAgentTurn'),context);
 await context.streamAgentTurn('Hi',async text=>seen.push(text),async event=>seen.push(event));
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(seen[0].type,'progress');
 assert.equal(seen[1],'Hello');
 assert.equal(seen[2].data.skill,'memoir-place-journey');
});
test('fast saved response retains live trace and later triggered skills', async () => {
 let emitEvent;
 const context=vm.createContext({state:{supabase:{accessToken:'test'},project:{id:'p'},chat:[]},conversationLanguage:()=> undefined, simulatedLoopTrace:()=>[{label:'fake'}], nextAssistantMessageId:()=> 'm1', render:()=>{}, updateStreamingAssistantMessage:()=>{},waitForAssistantPaint:async()=>{},
 streamAgentTurn:async (text,onDelta,onEvent)=>{
   emitEvent=onEvent;
   await onEvent({type:'progress',data:{id:'context',label:'Context',detail:'Loading conversation context',status:'running'}});
   await onDelta('Hello');
   await onEvent({type:'progress',data:{id:'context',label:'Context',detail:'Conversation context loaded',status:'completed'}});
   return {reply:'Hello',conversation_saved:true};
 }});
 context.refreshPrivateDraft = async () => {};
  context.refreshStageReadiness = async () => {};
 vm.runInContext(extract('agentTurn'),context);
 const result=await context.agentTurn('Hi');
 assert.equal(result.streamedMessage.progressText,undefined);
 assert.equal(result.traceMode,'live');
 assert.equal(result.trace.length,1);
 assert.equal(result.trace[0].status,'completed');
 await emitEvent({type:'progress',data:{id:'place',skill:'memoir-place-journey',status:'triggered'}});
 assert.equal(result.trace.length,2);
 assert.equal(result.streamedMessage.trace[1].skill,'memoir-place-journey');
});
test('live trace is collapsed while reply text is streaming', () => {
 const context=vm.createContext({state:{showThinkingSteps:true},CHATBOT_NAME:'Mira',escapeHtml:String,translate:key=>key,translateWith:(key,{count})=>`${count} steps`,formatText:String,cleanAssistantText:String});
 vm.runInContext(extract('renderAgentTrace'),context);
 vm.runInContext(extract('renderMessage'),context);
 const html=context.renderMessage({id:'m',role:'assistant',text:'Hello',streaming:true,traceMode:'live',trace:[{id:'place',label:'Checking places',status:'running'}]});
 assert.match(html,/class="message-trace"/);
 assert.doesNotMatch(html,/class="agent-loop" open/);
 assert.match(html,/data-step-status="running"/);
});
test('thinking steps distinguish lanes and explain skipped place extraction', () => {
 const state={showThinkingSteps:true,project:{id:'p'},chat:[]};
 const captured=[];
 const context=vm.createContext({state,escapeHtml:String,translate:key=>key,
   recordWorkspaceSkillProgress:step=>captured.push(step)});
 vm.runInContext(extract('renderAgentTrace'),context);
 vm.runInContext(extract('applyBackgroundSkillProgress'),context);
 context.applyBackgroundSkillProgress({project_id:'p',items:[{id:'place',client_turn_id:'turn',
   skill:'memoir-place-journey',phase:'place',lane:'B',status:'skipped',reason:'no_place_cue'}]});
 assert.equal(captured[0].detail,'Memoir.trace.placeNoCue');
 const html=context.renderAgentTrace([
   {id:'collector',detail:'Reply generated',status:'completed'},captured[0]],'live');
 assert.match(html,/A · Reply generated/);
 assert.match(html,/B · memoir-place-journey/);
 assert.match(html,/Memoir.trace.placeNoCue/);
});
test('thinking and text-only steps precede the reply, with no inline photo cards', () => {
 const context=vm.createContext({state:{showThinkingSteps:true},CHATBOT_NAME:'Mira',escapeHtml:String,translate:key=>key,translateWith:(key,{count})=>`${count} steps`,formatText:String,cleanAssistantText:String});
 vm.runInContext(extract('renderAgentTrace'),context);
 vm.runInContext(extract('renderMessage'),context);
 const message={id:'m',role:'assistant',text:'',progressText:'Checking places…',streaming:true,traceMode:'live',trace:[{id:'reply',label:'Reply',status:'running'}],cues:[{title:'Photograph'}]};
 const waiting=context.renderMessage(message);
 assert.match(waiting,/class="message-thinking" role="status" >Memoir.story.thinkingCodex/);
 assert.ok(waiting.indexOf('message-thinking') < waiting.indexOf('message-trace'));
 assert.doesNotMatch(waiting,/message-progress|Checking places…/);
 assert.ok(waiting.indexOf('message-trace') < waiting.indexOf('class="message-text"'));
 assert.match(waiting,/class="message-text" aria-live="polite" hidden/);
 const reply=context.renderMessage({...message,text:'Hello',streaming:false});
 assert.match(reply,/class="message-thinking" role="status" hidden/);
 assert.doesNotMatch(reply,/photo-card|cue-section|<img/);
 assert.ok(reply.indexOf('message-trace') < reply.indexOf('class="message-text"'));
});
test('incoming text replaces thinking without a standalone progress row', () => {
 const text={innerHTML:'',hidden:true,setAttribute(name,value){this[name]=value;}};
 const thinking={hidden:false};
 const progress={textContent:'',hidden:true};
 const row={querySelector:selector=>({'.message-text':text,'.message-thinking':thinking,'.message-progress':progress}[selector] || null)};
 const context=vm.createContext({document:{querySelector:()=>row},$:()=>null,formatText:String,cleanAssistantText:String,renderAgentTrace:()=>'',conversationScroll:{following:()=>true,refresh:()=>{}}});
 vm.runInContext(extract('updateStreamingAssistantMessage'),context);
 context.updateStreamingAssistantMessage({id:'m',text:'Hello',streaming:true,progressText:'Preparing your reply'});
 assert.equal(text.innerHTML,'Hello');
 assert.equal(text.hidden,false);
 assert.equal(thinking.hidden,true);
 assert.equal(progress.textContent,'');
 assert.equal(progress.hidden,true);
});

test('assistant rendering hides legacy profile comments', () => {
 const context=vm.createContext({state:{showThinkingSteps:false},CHATBOT_NAME:'Mira',escapeHtml:String,translate:key=>key,formatText:value=>String(value)});
 for (const name of ['cleanAssistantText','renderAgentTrace','renderMessage']) vm.runInContext(extract(name),context);
 const html=context.renderMessage({id:'m',role:'assistant',text:'慧博，你好。 <!-- profile: {"who":"慧博"} -->',streaming:false});
 assert.match(html,/慧博，你好。/);
 assert.doesNotMatch(html,/profile:/);
});

test('Mira avatar appears only on the opening greeting', () => {
 const context=vm.createContext({state:{showThinkingSteps:false},CHATBOT_NAME:'Mira',escapeHtml:String,translate:key=>key,formatText:value=>String(value),currentUiLocale:()=> 'zh-CN'});
 for (const name of ['cleanAssistantText','renderAgentTrace','renderMessage']) vm.runInContext(extract(name),context);
 const opening=context.renderMessage({id:'opening',role:'assistant',productCopy:'opening',text:'你好，我是 Mira。',streaming:false});
 const later=context.renderMessage({id:'reply',role:'assistant',text:'请继续说说那段回忆。',streaming:false});
 assert.match(opening,/class="assistant-avatar"/);
 assert.match(opening,/mira_avatar_zh-CN\.png/);
 assert.match(opening,/assistant-opening/);
 assert.doesNotMatch(later,/assistant-avatar|mira_avatar/);
 assert.doesNotMatch(later,/assistant-opening/);
});

test('finished workspace checks appear last inside the collapsed thinking steps', async () => {
 let emitEvent;
 const context=vm.createContext({state:{showThinkingSteps:true,supabase:{accessToken:'test'},project:{id:'p'},chat:[]},CHATBOT_NAME:'Mira',escapeHtml:String,translate:key=>key,translateWith:(key,{count})=>`${count} steps`,formatText:String,cleanAssistantText:String,simulatedLoopTrace:()=>[],conversationLanguage:()=>undefined,nextAssistantMessageId:()=> 'm1',render:()=>{},updateStreamingAssistantMessage:()=>{},
 streamAgentTurn:async (text,onDelta,onEvent)=>{
   emitEvent=onEvent;
   await onEvent({type:'progress',data:{id:'workspace',detail:'Checking workspace',status:'running'}});
   await onEvent({type:'progress',data:{id:'place',detail:'Place skill finished',status:'completed'}});
   return {reply:'Hello',conversation_saved:true};
 }});
 context.refreshPrivateDraft = async () => {};
  context.refreshStageReadiness = async () => {};
 for (const name of ['agentTurn','renderAgentTrace','renderMessage']) vm.runInContext(extract(name),context);
 const result=await context.agentTurn('Hi');
 await emitEvent({type:'progress',data:{id:'workspace',detail:'Workspace checks completed',status:'completed'}});
 assert.deepEqual(Array.from(result.trace,step=>step.id),['place','workspace']);
 const html=context.renderMessage({...result.streamedMessage,text:'Hello',streaming:false});
 assert.doesNotMatch(html,/message-progress|class="agent-loop" open/);
 assert.ok(html.indexOf('Place skill finished') < html.indexOf('Workspace checks completed'));
 assert.ok(html.indexOf('Workspace checks completed') < html.indexOf('</details>'));
 assert.equal(html.split('Workspace checks completed').length-1,1);
});

test('thinking status stays visible through steps, then hides when the response begins', () => {
 const context=vm.createContext({state:{showThinkingSteps:true},CHATBOT_NAME:'Mira',escapeHtml:String,translate:key=>key,formatText:String,cleanAssistantText:String});
 for (const name of ['renderAgentTrace','renderMessage','updateStreamingAssistantMessage']) vm.runInContext(extract(name),context);
 const message={id:'m',role:'assistant',text:'',streaming:true,traceMode:'live',trace:[]};
 assert.match(context.renderMessage(message),/class="message-thinking" role="status" >/);
 message.trace=[{id:'context',label:'Conversation context',detail:'Loaded memory summaries',status:'completed'}, {id:'reply',label:'Reply',detail:'Preparing a streamed reply',status:'running'}];
 const routine=context.renderMessage(message);
 assert.match(routine,/class="message-thinking" role="status" >/);
 assert.doesNotMatch(routine,/Preparing a streamed reply|Conversation context|Loaded memory|<details/);
 message.trace.push({id:'language',detail:'Checking conversation language',status:'running'});
 const steps=context.renderMessage(message);
 assert.match(steps,/class="message-thinking" role="status" >/);
 assert.match(steps,/class="agent-loop" open/);
 assert.match(steps,/Checking conversation language/);
 assert.doesNotMatch(steps,/agent-loop-note|agent-loop-kind|<small>|Memoir.trace.status/);
 const text={hidden:true,innerHTML:'',setAttribute(name,value){this[name]=value;}};
 const thinking={hidden:false};
 let details;
 const trace={querySelector:()=>details,set innerHTML(html){details=html ? {open:html.includes('class="agent-loop" open')} : undefined;}};
 const row={querySelector:selector=>({'.message-text':text,'.message-thinking':thinking,'.message-trace':trace}[selector])};
 context.document={querySelector:()=>row};
 context.$=()=>null;
 context.conversationScroll={following:()=>true,refresh:()=>{}};
 context.updateStreamingAssistantMessage(message);
 assert.equal(thinking.hidden,false);
 assert.equal(details.open,true);
 message.text='Hello';
 context.updateStreamingAssistantMessage(message);
 assert.equal(details.open,false);
 assert.equal(text.hidden,false);
 message.trace.push({id:'place',detail:'Place skill finished',status:'completed'});
 context.updateStreamingAssistantMessage(message);
 assert.equal(details.open,false);
 // Explicitly reopening remains respected as more response text arrives.
 details.open=true;
 message.text+=' there';
 context.updateStreamingAssistantMessage(message);
 assert.equal(details.open,true);
 context.state.showThinkingSteps=false;
 assert.match(context.renderMessage({...message,text:''}),/class="message-thinking" role="status" >/);
});

test('real memory saves and named skill events remain visible, simulated traces do not', () => {
 const context=vm.createContext({state:{showThinkingSteps:true},escapeHtml:String,translate:key=>key});
 vm.runInContext(extract('renderAgentTrace'),context);
 const steps=[{id:'save',detail:'Conversation memory saved',status:'completed'},
  {id:'place',skill:'memoir-place-journey',detail:'Validating the place',status:'triggered'}];
 const html=context.renderAgentTrace(steps,'live');
 assert.match(html,/Conversation memory saved/);
 assert.match(html,/memoir-place-journey · Memoir.trace.status.triggered/);
 assert.equal(context.renderAgentTrace(steps,'simulated'),'');
});

test('completed skill progress survives saving and restoring the local chat', () => {
 const trace=[{id:'photos:p',kind:'skill',skill:'memoir-place-photo-research',status:'completed',detail:'悉尼'}];
 let saved='';
 const state={project:{id:'p'},chat:[{id:'assistant-message-1',role:'assistant',text:'Hello',trace,traceMode:'live'}]};
 const context=vm.createContext({state,CHAT_HISTORY_STORAGE_PREFIX:'chat:',assistantMessageSequence:0,
   sessionStorage:{setItem:(key,value)=>{saved=value;},getItem:()=>saved},cleanAssistantText:text=>text,
 });
 for(const name of ['chatHistoryStorageKey','readBrowserValue','saveBrowserValue','persistChatHistory','restoreChatHistory']) vm.runInContext(extract(name),context);
 context.persistChatHistory();
 const restored=context.restoreChatHistory('p');
 assert.deepEqual(JSON.parse(JSON.stringify(restored[0].trace)),trace);
 assert.equal(restored[0].traceMode,'live');
});

test('skill calls are visible even when their IDs overlap routine progress', () => {
 const context=vm.createContext({state:{showThinkingSteps:true},escapeHtml:String,translate:key=>key});
 vm.runInContext(extract('renderAgentTrace'),context);
 for(const id of ['context','reply','workspace']) {
  assert.match(context.renderAgentTrace([{id,skill:'memoir-place-journey',status:'running'}],'live'),
    /memoir-place-journey/);
 }
});

test('thinking steps hide private question candidates including legacy traces', () => {
 const context=vm.createContext({escapeHtml,state:{showThinkingSteps:true},CHATBOT_NAME:'Mira',translate:key=>key==='Memoir.trace.selectedQuestion'?'Selected':key,formatText:String,cleanAssistantText:String});
 for (const name of ['renderAgentTrace','renderMessage']) vm.runInContext(extract(name),context);
 const pool={chosen_id:'chosen',candidates:[
  {id:'chosen',question:'Where did you play?',bridge:''},
  {id:'later',question:'Who was with you? <script>alert(1)</script>',bridge:'You also mentioned the garden.'}]};
 const trace=[{id:'collector-call',status:'completed',detail:'LLM call · Reply and question pool generated'},
  {id:'tool-1',status:'completed',detail:'read_file · Completed'},
  {id:'save',status:'completed',detail:'Conversation memory saved'},
  {id:'question-pool',status:'completed',detail:'Generated question pool · 2 candidates',question_pool:pool}];
 const html=context.renderMessage({id:'m',role:'assistant',text:'Where did you play?',trace,traceMode:'live'});
 const thinking=html.slice(html.indexOf('<details'),html.indexOf('</details>'));
 assert.doesNotMatch(thinking,/class="agent-question-pool"/);
 assert.match(thinking,/LLM call · Reply and question pool generated/);
 assert.match(thinking,/read_file · Completed/);
 assert.match(thinking,/Conversation memory saved/);
 assert.doesNotMatch(thinking,/data-candidate-id|You also mentioned the garden|Who was with you/);
 assert.doesNotMatch(html,/<script>/);
 assert.doesNotMatch(html.slice(html.indexOf('class="message-text"')),/Who was with you/);
 assert.doesNotMatch(html,/class="agent-loop" open/);
 context.state.showThinkingSteps=false;
 assert.doesNotMatch(context.renderMessage({role:'assistant',text:'Where did you play?',trace,traceMode:'live'}),/Who was with you|agent-question-pool/);
});

test('private question candidates are excluded from local trace persistence', () => {
 const trace=[{id:'question-pool',question_pool:{chosen_id:'q1',candidates:[{id:'q1',question:'Where did you play?',bridge:''}]},status:'completed'}];
 let saved='';
 const context=vm.createContext({state:{project:{id:'p'},chat:[{id:'m',role:'assistant',text:'Where did you play?',trace,traceMode:'live'}]},CHAT_HISTORY_STORAGE_PREFIX:'chat:',assistantMessageSequence:0,
  sessionStorage:{setItem:(key,value)=>{saved=value;},getItem:()=>saved},cleanAssistantText:text=>text});
 for(const name of ['chatHistoryStorageKey','readBrowserValue','saveBrowserValue','persistChatHistory','restoreChatHistory']) vm.runInContext(extract(name),context);
 context.persistChatHistory();
 assert.deepEqual(JSON.parse(JSON.stringify(context.restoreChatHistory('p')[0].trace)),[{id:'question-pool',status:'completed'}]);
});
