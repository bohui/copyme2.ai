import test from 'node:test';
import assert from 'node:assert/strict';
import {createAtlasUpdates} from '../../apps/web/client/memoir/atlas-updates.mjs';
import {createFamilyWorkspace} from '../../apps/web/client/memoir/family-workspace.mjs';
import {createPlaceWorkspace} from '../../apps/web/client/memoir/place-workspace.mjs';
import {createPhotoWorkspace} from '../../apps/web/client/memoir/photo-workspace.mjs';
import {buildMapMemoryJourney,cityEventCards} from '../../apps/web/client/memoir/map-memory-journey.mjs';
import {groupPlaces} from '../../apps/web/client/memoir/places.mjs';
import {readMemoirClientSource} from './helpers/memoir-source.mjs';
import vm from 'node:vm';

const source=readMemoirClientSource();
const declaration=name=>source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0];

test('one Atlas connection delivers map pages, grouped places, and private photo changes without follow-up reads', async t => {
  const previousWindow = globalThis.window;
  globalThis.window = {addEventListener(){}, matchMedia:()=>({matches:true,addEventListener(){}})};
  t.after(() => { if (previousWindow === undefined) delete globalThis.window; else globalThis.window = previousWindow; });
  const state = {project:{id:'project',profile:{}}, supabase:{accessToken:'test',user:{id:'owner'}}, timeline:[], lifeStage:'all'};
  const scope = {projectId:'project',ownerId:'owner'};
  const calls = [];
  const place = {place:'Pyrmont',hierarchy:['Earth','Australia','Sydney','Pyrmont'],granularity:'suburb'};
  const pin = {...place,latitude:-33.87,longitude:151.19};
  const grouped = {...place,map_city:pin,map_pin:pin};
  const photo = {photo_id:'upload:aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',kind:'private_upload',event_ids:['first']};
  let workspace;
  const current = captured => captured.ownerId === state.supabase.user.id;
  const dependencies = {state, profile:()=>state.project.profile,
    captureProjectScope:()=>scope, isCurrentProjectScope:current,
    render() { workspace.mapMemoryEvents.sync(null); },
    storyApi:async path=>{calls.push(path);return {items:[]};},
    api:async path=>{calls.push(path);return {photos:[photo]};},
    supabaseApi:async path=>{calls.push(path);return {places:[{index:0,city:pin,pin}]};}};
  const photos = createPhotoWorkspace(dependencies);
  workspace = createPlaceWorkspace({...dependencies,photos});
  const family = createFamilyWorkspace(dependencies);
  const context = vm.createContext({...dependencies, photos, AbortController, setTimeout, clearTimeout,
    refreshFamilyContext:family.refreshFamilyContext, applyMapEventPage:family.applyMapEventPage});
  vm.runInContext(declaration('refreshStageReadiness'),context);
  let stream;
  const atlas = state.atlasUpdates = createAtlasUpdates({scope:()=>scope, current, token:()=>state.supabase.accessToken,
    url:()=>'/v1/story/atlas-events?project_id=project', onUpdate:context.refreshStageReadiness,
    onUnavailable:()=>calls.push('Atlas fallback'), request:async (_path,{signal})=>new Response(new ReadableStream({
      start(controller) { stream = controller; signal.addEventListener('abort',()=>controller.close(),{once:true}); }
    }),{headers:{'Content-Type':'text/event-stream'}})});
  t.after(()=>atlas.stop());
  assert.ok(atlas.start());
  const encoder = new TextEncoder();
  const send = snapshot => stream.enqueue(encoder.encode(`event: atlas-update\ndata: ${JSON.stringify(snapshot)}\n\n`));
  for (const revision of [1, 2, 3]) {
    const events = ['first','second'].map(id=>({id,revision,status:'active',title:id,
      places:[{role:'setting',place:grouped}]}));
    const fence = {project_id:'project',policy_epoch:1,source_revision:revision,event_revision:revision};
    const page = {...fence, map_source:'published_events', streaming_pages:true};
    send({...fence, map_photos:revision < 3 ? [photo] : []});
    send({...fence, map_page:{...page,events:[events[0]],next_cursor:'second',complete:false}});
    send({...fence, map_page:{...page,events:[events[1]],after_cursor:'second',complete:true}});
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(workspace.mapMemoryEvents.nodes().length,2);
    assert.deepEqual(photos.mapPhotos().map(item=>item.photo_id),revision < 3 ? [photo.photo_id] : []);
  }
  assert.deepEqual(calls,[]);
});

