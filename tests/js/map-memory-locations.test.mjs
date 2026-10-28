import test from 'node:test';
import assert from 'node:assert/strict';
import {createMapMemoryEvents} from '../../apps/web/client/memoir/map-memory-events.mjs';
import {groupPlaces} from '../../apps/web/client/memoir/places.mjs';

const settle = () => new Promise(resolve=>setImmediate(resolve));
const city = {place:'Sydney',granularity:'city',hierarchy:['Earth','Australia','Sydney'],latitude:-33.86,longitude:151.2};
const events = [{id:'school',revision:1,canonical:true,status:'active',title:'Starting school',
  temporal:{precision:'age',expression:'Age 6'},life_stage:'childhood'}];
const supported = {role:'setting',status:'supported',place:city};

function setup(t, readPlaces) {
  const toolbar = {innerHTML:''};
  const panel = {hidden:true};
  const layer = {hidden:true,innerHTML:'',addEventListener(){},querySelector:selector=>selector==='.map-memory-toolbar'?toolbar:panel,
    querySelectorAll:()=>[]};
  const classes = new Set();
  const scene = {isConnected:true,querySelector:()=>scene.child,append:value=>{scene.child=value;},
    classList:{toggle:(name,on)=>on?classes.add(name):classes.delete(name)}};
  const original = globalThis.document;
  globalThis.document = {createElement:()=>layer};
  t.after(()=>{if(original===undefined)delete globalThis.document;else globalThis.document=original;});
  let scope='project:1';
  const overlay = createMapMemoryEvents({getEvents:()=>events,getGroups:()=>groupPlaces([city]),getProfile:()=>({}),
    getScope:()=>scope,getStage:()=> 'all',readPlaces,t:key=>key,lifeStageText:()=> 'Childhood'});
  return {overlay,scene,toolbar,classes,setScope:value=>{scope=value;}};
}

test('event locations follow every bounded page and reuse the same revision', async t => {
  const calls=[];
  const h=setup(t,async(id,cursor)=>{
    calls.push([id,cursor]);
    return cursor ? {items:[supported],next_cursor:null} : {items:[],next_cursor:'second'};
  });
  h.overlay.sync(h.scene);
  await settle();
  assert.deepEqual(calls,[['school',undefined],['school','second']]);
  assert.ok(h.classes.has('has-map-memories'));
  h.overlay.sync(h.scene);
  await settle();
  assert.equal(calls.length,2);
});

test('conflicted locations are excluded even when they have a matching city', async t => {
  const h=setup(t,async()=>({items:[{...supported,status:'conflicted'}],next_cursor:null}));
  h.overlay.sync(h.scene);await settle();
  assert.equal(h.classes.has('has-map-memories'),false);
  assert.match(h.toolbar.innerHTML,/mapEventsUnmapped/);
});

test('a late location page cannot paint into a different project or policy scope', async t => {
  const requests=[];
  const h=setup(t,()=>new Promise(resolve=>requests.push(resolve)));
  h.overlay.sync(h.scene);
  h.setScope('another-project:2');
  h.overlay.sync(h.scene);
  requests[0]({items:[supported],next_cursor:null});
  await settle();
  assert.equal(h.classes.has('has-map-memories'),false);
  requests[1]({items:[],next_cursor:null});await settle();
  assert.equal(h.classes.has('has-map-memories'),false);
});

test('failed location reads expose a retry and cannot become an automatic request loop', async t => {
  let calls=0;
  const h=setup(t,async()=>{calls++;throw new Error('private provider detail');});
  h.overlay.sync(h.scene);await settle();
  h.overlay.sync(h.scene);await settle();
  assert.equal(calls,1);
  assert.match(h.toolbar.innerHTML,/data-memory-retry/);
  assert.doesNotMatch(h.toolbar.innerHTML,/private provider detail/);
});
