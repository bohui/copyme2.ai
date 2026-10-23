import { readMemoirClientSource } from './helpers/memoir-source.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {TextDecoder, TextEncoder} from 'node:util';

const source = readMemoirClientSource();
const extract = name => source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))?.[0];
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return {promise, resolve, reject}; };
const tick = () => new Promise(resolve => setImmediate(resolve));
function load(context, ...names) {
  if (names.some(name => ['refreshProject', 'startMemoirStory'].includes(name))) {
    names = ['profile', 'preserveConversationLocale', 'mergePrivateProfile', 'hydrateConversationProfile', ...names];
  }
  for (const name of ['captureProjectScope', 'isCurrentProjectScope', 'invalidateProjectNavigation', ...names]) {
    if (extract(name)) vm.runInContext(extract(name), context);
  }
}

test('an older failed recovery cannot clear the newer Back/Forward project or history', async () => {
  const a = deferred();
  let path = '/memoir/interview/a';
  const state = {supabase: {user: {id: 'guest'}}, chat: [], navigationGeneration: 0};
  const context = vm.createContext({state, FALLBACK_STORY_PLANS: [],
    MEMOIR_ROUTES: {home: '/memoir', start: '/memoir/start', interview: '/memoir/interview'},
    localStorage: {removeItem() {}}, sessionStorage: {getItem: () => null},
    currentPath: () => path, window: {history: {replaceState() {}}}, $: () => ({innerHTML: ''}),
    ensureAuth: async () => {}, guestTransfer: {complete: async () => false},
    syncProfileUiLocale: async () => {}, savedProjectId: () => 'a',
    refreshProject: async () => { if (state.project.id === 'a') await a.promise; },
    restoreChatHistory: id => [{role: 'user', text: `${id} private history`}], rememberProject() {},
    hydrateAccountHistory: async () => {}, hydratePlaceJourney: async () => {},
    refreshFamilyEntitlement: async () => {}, profileHasContext: () => true,
    render() {}, renderLanding() {}, startCodexConversation: async () => {},
    persistChatHistory() {}, stopVoiceMode() {}, cancelDictation() {}, toast() {}, translate: x => x,
  });
  load(context, 'boot');
  const older = context.boot();
  await tick();
  path = '/memoir/interview/b';
  await context.boot();
  assert.equal(state.project.id, 'b');
  a.reject(new Error('Older recovery failed'));
  await older;
  assert.equal(state.project?.id, 'b');
  assert.equal(state.chat[0]?.text, 'b private history');
  assert.equal(state.projectRecoveryBlocked, null);
});

test('a stale successful recovery cannot overwrite a later visit to the same project', async () => {
  const response = deferred();
  const state = {project: {id: 'a', profile: {}}, supabase: {user: {id: 'guest'}}, navigationGeneration: 1};
  const context = vm.createContext({state, api: () => response.promise,
    preserveConversationLocale: p => p, refreshStageReadiness() {}, refreshPrivateDraft() {}});
  load(context, 'refreshProject');
  const older = context.refreshProject();
  state.navigationGeneration += 2; // Back to B, then Forward to a fresh A visit.
  state.project = {id: 'a', profile: {name: 'New visit'}};
  response.resolve({id: 'a', profile: {name: 'Obsolete response'}});
  await older;
  assert.equal(state.project.profile.name, 'New visit');
});

