import {readMemoirClientSource} from './helpers/memoir-source.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
const source=readMemoirClientSource();
function harness() {
  const state={showThinkingSteps:true,project:{id:'p'},chat:[
    {role:'assistant',clientTurnId:'first',text:'Saved first reply.'},
    {role:'assistant',clientTurnId:'later',text:'A later reply.'}]};
  let saves=0;
  const context=vm.createContext({state,translate:String,persistChatHistory(){saves++;},updateStreamingAssistantMessage(){}});
  for (const name of ['recordWorkspaceSkillProgress','applyBackgroundSkillProgress'])
    vm.runInContext(source.match(new RegExp(`function ${name}\\([^]*?\\n\\}`))[0],context);
  return {state,context,saves:()=>saves};
}
test('late persisted work creates a trace on its real turn and replay upserts',()=>{
  const h=harness();
  const item={id:'job-page-phase',skill:'memoir-author-timeline',phase:'extract',lane:'B',execution:'model',
    client_turn_id:'first',coverage_start:1,coverage_end:5,status:'running'};
  h.context.applyBackgroundSkillProgress({project_id:'p',items:[item]});
  h.context.applyBackgroundSkillProgress({project_id:'p',items:[{...item,status:'saved'}]});
  assert.equal(h.state.chat[0].trace.length,1);
  assert.equal(h.state.chat[0].trace[0].status,'saved');
  assert.equal(h.state.chat[0].trace[0].coverage_end,5);
  assert.equal(h.state.chat[1].trace,undefined);
  assert.equal(h.saves(),2);
});
test('finished queues disappear without manufacturing phase completions',()=>{
  const h=harness();
  h.context.applyBackgroundSkillProgress({project_id:'p',items:[{id:'queue:lane',phase:'queue',client_turn_id:'first',status:'queued'}]});
  h.context.applyBackgroundSkillProgress({project_id:'p',items:[{id:'extract',phase:'extract',client_turn_id:'first',status:'running'}]});
  assert.deepEqual(Array.from(h.state.chat[0].trace,item=>item.id),['extract']);
});
test('foreign project, missing correlation and thinking-off updates never attach to a newer reply',()=>{
  const h=harness();
  h.context.applyBackgroundSkillProgress({project_id:'foreign',items:[{id:'x',client_turn_id:'first'}]});
  h.context.applyBackgroundSkillProgress({project_id:'p',items:[{id:'uncorrelated'}]});
  h.state.showThinkingSteps=false;
  h.context.applyBackgroundSkillProgress({project_id:'p',items:[{id:'x',client_turn_id:'first'}]});
  assert.equal(h.saves(),0);
  assert.ok(h.state.chat.every(item=>!item.trace));
});
