import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../../apps/web/client/memoir/client.js', import.meta.url), 'utf8');

test('life-stage labels do not suppress the automatic photo request', async () => {
  for (const when of ['青年时期', '婴儿时期', 'young adulthood', undefined]) {
    const entry = {place: '承德', hierarchy: ['Earth', '中国', '河北', '承德']};
    const requests = [];
    const saved = [];
    const item = {asset_id: 'crawl4ai-one', image_url: 'https://images.example/one.jpg', allowed_actions: {embed: true}};
    const context = vm.createContext({
      state: {project: {id: 'project'}, placeJourney: entry}, URLSearchParams, workspaceUpdateQueue: Promise.resolve(),
      URL, window: {location: {origin: 'http://localhost'}}, document: {querySelector: () => null},
      PLACE_PHOTO_RESULT_LIMIT: 10,
      profile: () => ({story_focus: {when}, memory_places: [entry]}),
      api: async url => { requests.push(url); return {items: [item], status: 'PARTIAL'}; },
      placeHistoryKey: place => place.place,
      saveProfileUpdates: async updates => saved.push(updates), render: () => {},
    });
    for (const name of ['photoSearchPeriod', 'mergePlacePictures', 'loadPlacePictures']) {
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
});