for (const ending of ['final', 'error', 'workspace-tail']) test(`late A delta and ${ending} cannot enter B or a later A visit`, async () => {
  const reply = deferred();
  let delta, event;
  const caches = new Map();
  const state = {project: {id: 'a'}, projectPrincipalId: 'guest',
    supabase: {user: {id: 'guest'}, accessToken: 'session'}, navigationGeneration: 0,
    chat: [{role: 'user', text: 'A accepted memory'}], placeJourney: null};
  const context = vm.createContext({state, AbortController,
    appliedWorkspaceSequences: new Map(), workspaceUpdateQueue: Promise.resolve(),
    CHAT_HISTORY_STORAGE_PREFIX: 'chat:', localStorage: {getItem: k => caches.get(k), setItem: (k, v) => caches.set(k, v)},
    sessionStorage: {getItem: () => null, setItem() {}}, cleanAssistantText: x => x,
    conversationLanguage: () => 'en-AU', simulatedLoopTrace: () => [], nextAssistantMessageId: () => 'a-reply',
    render: () => context.persistChatHistory(), updateStreamingAssistantMessage: () => context.persistChatHistory(),
    streamAgentTurn: (_text, onDelta, onEvent) => { delta = onDelta; event = onEvent; return reply.promise; },
    stopVoiceMode() {}, cancelDictation() {}, toast: () => assert.fail('stale errors must remain detached'),
    saveProfileUpdates: () => assert.fail('stale workspace must not save'), refreshPrivateDraft: () => assert.fail('stale draft must not refresh'),
  });
  load(context, 'chatHistoryStorageKey', 'readBrowserValues', 'readBrowserValue', 'mergeChatHistoryCopies',
    'saveBrowserValue', 'persistChatHistory', 'currentWorkspaceMemoryFocus', 'workspaceTurnFocus', 'markWorkspaceFocusStarted', 'agentTurn');
  const pending = context.agentTurn('A accepted memory');
  if (ending === 'workspace-tail') {
    await delta('A accepted partial');
    reply.resolve({reply: 'A accepted partial', conversation_saved: true});
    // This ready reply may start its own draft refresh while still on A.
    context.refreshPrivateDraft = () => {};
    context.refreshStageReadiness = () => {};
    await pending;
  }
  context.invalidateProjectNavigation();
  state.project = {id: 'b'};
  state.chat = [{role: 'user', text: 'B private memory'}];
  context.persistChatHistory();
  const before = caches.get('chat:guest:b');
  await delta('A late delta');
  await event({type: 'progress', data: {id: 'a-progress', status: 'running'}});
  await event({type: 'workspace_update', data: {project_id: 'a', composition_stage: 3, task_errors: ['late error']}});
  await event({type: 'workspace_error', message: 'A late error'});
  await context.workspaceUpdateQueue;
  assert.equal(caches.get('chat:guest:b'), before);
  assert.deepEqual(state.chat.map(m => m.text), ['B private memory']);
  state.project = {id: 'a'};
  state.chat = [{role: 'user', text: 'A later visit'}];
  await delta('A obsolete delta after Forward');
  if (ending === 'error') reply.reject(new Error('A transport error'));
  else reply.resolve({reply: 'A obsolete complete reply', recall_status: {payment_required: true}, conversation_saved: true});
  if (ending !== 'workspace-tail') {
    const result = await pending;
    assert.equal(result.detached, true);
  }
  assert.deepEqual(state.chat.map(m => m.text), ['A later visit']);
  assert.equal(state.recallStatus, undefined);
  assert.match(caches.get('chat:guest:a'), /A accepted memory/);
  assert.doesNotMatch(caches.get('chat:guest:a'), /A late delta|A obsolete|B private/);
});

test('a late unauthorized response cannot clear another principals token', async () => {
  const response = deferred();
  const state = {project: {id: 'a'}, supabase: {user: {id: 'guest'}, accessToken: 'guest-token'}, chat: []};
  const context = vm.createContext({state, AbortController, fetch: () => response.promise,
    conversationLanguage: () => 'en-AU', memoirApiPath: x => x, readCookie: () => '', persistChatHistory() {}});
  load(context, 'streamAgentTurn');
  const pending = context.streamAgentTurn('Memory', () => {});
  context.invalidateProjectNavigation();
  state.project = {id: 'b'};
  state.supabase = {user: {id: 'other'}, accessToken: 'other-token'};
  response.resolve({status: 401});
  await assert.rejects(pending, /navigation changed/);
  assert.equal(state.supabase.accessToken, 'other-token');
  assert.equal(state.conversationStreams.size, 0);
});

