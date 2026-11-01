import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createFamilyWorkspace} from '../../../apps/web/client/memoir/family-workspace.mjs';
import {createMapMemoryEvents} from '../../../apps/web/client/memoir/map-memory-events.mjs';
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
for (const city of cities) {
  const html=memoryEventCardMarkup(city,{t:(key,values)=>translateWith(`Memoir.workspace.${key}`,values),
    lifeStageText:stage=>stage});
  assert.ok(html.includes(`<strong class="map-memory-summary">${city.city}</strong>`));
  assert.match(html,/From .+ to .+/);
  assert.match(html,/data-memory-city=[^>]+>Expand memories<\/button>/);
  assert.match(html,/data-memory-add[^>]*>Add a memory<\/button>/);
  assert.doesNotMatch(html,/Birth|Growing up|Shanghai study and work|Sydney residence|data-memory-explore|confidence/);
  if (city.city==='Chengde') assert.ok(html.includes(with_estimates
    ? 'From 1983 · About age 0 to About 2000 · About age 17'
    : 'From 1983 · About age 0 to ?'));
}
assert.ok(journey.legs.some(leg=>leg.from.city==='Shanghai' && leg.to.city==='Sydney'),
  'The skill’s sourced before relation must survive the database/API/client boundary');
for (const node of journey.nodes) {
  const html=memoryEventCardMarkup(node,{t:(key,values)=>translateWith(`Memoir.workspace.${key}`,values),
    lifeStageText:stage=>stage});
  assert.doesNotMatch(html,/confidence|>\d+%</);
  assert.doesNotMatch(html,/data-memory-add/,'An API event card must not gain a second city-level add action');
  if (node.event.title==='Birth') assert.match(html,/1983 · About age 0/);
  else if (with_estimates) {
    assert.match(html,/About \d{4}–\d{4} · About age \d+–\d+/);
    assert.ok(!('basis' in node.event.temporal_estimate));
  } else {
    assert.match(html,/<span class="map-memory-date">\?<\/span>/);
  }
  assert.ok(!('source_refs' in node.event));
}

const stamps=[],frames=[];
const canvas={getContext:()=>new Proxy({clearRect:()=>{stamps.length=0;},drawImage:(_,x,y,width)=>stamps.push(width)},
  {get:(target,key)=>target[key] || (()=>{})})};
const cards={innerHTML:'',scrollTop:0,getBoundingClientRect:()=>({top:0,bottom:700}),querySelectorAll:()=>[]};
const toolbar={innerHTML:''},overflow={replaceChildren(){}};
const layer={isConnected:true,classList:{toggle(){}},querySelectorAll:()=>[],addEventListener(){},
  getBoundingClientRect:()=>({left:0,top:0}),querySelector:selector=>({canvas,'.map-memory-cards':cards,
    '.map-memory-toolbar':toolbar,'.map-memory-overflow':overflow}[selector])};
const scene={clientWidth:600,clientHeight:700,classList:{toggle(){},contains:()=>true},querySelector:()=>layer};
Object.assign(globalThis,{window:{devicePixelRatio:1,matchMedia:()=>({matches:false})},
  document:{documentElement:{lang:'en-AU'}},Image:class {complete=true;naturalWidth=16;}});
const destination=places.find(place=>place.place==='Sydney');
const viewer={isDestroyed:()=>false,scene:{mode:2,postRender:{addEventListener(){}}},
  camera:{frustum:{left:-4000,right:4000},flyTo:frame=>frames.push(frame)}};
const cesium={SceneMode:{SCENE2D:2},Cartesian3:{fromDegrees:(longitude,latitude,height)=>({longitude,latitude,height})},
  SceneTransforms:{worldToWindowCoordinates:(_,point)=>({x:300+(point.longitude-destination.longitude)*500,
    y:350+(point.latitude-destination.latitude)*500})}};
const map=createMapMemoryEvents({getEvents:()=>enriched,getGroups:()=>groupPlaces(places),getProfile:()=>state.project.profile,
  getScope:()=>project_id,getStage:()=> 'all',t:(key,values)=>translateWith(`Memoir.workspace.${key}`,values),lifeStageText:stage=>stage});
map.sync(scene);map.attach(viewer,cesium);
assert.ok(stamps.length>0 && stamps.every(size=>size===16),'A sourced intercity trail stays visible in the one-event Sydney view');
assert.equal(frames.length,1);
map.dispose();map.sync(scene);map.attach(viewer,cesium);
assert.equal(frames.length,2,'Reopening the viewer must frame all cities returned by the API');
map.dispose();
