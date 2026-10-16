import { readMemoirClientSource } from './helpers/memoir-source.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';

const source = readMemoirClientSource();
function client(storyApi) {
  const state = { project: { id: 'project' }, supabase: { user: { id: 'owner' } },
    recallStatus: { rounds_completed: 20, free_rounds: 20, payment_required: true } };
  const timers = new Map();
  let time = 1000, id = 0;
  const context = vm.createContext({ state, storyApi, render() {}, conversationLanguage: () => 'zh-CN',
    AbortController, encodeURIComponent, Date: { now: () => time },
    setTimeout(fn, ms) { timers.set(++id, { fn, ms }); return id; },
    clearTimeout(key) { timers.delete(key); },
  });
  vm.runInContext(source.match(/function freeRecallFinished\([^]*?\n\}/)[0], context);
  vm.runInContext(source.match(/async function ensureRecallPreview\([^]*?\n\}/)[0], context);
  return { state, timers, context, advance(ms) { time += ms; } };
}

test('the twentieth completed round generates a sample for paid accounts too', async () => {
  const requests = [];
  const fixture = client(async url => {
    requests.push(url);
    return {status: 'ready', preview: {text: 'A supported sample.'}};
  });
  fixture.state.recallStatus.payment_required = false;
  fixture.state.recallStatus.paid = true;
  await fixture.context.ensureRecallPreview();
  assert.deepEqual(requests, ['/v1/story/preview']);
  assert.equal(fixture.state.recallPreview.status, 'ready');
});

test('nineteen completed rounds do not request the free sample', async () => {
  const fixture = client(async () => assert.fail('Sample requested before the twentieth round'));
  fixture.state.recallStatus.rounds_completed = 19;
  await fixture.context.ensureRecallPreview();
  assert.equal(fixture.state.recallPreview, undefined);
});

test('paid storytellers see their completed sample without another package offer', async () => {
  const fixture = client(async () => ({status: 'ready', preview: {title: 'A memory', text: 'My sample.'}}));
  fixture.state.recallStatus.payment_required = false;
  await fixture.context.ensureRecallPreview();
  Object.assign(fixture.context, {escapeHtml: String, translate: key => key, formatText: String});
  vm.runInContext(source.match(/function recallPackagePrompt\([^]*?\n\}/)[0], fixture.context);
  const markup = fixture.context.recallPackagePrompt();
  assert.match(markup, /My sample\./);
  assert.doesNotMatch(markup, /recall-package-prompt/);
});

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
