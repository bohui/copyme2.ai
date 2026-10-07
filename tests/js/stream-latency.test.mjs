import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {mergePlaces} from '../../apps/web/client/memoir/places.mjs';

const source = fs.readFileSync(new URL('../../apps/web/client/memoir/client.js', import.meta.url), 'utf8');
const extract = name => source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0];

test('map preview renders during text streaming without a profile write or photo wait', async () => {
  let renders = 0;
  const context = vm.createContext({
    state: {supabase: {accessToken: 'test'}, project: {id: 'p'}, chat: []},
    appliedWorkspaceSequences: new Map(), workspaceUpdateQueue: Promise.resolve(),
    conversationLanguage: () => 'en-AU', simulatedLoopTrace: () => [],
    nextAssistantMessageId: () => 'm', render: () => { renders++; }, updateStreamingAssistantMessage: () => {},
    placeHistoryKey: item => item.place, resolvePlaceMap: () => {},
    saveProfileUpdates: () => assert.fail('preview must not persist'),
    loadPlacePictures: () => assert.fail('preview must not block on photos'),
    streamAgentTurn: async (_text, onDelta, onEvent) => {
      await onDelta('I remember ');
      await onEvent({type: 'place_preview', data: {project_id: 'p', source_sequence: 1810000000001000000,
        place_journey: {place: 'Sydney', granularity: 'city', hierarchy: ['Earth', 'Australia', 'Sydney']}}});
      assert.equal(context.state.placeJourney.place, 'Sydney');
      assert.equal(context.state.chat.at(-1).streaming, true);
      assert.equal(context.state.selectedPlace, 'Sydney');
      await onEvent({type: 'place_preview', data: {project_id: 'other', source_sequence: 2,
        place_journey: {place: 'Paris'}}});
      await onEvent({type: 'place_preview', data: {project_id: 'p', source_sequence: 1810000000000000000,
        place_journey: {place: 'Paris'}}});
      assert.equal(context.state.placeJourney.place, 'Sydney');
      await onDelta('Sydney.');
      return {reply: 'I remember Sydney.', conversation_saved: true};
    },
  });
  context.refreshPrivateDraft = async () => {};
  vm.runInContext(extract('agentTurn'), context);
  await context.agentTurn('Sydney');
  assert.ok(renders >= 2);
});

test('a failed conversational save restores the previous place preview', async () => {
  const previous = {place: 'Chengde'};
  const context = vm.createContext({
    state: {supabase: {accessToken: 'test'}, project: {id: 'p'}, chat: [],
      placeJourney: previous, selectedPlace: 'Chengde'},
    appliedWorkspaceSequences: new Map(), workspaceUpdateQueue: Promise.resolve(),
    conversationLanguage: () => 'en-AU', simulatedLoopTrace: () => [],
    render: () => {}, toast: () => {}, placeHistoryKey: item => item.place, resolvePlaceMap: () => {},
    streamAgentTurn: async (_text, _onDelta, onEvent) => {
      await onEvent({type: 'place_preview', data: {project_id: 'p', source_sequence: 1,
        place_journey: {place: 'Sydney'}}});
      throw new Error('save failed');
    },
  });
  context.refreshPrivateDraft = async () => {};
  vm.runInContext(extract('agentTurn'), context);
  await context.agentTurn('Sydney');
  assert.equal(context.state.placeJourney, previous);
  assert.equal(context.state.selectedPlace, 'Chengde');
});

test('buffered response is not paced by one animation frame per delta', async () => {
  let frames = 0;
  const context = vm.createContext({
    state: {supabase: {accessToken: 'test'}, project: {id: 'p'}, chat: []},
    conversationLanguage: () => 'en-AU', simulatedLoopTrace: () => [],
    nextAssistantMessageId: () => 'm', render: () => {}, updateStreamingAssistantMessage: () => {},
    waitForAssistantPaint: async () => { frames++; },
    streamAgentTurn: async (_text, onDelta) => {
      for (let i = 0; i < 500; i++) await onDelta('a');
      return {reply: 'a'.repeat(500), conversation_saved: true};
    },
  });
  context.refreshPrivateDraft = async () => {};
  vm.runInContext(extract('agentTurn'), context);
  const result = await context.agentTurn('Hi');
  assert.equal(result.streamedMessage.text.length, 500);
  assert.ok(frames <= 1, `500 buffered deltas required ${frames} separate animation frames`);
});

