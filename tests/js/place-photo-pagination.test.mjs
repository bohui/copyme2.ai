import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../../apps/web/client/memoir/client.js', import.meta.url), 'utf8');
const picture = id => ({asset_id: id, image_url: `https://images.example/${id}.jpg`});

function harness(entry, api) {
  let saved = {memory_places: [entry]};
  const state = {project: {id: 'project'}, placeJourney: entry};
  const context = vm.createContext({state, URLSearchParams, URL,
    window: {location: {origin: 'http://localhost'}}, document: {querySelector: () => null},
    profile: () => saved, api, placeHistoryKey: item => item.place, render: () => {},
    saveProfileUpdates: async updates => { saved = {...saved, ...updates}; },
  });
  for (const name of ['photoSearchPeriod', 'mergePlacePictures', 'loadPlacePictures']) {
    vm.runInContext(source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0], context);
  }
  return {context, state, entry: () => saved.memory_places[0]};
}

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
  const original = {place: 'Chengde', photo_search_period: '', photo_next_cursor: 'snapshot:10', pictures: [picture('a')]};
  const h = harness(original, async () => ({status: 'UNAVAILABLE', items: []}));
  await h.context.loadPlacePictures(h.entry(), 'project', {more: true});
  assert.equal(h.entry(), original);
  assert.ok(Array.from(h.state.photoRequests.values())[0].error);
});

test('a different period never reuses old cursors or appends wrong-period photos', async () => {
  const calls = [];
  const h = harness({place: 'Chengde', period: '1990s', photo_search_period: '1980s',
    photo_next_cursor: 'old:10', pictures: [picture('old')]}, async url => {
    calls.push(url); return {items: [picture('new')], next_cursor: null};
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

test('older empty searches are retried under the bilingual search policy', async () => {
  let calls = 0;
  const h = harness({place: 'Chengde', period: '1983年', photo_search_period: '1983年',
    photo_search_at: Date.now(), photo_next_cursor: null, pictures: []}, async () => {
    calls++; return {items: [picture('a')], next_cursor: null};
  });
  await h.context.loadPlacePictures(h.entry(), 'project');
  await h.context.loadPlacePictures(h.entry(), 'project');
  assert.equal(calls, 1);
  assert.equal(h.entry().photo_search_policy, 'bilingual-decade-v1');
});

test('decade matches are labelled and a zero-image wall stays hidden', () => {
  const context = vm.createContext({escapeHtml: value => value, translate: key => key,
    placeHistoryKey: item => item.place, referenceUrl: value => value,
    formatDateExpression: value => value, currentUiLocale: () => 'en-AU',
    photoPaginationMarkup: () => ''});
  vm.runInContext(source.match(/function pictureWall\([^]*?\n\}/)[0], context);
  assert.equal(context.pictureWall([]), '');
  const html = context.pictureWall([{...picture('a'), allowed_actions: {embed: true},
    date_expression: '1984', period_match: 'decade'}]);
  assert.ok(html.includes('1984'));
  assert.ok(html.includes('Memoir.workspace.sameDecadeReference'));
});
