import test from 'node:test';
import assert from 'node:assert/strict';
import {createMapMemoryEvents} from '../../apps/web/client/memoir/map-memory-events.mjs';
import {groupPlaces} from '../../apps/web/client/memoir/places.mjs';

const city = {place:'Sydney',granularity:'city',hierarchy:['Earth','Australia','Sydney'],latitude:-33.86,longitude:151.2};
const events = [{id:'school',revision:1,canonical:true,status:'active',title:'Starting school',
  temporal:{precision:'age',expression:'Age 6'},life_stage:'childhood'}];
const supported = {role:'setting',status:'supported',place:city};

function setup(t, options = {}) {
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
    getScope:()=>scope,getStage:()=> 'all',t:key=>key,lifeStageText:()=> 'Childhood',...options});
  return {overlay,scene,toolbar,classes,setScope:value=>{scope=value;}};
}

test('an Atlas page supplies its locations before the map mounts', t => {
  const h=setup(t,{getEvents:()=>[{...events[0],places:[supported]}]});
  h.overlay.sync(null);
  assert.equal(h.overlay.nodes().length,1);
  assert.equal(h.scene.child,undefined);
  h.overlay.sync(h.scene);
  assert.ok(h.classes.has('has-map-memories'));
});

test('a conflicting snapshot removes the prior pin even when its metadata names a city', t => {
  let event={...events[0],places:[supported]};
  const h=setup(t,{getEvents:()=>[event]});
  h.overlay.sync(h.scene);
  assert.equal(h.overlay.nodes().length,1);
  event={...event,revision:2,places:[],location:city,locationConfidenceScore:.3,place_conflicts:['setting']};
  h.setScope('project:2');
  h.overlay.sync(h.scene);
  assert.equal(h.overlay.nodes().length,0);
});

test('a failed continuation leaves the existing cards visible with a reload action', t => {
  const h=setup(t,{getEvents:()=>[{...events[0],places:[supported]}],getPage:()=>({page_error:true})});
  h.overlay.sync(h.scene);
  assert.equal(h.overlay.nodes().length,1);
  assert.match(h.toolbar.innerHTML,/savedPageChanged/);
  assert.match(h.toolbar.innerHTML,/data-memory-more[^]*reloadSavedPages/);
});
