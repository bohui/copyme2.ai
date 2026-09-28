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
 const context=vm.createContext({fetch:async()=>({ok:true,status:200,body}),state:{supabase:{accessToken:'test'},project:{id:'p'}},memoirApiPath:p=>p,readCookie:()=>'',TextDecoder,conversationLocale:()=> 'en-AU'});
 vm.runInContext(extract('streamAgentTurn'),context);
 await context.streamAgentTurn('Hi',async text=>seen.push(text),async event=>seen.push(event));
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(seen[0].type,'progress');
 assert.equal(seen[1],'Hello');
 assert.equal(seen[2].data.skill,'memoir-place-journey');
});
test('fast saved response retains live trace and later triggered skills', async () => {
 let emitEvent;
 const context=vm.createContext({state:{supabase:{accessToken:'test'},project:{id:'p'},chat:[]},conversationLocale:()=> 'en-AU', simulatedLoopTrace:()=>[{label:'fake'}], nextAssistantMessageId:()=> 'm1', render:()=>{}, updateStreamingAssistantMessage:()=>{},waitForAssistantPaint:async()=>{},
 streamAgentTurn:async (text,onDelta,onEvent)=>{
   emitEvent=onEvent;
   await onEvent({type:'progress',data:{id:'context',label:'Context',status:'running'}});
   await onDelta('Hello');
   await onEvent({type:'progress',data:{id:'context',label:'Context',status:'completed'}});
   return {reply:'Hello',conversation_saved:true};
 }});
 vm.runInContext(extract('agentTurn'),context);
 const result=await context.agentTurn('Hi');
 assert.equal(result.traceMode,'live');
 assert.equal(result.trace.length,1);
 assert.equal(result.trace[0].status,'completed');
 await emitEvent({type:'progress',data:{id:'place',skill:'memoir-place-journey',status:'triggered'}});
 assert.equal(result.trace.length,2);
 assert.equal(result.streamedMessage.trace[1].skill,'memoir-place-journey');
});
test('live trace renders while reply text is still streaming', () => {
 const context=vm.createContext({state:{showThinkingSteps:true},CHATBOT_NAME:'Mira',escapeHtml:String,translate:key=>key,translateWith:(key,{count})=>`${count} steps`,formatText:String});
 vm.runInContext(extract('renderAgentTrace'),context);
 vm.runInContext(extract('renderMessage'),context);
 const html=context.renderMessage({id:'m',role:'assistant',text:'Hello',streaming:true,traceMode:'live',trace:[{id:'reply',label:'Reply',status:'running'}]});
 assert.match(html,/class="message-trace"/);
 assert.match(html,/class="agent-loop" open/);
 assert.match(html,/data-step-status="running"/);
});
