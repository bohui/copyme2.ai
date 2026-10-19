import test from 'node:test';
import assert from 'node:assert/strict';
import { createPhotoWorkspace } from '../../apps/web/client/memoir/photo-workspace.mjs';
import { createPlaceWorkspace } from '../../apps/web/client/memoir/place-workspace.mjs';
import { createFamilyWorkspace } from '../../apps/web/client/memoir/family-workspace.mjs';
import { createPrivateDraft } from '../../apps/web/client/memoir/private-draft.mjs';
import { createConversationHistory } from '../../apps/web/client/memoir/conversation-history.mjs';
import { createConversationAudio } from '../../apps/web/client/memoir/conversation-audio.mjs';
import { createStoryCheckout } from '../../apps/web/client/memoir/story-checkout.mjs';
import { createUiLocale } from '../../apps/web/client/memoir/ui-locale.mjs';
import {applyDerivedWorkspace} from '../../apps/web/client/memoir/derived-workspace.mjs';
import {placeHistoryKey,groupPlaces} from '../../apps/web/client/memoir/places.mjs';

function setup(t) {
  const storage = () => {
    const values = new Map();
    return { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
  };
  const globals = {
    document: { cookie: '', documentElement: {lang:'en-AU'}, querySelector: () => null, querySelectorAll: () => [] },
    window: { location: {origin:'https://memoir.test'}, addEventListener() {},
      matchMedia: () => ({matches:false, addEventListener() {}}), speechSynthesis: {cancel() {}} },
    localStorage: storage(), sessionStorage: storage(),
    __copyme2Intl: undefined, __copyme2SetUiLocale: undefined,
    __copyme2BeforeUiLocaleChange: undefined, __copyme2UiLocaleScope: undefined,
    __copyme2UiLocaleScopeCurrent: undefined,
  };
  for (const [key, value] of Object.entries(globals)) {
    const previous = Object.getOwnPropertyDescriptor(globalThis, key);
    Object.defineProperty(globalThis, key, {value, configurable:true, writable:true});
    t.after(() => {
      if (previous) Object.defineProperty(globalThis, key, previous);
      else delete globalThis[key];
    });
  }
  const state = {project:{id:'p',profile:{name:'Avery'}}, projectPrincipalId:'owner',
    supabase:{user:{id:'owner'},accessToken:'fixture'}, navigationGeneration:0,
    chat:[], people:[], relationships:[], timeline:[], sources:[], storyPlans:[],
    lifeStage:'all', selectedPlace:null, photoMemoryTask:null, photoMemoryRevision:0,
    voiceMode:false, voiceModeTurnId:0, dictationStatus:'off'};
  const captureProjectScope = () => ({projectId:state.project?.id, ownerId:state.supabase?.user?.id, generation:state.navigationGeneration});
  const isCurrentProjectScope = scope => JSON.stringify(scope) === JSON.stringify(captureProjectScope());
  const notices = [];
  const dependencies = {state, captureProjectScope, isCurrentProjectScope,
    profile: () => state.project.profile, render() {}, toast: message => notices.push(message),
    cleanAssistantText: text => text, storyApi: async () => ({}), api: async () => ({}),
    supabaseApi: async () => ({}), conversationLanguage: () => 'en-AU',
    conversationMessage: key => key, persistChatHistory() {}, referencesWorkspace: () => '',
    lifeStageText: () => 'Childhood', refreshPrivateDraft() {}, refreshProject() {},
    updateStreamingAssistantMessage() {}, memoirApiPath: path => path,
    freeRecallFinished: () => true, LIFE_STAGES:[{id:'childhood'}]};
  return {state, dependencies, notices};
}

test('photo and map factories compose around the same saved place and favorite actions', async t => {
  const {state, dependencies} = setup(t);
  const photo = {image_url:'https://photos.test/street.jpg', source_url:'https://photos.test/source',
    title:'Sydney street', date_expression:'1983', latitude:-33.86, longitude:151.2,
    allowed_actions:{embed:true}};
  const place = {place:'Sydney', latitude:-33.86, longitude:151.2, period:'1983', pictures:[photo]};
  state.project.profile.memory_places = [place];
  state.placeJourney = place;
  let places;
  const photos = createPhotoWorkspace({...dependencies, placeMapTarget: entry => places.placeMapTarget(entry),
    loadPlacePictures() {}, api: async () => ({favorites:[{...photo,key:photo.image_url}],selected:photo.image_url})});
  places = createPlaceWorkspace({...dependencies, photos, loadPlacePictures() {},
    saveProfileUpdates() {}, recordWorkspaceSkillProgress() {}, workspaceHasContent: () => true});
  assert.equal(places.placeWorkspaceSelection().place, 'Sydney');
  assert.match(places.workspaceMediaOverview(), /Sydney street|street\.jpg/);
  const listeners = new Map();
  const button = {dataset:{photoMemory:'select',photoReference:JSON.stringify(photo)},
    addEventListener: (event, handler) => listeners.set(event, handler)};
  photos.bindPhotoMemoryActions({querySelectorAll: selector => selector === '[data-photo-memory]' ? [button] : []});
  listeners.get('click')();
  await state.photoMemoryTask.done;
  assert.match(photos.selectedPhotoCue(), /Sydney street/);
  assert.match(places.workspaceMediaOverview(), /photo-favorites/);
  assert.equal(state.photoMemoryRevision, 1);
});

test('unstaged background places remain selectable during the default childhood view', async t => {
  t.mock.timers.enable({apis:['setTimeout']});
  const {state, dependencies} = setup(t);
  state.lifeStage = 'childhood';
  const chengde = {place:'承德市',hierarchy:['Earth','中国','河北省','承德市'],granularity:'city',
    status:'active',source_sequence:1,research_period:'1980s'};
  const sydney = {place:'悉尼',hierarchy:['Earth','澳大利亚','悉尼'],granularity:'city',
    status:'active',source_sequence:1,research_period:'',latitude:-33.86,longitude:151.2};
  applyDerivedWorkspace(state,{project_id:'p',source_revision:1,policy_epoch:1,
    authoritative:true,places:[chengde,sydney]});
  let places;
  const searched = [];
  const mapped = [];
  const photos = createPhotoWorkspace({...dependencies,placeMapTarget:entry=>places.placeMapTarget(entry)});
  places = createPlaceWorkspace({...dependencies,photos,loadPlacePictures:entry=>searched.push(entry.place),
    api:async (path,options)=>{
      const entry=JSON.parse(options.body);mapped.push(entry.place);
      return {target:{...entry,latitude:40.95,longitude:117.96}};
    },
    saveProfileUpdates() {},recordWorkspaceSkillProgress() {},workspaceHasContent:()=>true});
  const html = places.workspaceMediaOverview();
  assert.equal((html.match(/data-place-choice=/g) || []).length,2);
  assert.match(html, /<span>承德市<\/span>/);
  assert.match(html, /<span>悉尼<\/span>/);
  assert.doesNotMatch(html, /place-journey-heading/);
  places.selectPlace(placeHistoryKey(chengde));
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(places.placeWorkspaceSelection().place,'承德市');
  assert.deepEqual(mapped,['承德市']);
  assert.ok(searched.length && searched.every(place=>place==='承德市'));
  searched.length = 0;
  await places.hydratePlaceJourney();
  assert.deepEqual(searched,['承德市','悉尼']);
});

test('a failed map renderer preserves the place workspace and its coordinates', async t => {
  const {state, dependencies} = setup(t);
  const place = {place:'Chengde', latitude:40.95, longitude:117.96};
  state.project.profile.memory_places = [place];
  state.placeJourney = place;
  const container = {isConnected:true, dataset:{cesiumLatitude:'40.95', cesiumLongitude:'117.96'}};
  document.querySelector = () => container;
  window.Cesium = {WebMercatorProjection:class {}, Viewer:class {constructor() {throw new Error('WebGL unavailable');}}};
  const renders = [];
  let places;
  const photos = createPhotoWorkspace({...dependencies, placeMapTarget: entry => places.placeMapTarget(entry)});
  places = createPlaceWorkspace({...dependencies, photos, loadPlacePictures() {},
    render:() => renders.push(Boolean(places.placeWorkspaceSelection())),
    saveProfileUpdates() {}, recordWorkspaceSkillProgress() {}, workspaceHasContent:() => false});
  assert.equal(places.placeWorkspaceSelection().place, place.place);
  assert.match(places.workspaceMediaOverview(), /data-cesium-unavailable="false"/);
  places.initCesiumPlaceJourney();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(places.placeWorkspaceSelection().place, place.place);
  assert.match(places.workspaceMediaOverview(), /workspace-media-map/);
  assert.match(places.workspaceMediaOverview(), /data-cesium-unavailable="true"/,
    'Failure must invalidate the scene that renderStory otherwise reuses');
  assert.match(places.placeJourneySurface(), /place-journey-card/);
  assert.equal(places.placeMapTarget(place).latitude, place.latitude);
  assert.equal(renders.at(-1), true, 'map failure must preserve the saved place workspace');
  assert.equal(places.placeWorkspaceSelection({allowUnmapped:true}).place, place.place);
  state.project.id = 'another-project';
  assert.equal(places.placeWorkspaceSelection().place, place.place, 'failures belong to their original project');
  state.project.id = 'p';
  assert.equal(places.placeWorkspaceSelection().place, place.place);
  state.placeJourney = {...place, latitude:40.96};
  state.project.profile.memory_places = [state.placeJourney];
  assert.equal(places.placeWorkspaceSelection().latitude, 40.96, 'corrected coordinates can render a new map');
});

test('location buttons follow the UI language and refresh their localized cache', async t => {
  t.mock.timers.enable({apis:['setTimeout']});
  const {state,dependencies}=setup(t);
  const chengde={place:'承德市',hierarchy:['Earth','中国','河北省','承德市'],granularity:'city',latitude:40.95,longitude:117.96};
  const sydney={place:'悉尼',hierarchy:['Earth','澳大利亚','悉尼'],granularity:'city',latitude:-33.86,longitude:151.2};
  state.project.profile.memory_places=[chengde,sydney];state.placeJourney=sydney;
  const requests=[];
  let places;
  const photos=createPhotoWorkspace({...dependencies,placeMapTarget:entry=>places.placeMapTarget(entry)});
  places=createPlaceWorkspace({...dependencies,photos,loadPlacePictures() {},saveProfileUpdates() {},
    recordWorkspaceSkillProgress() {},workspaceHasContent:()=>true,
    supabaseApi:async (path,options)=>{
      const payload=JSON.parse(options.body);requests.push(payload.language);
      return {places:payload.places.map((entry,index)=>{
        const chinese=payload.language==='zh-CN',chengde=entry.place==='承德市';
        const name=chengde ? chinese ? '承德市' : 'Chengde' : chinese ? '悉尼' : 'Sydney';
        const hierarchy=chengde ? chinese ? ['中国','河北省'] : ['China','Hebei']
          : chinese ? ['澳大利亚','新南威尔士州'] : ['Australia','New South Wales'];
        const city={place:name,hierarchy:['Earth',...hierarchy,name],granularity:'city'};
        return {index,city,city_key:groupPlaces([city])[0].key,pin:entry};
      })};
    }});
  for(const language of ['zh-CN','en-AU','zh-CN']) {
    document.documentElement.lang=language;
    places.resolvePlaceMap(sydney);
    await new Promise(resolve=>setImmediate(resolve));
    const html=places.workspaceMediaOverview();
    assert.match(html,language==='zh-CN' ? /<span>承德市<\/span>/ : /<span>Chengde<\/span>/);
    assert.match(html,language==='zh-CN' ? /<span>悉尼<\/span>/ : /<span>Sydney<\/span>/);
    assert.match(html,language==='zh-CN' ? /新南威尔士州/ : /New South Wales/);
    assert.doesNotMatch(html,/place-journey-heading/);
  }
  assert.deepEqual(requests,['zh-CN','en-AU']);
  assert.deepEqual(state.project.profile.memory_places,[chengde,sydney]);
});

test('history factories restore message numbering and isolate account caches', t => {
  const {state, dependencies} = setup(t);
  const history = createConversationHistory(dependencies);
  state.chat = [{id:'assistant-message-8',role:'assistant',text:'A saved memory'}];
  history.persistChatHistory();
  history.rememberProject('p');
  const restored = createConversationHistory(dependencies);
  assert.equal(restored.restoreChatHistory('p')[0].text, 'A saved memory');
  assert.equal(restored.nextAssistantMessageId(), 'assistant-message-9');
  assert.equal(restored.savedProjectId(), 'p');
  state.supabase.user.id = 'another-owner';
  assert.deepEqual(restored.restoreChatHistory('p'), []);
});

test('family and draft factories share refreshed state through their public methods', async t => {
  const {state, dependencies} = setup(t);
  const draft = createPrivateDraft({...dependencies, storyApi: async () => ({
    snapshot_id:'snapshot', root_digest:'root', updating:false, preview:{text:'Saved draft'}})});
  const family = createFamilyWorkspace({...dependencies, refreshPrivateDraft:draft.refreshPrivateDraft});
  family.applyPersistedFamilyContext({project_id:'p',revision:2,people:[{id:'me',name:'Avery',introduction:'A gardener'}],relationships:[],timeline:[]});
  family.selectFamilyPerson('me');
  assert.match(family.familyWorkspace(), /A gardener/);
  family.applyPersistedFamilyContext({project_id:'p',revision:1,people:[]});
  assert.equal(state.people.length, 1);
  await draft.refreshPrivateDraft();
  assert.match(draft.privateDraftPreview({inChapters:true}), /Saved draft/);
});

test('locale factory installs recording guards and applies profile preferences', async t => {
  const {state, dependencies, notices} = setup(t);
  const locale = createUiLocale({...dependencies, preserveConversationLocale: profile => profile});
  locale.installUiLocaleBridge();
  assert.equal(locale.firstReplyLanguage('我的童年在中国'), 'zh-CN');
  state.recording = true;
  assert.equal(await globalThis.__copyme2BeforeUiLocaleChange('zh-CN'), false);
  assert.equal(notices.length, 1);
  state.recording = false;
  const choices = [];
  globalThis.__copyme2SetUiLocale = async (value, options) => {choices.push({value,options}); return true;};
  assert.equal(await locale.applyProfileUiLocale('zh-CN'), true);
  assert.equal(choices[0].value, 'zh-CN');
  assert.equal(choices[0].options.persistCookie, true);
});

test('audio factory stops capture and playback when leaving voice mode', t => {
  const {state, dependencies} = setup(t);
  const calls = [];
  Object.assign(state, {voiceMode:true, voiceModeRecorder:{state:'recording',stop: () => calls.push('recorder')},
    voiceModeStream:{getTracks: () => [{stop: () => calls.push('track')}]},
    audioPlayer:{pause: () => calls.push('player')}, voiceModePlaybackFinish: () => calls.push('playback')});
  const audio = createConversationAudio({...dependencies, sendChatMessage() {}});
  audio.stopVoiceMode({silent:true});
  assert.deepEqual(calls, ['recorder','track','player','playback']);
  assert.equal(state.voiceMode, false);
  assert.equal(state.voiceModeRecorder, null);
  assert.equal(state.voiceModeStream, null);
  assert.equal(state.voiceModeTurnId, 1);
});

test('checkout factory keeps guest selection and recovers from a failed checkout', async t => {
  const {state, dependencies, notices} = setup(t);
  state.selectedStoryPlan = 'printed_memoir_v1';
  state.storyBookCount = 4;
  state.supabase.user.is_anonymous = true;
  let opened = 0, requests = 0;
  const checkout = createStoryCheckout({...dependencies, authReminder:{open: () => opened++},
    storyApi: async (_path, options) => {
      requests++;
      assert.equal(JSON.parse(options.body).book_count, 4);
      throw new Error('Checkout unavailable');
    }});
  assert.match(checkout.storyCheckoutForm(), /AUD\s*99/);
  await checkout.requestStoryCheckout();
  assert.equal(opened, 1);
  assert.equal(requests, 0);
  assert.deepEqual(JSON.parse(sessionStorage.getItem('memoir-package-choice')), {plan:'printed_memoir_v1',books:4});
  state.supabase.user.is_anonymous = false;
  await checkout.requestStoryCheckout();
  assert.equal(requests, 1);
  assert.equal(state.loading, false);
  assert.deepEqual(notices, ['Checkout unavailable']);
});
