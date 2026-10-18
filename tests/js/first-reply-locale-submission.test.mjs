import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import {createPreferenceSession, firstReplyUiCandidate} from '../../apps/web/i18n/session.mjs';
import {encodePreference, preferenceCookie, readPreference} from '../../apps/web/i18n/preference.mjs';
import {createInterviewPhotoState} from '../../apps/web/client/memoir/interview-photo-turns.mjs';
import {readMemoirClientSource} from './helpers/memoir-source.mjs';

const source = readMemoirClientSource();
const localeSource = readFileSync(new URL('../../apps/web/client/memoir/ui-locale.mjs', import.meta.url), 'utf8');
const extract = name => source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0];
const deferred = () => {let resolve, reject; const promise = new Promise((yes, no) => {resolve = yes; reject = no;}); return {promise, resolve, reject};};
const tick = () => new Promise(resolve => setImmediate(resolve));
const manual = locale => ({locale, source:'manual', revision:1});
const record = locale => ({version:1, initialized:true, locale, revision:1, source:'explicit'});
const opposite = locale => locale === 'zh-CN' ? 'I remember the garden from childhood.' : '我记得小时候的花园。';

function harness({profile = {}, preference = null, cookie = '', uiLocale = 'en-AU', text = opposite('en-AU'), reviewedVoice = false} = {}) {
  const requests = [], rpcCalls = [], profileWrites = [], notices = [];
  const input = {value:reviewedVoice ? '' : text};
  const state = {project:{id:'project', profile:structuredClone(profile)}, supabase:{user:{id:'owner'}, accessToken:'fixture'},
    navigationGeneration:0, chat:[], dictationStatus:'off', attachments:[], audioTranscript:reviewedVoice ? text : '',
    audioRecordings:reviewedVoice ? [{id:'saved-recording'}] : [], audioTranscriptKind:'narrator_chat'};
  let read = async () => ({data:preference});
  let write = async args => ({data:{locale:args.p_locale, source:args.p_source, revision:2}});
  let patch = async options => {
    const locale = JSON.parse(options.body).preferred_language;
    profileWrites.push(locale);
    return {preferred_language:locale, conversation_language:record(locale)};
  };
  const client = {rpc:async (name, args) => {
    rpcCalls.push({name, args});
    return name === 'read_ui_locale_preference' ? read(args) : write(args);
  }};
  const context = vm.createContext({state, input, notices, document:{cookie}, uiLocale,
    createPreferenceSession, firstReplyUiCandidate, preferenceCookie, readPreference, encodePreference,
    $:selector => selector === '#chat-input' ? input : null, translate:key => key,
    currentUiLocale:() => context.uiLocale, localizedErrorMessage:() => 'Preferences unavailable',
    storyApi:async (_path, options) => patch(options),
    toast:message => notices.push(message), render() {}, conversationScroll:{follow() {}},
    conversationMessage:key => key, ensureMemorySession:async () => null,
    streamAssistantMessage:async () => {}, refreshFamilyContext() {},
    simulatedLoopTrace:() => [], workspaceTurnFocus:() => null, nextAssistantMessageId:() => 'reply',
    markWorkspaceFocusStarted() {}, refreshStageReadiness() {}, refreshPrivateDraft() {}, updateStreamingAssistantMessage() {},
    memoirApiPath:value => value, AbortController,
    fetch:async (url, options) => {
      requests.push({url, body:JSON.parse(options.body)});
      return {ok:true, status:200, body:null, json:async () => ({reply:'Synthetic reply', conversation_saved:true})};
    },
  });
  for (const name of ['captureProjectScope', 'isCurrentProjectScope', 'profile', 'conversationLanguage',
    'preserveConversationLocale', 'mergePrivateProfile', 'hydrateConversationProfile',
    'sendChatMessage', 'agentTurn', 'streamAgentTurn']) vm.runInContext(extract(name), context);
  vm.runInContext(localeSource.slice(localeSource.indexOf('export const UI_LOCALES')).replace(/^export /gm, ''), context);
  vm.runInContext(`
    Object.assign(globalThis, createUiLocale({captureProjectScope, isCurrentProjectScope, preserveConversationLocale,
      profile, state, storyApi, toast}));
    installUiLocaleBridge();
    globalThis.__copyme2SetUiLocale = async (locale, options = {}) => {
      const choice = await __copyme2BeforeUiLocaleChange(locale, options);
      if (!choice || !__copyme2UiLocaleScopeCurrent(choice.scope)) return false;
      uiLocale = choice.locale;
      document.cookie = preferenceCookie + '=' + encodeURIComponent(encodePreference(choice.locale, choice.source, state.supabase.user.id));
      return true;
    };
  `, context);
  context.uiPreferenceSession.setSession(client, state.supabase.user);
  const storage = new Map();
  state.photoTurns = createInterviewPhotoState({state, scope:() => context.captureProjectScope(), render() {},
    api:async () => ({}), storage:{setItem:(key, value) => storage.set(key, value), removeItem:key => storage.delete(key)}, uuid:() => 'turn'});
  const calls = {detection:0, localization:0};
  for (const [name, key] of [['firstReplyLanguage', 'detection'], ['applyFirstReplyLocalization', 'localization']]) {
    const original = context[name];
    context[name] = (...args) => {calls[key]++; return original(...args);};
  }
  return {context, state, input, requests, calls, rpcCalls, notices, profileWrites, client,
    setRead:value => {read = value;}, setWrite:value => {write = value;}, setPatch:value => {patch = value;}};
}

