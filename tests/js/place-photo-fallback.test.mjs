import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {groupPlaces, mergePlaces, placeHistoryKey, matchesPlaceStage} from '../../apps/web/client/memoir/places.mjs';

const source = fs.readFileSync(new URL('../../apps/web/client/memoir/client.js', import.meta.url), 'utf8');
const photo = id => ({asset_id: id, image_url: `https://images.example/${id}.jpg`,
  source_url: `https://sources.example/${id}`, title: id, date_expression: '1989',
  attribution: 'Original photographer', allowed_actions: {embed: true}});
const city = {place: '承德', hierarchy: ['Earth', '中国', '河北', '承德'], granularity: 'city',
  photo_search_period: '1989年', pictures: [photo('city-photo')]};
const town = {place: '大石庙镇', hierarchy: [...city.hierarchy, '大石庙镇'], granularity: 'suburb',
  period: '1989年', pictures: []};
const otherCity = {place: 'Sydney', hierarchy: ['Earth', 'Australia', 'Sydney'], granularity: 'city',
  pictures: [photo('other-city-photo')]};

function harness(api, entries = [city, town, otherCity]) {
  let saved = {memory_places: structuredClone(entries), story_focus: {when: '1989年'}};
  const state = {project: {id: 'p'}, placeJourney: town, lifeStage: 'all', photoRequests: new Map()};
  const context = vm.createContext({
    state, URL, URLSearchParams, workspaceUpdateQueue: Promise.resolve(),
    window: {location: {origin: 'http://localhost'}}, document: {querySelector: () => null},
    profile: () => saved, api, render: () => {},
    saveProfileUpdates: async updates => { saved = {...saved, ...updates}; },
    mergePlaces, placeHistoryKey, matchesPlaceStage,
    workspacePlaceGroups: groupPlaces, groupChoices: () => [], placeHistoryChoices: () => '',
    placeWorkspaceSelection: () => saved.memory_places.find(place => place.place === town.place),
    placeMapTarget: place => place, placeJourneyMarkup: () => '<div>map</div>',
    searchedPictures: () => [],
    escapeHtml: value => String(value).replaceAll('"', '&quot;'), translate: key => key,
    referenceUrl: value => value || '', formatDateExpression: value => value,
    currentUiLocale: () => 'zh-CN',
  });
  for (const name of ['photoSearchPeriod', 'mergePlacePictures', 'loadPlacePictures',
    'renderablePictureItems', 'workspacePictureItems', 'photoPaginationMarkup',
    'pictureWall', 'workspaceMediaOverview', 'placesWorkspace']) {
    vm.runInContext(source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0], context);
  }
  return {context, state, profile: () => saved,
    entry: () => saved.memory_places.find(place => place.place === town.place)};
}

function assertCityFallback(h) {
  for (const render of ['workspaceMediaOverview', 'placesWorkspace']) {
    const html = h.context[render]();
    assert.match(html, /city-photo\.jpg/);
    assert.match(html, /承德 · Original photographer/);
    assert.match(html, /1989/);
    assert.doesNotMatch(html, /other-city-photo/);
  }
  assert.equal(h.profile().memory_places[0].pictures[0].asset_id, 'city-photo');
  assert.equal(h.entry().pictures.length, 0, 'fallback photos were copied into the child');
}

test('saved city photos stay visible during a child search and switch to arriving child photos', async () => {
  let finish;
  const pending = new Promise(resolve => { finish = resolve; });
  const calls = [];
  const h = harness(async (url, options) => {
    calls.push(url);
    await pending;
    await options.onPhotoPage({items: [photo('town-photo')], searching: true, status: 'PARTIAL'});
    const result = {items: [photo('town-photo')], searching: false, status: 'PARTIAL', next_cursor: null};
    await options.onPhotoPage(result);
    return result;
  });
  const search = h.context.loadPlacePictures(h.entry(), 'p');
  assertCityFallback(h);
  assert.match(h.context.workspaceMediaOverview(), /role="status"/);
  assert.equal(new URL(calls[0], 'http://localhost').searchParams.get('place'), '大石庙镇, 承德');
  assert.equal(new URL(calls[0], 'http://localhost').searchParams.get('period'), '1989年');
  finish();
  await search;
  const html = h.context.workspaceMediaOverview();
  assert.match(html, /town-photo\.jpg/);
  assert.doesNotMatch(html, /city-photo\.jpg/);
  assert.equal(h.profile().memory_places[0].pictures[0].asset_id, 'city-photo');
  assert.equal(h.entry().pictures[0].asset_id, 'town-photo');
});

for (const status of ['NO_MATCH', 'UNAVAILABLE', 'throws']) {
  test(`a ${status} child search keeps original city photos and child retry controls`, async () => {
    const h = harness(async () => {
      if (status === 'throws') throw Error('network unavailable');
      return {status, items: [], next_cursor: null};
    });
    await h.context.loadPlacePictures(h.entry(), 'p');
    assertCityFallback(h);
    if (status !== 'NO_MATCH') {
      assert.match(h.context.workspaceMediaOverview(), /data-photo-retry="[^>]*大石庙镇/);
    }
  });
}

test('non-embeddable child results use the saved city photos', async () => {
  const h = harness(async () => ({status: 'PARTIAL', items: [{...photo('blocked'), allowed_actions: {embed: false}}]}));
  await h.context.loadPlacePictures(h.entry(), 'p');
  const html = h.context.workspaceMediaOverview();
  assert.match(html, /city-photo\.jpg/);
  assert.doesNotMatch(html, /blocked\.jpg/);
});

test('same-period group photos are preferred and broader dated city photos remain available', () => {
  const sibling = {...town, place: '双桥区', hierarchy: [...city.hierarchy, '双桥区'],
    photo_search_period: '1989年', pictures: [photo('sibling-photo')]};
  const olderCity = {...city, photo_search_period: '1983年', pictures: [{...photo('older-city-photo'), date_expression: '1983'}]};
  const h = harness(async () => ({}), [olderCity, town, sibling, otherCity]);
  assert.match(h.context.workspaceMediaOverview(), /sibling-photo\.jpg/);
  assert.doesNotMatch(h.context.workspaceMediaOverview(), /older-city-photo\.jpg/);
  h.profile().memory_places = h.profile().memory_places.filter(place => place.place !== '双桥区');
  const html = h.context.workspaceMediaOverview();
  assert.match(html, /older-city-photo\.jpg/);
  assert.match(html, /1983/);
  assert.match(html, /承德 · Original photographer/);
  assert.doesNotMatch(html, /other-city-photo/);
});

test('town photos for an older search period do not outrank matching city photos', () => {
  const h = harness(async () => ({}), [city, {...town, photo_search_period: '1983年', pictures: [photo('old-town-photo')]}, otherCity]);
  assert.match(h.context.workspaceMediaOverview(), /city-photo\.jpg/);
  assert.doesNotMatch(h.context.workspaceMediaOverview(), /old-town-photo\.jpg/);
});

test('a life-stage filter retains the city group fallback from earlier history', () => {
  const h = harness(async () => ({}), [{...city, life_stage: 'baby'}, {...town, life_stage: 'childhood'}, otherCity]);
  h.state.lifeStage = 'childhood';
  assertCityFallback(h);
});
