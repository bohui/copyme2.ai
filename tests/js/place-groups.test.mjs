import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {groupPlaces, groupMapPins, groupMapFrame, mergePlaces, placeHistoryKey} from '../../apps/web/client/memoir/places.mjs';

const city = {place:'承德', hierarchy:['Earth','中国','河北','承德'], granularity:'city', latitude:40.97, longitude:117.93};
const district = {place:'双桥区', hierarchy:[...city.hierarchy,'双桥区'], granularity:'suburb', latitude:40.93, longitude:117.96, pictures:[{asset_id:'district'}]};
const town = {place:'大石庙镇', hierarchy:['Earth','中国','河北省','承德市','大石庙镇'], granularity:'suburb', latitude:40.921, longitude:117.962, pictures:[{asset_id:'town'}]};

test('one city view contains independent district and town pins', () => {
  const entries = mergePlaces([city, district, town]);
  const groups = groupPlaces(entries);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].city.place, '承德');
  assert.deepEqual(groupMapPins(groups[0]).map(pin => pin.place), ['双桥区', '大石庙镇']);
  assert.deepEqual(entries.flatMap(entry => entry.pictures).map(picture => picture.asset_id), ['district','town']);
  const frame = groupMapFrame(groups[0], city);
  assert.ok(frame.height < 24000, 'child pins retain the old city-wide zoom');
  assert.ok(frame.latitude >= town.latitude && frame.latitude <= district.latitude);
});

test('a new child joins the existing city and a new city stays separate', () => {
  const first = groupPlaces([city, district]);
  const next = groupPlaces([city, district, town, {place:'Sydney', hierarchy:['Earth','Australia','Sydney'], granularity:'city'}]);
  assert.equal(first[0].key, next[0].key);
  assert.equal(next.length, 2);
  assert.equal(next[0].members.length, 3);
  assert.notEqual(placeHistoryKey(district), placeHistoryKey(town));
});

test('unresolved children are not pinned at the city centre', () => {
  const grouped = groupPlaces([city, {...district, latitude:city.latitude, longitude:city.longitude}, {...town, map_pin:null}])[0];
  assert.deepEqual(groupMapPins(grouped).map(pin => pin.place), ['承德']);
});

test('provider-confirmed city membership works without a city ancestor', () => {
  const groups = groupPlaces([
    {...district, hierarchy:['Earth','中国','双桥区'], map_city:city},
    {...town, hierarchy:['Earth','中国','大石庙镇'], map_city:city},
  ]);
  assert.equal(groups.length, 1);
  assert.equal(groupMapPins(groups[0]).length, 2);
});

const source = fs.readFileSync(new URL('../../apps/web/client/memoir/client.js', import.meta.url), 'utf8');
const extract = name => source.match(new RegExp(`function ${name}\\([^]*?\\n\\}`))[0];

test('background checks prioritise each new mention and ignore superseded corrections', async () => {
  const calls = [];
  let renders = 0;
  const context = vm.createContext({
    state: {project: {id: 'p'}, placeJourney: district},
    profile: () => ({memory_places: [city, district]}), mergePlaces, placeHistoryKey, groupPlaces,
    placeGroupRecords: new Map(), placeGroupRequests: new Map(), placeGroupLatest: new Map(),
    setTimeout: () => {}, render: () => {renders++;},
    api: (url, options) => new Promise(resolve => calls.push({url, body: JSON.parse(options.body), resolve})),
  });
  for (const name of ['publicPlaceFields', 'resolvePlaceGroups', 'workspacePlaceGroups']) vm.runInContext(extract(name), context);
  assert.equal(context.resolvePlaceGroups(district), undefined, 'caller waits for background enrichment');
  assert.equal(calls[0].body.places[0].place, district.place);
  assert.equal(Object.hasOwn(calls[0].body.places[0], 'pictures'), false);
  const correction = {...district, latitude: 40.932};
  context.resolvePlaceGroups(correction);
  calls[1].resolve({places: [{index: 0, city, city_key: groupPlaces([city])[0].key, pin: correction}]});
  await new Promise(resolve => setImmediate(resolve));
  calls[0].resolve({places: [{index: 0, city, pin: district}]});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(renders, 1, 'late correction result triggered a stale render');
  assert.equal(context.placeGroupRecords.get(`p:${placeHistoryKey(district)}`).pin.latitude, correction.latitude);
  assert.equal(groupMapPins(context.workspacePlaceGroups([city, correction])[0])[0].latitude, correction.latitude);
  assert.equal(groupMapPins(context.workspacePlaceGroups([city, district])[0])[0].latitude, district.latitude,
    'cache applies enrichment to different source coordinates');
  context.resolvePlaceGroups(town);
  context.state.project.id = 'other';
  calls[2].resolve({places: [{index: 0, city, pin: town}]});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(renders, 1, 'result for previous project reached current workspace');
});

test('map markup shows city choices and independent pending pin labels', () => {
  const pending = {...town, latitude: undefined, longitude: undefined};
  const groups = groupPlaces([city, district, pending]);
  const context = vm.createContext({
    escapeHtml: value => String(value).replaceAll('"', '&quot;'), translate: key => key,
    translateWith: key => key, currentUiLocale: () => 'zh-CN',
    placeHistoryKey, groupMapFrame, placeMapTarget: place => place,
    placeMapUrl: () => '', lifeStageText: () => '',
  });
  for (const name of ['placeJourneyMarkup', 'groupChoices', 'placeHistoryChoices']) vm.runInContext(extract(name), context);
  assert.equal(context.placeHistoryChoices(context.groupChoices(groups), district), '');
  const markup = context.placeJourneyMarkup(district, 'workspace', groups[0]);
  assert.match(markup, /<h2>承德<\/h2>/);
  assert.match(markup, /data-cesium-pins=/);
  assert.match(markup, /双桥区/);
  assert.match(markup, /大石庙镇/);
  assert.match(markup, /pinUnresolved/);
  assert.doesNotMatch(markup, /data-place-choice=/);
});