function assertExplicit(h, locale, text, reviewedVoice = false) {
  assert.deepEqual(h.calls, {detection:0, localization:0});
  assert.deepEqual(h.notices, []);
  assert.equal(h.requests.length, 1);
  assert.equal(h.requests[0].url, '/v1/agent/turn');
  assert.equal(h.requests[0].body.language, locale);
  assert.equal(h.requests[0].body.first_reply_localization, false);
  assert.equal(h.requests[0].body.conversation_text, text);
  assert.equal(h.requests[0].body.text, text);
  assert.equal(h.requests[0].body.source_kind, reviewedVoice ? 'narrator_transcript' : 'narrator_chat');
  assert.deepEqual(h.requests[0].body.recording_ids, reviewedVoice ? ['saved-recording'] : []);
  assert.equal(h.rpcCalls.filter(call => call.name === 'set_ui_locale_preference').length, 0);
  assert.deepEqual(h.profileWrites, []);
}

for (const locale of ['en-AU', 'zh-CN']) for (const reviewedVoice of [false, true]) {
  for (const setting of ['UI cookie', 'account', 'profile', 'interview record']) {
    test(`${setting} ${locale} skips both routines for opposite-language ${reviewedVoice ? 'reviewed voice' : 'text'}`, async () => {
      const text = opposite(locale);
      const profile = setting === 'profile' ? {preferred_language:locale} : setting === 'interview record' ? {conversation_language:record(locale)} : {};
      const cookie = setting === 'UI cookie' ? `${preferenceCookie}=${encodeURIComponent(encodePreference(locale, 'manual', 'owner'))}` : '';
      const h = harness({profile, cookie, preference:setting === 'account' ? manual(locale) : null, text, reviewedVoice});
      await h.context.sendChatMessage();
      assertExplicit(h, locale, text, reviewedVoice);
      assert.deepEqual(h.state.project.profile, profile);
      if (setting === 'account') assert.equal(h.context.uiPreferenceSession.preference.locale, locale);
    });
  }

  test(`account ${locale} is hydrated again on reload before ${reviewedVoice ? 'reviewed voice' : 'text'} submission`, async () => {
    for (let reload = 0; reload < 2; reload++) {
      const h = harness({preference:manual(locale), text:opposite(locale), reviewedVoice});
      await h.context.sendChatMessage();
      assertExplicit(h, locale, opposite(locale), reviewedVoice);
      assert.equal(h.rpcCalls[0].name, 'read_ui_locale_preference');
    }
  });
}

test('interview language keeps precedence over a different explicit UI language', async () => {
  const h = harness({profile:{preferred_language:'zh-CN'}, preference:manual('en-AU')});
  await h.context.sendChatMessage();
  assertExplicit(h, 'zh-CN', opposite('en-AU'));
  assert.equal(h.context.uiLocale, 'en-AU');
  assert.equal(h.context.uiPreferenceSession.preference.locale, 'en-AU');
});

