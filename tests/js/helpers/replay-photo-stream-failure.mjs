import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {readMemoirClientSource} from './memoir-source.mjs';

const frame=JSON.parse(readFileSync(0,'utf8'));
assert.equal(frame.skill_progress.status,'running');
const entry={place:'Chengde',research_period:'1980s'};
const events=[];
const context=vm.createContext({
  state:{project:{id:'project'},showThinkingSteps:true,chat:[{role:'assistant',clientTurnId:'latest'}]},
  URLSearchParams,workspaceUpdateQueue:Promise.resolve(),document:{querySelector:()=>null},
  profile:()=>({memory_places:[entry]}),placeHistoryKey:place=>place.place,
  translate:key=>key,render(){},persistChatHistory(){},
  api:async(_url,options)=>{
    await options.onPhotoPage(frame);
    throw Error('Synthetic connection loss after the initial API frame');
  },
});
const source=readMemoirClientSource();
for (const name of ['captureProjectScope','isCurrentProjectScope','recordWorkspaceSkillProgress',
  'photoSearchPeriod','placePhotoCenter','photoRequestKey','loadPlacePictures'])
  vm.runInContext(source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0],context);
await context.loadPlacePictures(entry,'project',{onProgress:step=>events.push(step)});
const last=events.at(-1);
assert.equal(last.id,frame.skill_progress.id);
assert.equal(last.status,'failed');
assert.equal(last.client_turn_id,'latest');
assert.ok(last.started_at && last.finished_at);
