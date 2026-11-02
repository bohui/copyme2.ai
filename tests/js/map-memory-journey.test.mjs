import test from 'node:test';
import assert from 'node:assert/strict';
import {buildMapMemoryJourney, chronologicalEvents, cityEventCards, eventAge, eventAgeLabel, layoutMemoryCards, map2DViewRectangle, mapCityInView, mapCityOverlapsView, mapTrailWindow, memoryEventCardMarkup} from '../../apps/web/client/memoir/map-memory-journey.mjs';
import {groupPlaces} from '../../apps/web/client/memoir/places.mjs';
import {translateWith} from '../../apps/web/client/i18n.js';

const city = {place:'Sydney',granularity:'city',hierarchy:['Earth','Australia','Sydney'],latitude:-33.8688,longitude:151.2093};
const school = {...city,place:'Newtown',granularity:'suburb',hierarchy:[...city.hierarchy,'Newtown'],latitude:-33.898,longitude:151.178};
const work = {...city,place:'Pyrmont',granularity:'suburb',hierarchy:[...city.hierarchy,'Pyrmont'],latitude:-33.872,longitude:151.195};
const melbourne = {...city,place:'Melbourne',hierarchy:['Earth','Australia','Melbourne'],latitude:-37.814,longitude:144.963};
const groups = groupPlaces([city,school,work,melbourne]);
const link = (place, role='setting') => ({place,role,status:'supported'});
const event = (id,age,place,stage='childhood') => ({id,title:`Memory ${id}`,status:'active',canonical:true,life_stage:stage,
  temporal:{expression:`Age ${age}`,precision:'age'},places:[link(place)]});
const t = (key,values) => translateWith(`Memoir.workspace.${key}`,values);

test('wide 2D views retain the displayed longitude span across the date line',()=>{
  const camera={position:{x:2.35,y:0},right:{x:1,y:0},up:{x:0,y:1},
    frustum:{left:-2.3,right:2.3,bottom:-1,top:1}};
  const rectangle=map2DViewRectangle(camera,point=>({longitude:point.x,latitude:point.y}));
  assert.ok(rectangle.east-rectangle.west>Math.PI);
  assert.equal(mapCityOverlapsView({longitude:117.93,latitude:40.97},rectangle),true);
  assert.equal(mapCityOverlapsView({longitude:151.2,latitude:-33.86},rectangle),true);
  assert.equal(mapCityOverlapsView({longitude:-45,latitude:0},rectangle),false);
  camera.right={x:0,y:1};camera.up={x:-1,y:0};
  const rotated=map2DViewRectangle(camera,point=>({longitude:point.x,latitude:point.y}));
  assert.equal(rotated.west,1.35);assert.equal(rotated.east,3.35);
});

test('a city stays visible while its 100 km circle overlaps the map, including corners and the antimeridian',()=>{
  const rectangle=(west,south,east,north)=>Object.fromEntries(Object.entries({west,south,east,north})
    .map(([key,value])=>[key,value*Math.PI/180]));
  const city={latitude:0,longitude:0};
  assert.equal(mapCityOverlapsView(city,rectangle(.8,-.1,1,.1)),true);
  assert.equal(mapCityOverlapsView(city,rectangle(1.1,-.1,1.3,.1)),false);
  assert.equal(mapCityOverlapsView(city,rectangle(.6,.6,1,1)),true);
  assert.equal(mapCityOverlapsView(city,rectangle(.7,.7,1,1)),false,'Both axes alone being within 100 km is insufficient');
  assert.equal(mapCityOverlapsView({latitude:0,longitude:179.8},rectangle(-179.9,-.1,-179.5,.1)),true);
  assert.equal(mapCityOverlapsView({latitude:80,longitude:0},rectangle(4,79.9,5,80.1)),true);
  assert.equal(mapCityOverlapsView({latitude:null,longitude:0},rectangle(-1,-1,1,1)),false);
});

