import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {mergePlaces, placeHistoryKey} from '../../apps/web/client/memoir/places.mjs';

const source = fs.readFileSync(new URL('../../apps/web/client/memoir/client.js', import.meta.url), 'utf8');
const center = {latitude: 40.98, longitude: 117.94};
const scope = {photo_search_policy: 'place-fallback-gps-time-v8', photo_search_latitude: center.latitude,
  photo_search_longitude: center.longitude};
const picture = id => ({asset_id: id, image_url: `https://images.example/${id}.jpg`,
  date_expression: '1983', ...center});

function harness(entry, api, dependencies = {}) {
  Object.assign(entry, {period: '1980s', ...center, ...scope, ...entry});
  let saved = {memory_places: [entry]};
  const state = {project: {id: 'project'}, placeJourney: entry};
  const context = vm.createContext({state, URLSearchParams, URL, workspaceUpdateQueue: Promise.resolve(),
    window: {location: {origin: 'http://localhost'}}, document: {querySelector: () => null},
    profile: () => saved, api, placeHistoryKey: item => item.place, render: () => {},
    saveProfileUpdates: async updates => { saved = {...saved, ...updates}; },
    ...dependencies,
  });
  for (const name of ['captureProjectScope', 'isCurrentProjectScope', 'photoSearchPeriod', 'placePhotoCenter', 'photoRequestKey', 'photoMatchesScope', 'mergePlacePictures', 'loadPlacePictures']) {
    vm.runInContext(source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0], context);
  }
  return {context, state, entry: () => saved.memory_places[0]};
}

test('landmark search keeps its geographic parent and memory period', async () => {
  const calls = [];
  const h = harness({place: '离宫', hierarchy: ['Earth', '中国', '河北省', '承德市'],
    granularity: 'landmark', period: '1983年'}, async url => {
    calls.push(url); return {items: [], next_cursor: null};
  });
  await h.context.loadPlacePictures(h.entry(), 'project');
  const query = new URL(calls[0], 'http://localhost').searchParams;
  assert.equal(query.get('place'), '离宫, 承德市');
  assert.equal(query.get('period'), '1983年');
  assert.equal(h.entry().place, '离宫');
});

test('refresh restores persisted photos without searching after the old cache expires', async () => {
  let calls = 0;
  const saved = {place: 'Chengde', period: '1980s', photo_search_period: '1980s',
    photo_search_place: 'Chengde', photo_search_at: Date.now() - 86400000,
    photo_search_policy: 'place-fallback-gps-time-v8', photo_next_cursor: null, pictures: [picture('saved')]};
  const h = harness(saved, async () => { calls++; return {items: [], next_cursor: null}; });
  await h.context.loadPlacePictures(h.entry(), 'project');
  assert.equal(calls, 0, 'history restoration unnecessarily triggered photo discovery');
  assert.equal(h.entry().pictures[0].asset_id, 'saved');
});

for (const refresh of [false, true]) {
for (const fallback of [false, true]) {
test(`a repeated city alias preserves saved ${fallback ? 'GPS/time fallback ' : ''}photos${refresh ? ' through refreshed discovery' : ' without another lookup'}`, async () => {
  let calls = 0;
  const saved = {place: '承德市', hierarchy: ['Earth', '中国', '河北省', '承德市'],
    granularity: 'city', life_stage: 'childhood', ...center, ...scope, period: '1980s',
    photo_search_period: '1980s', photo_search_place: '承德市',
    photo_search_complete: true, pictures: [{...picture('saved'), ...(fallback ? {
      date_expression: '1970', search_fallback: 'gps_time', requested_period: '1980s', search_place: '承德市',
    } : {})}]};
  const alias = {place: '承德', hierarchy: ['Earth', '中国', '河北', '承德'],
    granularity: 'city', life_stage: 'young_adulthood'};
  const entry = mergePlaces([saved, alias])[0];
  const h = harness(entry, async () => { calls++; return {status: 'NO_MATCH', items: []}; }, {placeHistoryKey});
  await h.context.loadPlacePictures(h.entry(), 'project', {force: refresh});
  assert.equal(calls, Number(refresh), 'an alias alone must not invalidate cached discovery');
  assert.deepEqual(Array.from(h.entry().pictures, item => item.asset_id), ['saved']);
  assert.deepEqual(Array.from(h.entry().life_stages), ['childhood', 'young_adulthood']);
  assert.equal(h.entry().latitude, center.latitude);
});
}
}