test('ordinary recall reads saved Lane B events for map cards without Family legacy access', async () => {
  const birth = {place:'承德市',hierarchy:['Earth','中国','河北省','承德市'],granularity:'city',latitude:40.9515,longitude:117.9634};
  const sydney = {place:'悉尼',hierarchy:['Earth','澳大利亚','新南威尔士州','悉尼'],granularity:'city',latitude:-33.8688,longitude:151.2093};
  const events = [{id:'saved-birth',kind:'event',status:'active',revision:1,title:'Birth in April 1991',life_stage:'baby',
    temporal:{expression:'1991年4月',precision:'month',year_start:1991,year_end:1991},
    places:[{role:'setting',status:'supported',place:birth}]},
  {id:'saved-home',kind:'period',status:'active',revision:1,title:'Living in Sydney',life_stage:'unplaced',temporal:null,
    places:[{role:'setting',status:'supported',place:sydney}]},
  {id:'saved-childhood',kind:'period',status:'active',revision:1,title:'Playing at the school staff compound',
    life_stage:'childhood',temporal:null}];
  const state = {project:{id:'project',profile:{birth_year:1991,memory_places:[birth,sydney]}},
    supabase:{accessToken:'test'},familyFeaturesEnabled:false,lifeStage:'all',timeline:[]};
  const requests=[];
  const workspace=createFamilyWorkspace({state,captureProjectScope:()=>state.project.id,
    isCurrentProjectScope:id=>id===state.project.id,render(){},
    supabaseApi:async()=>{throw new Error('Family context is unavailable during ordinary recall');},
    storyApi:async path=>{
      requests.push(path);
      if (!path.startsWith('/v1/story/atlas-events?')) throw Object.assign(new Error('Premium timeline is unavailable'),{status:403});
      return {project_id:'project',policy_epoch:1,source_revision:1,event_revision:1,events,complete:true,
        processing:{pending_inputs:0}};
    }});
  await workspace.refreshFamilyContext();
  assert.equal(state.timeline.length,3,'All saved Lane B events must reach the ordinary-recall map');
  assert.deepEqual(requests,['/v1/story/atlas-events?project_id=project&language=en-AU&view=map']);
  const journey=buildMapMemoryJourney(state.timeline,groupPlaces([birth,sydney]),state.project.profile);
  assert.equal(cityEventCards(journey.nodes).length,2,'A saved event must render as a city card, not disappear behind the family gate');
  assert.equal(journey.unmapped,1,'An event without an explicit location must not inherit a nearby city');
});

test('entitlement hydration leaves the ordinary map to Atlas', async () => {
  let reads=0;
  const state={project:{id:'project'},showThinkingSteps:false,showDraftUpdates:false};
  const context=vm.createContext({state,captureProjectScope:()=> 'project',isCurrentProjectScope:()=>true,
    freeRecallFinished:()=>false,storyApi:async()=>({family_features_enabled:false,payment_features:[],
      recall_status:{rounds_completed:1,free_rounds:20}}),refreshFamilyContext:async()=>{reads++;}});
  vm.runInContext(declaration('refreshFamilyEntitlement'),context);
  await context.refreshFamilyEntitlement();
  assert.equal(reads,0);
  assert.equal(state.familyFeaturesEnabled,false);
});

