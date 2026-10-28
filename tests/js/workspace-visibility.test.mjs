import { readMemoirClientSource } from './helpers/memoir-source.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {applyDerivedWorkspace} from '../../apps/web/client/memoir/derived-workspace.mjs';

const source = readMemoirClientSource();
const extract = name => source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0];

function workspaceHarness(overrides = {}, dependencies = {}) {
  const app = {innerHTML: ''};
  const state = {
    project: {id: 'project'}, chat: [{role: 'user', text: 'I grew up in Chengde.'}],
    chapters: [], people: [], timeline: [], familyFeaturesEnabled: true,
    compositionStage: 0, workspaceUnlocked: false, workspaceCollapsed: false,
    workspaceTab: 'memoir', placeJourney: {place: 'Chengde', latitude: 40.95, longitude: 117.96}, privateDraft: null,
    ...overrides,
  };
  const context = vm.createContext({ MEMOIR_ROUTES: { home: '/memoir' },
    state, $: selector => selector === '#app' ? app : null, document: {},
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
    mapPhotoAlbums: {sync() {}}, mapMemoryEvents: {sync() {}},
    ...dependencies,
  });
  for (const name of ['freeRecallFinished', 'composingWorkspaceActive', 'workspaceTabs', 'activeWorkspaceTab',
    'workspaceContentAvailable', 'workspaceHasContent', 'workspaceIsVisible', 'workspaceDetail', 'renderStory']) {
    vm.runInContext(extract(name), context);
  }
  return {state, context, app};
}

function renderedWorkspace(overrides = {}, dependencies = {}) {
  const {context, app} = workspaceHarness(overrides, dependencies);
  context.renderStory();
  return app.innerHTML;
}

test('an unresolved location stays in the conversation while its lookup is pending', () => {
  for (const preview of [false, true]) {
    const html = renderedWorkspace({placeJourney: {place: '大石庙', preview}, privateDraft: {updating: true}});
    assert.match(html, /story-shell conversation-only/);
    assert.doesNotMatch(html, /id="workspace-detail"|workspace-media-overview|life-stage-navigator/);
  }
});

test('saved or failed drafts do not open an otherwise unavailable workspace', () => {
  for (const privateDraft of [null, {preview: {title: 'Draft', text: 'Saved memory'}}, {error: 'Draft failed'}]) {
    const html = renderedWorkspace({privateDraft, placeJourney: null});
    assert.match(html, /story-shell conversation-only/);
    assert.doesNotMatch(html, /id="workspace-detail"|life-stage-navigator/);
  }
});

test('thinking steps require an enabled flag and a local browser', async () => {
  for (const hostname of ['localhost', '127.0.0.1', '[::1]', 'memoir.example', 'localhost.example', '192.168.1.10']) {
    for (const flag of [undefined, false, true, 'true']) {
      const state = {showThinkingSteps:true};
      const context = vm.createContext({state, window:{location:{hostname}}, memoirApiPath:String,
        fetch:async () => ({json:async () => ({auth_mode:'test', show_thinking_steps:flag})})});
      vm.runInContext(extract('loadSupabaseConfig'), context);
      await context.loadSupabaseConfig();
      assert.equal(state.showThinkingSteps,
        flag === true && ['localhost', '127.0.0.1', '[::1]'].includes(hostname), `${hostname}: ${flag}`);
    }
  }
});

test('live draft previews require only their own flag and a local browser', async () => {
  for (const hostname of ['localhost', '127.0.0.1', '[::1]', 'memoir.example']) {
    for (const thinking of [false, true]) for (const drafts of [false, true]) {
      const state = {};
      const context = vm.createContext({state, window:{location:{hostname}}, memoirApiPath:String,
        fetch:async()=>({json:async()=>({auth_mode:'test',show_thinking_steps:thinking,show_draft_updates:drafts})})});
      vm.runInContext(extract('loadSupabaseConfig'), context);
      await context.loadSupabaseConfig();
      assert.equal(state.showDraftUpdates, drafts && hostname !== 'memoir.example');
    }
  }
});

test('draft controls never appear beneath the message input, including with local debugging enabled', () => {
  for (const showThinkingSteps of [false, true]) for (const showDraftUpdates of [false,true]) {
    for (const overrides of [{placeJourney:null}, {workspaceCollapsed:true}]) {
      const html = renderedWorkspace({...overrides, showThinkingSteps, showDraftUpdates,
        privateDraft:{error:'MEMOIR_UNAVAILABLE'}}, {
        chatComposer:() => '<form id="chat-form"><textarea id="chat-input"></textarea></form>',
        privateDraftPreview:() => '<section class="private-draft-status">Draft language and retry</section>',
      });
      const conversation = html.match(/<main\b[^]*?<\/main>/)[0];
      assert.match(conversation, /id="chat-input"/);
      assert.doesNotMatch(conversation, /private-draft-status|Draft language and retry/);
    }
  }
});

test('local draft debugging does not add a status card to the place/photo workspace', () => {
  const html = renderedWorkspace({showThinkingSteps:true, showDraftUpdates:true, privateDraft:{error:'MEMOIR_UNAVAILABLE'}}, {
    privateDraftPreview:() => '<section class="private-draft-status">Draft language and retry</section>',
  });
  assert.doesNotMatch(html.match(/<main\b[^]*?<\/main>/)[0], /private-draft-status/);
  assert.doesNotMatch(html, /private-draft-status|Draft language and retry/);
});

test('early family and timeline records do not open a workspace without a map', () => {
  const html = renderedWorkspace({placeJourney: null, people: [{id: 'author', name: 'Author'}],
    timeline: [{id: 'birth', title: 'Born in Chengde'}]});
  assert.match(html, /story-shell conversation-only/);
  assert.doesNotMatch(html, /id="workspace-detail"|life-stage-navigator/);
});