test('a known birth precedes a broad same-year residence estimate regardless of capture order',()=>{
  const birth={...event('birth',0,melbourne,'baby'),
    temporal:{expression:'1983年4月',precision:'month',year_start:1983},yearConfidenceScore:1};
  const home={...event('home',null,city,'unplaced'),kind:'period',temporal:null,temporal_anchor:'present',
    temporal_estimate:{year_start:1983,year_end:2026,age_start:0,age_end:43,confidence:.3}};
  for(const input of [[home,birth],[birth,home]]) {
    const journey=buildMapMemoryJourney(input,groups,{birth_year:1983});
    assert.deepEqual(cityEventCards(journey.nodes).map(card=>card.city),['Melbourne','Sydney']);
  }
});

test('city summaries use their earliest event time even when supplied after a later related event',()=>{
  const early={...event('early',null,school),temporal:{expression:'1980',precision:'year',year_start:1980}};
  const late={...event('late',null,work),temporal:{expression:'2000',precision:'year',year_start:2000}};
  const middle={...event('middle',null,melbourne),temporal:{expression:'1990',precision:'year',year_start:1990}};
  const journey=buildMapMemoryJourney([late,middle,early],groups);
  const cards=cityEventCards([...journey.nodes].reverse());
  assert.deepEqual(cards.map(card=>card.city),['Sydney','Melbourne']);
  assert.deepEqual(cards[0].nodes.map(node=>node.event.id),['early','late']);
});

test('trail clipping samples only the visible portion of distant and crossing routes',()=>{
  assert.deepEqual(mapTrailWindow({x:50,y:50},{x:150,y:150},400,300),{start:0,end:1});
  for(const [from,to] of [[{x:-100000,y:150},{x:200,y:150}],
    [{x:200,y:100000},{x:200,y:150}],[{x:-100000,y:150},{x:100000,y:150}]]) {
    const window=mapTrailWindow(from,to,400,300);
    assert.ok(window && window.start>=0 && window.end<=1 && window.end>window.start);
    assert.ok((window.end-window.start)*Math.hypot(to.x-from.x,to.y-from.y)<=500.001);
  }
});

test('offscreen and invalid projected trails cannot generate footprint samples',()=>{
  assert.equal(mapTrailWindow({x:-100,y:0},{x:-100,y:500},400,300),null);
  assert.equal(mapTrailWindow(undefined,{x:10,y:20},400,300),null);
  assert.equal(mapTrailWindow({x:NaN,y:10},{x:10,y:20},400,300),null);
  assert.equal(mapTrailWindow({x:0,y:0},{x:10,y:20},0,300),null);
});

test('initial city grouping preserves separate event coordinates for zooming in', () => {
  const journey = buildMapMemoryJourney([event('school',6,school),event('work',20,work,'young_adulthood')],groups);
  const cities = cityEventCards(journey.nodes);
  assert.equal(cities.length,1);
  assert.equal(cities[0].city,'Sydney');
  assert.equal(cities[0].count,2);
  assert.deepEqual([cities[0].age.start,cities[0].age.end],[6,20]);
  assert.equal(cities[0].latitude,city.latitude);
  assert.deepEqual(journey.nodes.map(node => [node.place,node.latitude]),[['Newtown',school.latitude],['Pyrmont',work.latitude]]);
  assert.ok(journey.nodes.every(node => !node.cityOnly));
  assert.equal(journey.legs.length,1);
  assert.equal(journey.legs[0].stageTransition,true);
});

