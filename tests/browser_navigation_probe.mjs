import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const fixture = JSON.parse(fs.readFileSync(0, 'utf8'));
// Execute unchanged client functions; only browser transport and unrelated UI are controlled.
const source = fs.readFileSync(new URL('../apps/web/client/memoir/client.js', import.meta.url), 'utf8');
const extract = name => source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0];
const durable = new Map(), tab = new Map(), writes = [];
const app = {innerHTML:''}, events = new Map();
const state = {project:fixture.project, projectPrincipalId:fixture.owner,
 supabase:{user:{id:fixture.owner,is_anonymous:true},accessToken:'fixture-guest'},
 chat:[], chapters:[], freshAnonymousSession:false, chatHistoryCollapsed:true,
 conversationPhase:{ensure(){}}, navigationGeneration:0};
const buttons = () => [...app.innerHTML.matchAll(/<button\b([^>]+)>/g)].map(([,attrs]) => ({
 action:attrs.match(/data-action="([^"]+)"/)?.[1], mode:attrs.match(/data-mode="([^"]+)"/)?.[1]}));
const node = key => ({dataset:{mode:key},addEventListener:(_event,fn)=>events.set(key,fn),focus(){}});
const context = vm.createContext({state, MEMOIR_ROUTES:{home:'/memoir',interview:'/memoir/interview'},
 CHAT_HISTORY_STORAGE_PREFIX:'memory-spark-chat-history:', assistantMessageSequence:0,
 localStorage:{getItem:k=>durable.get(k)??null,setItem:(k,v)=>{durable.set(k,v);writes.push(v)},removeItem:k=>durable.delete(k)},
 sessionStorage:{getItem:k=>tab.get(k)??null,setItem:(k,v)=>tab.set(k,v)},
 $:selector=>selector==='#app'?app:selector.includes('open-memoir')?node('begin'):
 selector.includes('toggle-chat-history')?node('toggle'):null,
 document:{querySelectorAll:selector=>selector.includes('start-story')?buttons().filter(b=>b.action==='start-story').map(b=>node(b.mode)):[]},
 escapeHtml:String, translate:String,translateWith:String,cleanAssistantText:String,
 composingWorkspaceActive:()=>false,freeRecallFinished:()=>false,workspaceIsVisible:()=>false,workspaceHasContent:()=>false,
 profileMenu:()=>'',placeJourneySurface:()=>'',recallPackagePrompt:()=>'',chatComposer:()=>'<textarea id="chat-input"></textarea>',
 privateDraftPreview:()=>'',activeWorkspaceTab(){},bindViewActions(){},bindProfileMenu(){},
 disposeCesiumPlaceJourney(){},initCesiumPlaceJourney(){},initFamilyVisualizations(){},bindPhotoPagination(){},bindPhotoMemoryActions(){},resizeChatInput(){},
 authReminder:{mount(){}},mapPhotoAlbums:{sync(){}},currentUiLocale:()=> 'zh-CN',memoirApiPath:x=>x,
 conversationMessage:()=> 'Fixture opening', openingMessages:['Fixture opening'],
 renderMessage:m=>`<article class="assistant-message ${m.streaming?'message-streaming':''}">${m.text}</article>`,
 storyApi:async path=>{assert.equal(path,`/v1/user/projects/${fixture.project.id}/history?limit=100`);return fixture.history;},
 historicalContext:x=>x,
 nextAssistantMessageId:()=> 'assistant-message-1', ASSISTANT_STREAM_CHUNK_SIZE:5,
 waitForAssistantStream:async()=>{},updateStreamingAssistantMessage(){},
});
for(const name of ['captureProjectScope','isCurrentProjectScope','isFreshAnonymousSession','chatHistoryStorageKey',
 'readBrowserValues','mergeChatHistoryCopies','saveBrowserValue','persistChatHistory','originalConversationText',
 'normalizeHistoryOpening','hydrateAccountHistory','renderStory','renderPlatformLanding','renderMemoirLanding','streamAssistantMessage'])
 vm.runInContext(extract(name),context);
context.render=()=>context.renderStory();
const snapshots=[];
const take=label=>snapshots.push({label,html:app.innerHTML,cache:durable.get(context.chatHistoryStorageKey())??null});
context.renderStory();take('early-input-before-history');
state.chat=[{role:'user',text:'Synthetic private garden memory.'},{role:'assistant',text:'Synthetic garden reply.'}];
await context.hydrateAccountHistory();context.renderStory();take('authorized-history-collapsed');
vm.runInContext(source.match(/\$\("\[data-action='toggle-chat-history'\]"\)\?\.addEventListener\("click", \(\) => \{[^]*?\n  \}\);/)[0],context);
events.get('toggle')();take('history-expanded');
context.startStory=mode=>{events.set('selected-mode',mode)};
context.renderPlatformLanding();const platform=buttons();events.get('begin')();const beginMode=events.get('selected-mode');
context.renderMemoirLanding();const memoir=buttons();events.get('family')();const familyMode=events.get('selected-mode');
state.project={id:'project-b'};state.chat=[];state.chatHistoryCollapsed=true;
const key=context.chatHistoryStorageKey();const cacheBefore=durable.get(key)??null;
const startup=[];context.render=()=>{context.renderStory();startup.push({html:app.innerHTML,cache:durable.get(key)??null,streaming:state.chat.at(-1)?.streaming??false});};
await context.streamAssistantMessage('Welcome back to B.');
assert.equal(cacheBefore,null);assert.equal(startup[0].cache,'[]');assert.equal(startup.at(-1).streaming,false);
// page.goto('/memoir') adds an entry; the real family-start code replaces only it.
const stack = [`/memoir/interview/${fixture.project.id}`, '/'];
stack.push('/memoir');
context.window = {history:{
 pushState:(_state,_title,path)=>stack.push(path),
 replaceState:(_state,_title,path)=>{stack[stack.length-1]=path;},
}};
context.currentPath=()=>stack.at(-1);
Object.assign(context, {PLACE_JOURNEY_PROJECT_STORAGE_KEY:'places', stopVoiceMode(){},
 conversationLanguage:()=> 'zh-CN', refreshProject:async()=>{}, refreshFamilyEntitlement:async()=>{},
 startCodexConversation:async()=>{}, setLoading(){}, toast:error=>assert.fail(error),
 api:async(path, options)=>{
  if(path==='/v1/projects') { assert.equal(JSON.parse(options.body).mode,'family'); return fixture.familyProject; }
  assert.equal(path,`/v1/projects/${fixture.familyProject.id}/consents`);return {};
 }});
for(const name of ['invalidateProjectNavigation','navigateTo','savedProjectStorageKey','readBrowserValue',
 'rememberProject','startMemoirStory','startStory']) vm.runInContext(extract(name),context);
context.render=()=>context.renderStory();
context.renderMemoirLanding();
await events.get('family')();
assert.equal(state.project.id,fixture.familyProject.id);
assert.deepEqual(stack,[`/memoir/interview/${fixture.project.id}`,'/',`/memoir/interview/${fixture.familyProject.id}`]);
console.log(JSON.stringify({status:fixture.status,history:fixture.history,snapshots,platform,beginMode,memoir,familyMode,cacheBefore,startup,stack}));
