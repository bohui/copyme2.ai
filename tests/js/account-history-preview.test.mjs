import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../../apps/web/client/memoir/client.js', import.meta.url), 'utf8');
const openingMessages = ['en-AU', 'zh-CN'].map(locale => JSON.parse(fs.readFileSync(
  new URL(`../../apps/web/messages/${locale}.json`, import.meta.url), 'utf8')).Memoir.conversation.opening);
function load(context, name) {
  for (const helper of ['captureProjectScope', 'isCurrentProjectScope', 'readBrowserValues', 'mergeChatHistoryCopies']) {
    vm.runInContext(source.match(new RegExp(`(?:async )?function ${helper}\\([^]*?\\n\}`))[0], context);
  }
  if (name === 'boot') { load(context, 'invalidateProjectNavigation'); context.persistChatHistory ||= () => {}; }
  if (['boot', 'startMemoirStory'].includes(name)) {
    for (const helper of ['savedProjectStorageKey', 'readBrowserValue', 'saveBrowserValue', 'savedProjectId', 'rememberProject']) load(context, helper);
  }
  if (name === 'ensureRecallPreview') {
    context.AbortController = AbortController;
    context.clearTimeout ||= () => {};
    context.setTimeout ||= () => {};
  }
  if (name === 'hydrateAccountHistory') {
    context.openingMessages = openingMessages;
    context.conversationMessage ||= () => openingMessages[0];
    load(context, 'originalConversationText');
    load(context, 'normalizeHistoryOpening');
  }
  vm.runInContext(source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0], context);
}

test('merged history starts with one original Mira greeting and retains every real turn', async () => {
  const [opening, chineseOpening] = openingMessages;
  const state = { supabase: { user: { id: 'owner', is_anonymous: false } }, project: { id: 'project' },
    chat: [{ role: 'assistant', text: opening }, { role: 'assistant', text: chineseOpening }] };
  const context = vm.createContext({ state, openingMessages, conversationMessage: () => chineseOpening,
    cleanAssistantText: text => text, persistChatHistory() {},
    storyApi: async () => ({ items: [
      { id: 'account', created_at: '2026-09-01', messages: [
        { role: 'user', text: 'My first memory' }, { role: 'assistant', text: 'Tell me more.' }] },
      { id: 'attached', created_at: '2026-10-02', messages: [
        { role: 'assistant', text: opening }, { role: 'assistant', text: opening }] },
    ] }),
  });
  load(context, 'hydrateAccountHistory');
  await context.hydrateAccountHistory();
  assert.deepEqual(JSON.parse(JSON.stringify(state.chat.map(({ role, text }) => ({ role, text })))), [
    { role: 'assistant', text: opening }, { role: 'user', text: 'My first memory' },
    { role: 'assistant', text: 'Tell me more.' },
  ]);
});

test('older transcripts receive a greeting without deleting repeated replies or quoted greetings', () => {
  const context = vm.createContext({ openingMessages, conversationMessage: () => openingMessages[1] });
  load(context, 'normalizeHistoryOpening');
  const messages = [
    { role: 'user', text: openingMessages[0] },
    { role: 'assistant', text: 'Tell me more.' }, { role: 'assistant', text: 'Tell me more.' },
  ];
  const result = context.normalizeHistoryOpening(messages);
  assert.equal(result[0].role, 'assistant');
  assert.equal(result[0].text, openingMessages[1]);
  assert.equal(result.length, 4);
  result.slice(1).forEach((message, index) => assert.equal(message, messages[index]));
  assert.equal(context.normalizeHistoryOpening(result).length, 4);
  assert.equal(context.normalizeHistoryOpening([]).length, 0);
});

test('history removes legacy instructions from cached user messages before deduplication', async () => {
  const original = '我的家乡\n有一条河。';
  const wrapped = `The storyteller said: ${original}\nThis is the storyteller's first answer to the shared profile-intake opening. Extract only explicit facts`;
  const state = { supabase: { user: { id: 'owner', is_anonymous: false } }, project: { id: 'project' },
    chat: [{ role: 'user', text: wrapped }] };
  const context = vm.createContext({ state, cleanAssistantText: text => text, persistChatHistory() {},
    storyApi: async () => ({ items: [{ id: 'saved', messages: [{ role: 'user', text: original }] }] }),
  });
  load(context, 'hydrateAccountHistory');
  await context.hydrateAccountHistory();
  assert.equal(state.chat.filter(message => message.role === 'user').length, 1);
  assert.equal(state.chat[1].text, original);
});

