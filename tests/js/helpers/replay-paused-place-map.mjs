import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createPlaceWorkspace} from '../../../apps/web/client/memoir/place-workspace.mjs';
import {cityEventCards} from '../../../apps/web/client/memoir/map-memory-journey.mjs';

const {project_id,events,links,snapshot} = JSON.parse(readFileSync(0,'utf8'));
const state = {project:{id:project_id,profile:{memory_places:snapshot.places}},
  timeline:events.map(event=>({...event,canonical:true})),lifeStage:'all',chat:[],supabase:{accessToken:'fixture'}};
const cards={innerHTML:'',scrollTop:0,querySelectorAll:()=>[]};
const toolbar={innerHTML:''},overflow={replaceChildren(){}};
const canvas={getContext:()=>new Proxy({},{get:()=>()=>{}})};
const layer={isConnected:true,classList:{toggle(){}},addEventListener(){},querySelectorAll:()=>[],
  querySelector:selector=>({canvas,'.map-memory-cards':cards,'.map-memory-toolbar':toolbar,'.map-memory-overflow':overflow}[selector])};
const scene={isConnected:true,clientWidth:600,clientHeight:700,classList:{toggle(){},contains:()=>true},
  querySelector:()=>layer};
Object.assign(globalThis,{document:{documentElement:{lang:'zh-CN'}},
  window:{addEventListener(){},devicePixelRatio:1,matchMedia:()=>({matches:false})}});
const workspace=createPlaceWorkspace({state,profile:()=>state.project.profile,render(){},
  captureProjectScope:()=>project_id,isCurrentProjectScope:()=>true,lifeStageText:stage=>stage,
  photos:{bindPhotoMemoryActions(){},photoRequestKey:()=>'',pictureWall:()=>'',workspacePictureItems:()=>[]},
  storyApi:async path=>({items:links[events.find(event=>path.includes(event.id)).id]}),
  supabaseApi:async()=>{assert.fail('Supported saved coordinates must not require another geocoding request');}});
const map=workspace.mapMemoryEvents;
map.sync(null);
await new Promise(resolve=>setImmediate(resolve));
assert.deepEqual(cityEventCards(map.nodes()).map(city=>city.city).sort(),['承德市','悉尼'].sort(),
  'An unrelated Shanghai pause must not remove the supported Sydney city card');
map.overview();map.sync(scene);
map.attach({isDestroyed:()=>false,scene:{mode:2,postRender:{addEventListener(){}}},
  camera:{frustum:{left:-100000,right:100000},flyTo(){},setView(){},computeViewRectangle:()=>({
    west:80*Math.PI/180,east:170*Math.PI/180,south:-60*Math.PI/180,north:60*Math.PI/180})}},
  {SceneMode:{SCENE2D:2},Cartesian3:{fromDegrees:(longitude,latitude)=>({longitude,latitude})},
    SceneTransforms:{worldToWindowCoordinates:(_,point)=>({x:point.longitude*2,y:350-point.latitude*2})}});
assert.match(cards.innerHTML,/map-memory-summary">悉尼</);
assert.match(cards.innerHTML,/map-memory-summary">承德市</);
map.dispose();
