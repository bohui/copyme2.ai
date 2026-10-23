import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
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
