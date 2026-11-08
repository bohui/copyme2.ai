import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createFamilyWorkspace} from '../../../apps/web/client/memoir/family-workspace.mjs';
import {createPlaceWorkspace} from '../../../apps/web/client/memoir/place-workspace.mjs';
import {buildMapMemoryJourney,cityEventCards,memoryEventCardMarkup} from '../../../apps/web/client/memoir/map-memory-journey.mjs';
import {groupPlaces} from '../../../apps/web/client/memoir/places.mjs';
import {translateWith} from '../../../apps/web/client/i18n.js';

const {project_id,pages,places,with_estimates}=JSON.parse(readFileSync(0,'utf8'));
const state={project:{id:project_id,profile:{birth_year:1983}},supabase:{accessToken:'fixture'},
  familyFeaturesEnabled:false,timeline:[]};
const requests=[];
const family=createFamilyWorkspace({state,captureProjectScope:()=>project_id,isCurrentProjectScope:()=>true,render(){},
  storyApi:async path=>{
    requests.push(path);
    const url=new URL(path,'https://fixture.invalid');
    assert.equal(url.pathname,'/v1/story/atlas-events','Inline chronology must not fan out to per-event order reads');
    assert.equal(url.searchParams.get('view'),'map');
    return structuredClone(pages[url.searchParams.get('cursor') || 'first']);
  }});
await family.refreshFamilyContext({mapSnapshot:structuredClone(pages.first)});
assert.equal(requests.length,1,'Only read the continuation after Atlas supplies the first page');
assert.equal(state.timeline.length,4);
assert.deepEqual(state.timeline.map(event=>event.title),['Birth','Catching insects','Shanghai study and work','Sydney residence']);
const enriched=state.timeline.map(event=>({...event,places:event.places.map(link=>({...link,
  place:places.find(place=>place.place===link.place.place)}))}));
const journey=buildMapMemoryJourney(enriched,groupPlaces(places),state.project.profile);
assert.deepEqual(journey.nodes.map(node=>node.event.title),state.timeline.map(event=>event.title));
const cities=cityEventCards(journey.nodes);
assert.deepEqual(cities.map(city=>city.city),['Chengde','Shanghai','Sydney']);
assert.deepEqual(cities.map(city=>city.count),[2,1,1]);
const currentAge = /data-memory-text>About 2024 · About age 41<\/span><sup class="map-memory-question"/;
for (const city of cities) {
  const html=memoryEventCardMarkup(city,{t:(key,values)=>translateWith(`Memoir.workspace.${key}`,values),
    lifeStageText:stage=>stage});
  assert.ok(html.includes(`<strong class="map-memory-summary"><span data-memory-text>${city.city}</span></strong>`));
  if (with_estimates || city.city==='Chengde') assert.match(html,/From .+ to .+/);
  else if (city.city==='Sydney') {
    assert.match(html,currentAge);
    assert.equal(city.nodes[0].event.temporal_anchor,'present');
    assert.deepEqual(city.nodes[0].event.timing_hint,{year:2024,confidence:.3});
    assert.match(html,/timeline_avatar_middle_aged_male\.png/);
  }
  else assert.match(html,/data-memory-text>About \d{4} · About age \d+<\/span><sup class="map-memory-question"/);
  assert.match(html,/timeline_avatar_.*_male\.png/);
  assert.doesNotMatch(html,/is-unknown|Age not yet known|Year not yet known/);
  assert.match(html,/data-memory-city=[^>]+>Expand memories<\/button>/);
  assert.match(html,/data-memory-add[^>]*>Add a memory<\/button>/);
  assert.doesNotMatch(html,/Birth|Catching insects|Shanghai study and work|Sydney residence|data-memory-explore|confidence/);
  if (city.city==='Chengde') assert.ok(html.includes(with_estimates
    ? 'From 1983 · About age 0 to About 1993 · About age 10'
    : 'From 1983 · About age 0 to 1983 · About age 0'));
}
assert.ok(journey.legs.some(leg=>leg.from.city==='Shanghai' && leg.to.city==='Sydney'),
  'The skill’s sourced before relation must survive the database/API/client boundary');
