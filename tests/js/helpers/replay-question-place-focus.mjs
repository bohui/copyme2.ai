import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createPlaceWorkspace} from '../../../apps/web/client/memoir/place-workspace.mjs';
import {createPhotoWorkspace} from '../../../apps/web/client/memoir/photo-workspace.mjs';
import {applyDerivedWorkspace} from '../../../apps/web/client/memoir/derived-workspace.mjs';
import {matchesEventPlace} from '../../../apps/web/client/memoir/map-memory-journey.mjs';

const {project_id,snapshot,redirect_snapshot,events,links,places}=JSON.parse(readFileSync(0,'utf8'));
const expected=places.find(place=>matchesEventPlace(place,snapshot.current_active_location));
const other=places.find(place=>place!==expected);
assert.ok(expected,'The server must supply the story-owned active location');
Object.assign(globalThis,{window:{devicePixelRatio:1,location:{origin:'https://memoir.test'},addEventListener(){},
  matchMedia:()=>({matches:false})},localStorage:{getItem:()=>null,setItem(){throw new Error('Map navigation must not persist story authority');}}});

for (const restore of ['live','refresh','reopen']) {
  const state={project:{id:project_id,profile:{}},supabase:{user:{id:'owner'}},lifeStage:'all',timeline:[],chat:[],
    currentActiveLocation:restore==='live' ? null : undefined};
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
  const dependencies={state,profile:()=>state.project.profile,render(){},lifeStageText:stage=>stage,
    captureProjectScope:()=>project_id,isCurrentProjectScope:()=>true};
  let workspace;
  const photos=createPhotoWorkspace({...dependencies,placeMapTarget:place=>workspace.placeMapTarget(place)});
  workspace=createPlaceWorkspace({...dependencies,photos});
  const map=workspace.mapMemoryEvents;
  map.sync(null);
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
  map.sync(null);await new Promise(resolve=>setImmediate(resolve));
  const markup=workspace.workspaceMediaOverview();
  assert.match(markup,/workspace-media-map/);
  assert.ok(markup.includes('data-cesium-pins='));
  map.sync(scene);
  const flights=[],views=[];
  let center=null;
  const viewer={isDestroyed:()=>false,scene:{mode:2,postRender:{addEventListener(){}}},
    camera:{frustum:{left:-100000,right:100000},flyTo:flight=>flights.push(flight),
      setView:view=>{views.push(view);center=view.destination.height>40000 ? null : view.destination;}}};
  const cesium={SceneMode:{SCENE2D:2},Cartesian3:{fromDegrees:(longitude,latitude,height)=>({longitude,latitude,height})},
    SceneTransforms:{worldToWindowCoordinates:(_,point)=>center ? {x:300+(point.longitude-center.longitude)*500,
      y:350+(point.latitude-center.latitude)*500} : {x:300,y:350}}};
  map.attach(viewer,cesium);
  if (restore==='live') {
    assert.equal(flights.length,1,'null → chronological city needs one flight');
    assert.equal(flights[0].destination.latitude,expected.latitude);
    center=expected;viewer.camera.frustum={left:-6000,right:6000};flights[0].complete();
    assert.ok(!cards.innerHTML.includes(other.place==='承德市' ? '承德出生' : '悉尼生活'));
  } else {
    assert.equal(flights.length,0,'Restoring data is not an active-location change');
    assert.equal(map.viewCity(),null);
    assert.equal((cards.innerHTML.match(/class="map-memory-card is-city/g)||[]).length,2);
    assert.ok(views[0].destination.height>40000,'All saved cities must fit on refresh');
  }
  const previousFlights=flights.length,previousViews=views.length;
  applyDerivedWorkspace(state,snapshot);map.sync(scene);
  assert.equal(flights.length,previousFlights,'The same API snapshot must preserve the camera');
  assert.equal(views.length,previousViews);
  state.workspaceFocus={place:other.place,source_sequence:snapshot.source_revision+1};map.sync(scene);
  assert.equal(flights.length,previousFlights,'Question focus is not camera authority');
  assert.equal(state.currentActiveLocation.place,snapshot.current_active_location.place);
  if (redirect_snapshot) {
    applyDerivedWorkspace(state,redirect_snapshot);map.sync(scene);
    assert.equal(flights.length,previousFlights+1,'The saved explicit redirect changes the active location once');
    assert.equal(flights.at(-1).destination.latitude,other.latitude);
    applyDerivedWorkspace(state,redirect_snapshot);map.sync(scene);
    assert.equal(flights.length,previousFlights+1);
  }
  assert.equal(state.timeline.length,2,'Camera changes preserve both canonical memories');
  map.dispose();
}
