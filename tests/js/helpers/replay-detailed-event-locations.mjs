import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createPlaceWorkspace} from '../../../apps/web/client/memoir/place-workspace.mjs';
import {cityEventCards,memoryEventCardMarkup,memoryTrailLegs} from '../../../apps/web/client/memoir/map-memory-journey.mjs';
const {page,locations,grouping}=JSON.parse(readFileSync(0,'utf8'));
Object.assign(globalThis,{document:{documentElement:{lang:'zh-CN'}},window:{matchMedia:()=>({matches:false})}});
const profile={memory_places:[],birth_year:1983};
const state={project:{id:page.project_id,profile},timeline:page.events.map(event=>({...event,canonical:true})),
  memoryEventPage:page,lifeStage:'all',chat:[],supabase:{accessToken:'fixture',user:{id:'owner'}}};
const workspace=createPlaceWorkspace({state,profile:()=>profile,render(){},lifeStageText:stage=>stage,
  captureProjectScope:()=>page.project_id,isCurrentProjectScope:()=>true,
  storyApi:async path=>{
    const event=page.events.find(event=>path.includes(`/${event.id}/places`));
    assert.ok(event);return locations[event.id];
  },supabaseApi:async(path,options)=>{
    const body=JSON.parse(options.body);
    assert.equal(body.places.length,1);
    return grouping[body.places[0].place];
  },photos:{bindPhotoMemoryActions(){},favoritePhotoWall:()=>'',pictureWall:()=>'',
    photoRequestKey:()=>'',renderablePictureItems:()=>[],workspacePictureItems:()=>[]}});
workspace.mapPhotoAlbums.sync=()=>{};
workspace.mapMemoryEvents.sync(null);
await new Promise(resolve=>setImmediate(resolve));
const nodes=workspace.mapMemoryEvents.nodes();
assert.equal(nodes.length,3,'A public hospital must survive the real workspace merge');
const local=nodes.filter(node=>node.city==='承德市');
assert.deepEqual(local.map(node=>node.place),['承德市附属医院','大石庙镇']);
assert.ok(local.every(node=>!node.cityOnly));
assert.notEqual(local[0].latitude,local[1].latitude);
const cities=cityEventCards(nodes);
assert.equal(cities.length,2);
assert.equal(cities.find(city=>city.city==='承德市').count,2);
assert.equal(memoryTrailLegs(local).length,1,'Distinct local event settings create a footprint leg');
for (const node of local) {
  const markup=memoryEventCardMarkup(node,{t:key=>key,lifeStageText:stage=>stage});
  assert.ok(markup.includes(`class="map-memory-location"><span data-memory-text>${node.place}</span>`));
}
assert.equal(profile.memory_places.length,0,'Resolving event places must not rewrite city journey history');
workspace.mapMemoryEvents.dispose();
