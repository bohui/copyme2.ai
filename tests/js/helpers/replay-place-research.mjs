// Feed actual API responses through the production client after delayed Lane B work.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {readMemoirClientSource} from './memoir-source.mjs';
import {applyDerivedWorkspace} from '../../../apps/web/client/memoir/derived-workspace.mjs';
import {createPhotoWorkspace} from '../../../apps/web/client/memoir/photo-workspace.mjs';
import {createPlaceWorkspace} from '../../../apps/web/client/memoir/place-workspace.mjs';
import {placeHistoryKey} from '../../../apps/web/client/memoir/places.mjs';
import {translate} from '../../../apps/web/client/i18n.js';

const packet = JSON.parse(readFileSync(0, 'utf8'));
const projectId = packet.ready.derived_workspace.project_id;
const state = {project:{id:projectId,profile:{}},projectPrincipalId:'owner',
  supabase:{accessToken:'fixture',user:{id:'owner'}},navigationGeneration:0,
  lifeStage:'childhood',chat:[],people:[],relationships:[],timeline:[],sources:[],storyPlans:[]};
const plain = value => JSON.parse(JSON.stringify(value));
const settle = () => new Promise(resolve => setImmediate(resolve));
const timers = new Map(), photoCalls = [], loads = [], groups = [], steps = [], memoryWrites = [];
let now = Date.now(), sequence = 0;
const schedule = (callback, delay) => {const id=++sequence;timers.set(id,{callback,at:now+delay});return id;};
const values = new Map();
Object.assign(globalThis,{
  document:{cookie:'',documentElement:{lang:'zh-CN'},querySelector:()=>null,querySelectorAll:()=>[]},
  window:{location:{origin:'https://memoir.test'},matchMedia:()=>({matches:true,addEventListener() {}}),addEventListener() {}},
  localStorage:{getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,value)},
  setTimeout:schedule,clearTimeout:id=>timers.delete(id),
});
const context = vm.createContext({state,AbortController,URLSearchParams,TextDecoder,document,translate,placeHistoryKey,
  Date:{now:()=>now},setTimeout:schedule,clearTimeout:id=>timers.delete(id),
  render() {},refreshProfileMenu() {},workspaceUpdateQueue:Promise.resolve(),applyDerivedWorkspace,
  applyBackgroundSkillProgress:result=>steps.push(...result.items),
  recordWorkspaceSkillProgress:step=>steps.push(step)});
