import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../../apps/web/client/memoir/client.js', import.meta.url), 'utf8');

test('life-stage labels do not suppress the automatic photo request', async () => {
  for (const when of ['青年时期', '婴儿时期', 'young adulthood', undefined]) {
    const entry = {place: '承德', hierarchy: ['Earth', '中国', '河北', '承德'], latitude: 40.98, longitude: 117.94};
    const requests = [];
    const saved = [];
    const item = {asset_id: 'crawl4ai-one', image_url: 'https://images.example/one.jpg', allowed_actions: {embed: true},
      date_expression: new Date().toISOString().slice(0, 10), latitude: 40.98, longitude: 117.94};
    const context = vm.createContext({
      state: {project: {id: 'project'}, placeJourney: entry}, URLSearchParams, workspaceUpdateQueue: Promise.resolve(),
      URL, window: {location: {origin: 'http://localhost'}}, document: {querySelector: () => null},
      PLACE_PHOTO_RESULT_LIMIT: 10,
      profile: () => ({story_focus: {when}, memory_places: [entry]}),
      api: async url => { requests.push(url); return {items: [item], status: 'PARTIAL'}; },
      placeHistoryKey: place => place.place,
      saveProfileUpdates: async updates => saved.push(updates), render: () => {},
    });
    for (const name of ['photoSearchPeriod', 'placePhotoCenter', 'photoRequestKey', 'photoMatchesScope', 'mergePlacePictures', 'loadPlacePictures']) {
      vm.runInContext(source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0], context);
    }
    await context.loadPlacePictures(entry, 'project');
    assert.equal(new URL(requests[0], 'http://localhost').searchParams.get('period'), '');
    assert.equal(saved[0].memory_places[0].pictures[0].asset_id, 'crawl4ai-one');
  }
});

test('explicit calendar period takes priority and remains grounded', () => {
  const context = vm.createContext({});
  vm.runInContext(source.match(/function photoSearchPeriod\([^]*?\n\}/)[0], context);
  assert.equal(context.photoSearchPeriod({period: '1980s'}, {when: '青年时期'}), '1980s');
  assert.equal(context.photoSearchPeriod({}, {when: '1983年'}), '1983年');
  assert.equal(context.photoSearchPeriod({}, {when: '1980–1989'}), '1980–1989');
  assert.equal(context.photoSearchPeriod({place: '悉尼', period: ''}, {when: '1983年4月'}), '');
  assert.equal(context.photoSearchPeriod({place: '承德市', period: '1983年4月'}, {when: '小时候'}), '1983年4月');
});

test('photo research reports real request progress and an unavailable provider fails the step', async () => {
  const entry = {place: '承德市', granularity: 'city', period: '1983年4月'};
  const events = [];
  let calls = 0;
  const context = vm.createContext({
    state: {project: {id: 'project'}}, URLSearchParams, workspaceUpdateQueue: Promise.resolve(),
    document: {querySelector: () => null}, profile: () => ({memory_places: [entry]}),
    api: async () => { calls++; return {items: [], status: 'UNAVAILABLE'}; },
    placeHistoryKey: place => place.place, translate: key => key, render: () => {},
  });
  for (const name of ['photoSearchPeriod', 'placePhotoCenter', 'photoRequestKey', 'loadPlacePictures']) {
    vm.runInContext(source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0], context);
  }
  await context.loadPlacePictures(entry, 'project', {onProgress: step => events.push(step)});
  assert.equal(calls, 1);
  assert.deepEqual(events.map(step => [step.skill, step.status]),
    [['place-photo-research', 'running'], ['place-photo-research', 'failed']]);
  assert.match(events[0].detail, /承德市 · 1983年4月/);
});

test('photo batches persist after being painted optimistically', async () => {
  const entry = {place: '承德市', granularity: 'city', period: '1983年4月',
    latitude: 40.9515, longitude: 117.9634};
  const picture = {asset_id: 'historical', image_url: 'https://images.example/1983.jpg',
    date_expression: '1983', latitude: entry.latitude, longitude: entry.longitude};
  const state = {project: {id: 'project', revision: 7, profile: {memory_places: [entry]}}, placeJourney: entry};
  const patches = [];
  const context = vm.createContext({
    state, URLSearchParams, URL, workspaceUpdateQueue: Promise.resolve(),
    window: {location: {origin: 'http://localhost'}}, document: {querySelector: () => null},
    profile: () => state.project.profile, placeHistoryKey: place => place.place,
    render: () => {}, toast: message => { throw new Error(message); },
    api: async (url, options = {}) => {
      if (options.method !== 'PATCH') return {items: [picture], status: 'PARTIAL', searching: false};
      const body = JSON.parse(options.body);
      patches.push(body);
      return {...state.project, profile: body.profile, revision: 8};
    },
  });
  for (const name of ['photoSearchPeriod', 'placePhotoCenter', 'photoRequestKey', 'photoMatchesScope',
    'mergePlacePictures', 'loadPlacePictures', 'mergeProfileUpdates', 'saveProfileUpdates']) {
    vm.runInContext(source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0], context);
  }
  await context.loadPlacePictures(entry, 'project');
  assert.equal(patches.length, 1);
  assert.equal(patches[0].expected_revision, 7);
  assert.equal(patches[0].profile.memory_places[0].pictures[0].asset_id, 'historical');
  assert.equal(patches[0].profile.memory_places[0].photo_search_period, '1983年4月');
});

test('selecting a restored place starts its own photo request', () => {
  const entry = {place: '承德市', granularity: 'city', period: '1983年4月'};
  const calls = [];
  const state = {project: {id: 'project'}};
  const context = vm.createContext({state, profile: () => ({memory_places: [entry]}),
    placeHistoryKey: place => place.place, loadPlacePictures: (place, project) => calls.push([place, project]),
    render: () => {},
  });
  vm.runInContext(source.match(/function selectPlace\([^]*?\n\}/)[0], context);
  context.selectPlace('承德市');
  assert.equal(state.selectedPlace, '承德市');
  assert.equal(calls[0][0], entry);
  assert.equal(calls[0][1], 'project');
});
