import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../../apps/web/client/memoir/client.js', import.meta.url), 'utf8');
function client(storyApi) {
  const state = { project: { id: 'project' }, supabase: { user: { id: 'owner' } }, recallStatus: { payment_required: true } };
  const timers = new Map();
  let time = 1000, id = 0;
  const context = vm.createContext({ state, storyApi, render() {}, conversationLanguage: () => 'zh-CN',
    AbortController, encodeURIComponent, Date: { now: () => time },
    setTimeout(fn, ms) { timers.set(++id, { fn, ms }); return id; },
    clearTimeout(key) { timers.delete(key); },
  });
  vm.runInContext(source.match(/async function ensureRecallPreview\([^]*?\n\}/)[0], context);
  return { state, timers, context, advance(ms) { time += ms; } };
}

test('polling reads one existing job and never submits it again', async () => {
  const requests = [];
  const fixture = client(async (url, options) => {
    requests.push({ url, method: options.method || 'GET' });
    return requests.length === 1 ? { status: 'pending', job: { id: 'job' } } : { status: 'ready', preview: {} };
  });
  await fixture.context.ensureRecallPreview();
  const poll = [...fixture.timers.values()].find(timer => timer.ms === 3000);
  poll.fn();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(requests, [{ url: '/v1/story/preview', method: 'POST' },
    { url: '/v1/story/preview/job', method: 'GET' }]);
  assert.equal(fixture.state.recallPreview.status, 'ready');
  assert.equal(fixture.timers.size, 0);
});

test('account switch suppresses both a late result and its retry timer', async () => {
  let finish;
  const fixture = client(() => new Promise(resolve => { finish = resolve; }));
  const request = fixture.context.ensureRecallPreview();
  fixture.state.supabase.user = { id: 'new-owner' };
  finish({ status: 'ready', preview: { text: 'Old owner fixture' } });
  await request;
  assert.equal(fixture.state.recallPreview.preview, undefined);
  assert.equal(fixture.timers.size, 0);
});

test('repeated polling failures stop automatic retries and allow a manual retry', async () => {
  let calls = 0;
  const fixture = client(async () => {
    if (++calls === 1) return { status: 'pending', job: { id: 'job' } };
    throw Object.assign(new Error('Test transport failure'), { status: 503 });
  });
  await fixture.context.ensureRecallPreview();
  for (let i = 0; i < 4; i++) await fixture.context.ensureRecallPreview({ poll: true });
  assert.equal(fixture.state.recallPreview.status, 'error');
  assert.equal(fixture.timers.size, 0);
  await fixture.context.ensureRecallPreview({ retry: true });
  assert.equal(calls, 6);
});

test('long-running job pauses polling and manual progress check keeps its identity', async () => {
  const requests = [];
  const fixture = client(async url => {
    requests.push(url);
    return { status: 'pending', job: { id: 'job' } };
  });
  await fixture.context.ensureRecallPreview();
  fixture.advance(900001);
  await fixture.context.ensureRecallPreview({ poll: true });
  assert.equal(fixture.state.recallPreview.status, 'paused');
  assert.equal(fixture.timers.size, 0);
  await fixture.context.ensureRecallPreview({ retry: true });
  assert.equal(requests.at(-1), '/v1/story/preview/job');
});