for (const node of journey.nodes) {
  const html=memoryEventCardMarkup(node,{t:(key,values)=>translateWith(`Memoir.workspace.${key}`,values),
    lifeStageText:stage=>stage});
  assert.doesNotMatch(html,/confidence|>\d+%</);
  assert.doesNotMatch(html,/data-memory-add/,'An API event card must not gain a second city-level add action');
  if (node.event.title==='Birth') assert.match(html,/1983 · About age 0/);
  else if (node.event.title==='Catching insects') {
    assert.match(html,/About 1991 · About age 8<\/span><sup class="map-memory-question"/);
    if (with_estimates) {
      assert.equal(node.event.temporal_estimate.age_start,6);
      assert.equal(node.event.temporal_estimate.age_end,10);
      assert.ok(!('basis' in node.event.temporal_estimate));
    }
  } else if (with_estimates) {
    assert.match(html,/About \d{4}–\d{4} · About age \d+–\d+/);
    assert.ok(!('basis' in node.event.temporal_estimate));
  } else if (node.event.title==='Sydney residence') {
    assert.match(html,currentAge);
    assert.equal(node.dated,false,'A display hint alone must not date a period for the route');
  }
  else assert.match(html,/data-memory-text>About \d{4} · About age \d+<\/span><sup class="map-memory-question"/);
  assert.match(html,/timeline_avatar_.*_male\.png/);
  assert.doesNotMatch(html,/is-unknown/);
  assert.ok(!('source_refs' in node.event));
}

const stamps=[],frames=[],views=[];
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
let center=destination,redraw;
const viewer={isDestroyed:()=>false,scene:{mode:2,postRender:{addEventListener:callback=>{redraw=callback;}}},
  camera:{frustum:{left:-4000,right:4000},flyTo:frame=>{frames.push(frame);center=frame.destination;},
    setView:view=>{views.push(view);center=view.destination.height>40000 ? null : view.destination;
      const span=view.destination.height>40000 ? 200000 : 8000;
      viewer.camera.frustum={left:-span/2,right:span/2};}}};
const cesium={SceneMode:{SCENE2D:2},Cartesian3:{fromDegrees:(longitude,latitude,height)=>({longitude,latitude,height})},
  SceneTransforms:{worldToWindowCoordinates:(_,point)=>center ? {x:300+(point.longitude-center.longitude)*500,
    y:350+(point.latitude-center.latitude)*500} : {x:300,y:350}}};
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
map.selectCity(groupPlaces([destination])[0].key);
map.sync(scene);map.attach(viewer,cesium);
assert.ok(stamps.length>0 && stamps.every(size=>size===16),'A sourced intercity trail stays visible in the one-event Sydney view');
assert.equal(frames.length,0,'Restoring a map selection must not create an active-location flight');
center={longitude:0,latitude:0};redraw();
assert.equal(cards.innerHTML,'','A view outside every API city must not retain event cards');
center=destination;redraw();
assert.match(cards.innerHTML,/Sydney residence/);
const active=places.find(place=>place.place==='Chengde');
state.placeJourney=active;
const groupKey=map.nodes().find(node=>node.city==='Chengde').groupKey;
listeners.click({target:{closest:()=>({dataset:{memoryCity:groupKey},hasAttribute:name=>name==='data-memory-city'})}});
assert.equal(frames.at(-1).destination.latitude,active.latitude);
const beforeReopen=frames.length;
map.dispose();scene.child=null;map.sync(scene);map.attach(viewer,cesium);
assert.equal(frames.length,beforeReopen,'Reopening must restore the API city without another animation');
assert.equal(views.at(-1).destination.latitude,active.latitude);
assert.ok(views.at(-1).destination.height<=40000);
map.dispose();
scene.child=null;
state.placeJourney=destination;
const refreshed=workspace();
refreshed.mapMemoryEvents.sync(null);
assert.match(refreshed.workspaceMediaOverview(),/data-place-key="all"/,
  'Refresh opens the whole journey regardless of the previous camera selection');
const beforeArrival=frames.length;
center=active;
refreshed.mapMemoryEvents.sync(scene);refreshed.mapMemoryEvents.attach(viewer,cesium,groupKey);
assert.equal(frames.length,beforeArrival,'An API city already framed by the opening flight must not get another fast zoom');
assert.ok(views.at(-1).destination.height>40000,'Refresh frames every saved API city without a flight');
assert.ok(Math.abs(frames.at(-1).destination.longitude-active.longitude)<1e-9);
assert.equal((cards.innerHTML.match(/class="map-memory-card is-city/g)||[]).length,3);
refreshed.mapMemoryEvents.dispose();
state.project.profile.memory_places=[];
const eventOnly=workspace();
eventOnly.mapMemoryEvents.sync(null);
assert.match(eventOnly.workspaceMediaOverview(),/data-place-key="all"/,
  'Event-only cities also open on the whole journey');
eventOnly.mapMemoryEvents.dispose();
