import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source = fs.readFileSync(new URL('../../apps/web/client/memoir/client.js', import.meta.url), 'utf8');
function harness() {
  const durable = new Map(), tab = new Map();
  let quota = false;
  const state = {project: {id: 'a'}, projectPrincipalId: 'guest', supabase: {user: {id: 'guest'}}, chat: []};
  const context = vm.createContext({state, CHAT_HISTORY_STORAGE_PREFIX: 'chat:', assistantMessageSequence: 0,
    localStorage: {getItem: k => durable.get(k) || null, setItem: (k, v) => {if (quota) throw new Error('Quota'); durable.set(k, v);}},
    sessionStorage: {getItem: k => tab.get(k) || null, setItem: (k, v) => tab.set(k, v)}, cleanAssistantText: x => x});
  for (const name of ['chatHistoryStorageKey', 'savedProjectStorageKey', 'readBrowserValues', 'readBrowserValue',
    'mergeChatHistoryCopies', 'saveBrowserValue', 'savedProjectId', 'rememberProject', 'persistChatHistory', 'restoreChatHistory']) {
    const match = source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`));
    if (match) vm.runInContext(match[0], context);
  }
  return {context, state, durable, tab, fillQuota: () => {quota = true;}};
}

test('readable old durable history cannot hide a newer tab copy after a quota error', () => {
  const h = harness();
  h.state.chat = [{role: 'user', text: 'Older memory'}];
  h.context.persistChatHistory();
  h.fillQuota();
  h.state.chat.push({role: 'user', text: 'New accepted memory'});
  h.context.persistChatHistory();
  assert.equal(JSON.parse(h.durable.get('chat:guest:a')).length, 1);
  assert.deepEqual(Array.from(h.context.restoreChatHistory('a'), m => m.text), ['Older memory', 'New accepted memory']);
});

test('a newer durable copy from another tab is merged with this tabs newer partial reply', () => {
  const h = harness();
  h.durable.set('chat:guest:a', JSON.stringify([{cacheId: 'old', role: 'user', text: 'Older memory'},
    {cacheId: 'reply', role: 'assistant', text: 'Partial'}, {cacheId: 'new', role: 'user', text: 'Other tab memory'}]));
  h.tab.set('chat:guest:a', JSON.stringify([{cacheId: 'old', role: 'user', text: 'Older memory'},
    {cacheId: 'reply', role: 'assistant', text: 'Partial continued'}]));
  assert.deepEqual(Array.from(h.context.restoreChatHistory('a'), m => m.text),
    ['Older memory', 'Partial continued', 'Other tab memory']);
});

test('an older tab error cannot replace a newer completed reply with the same identity', () => {
  const h = harness();
  h.durable.set('chat:guest:a', JSON.stringify([{cacheId: 'reply', role: 'assistant', text: 'Saved complete reply', updatedAt: 20}]));
  h.tab.set('chat:guest:a', JSON.stringify([{cacheId: 'reply', role: 'assistant', text: 'Earlier error', updatedAt: 10}]));
  assert.equal(h.context.restoreChatHistory('a')[0].text, 'Saved complete reply');
});

test('quota fallback and cross-tab project pointers select the newest successful write', () => {
  const h = harness();
  h.context.rememberProject('a');
  h.fillQuota();
  h.context.rememberProject('b');
  assert.equal(h.context.savedProjectId(), 'b');
  h.durable.set('memory-spark-project:guest', JSON.stringify({projectId: 'c', updatedAt: Date.now() + 1000}));
  assert.equal(h.context.savedProjectId(), 'c');
});

test('history copies and project pointers remain principal and project scoped', () => {
  const h = harness();
  h.context.rememberProject('a');
  h.state.chat = [{role: 'user', text: 'Guest A'}]; h.context.persistChatHistory();
  h.state.project = {id: 'b'};
  h.state.chat = [{role: 'user', text: 'Guest B'}]; h.context.persistChatHistory();
  assert.deepEqual(Array.from(h.context.restoreChatHistory('a'), m => m.text), ['Guest A']);
  h.state.supabase.user.id = 'other';
  assert.equal(h.context.savedProjectId(), null);
  assert.equal(h.context.restoreChatHistory('a').length, 0);
  h.context.persistChatHistory(); // A stale principal cannot write its chat as the new account.
  assert.equal(h.durable.has('chat:other:b'), false);
});
