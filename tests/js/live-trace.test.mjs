import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../../apps/web/client/memoir/client.js',import.meta.url),'utf8');
const extract = name => source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0];
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
 const text={innerHTML:'',hidden:true};
 const thinking={hidden:false};
 const progress={textContent:'',hidden:true};
 const row={querySelector:selector=>({'.message-text':text,'.message-thinking':thinking,'.message-progress':progress}[selector] || null)};
 const context=vm.createContext({document:{querySelector:()=>row},$:()=>null,formatText:String,cleanAssistantText:String,renderAgentTrace:()=>''});
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

test('finished workspace checks appear last inside the collapsed thinking steps', async () => {
 let emitEvent;
 const context=vm.createContext({state:{showThinkingSteps:true,supabase:{accessToken:'test'},project:{id:'p'},chat:[]},CHATBOT_NAME:'Mira',escapeHtml:String,translate:key=>key,translateWith:(key,{count})=>`${count} steps`,formatText:String,cleanAssistantText:String,simulatedLoopTrace:()=>[],conversationLanguage:()=>undefined,nextAssistantMessageId:()=> 'm1',render:()=>{},updateStreamingAssistantMessage:()=>{},
 streamAgentTurn:async (text,onDelta,onEvent)=>{
   emitEvent=onEvent;
   await onEvent({type:'progress',data:{id:'workspace',detail:'Checking workspace',status:'running'}});
   await onEvent({type:'progress',data:{id:'place',detail:'Place skill finished',status:'completed'}});
   return {reply:'Hello',conversation_saved:true};
 }});
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
 const text={hidden:true,innerHTML:''};
 const thinking={hidden:false};
 let details;
 const trace={querySelector:()=>details,set innerHTML(html){details=html ? {open:html.includes('class="agent-loop" open')} : undefined;}};
 const row={querySelector:selector=>({'.message-text':text,'.message-thinking':thinking,'.message-trace':trace}[selector])};
 context.document={querySelector:()=>row};
 context.$=()=>null;
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