test('pending preference hydration waits before either routine or backend submission', async () => {
  const h = harness(), response = deferred();
  h.setRead(() => response.promise);
  const sending = h.context.sendChatMessage();
  await tick();
  assert.deepEqual(h.calls, {detection:0, localization:0});
  assert.deepEqual(h.requests, []);
  assert.equal(h.input.value, opposite('en-AU'));
  response.resolve({data:manual('en-AU')});
  await sending;
  assertExplicit(h, 'en-AU', opposite('en-AU'));
});

for (const locale of ['en-AU', 'zh-CN']) test(`pending private profile hydration resolves ${locale} before submission`, async () => {
  const h = harness({text:opposite(locale)}), response = deferred();
  h.context.api = async path => path.endsWith('/journey') ? {active_session:null} : {id:'project', profile:{}};
  h.context.storyApi = () => response.promise;
  h.context.mergePlaces = places => places;
  vm.runInContext(extract('refreshProject'), h.context);
  const refreshing = h.context.refreshProject();
  await tick();
  const sending = h.context.sendChatMessage();
  await tick();
  assert.deepEqual(h.calls, {detection:0, localization:0});
  assert.deepEqual(h.requests, []);
  response.resolve({preferred_language:locale, conversation_language:record(locale)});
  await refreshing;
  await sending;
  assertExplicit(h, locale, opposite(locale));
  assert.equal(h.state.project.profile.preferred_language, locale);
});

for (const reviewedVoice of [false, true]) test(`failed preference read preserves the ${reviewedVoice ? 'reviewed voice' : 'typed'} draft without inferring`, async () => {
  const h = harness({reviewedVoice});
  h.setRead(async () => ({error:{code:'503'}}));
  await h.context.sendChatMessage();
  assert.deepEqual(h.calls, {detection:0, localization:0});
  assert.deepEqual(h.requests, []);
  assert.equal(h.state.chat.length, 0);
  assert.equal(h.state.loading, false);
  assert.equal(reviewedVoice ? h.state.audioTranscript : h.input.value, opposite('en-AU'));
  if (reviewedVoice) assert.equal(h.state.audioRecordings[0].id, 'saved-recording');
  h.setRead(async () => ({data:manual('en-AU')}));
  h.notices.length = 0;
  await h.context.sendChatMessage();
  assertExplicit(h, 'en-AU', opposite('en-AU'), reviewedVoice);
});

for (const reviewedVoice of [false, true]) test(`failed private profile hydration retries before ${reviewedVoice ? 'reviewed voice' : 'typed'} submission`, async () => {
  const h = harness({reviewedVoice}), response = deferred();
  let reads = 0;
  h.context.mergePlaces = places => places;
  h.context.storyApi = () => {
    reads++;
    return reads === 1 ? response.promise : Promise.resolve({preferred_language:'en-AU', conversation_language:record('en-AU')});
  };
  const hydrating = assert.rejects(h.context.hydrateConversationProfile(), /Unavailable/);
  const sending = h.context.sendChatMessage();
  await tick();
  response.reject(new Error('Unavailable'));
  await Promise.all([hydrating, sending]);
  assert.equal(reviewedVoice ? h.state.audioTranscript : h.input.value, opposite('en-AU'));
  assert.deepEqual(h.requests, []);
  assert.deepEqual(h.calls, {detection:0, localization:0});
  assert.equal(h.state.conversationLocaleHydration.failed, true);
  h.notices.length = 0;
  await h.context.sendChatMessage();
  assertExplicit(h, 'en-AU', opposite('en-AU'), reviewedVoice);
  assert.equal(reads, 2);
  assert.equal(h.state.conversationLocaleHydration.failed, false);
});

test('repeated private profile failures stay retryable without treating unknown preference as automatic', async () => {
  const h = harness();
  let reads = 0;
  h.context.storyApi = async () => {reads++; throw new Error('Unavailable');};
  await assert.rejects(h.context.hydrateConversationProfile(), /Unavailable/);
  for (let retry = 0; retry < 2; retry++) {
    await h.context.sendChatMessage();
    assert.equal(h.input.value, opposite('en-AU'));
    assert.deepEqual(h.requests, []);
    assert.deepEqual(h.calls, {detection:0, localization:0});
  }
  assert.equal(reads, 3);
});

