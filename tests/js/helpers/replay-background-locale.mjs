import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createFamilyWorkspace} from '../../../apps/web/client/memoir/family-workspace.mjs';
import {buildMapMemoryJourney,memoryEventCardMarkup} from '../../../apps/web/client/memoir/map-memory-journey.mjs';
import {translateWith} from '../../../apps/web/client/i18n.js';

const {project_id,feed,timeline,profile,locale,title,description}=JSON.parse(readFileSync(0,'utf8'));
globalThis.document={documentElement:{lang:locale}};
const state={project:{id:project_id,profile},supabase:{accessToken:'fixture'},familyFeaturesEnabled:false,timeline:[]};
const family=createFamilyWorkspace({state,render(){},captureProjectScope:()=>project_id,isCurrentProjectScope:()=>true,
  lifeStageText:stage=>stage,referencesWorkspace:()=>'',
  storyApi:async path=>{
    if (path.startsWith('/v1/story/events?')) return structuredClone(timeline);
    assert.ok(path.startsWith('/v1/story/atlas-events?'));
    return structuredClone(feed);
  }});
await family.refreshFamilyContext();
assert.deepEqual(state.timeline.map(event=>event.title),[title]);
const journey=buildMapMemoryJourney(state.timeline,[],profile);
const [card]=[...journey.nodes,...journey.unlocated];
const html=memoryEventCardMarkup(card,{t:(key,values)=>translateWith(`Memoir.workspace.${key}`,values),lifeStageText:stage=>stage});
assert.ok(html.includes(`<strong class="map-memory-summary"><span data-memory-text>${title}</span></strong>`));
assert.ok(html.includes(locale==='zh-CN' ? '继续聊这段回忆' : 'Explore this memory'));
state.debugEarlyGeneration=true;
state.debugWorkspace='memoir';
await family.refreshFamilyContext();
assert.ok(family.timelineWorkspace().includes(`<p class="timeline-description">${description}</p>`));
