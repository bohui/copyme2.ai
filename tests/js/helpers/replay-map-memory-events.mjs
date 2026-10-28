import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createPlaceWorkspace} from '../../../apps/web/client/memoir/place-workspace.mjs';
import {buildMapMemoryJourney,cityEventCards} from '../../../apps/web/client/memoir/map-memory-journey.mjs';
import {groupPlaces} from '../../../apps/web/client/memoir/places.mjs';

const {events,locations,places,grouping} = JSON.parse(readFileSync(0,'utf8'));
const enriched = events.map(event => ({...event,canonical:true,map_places:locations[event.id].items.map(link => {
  const record=grouping[link.place.place].places[0];
  return {...link,place:{...link.place,map_city:record.city,map_city_key:record.city_key,map_pin:record.pin}};
})}));
const journey = buildMapMemoryJourney(enriched,groupPlaces([...places,...enriched.flatMap(event=>event.map_places.map(link=>link.place))]));
assert.equal(journey.nodes.length,2,'Both canonical API events need separate map cards');
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
const state={project:{id:'map-replay',profile:{memory_places:places}},supabase:{accessToken:'fixture',user:{id:'owner'}},
  timeline:events.map(event=>({...event,canonical:true})),lifeStage:'all',chat:[],placeJourney:null};
const history=JSON.stringify(places), requests=[];
const workspace=createPlaceWorkspace({state,profile:()=>state.project.profile,render(){},
  captureProjectScope:()=>state.project.id,isCurrentProjectScope:id=>id===state.project.id,
  lifeStageText:stage=>stage,storyApi:async path=>{
    const event=events.find(event=>path.includes(`/${event.id}/places`));
    assert.ok(event);return locations[event.id];
  },supabaseApi:async(path,options)=>{
    assert.equal(path,'/v1/agent/places/map-replay/groups');
    const body=JSON.parse(options.body);
    assert.equal(body.places.length,1);
    assert.equal(body.language,'en-AU');
    assert.ok(!('title' in body.places[0]) && !('source_refs' in body.places[0]));
    requests.push(body.places[0].place);return grouping[body.places[0].place];
  },photos:{bindPhotoMemoryActions(){},favoritePhotoWall:()=>'',pictureWall:()=>'',
    photoRequestKey:()=>'',renderablePictureItems:()=>[],workspacePictureItems:()=>[]}});
workspace.mapMemoryEvents.sync(null);
await new Promise(resolve=>setImmediate(resolve));
assert.deepEqual(requests.sort(),['Newtown','Pyrmont']);
assert.ok(workspace.placeWorkspaceSelection(),'Canonical event locations must activate a map without a separate journey hint');
assert.equal(JSON.stringify(state.project.profile.memory_places),history,'Event map lookup must not rewrite place history');
workspace.mapMemoryEvents.sync(scene);
let afterRender;
const viewer={isDestroyed:()=>false,scene:{mode:2,postRender:{addEventListener:callback=>{afterRender=callback;return ()=>{};}}},
  camera:{frustum:{left:-50000,right:50000},flyTo(){}}};
workspace.mapMemoryEvents.attach(viewer,{SceneMode:{SCENE2D:2},Cartesian3:{fromDegrees:(longitude,latitude)=>({longitude,latitude})},
  SceneTransforms:{worldToWindowCoordinates:(_,point)=>({x:150+(point.longitude-151.18)*1000,y:240+(point.latitude+33.88)*1000})}});
assert.match(cards.innerHTML,/Sydney/);
assert.match(cards.innerHTML,/2 events/);
assert.ok(classes.has('is-compact'),'Narrow desktop panels use the compact card layout');
viewer.camera.frustum={left:-4000,right:4000};afterRender();
for(const text of ['Newtown','Pyrmont','Age 6','Age 25']) assert.ok(cards.innerHTML.includes(text),text);
workspace.mapMemoryEvents.dispose();
