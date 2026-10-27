import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {readMemoirClientSource} from './memoir-source.mjs';

const response=JSON.parse(readFileSync(0,'utf8'));
const entry={place:'Chengde',research_period:'1980s'};
const events=[];
const context=vm.createContext({
  state:{project:{id:'project'},showThinkingSteps:true},URLSearchParams,workspaceUpdateQueue:Promise.resolve(),
  document:{querySelector:()=>null},profile:()=>({memory_places:[entry]}),
  api:async()=>response,placeHistoryKey:place=>place.place,translate:key=>key,render() {},
  persistChatHistory() {},
});
const source=readMemoirClientSource();
for (const name of ['captureProjectScope','isCurrentProjectScope','recordWorkspaceSkillProgress',
  'photoSearchPeriod','placePhotoCenter','photoRequestKey','loadPlacePictures']) {
  const declaration=source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`));
  assert.ok(declaration,`Missing production function ${name}`);
  vm.runInContext(declaration[0],context);
}
await context.loadPlacePictures(entry,'project',{onProgress:step=>events.push(step)});
assert.equal(events.at(-1).status,'failed');
assert.match(events.at(-1).detail,/google: quota_exhausted; commons: robots_denied/);
assert.equal(entry.photo_search_complete,undefined,'Provider failure must never become a saved no-match');
assert.equal(Array.from(context.state.photoRequests.values())[0].error,true);