test('busy composer remains pending rather than reporting a failed skill', async () => {
  const state = { project: { id: 'project' }, recallStatus: { payment_required: true } };
  const context = vm.createContext({ state, render() {}, conversationLanguage: () => 'zh-CN',
    setTimeout() {},
    storyApi: async () => { throw Object.assign(new Error('Busy'), { code: 'AGENT_TURN_IN_PROGRESS' }); },
  });
  load(context, 'ensureRecallPreview');
  await context.ensureRecallPreview();
  assert.equal(state.recallPreview.status, 'pending');
});

test('OAuth return loads saved account history into the main chat before rendering', async () => {
  const state = { supabase: { user: { id: 'owner', is_anonymous: false } }, chat: [] };
  const context = vm.createContext({ state, FALLBACK_STORY_PLANS: [], MEMOIR_ROUTES: { start: '/memoir/start', interview: '/memoir/interview' },
    sessionStorage: { getItem: () => null },
    localStorage: { getItem: () => 'project', setItem() {}, removeItem() {} },
    ensureAuth: async () => {}, guestTransfer: { complete: async () => false },
    syncProfileUiLocale: async () => {}, refreshProject: async () => {},
    hydratePlaceJourney: async () => {}, refreshFamilyEntitlement: async () => {},
    profileHasContext: () => true, currentPath: () => '/memoir/interview/project',
    render() {}, startCodexConversation: async () => {},
    restoreChatHistory: () => [{ role: 'assistant', text: 'Guest opening' }],
    cleanAssistantText: text => text, persistChatHistory() {},
    storyApi: async () => ({ items: [{ id: 'account-conversation', messages: [
      { role: 'user', text: 'My saved childhood' }, { role: 'assistant', text: 'Tell me more.' },
    ] }] }),
    toast() {},
  });
  if (source.includes('function hydrateAccountHistory(')) load(context, 'hydrateAccountHistory');
  load(context, 'boot');
  await context.boot();
  assert.ok(state.chat.some(message => message.text === 'My saved childhood'));
  assert.ok(state.chat.some(message => message.text === 'Guest opening'));
});

test('history hydration preserves repeated saved messages without duplicating local mirrors', async () => {
  const repeated = { role: 'user', text: 'I remember the garden.' };
  const state = { supabase: { user: { id: 'owner', is_anonymous: false } }, project: { id: 'project' },
    chat: [repeated, repeated, { role: 'user', text: 'Unsent local memory' }] };
  const context = vm.createContext({ state, cleanAssistantText: text => text, persistChatHistory() {},
    storyApi: async () => ({ items: [{ id: 'saved', messages: [repeated, repeated] }] }),
  });
  load(context, 'hydrateAccountHistory');
  await context.hydrateAccountHistory();
  assert.equal(state.chat.filter(message => message.text === repeated.text).length, 2);
  assert.ok(state.chat.some(message => message.text === 'Unsent local memory'));
});

test('history response for an account cannot populate a different account', async () => {
  const state = { supabase: { user: { id: 'owner', is_anonymous: false } }, project: { id: 'project' }, chat: [] };
  const context = vm.createContext({ state, cleanAssistantText: text => text, persistChatHistory() {},
    storyApi: async () => {
      state.supabase.user = { id: 'another-owner', is_anonymous: false };
      return { items: [{ id: 'saved', messages: [{ role: 'user', text: 'Private memory' }] }] };
    },
  });
  load(context, 'hydrateAccountHistory');
  await context.hydrateAccountHistory();
  assert.equal(state.chat.length, 0);
});

test('manual retry cannot launch a second preview while the first request is running', async () => {
  const state = { project: { id: 'project' }, recallStatus: { payment_required: true } };
  let finish, requests = 0;
  const context = vm.createContext({ state, render() {}, conversationLanguage: () => 'zh-CN',
    storyApi: () => { requests++; return new Promise(resolve => { finish = resolve; }); },
  });
  load(context, 'ensureRecallPreview');
  const running = context.ensureRecallPreview();
  await context.ensureRecallPreview({ retry: true });
  assert.equal(requests, 1);
  finish({ status: 'ready', preview: {} });
  await running;
  assert.equal(state.recallPreview.status, 'ready');
});

