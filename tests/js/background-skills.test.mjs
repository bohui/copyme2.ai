import {readFileSync} from 'node:fs';
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
test('one combined background batch appears only on its final covered reply',()=>{
  const h=harness();
  const started_at='2026-10-30T00:01:02.000Z', finished_at='2026-10-30T00:01:04.000Z';
  const items=['earlier-source','later-source'].map(id=>({id,batch_id:'combined',phase:'extract',
    skill:'memoir-author-timeline',lane:'B',execution:'model',client_turn_id:'later',
    coverage_start:1,coverage_end:2,status:'saved',started_at,finished_at}));
  h.context.applyBackgroundSkillProgress({project_id:'p',items});
  assert.equal(h.state.chat[0].trace,undefined);
  assert.equal(h.state.chat[1].trace.length,2);
  assert.ok(h.state.chat[1].trace.every(item=>item.started_at===started_at && item.finished_at===finished_at));
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
test('unattributed workspace lookups are scoped separately instead of assigned to a conversation',()=>{
  const h=harness();
  h.context.applyBackgroundSkillProgress({project_id:'p',items:[{id:'lookup',skill:'memoir-place-photo-research',phase:'photos',status:'cached'}]});
  assert.equal(h.state.workspaceSkillProgress.project_id,'p');
  assert.equal(h.state.workspaceSkillProgress.items[0].status,'cached');
  assert.ok(h.state.chat.every(item=>!item.trace));
});
test('the server work identity replaces a temporary browser trace and readback upserts it',()=>{
  const h=harness();
  h.context.recordWorkspaceSkillProgress({id:'temporary',client_turn_id:'first',status:'running'});
  h.context.recordWorkspaceSkillProgress({id:'server-job',replaces_id:'temporary',client_turn_id:'first',status:'completed'});
  h.context.applyBackgroundSkillProgress({project_id:'p',items:[{id:'server-job',client_turn_id:'first',status:'completed'}]});
  assert.equal(h.state.chat[0].trace.length,1);
  assert.equal(h.state.chat[0].trace[0].id,'server-job');
});

for (const locale of ['en-AU','zh-CN']) {
  test(`guidance model progress appears on its original turn with a localized operation (${locale})`,()=>{
    const messages=JSON.parse(readFileSync(new URL(`../../apps/web/messages/${locale}.json`,import.meta.url),'utf8'));
    const h=harness();
    h.context.translate=key=>key.split('.').reduce((value,part)=>value?.[part],messages) ?? key;
    const item={id:'guidance-model',skill:'memoir-interview-guidance',phase:'guidance',lane:'B',execution:'model',
      client_turn_id:'first',status:'running',model_invoked:true};
    h.context.applyBackgroundSkillProgress({project_id:'p',items:[item]});
    h.context.applyBackgroundSkillProgress({project_id:'p',items:[{...item,status:'saved'}]});
    assert.equal(h.state.chat[0].trace.length,1);
    const step=h.state.chat[0].trace[0];
    assert.equal(step.label,'memoir-interview-guidance');
    assert.equal(step.lane,'B');
    assert.equal(step.status,'saved');
    assert.equal(typeof messages.Memoir.trace.operation.guidance,'string');
    assert.equal(step.detail,messages.Memoir.trace.operation.guidance);
    assert.equal(h.state.chat[1].trace,undefined);
  });
}
