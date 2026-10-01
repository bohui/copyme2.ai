import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {mergePlaces} from '../../apps/web/client/memoir/places.mjs';

const source = fs.readFileSync(new URL('../../apps/web/client/memoir/client.js', import.meta.url), 'utf8');
const extract = name => source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0];

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
    {place: 'Chengde', hierarchy: ['Earth', 'China', 'Chengde']},
    {place: 'Sydney', hierarchy: ['Earth', 'Australia', 'Sydney']},
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
  vm.runInContext(extract('agentTurn'), context);
  const result = await context.agentTurn('I remember Chengde');
  let delivered = false;
  const delivery = event({type: 'workspace_update', data: {
    place_journey: {place: 'Chengde', hierarchy: ['Earth', 'China', 'Chengde']},
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
    {place: 'Chengde', hierarchy: ['Earth', 'China', 'Chengde'], life_stage: 'childhood', revision: 3},
    {place: 'Sydney', hierarchy: ['Earth', 'Australia', 'Sydney'], life_stage: 'young_adulthood', revision: 2},
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

test('photo workspace exposes discovery even before any eligible result', () => {
  const entry = {place: 'Chengde'};
  const context = vm.createContext({
    state: {placeJourney: entry, project: {id: 'p'}, lifeStage: 'all', photoRequests: new Map()},
    escapeHtml: String, translate: key => key, placeWorkspaceSelection: () => entry,
    placeMapTarget: () => ({}), profile: () => ({memory_places: [entry]}), mergePlaces: items => items,
    placeHistoryChoices: () => '', placeJourneyMarkup: () => '<div>map</div>',
    renderablePictureItems: items => items, workspacePictureItems: () => [], pictureWall: () => '',
    placeHistoryKey: item => item.place, photoSearchPeriod: () => '',
  });
  vm.runInContext(extract('workspaceMediaOverview'), context);
  assert.match(context.workspaceMediaOverview(), /workspace-media-gallery/);
  context.state.photoRequests.set(JSON.stringify(['p', 'Chengde', '']), {loading: true});
  assert.match(context.workspaceMediaOverview(), /role="status"/);
});