test('restoring a stage-tagged place preserves the initial all-ages map', async t => {
  t.mock.timers.enable({apis:['setTimeout']});
  const previousWindow=globalThis.window;
  globalThis.window={addEventListener(){},matchMedia:()=>({matches:true,addEventListener(){}})};
  t.after(()=>{if (previousWindow === undefined) delete globalThis.window; else globalThis.window=previousWindow;});
  const birth={place:'Chengde',hierarchy:['Earth','China','Hebei','Chengde'],granularity:'city',
    latitude:40.9515,longitude:117.9634,life_stage:'baby',source_sequence:1};
  const home={place:'Sydney',hierarchy:['Earth','Australia','New South Wales','Sydney'],granularity:'city',
    latitude:-33.8688,longitude:151.2093,life_stage:'midlife',source_sequence:2};
  const state={project:{id:'project',profile:{memory_places:[birth,home]}},supabase:{accessToken:'test'},
    timeline:[],lifeStage:'all',chat:[]};
  const workspace=createPlaceWorkspace({state,profile:()=>state.project.profile,render(){},
    captureProjectScope:()=> 'project',isCurrentProjectScope:()=>true,
    loadPlacePictures(){},recordWorkspaceSkillProgress(){},saveProfileUpdates:async()=>{},supabaseApi:async()=>({places:[]}),
    photos:{}});
  await workspace.hydratePlaceJourney();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(state.placeJourney.place,'Sydney');
  assert.equal(state.lifeStage,'all','Restoring a midlife city must not hide baby or unplaced events');
});

test('an unfinished Lane B extraction does not poll the map feed', async t => {
  t.mock.timers.enable({apis:['setTimeout']});
  const state={project:{id:'project'},supabase:{accessToken:'test'},familyFeaturesEnabled:false,timeline:[]};
  let reads=0;
  const workspace=createFamilyWorkspace({state,captureProjectScope:()=> 'project',isCurrentProjectScope:()=>true,
    render(){},storyApi:async()=>({events:++reads===1 ? [] : [{id:'birth',status:'active',kind:'event',
      title:'Birth',life_stage:'baby',temporal:{expression:'1991年4月',precision:'month',year_start:1991}}],
      processing:{pending_inputs:reads===1 ? 1 : 0}})});
  await workspace.refreshFamilyContext();
  assert.equal(state.timeline.length,0);
  t.mock.timers.tick(60000);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(reads,1);
  await workspace.refreshFamilyContext();
  assert.equal(state.timeline[0].id,'birth');
  assert.equal(reads,2);
});

test('a transient map read failure keeps the saved events until the next refresh', async t => {
  t.mock.timers.enable({apis:['setTimeout']});
  const saved={id:'birth',canonical:true}, state={project:{id:'project',profile:{}},supabase:{accessToken:'test'},
    familyFeaturesEnabled:false,timeline:[saved]};
  let reads=0;
  const workspace=createFamilyWorkspace({state,captureProjectScope:()=>state.project.id,
    isCurrentProjectScope:id=>id===state.project.id,render(){},storyApi:async()=>{
      if (++reads===1) throw Object.assign(new Error('stale lifetime read fence'),{status:500});
      return {project_id:'project',events:[{...saved,title:'Updated birth memory'}]};
    }});
  await workspace.refreshFamilyContext();
  assert.deepEqual(state.timeline,[saved]);
  t.mock.timers.tick(15000);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(reads,1);
  await workspace.refreshFamilyContext();
  assert.equal(reads,2);
  assert.equal(state.timeline[0].title,'Updated birth memory');
});

test('family chronology does not fetch unrelated event details', async () => {
  const state={project:{id:'project'},supabase:{accessToken:'test'},familyFeaturesEnabled:true,timeline:[]};
  const requests=[];
  const workspace=createFamilyWorkspace({state,captureProjectScope:()=> 'project',isCurrentProjectScope:()=>true,
    render(){},supabaseApi:async()=>null,storyApi:async path=>{
      requests.push(path);
      return {events:[{id:'event',status:'active',details_complete:false,relations:[]}],complete:true};
    }});
  await workspace.refreshFamilyContext();
  assert.deepEqual(requests,['/v1/story/events?project_id=project&language=en-AU']);
});

