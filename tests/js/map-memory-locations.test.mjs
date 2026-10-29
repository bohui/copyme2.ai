import test from 'node:test';
import assert from 'node:assert/strict';
import {createMapMemoryEvents} from '../../apps/web/client/memoir/map-memory-events.mjs';
import {groupPlaces} from '../../apps/web/client/memoir/places.mjs';

const settle = () => new Promise(resolve=>setImmediate(resolve));
const city = {place:'Sydney',granularity:'city',hierarchy:['Earth','Australia','Sydney'],latitude:-33.86,longitude:151.2};
const events = [{id:'school',revision:1,canonical:true,status:'active',title:'Starting school',
  temporal:{precision:'age',expression:'Age 6'},life_stage:'childhood'}];
const supported = {role:'setting',status:'supported',place:city};

function setup(t, readPlaces, options = {}) {
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
    getScope:()=>scope,getStage:()=> 'all',readPlaces,t:key=>key,lifeStageText:()=> 'Childhood',...options});
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

test('childhood filtering can use a loaded early-city suggestion and removes it when its anchor disappears', async t => {
  const input=[{id:'birth',revision:1,canonical:true,status:'active',kind:'event',life_stage:'baby',
    temporal:{precision:'age',expression:'Age 0'}},
  {id:'compound',revision:1,canonical:true,status:'active',kind:'period',life_stage:'childhood',temporal:null}];
  const before=JSON.stringify(input);
  let anchor=true;
  const h=setup(t,async id=>({items:id==='birth' && anchor ? [supported] : [],complete:true}),{
    getEvents:()=>input,getStage:()=> 'childhood',
  });
  h.overlay.sync(h.scene);await settle();
  assert.ok(h.classes.has('has-map-memories'),'The childhood period should appear at the suggested city');
  assert.doesNotMatch(h.toolbar.innerHTML,/mapEventsUnmapped/);
  assert.equal(JSON.stringify(input),before);
  anchor=false;h.setScope('project:2');h.overlay.sync(h.scene);await settle();
  assert.equal(h.classes.has('has-map-memories'),false,'An unavailable anchor must remove its dependent suggestion');
});

test('a conflicting childhood place cannot be replaced by an early-city assumption', async t => {
  const input=[{id:'birth',revision:1,canonical:true,status:'active',kind:'event',life_stage:'baby',
    temporal:{precision:'age',expression:'Age 0'}},
  {id:'compound',revision:1,canonical:true,status:'active',kind:'period',life_stage:'childhood',temporal:null}];
  const h=setup(t,async id=>({items:[id==='birth' ? supported : {...supported,status:'conflicted'}],complete:true}),{
    getEvents:()=>input,getStage:()=> 'childhood',
  });
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

test('canonical locations resolve before a map exists and join the map groups independently', async t => {
  const received=[];
  const h=setup(t,async()=>({items:[{...supported,place:{...city,latitude:null,longitude:null}}],next_cursor:null}),{
    resolvePlaces:async entries=>entries.map(place=>({...place,latitude:city.latitude,longitude:city.longitude})),
    getGroups:entries=>{received.push(...entries);return groupPlaces(entries);},
  });
  h.overlay.sync(null);await settle();
  assert.ok(received.some(place=>place.latitude===city.latitude));
  assert.equal(h.scene.child,undefined,'Location resolution must not require a map DOM container');
  h.overlay.sync(h.scene);
  assert.ok(h.classes.has('has-map-memories'));
});

test('a late geocoding result cannot revive a previous policy scope', async t => {
  const pending=[];
  const h=setup(t,async()=>({items:[supported],next_cursor:null}),{
    resolvePlaces:entries=>new Promise(resolve=>pending.push(()=>resolve(entries))),
  });
  h.overlay.sync(h.scene);await settle();
  h.setScope('project:2');h.overlay.sync(h.scene);await settle();
  pending[0]();await settle();
  assert.equal(h.classes.has('has-map-memories'),false);
  pending[1]();await settle();
  assert.ok(h.classes.has('has-map-memories'));
});
