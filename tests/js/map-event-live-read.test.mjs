import test from 'node:test';
import assert from 'node:assert/strict';
import {createFamilyWorkspace} from '../../apps/web/client/memoir/family-workspace.mjs';
import {buildMapMemoryJourney,cityEventCards} from '../../apps/web/client/memoir/map-memory-journey.mjs';
import {groupPlaces} from '../../apps/web/client/memoir/places.mjs';
import {readMemoirClientSource} from './helpers/memoir-source.mjs';
import vm from 'node:vm';

const source=readMemoirClientSource();
const declaration=name=>source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0];

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
      if (!path.startsWith('/v1/story/map-events?')) throw Object.assign(new Error('Premium timeline is unavailable'),{status:403});
      return {project_id:'project',policy_epoch:1,source_revision:1,event_revision:1,events,complete:true,
        processing:{pending_inputs:0}};
    }});
  await workspace.refreshFamilyContext();
  assert.equal(state.timeline.length,3,'All saved Lane B events must reach the ordinary-recall map');
  assert.deepEqual(requests,['/v1/story/map-events?project_id=project']);
  const journey=buildMapMemoryJourney(state.timeline,groupPlaces([birth,sydney]),state.project.profile);
  assert.equal(cityEventCards(journey.nodes).length,2,'A saved event must render as a city card, not disappear behind the family gate');
  assert.equal(journey.unmapped,1,'An event without an explicit location must not inherit a nearby city');
});

test('entitlement hydration starts the map read during ordinary recall', async () => {
  let reads=0;
  const state={project:{id:'project'},showThinkingSteps:false,showDraftUpdates:false};
  const context=vm.createContext({state,captureProjectScope:()=> 'project',isCurrentProjectScope:()=>true,
    freeRecallFinished:()=>false,storyApi:async()=>({family_features_enabled:false,payment_features:[],
      recall_status:{rounds_completed:1,free_rounds:20}}),refreshFamilyContext:async()=>{reads++;}});
  vm.runInContext(declaration('refreshFamilyEntitlement'),context);
  await context.refreshFamilyEntitlement();
  assert.equal(reads,1);
  assert.equal(state.familyFeaturesEnabled,false);
});

test('a pending Lane B extraction refreshes map events after they are saved', async t => {
  t.mock.timers.enable({apis:['setTimeout']});
  const state={project:{id:'project'},supabase:{accessToken:'test'},familyFeaturesEnabled:false,timeline:[]};
  let reads=0;
  const workspace=createFamilyWorkspace({state,captureProjectScope:()=> 'project',isCurrentProjectScope:()=>true,
    render(){},storyApi:async()=>({events:++reads===1 ? [] : [{id:'birth',status:'active',kind:'event',
      title:'Birth',life_stage:'baby',temporal:{expression:'1991年4月',precision:'month',year_start:1991}}],
      processing:{pending_inputs:reads===1 ? 1 : 0}})});
  await workspace.refreshFamilyContext();
  assert.equal(state.timeline.length,0);
  t.mock.timers.tick(15000);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(state.timeline[0].id,'birth');
  assert.equal(reads,2);
});

test('ordinary map pagination loads later events without Family access', async () => {
  const state={project:{id:'project'},supabase:{accessToken:'test'},familyFeaturesEnabled:false,
    timeline:[{id:'earlier'}],memoryEventPage:{next_cursor:'next'}};
  const requests=[];
  const workspace=createFamilyWorkspace({state,captureProjectScope:()=> 'project',isCurrentProjectScope:()=>true,
    render(){},storyApi:async path=>{requests.push(path);return {events:[{id:'later',status:'active'}],complete:true};}});
  await workspace.loadMoreMemoryEvents();
  assert.deepEqual(requests,['/v1/story/map-events?project_id=project&cursor=next']);
  assert.deepEqual(state.timeline.map(event=>event.id),['earlier','later']);
});

test('the all-ages map keeps the life-stage navigator reachable by keyboard', () => {
  const context=vm.createContext({state:{lifeStage:'all',stageReadiness:{}},LIFE_STAGES:[{id:'baby'},{id:'childhood'}],
    translateWith:key=>key,escapeHtml:String,lifeStageText:stage=>stage,lifeStageIllustration:()=>'',
    lifeStageEvidence:()=>({memoryCount:0,pictureCount:0})});
  vm.runInContext(declaration('lifeStageNavigator'),context);
  const html=context.lifeStageNavigator();
  assert.match(html,/<button id="life-stage-baby"[^>]*tabindex="0"/);
  assert.match(html,/<button id="life-stage-childhood"[^>]*tabindex="-1"/);
});
