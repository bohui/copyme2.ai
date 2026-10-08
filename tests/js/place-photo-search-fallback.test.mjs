import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../../apps/web/client/memoir/client.js', import.meta.url), 'utf8');
const center = {latitude: 40.98, longitude: 117.94};
const entry = {place: 'Chengde', period: '1983年', ...center};
const picture = fields => ({asset_id: 'reference', title: 'Chengde street',
  source_url: 'https://archive.example/photo', image_url: 'https://images.example/photo.jpg',
  date_expression: '1983', requested_period: '1983年', search_place: 'Chengde',
  search_fallback: 'gps', allowed_actions: {embed: true}, ...fields});

function harness() {
  const context = vm.createContext({state: {project: {id:'p'}}, URL, window: {location: {origin: 'http://localhost'}},
    profile: () => ({story_focus: {when: '1983年'}}),
    placeHistoryKey: place => place.place, searchedPictures: () => [],
    escapeHtml: value => String(value), translate: key => key,
    currentUiLocale: () => 'en-AU', formatDateExpression: value => value,
    photoPaginationMarkup: () => '',
  });
  for (const name of ['photoSearchPeriod', 'placePhotoCenter', 'photoMatchesScope',
    'mergePlacePictures', 'renderablePictureItems', 'workspacePictureItems', 'referenceUrl', 'photoMemoryState', 'photoMemoryControls', 'pictureWall']) {
    vm.runInContext(source.match(new RegExp(`function ${name}\\([^]*?\\n\\}`))[0], context);
  }
  return context;
}

test('saved GPS fallbacks remain visible in the workspace and keep the original period', () => {
  const context = harness();
  const saved = {...entry, photo_search_period: '1983年', pictures: [picture()]};
  assert.equal(context.workspacePictureItems(saved).length, 1);
  assert.equal(context.photoMatchesScope(picture({date_expression: '2020'}), entry), false);
  assert.match(context.pictureWall(saved.pictures, saved), /sourceLocationReference/);
});

test('time fallbacks show other capture periods and unknown dates with honest captions', () => {
  const context = harness();
  for (const expression of ['1900', '2020', '']) {
    const item = picture({date_expression: expression, search_fallback: 'gps_time', period_match: 'any_time'});
    assert.ok(context.photoMatchesScope(item, entry));
    assert.match(context.pictureWall([item], entry), /otherPeriodReference/);
    if (!expression) assert.match(context.pictureWall([item], entry), /dateUnknown/);
  }
});

test('fallbacks cannot bypass a changed place, period, future date or publication-date evidence', () => {
  const context = harness();
  for (const fields of [
    {search_place: 'Chengdu'}, {requested_period: '1990s'},
    {date_expression: '2099'}, {date_expression: '1983-02-30'}, {date_basis: 'upload_date'},
  ]) {
    assert.equal(context.photoMatchesScope(picture({search_fallback: 'gps_time', ...fields}), entry), false);
  }
  assert.equal(context.photoMatchesScope(picture({search_fallback: undefined}), entry), false);
});