test('city summaries show the city and first-to-last timing, with event copy reserved for event cards', () => {
  const events=[{...event('last',null,work),title:'Last event title',summary:'Last event description',
    temporal:{expression:'1991',precision:'year',year_start:1991}},
  {...event('first',null,school,'baby'),title:'Birth event title',summary:'Birth event description',uncertainty:'Event uncertainty',
    temporal:{expression:'1983',precision:'year',year_start:1983}}];
  const journey=buildMapMemoryJourney(events,groups,{birth_year:1983});
  const city=cityEventCards(journey.nodes)[0];
  const html=memoryEventCardMarkup(city,{t,lifeStageText:stage=>stage});
  assert.match(html,/<strong class="map-memory-summary"><span data-memory-text>Sydney<\/span><\/strong>/);
  assert.match(html,/From 1983 · About age 0 to 1991 · About age 8/);
  assert.match(html,/2 events/);
  assert.match(html,/data-memory-city=[^>]+>Expand memories<\/button>/);
  assert.doesNotMatch(html,/Birth event title|Last event title|event description|Event uncertainty|data-memory-explore|Explore this memory/);
  const individual=memoryEventCardMarkup(journey.nodes[0],{t,lifeStageText:stage=>stage});
  assert.match(individual,/Birth event title/);
  assert.match(individual,/Birth event description/);
  assert.doesNotMatch(individual,/Event uncertainty/);
  assert.match(individual,/data-memory-explore="first"/);
});

test('one-event city summaries still expand and retain unknown timing at the last event', () => {
  const birth={...event('birth',0,city,'baby'),temporal:{expression:'1983',precision:'year',year_start:1983}};
  const later={...event('later',null,school),temporal:null};
  for (const events of [[birth],[birth,later]]) {
    const grouped=cityEventCards(buildMapMemoryJourney(events,groups,{birth_year:1983}).nodes)[0];
    const html=memoryEventCardMarkup(grouped,{t,lifeStageText:stage=>stage});
    assert.match(html,events.length===1 ? /From 1983 · About age 0 to 1983 · About age 0/
      : /From 1983 · About age 0 to \?/);
    assert.match(html,/Expand memories/);
    assert.doesNotMatch(html,/data-memory-explore|Explore this memory/);
  }
});

test('city timing uses the last event instead of the longest earlier interval', () => {
  const early={...event('early',null,school),temporal:{expression:'1983–2000',precision:'range',year_start:1983,year_end:2000}};
  const later={...event('later',null,work),temporal:{expression:'1991–1993',precision:'range',year_start:1991,year_end:1993}};
  const grouped=cityEventCards(buildMapMemoryJourney([later,early],groups,{birth_year:1983}).nodes)[0];
  const html=memoryEventCardMarkup(grouped,{t,lifeStageText:stage=>stage});
  assert.match(html,/From 1983 · About age 0 to 1993 · About age 10/);
  assert.doesNotMatch(html,/2000|age 17/);
});

test('Chinese city summaries use 展开记忆 and reserve 继续聊这段回忆 for events', context => {
  const previous=globalThis.document;
  globalThis.document={documentElement:{lang:'zh-CN'}};
  context.after(()=>{globalThis.document=previous;});
  const chengde={...city,place:'承德市',hierarchy:['Earth','中国','河北省','承德市']};
  const events=[{...event('birth',0,chengde,'baby'),title:'出生'}, {...event('school',8,chengde),title:'上学'}];
  const journey=buildMapMemoryJourney(events,groupPlaces([chengde]),{birth_year:1983});
  const html=memoryEventCardMarkup(cityEventCards(journey.nodes)[0],{t,lifeStageText:stage=>stage});
  assert.match(html,/<strong class="map-memory-summary"><span data-memory-text>承德市<\/span><\/strong>/);
  assert.match(html,/从 约1983年 · 0岁 至 约1991年 · 8岁/);
  assert.match(html,/展开记忆/);
  assert.doesNotMatch(html,/继续聊这段回忆|出生|上学/);
  assert.match(memoryEventCardMarkup(journey.nodes[0],{t,lifeStageText:stage=>stage}),/继续聊这段回忆/);
});

test('footsteps follow chronology across city moves and preserve return visits', () => {
  const events = [event('return',40,work,'midlife'),event('move',22,melbourne,'young_adulthood'),event('school',6,school)];
  const {nodes,legs} = buildMapMemoryJourney(events,groups);
  assert.deepEqual(nodes.map(node=>node.event.id),['school','move','return']);
  assert.deepEqual(legs.map(leg=>[leg.from.city,leg.to.city]),[['Sydney','Melbourne'],['Melbourne','Sydney']]);
});