const source = readMemoirClientSource();
for (const name of ['captureProjectScope','isCurrentProjectScope','profile','preserveConversationLocale',
  'mergePrivateProfile','consumePhotoStream','loadPlacePictures','refreshStageReadiness']) {
  const declaration=source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`));
  assert.ok(declaration,`Missing production function ${name}`);
  vm.runInContext(declaration[0],context);
}
const snapshots=[packet.pending,packet.ready];
context.storyApi=async()=>{
  assert.ok(snapshots.length,'Readiness must settle after Lane B finishes');
  return snapshots.shift();
};
const api=async(path,options)=>{
  const url=new URL(path,'https://memoir.test');
  if (url.pathname === `/v1/projects/${projectId}/photo-memories`) {
    const body=JSON.parse(options.body);
    assert.equal(body.action,'favorite');
    assert.equal(body.photo.attribution,'Alice Example');
    memoryWrites.push(body);
    return {favorites:[{...body.photo,key:body.photo.original_url || body.photo.image_url}],selected:null};
  }
  assert.equal(url.pathname,`/v1/agent/places/${projectId}/photos`);
  const place=url.searchParams.get('place'),period=url.searchParams.get('period');
  assert.equal(period,place==='悉尼'?'':'1980s','Each place must retain its own research period');
  assert.equal(url.searchParams.get('context_year'),place==='悉尼'?null:'1983',
    'The original context year must survive the containing-decade search');
  assert.ok(Object.hasOwn(packet.photos,place),`Unexpected photo lookup ${place}`);
  photoCalls.push([place,period]);
  return context.consumePhotoStream(new Response(packet.photos[place]),options.onPhotoPage);
};
const supabaseApi=async(path,options)=>{
  assert.equal(path,`/v1/agent/places/${projectId}/groups`);
  const body=JSON.parse(options.body);
  assert.equal(body.language,document.documentElement.lang);
  const recorded=packet.groups.find(item=>item.request.language===body.language
    && JSON.stringify(item.request.places)===JSON.stringify(body.places));
  assert.ok(recorded,'Grouping must use the public place fields and the current UI language');
  groups.push(body.language);
  return recorded.response;
};
const load=context.loadPlacePictures;
context.loadPlacePictures=(...args)=>{const done=load(...args);loads.push(done);return done;};
const dependencies={state,api,supabaseApi,profile:context.profile,
  captureProjectScope:context.captureProjectScope,isCurrentProjectScope:context.isCurrentProjectScope,
  loadPlacePictures:context.loadPlacePictures,render() {},saveProfileUpdates:async()=>{},
  persistChatHistory() {},recordWorkspaceSkillProgress:context.recordWorkspaceSkillProgress,
  workspaceHasContent:()=>true,lifeStageText:()=>'',toast:message=>assert.fail(message)};
let places;
const photos=createPhotoWorkspace({...dependencies,placeMapTarget:entry=>places.placeMapTarget(entry)});
places=createPlaceWorkspace({...dependencies,photos});
Object.assign(context,photos,{api,saveProfileUpdates:dependencies.saveProfileUpdates,resolvePlaceMap:places.resolvePlaceMap,
  rememberPlaceJourneyProject:places.rememberPlaceJourneyProject});

const refresh=context.refreshStageReadiness();
await settle();
assert.equal(photoCalls.length,0,'No places are ready in the foreground reply');
const wake=[...timers].sort((a,b)=>a[1].at-b[1].at)[0];
assert.ok(wake,'Pending extraction must schedule recovery');
timers.delete(wake[0]);now=wake[1].at;wake[1].callback();
await refresh;
await Promise.all(loads);
await settle();
assert.deepEqual(photoCalls,[['承德市','1980s'],['悉尼','']]);
assert.equal(state.lifeStage,'childhood','Exercise the initial stage filter');
assert.ok(steps.some(step=>step.skill==='memoir-historical-news-research' && step.status==='saved'));
assert.ok(!steps.some(step=>step.status==='failed'),'The real provider/parser path must complete');

for (const language of ['zh-CN','en-AU','zh-CN']) {
  document.documentElement.lang=language;
  places.resolvePlaceMap(state.placeJourney);
  await settle();
  const html=places.workspaceMediaOverview();
  const navigation=html.match(/<nav class="place-choices"[^]*?<\/nav>/)?.[0]||'';
  const choices=[...navigation.matchAll(/data-place-choice="([^"]*)"[^>]*><span>([^<]+)<\/span>/g)];
  assert.deepEqual(choices.map(choice=>choice[2]).sort(),language==='zh-CN'?['承德市','悉尼'].sort():['Chengde','Sydney']);
  assert.match(navigation,language==='zh-CN'?/中国 · 河北省/:/China · Hebei/);
  assert.match(navigation,language==='zh-CN'?/澳大利亚 · 新南威尔士州/:/Australia · New South Wales/,
    `Both city and parent labels must survive returning to ${language}`);
  assert.doesNotMatch(html,/place-journey-heading/,'Workspace cities need buttons without a duplicate title');
  for (const choice of choices) {
    places.selectPlace(choice[1].replaceAll('&quot;','"').replaceAll('&amp;','&'));
    await Promise.all(loads);
    const selected=places.placeWorkspaceSelection();
    assert.equal(selected.place,['Chengde','承德市'].includes(choice[2])?'承德市':'悉尼');
    const selectedHtml=places.workspaceMediaOverview();
    const pins=JSON.parse((selectedHtml.match(/data-cesium-pins="([^"]*)"/)?.[1] || '[]')
      .replaceAll('&quot;','"').replaceAll('&amp;','&'));
    assert.deepEqual(pins.map(pin=>[pin.place,pin.latitude,pin.longitude,pin.isChild]),
      [[selected.place,selected.latitude,selected.longitude,false]],
      `The ${language} map must retain the selected city's pin after API localization`);
    assert.equal(photos.workspacePictureItems(selected).length,10,'Each selected place must retain its own photographs');
    if (selected.place==='承德市') {
      const gaps=photos.workspacePictureItems(selected).map(photo=>Math.abs(Number(photo.date_expression.slice(0,4))-1983));
      assert.deepEqual(gaps,[...gaps].sort((a,b)=>a-b),'The gallery must preserve the API relevance order');
      const willow=photos.workspacePictureItems(selected).find(photo=>photo.title==='Willow trees');
      assert.equal(willow?.attribution,'Alice Example');
      assert.match(selectedHtml,/Alice Example/,'The gallery must display the source creator credit');
      if (!memoryWrites.length) {
        const reference=[...selectedHtml.matchAll(/data-photo-reference="([^"]*)"/g)]
          .map(match=>JSON.parse(match[1].replaceAll('&quot;','"').replaceAll('&amp;','&')))
          .find(photo=>photo.title==='Willow trees');
        let click;
        const button={dataset:{photoMemory:'favorite',photoReference:JSON.stringify(reference)},
          addEventListener:(name,handler)=>{if(name==='click')click=handler;}};
        photos.bindPhotoMemoryActions({querySelectorAll:selector=>selector==='[data-photo-memory]'?[button]:[]});
        click();
        await state.photoMemoryTask.done;
        assert.equal(state.project.profile.photo_memories[projectId].favorites[0].attribution,'Alice Example');
      }
    }
  }
}
assert.ok(groups.includes('zh-CN') && groups.includes('en-AU'));
const saved=plain(state.project.profile.memory_places);
applyDerivedWorkspace(state,packet.ready.derived_workspace);
await places.hydratePlaceJourney();
await Promise.all(loads);
assert.deepEqual(plain(state.project.profile.memory_places),saved,'A refreshed snapshot must preserve photo cache metadata');
assert.equal(photoCalls.length,2,'Restoring the interview must reuse both completed searches');

