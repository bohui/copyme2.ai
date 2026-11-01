import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createFamilyWorkspace} from '../../../apps/web/client/memoir/family-workspace.mjs';
import {createMapMemoryEvents} from '../../../apps/web/client/memoir/map-memory-events.mjs';
import {groupPlaces} from '../../../apps/web/client/memoir/places.mjs';
import {translateWith} from '../../../apps/web/client/i18n.js';

const {project_id,childhood_id,feeds}=JSON.parse(readFileSync(0,'utf8'));
const city={place:'Chengde',hierarchy:['Earth','China','Hebei','Chengde'],granularity:'city',latitude:40.95,longitude:117.96};
const state={project:{id:project_id,profile:{birth_year:1991}},supabase:{accessToken:'fixture'},
  familyFeaturesEnabled:false,timeline:[]};
let current=0,selected;
const family=createFamilyWorkspace({state,render(){},captureProjectScope:()=>project_id,isCurrentProjectScope:()=>true,
  storyApi:async path=>{
    assert.ok(path.startsWith('/v1/story/map-events?'));
    return structuredClone(feeds[current].feed);
  }});
const listeners={},cards={innerHTML:'',scrollTop:0,querySelectorAll:()=>[],getBoundingClientRect:()=>({top:0,bottom:700})};
const toolbar={innerHTML:''},overflow={replaceChildren(){}};
const canvas={getContext:()=>new Proxy({},{get:()=>()=>{}})};
const layer={isConnected:true,classList:{toggle(){}},querySelectorAll:()=>[],
  addEventListener:(name,callback)=>{listeners[name]=callback;},getBoundingClientRect:()=>({left:0,top:0}),
  querySelector:selector=>({'.map-memory-cards':cards,'.map-memory-toolbar':toolbar,'.map-memory-overflow':overflow,canvas}[selector])};
const scene={isConnected:true,clientWidth:600,clientHeight:700,classList:{toggle(){},contains:()=>true},
  append:value=>{scene.child=value;},querySelector:()=>scene.child};
Object.assign(globalThis,{document:{createElement:()=>layer},window:{devicePixelRatio:1,matchMedia:()=>({matches:false})}});
const map=createMapMemoryEvents({getEvents:()=>state.timeline,getGroups:()=>groupPlaces([city]),
  getProfile:()=>state.project.profile,getScope:()=>project_id,getStage:()=> 'all',
  readPlaces:async id=>structuredClone(feeds[current].locations[id]),
  t:(key,values)=>translateWith(`Memoir.workspace.${key}`,values),lifeStageText:stage=>stage,onExplore:id=>{selected=id;}});
map.attach({isDestroyed:()=>false,scene:{mode:2,postRender:{addEventListener(){}}},
  camera:{frustum:{left:-100000,right:100000},flyTo(){}}},
  {SceneMode:{SCENE2D:2},Cartesian3:{fromDegrees:(longitude,latitude)=>({longitude,latitude})},
    SceneTransforms:{worldToWindowCoordinates:()=>({x:300,y:350})}});
for (;current<feeds.length;current++) {
  await family.refreshFamilyContext();
  map.sync(scene);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(state.timeline.length,2,'Birth and the school-compound memory retain separate identities');
  assert.ok(!JSON.stringify(feeds[current].feed).includes('source_refs'),'The map feed must not expose original passages');
  const childhood=state.timeline.find(event=>event.id===childhood_id);
  assert.equal((cards.innerHTML.match(new RegExp(`data-memory-explore="${childhood_id}"`,'g'))||[]).length,1);
  assert.ok(cards.innerHTML.includes(childhood.title));
  if (current===0) {
    assert.match(cards.innerHTML,/Location to confirm/);
    assert.equal(map.nodes().some(node=>node.event.id===childhood_id),false);
    listeners.click({target:{closest:()=>({dataset:{memoryExplore:childhood_id},
      hasAttribute:name=>name==='data-memory-explore'})}});
    assert.equal(selected,childhood_id,'Continue the childhood event instead of the birth event');
  } else {
    assert.doesNotMatch(cards.innerHTML,/Location to confirm/);
    assert.equal(map.nodes().filter(node=>node.event.id===childhood_id).length,1);
  }
}
map.dispose();
