import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createPlaceWorkspace} from '../../../apps/web/client/memoir/place-workspace.mjs';
import {createFamilyWorkspace} from '../../../apps/web/client/memoir/family-workspace.mjs';
import {buildMapMemoryJourney,cityEventCards} from '../../../apps/web/client/memoir/map-memory-journey.mjs';
import {createMapMemoryEvents} from '../../../apps/web/client/memoir/map-memory-events.mjs';
import {groupMapFrame,groupPlaces,mergePlaces} from '../../../apps/web/client/memoir/places.mjs';
import {harness as mapImageryHarness} from './place-map-imagery.mjs';

const {events,places,snapshot,relative_current_home,estimated_current_home} = JSON.parse(readFileSync(0,'utf8'));
const enriched = events.map(event => ({...event,canonical:true,map_places:event.places}));
const groups=groupPlaces(mergePlaces([...places,...enriched.flatMap(event=>event.map_places.map(link=>link.place))]));
const journey = buildMapMemoryJourney(enriched,groups);
for (const provider of ['google','geoapify']) for (const group of groups) {
  const frame=groupMapFrame(group,group.city);
  assert.ok(Number.isFinite(frame.latitude) && Number.isFinite(frame.longitude));
  const slow=await mapImageryHarness(provider,{journey:frame,projectId:snapshot.project_id,
    placeKey:group.key,reducedMotion:false});
  const pending=slow.imagery.requestImage(0,0,0);
  slow.expireTileWait();
  assert.equal(slow.unavailable.size,0,'Slow imagery must keep an API-backed city recoverable');
  assert.equal(slow.viewer.view.destination.longitude,frame.longitude,
    'A restored map starts at an authorized place while its imagery is loading');
  assert.equal(slow.viewer.view.destination.latitude,frame.latitude);
  slow.resolveImage({width:256,height:256});await pending;slow.loadedTiles();
  assert.equal(slow.classes.has('is-cesium-map'),true,'Late tiles must restore the canonical API city without reload');
  assert.equal(slow.loads(),1);
  assert.equal(slow.flights.length,0);
  assert.equal(slow.viewer.scene.screenSpaceCameraController.enableInputs,true);
  const destination={longitude:frame.longitude,latitude:frame.latitude,height:frame.height || 40000};
  slow.viewer.camera.flyTo({destination,duration:2.8});
  assert.equal(slow.flights.length,0,'An API-backed location must prepare its zoom before flying');
  for (let step=0;!slow.flights.length && step<64;step++) {
    slow.loadedTiles();await new Promise(resolve=>setImmediate(resolve));
  }
  assert.equal(slow.flights.length,1,'Prepared API-backed locations use one continuous flight');
  assert.deepEqual(slow.flights[0].options.destination,destination);
  assert.ok(slow.views.some(view=>view.destination.height===destination.height));
  slow.viewer.completeFlight();
  assert.equal(slow.viewer.scene.screenSpaceCameraController.enableInputs,true);
  slow.context.disposeCesiumPlaceJourney();
}
assert.equal(journey.nodes.length,2,'Both canonical API events need separate map cards');
if (relative_current_home) {
  const groups=groupPlaces(enriched.flatMap(event=>event.map_places.map(link=>link.place)));
  for (const ordered of [enriched,[...enriched].reverse()]) {
    const route=buildMapMemoryJourney(ordered,groups);
    assert.deepEqual(route.legs.map(leg=>[leg.from.city,leg.to.city]),[['Chengde','Sydney']],
      'Birth precedes the undated current home regardless of API event order');
    const home=route.nodes.find(node=>node.city==='Sydney');
    assert.equal(home.year,estimated_current_home ? 1991 : null);
    if (estimated_current_home) {
      assert.equal(home.age.start,0);
      assert.equal(home.age.end,35);
    } else assert.deepEqual(home.age,{start:null,end:null});
    assert.equal(home.event.yearConfidenceScore,estimated_current_home ? .2 : 0);
    assert.equal(home.event.temporal.year_start,null);
    assert.equal(home.event.temporal.year_end,null);
    assert.equal(home.event.temporal_anchor,'present');
    assert.ok(!('source_refs' in home.event),'Relative order must not expose original testimony');
  }
  const cards={innerHTML:'',scrollTop:0,querySelectorAll:()=>[],getBoundingClientRect:()=>({top:0,bottom:700})};
  const toolbar={innerHTML:''},overflow={replaceChildren(){}};
  const stamps=[];
  const canvas={getContext:()=>new Proxy({clearRect:()=>{stamps.length=0;},drawImage:()=>stamps.push(true)},
    {get:(target,key)=>target[key] || (()=>{})})};
  const layer={isConnected:true,classList:{toggle(){}},addEventListener(){},querySelectorAll:()=>[],
    getBoundingClientRect:()=>({left:0,top:0}),
    querySelector:selector=>({'.map-memory-cards':cards,'.map-memory-toolbar':toolbar,
      '.map-memory-overflow':overflow,canvas}[selector])};
  const scene={isConnected:true,clientWidth:600,clientHeight:700,classList:{toggle(){},contains:()=>true},
    append:value=>{scene.child=value;},querySelector:()=>scene.child};
  Object.assign(globalThis,{document:{createElement:()=>layer},window:{devicePixelRatio:1,matchMedia:()=>({matches:false})},
    Image:class {complete=true;naturalWidth=16;}});
  const mapGroups=groupPlaces(mergePlaces([...places,...enriched.flatMap(event=>event.map_places.map(link=>link.place))]));
  const overlay=createMapMemoryEvents({getEvents:()=>enriched.map(event=>({...event,places:event.map_places})),
    getGroups:()=>mapGroups,getProfile:()=>({}),getScope:()=>snapshot.project_id,getStage:()=> 'all',
    t:key=>key,lifeStageText:stage=>stage});
  let redraw,center=null;
  const viewer={isDestroyed:()=>false,scene:{mode:2,postRender:{addEventListener:callback=>{redraw=callback;}}},
    camera:{frustum:{left:-100000,right:100000},flyTo(){},setView(){}}};
  overlay.sync(scene);
  overlay.attach(viewer,{SceneMode:{SCENE2D:2},Cartesian3:{fromDegrees:(longitude,latitude)=>({longitude,latitude})},
    SceneTransforms:{worldToWindowCoordinates:(_,point)=>center
      ? {x:300+(point.longitude-center.longitude)*500,y:350+(point.latitude-center.latitude)*500} : {x:300,y:350}}});
  for (const node of journey.nodes) for (const span of [8000,80000,12000]) {
    center=node;
    viewer.camera.frustum={left:-span/2,right:span/2};
    redraw();
    assert.equal((cards.innerHTML.match(/data-memory-explore=/g)||[]).length,1,
      'The API-backed list must keep only the visible city’s event when zooming in or out');
    assert.ok(cards.innerHTML.includes(`data-memory-explore="${node.event.id}"`));
    assert.ok(stamps.length>0,'The API-backed intercity trail must draw its footprints at each city');
    assert.doesNotMatch(layer.innerHTML,/map-memory-detail/);
  }
  overlay.dispose();
  process.exit(0);
}
const cities = cityEventCards(journey.nodes);
assert.equal(cities.length,1,'The initial map groups both events under Sydney');
assert.equal(cities[0].city,'Sydney');
assert.equal(cities[0].count,2);
assert.deepEqual(journey.nodes.map(node=>node.place),['Newtown','Pyrmont']);
assert.deepEqual(journey.nodes.map(node=>node.age.start),[6,25]);
assert.notEqual(journey.nodes[0].latitude,journey.nodes[1].latitude,
  'Zooming in must retain actual event coordinates instead of the city centre');