test('navigation cancels the reader even after conversation readiness, without replaying its tail', async () => {
  let read, canceled = 0, released = false;
  const reader = {read: () => {read = deferred(); return read.promise;},
    cancel: async () => {canceled++; read?.resolve({done: true});}, releaseLock: () => {released = true;}};
  const state = {project: {id: 'a'}, supabase: {user: {id: 'guest'}, accessToken: 'session'}, chat: []};
  const seen = [];
  const context = vm.createContext({state, AbortController, TextDecoder,
    fetch: async () => ({ok: true, status: 200, body: {getReader: () => reader}}),
    conversationLanguage: () => 'en-AU', memoirApiPath: x => x, readCookie: () => '', persistChatHistory() {}});
  load(context, 'streamAgentTurn');
  const pending = context.streamAgentTurn('Memory', x => seen.push(x), x => seen.push(x));
  await tick();
  read.resolve({done: false, value: new TextEncoder().encode(JSON.stringify({type: 'conversation_saved',
    data: {conversation_saved: true, reply: 'Saved'}}))});
  assert.equal((await pending).reply, 'Saved');
  await tick();
  assert.equal(state.conversationStreams.size, 1);
  context.invalidateProjectNavigation();
  state.project = {id: 'b'};
  await tick();
  assert.ok(canceled > 0);
  assert.equal(released, true);
  assert.equal(seen.length, 0);
});

for (const ending of ['final', 'error']) test(`the outer send ${ending} cannot finalize a new projects chat or loading state`, async () => {
  const reply = deferred();
  const state = {project: {id: 'a'}, supabase: {user: {id: 'guest'}}, chat: [],
    dictationStatus: 'off', audioTranscript: '', attachments: [], profileIntakePending: false};
  const input = {value: 'A accepted memory'};
  const context = vm.createContext({state, $: () => input, profile: () => ({}),
    conversationScroll: {follow() {}}, conversationLanguage: () => 'en-AU', currentUiPreference: () => null,
    settleUiLocale: async () => true, conversationMessage: () => 'Fallback',
    render() {}, persistChatHistory() {}, ensureMemorySession: async () => null, agentTurn: () => reply.promise,
    streamAssistantMessage: () => assert.fail('stale send must not replay a reply'), toast: () => assert.fail('stale send must not toast'),
    refreshFamilyContext: () => assert.fail('stale send must not refresh the new project')});
  load(context, 'sendChatMessage');
  const pending = context.sendChatMessage();
  await tick();
  context.invalidateProjectNavigation();
  state.project = {id: 'b'};
  state.chat = [{role: 'user', text: 'B memory'}];
  state.loading = true; // B now has its own pending turn.
  if (ending === 'error') reply.reject(new Error('A error'));
  else reply.resolve({reply: 'A final reply'});
  await pending;
  assert.deepEqual(state.chat.map(m => m.text), ['B memory']);
  assert.equal(state.loading, true);
});

test('same-route photo album Back/Forward keeps the active reply and project recovery intact', () => {
  const path = '/memoir/interview/a';
  const state = {navigationPath: path, project: {id: 'a'}, loading: true, chat: [{role: 'user', text: 'A memory'}]};
  let popstate;
  const context = vm.createContext({state, currentPath: () => path,
    MEMOIR_ROUTES: {interview: '/memoir/interview'},
    window: {addEventListener: (_type, callback) => {popstate = callback;}},
    invalidateProjectNavigation: () => assert.fail('album history must not detach a reply'),
    boot: () => assert.fail('album history must not recover the same project'), render: () => assert.fail('the album controller owns its dialog'),
  });
  vm.runInContext(source.match(/window.addEventListener\("popstate", \(\) => \{[^]*?\n\}\);/)[0], context);
  popstate(); // Back closes the album.
  popstate(); // Forward restores it at the same interview URL.
  assert.equal(state.loading, true);
  assert.equal(state.chat[0].text, 'A memory');
});

