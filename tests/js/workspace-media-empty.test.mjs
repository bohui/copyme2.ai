import { readMemoirClientSource } from './helpers/memoir-source.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';

test('no media workspace renders without a current location', () => {
  const source = readMemoirClientSource();
  const context = vm.createContext({
    state: {placeJourney: null, lifeStage: 'all', photoRequests: new Map()},
    placeWorkspaceSelection: () => null, placeMapTarget: () => null, profile: () => ({memory_places: []}),
    mergePlaces: () => [], workspacePlaceGroups: () => [],
    escapeHtml: String, translate: String, renderablePictureItems: value => value,
    favoritePhotoWall: () => '',
  });
  vm.runInContext(source.match(/function workspaceMediaOverview\([^]*?\n\}/)[0], context);
  assert.equal(context.workspaceMediaOverview(), '');
});

for (const outcome of ['found', 'no-match', 'error']) {
test(`background location lookup ${outcome} only shows the workspace when a map is found`, async () => {
  const source = readMemoirClientSource();
  const journey = {place: '承德', hierarchy: ['Earth', '中国', '河北', '承德'], granularity: 'city'};
  const pending = new Map();
  let calls = 0;
  const visible = [];
  const context = vm.createContext({
    state: {project: {id: 'synthetic'}, placeJourney: journey, lifeStage: 'all', photoRequests: new Map()},
    composingWorkspaceActive: () => false,
    pendingPlaceTargets: pending, resolvedPlaceTargets: new Map(),
    resolvePlaceGroups: () => {},
    mapTarget: () => null, placeHistoryKey: () => 'synthetic-place',
    api: async () => {
      calls++;
      if (outcome === 'error') throw new Error('Synthetic provider authorization rejection');
      return {target: outcome === 'found' ? {place: journey.place, latitude: 40.95, longitude: 117.96} : null};
    },
    loadPlacePictures: () => {},
    render: () => visible.push(context.workspaceHasContent()),
    placeWorkspaceSelection: () => journey, profile: () => ({memory_places: [journey]}),
    mergePlaces: value => value, workspacePlaceGroups: () => [],
    placeHistoryChoices: () => '', groupChoices: () => [], placeJourneyMarkup: () => '<div>map</div>',
    workspacePictureItems: () => [], photoRequestKey: () => 'synthetic-place',
    escapeHtml: String, translate: String, renderablePictureItems: value => value,
    favoritePhotoWall: () => '',
  });
  for (const name of ['placeMapTarget', 'resolvePlaceMap', 'freeRecallFinished', 'workspaceContentAvailable', 'workspaceHasContent', 'workspaceMediaOverview']) {
    vm.runInContext(source.match(new RegExp(`function ${name}\\([^]*?\\n\\}`))[0], context);
  }
  assert.equal(context.workspaceHasContent(), false);
  assert.equal(context.workspaceMediaOverview(), '');
  context.resolvePlaceMap(journey);
  await Promise.all([...pending.values()]);
  assert.equal(context.workspaceHasContent(), outcome === 'found');
  const html = context.workspaceMediaOverview();
  if (outcome === 'found') {
    assert.match(html, /workspace-media-map/);
    assert.match(html, /workspace-media-gallery/);
    assert.equal(visible.at(-1), true, 'successful resolution must open the workspace without an existing map panel');
  } else assert.equal(html, '');
  context.resolvePlaceMap(journey);
  await Promise.all([...pending.values()]);
  assert.equal(calls, 1, 'hidden panels must not cause repeated location lookups');
});
}
