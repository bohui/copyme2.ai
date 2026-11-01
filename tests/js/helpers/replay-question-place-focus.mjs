import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createPlaceWorkspace} from '../../../apps/web/client/memoir/place-workspace.mjs';
import {createPhotoWorkspace} from '../../../apps/web/client/memoir/photo-workspace.mjs';
import {applyDerivedWorkspace} from '../../../apps/web/client/memoir/derived-workspace.mjs';
import {matchesEventPlace} from '../../../apps/web/client/memoir/map-memory-journey.mjs';

const {project_id,result,snapshot,events,links,places}=JSON.parse(readFileSync(0,'utf8'));
const expected=places.find(place=>matchesEventPlace(place,{place:result.workspace_focus.place}));
const other=places.find(place=>place!==expected);
const state={project:{id:project_id,profile:{}},supabase:{user:{id:'owner'}},lifeStage:'all',timeline:[],chat:[],
  workspaceFocus:result.workspace_focus};
const values=new Map();
Object.assign(globalThis,{window:{devicePixelRatio:1,location:{origin:'https://memoir.test'},addEventListener(){},
  matchMedia:()=>({matches:false})},localStorage:{getItem:key=>values.get(key) ?? null,setItem:(key,value)=>values.set(key,value)}});

function makeWorkspace() {
  applyDerivedWorkspace(state,snapshot);
  state.project.profile.memory_places=state.project.profile.memory_places.map(place=>({...place,
    ...places.find(candidate=>matchesEventPlace(candidate,place)),pictures:[{
      asset_id:place.place,image_url:`https://photos.example/${encodeURIComponent(place.place)}.jpg`,
      allowed_actions:{embed:true},date_expression:new Date().toLocaleDateString('en-CA',{timeZone:'Australia/Sydney'}),title:place.place,
      latitude:places.find(candidate=>matchesEventPlace(candidate,place)).latitude,
      longitude:places.find(candidate=>matchesEventPlace(candidate,place)).longitude}]}));
  state.placeJourney=state.project.profile.memory_places.find(place=>matchesEventPlace(place,other));
  state.selectedPlace=null;
  state.timeline=events.map(event=>({...event,places:links[event.id].map(link=>({...link,
    place:{...link.place,...places.find(candidate=>matchesEventPlace(candidate,link.place))}}))}));
  const dependencies={state,profile:()=>state.project.profile,render(){},lifeStageText:stage=>stage,
    captureProjectScope:()=>project_id,isCurrentProjectScope:()=>true};
  let workspace;
  const photos=createPhotoWorkspace({...dependencies,placeMapTarget:place=>workspace.placeMapTarget(place)});
  workspace=createPlaceWorkspace({...dependencies,photos});
  return workspace;
}

for (const restore of ['live','refresh','reopen']) {
  const cards={innerHTML:'',scrollTop:0,querySelectorAll:()=>[],getBoundingClientRect:()=>({top:0,bottom:700})};
  const toolbar={innerHTML:''},overflow={replaceChildren(){}};
  const canvas={getContext:()=>new Proxy({},{get:()=>()=>{}})};
  const layer={isConnected:true,classList:{toggle(){}},querySelectorAll:()=>[],addEventListener(){},
    getBoundingClientRect:()=>({left:0,top:0}),querySelector:selector=>({canvas,'.map-memory-cards':cards,
      '.map-memory-toolbar':toolbar,'.map-memory-overflow':overflow}[selector])};
  const photoOverflow={scrollTop:0};
  const photoLayer={isConnected:true,dataset:{},style:{},classList:{toggle(){}},querySelectorAll:()=>[],addEventListener(){},
    querySelector:()=>photoOverflow};
  const scene={isConnected:true,clientWidth:600,clientHeight:700,classList:{toggle(){},contains:()=>true},
    querySelector:selector=>selector==='.map-memory-layer' ? layer : selector==='.map-photo-album-layer' ? photoLayer : null};
  globalThis.document={documentElement:{lang:'zh-CN'},querySelector:()=>null};
  const workspace=makeWorkspace(),map=workspace.mapMemoryEvents;
  map.sync(null);
  await new Promise(resolve=>setImmediate(resolve));
  assert.match(workspace.workspaceMediaOverview(),new RegExp(`data-cesium-latitude="${expected.latitude}"`),restore);
  map.sync(scene);
  const flights=[];
  let ready=false,center=other;
  scene.classList.contains=()=>ready;
  const viewer={isDestroyed:()=>false,scene:{mode:2,postRender:{addEventListener(){}}},
    camera:{frustum:{left:-100000,right:100000},flyTo:flight=>flights.push(flight)}};
  const cesium={SceneMode:{SCENE2D:2},Cartesian3:{fromDegrees:(longitude,latitude,height)=>({longitude,latitude,height})},
    SceneTransforms:{worldToWindowCoordinates:(_,point)=>({x:300+(point.longitude-center.longitude)*500,
      y:350+(point.latitude-center.latitude)*500})}};
  map.attach(viewer,cesium);
  assert.ok(map.viewCity(),'The opening globe already has the question city for photo filtering');
  workspace.mapPhotoAlbums.sync(scene);
  assert.ok(!photoLayer.innerHTML?.includes(encodeURIComponent(other.place)));
  ready=true;map.sync(scene);
  assert.equal(flights.at(-1).destination.latitude,expected.latitude);
  assert.ok(flights.at(-1).destination.height<=40000);
  assert.ok(!cards.innerHTML.includes(other.place==='承德市' ? '承德出生' : '悉尼生活'));
  assert.ok(!photoLayer.innerHTML.includes(encodeURIComponent(other.place)),'The other city cannot appear during flight');
  center=expected;viewer.camera.frustum={left:-6000,right:6000};flights.at(-1).complete();
  assert.ok(cards.innerHTML.includes(expected.place==='承德市' ? '承德出生' : '悉尼生活'));
  assert.ok(photoLayer.innerHTML?.includes(encodeURIComponent(expected.place)));
  const albums=workspace.mapPhotoAlbumsForScene(scene,{allPlaces:true,detailed:true,cityKey:map.viewCity()});
  assert.deepEqual(albums.map(album=>album.place),[expected.place]);
  assert.equal(state.timeline.length,2,'City filtering preserves both saved memories');
  if (restore==='reopen') {
    map.dispose();map.sync(scene);map.attach(viewer,cesium);
    assert.equal(flights.at(-1).destination.latitude,expected.latitude);
  }
  map.dispose();
}
