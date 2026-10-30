import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readMemoirClientSource} from './memoir-source.mjs';
import {escapeHtml} from '../../../apps/web/client/memoir/dom.mjs';

const {progress,turns}=JSON.parse(readFileSync(0,'utf8'));
const source=readMemoirClientSource();
for (const locale of ['en-AU','zh-CN']) {
  const messages=JSON.parse(readFileSync(new URL(`../../../apps/web/messages/${locale}.json`,import.meta.url),'utf8'));
  const state={showThinkingSteps:true,project:{id:progress.project_id},
    chat:turns.map(clientTurnId=>({role:'assistant',clientTurnId,text:'Saved reply'}))};
  const context=vm.createContext({state,escapeHtml,currentUiLocale:()=>locale,
    translate:key=>key.split('.').reduce((value,part)=>value?.[part],messages),
    persistChatHistory(){},updateStreamingAssistantMessage(){}});
  for (const name of ['recordWorkspaceSkillProgress','applyBackgroundSkillProgress','renderAgentTrace'])
    vm.runInContext(source.match(new RegExp(`function ${name}\\([^]*?\\n\\}`))[0],context);
  context.applyBackgroundSkillProgress(progress);
  context.applyBackgroundSkillProgress(progress);
  assert.equal(state.chat[1].trace,undefined);
  const final=state.chat[2];
  const grouped=final.trace.filter(step=>step.batch_id && step.coverage_start===2 && step.coverage_end===3);
  assert.equal(grouped.length,2);
  assert.ok(final.trace.some(step=>step.skill==='memoir-place-groups'));
  const html=context.renderAgentTrace(final.trace,'live');
  assert.ok(html.includes(messages.Memoir.trace.groupedConversations));
  for (const step of grouped) {
    assert.ok(html.includes(`datetime="${new Date(step.started_at).toISOString()}"`));
    assert.ok(html.includes(`datetime="${new Date(step.finished_at).toISOString()}"`));
  }
}