test('sourced before and after relations order undated events independently of capture order', () => {
  const home={...event('home',null,city,'unplaced'),temporal:null};
  const childhood={...event('childhood',null,school),temporal:null};
  const study={...event('study',null,melbourne,'unplaced'),temporal:null,
    relations:[{kind:'before',event_id:'home'},{kind:'after',event_id:'childhood'}]};
  const birth={...event('birth',0,city,'baby'),temporal:{expression:'1983',precision:'year',year_start:1983}};
  for (const input of [[home,study,childhood,birth],[birth,childhood,study,home]]) {
    const saved=JSON.stringify(input);
    assert.deepEqual(chronologicalEvents(input).map(event=>event.id),['birth','childhood','study','home']);
    assert.equal(JSON.stringify(input),saved);
  }
});

test('cyclic and out-of-scope relations do not manufacture a chronological order', () => {
  const a={...event('a',6,school),relations:[{kind:'before',event_id:'b'},{kind:'after',event_id:'not-authorized'}]};
  const b={...event('b',20,work,'young_adulthood'),relations:[{kind:'before',event_id:'a'}]};
  assert.deepEqual(chronologicalEvents([b,a]).map(event=>event.id),['a','b']);
});

test('an undated current home follows birth without inventing its year or age', () => {
  const chengde={place:'Chengde',granularity:'city',hierarchy:['Earth','China','Chengde'],latitude:40.95,longitude:117.96};
  const birth={...event('birth',0,chengde,'baby'),title:'Born in Chengde',
    temporal:{expression:'1991',precision:'year',year_start:1991}};
  for (const current of [
    {title:'Currently living in Sydney',temporal:null,temporal_anchor:'present'},
    {title:'Living in Sydney',temporal:{expression:'unknown',precision:'unknown'},temporal_anchor:'present'},
    {title:'在悉尼生活',temporal:null,temporal_anchor:'present'},
  ]) for (const reversed of [false,true]) {
    const home={...event('home',null,city,'unplaced'),kind:'period',temporal:null,
      yearConfidenceScore:0,...current};
    const events=reversed ? [home,birth] : [birth,home];
    const saved=JSON.stringify(events);
    const journey=buildMapMemoryJourney(events,groupPlaces([chengde,city]),{birth_year:1991});
    assert.deepEqual(journey.nodes.map(node=>node.event.id),['birth','home']);
    assert.deepEqual(journey.legs.map(leg=>[leg.from.city,leg.to.city]),[['Chengde','Sydney']]);
    const node=journey.nodes.find(node=>node.event.id==='home');
    assert.equal(node.year,null);
    assert.equal(node.calendar,null);
    assert.deepEqual(node.age,{start:null,end:null});
    assert.equal(JSON.stringify(events),saved);
  }
});

test('unrelated present-day testimony and timing conflicts do not order an undated event', () => {
  const birth={...event('birth',0,melbourne,'baby'),temporal:{expression:'1991',precision:'year',year_start:1991}};
  const past={...event('past',null,city,'unplaced'),title:'Living in Sydney',temporal:null,
    source_refs:[{quote:'I lived in Sydney, but I currently live in Melbourne.'}]};
  const conflicted={...past,title:'Currently living in Sydney',temporal_anchor:'present',timing_conflict:true};
  for (const home of [past,conflicted]) {
    assert.equal(buildMapMemoryJourney([birth,home],groups,{birth_year:1991}).legs.length,0);
  }
});

test('calendar dates determine the route within a stage even without a birth year', () => {
  const dated = (id,year,place) => ({...event(id,6,place),temporal:{expression:String(year),precision:'year',year_start:year}});
  const {nodes,legs} = buildMapMemoryJourney([dated('later',1990,work),dated('earlier',1986,school)],groups);
  assert.deepEqual(nodes.map(node=>node.event.id),['earlier','later']);
  assert.equal(legs.length,1);
});