test('a real geography or period change invalidates the alias photo cache', async () => {
  for (const changed of [{photo_search_place: '承德县'}, {photo_search_period: '1970s'}]) {
    let calls = 0;
    const h = harness({place: '承德', hierarchy: ['Earth', '中国', '河北', '承德'],
      granularity: 'city', photo_search_period: '1980s', photo_search_place: '承德市',
      photo_search_complete: true, pictures: [picture('outdated')], ...changed},
      async () => { calls++; return {status: 'NO_MATCH', items: []}; }, {placeHistoryKey});
    await h.context.loadPlacePictures(h.entry(), 'project');
    assert.equal(calls, 1);
    assert.equal(h.entry().pictures.length, 0, 'photos from a different search scope must be retired');
  }
});

test('a newly contextualized place retires the old cursor and accumulates arriving photos', async () => {
  const calls = [];
  const h = harness({place: '离宫', hierarchy: ['Earth', '中国', '承德市', '离宫'],
    granularity: 'landmark', period: '1983年', photo_search_period: '1983年',
    photo_next_cursor: 'old:10', pictures: [picture('old')]}, async (url, options) => {
    calls.push(url);
    await options.onPhotoPage({items: [picture('a')], searching: true});
    await options.onPhotoPage({items: [picture('b')], searching: false, next_cursor: null});
    return {};
  });
  await h.context.loadPlacePictures(h.entry(), 'project', {more: true});
  assert.equal(calls.length, 0);
  await h.context.loadPlacePictures(h.entry(), 'project');
  assert.equal(new URL(calls[0], 'http://localhost').searchParams.has('cursor'), false);
  assert.deepEqual(Array.from(h.entry().pictures, item => item.asset_id), ['a', 'b']);
});

test('appends pages, deduplicates overlaps and stops at exhaustion', async () => {
  const calls = [];
  const h = harness({place: 'Chengde', period: '1980s'}, async url => {
    calls.push(url);
    return calls.length === 1
      ? {items: [picture('a'), picture('b')], next_cursor: 'snapshot:2'}
      : {items: [picture('b'), picture('c')], next_cursor: null};
  });
  await h.context.loadPlacePictures(h.entry(), 'project');
  await h.context.loadPlacePictures(h.entry(), 'project', {more: true});
  await h.context.loadPlacePictures(h.entry(), 'project', {more: true});
  await h.context.loadPlacePictures(h.entry(), 'project');
  assert.equal(calls.length, 2);
  assert.equal(new URL(calls[1], 'http://localhost').searchParams.get('cursor'), 'snapshot:2');
  assert.equal(Array.from(h.entry().pictures, item => item.asset_id).join(','), 'a,b,c');
});

test('photo results wait for workspace writes and preserve a newer place', async () => {
  let release;
  const pendingWrite = new Promise(resolve => { release = resolve; });
  const h = harness({place: 'Chengde', period: '1983年'}, async () => ({items: [picture('a')], status: 'READY'}));
  h.context.workspaceUpdateQueue = pendingWrite;
  const photos = h.context.loadPlacePictures(h.entry(), 'project');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.entry().pictures, undefined, 'photo persistence raced the workspace write');
  await h.context.saveProfileUpdates({memory_places: [h.entry(), {place: 'Sydney'}]});
  release();
  await photos;
  assert.equal(h.context.profile().memory_places.length, 2);
  assert.equal(h.entry().pictures[0].asset_id, 'a');
});

test('concurrent scroll events issue only one request', async () => {
  let resolve;
  let calls = 0;
  const response = new Promise(done => { resolve = done; });
  const h = harness({place: 'Chengde'}, async () => { calls++; return response; });
  const pending = h.context.loadPlacePictures(h.entry(), 'project');
  await h.context.loadPlacePictures(h.entry(), 'project');
  assert.equal(calls, 1);
  resolve({items: [picture('a')], next_cursor: null});
  await pending;
});

test('expired cursors restart safely without erasing visible pictures', async () => {
  const calls = [];
  const h = harness({place: 'Chengde', period: '1980s', photo_search_period: '1980s',
    photo_next_cursor: 'expired:10', pictures: [picture('a')]}, async url => {
    calls.push(url);
    if (calls.length === 1) throw Object.assign(new Error('expired'), {status: 410});
    return {items: [picture('a'), picture('b')], next_cursor: 'fresh:2'};
  });
  await h.context.loadPlacePictures(h.entry(), 'project', {more: true});
  assert.equal(calls.length, 2);
  assert.equal(new URL(calls[1], 'http://localhost').searchParams.has('cursor'), false);
  assert.equal(Array.from(h.entry().pictures, item => item.asset_id).join(','), 'a,b');
  assert.equal(h.entry().photo_next_cursor, 'fresh:2');
});