test('a complete server response is shown without replaying a simulated stream', async () => {
  const context = vm.createContext({
    state: {supabase: {accessToken: 'test'}, project: {id: 'p'}, chat: []},
    conversationLanguage: () => 'en-AU', simulatedLoopTrace: () => [],
    nextAssistantMessageId: () => 'm', render: () => {},
    streamAgentTurn: async () => ({reply: 'A complete response', conversation_saved: true}),
  });
  context.refreshPrivateDraft = async () => {};
  vm.runInContext(extract('agentTurn'), context);
  const result = await context.agentTurn('Hi');
  assert.equal(result.streamedMessage?.text, 'A complete response');
  assert.equal(result.streamedMessage.streaming, false);
});

test('place activation and later progress do not wait for photo discovery', async () => {
  let event;
  let remembered = false;
  let renders = 0;
  let finishPhotos;
  const photos = new Promise(resolve => { finishPhotos = resolve; });
  let currentProfile = {memory_places: [
    {place: 'Chengde', granularity: 'city', hierarchy: ['Earth', 'China', 'Chengde']},
    {place: 'Sydney', granularity: 'city', hierarchy: ['Earth', 'Australia', 'Sydney']},
  ]};
  let photoCalls = 0;
  const context = vm.createContext({
    state: {supabase: {accessToken: 'test'}, project: {id: 'p'}, chat: []},
    LIFE_STAGES: [], appliedWorkspaceSequences: new Map(), workspaceUpdateQueue: Promise.resolve(),
    conversationLanguage: () => 'en-AU', simulatedLoopTrace: () => [],
    nextAssistantMessageId: () => 'm', render: () => { renders++; }, updateStreamingAssistantMessage: () => {},
    profile: () => currentProfile, mergePlaces, placeHistoryKey: entry => entry.place,
    saveProfileUpdates: async update => { currentProfile = {...currentProfile, ...update}; },
    resolvePlaceMap: () => {}, loadPlacePictures: () => { photoCalls++; return photos; },
    rememberPlaceJourneyProject: () => { remembered = true; }, toast: () => {},
    streamAgentTurn: async (_text, _onDelta, onEvent) => {
      event = onEvent;
      return {reply: 'Hello', conversation_saved: true};
    },
  });
  context.refreshPrivateDraft = async () => {};
  vm.runInContext(extract('agentTurn'), context);
  const result = await context.agentTurn('I remember Chengde');
  let delivered = false;
  const delivery = event({type: 'workspace_update', data: {
    place_journey: {place: 'Chengde', granularity: 'city', hierarchy: ['Earth', 'China', 'Chengde']},
    place_journey_change: {changed: true},
  }}).then(() => { delivered = true; });
  await new Promise(resolve => setImmediate(resolve));
  try {
    assert.equal(delivered, true, 'photo discovery blocks the workspace event consumer');
    assert.equal(remembered, true, 'place activation waits for photo discovery');
    assert.ok(renders > 0, 'map is not rendered until photos settle');
    await event({type: 'workspace_update', data: {profile_updates: {story_focus: {when: '1980s'}}}});
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(photoCalls, 2, 'late date context never refreshes the photo search');
    await event({type: 'progress', data: {id: 'workspace', status: 'completed'}});
    assert.equal(context.state.chat.at(-1).trace[0].id, 'workspace');
  } finally {
    finishPhotos();
    await delivery;
  }
});

