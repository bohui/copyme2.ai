import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../../apps/web/client/memoir/client.js', import.meta.url), 'utf8');
const extract = name => source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0];

function renderedWorkspace(overrides = {}, dependencies = {}) {
  const app = {innerHTML: ''};
  const state = {
    project: {id: 'project'}, chat: [{role: 'user', text: 'I grew up in Chengde.'}],
    chapters: [], people: [], timeline: [], familyFeaturesEnabled: true,
    compositionStage: 0, workspaceUnlocked: false, workspaceCollapsed: false,
    workspaceTab: 'memoir', placeJourney: {place: 'Chengde'}, privateDraft: null,
    ...overrides,
  };
  const context = vm.createContext({ MEMOIR_ROUTES: { home: '/memoir' },
    state, $: selector => selector === '#app' ? app : null, document: {},
    workspaceVisibility: {projectId: null, stable: false},
    placeWorkspaceSelection: () => state.placeJourney,
    placeMapTarget: place => Number.isFinite(place?.latitude) && Number.isFinite(place?.longitude) ? place : null,
    workspaceMediaOverview: () => '<section class="workspace-media-overview">map and photo gallery</section>',
    lifeStageNavigator: () => '<section class="life-stage-navigator">life stages</section>',
    privateDraftPreview: () => '', familyWorkspace: () => 'family', timelineWorkspace: () => 'timeline',
    memoirWorkspace: () => 'memoir', escapeHtml: String, translate: String, translateWith: String,
    isFreshAnonymousSession: () => true, profileMenu: () => '', renderMessage: () => '',
    placeJourneySurface: () => '', recallPackagePrompt: () => '', chatComposer: () => '',
    bindViewActions() {}, bindProfileMenu() {}, disposeCesiumPlaceJourney() {}, initCesiumPlaceJourney() {},
    initFamilyVisualizations() {}, bindPhotoPagination() {}, bindPhotoMemoryActions() {}, resizeChatInput() {}, persistChatHistory() {},
    authReminder: {mount() {}}, render() {},
    mapPhotoAlbums: {sync() {}},
    ...dependencies,
  });
  for (const name of ['freeRecallFinished', 'composingWorkspaceActive', 'workspaceTabs', 'activeWorkspaceTab',
    'workspaceContentAvailable', 'workspaceHasContent', 'workspaceIsVisible', 'workspaceDetail', 'renderStory']) {
    vm.runInContext(extract(name), context);
  }
  context.renderStory();
  return app.innerHTML;
}

test('a first location trigger opens the place/photo workspace before its map is ready', () => {
  const html = renderedWorkspace({privateDraft: {updating: true}});
  assert.match(html, /story-shell context-visible/);
  assert.match(html, /id="workspace-detail"/);
  assert.match(html, /workspace-media-overview/);
  assert.match(html, /life-stage-navigator/);
});

test('saved or failed drafts do not open an otherwise unavailable workspace', () => {
  for (const privateDraft of [null, {preview: {title: 'Draft', text: 'Saved memory'}}, {error: 'Draft failed'}]) {
    const html = renderedWorkspace({privateDraft, placeJourney: null});
    assert.match(html, /story-shell conversation-only/);
    assert.doesNotMatch(html, /id="workspace-detail"|life-stage-navigator/);
  }
});

test('early family and timeline records do not open a workspace without a map', () => {
  const html = renderedWorkspace({placeJourney: null, people: [{id: 'author', name: 'Author'}],
    timeline: [{id: 'birth', title: 'Born in Chengde'}]});
  assert.match(html, /story-shell conversation-only/);
  assert.doesNotMatch(html, /id="workspace-detail"|life-stage-navigator/);
});

test('an unready selection keeps the workspace available without substituting a different map', () => {
  const html = renderedWorkspace({placeJourney: {place: 'Chengde', latitude: 40.95, longitude: 117.96}}, {
    placeWorkspaceSelection: () => null,
    workspaceMediaOverview: () => '',
  });
  assert.match(html, /story-shell context-visible/);
  assert.match(html, /id="workspace-detail"/);
  assert.doesNotMatch(html, /life-stage-navigator/);
});

