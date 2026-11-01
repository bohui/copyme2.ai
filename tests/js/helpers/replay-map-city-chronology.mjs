import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createFamilyWorkspace} from '../../../apps/web/client/memoir/family-workspace.mjs';
import {createPlaceWorkspace} from '../../../apps/web/client/memoir/place-workspace.mjs';
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
  if (with_estimates || city.city==='Chengde') assert.match(html,/From .+ to .+/);
  else assert.match(html,/<span class="map-memory-date">\?<\/span>/);
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
const listeners={};
const layer={isConnected:true,classList:{toggle(){}},querySelectorAll:()=>[],addEventListener:(name,callback)=>{listeners[name]=callback;},
  getBoundingClientRect:()=>({left:0,top:0}),querySelector:selector=>({canvas,'.map-memory-cards':cards,
    '.map-memory-toolbar':toolbar,'.map-memory-overflow':overflow}[selector])};
const scene={isConnected:true,clientWidth:600,clientHeight:700,classList:{toggle(){},contains:()=>true},
  querySelector(){return this.child;},append(value){this.child=value;}};
const storage=new Map();
Object.assign(globalThis,{window:{devicePixelRatio:1,matchMedia:()=>({matches:false}),addEventListener(){}},
  document:{documentElement:{lang:'en-AU'},createElement:()=>layer},Image:class {complete=true;naturalWidth=16;},
  localStorage:{getItem:key=>storage.get(key) ?? null,setItem:(key,value)=>storage.set(key,value)}});
const destination=places.find(place=>place.place==='Sydney');
let center=destination;
const viewer={isDestroyed:()=>false,scene:{mode:2,postRender:{addEventListener(){}}},
  camera:{frustum:{left:-4000,right:4000},flyTo:frame=>{frames.push(frame);center=frame.destination;}}};
const cesium={SceneMode:{SCENE2D:2},Cartesian3:{fromDegrees:(longitude,latitude,height)=>({longitude,latitude,height})},
  SceneTransforms:{worldToWindowCoordinates:(_,point)=>({x:300+(point.longitude-center.longitude)*500,
    y:350+(point.latitude-center.latitude)*500})}};
Object.assign(state,{timeline:enriched,placeJourney:destination,lifeStage:'all'});
state.project.profile.memory_places=places;
const workspace=()=>{
  const result=createPlaceWorkspace({state,profile:()=>state.project.profile,captureProjectScope:()=>project_id,
    isCurrentProjectScope:()=>true,render(){},lifeStageText:stage=>stage,
    photos:{bindPhotoMemoryActions(){},photoRequestKey:()=>'',pictureWall:()=>'',workspacePictureItems:()=>[]}});
  result.mapPhotoAlbums.sync=()=>{};
  return result;
};
const first=workspace(),map=first.mapMemoryEvents;
map.sync(scene);map.attach(viewer,cesium);
assert.ok(stamps.length>0 && stamps.every(size=>size===16),'A sourced intercity trail stays visible in the one-event Sydney view');
assert.equal(frames.length,1);
const active=places.find(place=>place.place==='Chengde');
const groupKey=map.nodes().find(node=>node.city==='Chengde').groupKey;
listeners.click({target:{closest:()=>({dataset:{memoryCity:groupKey},hasAttribute:name=>name==='data-memory-city'})}});
assert.equal(frames.at(-1).destination.latitude,active.latitude);
map.dispose();scene.child=null;map.sync(scene);map.attach(viewer,cesium);
assert.equal(frames.at(-1).destination.latitude,active.latitude,'Reopening must fly to the last active API city');
assert.ok(frames.at(-1).destination.height<=40000);
map.dispose();
scene.child=null;
const refreshed=workspace();
assert.match(refreshed.workspaceMediaOverview(),new RegExp(`data-cesium-latitude="${active.latitude}"`),
  'The opening globe flight must use the saved city before the event layer is attached');
refreshed.mapMemoryEvents.sync(scene);refreshed.mapMemoryEvents.attach(viewer,cesium);
assert.equal(frames.at(-1).destination.latitude,active.latitude,'A refreshed project must restore the same API city');
assert.ok(Math.abs(frames.at(-1).destination.longitude-active.longitude)<1e-9);
assert.match(cards.innerHTML,/Growing up/);
assert.doesNotMatch(cards.innerHTML,/Sydney residence|Shanghai study and work/);
refreshed.mapMemoryEvents.dispose();
state.project.profile.memory_places=[];
const eventOnly=workspace();
eventOnly.mapMemoryEvents.sync(null);
assert.match(eventOnly.workspaceMediaOverview(),new RegExp(`data-cesium-latitude="${active.latitude}"`),
  'Event-only cities must also supply the restored opening flight');
eventOnly.mapMemoryEvents.dispose();