assert.ok(journey.nodes.every(node=>!node.cityOnly));
assert.equal(journey.legs.length,1,'The footprint trail connects the two age stages');

const classes = new Set();
const toolbar={innerHTML:''}, panel={hidden:true}, cards={innerHTML:'',querySelectorAll:()=>[]};
const overflow={hidden:true,replaceChildren(){},querySelector:()=>null};
const context=new Proxy({}, {get:(target,key)=>target[key] || (()=>{})});
const canvas={width:0,height:0,getContext:()=>context};
const layer={isConnected:true,clientWidth:450,clientHeight:500,innerHTML:'',addEventListener(){},
  classList:{toggle:(name,on)=>on?classes.add(name):classes.delete(name)},querySelectorAll:()=>[],
  querySelector:selector=>({'.map-memory-toolbar':toolbar,'.map-memory-detail':panel,
    '.map-memory-cards':cards,'.map-memory-overflow':overflow,canvas}[selector])};
toolbar.offsetHeight=44;
const scene={isConnected:true,child:null,append:value=>{scene.child=value;},querySelector:()=>scene.child,
  classList:{contains:()=>true,toggle:(name,on)=>on?classes.add(name):classes.delete(name)}};
Object.assign(globalThis,{document:{documentElement:{lang:'en-AU'},createElement:()=>layer},
  window:{addEventListener(){},matchMedia:()=>({matches:true,addEventListener(){}})}});
