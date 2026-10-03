import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../../apps/web/client/memoir/client.js', import.meta.url), 'utf8');
const extract = name => source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0];

test('keeps the first place workspace visible through a transient map-target gap', () => {
  let target = {place: 'Chengde', latitude: 40.95, longitude: 117.96};
  let rendered = 0;
  let nextTimerId = 0;
  const timers = new Map();
  const state = {
    project: {id: 'project'},
    workspaceCollapsed: false,
    workspaceTab: 'chapters',
    placeJourney: {place: 'Chengde'},
    privateDraft: null,
  };
  const context = vm.createContext({
    state,
    workspaceVisibility: {projectId: null, stable: false, pending: null, timer: null},
    WORKSPACE_VISIBILITY_DEBOUNCE_MS: 180,
    workspaceTabs: () => [],
    placeWorkspaceSelection: () => state.placeJourney,
    placeMapTarget: () => target,
    render: () => { rendered += 1; },
    setTimeout: (callback) => {
      const id = ++nextTimerId;
      timers.set(id, callback);
      return id;
    },
    clearTimeout: id => timers.delete(id),
  });
  for (const name of ['workspaceContentAvailable', 'workspaceHasContent', 'workspaceIsVisible']) {
    vm.runInContext(extract(name), context);
  }

  assert.equal(context.workspaceIsVisible(), true);
  target = null;
  assert.equal(context.workspaceIsVisible(), true);
  assert.equal(timers.size, 1);

  target = {place: 'Chengde', latitude: 40.95, longitude: 117.96};
  assert.equal(context.workspaceIsVisible(), true);
  assert.equal(timers.size, 0);
  assert.equal(rendered, 0);

  target = null;
  assert.equal(context.workspaceIsVisible(), true);
  assert.equal(timers.size, 1);

  timers.values().next().value();
  assert.equal(rendered, 1);
  assert.equal(context.workspaceIsVisible(), false);
});
