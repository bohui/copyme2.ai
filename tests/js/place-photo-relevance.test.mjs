import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../../apps/web/client/memoir/client.js', import.meta.url), 'utf8');
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
  assert.equal(context.mergePlacePictures([original], [redirect, thumbnail]).length, 1);
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
  assert.equal(context.photoSearchPeriod({period: '青年时期'}, {when: '1983年'}), '1983年');
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