test('ordinary map pagination loads later events without Family access', async () => {
  const state={project:{id:'project'},supabase:{accessToken:'test'},familyFeaturesEnabled:false,
    timeline:[{id:'earlier'}],memoryEventPage:{next_cursor:'next'}};
  const requests=[];
  const workspace=createFamilyWorkspace({state,captureProjectScope:()=> 'project',isCurrentProjectScope:()=>true,
    render(){},storyApi:async path=>{requests.push(path);return {events:[{id:'later',status:'active'}],complete:true};}});
  await workspace.loadMoreMemoryEvents();
  assert.deepEqual(requests,['/v1/story/atlas-events?project_id=project&cursor=next&language=en-AU&view=map']);
  assert.deepEqual(state.timeline.map(event=>event.id),['earlier','later']);
});

test('refresh reads every saved event page and orders late recollections by story date', async () => {
  const state={project:{id:'project',profile:{birth_year:1983}},supabase:{accessToken:'test'},
    familyFeaturesEnabled:false,timeline:[]};
  const dated=(id,year)=>({id,status:'active',title:id,temporal:{expression:String(year),precision:'year',year_start:year}});
  const requests=[];
  const workspace=createFamilyWorkspace({state,captureProjectScope:()=> 'project',isCurrentProjectScope:()=>true,
    render(){},storyApi:async path=>{
      requests.push(path);
      return path.includes('cursor=') ? {events:[dated('birth',1983)],complete:true}
        : {events:[dated('later',2012)],next_cursor:'older-memory',complete:false};
    }});
  await workspace.refreshFamilyContext();
  assert.equal(requests.length,2);
  assert.deepEqual(state.timeline.map(event=>event.id),['birth','later']);
  assert.equal(state.memoryEventPage.complete,true);
});

test('a late older refresh cannot erase cards from a newer saved-event page', async () => {
  const state={project:{id:'project'},supabase:{accessToken:'test'},familyFeaturesEnabled:false,timeline:[]};
  const responses=[];
  const workspace=createFamilyWorkspace({state,captureProjectScope:()=> 'project',isCurrentProjectScope:()=>true,
    render(){},storyApi:()=>new Promise(resolve=>responses.push(resolve))});
  const older=workspace.refreshFamilyContext();
  const newer=workspace.refreshFamilyContext();
  responses[1]({events:[{id:'saved',status:'active'}],event_revision:2,processing:{pending_inputs:0}});
  await newer;
  responses[0]({events:[],event_revision:0,processing:{pending_inputs:0}});
  await older;
  assert.deepEqual(state.timeline.map(event=>event.id),['saved']);
  assert.equal(state.memoryEventPage.event_revision,2);
});

test('the all-ages map keeps the life-stage navigator reachable by keyboard', () => {
  const context=vm.createContext({state:{lifeStage:'all',stageReadiness:{}},LIFE_STAGES:[{id:'baby'},{id:'childhood'}],
    translateWith:key=>key,escapeHtml:String,lifeStageText:stage=>stage,lifeStageIllustration:()=>'',
    lifeStageEvidence:()=>({memoryCount:0,pictureCount:0})});
  vm.runInContext(declaration('lifeStageNavigator'),context);
  const html=context.lifeStageNavigator();
  assert.match(html,/<button id="life-stage-baby"[^>]*tabindex="0"/);
  assert.match(html,/<button id="life-stage-childhood"[^>]*tabindex="-1"/);
  assert.match(html,/data-add-workspace-memory/,'The stage view retains its own add-memory action');
  assert.equal(context.lifeStageNavigator(false),'','The map footer must not duplicate the city-card action');
});
