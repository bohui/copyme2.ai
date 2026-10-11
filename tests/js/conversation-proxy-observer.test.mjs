import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../../scripts/smoke_conversation_proxy.py', import.meta.url), 'utf8');
const observer = source.match(/OBSERVE = r"""([^]*?)"""/)[1];

test('proxy smoke observes native bytes before UI consumption, without a competing cloned reader', async () => {
  const bytes = new TextEncoder().encode('{"type":"text_delta","text":"你好"}\n{"type":"conversation_saved","data":{}}\n');
  const reader = {read: async () => ({value: bytes, done: false})};
  const response = {status: 200, headers: {get: () => 'application/x-ndjson'},
    body: {getReader: () => reader}};
  const context = vm.createContext({window: {fetch: async () => response}, performance, TextDecoder,
    MutationObserver: class {observe() {}}, document: {}, setTimeout});
  vm.runInContext(observer, context);
  const received = await context.window.fetch('/api/v1/memoir/agent/turn', {});
  assert.equal(received, response, 'The real response must not be replaced');
  const packet = await received.body.getReader().read();
  assert.equal(packet.value, bytes, 'Do not alter or re-chunk provider bytes');
  assert.ok(context.window.proxySmoke[0].events.text_delta >= 0);
  assert.ok(context.window.proxySmoke[0].events.conversation_saved >= 0,
    'Save must be observed before the UI can consume it and enable Send');
  assert.equal(context.window.proxySmoke[0].observerFailed, undefined);
});
