import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createFamilyWorkspace} from '../../../apps/web/client/memoir/family-workspace.mjs';
import {memoryEventTiming,memoryEventTimingMarkup} from '../../../apps/web/client/memoir/map-memory-journey.mjs';
import {translateWith} from '../../../apps/web/client/i18n.js';

const {project_id,feeds}=JSON.parse(readFileSync(0,'utf8'));
const state={project:{id:project_id,profile:{birth_year:1983}},supabase:{accessToken:'fixture'},
  familyFeaturesEnabled:false,timeline:[]};
let current=0;
const family=createFamilyWorkspace({state,render(){},captureProjectScope:()=>project_id,isCurrentProjectScope:()=>true,
  storyApi:async path=>{
    assert.ok(path.startsWith('/v1/story/map-events?'));
    return structuredClone(feeds[current]);
  }});
for (const confidence of [.4,.9,1]) {
  await family.refreshFamilyContext();
  assert.equal(state.timeline.length,1,'A follow-up must update the existing timeline row');
  const event=state.timeline[0];
  assert.equal(event.id,feeds[0].events[0].id);
  assert.equal(event.yearConfidenceScore,confidence);
  const html=memoryEventTimingMarkup({event,...memoryEventTiming(event,state.project.profile)},
    (key,values)=>translateWith(`Memoir.workspace.${key}`,values));
  assert.match(html,new RegExp(`${current===2 ? 'Date confidence' : 'Estimated · confidence'} ${confidence*100}%`));
  if (current===2) assert.match(html,/2012/);
  current++;
}