test('an account switch discards old hydration and resolves the new viewer before submission', async () => {
  const cookie = `${preferenceCookie}=${encodeURIComponent(encodePreference('en-AU', 'manual', 'owner'))}`;
  const h = harness({cookie}), old = deferred();
  h.setRead(args => args.p_expected_viewer === 'owner' ? old.promise : Promise.resolve({data:manual('zh-CN')}));
  const sending = h.context.sendChatMessage();
  await tick();
  h.state.supabase.user = {id:'new-owner'};
  h.state.project = {id:'new-project', profile:{}};
  h.state.chat = [];
  h.state.loading = false;
  h.context.uiPreferenceSession.setSession(h.client, h.state.supabase.user);
  old.resolve({data:manual('en-AU')});
  await sending;
  assert.deepEqual(h.requests, []);
  assert.equal(h.context.uiPreferenceSession.preference, null);
  await h.context.sendChatMessage();
  assertExplicit(h, 'zh-CN', opposite('en-AU'));
  assert.equal(h.requests[0].body.project_id, 'new-project');
});

for (const stage of ['hydration', 'optional session']) test(`manual language change during ${stage} wins before either first-reply call`, async () => {
  const h = harness(), pause = deferred(), saved = deferred();
  if (stage === 'hydration') h.setRead(() => pause.promise);
  else h.context.ensureMemorySession = () => pause.promise;
  h.setPatch(() => saved.promise);
  const sending = h.context.sendChatMessage();
  await tick();
  const changing = h.context.__copyme2SetUiLocale('en-AU');
  await tick();
  pause.resolve(stage === 'hydration' ? {data:null} : null);
  await tick();
  assert.deepEqual(h.calls, {detection:0, localization:0});
  assert.deepEqual(h.requests, []);
  saved.resolve({preferred_language:'en-AU', conversation_language:record('en-AU')});
  await changing;
  await sending;
  assert.deepEqual(h.calls, {detection:0, localization:0});
  assert.deepEqual(h.notices, []);
  assert.equal(h.requests.length, 1);
  assert.equal(h.requests[0].body.language, 'en-AU');
  assert.equal(h.requests[0].body.first_reply_localization, false);
  assert.equal(h.state.project.profile.preferred_language, 'en-AU');
  assert.equal(h.context.uiPreferenceSession.preference.locale, 'en-AU');
});

for (const locale of ['en-AU', 'zh-CN']) test(`automatic mode still detects and localizes the first ${locale} reply`, async () => {
  const text = opposite(locale === 'en-AU' ? 'zh-CN' : 'en-AU');
  const h = harness({text});
  await h.context.sendChatMessage();
  assert.deepEqual(h.notices, []);
  assert.deepEqual(h.calls, {detection:1, localization:1});
  assert.equal(h.requests.length, 1);
  assert.equal(h.requests[0].body.language, locale);
  assert.equal(h.requests[0].body.first_reply_localization, true);
  assert.equal(h.context.uiPreferenceSession.preference.source, 'first_reply');
  assert.equal(h.context.uiPreferenceSession.preference.locale, locale);
});

test('a manual change superseding in-flight automatic localization reaches the backend', async () => {
  const h = harness(), response = deferred();
  h.setWrite(args => args.p_source === 'first_reply' ? response.promise : Promise.resolve({data:manual(args.p_locale)}));
  const sending = h.context.sendChatMessage();
  await tick();
  assert.deepEqual(h.calls, {detection:1, localization:1});
  const changing = h.context.__copyme2SetUiLocale('en-AU');
  response.resolve({data:{locale:'zh-CN', source:'first_reply', revision:1}});
  await changing;
  await sending;
  assert.deepEqual(h.notices, []);
  assert.equal(h.requests.length, 1);
  assert.equal(h.requests[0].body.language, 'en-AU');
  assert.equal(h.requests[0].body.first_reply_localization, false);
  assert.equal(h.state.project.profile.preferred_language, 'en-AU');
  assert.equal(h.context.uiPreferenceSession.preference.locale, 'en-AU');
});