const chengde=state.project.profile.memory_places.find(place=>place.place==='承德市');
state.project.profile.memory_places=[chengde];state.placeJourney=chengde;
state.selectedPlace=placeHistoryKey(chengde);state.lifeStage='all';
const single=places.workspaceMediaOverview();
assert.equal((single.match(/data-place-choice=/g)||[]).length,1,'One city must still have a location button');
assert.doesNotMatch(single,/place-journey-heading/);
assert.equal(memoryWrites.length,1,'The real favorite action must preserve the original creator credit');

state.project.profile.memory_places=packet.provider_places;
state.placeJourney=packet.provider_places[1];
state.selectedPlace=placeHistoryKey(state.placeJourney);state.lifeStage='all';
document.documentElement.lang='en-AU';
const cityLoads=[];
const cityWorkspace=createPlaceWorkspace({...dependencies,photos,loadPlacePictures:entry=>cityLoads.push(entry.place)});
cityWorkspace.resolvePlaceMap(state.placeJourney);
await settle();
const cityHtml=cityWorkspace.workspaceMediaOverview();
const cityChoices=[...cityHtml.matchAll(/data-place-choice="([^"]*)"[^>]*><span>([^<]+)<\/span>/g)];
assert.deepEqual(cityChoices.map(choice=>choice[2]).sort(),['Parramatta','Sydney']);
const parramatta=cityChoices.find(choice=>choice[2]==='Parramatta');
cityWorkspace.selectPlace(parramatta[1].replaceAll('&quot;','"').replaceAll('&amp;','&'));
assert.equal(cityWorkspace.placeWorkspaceSelection().place,'Parramatta');
assert.equal(cityLoads.at(-1),'Parramatta');

const landmark=packet.landmark;
state.project.profile.memory_places=[landmark];state.placeJourney=landmark;
await context.loadPlacePictures(landmark,projectId);
const landmarkPhotos=photos.workspacePictureItems(state.project.profile.memory_places[0]);
assert.deepEqual(landmarkPhotos.map(photo=>photo.title),['Mountain Resort'],
  'The landmark caption and structured city must survive API-to-client filtering');
assert.equal(landmarkPhotos[0].date_expression,'1983-10-01');
const landmarkWall=photos.pictureWall(landmarkPhotos,landmark);
assert.match(landmarkWall,/resort\.jpg/);
assert.doesNotMatch(landmarkWall,/Beijing|beijing\.jpg/);
for (const parent of packet.containing_places) {
  state.project.profile.memory_places=[parent];state.placeJourney=parent;
  await context.loadPlacePictures(parent,projectId);
  const items=photos.workspacePictureItems(state.project.profile.memory_places[0]);
  assert.deepEqual(items.map(photo=>photo.title),[packet.containing_titles[parent.place]],
    `The ${parent.place} gallery must retain its source-confirmed photograph`);
  assert.equal(items[0].date_expression,'1983-10-01');
  assert.match(photos.pictureWall(items,parent),new RegExp(`${parent.place.toLowerCase()}\\.jpg`));
}
for (const city of packet.rejected_city_places) {
  state.project.profile.memory_places=[city];state.placeJourney=city;
  await context.loadPlacePictures(city,projectId);
  const items=photos.workspacePictureItems(state.project.profile.memory_places[0]);
  assert.deepEqual(items,[],`${city.place} must not display a conflicting city photograph`);
}
console.log('Place regression replay passed: delayed extraction, two searches, localized buttons, selection and restore.');