test('saved conversation hydration preserves matching local skill progress', async () => {
 const trace=[{id:'place',skill:'memoir-place-journey',status:'completed'}];
 const state={supabase:{user:{id:'owner',is_anonymous:false}},project:{id:'project'},
   chat:[{role:'assistant',text:'Tell me more.',trace,traceMode:'live'}]};
 const context=vm.createContext({state,cleanAssistantText:text=>text,persistChatHistory(){},
   storyApi:async()=>({items:[{id:'saved',messages:[{role:'assistant',text:'Tell me more.'}]}]}),
 });
 load(context,'hydrateAccountHistory');
 await context.hydrateAccountHistory();
 const reply=state.chat.find(message=>message.text==='Tell me more.');
 assert.equal(reply.trace,trace);
 assert.equal(reply.traceMode,'live');
});

test('opening an interview after login restores account turns before sample admission', async () => {
  const state = { supabase: { user: { id: 'owner', is_anonymous: false } }, chat: [], loading: false };
  let previewHistory;
  const context = vm.createContext({ state, PLACE_JOURNEY_PROJECT_STORAGE_KEY: 'places',
    MEMOIR_ROUTES: { interview: '/memoir/interview' }, stopVoiceMode() {},
    conversationLanguage: () => 'zh-CN', currentUiLocale: () => 'zh-CN',
    localStorage: { setItem() {}, removeItem() {} },
    api: async path => path === '/v1/projects' ? { id: 'new-project', profile: {} } : {},
    storyApi: async path => path === '/v1/user/profile' ? {} : { items: [
      { id: 'saved', messages: [{ role: 'user', text: 'My saved childhood' }] }] },
    navigateTo() {}, refreshProject: async () => {},
    refreshFamilyEntitlement: async () => { previewHistory = [...state.chat]; },
    startCodexConversation: async () => { if (!state.chat.length) state.chat.push({ role: 'assistant', text: 'Opening' }); },
    cleanAssistantText: text => text, persistChatHistory() {}, setLoading() {}, toast() {},
  });
  load(context, 'hydrateAccountHistory');
  load(context, 'startMemoirStory');
  await context.startMemoirStory();
  assert.ok(state.chat.some(message => message.text === 'My saved childhood'));
  assert.ok(previewHistory.some(message => message.text === 'My saved childhood'));
});

test('continuing a signed-in interview uses its saved project for progressive samples', async () => {
  const state = { supabase: { user: { id: 'owner', is_anonymous: false }, accessToken: 'session' }, chat: [], loading: false };
  const context = vm.createContext({ state, PLACE_JOURNEY_PROJECT_STORAGE_KEY: 'places',
    MEMOIR_ROUTES: { interview: '/memoir/interview' }, stopVoiceMode() {},
    conversationLanguage: () => 'zh-CN', currentUiLocale: () => 'zh-CN',
    localStorage: { setItem() {}, removeItem() {} },
    api: async (path, options) => {
      if (path !== '/v1/projects') return {};
      assert.equal(JSON.parse(options.body).restore_project_id, 'saved-project');
      assert.equal(options.headers.Authorization, 'Bearer session');
      return { id: 'saved-project', profile: {} };
    },
    storyApi: async path => path === '/v1/user/profile' ? {} : {
      resume_project_id: 'saved-project', items: [{ id: 'saved', messages: [{ role: 'user', text: 'My saved childhood' }] }] },
    navigateTo() {}, refreshProject: async () => {}, refreshFamilyEntitlement: async () => {},
    startCodexConversation: async () => {}, cleanAssistantText: text => text, persistChatHistory() {},
    setLoading() {}, toast() {},
  });
  load(context, 'hydrateAccountHistory');
  load(context, 'startMemoirStory');
  await context.startMemoirStory();
  assert.equal(state.project?.id, 'saved-project');
  assert.ok(state.chat.some(message => message.text === 'My saved childhood'));
});

test('an account switch during interview recovery discards the prior account history', async () => {
  const state = { supabase: { user: { id: 'owner', is_anonymous: false } }, chat: [], loading: false };
  let created = false;
  const context = vm.createContext({ state, stopVoiceMode() {}, conversationLanguage: () => 'en-AU',
    storyApi: async () => {
      context.invalidateProjectNavigation();
      state.supabase.user = { id: 'another-owner', is_anonymous: false };
      return { resume_project_id: 'private-project', items: [{ messages: [{ role: 'user', text: 'Private memory' }] }] };
    },
    api: async () => { created = true; return {}; },
    persistChatHistory() {}, setLoading() {}, toast() {},
  });
  load(context, 'invalidateProjectNavigation');
  load(context, 'startMemoirStory');
  await context.startMemoirStory();
  assert.equal(created, false);
  assert.equal(state.chat.length, 0);
  assert.equal(state.loading, false);
});