test('unavailable later pages preserve pictures and expose manual retry', async () => {
  const original = {place: 'Chengde', photo_search_period: '1980s', photo_next_cursor: 'snapshot:10', pictures: [picture('a')]};
  const h = harness(original, async () => ({status: 'UNAVAILABLE', items: []}));
  await h.context.loadPlacePictures(h.entry(), 'project', {more: true});
  assert.equal(h.entry(), original);
  assert.ok(Array.from(h.state.photoRequests.values())[0].error);
});

test('a different period never reuses old cursors or appends wrong-period photos', async () => {
  const calls = [];
  const h = harness({place: 'Chengde', period: '1990s', photo_search_period: '1980s',
    photo_next_cursor: 'old:10', pictures: [picture('old')]}, async url => {
    calls.push(url); return {items: [{...picture('new'), date_expression: '1993'}], next_cursor: null};
  });
  await h.context.loadPlacePictures(h.entry(), 'project', {more: true});
  assert.equal(calls.length, 0);
  await h.context.loadPlacePictures(h.entry(), 'project');
  assert.equal(new URL(calls[0], 'http://localhost').searchParams.get('period'), '1990s');
  assert.equal(Array.from(h.entry().pictures, item => item.asset_id).join(','), 'new');
});

test('client deduplication also recognizes Flickr size variants', () => {
  const h = harness({place: 'Chengde'}, async () => ({}));
  const merged = h.context.mergePlacePictures(
    [{asset_id:'one', image_url:'https://live.staticflickr.com/12/123_secret_z.jpg'}],
    [{asset_id:'two', image_url:'https://farm1.staticflickr.com/12/123_secret_b.jpg?utm_source=google'}]);
  assert.equal(merged.length, 1);
});

test('rendering without a gallery does not dereference a missing element', () => {
  const block = source.match(/const nextGallery = \$\("\.place-pictures\[data-photo-place\]"\);[^]*?bindPhotoPagination\(\);/)[0];
  const context = vm.createContext({$: () => null, galleryPlace: undefined, galleryTop: 0, bindPhotoPagination: () => {}});
  assert.doesNotThrow(() => vm.runInContext(block, context));
});

test('older empty searches are retried under the radius and year policy', async () => {
  let calls = 0;
  const h = harness({place: 'Chengde', period: '1983年', photo_search_period: '1983年',
    photo_search_policy: 'place-aliases-v4',
    photo_search_at: Date.now(), photo_next_cursor: null, pictures: []}, async () => {
    calls++; return {items: [picture('a')], next_cursor: null};
  });
  await h.context.loadPlacePictures(h.entry(), 'project');
  await h.context.loadPlacePictures(h.entry(), 'project');
  assert.equal(calls, 1);
  assert.equal(h.entry().photo_search_policy, 'place-fallback-gps-time-v8');
});

test('decade matches are labelled and a zero-image wall stays hidden', () => {
  const context = vm.createContext({state: {project: {id:'p'}}, profile: () => ({}), escapeHtml: value => value, translate: key => key,
    placeHistoryKey: item => item.place, referenceUrl: value => value,
    formatDateExpression: value => value, currentUiLocale: () => 'en-AU',
    photoPaginationMarkup: () => '', URL, window: {location: {origin: 'http://localhost'}}});
  for (const name of ['mergePlacePictures', 'photoMemoryState', 'photoMemoryControls', 'pictureWall']) {
    vm.runInContext(source.match(new RegExp(`function ${name}\\([^]*?\\n\\}`))[0], context);
  }
  assert.equal(context.pictureWall([]), '');
  const html = context.pictureWall([{...picture('a'), allowed_actions: {embed: true},
    date_expression: '1984', period_match: 'decade'}]);
  assert.ok(html.includes('1984'));
  assert.ok(html.includes('Memoir.workspace.sameDecadeReference'));
});

test('verified photos are visible while the response is still researching', async () => {
  let release;
  const finished = new Promise(resolve => { release = resolve; });
  const h = harness({place: 'Chengde', period: '1980s'}, async (url, options) => {
    await options.onPhotoPage({items: [picture('early')], searching: true, status: 'PARTIAL'});
    await finished;
    const result = {items: [picture('early'), picture('late')], searching: false, next_cursor: null};
    await options.onPhotoPage(result);
    return result;
  });
  const request = h.context.loadPlacePictures(h.entry(), 'project');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.entry().pictures[0].asset_id, 'early');
  assert.equal(h.entry().photo_search_at, 0, 'Incomplete results were marked cached');
  assert.ok(Array.from(h.state.photoRequests.values())[0].loading);
  release();
  await request;
  assert.equal(h.entry().pictures.length, 2);
  assert.ok(h.entry().photo_search_at > 0);
  assert.equal(Array.from(h.state.photoRequests.values())[0].loading, false);
});

