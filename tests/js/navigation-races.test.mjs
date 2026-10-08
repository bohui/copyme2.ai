import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {TextDecoder, TextEncoder} from 'node:util';

const source = fs.readFileSync(new URL('../../apps/web/client/memoir/client.js', import.meta.url), 'utf8');
const extract = name => source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))?.[0];
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return {promise, resolve, reject}; };
const tick = () => new Promise(resolve => setImmediate(resolve));
function load(context, ...names) {
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
    'saveBrowserValue', 'persistChatHistory', 'agentTurn');
  const pending = context.agentTurn('A accepted memory');
  if (ending === 'workspace-tail') {
    await delta('A accepted partial');
    reply.resolve({reply: 'A accepted partial', conversation_saved: true});
    // This ready reply may start its own draft refresh while still on A.
    context.refreshPrivateDraft = () => {};
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
    conversationScroll: {follow() {}}, conversationLanguage: () => 'en-AU', conversationMessage: () => 'Fallback',
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
