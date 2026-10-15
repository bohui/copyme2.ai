import { readMemoirClientSource } from './helpers/memoir-source.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
const source = readMemoirClientSource();
function setup() {
  const message = {role:'assistant', clientTurnId:'turn-five', text:'A fast saved reply.', streaming:false, trace:[]};
  const state = {chat:[message], backgroundDraftTurn:'turn-five', project:{id:'project'}, supabase:{accessToken:'test'}, loading:false,
    showThinkingSteps:true, showDraftUpdates:true, privateDraftRequest:1};
  let updates=0, renders=0;
  const context=vm.createContext({state, translate:String, updateStreamingAssistantMessage(){updates++;}, persistChatHistory(){},
    clearTimeout(){},setTimeout(){return 1;},captureProjectScope:()=>({id:'project'}),isCurrentProjectScope:s=>s.id===state.project.id,
    profile:()=>({preferred_language:'en-AU'}),currentUiLocale:()=> 'en-AU',currentSectionRework:()=>null,render(){renders++;},
    storyApi:async()=>({snapshot_id:'root',root_digest:'digest',updating:true,status:'pending',background_progress:{state:'running',phase:'summarizing'}})});
  for(const name of ['updateBackgroundComposerProgress','applyPrivateDraftUpdate']) {
    const match=source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`));
    assert.ok(match);vm.runInContext(match[0],context);
  }
  return {context,state,message,updates:()=>updates,renders:()=>renders};
}
test('background thinking steps continue after the reply finishes without changing its text',()=>{
  const s=setup();
  for(const phase of ['summarizing','drafting','reviewing']) s.context.updateBackgroundComposerProgress({background_progress:{state:'running',phase}});
  assert.equal(s.message.streaming,false);assert.equal(s.message.text,'A fast saved reply.');
  assert.deepEqual(Array.from(s.message.trace,step=>step.status),['completed','completed','running']);
  s.context.updateBackgroundComposerProgress({background_progress:{state:'finished'}});
  assert.ok(s.message.trace.every(step=>step.status==='completed'));
});
test('a streamed draft update cannot rerender or block an active streaming reply',async()=>{
  const s=setup();s.state.loading=true;s.message.streaming=true;
  await s.context.applyPrivateDraftUpdate(await s.context.storyApi(),{id:'project'},1);
  assert.equal(s.renders(),0);assert.equal(s.updates(),1);assert.equal(s.state.loading,true);
  assert.equal(s.message.text,'A fast saved reply.');
});
test('a response from an older project cannot update thinking steps',async()=>{
  const s=setup();s.context.storyApi=async()=>{s.state.project.id='other';return {updating:true,background_progress:{state:'running',phase:'drafting'}};};
  await s.context.applyPrivateDraftUpdate(await s.context.storyApi(),{id:'project'},1);
  assert.equal(s.updates(),0);assert.equal(s.message.trace.length,0);
});

test('background thinking steps depend only on the thinking-step flag',()=>{
  const s=setup();s.state.showDraftUpdates=false;
  s.context.updateBackgroundComposerProgress({background_progress:{state:'running',phase:'drafting'}});
  assert.equal(s.updates(),1);
  s.state.showThinkingSteps=false;
  s.context.updateBackgroundComposerProgress({background_progress:{state:'running',phase:'reviewing'}});
  assert.equal(s.updates(),1);
});
