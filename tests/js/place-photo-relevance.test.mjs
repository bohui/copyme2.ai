import { readMemoirClientSource } from './helpers/memoir-source.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';

const source = readMemoirClientSource();
const picture = (id, fields = {}) => ({asset_id: id, title: 'Chengde courtyard',
  image_url: `https://images.example/${id}.jpg`, allowed_actions: {embed: true}, ...fields});

function harness(place, extra = {}) {
  const context = vm.createContext({
    URL, window: {location: {origin: 'http://localhost'}},
    profile: () => ({story_focus: {when: '1983年'}}),
    placeHistoryKey: item => item.place, searchedPictures: () => [], ...extra,
  });
  for (const name of ['photoSearchPeriod', 'placePhotoCenter', 'photoMatchesScope', 'mergePlacePictures', 'renderablePictureItems', 'workspacePictureItems']) {
    vm.runInContext(source.match(new RegExp(`function ${name}\\([^]*?\\n\\}`))[0], context);
  }
  return context;
}

test('Wikimedia file redirects and thumbnails merge across source revisions', () => {
  const context = harness();
  const filename = 'Chengde_courtyard.jpg';
  const original = picture('original', {image_url: `https://upload.wikimedia.org/wikipedia/commons/a/ab/${filename}`});
  const redirect = picture('redirect', {image_url: `https://commons.wikimedia.org/wiki/Special:FilePath/${filename}?width=300`});
  const thumbnail = picture('thumbnail', {image_url: `https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/${filename}/120px-${filename}`});
  const thumbHost = picture('thumb-host', {image_url: `https://thumb.wikimedia.org/wikipedia/commons/thumb/a/ab/${filename}/960px-${filename}`});
  assert.equal(context.mergePlacePictures([original], [redirect, thumbnail, thumbHost]).length, 1);
});

test('historical results replace modern fallbacks for the same search', () => {
  const context = harness();
  const scope = {requested_period:'1980s',search_place:'Chengde'};
  const modern = picture('modern', {...scope, date_expression:'2025', search_fallback:'gps_time'});
  const historical = picture('historical', {...scope, date_expression:'1983', search_fallback:'gps'});
  assert.deepEqual(Array.from(context.mergePlacePictures([modern], [historical]), item => item.asset_id), ['historical']);
});

test('saved and grouped galleries hide distant, undated and wrong-period photos', () => {
  const center = {latitude: 40.98, longitude: 117.94};
  const place = {place: 'Chengde', period: '1983年', photo_search_period: '2025', ...center,
    pictures: [picture('stale', {date_expression: '2025', ...center})]};
  const group = {city: place, members: [place, {place: 'Courtyard', pictures: [
    picture('near', {date_expression: '1983', ...center}),
    picture('far', {date_expression: '1983', latitude: 41.3, longitude: 117.94}),
    picture('unknown', {date_expression: '1983'}),
    picture('wrong-period', {date_expression: '2025', ...center}),
  ]}]};
  const context = harness(place);
  assert.deepEqual(Array.from(context.workspacePictureItems(place, group), item => item.asset_id), ['near']);
});

test('period boundaries, uncertain metadata and coordinate validation remain strict', () => {
  const context = harness();
  const center = {latitude: 40.98, longitude: 117.94};
  const entry = {place: 'Chengde', period: '1983年', ...center};
  for (const year of ['1973', '1983', '1993']) {
    assert.ok(context.photoMatchesScope(picture(year, {date_expression: year, ...center}), entry));
  }
  for (const year of ['1972', '1994', 'circa 1983', '1983-02-30', '']) {
    assert.equal(context.photoMatchesScope(picture(year, {date_expression: year, ...center}), entry), false);
  }
  assert.equal(context.photoMatchesScope(picture('upload', {date_expression: '1983', date_basis: 'upload_date', ...center}), entry), false);
  assert.equal(context.photoMatchesScope(picture('invalid', {date_expression: '1983', latitude: '', longitude: ''}), entry), false);
  assert.equal(context.photoSearchPeriod({period: '青年时期'}, {when: '1983年'}), '');
});

test('content fingerprints merge rehosted variants while keeping a different scene', () => {
  const context = harness();
  const items = context.mergePlacePictures([], [
    picture('original', {perceptual_hash: '44cfa6dc2368aa6d'}),
    picture('compressed', {perceptual_hash: '44cfa6dc2368aa6f'}),
    picture('different', {perceptual_hash: 'b3305923dc975592'}),
  ]);
  assert.deepEqual(Array.from(items, item => item.asset_id), ['original', 'different']);
});

test('current photos retain exact normalized date endpoints', () => {
  class FixedDate extends Date {
    constructor(...args) { super(...(args.length ? args : ['2026-10-21T12:00:00Z'])); }
  }
  const context = harness(null, {Date: FixedDate});
  const center = {latitude: 40.98, longitude: 117.94};
  const entry = {place: 'Chengde', ...center};
  for (const [start, end, accepted] of [
    ['2026-06-01', '2026-06-01', true],
    ['2026-06-01', '2026-06-30', true],
    ['2024-10-21', '2026-10-21', true],
    ['2026-10-22', '2026-10-22', false],
    ['2026-10-20', '2026-10-22', false],
    ['2024-10-20', '2026-10-21', false],
    ['2026-06-30', '2026-06-01', false],
    ['2026-02-30', '2026-03-01', false],
  ]) {
    assert.equal(context.photoMatchesScope(picture(start + end, {...center,
      scene_date_range: {start, end, basis: 'source_caption'}, date_expression: 'ignored display text'}), entry),
      accepted, `${start}–${end}`);
  }
});
