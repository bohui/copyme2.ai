import test from 'node:test';
import assert from 'node:assert/strict';
import {createMapMemoryEvents} from '../../apps/web/client/memoir/map-memory-events.mjs';
import {groupPlaces} from '../../apps/web/client/memoir/places.mjs';
import {translateWith} from '../../apps/web/client/i18n.js';

const chengde={place:'Chengde',granularity:'city',hierarchy:['Earth','China','Chengde'],latitude:40.95,longitude:117.96};
const shanghai={place:'Shanghai',granularity:'city',hierarchy:['Earth','China','Shanghai'],latitude:31.23,longitude:121.47};
const sydney={place:'Sydney',granularity:'city',hierarchy:['Earth','Australia','Sydney'],latitude:-33.87,longitude:151.21};
const event=(id,place,year,stage)=>({id,status:'active',kind:'event',title:id,life_stage:stage,
  yearConfidenceScore:.9,temporal:year ? {expression:String(year),precision:'year',year_start:year} : null,
  places:[{role:'setting',status:'supported',place}]});

function mapFixture(t, mobile=false) {
  const globals={window:globalThis.window,document:globalThis.document};
  t.after(()=>Object.assign(globalThis,globals));
  const listeners={},cards={innerHTML:'',scrollTop:0,querySelectorAll:()=>[],getBoundingClientRect:()=>({top:0,bottom:700})};
  const toolbar={innerHTML:'',offsetHeight:40},detail={hidden:true},overflow={replaceChildren(){},querySelector:()=>null};
  const ctx=new Proxy({},{get:()=>()=>{}}),canvas={getContext:()=>ctx};
  const layer={isConnected:true,clientWidth:600,clientHeight:700,
    classList:{toggle(){}},addEventListener:(name,callback)=>{listeners[name]=callback;},querySelectorAll:()=>[],
    getBoundingClientRect:()=>({left:0,top:0}),
    querySelector:s=>({'.map-memory-cards':cards,'.map-memory-toolbar':toolbar,'.map-memory-detail':detail,
      '.map-memory-overflow':overflow,canvas}[s])};
  const scene={isConnected:true,clientWidth:600,clientHeight:700,classList:{toggle(){},contains:()=>true},
    append(value){this.child=value;},querySelector(){return this.child;}};
  globalThis.window={devicePixelRatio:1,matchMedia:q=>({matches:q.includes('max-width') && mobile})};
  globalThis.document={createElement:()=>layer};
  let redraw,center=null;
  const viewer={isDestroyed:()=>false,scene:{mode:2,postRender:{addEventListener:cb=>{redraw=cb;return ()=>{};}}},
    camera:{frustum:{left:-100000,right:100000},flyTo(){}}};
  const cesium={SceneMode:{SCENE2D:2},Cartesian3:{fromDegrees:(longitude,latitude)=>({longitude,latitude})},
    SceneTransforms:{worldToWindowCoordinates:(_,p)=>center
      ? {x:300+(p.longitude-center.longitude)*500,y:350+(p.latitude-center.latitude)*500}
      : {x:300,y:350}}};
  const events=[event('Sydney arrival',sydney,2012,'young_adulthood'),event('University',shanghai,2007,'young_adulthood'),
    event('Birth',chengde,1983,'baby'),event('Growing up',chengde,null,'childhood')];
  const map=createMapMemoryEvents({getEvents:()=>events,getGroups:()=>groupPlaces([chengde,shanghai,sydney]),
    getProfile:()=>({birth_year:1983}),getScope:()=> 'fixture',getStage:()=> 'all',
    t:(key,values)=>translateWith(`Memoir.workspace.${key}`,values),lifeStageText:stage=>stage,onExplore(){}});
  map.sync(scene);map.attach(viewer,cesium);
  return {map,cards,click(key){listeners.click({target:{closest:()=>({dataset:{mapMemory:key},hasAttribute:()=>false})}});},
    zoom(place){center=place;viewer.camera.frustum={left:-4000,right:4000};redraw();}};
}

test('desktop overview merges each city and sorts by its first event', t=>{
  const {cards}=mapFixture(t);
  assert.equal((cards.innerHTML.match(/class="map-memory-card is-city/g)||[]).length,3);
  assert.ok(cards.innerHTML.indexOf('Chengde')<cards.innerHTML.indexOf('Shanghai'));
  assert.ok(cards.innerHTML.indexOf('Shanghai')<cards.innerHTML.indexOf('Sydney'));
  assert.match(cards.innerHTML,/2 events/);
});

test('city zoom lists only that city’s events on desktop and mobile', t=>{
  for (const mobile of [false,true]) {
    const {cards,zoom}=mapFixture(t,mobile);
    cards.scrollTop=120;
    zoom(chengde);
    assert.match(cards.innerHTML,/Birth/);
    assert.match(cards.innerHTML,/Growing up/);
    assert.doesNotMatch(cards.innerHTML,/Sydney arrival|University/);
    assert.equal(cards.scrollTop,0,'A different city view starts at the earliest event');
  }
});

test('clicking a city expands its chronological events inside the city list', t=>{
  const {map,cards,click}=mapFixture(t);
  const key=`city:${map.nodes().find(node=>node.city==='Chengde').groupKey}`;
  click(key);
  assert.match(cards.innerHTML,/Growing up/);
  assert.match(cards.innerHTML,/aria-expanded="true"/);
  assert.match(cards.innerHTML,/Shanghai/);
  click(key);
  assert.doesNotMatch(cards.innerHTML,/Growing up/);
});
