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

function mapFixture(t, mobile=false, extraPlaces=[], savedEvents, canAddMemory=true, settings={}) {
  const globals={window:globalThis.window,document:globalThis.document,Image:globalThis.Image,localStorage:globalThis.localStorage};
  t.after(()=>Object.assign(globalThis,globals));
  const listeners={},focusCalls=[],cards={innerHTML:'',scrollTop:0,querySelectorAll:()=>[],getBoundingClientRect:()=>({top:0,bottom:700})};
  const toolbar={innerHTML:'',offsetHeight:40},overflow={replaceChildren(){},querySelector:()=>null};
  const footprints=[];
  let stamp;
  const ctx=new Proxy({translate:(x,y)=>{stamp={x,y};},drawImage:(_,x,y,width,height)=>footprints.push({...stamp,width,height})},
    {get:(target,key)=>target[key] || (()=>{})}),canvas={getContext:()=>ctx};
  const layer={isConnected:true,clientWidth:600,clientHeight:700,
    classList:{toggle(){}},addEventListener:(name,callback)=>{listeners[name]=callback;},
    querySelectorAll:selector=>selector==='[data-map-memory]' ? map.nodes().map(node=>({
      dataset:{mapMemory:node.key},focus:()=>focusCalls.push(node.key)})) : [],
    getBoundingClientRect:()=>({left:0,top:0}),
    querySelector:s=>({'.map-memory-cards':cards,'.map-memory-toolbar':toolbar,
      '.map-memory-overflow':overflow,canvas}[s])};
  const scene={isConnected:true,clientWidth:600,clientHeight:700,classList:{toggle(){},contains:()=>true},
    append(value){this.child=value;},querySelector(){return this.child;}};
  globalThis.window={devicePixelRatio:1,matchMedia:q=>({matches:q.includes('max-width') && mobile})};
  globalThis.document={createElement:()=>layer};
  globalThis.Image=class {complete=true;naturalWidth=16;};
  const values=settings.values || new Map();
  globalThis.localStorage=settings.storage || {getItem:key=>values.get(key) ?? null,setItem:(key,value)=>values.set(key,value)};
  let redraw,moveEnd,finishFlight,center=settings.center || null;
  const flights=[],views=[],explored=[],added=[];
  const viewer={isDestroyed:()=>false,scene:{mode:2,postRender:{addEventListener:cb=>{redraw=cb;return ()=>{};}}},
    camera:{frustum:{left:-100000,right:100000},setView:view=>{views.push(view);center=view.destination;},
      flyTo:flight=>{flights.push(flight);finishFlight=flight.complete;},
      moveEnd:{addEventListener:callback=>{moveEnd=callback;return ()=>{moveEnd=null;};}}}};
  const cesium={SceneMode:{SCENE2D:2},Cartesian3:{fromDegrees:(longitude,latitude,height)=>({longitude,latitude,height})},
    SceneTransforms:{worldToWindowCoordinates:(_,p)=>center
      ? {x:300+(p.longitude-center.longitude)*500,y:350+(p.latitude-center.latitude)*500}
      : {x:300,y:350}}};
  const events=savedEvents || [event('Sydney arrival',sydney,2012,'young_adulthood'),event('University',shanghai,2007,'young_adulthood'),
    event('Birth',chengde,1983,'baby'),event('Growing up',chengde,null,'childhood')];
  const map=createMapMemoryEvents({getEvents:()=>events,getGroups:()=>groupPlaces(settings.places || [chengde,shanghai,sydney,...extraPlaces]),
    getProfile:()=>({birth_year:1983}),getScope:()=>settings.scope || 'fixture',getIdentity:()=>settings.identity || 'fixture',
    getInitialPlace:()=>settings.initialPlace || null,getStage:()=> 'all',
    getQuestionFocus:()=>settings.questionFocus || null,
    t:(key,values)=>translateWith(`Memoir.workspace.${key}`,values),lifeStageText:stage=>stage,
    getCanAddMemory:()=>canAddMemory,onAdd:()=>added.push('add_memory'),onExplore:id=>explored.push(id)});
  map.sync(scene);map.attach(viewer,cesium,settings.arrivalCity);
  const initialFlights=flights.slice();
  flights.length=0;
  return {map,cards,flights,views,initialFlights,explored,added,focusCalls,footprints,markup:()=>layer.innerHTML,refresh:()=>map.sync(scene),hidden:()=>layer.hidden,
    add(){listeners.click({target:{closest:()=>({dataset:{},hasAttribute:name=>name==='data-memory-add'})}});},
    setCanAddMemory(value){canAddMemory=value;map.sync(scene);},
    remount(){map.dispose();scene.child=null;center=null;viewer.camera.frustum={left:-100000,right:100000};map.sync(scene);map.attach(viewer,cesium);},
    click(key){listeners.click({target:{closest:()=>({dataset:{mapMemory:key},hasAttribute:()=>false})}});},
    expand(groupKey){
      const target={dataset:{memoryCity:groupKey},hasAttribute:name=>name==='data-memory-city'};
      document.activeElement=target;
      listeners.click({target:{closest:()=>target}});
    },
    explore(id){listeners.click({target:{closest:()=>({dataset:{memoryExplore:id},hasAttribute:name=>name==='data-memory-explore'})}});},
    zoom(place,span=8000){center=place;viewer.camera.frustum={left:-span/2,right:span/2};footprints.length=0;finishFlight?.();finishFlight=null;redraw();moveEnd?.();}};
}