test('photo transport handles split records and rejects interrupted streams', async () => {
  const context = vm.createContext({TextDecoder, localizedErrorMessage: () => 'interrupted'});
  vm.runInContext(source.match(/async function consumePhotoStream\([^]*?\n\}/)[0], context);
  const response = chunks => ({body: new ReadableStream({start(controller) {
    chunks.forEach(chunk => controller.enqueue(new TextEncoder().encode(chunk)));
    controller.close();
  }})});
  const seen = [];
  const result = await context.consumePhotoStream(response([
    '{"items":[{"asset_id":"early"}],"sear', 'ching":true}\n',
    '{"items":[{"asset_id":"early"}],"searching":false}']), page => seen.push(page));
  assert.equal(seen.length, 2);
  assert.equal(result.searching, false);
  await assert.rejects(context.consumePhotoStream(response(['{"items":[],"searching":true}\n']), () => {}), /interrupted/);
});

test('an interrupted search retains early photos and exposes retry without a cursor', async () => {
  const h = harness({place: 'Chengde', period: '1980s'}, async (url, options) => {
    await options.onPhotoPage({items: [picture('early')], searching: true});
    throw Error('disconnected');
  });
  await h.context.loadPlacePictures(h.entry(), 'project');
  assert.equal(h.entry().pictures[0].asset_id, 'early');
  h.context.escapeHtml = value => value;
  h.context.translate = value => value;
  vm.runInContext(source.match(/function photoPaginationMarkup\([^]*?\n\}/)[0], h.context);
  assert.ok(h.context.photoPaginationMarkup(h.entry()).includes('data-photo-retry="Chengde"'));
});

test('old cached empty results are rechecked and blocked sources remain retryable', async () => {
  let calls = 0;
  const h = harness({place: 'Chengde', photo_search_period: '', pictures: [],
    photo_search_policy: 'warm-progressive-v2', photo_search_at: Date.now(), photo_next_cursor: null},
    async () => {
      calls++;
      return {status: 'UNAVAILABLE', items: [], failures: [{provider: 'google', reason: 'verification_required'}]};
    });
  await h.context.loadPlacePictures(h.entry(), 'project');
  assert.equal(calls, 1);
  assert.ok(Array.from(h.state.photoRequests.values())[0].error);
  assert.equal(Array.from(h.state.photoRequests.values())[0].failures[0].reason, 'verification_required');
  await h.context.loadPlacePictures(h.entry(), 'project');
  assert.equal(calls, 2, 'failed search was cached as a completed no-match');
});

test('a changed coordinate starts a separate request and rejects the older response', async () => {
  const calls = [];
  let release;
  const pending = new Promise(resolve => { release = resolve; });
  const h = harness({place: 'Chengde', period: '1983年'}, async url => {
    calls.push(new URL(url, 'http://localhost').searchParams);
    if (calls.length === 1) return await pending;
    return {items: [{...picture('new-center'), latitude: 41.5}], next_cursor: null};
  });
  const first = h.context.loadPlacePictures(h.entry(), 'project');
  await new Promise(resolve => setImmediate(resolve));
  await h.context.saveProfileUpdates({memory_places: [{...h.entry(), latitude: 41.5}]});
  await h.context.loadPlacePictures(h.entry(), 'project');
  assert.equal(calls.length, 2);
  assert.equal(calls[0].get('latitude'), '40.98');
  assert.equal(calls[1].get('latitude'), '41.5');
  release({items: [picture('old-center')], next_cursor: null});
  await first;
  assert.deepEqual(Array.from(h.entry().pictures, item => item.asset_id), ['new-center']);
});

test('legacy cached photos are refreshed under the strict scope policy', async () => {
  let calls = 0;
  const h = harness({place: 'Chengde', period: '1983年', photo_search_period: '1983年',
    photo_search_policy: 'place-aliases-v4', photo_search_complete: true, pictures: [picture('legacy')]},
    async () => { calls++; return {items: [picture('verified')], next_cursor: null}; });
  await h.context.loadPlacePictures(h.entry(), 'project');
  assert.equal(calls, 1);
  assert.deepEqual(Array.from(h.entry().pictures, item => item.asset_id), ['verified']);
});
