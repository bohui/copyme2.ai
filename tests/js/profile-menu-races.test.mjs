import { readMemoirClientSource } from './helpers/memoir-source.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';

const source = readMemoirClientSource();
const extract = name => source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0];

function harness() {
  const document = {activeElement: null}, events = new Map();
  let html = '', menu, opened = 0;
  function makeMenu(markup) {
    const listeners = new Map();
    const trigger = {dataset: {}, expanded: markup.match(/data-profile-trigger[^>]*aria-expanded="([^"]+)"/)?.[1],
      getAttribute: name => name === 'aria-expanded' ? trigger.expanded : null,
      hasAttribute: name => name === 'data-profile-trigger',
      setAttribute: (name, value) => {assert.equal(name, 'aria-expanded'); trigger.expanded = value;},
      addEventListener: (_type, callback) => listeners.set('trigger', callback),
      focus: () => {document.activeElement = trigger;}, click: () => listeners.get('trigger')()};
    const dropdown = {hidden: markup.includes('id="profile-menu-content" role="menu" hidden')};
    const login = {dataset: {profileAction: 'login'},
      addEventListener: (_type, callback) => listeners.set('login', callback),
      focus: () => {document.activeElement = login;}};
    return {trigger, dropdown, login, listeners, classList: {add() {}, remove() {}},
      contains: node => node === trigger || node === login,
      querySelector: selector => selector === '[data-profile-trigger]' ? trigger : selector === '.profile-dropdown' ? dropdown
        : selector === "[data-profile-action='login']" && markup.includes('data-profile-action="login"') ? login : null};
  }
  const app = {};
  Object.defineProperty(app, 'innerHTML', {get: () => html, set: value => {
    if (menu?.contains(document.activeElement)) document.activeElement = null;
    html = value; menu = makeMenu(value);
  }});
  const state = {project: {id: 'a', profile: {}}, supabase: {user: {id: 'owner', is_anonymous: true}, accessToken: 'session'},
    conversationPhase: {ensure() {}}, chat: [], chapters: [], navigationGeneration: 1};
  const context = vm.createContext({state, document, AbortController, setTimeout, clearTimeout, MEMOIR_ROUTES: {home: '/memoir'},
    $: selector => selector === '#app' ? app : selector === '[data-profile-menu]' ? menu
      : selector === '[data-profile-trigger]' ? menu?.trigger : selector === '[data-profile-action="login"]' ? menu?.login : null,
    window: {addEventListener: (name, callback) => events.set(name, callback)},
    escapeHtml: String, translate: String, translateWith: String, cleanAssistantText: String,
    composingWorkspaceActive: () => false, freeRecallFinished: () => false,
    workspaceIsVisible: () => false, workspaceHasContent: () => false, isFreshAnonymousSession: () => false,
    renderMessage: message => `<p>${message.text}</p>`, placeJourneySurface: () => '', recallPackagePrompt: () => '',
    chatComposer: () => '', privateDraftPreview: () => '', activeWorkspaceTab() {}, bindViewActions() {},
    disposeCesiumPlaceJourney() {}, initCesiumPlaceJourney() {}, initFamilyVisualizations() {},
    bindPhotoPagination() {}, bindPhotoMemoryActions() {}, resizeChatInput() {}, persistChatHistory() {},
    authReminder: {mount() {}, open() {opened++;}}, mapPhotoAlbums: {sync() {}}, mapMemoryEvents: {sync() {}},
    currentUiLocale: () => 'en-AU', memoirApiPath: path => path, privateDraftTimer: null,
    storyApi: async path => {assert.match(path, /^\/v1\/story\/(private-draft|readiness)\?project_id=a/); return {};},
    nextAssistantMessageId: () => 'opening', ASSISTANT_STREAM_CHUNK_SIZE: 5,
    waitForAssistantStream: async () => {}, updateStreamingAssistantMessage() {},
  });
  for (const name of ['captureProjectScope', 'isCurrentProjectScope', 'invalidateProjectNavigation', 'profile', 'profileDetails',
    'profileMenu', 'closeProfileMenu', 'bindProfileMenu', 'refreshPrivateDraft', 'refreshStageReadiness', 'streamAssistantMessage', 'renderStory']) {
    vm.runInContext(extract(name), context);
  }
  for (const name of ['click', 'keydown']) {
    vm.runInContext(source.match(new RegExp(`window.addEventListener\\("${name}", \\(event\\) => \\{[^]*?\\n\\}\\);`))[0], context);
  }
  context.render = () => context.renderStory();
  context.render();
  return {state, context, document, events, menu: () => menu, opened: () => opened,
    open() {menu.trigger.focus(); menu.trigger.click();}};
}

for (const paint of ['refreshPrivateDraft', 'refreshStageReadiness', 'streamAssistantMessage']) {
  test(`same-project ${paint} preserves the open menu and keyboard focus`, async () => {
    const h = harness(); h.open(); h.menu().login.focus();
    assert.equal(h.menu().dropdown.hidden, false);
    await h.context[paint]('Opening copy');
    assert.equal(h.menu().dropdown.hidden, false);
    assert.equal(h.menu().trigger.expanded, 'true');
    assert.equal(h.document.activeElement, h.menu().login);
    h.menu().listeners.get('login')();
    assert.equal(h.opened(), 1);
    assert.equal(h.menu().dropdown.hidden, true);
  });
}

test('same-scope repaint preserves trigger focus without moving focus from the composer', () => {
  const h = harness(); h.open(); h.context.render();
  assert.equal(h.document.activeElement, h.menu().trigger);
  const composer = {dataset: {}}; h.document.activeElement = composer;
  h.context.render();
  assert.equal(h.document.activeElement, composer);
});

for (const close of ['explicit', 'escape', 'outside']) test(`${close} close is not reversed by a later paint`, () => {
  const h = harness(); h.open();
  if (close === 'explicit') h.context.closeProfileMenu();
  else if (close === 'escape') h.events.get('keydown')({key: 'Escape'});
  else h.events.get('click')({target: {}});
  h.context.render();
  assert.equal(h.menu().dropdown.hidden, true);
  assert.equal(h.menu().trigger.expanded, 'false');
});

for (const transition of ['project', 'owner', 'navigation', 'logout']) test(`${transition} transition never resurrects another scope's menu`, () => {
  const h = harness(); h.open(); h.menu().login.focus();
  if (transition === 'project') h.state.project = {id: 'b', profile: {}};
  else if (transition === 'owner') h.state.supabase.user = {id: 'other', is_anonymous: false};
  else if (transition === 'navigation') h.context.invalidateProjectNavigation();
  else {h.context.closeProfileMenu(); h.state.supabase = null;}
  h.context.render();
  assert.equal(h.menu().dropdown.hidden, true);
  assert.notEqual(h.document.activeElement, h.menu().login);
});
