import test from 'node:test';
import assert from 'node:assert/strict';
import {createPhotoWorkspace} from '../../apps/web/client/memoir/photo-workspace.mjs';
import {createPlaceWorkspace} from '../../apps/web/client/memoir/place-workspace.mjs';
import {albumStackMarkup} from '../../apps/web/client/memoir/map-photo-albums.mjs';
import {placeHistoryKey} from '../../apps/web/client/memoir/places.mjs';
import {responsePhotoCards} from '../../apps/web/client/memoir/interview-photo-turns.mjs';
import vm from 'node:vm';
import {readMemoirClientSource} from './helpers/memoir-source.mjs';
import {groupPlaces,mergePlaces} from '../../apps/web/client/memoir/places.mjs';

const personalId='upload:aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const city={place:'Sydney',granularity:'city',hierarchy:['Earth','Australia','Sydney'],latitude:-33.86,longitude:151.2,period:'1983'};
const school={...city,place:'Newtown',granularity:'suburb',hierarchy:[...city.hierarchy,'Newtown'],latitude:-33.9,longitude:151.18};
const north={place:'Chengde',granularity:'city',hierarchy:['Earth','China','Chengde'],latitude:40.95,longitude:117.96,period:'1983'};
const photo=(place,id)=>({asset_id:id,image_url:`https://photos.example/${id}.jpg`,date_expression:'1983',
  latitude:place.latitude,longitude:place.longitude,allowed_actions:{embed:true}});
const event=(id,age,place)=>({id,revision:1,canonical:true,status:'active',life_stage:'childhood',title:`Memory ${id}`,
  temporal:{expression:`Age ${age}`,precision:'age'},places:[{role:'setting',status:'supported',place}]});

test('map markup keeps the same opening target when the active location changes',async t=>{
  const {places,state}=await setup(t,[]);
  const initial=places.workspaceMediaOverview();
  state.currentActiveLocation=north;state.activeLocationChange=1;
  state.workspaceFocus={place:'School family compound',source_sequence:2};
  assert.equal(places.workspaceMediaOverview(),initial,'The loaded imagery stays mounted while the controller flies');
  assert.match(initial,/data-place-key="all"/);
  assert.match(initial,/data-cesium-latitude="-33.9"/);
  assert.match(initial,/sydney/);
  assert.match(initial,/Chengde/);
});

test('a new workspace revision keeps the current map until its event authority changes', async t=>{
  const {places,state}=await setup(t,[]);
  state.memoryEventPage={...state.memoryEventPage,project_id:'project',map_source:'published_events'};
  state.derivedWorkspace={project_id:'project',policy_epoch:1,source_revision:2,map_source:'published_events'};
  assert.match(places.workspaceMediaOverview(),/data-place-key="all"/,
    'Refresh the event model before choosing the workspace markup');
  state.derivedWorkspace.policy_epoch=2;
  assert.equal(places.workspaceMediaOverview(),'', 'Do not reuse places from an older privacy scope');
  state.memoryEventPage={...state.memoryEventPage,policy_epoch:2,source_revision:2};
  assert.match(places.workspaceMediaOverview(),/data-place-key="all"/);
});

async function setup(t,privatePhotos=[{photo_id:personalId,kind:'private_upload',title:'My school photo',event_ids:['school']}]) {
  for (const [name,value] of Object.entries({document:{documentElement:{lang:'en-AU'}},
    window:{location:{origin:'https://memoir.test'},addEventListener(){},matchMedia:()=>({matches:false,addEventListener(){}})}})) {
    const previous=Object.getOwnPropertyDescriptor(globalThis,name);
    Object.defineProperty(globalThis,name,{value,configurable:true,writable:true});
    t.after(()=>previous ? Object.defineProperty(globalThis,name,previous) : delete globalThis[name]);
  }
  const entries=[city,school,north].map((place,index)=>({...place,pictures:[photo(place,String(index))]}));
  const state={project:{id:'project',profile:{memory_places:entries}},supabase:{user:{id:'owner'},accessToken:'fixture'},
    placeJourney:entries[1],lifeStage:'all',chat:[],timeline:[event('return',40,city),event('school',6,school),event('birth',0,north)],
    workspaceFocus:{place:'Sydney',source_sequence:1},
    photoTurns:{cards:responsePhotoCards},memoryEventPage:{project_id:'project',policy_epoch:1,event_revision:1,source_revision:1}};
  const dependencies={state,profile:()=>state.project.profile,render(){},lifeStageText:()=>'',
    captureProjectScope:()=>JSON.stringify([state.project.id,state.supabase.user.id,state.navigationGeneration]),
    isCurrentProjectScope:scope=>scope===JSON.stringify([state.project.id,state.supabase.user.id,state.navigationGeneration])};
  let places;
  const photos=createPhotoWorkspace({...dependencies,placeMapTarget:entry=>places.placeMapTarget(entry)});
  places=createPlaceWorkspace({...dependencies,photos});
  places.mapMemoryEvents.sync(null);
  await new Promise(resolve=>setImmediate(resolve));
  photos.applyMapPhotos({...state.memoryEventPage,map_photos:privatePhotos},dependencies.captureProjectScope());
  return {places,photos,state,captureProjectScope:dependencies.captureProjectScope};
}