function reentryHarness({anonymous = true, saved = 'a', denied = null, historyDenied = false} = {}) {
  const recovery = deferred(), creates = [], starts = [], notices = [], hydrations = [], events = new Map();
  let path = '/', pointer = saved;
  const app = {innerHTML: ''};
  const state = {chat: [], navigationGeneration: 0, compositionStage: 0,
    supabase: {user: {id: 'owner', is_anonymous: anonymous}, accessToken: 'session'}};
  const context = vm.createContext({state, FALLBACK_STORY_PLANS: [],
    MEMOIR_ROUTES: {home: '/memoir', start: '/memoir/start', interview: '/memoir/interview'},
    PLACE_JOURNEY_PROJECT_STORAGE_KEY: 'places',
    localStorage: {removeItem() {}}, sessionStorage: {getItem: () => null},
    currentPath: () => path, window: {history: {
      pushState: (_state, _title, next) => {path = next;}, replaceState: (_state, _title, next) => {path = next;},
    }, addEventListener: (name, callback) => events.set(name, callback)},
    document: {querySelectorAll: () => []},
    $: selector => selector === '#app' ? app : selector.includes('open-memoir')
      ? {addEventListener: (_name, callback) => events.set('begin', callback)} : null,
    ensureAuth: async () => {}, guestTransfer: {complete: async () => false},
    syncProfileUiLocale: async () => events.get('copyme2:ui-locale-change')(),
    savedProjectId: () => pointer, rememberProject: id => {pointer = id;},
    restoreChatHistory: id => [{role: 'user', text: `${id} private history`}],
    hydrateAccountHistory: async () => {hydrations.push(state.project?.id); if (historyDenied) throw new Error('History denied');},
    hydratePlaceJourney: async () => {}, refreshFamilyEntitlement: async () => {}, profileHasContext: () => true,
    conversationLanguage: () => 'en-AU', currentUiLocale: () => 'en-AU',
    preserveConversationLocale: incoming => incoming, mergePlaces: places => places,
    refreshStageReadiness() {}, refreshPrivateDraft() {},
    startCodexConversation: async () => {starts.push(state.project?.id);},
    renderStory() {}, storyGameDialog:{sync() {}},conversationScroll: {mount() {}}, disposeCesiumPlaceJourney() {}, closeProfileMenu() {},
    persistChatHistory() {}, stopVoiceMode() {}, cancelDictation() {}, setLoading: value => {state.loading = value;},
    toast: value => notices.push(value), translate: String, escapeHtml: String,
    api: async (url, options = {}) => {
      if (url === '/v1/projects') {
        const body = JSON.parse(options.body);
        if (body.restore_project_id) throw Object.assign(new Error('Recovery denied'), {status: 403});
        creates.push(body);
        return {id: `new-${creates.length}`, mode: body.mode, profile: {}, requires_supabase_auth: true};
      }
      if (url.endsWith('/consents')) return {};
      if (url.endsWith('/journey')) return {};
      const id = url.slice('/v1/projects/'.length);
      if (id === 'a') {await recovery.promise; if (denied) throw denied;}
      return {id, mode: 'self', profile: {}, requires_supabase_auth: true};
    },
    storyApi: async url => {
      assert.ok(['/v1/user/conversations', '/v1/user/profile'].includes(url));
      return url.endsWith('/conversations') ? {items: []} : {};
    },
  });
  load(context, 'refreshOpeningMessageLocale', 'render', 'renderLanding', 'renderPlatformLanding', 'renderMemoirLanding',
    'navigateTo', 'refreshProject', 'boot', 'startMemoirStory', 'startStory');
  vm.runInContext(source.match(/window.addEventListener\("copyme2:ui-locale-change", \(\) => \{[^]*?\n\}\);/)[0], context);
  return {context, state, recovery, creates, starts, notices, hydrations, events, app, path: () => path,
    setPath: next => {path = next;}};
}

for (const anonymous of [true, false]) test(`early Begin waits for ${anonymous ? 'guest' : 'account'} recovery and keeps one journey`, async () => {
  const h = reentryHarness({anonymous});
  const boot = h.context.boot();
  await tick();
  assert.match(h.app.innerHTML, /data-action="open-memoir"/);
  assert.equal(h.state.project.id, 'a');
  assert.equal(h.state.project.mode, undefined); // Recovery has not authorized its metadata yet.
  const begin = h.events.get('begin')();
  const repeated = h.events.get('begin')();
  try {
    await tick();
    assert.equal(h.creates.length, 0);
  } finally {
    h.recovery.resolve();
    await Promise.all([boot, begin, repeated]);
  }
  assert.equal(h.state.project.id, 'a');
  assert.equal(h.state.projectPrincipalId, 'owner');
  assert.equal(h.path(), '/memoir/interview/a');
  assert.equal(h.creates.length, 0);
  assert.deepEqual(h.hydrations, ['a', 'a']); // Boot plus one coalesced resume.
});