test('supported month and day dates order events within the same year', () => {
  for (const [earlier,later,precision] of [['1986-01-01','1986-09-01','day'],['1986-02','1986-09','month'],['1986年2月1日','1986年9月1日','day']]) {
    const dated = (id,date,place) => ({...event(id,6,place),temporal:{expression:date,precision,year_start:1986}});
    const {nodes,legs} = buildMapMemoryJourney([dated('later',later,work),dated('earlier',earlier,school)],groups);
    assert.deepEqual(nodes.map(node=>node.event.id),['earlier','later']);
    assert.equal(legs.length,1);
  }
});

test('overlapping date ranges do not imply a footprint order', () => {
  const early = {...event('earlier',6,school),temporal:{expression:'1986–1990',precision:'range',year_start:1986,year_end:1990}};
  const later = {...event('later',8,work),temporal:{expression:'1988',precision:'year',year_start:1988}};
  assert.equal(buildMapMemoryJourney([early,later],groups).legs.length,0);
});

test('a unique compatible hierarchy reuses known geography without crossing regions or countries', () => {
  const fuller = {...city,hierarchy:['Earth','Australia','New South Wales','Sydney']};
  assert.equal(buildMapMemoryJourney([event('home',6,city)],groupPlaces([fuller])).nodes.length,1);
  const abroad = {...fuller,hierarchy:['Earth','Canada','Nova Scotia','Sydney']};
  assert.equal(buildMapMemoryJourney([event('home',6,city)],groupPlaces([abroad])).nodes.length,0);
  const otherRegion = {...fuller,hierarchy:['Earth','Australia','Victoria','Sydney']};
  assert.equal(buildMapMemoryJourney([event('home',6,fuller)],groupPlaces([otherRegion])).nodes.length,0);
  assert.equal(buildMapMemoryJourney([event('home',6,city)],groupPlaces([fuller,otherRegion])).nodes.length,0);
});

test('a move retains its explicit origin and destination within the same event', () => {
  const moving = {...event('move',20,city,'young_adulthood'),places:[link(melbourne,'destination'),link(city,'origin')]};
  const {nodes,legs} = buildMapMemoryJourney([moving],groups);
  assert.deepEqual(nodes.map(node=>node.city),['Sydney','Melbourne']);
  assert.equal(legs.length,1);
});

test('missing and conflicted locations never acquire an invented pin', () => {
  const noLink = {...event('missing',5,school),places:[],source_refs:[{quote:'I went to school in Newtown.'}]};
  const conflict = {...event('conflict',8,school),places:[{...link(school),status:'conflicted'}]};
  const {nodes,unmapped} = buildMapMemoryJourney([noLink,conflict,{...event('private',9,school),status:'withdrawn'}],groups);
  assert.equal(nodes.length,0);
  assert.equal(unmapped,2);
});

test('city scope uses a visible neighborhood when its center is offscreen and skips unresolved geography', () => {
  const city={groupKey:'sydney',latitude:-33.86,longitude:151.2,nodes:[{latitude:-33.9,longitude:151.18}]};
  const scope=mapCityInView([{groupKey:'unresolved',latitude:null,longitude:null},city],place=>{
    assert.ok(Number.isFinite(place.latitude) && Number.isFinite(place.longitude));
    return {x:200+(place.longitude-151.18)*100000,y:200+(place.latitude+33.9)*100000};
  },400,400);
  assert.equal(scope,'sydney');
});

test('unresolved coordinates retain their city fallback without a redundant location label in the card', () => {
  const unresolved = {...school,latitude:null,longitude:null,map_pin:null};
  const {nodes} = buildMapMemoryJourney([event('school',6,unresolved)],groupPlaces([city,unresolved]));
  assert.equal(nodes[0].latitude,city.latitude);
  assert.equal(nodes[0].cityOnly,true);
  const html=memoryEventCardMarkup(nodes[0],{t,lifeStageText:()=>''});
  assert.match(html,/data-memory-explore="school"/);
  assert.doesNotMatch(html,/exact place not yet known/);
});