test('an unresolved selection hides the workspace without substituting a different map', () => {
  const html = renderedWorkspace({placeJourney: {place: 'Chengde', latitude: 40.95, longitude: 117.96}}, {
    placeWorkspaceSelection: () => null,
    workspaceMediaOverview: () => '',
  });
  assert.match(html, /story-shell conversation-only/);
  assert.doesNotMatch(html, /id="workspace-detail"|workspace-media-overview|life-stage-navigator/);
});

test('a missing map target hides the place/photo panels and life-stage strip', () => {
  const html = renderedWorkspace({}, {
    placeMapTarget: () => null,
  });
  assert.match(html, /story-shell conversation-only/);
  assert.doesNotMatch(html, /id="workspace-detail"|workspace-media-overview|life-stage-navigator/);
});

test('the fifth-round private draft keeps the place/photo view until composition unlocks', () => {
  const html = renderedWorkspace({privateDraft: {covered_round: 5, preview: {title: 'Draft', text: 'Memory'}}});
  assert.match(html, /story-shell context-visible/);
  assert.match(html, /workspace-media-overview/);
  assert.doesNotMatch(html, /data-workspace-tab/);
});

test('a ready map opens the place/photo workspace and its life-stage strip', () => {
  const html = renderedWorkspace({placeJourney: {place: 'Chengde', latitude: 40.95, longitude: 117.96}}, {
    isFreshAnonymousSession: () => false,
  });
  assert.match(html, /story-shell context-visible/);
  assert.match(html, /workspace-media-overview/);
  assert.match(html, /life-stage-navigator/);
  assert.match(html, /data-action="toggle-chat-history"/);
  assert.doesNotMatch(html, /data-news-enable|data-news-disable/);
});

test('unlocked composition opens its tabs without a map or draft', () => {
  const html = renderedWorkspace({compositionStage: 3, placeJourney: null});
  assert.match(html, /story-shell workspace-visible/);
  for (const tab of ['family', 'timeline', 'memoir']) assert.match(html, new RegExp(`data-workspace-tab="${tab}"`));
  assert.doesNotMatch(html, /workspace-media-overview/);
  assert.match(html, /life-stage-navigator/);
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

test('an activated workspace survives a later unresolved location and respects collapse and project scope', () => {
  let target = {place: 'Chengde', latitude: 40.95, longitude: 117.96};
  const state = {
    project: {id: 'project'},
    workspaceCollapsed: false,
    workspaceTab: 'chapters',
    placeJourney: {place: 'Chengde'},
    privateDraft: null,
  };
  const context = vm.createContext({
    state,
    composingWorkspaceActive: () => false,
    freeRecallFinished: () => false,
    placeWorkspaceSelection: () => state.placeJourney,
    placeMapTarget: place => place ? target : null,
  });
  for (const name of ['workspaceContentAvailable', 'workspaceHasContent', 'workspaceIsVisible']) {
    vm.runInContext(extract(name), context);
  }

  assert.equal(context.workspaceIsVisible(), true);
  target = null;
  assert.equal(context.workspaceIsVisible(), true, 'a later unresolved location must not close the workspace');
  assert.equal(context.workspaceHasContent(), true);

  target = {place: 'Chengde', latitude: 40.95, longitude: 117.96};
  assert.equal(context.workspaceIsVisible(), true);

  state.workspaceCollapsed = true;
  assert.equal(context.workspaceIsVisible(), false);
  assert.equal(context.workspaceHasContent(), true);
  state.workspaceCollapsed = false;
  assert.equal(context.workspaceIsVisible(), true);

  state.project = {id: 'another-project'};
  state.placeJourney = null;
  assert.equal(context.workspaceIsVisible(), false, 'a past map must not activate a new empty project');
});

for (const policyEpoch of [1, 2]) test(`an activated workspace stays rendered after an empty place snapshot at policy epoch ${policyEpoch}`, () => {
  const journey = {place:'Chengde', hierarchy:['Earth', 'China', 'Chengde'], status:'active',
    latitude:40.95, longitude:117.96};
  const {state, context, app} = workspaceHarness({
    project:{id:'project', profile:{memory_places:[journey]}}, placeJourney:journey,
    placeWorkspaceMap:{projectId:'project', key:'saved-map'},
  }, {workspaceMediaOverview:() => ''});
  context.renderStory();
  assert.match(app.innerHTML, /story-shell context-visible/);

  assert.equal(applyDerivedWorkspace(state, {project_id:'project', source_revision:2,
    policy_epoch:policyEpoch, authoritative:true, places:[]}), true);
  context.renderStory();
  assert.match(app.innerHTML, /story-shell context-visible/);
  assert.match(app.innerHTML, /id="workspace-detail"/);
  assert.doesNotMatch(app.innerHTML, /conversation-only|workspace-collapsed/);
  assert.equal(state.placeJourney, null);
  assert.equal(state.placeWorkspaceMap, null);
  assert.deepEqual(state.project.profile.memory_places, []);

  state.workspaceCollapsed = true;
  context.renderStory();
  assert.match(app.innerHTML, /workspace-detail is-collapsed/);
  state.workspaceCollapsed = false;
  context.renderStory();
  assert.match(app.innerHTML, /story-shell context-visible/);

  state.project = {id:'another-project', profile:{}};
  context.renderStory();
  assert.match(app.innerHTML, /story-shell conversation-only/);
  assert.doesNotMatch(app.innerHTML, /id="workspace-detail"/);
});
