import test from 'node:test';
import assert from 'node:assert/strict';
import {createPhotoWorkspace} from '../../apps/web/client/memoir/photo-workspace.mjs';
import {createPlaceWorkspace} from '../../apps/web/client/memoir/place-workspace.mjs';
import {albumStackMarkup} from '../../apps/web/client/memoir/map-photo-albums.mjs';
import {placeHistoryKey} from '../../apps/web/client/memoir/places.mjs';
import {responsePhotoCards} from '../../apps/web/client/memoir/interview-photo-turns.mjs';

const personalId='upload:aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const city={place:'Sydney',granularity:'city',hierarchy:['Earth','Australia','Sydney'],latitude:-33.86,longitude:151.2,period:'1983'};
const school={...city,place:'Newtown',granularity:'suburb',hierarchy:[...city.hierarchy,'Newtown'],latitude:-33.9,longitude:151.18};
const north={place:'Chengde',granularity:'city',hierarchy:['Earth','China','Chengde'],latitude:40.95,longitude:117.96,period:'1983'};
const photo=(place,id)=>({asset_id:id,image_url:`https://photos.example/${id}.jpg`,date_expression:'1983',
  latitude:place.latitude,longitude:place.longitude,allowed_actions:{embed:true}});
const event=(id,age,place)=>({id,revision:1,canonical:true,status:'active',life_stage:'childhood',title:`Memory ${id}`,
  temporal:{expression:`Age ${age}`,precision:'age'},places:[{role:'setting',status:'supported',place}]});

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
    photoTurns:{cards:responsePhotoCards},memoryEventPage:{policy_epoch:1,event_revision:1,source_revision:1}};
  const calls=[];
  const dependencies={state,profile:()=>state.project.profile,render(){},lifeStageText:()=>'',
    captureProjectScope:()=>JSON.stringify([state.project.id,state.supabase.user.id]),
    isCurrentProjectScope:scope=>scope===JSON.stringify([state.project.id,state.supabase.user.id]),
    api:async path=>{calls.push(path);return {photos:typeof privatePhotos==='function' ? await privatePhotos() : privatePhotos};}};
  let places;
  const photos=createPhotoWorkspace({...dependencies,placeMapTarget:entry=>places.placeMapTarget(entry)});
  places=createPlaceWorkspace({...dependencies,photos});
  places.mapMemoryEvents.sync(null);
  await new Promise(resolve=>setImmediate(resolve));
  await photos.refreshMapPhotos();
  return {places,photos,state,calls};
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

test('unlocated personal photos remain accessible without borrowing a nearby event location',async t=>{
  const {places}=await setup(t,[{photo_id:personalId,kind:'private_upload',title:'Unlocated',event_ids:[]}]);
  const albums=places.mapPhotoAlbumsForScene(null,{allPlaces:true,detailed:true});
  const personal=albums.find(album=>album.key==='personal:unlocated');
  assert.equal(personal.pinned,false);
  assert.equal(personal.latitude,undefined);
  assert.equal(personal.pictures.length,1);
  assert.ok(albums.filter(album=>album.pinned).every(album=>!album.pictures.some(photo=>photo.photo_id===personalId)));
});

test('personal photo reads are bounded by the current owner and event revision',async t=>{
  const {photos,state,calls}=await setup(t);
  assert.equal(photos.mapPhotos().length,1);
  await photos.refreshMapPhotos();
  assert.equal(calls.length,1);
  state.memoryEventPage.event_revision++;
  assert.equal(photos.mapPhotos().length,0,'Do not reuse an old location association after canonical events change');
  await photos.refreshMapPhotos();
  assert.equal(calls.length,2);
  state.navigationGeneration=1;
  assert.equal(photos.mapPhotos().length,0,'A new navigation cannot reuse the previous read');
  await photos.refreshMapPhotos();
  state.supabase.user.id='other';
  assert.deepEqual(photos.mapPhotos(),[]);
});

test('a photo associated with multiple locations stays unpinned',async t=>{
  const {places}=await setup(t,[{photo_id:personalId,kind:'private_upload',title:'Two memories',event_ids:['birth','school']}]);
  const albums=places.mapPhotoAlbumsForScene(null,{allPlaces:true,detailed:true});
  assert.equal(albums.find(album=>album.key==='personal:unlocated').pictures[0].photo_id,personalId);
  assert.ok(albums.filter(album=>album.pinned).every(album=>!album.pictures.some(photo=>photo.photo_id===personalId)));
});

test('an unavailable personal photo read exposes retry and recovers without stale locations',async t=>{
  let fail=true;
  const {photos,places}=await setup(t,()=>{
    if(fail) throw new Error('Temporary read failure');
    return [{photo_id:personalId,kind:'private_upload',title:'Recovered',event_ids:['school']}];
  });
  assert.equal(photos.mapPhotosUnavailable(),true);
  assert.equal(places.mapPhotoAlbum('personal:unlocated').status,'error');
  fail=false;
  await photos.refreshMapPhotos({force:true});
  assert.equal(photos.mapPhotosUnavailable(),false);
  assert.equal(places.mapPhotoAlbum(placeHistoryKey(school)).pictures[0].photo_id,personalId);
});
