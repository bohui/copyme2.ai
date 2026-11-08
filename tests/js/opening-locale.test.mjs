import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import {createConversationHistory} from '../../apps/web/client/memoir/conversation-history.mjs';
import {readMemoirClientSource} from './helpers/memoir-source.mjs';

const source = readMemoirClientSource();
const openings = Object.fromEntries(['en-AU', 'zh-CN'].map(locale => [locale, JSON.parse(readFileSync(
  new URL(`../../apps/web/messages/${locale}.json`, import.meta.url), 'utf8')).Memoir.conversation.opening]));

const extract = name => source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0];

function harness(chat = []) {
  const state = {chat};
  let locale = 'en-AU';
  let listener, saved;
  const context = vm.createContext({state,
    window:{addEventListener:(_name, handler) => {listener = handler;}},
    currentPath: () => '/memoir/interview/project', MEMOIR_ROUTES: { home: '/memoir' },
    openingMessages:Object.values(openings), conversationMessage:() => openings[locale],
    persistChatHistory:() => {saved = structuredClone(state.chat);},
    closeProfileMenu() {}, render() {},
    cleanAssistantText:text => text, captureProjectScope:() => ({}), isCurrentProjectScope:() => true,
    nextAssistantMessageId:() => 'opening', ASSISTANT_STREAM_CHUNK_SIZE:5,
    updateStreamingAssistantMessage() {},
  });
  for (const name of ['refreshOpeningMessageLocale', 'normalizeHistoryOpening', 'streamAssistantMessage']) {
    vm.runInContext(extract(name), context);
  }
  vm.runInContext(source.match(/window.addEventListener\("copyme2:ui-locale-change", \(\) => \{[^]*?\n\}\);/)[0], context);
  return {state, context, saved:() => saved, switchLocale:value => {locale = value; listener();}};
}

function historyHarness(t) {
  const stores = {localStorage:new Map(), sessionStorage:new Map()};
  for (const [name, cache] of Object.entries(stores)) {
    const previous = Object.getOwnPropertyDescriptor(globalThis, name);
    Object.defineProperty(globalThis, name, {configurable:true, value:{
      getItem: key => cache.get(key) ?? null,
      setItem: (key, value) => cache.set(key, value),
    }});
    t.after(() => {
      if (previous) Object.defineProperty(globalThis, name, previous);
      else delete globalThis[name];
    });
  }
  const visit = () => {
    const h = harness();
    Object.assign(h.state, {project:{id:'project'}, supabase:{user:{id:'guest', is_anonymous:true}}});
    Object.assign(h.context, createConversationHistory({state:h.state, cleanAssistantText:h.context.cleanAssistantText}), {
      translate: key => key, translateWith: key => key,
      storyApi: async () => ({project_id:'project', policy_epoch:'1', items:[]}),
    });
    for (const name of ['simulatedLoopTrace', 'startCodexConversation', 'hydrateAccountHistory', 'originalConversationText']) {
      vm.runInContext(extract(name), h.context);
    }
    return h;
  };
  return {cache:stores.localStorage, visit};
}

test('switching languages updates and saves only the fixed opening greeting', () => {
  const opening = {id:'opening', role:'assistant', productCopy:'opening', text:openings['en-AU'], streaming:false};
  const original = [{role:'user', text:openings['en-AU']}, {role:'assistant', text:'Tell me more about the garden.'}];
  const h = harness([opening, ...original]);

  for (const locale of ['zh-CN', 'en-AU']) {
    h.switchLocale(locale);
    assert.equal(opening.text, openings[locale]);
    assert.equal(h.saved()[0].text, openings[locale]);
    assert.equal(opening.streaming, false);
    assert.deepEqual(h.state.chat.slice(1), original);
    assert.deepEqual(h.saved().slice(1), original);
  }
});

test('restored English product copy uses the selected Chinese locale', () => {
  const original = {role:'user', text:'My garden memory.'};
  const h = harness();
  h.switchLocale('zh-CN');
  const messages = h.context.normalizeHistoryOpening([
    {id:'cached-opening', role:'assistant', text:openings['en-AU']}, original,
  ]);
  assert.equal(messages[0].text, openings['zh-CN']);
  assert.equal(messages[0].id, 'cached-opening');
  assert.equal(messages[0].productCopy, 'opening');
  assert.equal(messages.length, 2);
  assert.equal(messages[1], original);
});

test('switching language during the opening animation cannot restore English text', async () => {
  const h = harness();
  let resume;
  const paused = new Promise(resolve => {resume = resolve;});
  h.context.waitForAssistantStream = () => paused;
  const streaming = h.context.streamAssistantMessage(openings['en-AU'], {productCopy:'opening'});
  assert.equal(h.state.chat[0].streaming, true);

  h.switchLocale('zh-CN');
  resume();
  await streaming;

  assert.equal(h.state.chat.length, 1);
  assert.equal(h.state.chat[0].text, openings['zh-CN']);
  assert.equal(h.state.chat[0].streaming, false);
});

test('reloading during the opening restores one complete greeting', async t => {
  const {visit} = historyHarness(t);
  const first = visit();
  let resume;
  const paused = new Promise(resolve => {resume = resolve;});
  first.context.simulatedLoopTrace = () => [];
  first.context.waitForAssistantStream = () => paused;
  const streaming = first.context.startCodexConversation();
  assert.equal(first.state.chat[0].streaming, true);
  assert.notEqual(first.state.chat[0].text, openings['en-AU']);
  first.context.persistChatHistory(); // The pagehide handler saves this partial message.
  first.context.isCurrentProjectScope = () => false;
  resume();
  await streaming;

  const reloaded = visit();
  reloaded.switchLocale('zh-CN');
  reloaded.state.chat = reloaded.context.restoreChatHistory('project');
  const cachedOpening = reloaded.state.chat[0];
  await reloaded.context.hydrateAccountHistory();
  await reloaded.context.startCodexConversation({resume:true});

  assert.equal(reloaded.state.chat.length, 1);
  assert.equal(cachedOpening.productCopy, 'opening');
  assert.equal(reloaded.state.chat[0].id, cachedOpening.id);
  assert.equal(reloaded.state.chat[0].text, openings['zh-CN']);
  assert.ok(!reloaded.state.chat[0].streaming);
});

test('restoring a legacy duplicate removes the partial opening and preserves real turns', async t => {
  const {cache, visit} = historyHarness(t);
  const h = visit();
  const opening = openings['en-AU'];
  const reply = 'Hi,';
  cache.set('memory-spark-chat-history:guest:project', JSON.stringify([
    {id:'assistant-message-1', role:'assistant', text:opening.slice(0, 60),
      traceMode:'simulated', trace:h.context.simulatedLoopTrace(['conversation.start', 'memory.search'])},
    {id:'history-opening', role:'assistant', text:opening},
    {role:'user', text:'Can you say hi?', clientTurnId:'turn'},
    {role:'assistant', text:reply, clientTurnId:'turn'},
  ]));
  h.state.chat = h.context.restoreChatHistory('project');
  await h.context.hydrateAccountHistory();

  assert.deepEqual(Array.from(h.state.chat, message => [message.role, message.text]), [
    ['assistant', opening], ['user', 'Can you say hi?'], ['assistant', reply],
  ]);
});