test('time conflicts and undated same-stage memories do not invent a route order', () => {
  const unknown = {...event('uncertain',8,school),temporal:{expression:'unknown',precision:'unknown'}};
  const conflict = {...event('conflict',9,work),timing_conflict:true};
  assert.equal(buildMapMemoryJourney([unknown,conflict],groups).legs.length,0);
  assert.equal(buildMapMemoryJourney([event('a',6,school),event('b',6,work)],groups).legs.length,0);
});

test('ages remain unknown without an anchor and year-derived ages stay approximate', () => {
  assert.deepEqual(eventAge({temporal:{expression:'1988',year_start:1988,precision:'year'}}),{start:null,end:null});
  const derived = eventAge({temporal:{year_start:1988,year_end:1990,precision:'range'}},{birth_year:1980});
  assert.equal(eventAgeLabel(derived,t),'About age 8–10');
  assert.equal(eventAgeLabel(eventAge({temporal:{expression:'6至9岁',precision:'age'}}),t),'Age 6–9');
  assert.equal(eventAgeLabel(eventAge({temporal:{expression:'at age six',precision:'age'}}),t),'Age 6');
  assert.equal(eventAgeLabel(eventAge({temporal:{expression:'when I was twenty-five',precision:'age'}}),t),'Age 25');
  assert.equal(eventAgeLabel(eventAge({temporal:{expression:'at age fourteen',precision:'age'}}),t),'Age 14');
  assert.equal(eventAgeLabel(eventAge({temporal:{expression:'二十五岁',precision:'age'}}),t),'Age 25');
});

test('cards escape model content and show the detailed event location', () => {
  const {nodes} = buildMapMemoryJourney([{...event('unsafe',6,school),title:'A <script>memory</script>',uncertainty:'Maybe 1988'}],groups);
  const html = memoryEventCardMarkup(nodes[0],{t,lifeStageText:()=> 'Childhood'});
  assert.match(html,/Age 6/);
  assert.match(html,/A &lt;script&gt;memory&lt;\/script&gt;/);
  assert.doesNotMatch(html,/<script>/);
  assert.match(html,/type="button"/);
  assert.match(html,/Childhood/);
  assert.match(html,/<strong class="map-memory-summary"><span data-memory-text>A &lt;script&gt;memory&lt;\/script&gt;<\/span><\/strong>/);
  assert.match(html,/<\/button><button[^>]+data-memory-explore="unsafe"/);
  assert.doesNotMatch(html,/Maybe 1988/);
  assert.match(html.replace(/<[^>]+>/g,''),/Newtown/);
  assert.doesNotMatch(html.replace(/<[^>]+>/g,''),/Childhood/);
});

test('cards show readiness with colored rings and keep confidence scores out of the display', () => {
  const original={...event('school',6,school),yearConfidenceScore:.73};
  const saved=JSON.stringify(original);
  const {nodes}=buildMapMemoryJourney([original],groups,{birth_year:1980});
  for (const [percent,color] of [[0,'red'],[23,'amber'],[100,'green']]) {
    const html=memoryEventCardMarkup(nodes[0],{t,lifeStageText:()=> 'Childhood',profile:{avatar_style:'female'},
      readiness:{childhood:{percent,color,word_equivalents:1200}}});
    assert.match(html,/1986 · Age 6/);
    assert.match(html,new RegExp(`--readiness:${percent}%`));
    assert.match(html,new RegExp(`readiness-${color}`));
    assert.match(html,new RegExp(`aria-label="Childhood: ${percent}% context readiness`));
    assert.match(html,/timeline_avatar_child_female\.png/);
    assert.doesNotMatch(html,/confidence|<small>|>\d+%</);
  }
  assert.equal(JSON.stringify(original),saved);
});