test('panning outside every linked city clears the event cards at every zoom and restores only visible cities',t=>{
  const empty={longitude:0,latitude:0};
  for(const mobile of [false,true]) {
    const {map,cards,zoom}=mapFixture(t,mobile);
    for(const span of [200000,8000,80000]) {
      zoom(empty,span);
      assert.equal(cards.innerHTML,'','An overview must not retain offscreen city cards');
    }
    zoom(chengde,80000);
    assert.match(cards.innerHTML,/Chengde/);
    assert.doesNotMatch(cards.innerHTML,/Sydney|Shanghai/);
    zoom(chengde);
    assert.match(cards.innerHTML,/Birth/);
    zoom(empty);
    assert.equal(cards.innerHTML,'','The selected city must disappear as soon as it leaves the viewport');
    zoom(null,200000);
    assert.equal((cards.innerHTML.match(/class="map-memory-card is-city/g)||[]).length,3);
    assert.equal(map.viewCity(),null);
  }
});

test('each city card has its own add-memory action without expanding or continuing an event', t=>{
  for (const mobile of [false,true]) {
    const {cards,flights,explored,added,add,zoom}=mapFixture(t,mobile);
    assert.equal((cards.innerHTML.match(/data-memory-add/g)||[]).length,3);
    assert.match(cards.innerHTML,/data-memory-add[^>]*>Add a memory<\/button>/);
    add();
    assert.deepEqual(added,['add_memory']);
    assert.deepEqual(explored,[]);
    assert.equal(flights.length,0);
    zoom(chengde);
    assert.doesNotMatch(cards.innerHTML,/data-memory-add/,'Add memory belongs to the city card, not each individual event');
  }
});

test('an opening flight already framed on its city does not trigger another fast zoom',t=>{
  const settings={initialPlace:chengde,arrivalCity:groupPlaces([chengde])[0].key,center:chengde};
  const {map,cards,initialFlights}=mapFixture(t,false,[],undefined,true,settings);
  assert.equal(initialFlights.length,0,'The event overlay must reuse the finished opening camera view');
  assert.equal(map.viewCity(),settings.arrivalCity);
  assert.match(cards.innerHTML,/Birth/);
});

test('provisional locations join city summaries and low-confidence dates use a small question mark', t=>{
  const birth={...event('Birth',chengde,1983,'baby'),locationConfidenceScore:1,yearConfidenceScore:1};
  const childhood={...event('School compound',chengde,null,'childhood'),canonical:true,revision:1,places:[],
    location:chengde,locationConfidenceScore:.3,yearConfidenceScore:.3,
    temporal_estimate:{year_start:1986,year_end:1995,age_start:3,age_end:12,confidence:.3,rationale:'A broad childhood estimate.'}};
  const {map,cards,refresh,zoom}=mapFixture(t,false,[],[birth,childhood,event('Sydney arrival',sydney,2012,'young_adulthood')]);
  assert.deepEqual(map.nodes().map(node=>node.event.id),['Birth','School compound','Sydney arrival']);
  assert.equal((cards.innerHTML.match(/class="map-memory-card is-city/g)||[]).length,2);
  assert.doesNotMatch(cards.innerHTML,/School compound|data-memory-explore|Location to confirm|Age not yet known|Year not yet known/);
  assert.match(cards.innerHTML,/map-memory-question/);
  zoom(chengde);
  assert.match(cards.innerHTML,/School compound/);
  assert.match(cards.innerHTML,/1986/);
  assert.match(cards.innerHTML,/1995/);
  assert.match(cards.innerHTML,/map-memory-question/);
  childhood.locationConfidenceScore=.5;
  childhood.yearConfidenceScore=.5;
  childhood.temporal_estimate.confidence=.5;
  childhood.revision++;
  refresh();
  assert.doesNotMatch(cards.innerHTML,/map-memory-question/,'Exactly 50% does not get the below-50% marker');
});

test('city add-memory actions respect loading and payment restrictions and update when they clear', t=>{
  const {cards,added,add,setCanAddMemory}=mapFixture(t,false,[],undefined,false);
  assert.equal((cards.innerHTML.match(/data-memory-add disabled/g)||[]).length,3);
  add();
  assert.deepEqual(added,[]);
  setCanAddMemory(true);
  assert.doesNotMatch(cards.innerHTML,/data-memory-add disabled/);
  add();
  assert.deepEqual(added,['add_memory']);
});

test('reopening a collapsed map restores the last active city without replaying its flight', t=>{
  const events=[event('Birth',chengde,1983,'baby'),event('Sydney arrival',sydney,2012,'young_adulthood')];
  const {map,cards,flights,views,expand,zoom,remount}=mapFixture(t,false,[],events);
  zoom(sydney);
  expand(map.nodes().find(node=>node.city==='Sydney').groupKey);
  flights.length=0;
  remount();
  assert.equal(flights.length,0,'A recreated viewer must reuse the page animation cache');
  assert.ok(Math.abs(views[0].destination.longitude-sydney.longitude)<1e-9,'Restore Sydney instead of framing all cities');
  assert.equal(views[0].destination.latitude,sydney.latitude);
  assert.ok(views[0].destination.height<=40000);
  zoom(sydney);
  assert.equal(map.viewCity(),map.nodes().find(node=>node.city==='Sydney').groupKey);
  assert.match(cards.innerHTML,/Sydney arrival/);
  assert.doesNotMatch(cards.innerHTML,/Birth|class="map-memory-card is-city/);
});

test('refresh restores the selected city from storage on desktop and phone', t=>{
  for (const mobile of [false,true]) {
    const settings={values:new Map(),initialPlace:shanghai};
    const first=mapFixture(t,mobile,[],undefined,true,settings);
    assert.equal(first.initialFlights[0].destination.latitude,shanghai.latitude);
    first.expand(first.map.nodes().find(node=>node.city==='Sydney').groupKey);
    first.map.dispose();
    const refreshed=mapFixture(t,mobile,[],undefined,true,settings);
    assert.equal(refreshed.initialFlights.length,1);
    assert.equal(refreshed.initialFlights[0].destination.latitude,sydney.latitude);
    assert.ok(Math.abs(refreshed.initialFlights[0].destination.longitude-sydney.longitude)<1e-9);
    assert.ok(refreshed.initialFlights[0].destination.height<=40000);
    assert.match(refreshed.cards.innerHTML,/Sydney arrival/);
    assert.doesNotMatch(refreshed.cards.innerHTML,/University|Birth|class="map-memory-card is-city/);
  }
});

test('existing saved city choices migrate to stable city scopes across same-city replies',t=>{
  const questionFocus={place:'Chengde',source_sequence:1};
  const savedCity=groupPlaces([sydney])[0].key;
  const settings={initialPlace:chengde,questionFocus,values:new Map([['memory-spark-map-city:fixture',
    JSON.stringify({scope:JSON.stringify(['fixture',questionFocus]),city:savedCity})]])};
  const fixture=mapFixture(t,false,[],undefined,true,settings);
  assert.equal(fixture.initialFlights[0].destination.latitude,sydney.latitude);
  settings.questionFocus={...questionFocus,source_sequence:2};fixture.map.dispose();
  const refreshed=mapFixture(t,false,[],undefined,true,settings);
  assert.equal(refreshed.initialFlights[0].destination.latitude,sydney.latitude);
});

test('the question city controls the flight while its event list waits until the city is in view',t=>{
  for (const mobile of [false,true]) {
    const settings={initialPlace:sydney,questionFocus:{place:'Chengde',source_sequence:1},center:sydney};
    const {map,cards,initialFlights,zoom}=mapFixture(t,mobile,[],undefined,true,settings);
    assert.equal(initialFlights[0].destination.latitude,chengde.latitude);
    assert.equal(map.viewCity(),groupPlaces([chengde])[0].key,'Photos share the question city while the camera is still elsewhere');
    assert.equal(cards.innerHTML,'','Do not show the destination cards while that city is outside the view');
    zoom(chengde);
    assert.match(cards.innerHTML,/Birth|Growing up/);
    assert.doesNotMatch(cards.innerHTML,/Sydney arrival|University/);
  }
});

test('two cities from one source wait for the question to confirm the active city',t=>{
  const places=[chengde,sydney].map(place=>({...place,source_sequence:1}));
  const settings={places,initialPlace:places[1]};
  const fixture=mapFixture(t,false,[],undefined,true,settings);
  assert.equal(fixture.initialFlights.length,0,'Extraction order cannot choose between two cities');
  assert.equal(fixture.cards.innerHTML,'');
  settings.questionFocus={place:'Chengde',source_sequence:1};
  fixture.refresh();
  assert.equal(fixture.flights.length,1);
  assert.equal(fixture.flights[0].destination.latitude,chengde.latitude);
});

test('continuing the conversation in the same city never reframes the camera',t=>{
  const settings={initialPlace:chengde,questionFocus:{place:'Chengde',source_sequence:1},center:chengde};
  const fixture=mapFixture(t,false,[],undefined,true,settings);
  fixture.zoom(chengde);fixture.flights.length=0;
  settings.questionFocus={place:'Chengde',source_sequence:2};
  settings.scope='fixture:next-reply';
  fixture.refresh();
  assert.equal(fixture.flights.length,0,'A new reply sequence in the same city must not fly again');
  assert.equal(fixture.views.length,0,'Same-city replies must also preserve the current zoom');
});

test('automatic returns to a city use the page cache while refresh can replay the flight',t=>{
  const settings={initialPlace:chengde,questionFocus:{place:'Chengde',source_sequence:1},center:chengde};
  const fixture=mapFixture(t,false,[],undefined,true,settings);
  fixture.zoom(chengde);fixture.flights.length=0;
  settings.questionFocus={place:'Sydney',source_sequence:2};
  fixture.refresh();
  assert.equal(fixture.flights.length,1,'A confirmed first visit to a new city should fly');
  fixture.zoom(sydney);fixture.flights.length=0;
  settings.questionFocus={place:'Chengde',source_sequence:3};
  fixture.refresh();
  assert.equal(fixture.flights.length,0,'An already animated city should return without another flight');
  assert.equal(fixture.views.at(-1).destination.latitude,chengde.latitude);
  const refreshed=mapFixture(t,false,[],undefined,true,settings);
  assert.equal(refreshed.initialFlights.length,1,'A fresh page has a fresh animation cache');
});

test('a later two-city extraction keeps the current city until its question focus arrives',t=>{
  const settings={places:[chengde,sydney],initialPlace:chengde,questionFocus:{place:'Chengde',source_sequence:1},center:chengde};
  const fixture=mapFixture(t,false,[],undefined,true,settings);
  fixture.zoom(chengde);fixture.flights.length=0;
  settings.places=[chengde,sydney].map(place=>({...place,source_sequence:2}));
  settings.initialPlace=settings.places[1];settings.scope='fixture:new-extraction';
  fixture.refresh();
  assert.equal(fixture.flights.length,0);
  assert.match(fixture.cards.innerHTML,/Birth/);
  assert.doesNotMatch(fixture.cards.innerHTML,/Sydney arrival/);
  settings.questionFocus={place:'Sydney',source_sequence:2};fixture.refresh();
  assert.equal(fixture.flights.length,1);
  assert.equal(fixture.flights[0].destination.latitude,sydney.latitude);
});

test('event-only city previews wait for question focus without exposing another project’s city',t=>{
  const settings={initialPlace:chengde,questionFocus:{place:'Chengde',source_sequence:1},center:chengde};
  const fixture=mapFixture(t,false,[],undefined,true,settings);
  fixture.zoom(chengde);fixture.flights.length=0;
  settings.identity='other-project';settings.scope='other-project';settings.questionFocus=null;
  settings.initialPlace={...chengde,preview:true};fixture.refresh();
  assert.equal(fixture.map.activeCity(),undefined);
  assert.equal(fixture.flights.length,0);
  settings.questionFocus={place:'Chengde',source_sequence:2};fixture.refresh();
  assert.equal(fixture.flights.length,1,'A different project has its own animation cache');
});

test('a city reached by panning or zooming becomes the saved fly-to target', t=>{
  const settings={values:new Map()};
  const first=mapFixture(t,false,[],undefined,true,settings);
  first.zoom(chengde);
  first.map.dispose();
  const refreshed=mapFixture(t,false,[],undefined,true,settings);
  assert.equal(refreshed.initialFlights[0].destination.latitude,chengde.latitude);
  assert.match(refreshed.cards.innerHTML,/Growing up/);
  assert.doesNotMatch(refreshed.cards.innerHTML,/Sydney arrival|University/);
});

test('background event revisions preserve the active city without another flight', t=>{
  const settings={values:new Map(),initialPlace:chengde};
  const first=mapFixture(t,false,[],undefined,true,settings);
  first.expand(first.map.nodes().find(node=>node.city==='Sydney').groupKey);
  first.zoom(sydney);
  first.flights.length=0;
  settings.scope='fixture:updated-events';
  first.refresh();
  assert.equal(first.map.viewCity(),first.map.nodes().find(node=>node.city==='Sydney').groupKey);
  assert.match(first.cards.innerHTML,/Sydney arrival/);
  assert.doesNotMatch(first.cards.innerHTML,/Birth|University|class="map-memory-card is-city/);
  assert.equal(first.flights.length,0,'An event update must not interrupt the current map view');
});

test('Whole journey remains an explicit saved choice after collapse and refresh', t=>{
  const settings={values:new Map(),initialPlace:shanghai};
  const first=mapFixture(t,false,[],undefined,true,settings);
  first.expand(first.map.nodes().find(node=>node.city==='Sydney').groupKey);
  first.map.overview();
  first.flights.length=0;
  first.remount();
  assert.ok(first.flights[0].destination.height>40000);
  first.map.dispose();
  const refreshed=mapFixture(t,false,[],undefined,true,settings);
  assert.ok(refreshed.initialFlights[0].destination.height>40000);
  assert.equal(refreshed.map.viewCity(),null);
  assert.equal((refreshed.cards.innerHTML.match(/class="map-memory-card is-city/g)||[]).length,3);
});

test('a newly mentioned place supersedes the older saved city', t=>{
  const settings={values:new Map(),initialPlace:{...chengde,source_sequence:1}};
  const first=mapFixture(t,false,[],undefined,true,settings);
  first.expand(first.map.nodes().find(node=>node.city==='Sydney').groupKey);
  settings.initialPlace={...shanghai,source_sequence:2};
  first.refresh();
  assert.equal(first.flights.at(-1).destination.latitude,shanghai.latitude);
  first.map.dispose();
  const refreshed=mapFixture(t,false,[],undefined,true,settings);
  assert.equal(refreshed.initialFlights[0].destination.latitude,shanghai.latitude);
});

test('saved city preferences stay within the project, owner and policy identity', t=>{
  const values=new Map();
  const settings={values,identity:'project:owner:1',initialPlace:chengde};
  const first=mapFixture(t,false,[],undefined,true,settings);
  first.expand(first.map.nodes().find(node=>node.city==='Sydney').groupKey);
  first.map.dispose();
  for (const identity of ['other-project:owner:1','project:other-owner:1','project:owner:2']) {
    const refreshed=mapFixture(t,false,[],undefined,true,{...settings,identity});
    assert.equal(refreshed.initialFlights[0].destination.latitude,chengde.latitude);
    refreshed.map.dispose();
  }
});

test('switching project or policy scope hides old locations before the next map sync', t=>{
  const settings={};
  const {map}=mapFixture(t,false,[],undefined,true,settings);
  assert.ok(map.nodes().length>0);
  settings.scope='another-project:policy-2';
  assert.deepEqual(map.nodes(),[]);
});

test('malformed storage and unavailable cities fall back to current geography', t=>{
  const values=new Map();
  const settings={values,initialPlace:shanghai};
  const first=mapFixture(t,false,[],undefined,true,settings);
  first.expand(first.map.nodes().find(node=>node.city==='Sydney').groupKey);
  first.map.dispose();
  const missing=mapFixture(t,false,[],[event('University',shanghai,2007,'young_adulthood')],true,
    {...settings,places:[shanghai]});
  assert.equal(missing.initialFlights[0].destination.latitude,shanghai.latitude);
  missing.map.dispose();
  for (const key of values.keys()) values.set(key,'{invalid');
  const refreshed=mapFixture(t,false,[],undefined,true,settings);
  assert.equal(refreshed.initialFlights[0].destination.latitude,shanghai.latitude);
});

test('restricted browser storage still retains the city across collapse in the current page', t=>{
  const storage={getItem(){throw new Error('Storage denied');},setItem(){throw new Error('Storage denied');}};
  const {map,flights,views,expand,remount}=mapFixture(t,false,[],undefined,true,{storage});
  expand(map.nodes().find(node=>node.city==='Sydney').groupKey);
  flights.length=0;
  remount();
  assert.equal(flights.length,0);
  assert.equal(views[0].destination.latitude,sydney.latitude);
});

test('one-event city views retain large intercity footprints even when the other city is far offscreen', t=>{
  const events=[event('Birth',chengde,1983,'baby'),event('Sydney arrival',sydney,2012,'young_adulthood')];
  const {footprints,zoom}=mapFixture(t,false,[],events);
  for(const city of [sydney,chengde]) {
    zoom(city);
    assert.ok(footprints.length>0,'The visible part of the intercity trail must keep its footprints');
    assert.ok(footprints.every(stamp=>stamp.width===16 && stamp.height===16));
  }
});

test('local footprints connect chronological city events across an intervening visit to another city', t=>{
  const school={...chengde,place:'School',granularity:'suburb',hierarchy:[...chengde.hierarchy,'School'],
    longitude:chengde.longitude+.1,latitude:chengde.latitude+.1};
  const home={...chengde,place:'Home',granularity:'suburb',hierarchy:[...chengde.hierarchy,'Home'],
    longitude:chengde.longitude-.1,latitude:chengde.latitude-.1};
  const events=[event('Return home',home,2010,'midlife'),event('Sydney visit',sydney,2000,'young_adulthood'),
    event('School',school,1990,'childhood')];
  const {footprints,zoom}=mapFixture(t,false,[school,home],events);
  zoom(chengde);
  assert.ok(footprints.length>0,'The city chronology must have its own trail');
  assert.ok(footprints.every(stamp=>stamp.width===10 && stamp.height===10));
  assert.ok(footprints[0].x>footprints.at(-1).x,'Follow school then home, independent of capture order');
});

test('memories sharing only a city pin keep the intercity trail without inventing local positions', t=>{
  const events=[event('Birth',chengde,1983,'baby'),event('School',chengde,1990,'childhood'),
    event('Sydney arrival',sydney,2012,'young_adulthood')];
  const {map,footprints,zoom}=mapFixture(t,false,[],events);
  zoom(chengde);
  assert.ok(footprints.length>0);
  assert.ok(footprints.every(stamp=>stamp.width===16));
  assert.ok(map.nodes().filter(node=>node.city==='Chengde').every(node=>node.longitude===chengde.longitude && node.latitude===chengde.latitude));
});

test('events with no candidate city do not create map cards without a linked location', t=>{
  for (const mobile of [false,true]) {
    const birth=event('Birth',chengde,1983,'baby');
    const compound={...event('School compound',chengde,null,'childhood'),places:[],locationConfidenceScore:.3};
    const snail={...compound,id:'Snail outing',title:'Snail outing'};
    const {map,cards,flights,zoom}=mapFixture(t,mobile,[],[birth,compound,snail]);
    assert.equal((cards.innerHTML.match(/class="map-memory-card is-city/g)||[]).length,1);
    assert.doesNotMatch(cards.innerHTML,/School compound|Snail outing|Location to confirm|data-memory-explore/);
    assert.deepEqual(map.nodes().map(node=>node.event.id),['Birth'],'Unknown locations must not inherit the birth pin');
    zoom(sydney);
    assert.equal(cards.innerHTML,'');
    assert.equal(flights.length,0);
  }
});

test('an unlocated memory appears on the map only once its location is confirmed', t=>{
  const memory={...event('School compound',chengde,null,'childhood'),places:[]};
  const {map,cards,refresh,hidden,zoom}=mapFixture(t,false,[],[memory]);
  assert.equal(hidden(),false);
  assert.equal(cards.innerHTML,'');
  assert.equal(map.nodes().length,0);
  memory.revision++;
  memory.places=[{role:'setting',status:'supported',place:chengde}];
  refresh();
  assert.equal(map.nodes().length,1);
  assert.match(cards.innerHTML,/<strong class="map-memory-summary">Chengde<\/strong>/);
  assert.doesNotMatch(cards.innerHTML,/data-memory-explore/);
  zoom(chengde);
  assert.equal((cards.innerHTML.match(/data-memory-explore="School compound"/g)||[]).length,1);
  assert.doesNotMatch(cards.innerHTML,/Location to confirm/);
});

test('desktop overview merges each city and sorts by its first event', t=>{
  const {cards}=mapFixture(t);
  assert.equal((cards.innerHTML.match(/class="map-memory-card is-city/g)||[]).length,3);
  assert.ok(cards.innerHTML.indexOf('Chengde')<cards.innerHTML.indexOf('Shanghai'));
  assert.ok(cards.innerHTML.indexOf('Shanghai')<cards.innerHTML.indexOf('Sydney'));
  assert.doesNotMatch(cards.innerHTML,/Birth|University|Sydney arrival|Growing up|data-memory-explore/);
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

test('expanding either a one-event or multi-event city zooms and shows only that city’s events', t=>{
  for (const mobile of [false,true]) for (const city of [chengde,shanghai]) {
    const {map,cards,flights,explored,focusCalls,expand}=mapFixture(t,mobile);
    const groupKey=map.nodes().find(node=>node.city===city.place).groupKey;
    assert.match(cards.innerHTML,/Expand memories/);
    expand(groupKey);
    assert.equal(flights.length,1);
    assert.ok(Math.abs(flights[0].destination.longitude-city.longitude)<1e-9);
    assert.deepEqual(explored,[],'Expanding a city must not start a conversation about its first event');
    assert.deepEqual(focusCalls,[map.nodes().find(node=>node.groupKey===groupKey).key],
      'Focus moves from the city action to its first event card');
    if (city===chengde) {
      assert.ok(cards.innerHTML.indexOf('Birth')<cards.innerHTML.indexOf('Growing up'));
      assert.doesNotMatch(cards.innerHTML,/University|Sydney arrival/);
      assert.equal((cards.innerHTML.match(/data-memory-explore=/g)||[]).length,2);
    } else {
      assert.match(cards.innerHTML,/University/);
      assert.doesNotMatch(cards.innerHTML,/Birth|Growing up|Sydney arrival/);
      assert.equal((cards.innerHTML.match(/data-memory-explore=/g)||[]).length,1);
    }
  }
});

test('one visible city keeps the same event list across zoom levels and returns to the overview when zoomed out', t=>{
  for (const mobile of [false,true]) {
    const {map,cards,zoom}=mapFixture(t,mobile);
    zoom(chengde);
    cards.scrollTop=120;
    for (const span of [16000,40000,80000,12000]) {
      zoom(chengde,span);
      assert.equal(map.viewCity(),groupPlaces([chengde])[0].key);
      assert.match(cards.innerHTML,/Birth/);
      assert.match(cards.innerHTML,/Growing up/);
      assert.doesNotMatch(cards.innerHTML,/Sydney arrival|University/);
      assert.equal(cards.scrollTop,120,'Changing zoom within the city keeps the list position');
    }
    zoom(null,200000);
    assert.equal(map.viewCity(),null);
    assert.equal((cards.innerHTML.match(/class="map-memory-card is-city/g)||[]).length,3);
    assert.equal(cards.scrollTop,0);
  }
});

test('event clicks zoom on desktop and phone without a popup, while the inline action continues the exact event', t=>{
  for (const mobile of [false,true]) {
    const {map,cards,flights,explored,markup,click,explore,zoom}=mapFixture(t,mobile);
    zoom(chengde);
    const node=map.nodes().find(node=>node.event.id==='Birth');
    click(node.key);
    assert.equal(flights.length,1);
    assert.ok(Math.abs(flights[0].destination.longitude-chengde.longitude)<1e-9);
    assert.equal(flights[0].destination.latitude,chengde.latitude);
    assert.doesNotMatch(markup(),/map-memory-detail/);
    assert.match(cards.innerHTML,/data-memory-explore="Birth"/);
    explore('Birth');
    assert.deepEqual(explored,['Birth']);
    assert.equal(flights.length,1,'Continuing a memory must not also trigger a map flight');
  }
});

test('a city with one event zooms directly rather than duplicating that event in an expanded group', t=>{
  const {map,cards,flights,click}=mapFixture(t);
  click(`city:${map.nodes().find(node=>node.event.id==='University').groupKey}`);
  assert.equal(flights.length,1);
  assert.ok(Math.abs(flights[0].destination.longitude-shanghai.longitude)<1e-9);
  assert.doesNotMatch(cards.innerHTML,/map-memory-city-events/);
});

test('zooming to a photo-only city does not select a neighbouring city with events', t=>{
  const nearby={...chengde,place:'Nearby city',hierarchy:['Earth','China','Nearby city'],longitude:118.36};
  const {map,cards,zoom}=mapFixture(t,false,[nearby]);
  zoom(nearby);
  assert.equal(map.viewCity(),groupPlaces([nearby])[0].key);
  assert.equal(cards.innerHTML,'');
});

test('saved city aliases select the same city’s events when their pin is nearer', t=>{
  const saved={...chengde,hierarchy:['Earth','China','Hebei','Chengde'],latitude:40.96,longitude:117.98};
  const {map,cards,zoom}=mapFixture(t,false,[saved]);
  zoom(saved);
  assert.equal(map.viewCity(),groupPlaces([chengde])[0].key);
  assert.match(cards.innerHTML,/Birth/);
  assert.match(cards.innerHTML,/Growing up/);
});
