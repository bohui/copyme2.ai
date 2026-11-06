import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createFamilyWorkspace} from '../../../apps/web/client/memoir/family-workspace.mjs';
import {createPlaceWorkspace} from '../../../apps/web/client/memoir/place-workspace.mjs';
import {cityEventCards, memoryEventCardMarkup, memoryTrailLegs} from '../../../apps/web/client/memoir/map-memory-journey.mjs';
import {translateWith} from '../../../apps/web/client/i18n.js';

const {project,feed,locations,end} = JSON.parse(readFileSync(0,'utf8'));
const city = (place,country,latitude,longitude) => ({place,hierarchy:['Earth',country,place],
  granularity:'city',latitude,longitude});
const memory_places = [city('Porto','Portugal',41.1496,-8.6109), city('Hobart','Australia',-42.8821,147.3272),
  city('Reykjavik','Iceland',64.1466,-21.9426)];
const state = {project:{id:project,profile:{memory_places}},supabase:{accessToken:'test'},lifeStage:'all',
  placeJourney:memory_places[2],timeline:[]};
globalThis.window = {addEventListener(){}};
const context = {state,captureProjectScope:()=>project,isCurrentProjectScope:id=>id===project,render(){},
  storyApi:async path=>{
    const url = new URL(path,'https://fixture.invalid');
    if (url.pathname === '/v1/story/atlas-events') return structuredClone(feed);
    const [id,kind] = url.pathname.split('/').slice(-2);
    assert.equal(kind,'places');
    return structuredClone(locations[id]);
  }};
await createFamilyWorkspace(context).refreshFamilyContext();
assert.ok(state.timeline.every(event=>event.canonical));
const workspace = createPlaceWorkspace({...context,profile:()=>state.project.profile,lifeStageText:stage=>stage,photos:{}});
workspace.mapMemoryEvents.sync(null);
await new Promise(resolve=>setImmediate(resolve));
const nodes = workspace.mapMemoryEvents.nodes();
const cards = cityEventCards(nodes);
assert.deepEqual(cards.map(card=>[card.city,card.count]),[['Porto',1],['Hobart',1]]);
assert.deepEqual(memoryTrailLegs(nodes).map(leg=>[leg.from.city,leg.to.city]),[['Porto','Hobart']]);
const porto = memoryEventCardMarkup(cards[0],{t:(key,values)=>translateWith(`Memoir.workspace.${key}`,values),
  lifeStageText:stage=>stage});
assert.ok(porto.includes(`<span data-memory-text>From 1999 to ${end}</span>`),porto);
const map = workspace.workspaceMediaOverview();
assert.match(map,/data-cesium-place/);
assert.doesNotMatch(map,/Reykjavik/);