test('a map gap retains the place/photo panels alongside the life-stage strip', () => {
  const html = renderedWorkspace({}, {
    workspaceVisibility: {projectId: 'project', stable: true, pending: null, timer: null},
    setTimeout: () => 1,
  });
  assert.match(html, /workspace-media-overview/);
  assert.match(html, /life-stage-navigator/);
});

test('the fifth-round private draft keeps the place/photo view until composition unlocks', () => {
  const html = renderedWorkspace({privateDraft: {covered_round: 5, preview: {title: 'Draft', text: 'Memory'}}});
  assert.match(html, /story-shell context-visible/);
  assert.match(html, /workspace-media-overview/);
  assert.doesNotMatch(html, /data-workspace-tab/);
});

test('a ready map opens the place/photo workspace and its life-stage strip', () => {
  const html = renderedWorkspace({placeJourney: {place: 'Chengde', latitude: 40.95, longitude: 117.96}});
  assert.match(html, /story-shell context-visible/);
  assert.match(html, /workspace-media-overview/);
  assert.match(html, /life-stage-navigator/);
});

test('unlocked composition opens its tabs without a map or draft', () => {
  const html = renderedWorkspace({compositionStage: 3, placeJourney: null});
  assert.match(html, /story-shell workspace-visible/);
  for (const tab of ['family', 'timeline', 'memoir']) assert.match(html, new RegExp(`data-workspace-tab="${tab}"`));
  assert.doesNotMatch(html, /workspace-media-overview|life-stage-navigator/);
});

test('finishing free recall opens Chapters even without a map, payment or composition', () => {
  const html = renderedWorkspace({placeJourney:null, familyFeaturesEnabled:false,
    recallStatus:{rounds_completed:20, free_rounds:20, payment_required:true}});
  assert.match(html, /story-shell workspace-visible/);
  assert.match(html, /data-workspace-tab="memoir"/);
  assert.doesNotMatch(html, /data-workspace-tab="family"|data-workspace-tab="timeline"|workspace-media-overview/);
});

test('collapsing a ready workspace also hides the life-stage strip', () => {
  const html = renderedWorkspace({workspaceCollapsed: true,
    placeJourney: {place: 'Chengde', latitude: 40.95, longitude: 117.96}});
  assert.match(html, /workspace-detail is-collapsed/);
  assert.doesNotMatch(html, /workspace-media-overview|life-stage-navigator/);
});

test('keeps an activated place workspace visible after the selected map becomes unavailable', () => {
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
    workspaceVisibility: {projectId: null, stable: false},
    WORKSPACE_VISIBILITY_DEBOUNCE_MS: 180,
    workspaceTabs: () => [],
    composingWorkspaceActive: () => false,
    freeRecallFinished: () => false,
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
  for (const callback of [...timers.values()]) callback();
  assert.equal(context.workspaceIsVisible(), true, 'an activated workspace must not disappear after map resolution changes');

  target = {place: 'Chengde', latitude: 40.95, longitude: 117.96};
  assert.equal(context.workspaceIsVisible(), true);

  target = null;
  assert.equal(context.workspaceIsVisible(), true);
  for (const callback of [...timers.values()]) callback();
  assert.equal(context.workspaceIsVisible(), true);
  assert.equal(rendered, 0);

  state.placeJourney = null;
  assert.equal(context.workspaceIsVisible(), true);
  state.workspaceCollapsed = true;
  assert.equal(context.workspaceIsVisible(), false);
  assert.equal(context.workspaceHasContent(), true);
  state.workspaceCollapsed = false;
  assert.equal(context.workspaceIsVisible(), true);

  state.project = {id: 'another-project'};
  assert.equal(context.workspaceIsVisible(), false, 'activation belongs to the current project');
});