const projectId=snapshot.project_id;
const state={project:{id:projectId,profile:{memory_places:places}},supabase:{accessToken:'fixture',user:{id:'owner'}},
  timeline:[],familyFeaturesEnabled:false,lifeStage:'all',chat:[],placeJourney:null};
const history=JSON.stringify(places), requests=[];
const dependencies={state,profile:()=>state.project.profile,render(){},
  captureProjectScope:()=>state.project.id,isCurrentProjectScope:id=>id===state.project.id,
  lifeStageText:stage=>stage,storyApi:async path=>{
    assert.ok(path.startsWith('/v1/story/atlas-events?'),'Map locations must arrive inline');
    return snapshot;
  },supabaseApi:async path=>{requests.push(path);}};
const family=createFamilyWorkspace(dependencies);
await family.refreshFamilyContext();
assert.equal(state.timeline.length,2,'Ordinary recall must load saved events before the map can render them');
const workspace=createPlaceWorkspace({...dependencies,photos:{bindPhotoMemoryActions(){},favoritePhotoWall:()=>'',pictureWall:()=>'',
    photoRequestKey:()=>'',renderablePictureItems:()=>[],workspacePictureItems:()=>[]}});
// This replay supplies only the event layer DOM; photo albums have their own browser coverage.
workspace.mapPhotoAlbums.sync=()=>{};
workspace.mapMemoryEvents.sync(null);
await new Promise(resolve=>setImmediate(resolve));
assert.deepEqual(requests,[]);
assert.ok(workspace.placeWorkspaceSelection(),'Canonical event locations must activate a map without a separate journey hint');
assert.equal(JSON.stringify(state.project.profile.memory_places),history,'Event map lookup must not rewrite place history');
workspace.mapMemoryEvents.sync(scene);
workspace.mapMemoryEvents.selectCity(journey.nodes[0].groupKey);
let afterRender;
const viewer={isDestroyed:()=>false,scene:{mode:2,postRender:{addEventListener:callback=>{afterRender=callback;return ()=>{};}}},
  camera:{frustum:{left:-50000,right:50000},flyTo(){},setView(){}}};
workspace.mapMemoryEvents.attach(viewer,{SceneMode:{SCENE2D:2},Cartesian3:{fromDegrees:(longitude,latitude)=>({longitude,latitude})},
  SceneTransforms:{worldToWindowCoordinates:(_,point)=>({x:150+(point.longitude-151.18)*1000,y:240+(point.latitude+33.88)*1000})}});
assert.doesNotMatch(cards.innerHTML,/map-memory-detail/);
assert.equal((cards.innerHTML.match(/data-memory-explore=/g)||[]).length,2,
  'The restored active city shows its own events instead of resetting to the whole journey');
assert.equal((cards.innerHTML.match(/data-memory-city=/g)||[]).length,0);
assert.ok(classes.has('is-compact'),'Narrow desktop panels use the compact card layout');
viewer.camera.frustum={left:-4000,right:4000};afterRender();
for(const text of ['Age 6','Age 25']) assert.ok(cards.innerHTML.includes(text),text);
for(const node of journey.nodes) assert.ok(cards.innerHTML.includes(`data-memory-explore="${node.event.id}"`));
workspace.mapMemoryEvents.dispose();
