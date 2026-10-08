import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

test('a retained workspace renders empty media without a current location', () => {
  const source = fs.readFileSync(new URL('../../apps/web/client/memoir/client.js', import.meta.url), 'utf8');
  const context = vm.createContext({
    state: {placeJourney: null, lifeStage: 'all', photoRequests: new Map()},
    placeWorkspaceSelection: () => null, profile: () => ({memory_places: []}),
    mergePlaces: () => [], workspacePlaceGroups: () => [],
    escapeHtml: String, translate: String, renderablePictureItems: value => value,
    favoritePhotoWall: () => '',
  });
  vm.runInContext(source.match(/function workspaceMediaOverview\([^]*?\n\}/)[0], context);
  const html = context.workspaceMediaOverview();
  assert.match(html, /workspace-media-map/);
  assert.match(html, /workspace-media-gallery/);
  assert.match(html, /placesEmpty/);
});

test('provider rejection retains the activated workspace and unresolved media panes', async () => {
  const source = fs.readFileSync(new URL('../../apps/web/client/memoir/client.js', import.meta.url), 'utf8');
  const journey = {place: '承德', hierarchy: ['Earth', '中国', '河北', '承德'], granularity: 'city'};
  const pending = new Map();
  const context = vm.createContext({
    state: {project: {id: 'synthetic'}, placeJourney: journey, lifeStage: 'all', photoRequests: new Map()},
    workspaceVisibility: {projectId: 'synthetic', stable: true}, composingWorkspaceActive: () => false,
    pendingPlaceTargets: pending, resolvedPlaceTargets: new Map(),
    resolvePlaceGroups: () => {},
    mapTarget: () => null, placeHistoryKey: () => 'synthetic-place',
    api: () => Promise.reject(new Error('Synthetic provider authorization rejection')),
    placeWorkspaceSelection: () => journey, profile: () => ({memory_places: [journey]}),
    mergePlaces: value => value, workspacePlaceGroups: () => [],
    placeHistoryChoices: () => '', groupChoices: () => [], placeJourneyMarkup: () => '',
    workspacePictureItems: () => [], photoRequestKey: () => 'synthetic-place',
    escapeHtml: String, translate: String, renderablePictureItems: value => value,
    favoritePhotoWall: () => '',
  });
  for (const name of ['resolvePlaceMap', 'workspaceContentAvailable', 'workspaceHasContent', 'workspaceMediaOverview']) {
    vm.runInContext(source.match(new RegExp(`function ${name}\\([^]*?\\n\\}`))[0], context);
  }
  context.resolvePlaceMap(journey);
  await Promise.all([...pending.values()]);
  assert.equal(context.workspaceHasContent(), true);
  const html = context.workspaceMediaOverview();
  assert.match(html, /pinUnresolved/);
  assert.match(html, /workspace-media-gallery/);
});