test('unplaced events keep a neutral avatar and unknown dates rather than an invented life stage', () => {
  const {nodes}=buildMapMemoryJourney([{...event('unknown',6,school,'unplaced'),temporal:null,yearConfidenceScore:0}],groups);
  const html=memoryEventCardMarkup(nodes[0],{t,lifeStageText:()=>''});
  assert.match(html,/<span class="map-memory-date"><span data-memory-text>\?<\/span><\/span>/);
  assert.doesNotMatch(html,/Year not yet known|Age not yet known/);
  assert.doesNotMatch(html,/confidence|>\d+%</);
  assert.match(html,/is-unknown[^]*Stage not yet known[^]*<svg/);
  assert.doesNotMatch(html,/timeline_avatar_/);
});

test('model estimates order city cards and show approximate years and ages without confidence scores', () => {
  const estimate=(start,end,confidence)=>({year_start:start,year_end:end,confidence,rationale:'Original duration and birth anchors.'});
  const birth={...event('birth',0,school,'baby'),temporal:{expression:'1983年4月',precision:'month',year_start:1983},yearConfidenceScore:1};
  const study={...event('study',null,melbourne,'unplaced'),temporal:null,temporal_estimate:estimate(2006,2008,.65)};
  const home={...event('home',null,city,'unplaced'),temporal:null,temporal_estimate:estimate(2011,2013,.8)};
  const childhood={...event('growing up',null,school),temporal:null,temporal_estimate:estimate(1983,2001,.4)};
  const input=[home,childhood,study,birth],saved=JSON.stringify(input);
  const journey=buildMapMemoryJourney(input,groups,{birth_year:1983});
  assert.deepEqual(journey.nodes.map(node=>node.event.id),['birth','growing up','study','home']);
  const html=memoryEventCardMarkup(journey.nodes.at(-1),{t,lifeStageText:()=>''});
  assert.match(html,/About 2011–2013 · About age 28–30/);
  assert.doesNotMatch(html,/confidence|>\d+%</);
  assert.match(html,/title="Original duration and birth anchors\."/);
  assert.equal(JSON.stringify(input),saved);
});

test('stated dates and timing conflicts take precedence over estimated years', () => {
  const input={...event('school',6,school),yearConfidenceScore:1,
    temporal:{expression:'1989',precision:'year',year_start:1989},
    temporal_estimate:{year_start:1988,year_end:1991,confidence:.5}};
  const {nodes}=buildMapMemoryJourney([input],groups,{birth_year:1983});
  assert.equal(nodes[0].year,1989);
  assert.equal(nodes[0].yearEnd,1989);
  assert.match(memoryEventCardMarkup(nodes[0],{t,lifeStageText:()=>''}),/1989 · About age 6/);
  const conflict=buildMapMemoryJourney([{...input,timing_conflict:true}],groups,{birth_year:1983}).nodes[0];
  assert.equal(conflict.year,null);
  assert.deepEqual(conflict.age,{start:null,end:null});
});

test('nearby memories stay distinct, with overflow instead of inaccessible cards', () => {
  const points = Array.from({length:20},(_,i)=>({key:String(i),x:200,y:220}));
  const boxes = layoutMemoryCards([...points,{key:'off',x:-1,y:0}],390,440,164);
  assert.equal(boxes.length,20);
  assert.ok(boxes.some(box=>box.overflow));
  const placed = boxes.filter(box=>!box.overflow);
  for (const box of placed) assert.ok(box.left>=8 && box.left+164<=382 && box.top>=54 && box.top+126<=352);
  for (let i=0;i<placed.length;i++) for (let j=i+1;j<placed.length;j++) {
    const a=placed[i],b=placed[j];
    assert.ok(a.left+172<=b.left || b.left+172<=a.left || a.top+134<=b.top || b.top+134<=a.top);
  }
});
