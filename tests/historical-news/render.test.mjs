import test from 'node:test';
import assert from 'node:assert/strict';
import {historicalContextMarkup, historicalContext} from '../../apps/web/client/memoir/historical-news.mjs';
const clue={id:'news-0123456789abcdef01234567',title:'Community fair',summary:'A fair opened.',event_start:1970,event_end:1970,
 source_url:'https://archive.example/fair',source_title:'Original archive title',publisher:'Library'};
test('citation, event date and per-clue skip render in both languages without changing source names',()=>{
 for(const locale of ['en-AU','zh-CN']){
  const html=historicalContextMarkup(clue,locale);
  assert.match(html,/1970/);assert.match(html,/Original archive title/);
  assert.match(html,/rel="noopener noreferrer"/);assert.match(html,/data-news-reject/);
  assert.doesNotMatch(html,/data-news-enable|data-news-disable/);
 }
});
test('private fields never persist, unsafe links fail closed and text is escaped',()=>{
 assert.equal(historicalContext({...clue,source_url:'javascript:alert(1)'}),null);
 assert.equal(historicalContext({...clue,source_url:'https://user:secret@example.org/'}),null);
 assert.equal(historicalContext({...clue,receipt:{secret:'x'},relevance:{private:'x'}}).receipt,undefined);
 assert.match(historicalContextMarkup({...clue,title:'<script>x</script>'},'en-AU'),/&lt;script&gt;/);
});
test('saved public snapshot replays exactly',()=>{
 const saved=historicalContext(clue);
 assert.equal(historicalContextMarkup(JSON.parse(JSON.stringify(saved)),'zh-CN'),historicalContextMarkup(clue,'zh-CN'));
});

// Exercise the actual client integration, not a parallel renderer implementation.
import {readMemoirClientSource} from '../js/helpers/memoir-source.mjs';
import vm from 'node:vm';
const source=readMemoirClientSource();
function install(context,names){
 for(const name of names) vm.runInContext(source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0],context);
}
test('production local history retains only the public historical snapshot',()=>{
 const data=new Map();
 const state={project:{id:'project'},projectPrincipalId:'owner',supabase:{user:{id:'owner'}},chat:[
  {role:'assistant',text:'Optional clue?',historicalContext:{...clue,relevance:{private:'never save'}}}]};
 const storage={getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v)};
 const context=vm.createContext({state,CHAT_HISTORY_STORAGE_PREFIX:'chat:',assistantMessageSequence:0,
  localStorage:storage,sessionStorage:storage,cleanAssistantText:x=>x,historicalContext});
 install(context,['chatHistoryStorageKey','savedProjectStorageKey','readBrowserValues','readBrowserValue',
  'mergeChatHistoryCopies','saveBrowserValue','persistChatHistory','restoreChatHistory']);
 context.persistChatHistory();
 const restored=context.restoreChatHistory('project');
 assert.equal(restored.length,1);assert.equal(restored[0].historicalContext.id,clue.id);
 assert.equal(restored[0].historicalContext.relevance,undefined);
 assert.match(historicalContextMarkup(restored[0].historicalContext,'en-AU'),/Original archive title/);
});
test('production completed streaming reply carries verified historical context',async()=>{
 const state={supabase:{accessToken:'fixture'},project:{id:'project'},chat:[]};
 const context=vm.createContext({state,historicalContext,conversationLanguage:()=> 'en-AU',simulatedLoopTrace:()=>[],
  nextAssistantMessageId:()=> 'message',render(){},updateStreamingAssistantMessage(){},refreshPrivateDraft:async()=>{},refreshStageReadiness:async()=>{},
  toast:message=>assert.fail(message),
  streamAgentTurn:async()=>({reply:'Optional clue?',conversation_saved:true,historical_context:{...clue,receipt:{private:'omit'}}})});
 install(context,['captureProjectScope','isCurrentProjectScope','currentWorkspaceMemoryFocus','workspaceTurnFocus',
  'markWorkspaceFocusStarted','readBrowserValues','mergeChatHistoryCopies','agentTurn']);
 const reply=await context.agentTurn('My own memory');
 assert.equal(reply.historicalContext.id,clue.id);assert.equal(reply.streamedMessage.historicalContext.id,clue.id);
 assert.equal(reply.historicalContext.receipt,undefined);assert.equal(reply.streamedMessage.streaming,false);
});
