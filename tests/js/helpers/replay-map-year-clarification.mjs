import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createFamilyWorkspace} from '../../../apps/web/client/memoir/family-workspace.mjs';
import {buildMapMemoryJourney,cityEventCards,memoryEventCardMarkup} from '../../../apps/web/client/memoir/map-memory-journey.mjs';
import {groupPlaces} from '../../../apps/web/client/memoir/places.mjs';
import {translateWith} from '../../../apps/web/client/i18n.js';

const {project,event_id,feeds} = JSON.parse(readFileSync(0,'utf8'));
globalThis.document = {documentElement:{lang:'zh-CN'}};
const profile = {birth_year:1983};
const state = {project:{id:project,profile},supabase:{accessToken:'fixture'},timeline:[]};
const family = createFamilyWorkspace({state,render(){},captureProjectScope:()=>project,isCurrentProjectScope:()=>true});
const location = feeds[0].events.find(event=>event.id===event_id).location;
const groups = groupPlaces([{...location,latitude:-33.8688,longitude:151.2093}]);

for (const [feed,year] of feeds.map((feed,index)=>[feed,[1912,2012][index]])) {
  await family.refreshFamilyContext({mapSnapshot:feed});
  const cards = cityEventCards(buildMapMemoryJourney(state.timeline,groups,profile).nodes);
  const [sydney] = cards.filter(card=>card.city==='悉尼');
  assert.ok(sydney);
  assert.deepEqual(sydney.nodes.map(node=>node.event.id),[event_id]);
  const html = memoryEventCardMarkup(sydney,{profile,t:(key,values)=>translateWith(`Memoir.workspace.${key}`,values),
    lifeStageText:stage=>stage});
  assert.match(html,new RegExp(`data-memory-text>${year}(?: · |<)`));
  if (year===2012) assert.doesNotMatch(html,/1912/);
}