test('reload restores the latest mentioned place while preserving chronological history', async () => {
  const places = [
    {place: 'Chengde', granularity: 'city', hierarchy: ['Earth', 'China', 'Chengde'], life_stage: 'childhood', revision: 3},
    {place: 'Sydney', granularity: 'city', hierarchy: ['Earth', 'Australia', 'Sydney'], life_stage: 'young_adulthood', revision: 2},
  ];
  const context = vm.createContext({
    state: {project: {id: 'p'}}, profile: () => ({memory_places: places}), mergePlaces,
    placeHistoryKey: item => item.place, rememberPlaceJourneyProject: () => {},
    saveProfileUpdates: async () => {}, loadPlacePictures: async () => {}, resolvePlaceMap: () => {},
  });
  vm.runInContext(extract('hydratePlaceJourney'), context);
  await context.hydratePlaceJourney();
  assert.equal(context.state.placeJourney.place, 'Chengde');
  assert.equal(context.state.lifeStage, 'childhood');
  assert.equal(mergePlaces(places).at(-1).place, 'Sydney');
});

test('one turn saves and groups every place while retaining existing photographs', async () => {
  const town = {place: '大石庙镇', hierarchy: ['Earth', '中国', '河北', '承德', '大石庙镇'], granularity: 'suburb'};
  const district = {place: '双桥区', hierarchy: ['Earth', '中国', '河北', '承德', '双桥区'], granularity: 'suburb'};
  let currentProfile = {memory_places: [{...town, life_stage: 'childhood', pictures: [{asset_id: 'old-photo'}]}]};
  const requests = [], photos = [];
  let event, saves = 0;
  const context = vm.createContext({
    state: {supabase: {accessToken: 'test'}, project: {id: 'p'}, chat: []},
    LIFE_STAGES: [{id: 'childhood'}], appliedWorkspaceSequences: new Map(), workspaceUpdateQueue: Promise.resolve(),
    placeGroupRecords: new Map(), placeGroupRequests: new Map(), placeGroupLatest: new Map(),
    setTimeout: () => {},
    conversationLanguage: () => 'zh-CN', simulatedLoopTrace: () => [],
    nextAssistantMessageId: () => 'm', render: () => {}, toast: () => {},
    profile: () => currentProfile, mergePlaces, placeHistoryKey: entry => entry.place,
    saveProfileUpdates: async update => { saves++; currentProfile = {...currentProfile, ...update}; },
    resolvePlaceMap: journey => context.resolvePlaceGroups(journey),
    loadPlacePictures: journey => { photos.push(journey.place); },
    rememberPlaceJourneyProject: () => {},
    api: async (url, options) => {
      requests.push({url, body: JSON.parse(options.body)});
      return {places: []};
    },
    streamAgentTurn: async (_text, _delta, onEvent) => {
      event = onEvent;
      return {reply: '童年的两个地方。', conversation_saved: true};
    },
  });
  for (const name of ['publicPlaceFields', 'resolvePlaceGroups', 'agentTurn']) vm.runInContext(extract(name), context);
  await context.agentTurn('从大石庙镇搬到双桥区');
  await event({type: 'workspace_update', data: {
    source_sequence: 10, place_journey: district, place_journey_change: {changed: false, mentioned: true},
    place_journeys: [town, district],
  }});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(saves, 1);
  assert.deepEqual(currentProfile.memory_places.map(place => place.place), ['大石庙镇', '双桥区']);
  assert.equal(currentProfile.memory_places[0].pictures[0].asset_id, 'old-photo');
  assert.equal(context.state.selectedPlace, '双桥区');
  assert.deepEqual(photos, ['大石庙镇', '双桥区']);
  assert.equal(requests.length, 2);
  for (const request of requests) {
    assert.equal(request.url, '/v1/projects/p/place-groups');
    assert.deepEqual(new Set(request.body.places.map(place => place.place)), new Set(['大石庙镇', '双桥区']));
    assert.ok(request.body.places.every(place => !('pictures' in place) && !('life_stage' in place)));
  }
  await event({type: 'workspace_update', data: {
    source_sequence: 9, place_journey: town, place_journey_change: {changed: true}, place_journeys: [town],
  }});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(saves, 1);
  assert.equal(context.state.selectedPlace, '双桥区');
});

