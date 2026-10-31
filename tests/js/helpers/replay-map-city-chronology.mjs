import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createFamilyWorkspace} from '../../../apps/web/client/memoir/family-workspace.mjs';
import {buildMapMemoryJourney,cityEventCards,memoryEventCardMarkup} from '../../../apps/web/client/memoir/map-memory-journey.mjs';
import {groupPlaces} from '../../../apps/web/client/memoir/places.mjs';
import {translateWith} from '../../../apps/web/client/i18n.js';

const {project_id,pages,orders,locations,places,with_estimates}=JSON.parse(readFileSync(0,'utf8'));
const state={project:{id:project_id,profile:{birth_year:1983}},supabase:{accessToken:'fixture'},
  familyFeaturesEnabled:false,timeline:[]};
const requests=[];
const family=createFamilyWorkspace({state,captureProjectScope:()=>project_id,isCurrentProjectScope:()=>true,render(){},
  storyApi:async path=>{
    requests.push(path);
    const url=new URL(path,'https://fixture.invalid');
    if (url.pathname==='/v1/story/map-events') return structuredClone(pages[url.searchParams.get('cursor') || 'first']);
    const match=url.pathname.match(/\/map-events\/[^/]+\/([^/]+)\/order$/);
    assert.ok(match,'Only the ordinary map read endpoints are authorized');
    return orders[match[1]][url.searchParams.get('cursor') || 'first'];
  }});
await family.refreshFamilyContext();
assert.equal(requests.filter(path=>path.includes('?project_id')).length,2,'All event pages must be loaded');
assert.equal(state.timeline.length,4);
assert.deepEqual(state.timeline.map(event=>event.title),['Birth','Growing up','Shanghai study and work','Sydney residence']);
const enriched=state.timeline.map(event=>({...event,places:locations[event.id].items.map(link=>({...link,
  place:places.find(place=>place.place===link.place.place)}))}));
const journey=buildMapMemoryJourney(enriched,groupPlaces(places),state.project.profile);
assert.deepEqual(journey.nodes.map(node=>node.event.title),state.timeline.map(event=>event.title));
const cities=cityEventCards(journey.nodes);
assert.deepEqual(cities.map(city=>city.city),['Chengde','Shanghai','Sydney']);
assert.deepEqual(cities.map(city=>city.count),[2,1,1]);
assert.ok(journey.legs.some(leg=>leg.from.city==='Shanghai' && leg.to.city==='Sydney'),
  'The skill’s sourced before relation must survive the database/API/client boundary');
for (const node of journey.nodes) {
  const html=memoryEventCardMarkup(node,{t:(key,values)=>translateWith(`Memoir.workspace.${key}`,values),
    lifeStageText:stage=>stage});
  if (node.event.title==='Birth') assert.match(html,/1983 · About age 0/);
  else if (with_estimates) {
    assert.match(html,/About \d{4}–\d{4} · About age \d+–\d+/);
    assert.match(html,/Estimated · confidence (40|65|80)%/);
    assert.ok(!('basis' in node.event.temporal_estimate));
  } else {
    assert.match(html,/Year not yet known · Age not yet known/);
    assert.match(html,/Date confidence 0%/);
  }
  assert.ok(!('source_refs' in node.event));
}