for (const denied of [new Error('Recovery unavailable'), Object.assign(new Error('Denied'), {status: 403})]) {
  test(`failed saved recovery cannot silently create a self project: ${denied.message}`, async () => {
    const h = reentryHarness({denied});
    const boot = h.context.boot(); await tick();
    const begin = h.context.startStory();
    h.recovery.resolve(); await Promise.all([boot, begin]);
    await h.context.startStory(); // A later repeated click remains an explicit recovery failure.
    assert.equal(h.creates.length, 0);
    assert.equal(h.state.projectRecoveryBlocked, 'a');
    assert.equal(h.state.project, null);
  });
}

test('denied canonical history keeps saved self recovery blocked instead of allocating a replacement', async () => {
  const h = reentryHarness({historyDenied: true}); h.recovery.resolve();
  await h.context.boot();
  await h.context.startStory();
  await h.context.startStory();
  assert.equal(h.creates.length, 0);
  assert.equal(h.state.projectRecoveryBlocked, 'a');
});

test('cold Begin coalesces to one fresh self project without a saved pointer', async () => {
  const h = reentryHarness({saved: null});
  await h.context.boot();
  await Promise.all([h.context.startStory(), h.context.startStory()]);
  assert.equal(h.creates.length, 1);
  assert.equal(h.creates[0].mode, 'self');
  assert.equal(h.path(), '/memoir/interview/new-1');
});

test('an explicit family start waits for recovery and then deliberately creates its own project', async () => {
  const h = reentryHarness(); const boot = h.context.boot(); await tick();
  const family = h.context.startStory('family');
  try {await tick(); assert.equal(h.creates.length, 0);}
  finally {h.recovery.resolve(); await Promise.all([boot, family]);}
  assert.equal(h.creates.length, 1);
  assert.equal(h.creates[0].mode, 'family');
  assert.equal(h.path(), '/memoir/interview/new-1');
});

for (const replacement of ['owner', 'session', 'logout', 'navigation']) {
  test(`a waiting Begin cannot survive ${replacement} replacement`, async () => {
    const h = reentryHarness(); const boot = h.context.boot(); await tick();
    const begin = h.context.startStory();
    if (replacement === 'owner') {
      h.context.invalidateProjectNavigation();
      h.state.supabase.user = {id: 'other', is_anonymous: false};
      h.state.supabase.accessToken = 'other-session';
      h.state.project = null;
    } else if (replacement === 'session') h.state.supabase.accessToken = 'new-session';
    else if (replacement === 'logout') h.state.explicitSignOutInProgress = true;
    else {
      h.setPath('/memoir/interview/b');
      await h.context.boot();
    }
    h.recovery.resolve(); await Promise.all([boot, begin]);
    assert.equal(h.creates.length, 0);
    if (replacement === 'owner') assert.equal(h.state.project, null);
    if (replacement === 'navigation') assert.equal(h.state.project.id, 'b');
  });
}

test('recovery completion does not wait for the subsequent greeting before admitting Begin', async () => {
  const h = reentryHarness(), greeting = deferred();
  let greetingStarted;
  const entered = new Promise(resolve => {greetingStarted = resolve;});
  h.context.startCodexConversation = async () => {greetingStarted(); await greeting.promise;};
  const boot = h.context.boot(); await tick();
  const begin = h.context.startStory();
  h.recovery.resolve(); await entered; await tick();
  // The recovered identity is already authoritative even if opening copy is streaming.
  assert.equal(h.creates.length, 0);
  assert.equal(h.state.projectRecovery, null);
  greeting.resolve(); await Promise.all([boot, begin]);
});