for (const profileUpdates of [undefined, {story_focus: {where: '悉尼', life_stage: 'midlife'}}]) {
test(`uses backend place stages with ${profileUpdates ? 'a different profile focus' : 'a place-only stream event'}`, async () => {
  const sydney = {place: '悉尼', hierarchy: ['Earth', '澳大利亚', '新南威尔士州', '悉尼'], granularity: 'city', life_stage: null};
  const chengde = {place: '承德市', hierarchy: ['Earth', '中国', '河北省', '承德市'], granularity: 'city', life_stage: 'baby'};
  let currentProfile = {memory_places: []};
  let event;
  const context = vm.createContext({
    state: {supabase: {accessToken: 'test'}, project: {id: 'p'}, chat: []},
    LIFE_STAGES: [{id: 'baby'}], appliedWorkspaceSequences: new Map(), workspaceUpdateQueue: Promise.resolve(),
    conversationLanguage: () => 'zh-CN', simulatedLoopTrace: () => [],
    nextAssistantMessageId: () => 'm', render: () => {}, toast: () => {},
    profile: () => currentProfile, mergePlaces, placeHistoryKey: entry => entry.place,
    saveProfileUpdates: async update => { currentProfile = {...currentProfile, ...update}; },
    resolvePlaceMap: () => {}, loadPlacePictures: () => {}, rememberPlaceJourneyProject: () => {},
    streamAgentTurn: async (_text, _delta, onEvent) => {
      event = onEvent;
      return {reply: '我记下了。', conversation_saved: true};
    },
  });
  context.refreshPrivateDraft = async () => {};
  vm.runInContext(extract('agentTurn'), context);
  await context.agentTurn('我叫慧博，现在生活在悉尼，但是我于1983年4月出生在河北省承德市附属医院');
  await event({type: 'workspace_update', data: {
    source_sequence: 1,
    profile_updates: profileUpdates,
    place_journey: chengde,
    place_journey_change: {changed: true},
    place_journeys: [sydney, chengde],
  }});
  await new Promise(resolve => setImmediate(resolve));
  const saved = Object.fromEntries(currentProfile.memory_places.map(place => [place.place, place]));
  assert.equal(saved['悉尼'].life_stage, null);
  assert.deepEqual(saved['悉尼'].life_stages, []);
  assert.equal(saved['承德市'].life_stage, 'baby');
  assert.deepEqual(saved['承德市'].life_stages, ['baby']);
});
}

test('photo workspace exposes discovery even before any eligible result', () => {
  const entry = {place: 'Chengde'};
  const context = vm.createContext({
    state: {placeJourney: entry, project: {id: 'p'}, lifeStage: 'all', photoRequests: new Map()},
    escapeHtml: String, translate: key => key, placeWorkspaceSelection: () => entry,
    placeMapTarget: () => ({}), profile: () => ({memory_places: [entry]}), mergePlaces: items => items,
    placeHistoryChoices: () => '', placeJourneyMarkup: () => '<div>map</div>',
    workspacePlaceGroups: () => [{city: entry, members: [entry]}], groupChoices: () => [entry],
    renderablePictureItems: items => items, workspacePictureItems: () => [], pictureWall: () => '',
    placeHistoryKey: item => item.place, photoSearchPeriod: () => '',
    photoRequestKey: () => JSON.stringify(['p', 'Chengde', '', null, null]),
  });
  vm.runInContext(extract('workspaceMediaOverview'), context);
  assert.match(context.workspaceMediaOverview(), /workspace-media-gallery/);
  context.state.photoRequests.set(JSON.stringify(['p', 'Chengde', '', null, null]), {loading: true});
  assert.match(context.workspaceMediaOverview(), /role="status"/);
});