test('desktop fills the map, with chronological events and north-to-south albums that split on zoom',async t=>{
  const {places,photos}=await setup(t);
  const markup=places.workspaceMediaOverview('<button>collapse</button>');
  assert.doesNotMatch(markup,/workspace-media-gallery|<h2>/);
  assert.match(markup,/data-all-places>Whole journey/);
  assert.deepEqual(places.mapMemoryEvents.nodes().map(node=>node.event.id),['birth','school','return']);
  const coarse=places.mapPhotoAlbumsForScene(null,{allPlaces:true,detailed:false});
  assert.deepEqual(coarse.map(album=>album.place),['Chengde','Sydney']);
  assert.equal(coarse[1].pictures[0].photo_id,personalId);
  assert.equal(coarse[1].pictures.length,3);
  const detailed=places.mapPhotoAlbumsForScene(null,{allPlaces:true,detailed:true});
  assert.deepEqual(detailed.map(album=>album.place),['Chengde','Sydney','Newtown']);
  const schoolAlbum=detailed[2];
  assert.equal(schoolAlbum.pictures[0].photo_id,personalId);
  assert.equal(schoolAlbum.latitude,school.latitude);
  const wall=photos.pictureWall(schoolAlbum.pictures);
  assert.ok(wall.indexOf('data-photo-kind="private_upload"')<wall.indexOf('photos.example/1.jpg'));
  assert.match(wall,/data-private-response-photo="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"/);
  const stack=albumStackMarkup(schoolAlbum);
  assert.ok(stack.indexOf('photos.example/1.jpg')<stack.indexOf('data-private-response-photo'),
    'The personal image must be painted on top of the web image in the stack');
});

test('map markup retains every city independently of question focus',async t=>{
  const {places,state}=await setup(t,[]);
  state.workspaceFocus={place:'Chengde',source_sequence:1};
  const markup=places.workspaceMediaOverview();
  assert.match(markup,/data-place-key="all"/);
  assert.match(markup,/sydney/);
  assert.match(markup,/Chengde/);
});

test('unlocated personal photos remain accessible without borrowing a nearby event location',async t=>{
  const {places}=await setup(t,[{photo_id:personalId,kind:'private_upload',title:'Unlocated',event_ids:[]}]);
  const albums=places.mapPhotoAlbumsForScene(null,{allPlaces:true,detailed:true});
  const personal=albums.find(album=>album.key==='personal:unlocated');
  assert.equal(personal.pinned,false);
  assert.equal(personal.latitude,undefined);
  assert.equal(personal.pictures.length,1);
  assert.ok(albums.filter(album=>album.pinned).every(album=>!album.pictures.some(photo=>photo.photo_id===personalId)));
});

test('city zoom filters reference and personal photos to that city',async t=>{
  const {places}=await setup(t);
  const key=places.mapMemoryEvents.nodes().find(node=>node.place==='Newtown').groupKey;
  const albums=places.mapPhotoAlbumsForScene(null,{allPlaces:true,detailed:true,cityKey:key});
  assert.deepEqual(albums.map(album=>album.place),['Sydney','Newtown']);
  assert.equal(albums.find(album=>album.place==='Newtown').pictures[0].photo_id,personalId);
  assert.deepEqual(places.mapPhotoAlbumsForScene(null,{allPlaces:true,detailed:true,cityKey:null}),[]);
});

test('streamed personal photos are bounded by the current owner, visit, and event revision',async t=>{
  const {photos,state,captureProjectScope}=await setup(t);
  const initial=photos.mapPhotos();
  assert.equal(initial.length,1);
  state.memoryEventPage.event_revision++;
  assert.deepEqual(photos.mapPhotos(),[],'An older photo snapshot cannot supply the current association');
  photos.applyMapPhotos({...state.memoryEventPage,map_photos:initial},captureProjectScope());
  assert.equal(photos.mapPhotos().length,1);
  state.navigationGeneration=1;
  assert.deepEqual(photos.mapPhotos(),[]);
  photos.applyMapPhotos({...state.memoryEventPage,map_photos:initial},captureProjectScope());
  state.supabase.user.id='other';
  assert.deepEqual(photos.mapPhotos(),[]);
});

test('a photo associated with multiple locations stays unpinned',async t=>{
  const {places}=await setup(t,[{photo_id:personalId,kind:'private_upload',title:'Two memories',event_ids:['birth','school']}]);
  const albums=places.mapPhotoAlbumsForScene(null,{allPlaces:true,detailed:true});
  assert.equal(albums.find(album=>album.key==='personal:unlocated').pictures[0].photo_id,personalId);
  assert.ok(albums.filter(album=>album.pinned).every(album=>!album.pictures.some(photo=>photo.photo_id===personalId)));
});

test('a photo withdrawal on Atlas clears the existing album association',async t=>{
  const {photos,places,state,captureProjectScope}=await setup(t);
  assert.equal(places.mapPhotoAlbum(placeHistoryKey(school)).pictures[0].photo_id,personalId);
  photos.applyMapPhotos({...state.memoryEventPage,map_photos:[]},captureProjectScope());
  assert.ok(!places.mapPhotoAlbum(placeHistoryKey(school)).pictures.some(photo=>photo.photo_id===personalId));
});
