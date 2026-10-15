import {readMemoirClientSource} from './helpers/memoir-source.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';

const source = readMemoirClientSource();
const extract = name => source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0];
const settle = () => new Promise(resolve => setImmediate(resolve));
const stage = (percent, pending = false) => ({stages:{childhood:{percent,
  color:percent >= 50 ? 'green' : 'red', word_equivalents:percent * 10}}, pending});
const fenceError = (status = 409) => Object.assign(new Error('Read revision changed'), {
  status, code:status === 409 ? 'LIFETIME_READ_STALE' : 'LIFETIME_READ_UNAVAILABLE'});

function harness() {
  let now = 0, sequence = 0;
  const requests = [], timers = new Map(), renders = [];
  const state = {project:{id:'p'}, supabase:{accessToken:'synthetic',user:{id:'owner'}},
    stageReadiness:{}, chat:[]};
  const context = vm.createContext({state, AbortController, Date:{now:() => now},
    setTimeout:(callback, delay) => {const id = ++sequence; timers.set(id, {callback, at:now + delay}); return id;},
    clearTimeout:id => timers.delete(id), workspaceTurnFocus:() => null,
    markWorkspaceFocusStarted() {}, conversationLanguage:() => 'en-AU', simulatedLoopTrace:() => [],
    refreshPrivateDraft() {}, applyCommittedConversationLocale:async () => {}, persistChatHistory() {},
    render:() => renders.push(JSON.parse(JSON.stringify(state.stageReadiness))),
    toast:message => {throw new Error(message);},
    nextAssistantMessageId:() => 'reply', updateStreamingAssistantMessage() {},
    storyApi:(_path, options = {}) => new Promise((resolve, reject) => {
      const response = value => {response.settled = true; resolve(value);};
      response.reject = error => {response.settled = true; reject(error);};
      response.signal = options.signal;
      requests.push(response);
    }),
    streamAgentTurn:async () => ({conversation_saved:true, reply:'Saved reply.'})});
  for (const name of ['captureProjectScope','isCurrentProjectScope','invalidateProjectNavigation',
    'refreshStageReadiness','agentTurn']) vm.runInContext(extract(name), context);
  async function nextTimer() {
    const next = [...timers].sort((a,b) => a[1].at - b[1].at)[0];
    assert.ok(next, 'Recovery must schedule another bounded read');
    now = next[1].at; timers.delete(next[0]); next[1].callback(); await settle();
  }
  return {context,state,requests,timers,renders,nextTimer,now:() => now};
}

test('a canonical saved reply refreshes rings without a workspace update or private draft', async () => {
  const h = harness();
  const result = await h.context.agentTurn('A memory.');
  assert.equal(result.reply, 'Saved reply.');
  assert.equal(h.requests.length, 1);
  h.requests[0](stage(10)); await settle();
  assert.equal(h.state.stageReadiness.childhood.percent, 10);
});

test('a refresh during an in-flight read coalesces and never paints its older snapshot', async () => {
  const h = harness();
  const old = h.context.refreshStageReadiness();
  const fresh = h.context.refreshStageReadiness();
  assert.equal(h.requests.length, 1, 'Only one readiness read may be in flight');
  h.requests[0](stage(10)); await settle();
  assert.equal(h.renders.length, 0, 'A read preceding the newer save is not painted');
  assert.equal(h.requests.length, 2);
  h.requests[1](stage(30)); await Promise.all([old,fresh]);
  assert.deepEqual(h.renders.map(value => value.childhood.percent), [30]);
});

test('the streamed save receipt refreshes before the optional workspace tail finishes', async () => {
  const h = harness();
  let finish;
  h.context.streamAgentTurn = async (_text, _delta, onEvent) => {
    await onEvent({type:'conversation_saved',data:{}});
    return new Promise(resolve => {finish = resolve;});
  };
  const turn = h.context.agentTurn('A streamed memory.'); await settle();
  assert.equal(h.requests.length, 1);
  h.requests[0](stage(10)); await settle();
  assert.equal(h.state.stageReadiness.childhood.percent, 10);
  finish({conversation_saved:true,reply:'Saved reply.'}); await turn;
  assert.equal(h.requests.length, 2);
  h.requests[1](stage(10)); await settle();
});

for (const transition of ['project','owner','navigation']) test(`late readiness cannot cross a ${transition} transition`, async () => {
  const h = harness();
  const pending = h.context.refreshStageReadiness();
  if (transition === 'project') h.state.project = {id:'other'};
  if (transition === 'owner') h.state.supabase.user.id = 'other';
  if (transition === 'navigation') h.context.invalidateProjectNavigation();
  h.requests[0](stage(50)); await pending;
  assert.deepEqual(h.state.stageReadiness, {});
  assert.equal(h.timers.size, 0);
});

test('pending extraction refreshes when stage evidence becomes ready', async () => {
  const h = harness();
  const pending = h.context.refreshStageReadiness();
  h.requests[0](stage(0,true)); await settle();
  await h.nextTimer();
  assert.equal(h.requests.length, 2);
  h.requests[1](stage(15.7)); await pending;
  assert.equal(h.state.stageReadiness.childhood.percent, 15.7);
  assert.equal(h.timers.size, 0);
});

test('a supported 240-second extraction is observed without another turn or reload', async () => {
  const h = harness();
  const pending = h.context.refreshStageReadiness();
  for (let index = 0; index < 40; index++) {
    h.requests[index](stage(h.now() >= 240_000 ? 50 : 0, h.now() < 240_000)); await settle();
    if (!h.timers.size) break;
    await h.nextTimer();
  }
  await pending;
  assert.equal(h.state.stageReadiness.childhood.percent, 50);
  assert.ok(h.now() >= 240_000 && h.now() <= 300_000);
  assert.ok(h.requests.length <= 25, 'Backoff must avoid busy polling');
  assert.equal(h.timers.size, 0);
});

test('a failed final-save read preserves recovery from the older healthy streamed-save poll', async () => {
  const h = harness();
  const streamed = h.context.refreshStageReadiness();
  h.requests[0](stage(10,true)); await settle();
  const finalSave = h.context.refreshStageReadiness(); await settle();
  assert.equal(h.requests.length, 2);
  h.requests[1].reject(fenceError(503)); await settle();
  assert.equal(h.state.stageReadiness.childhood.percent, 10);
  await h.nextTimer();
  assert.equal(h.requests.length, 3, 'A failed newer read must not discard recovery');
  h.requests[2](stage(50)); await Promise.all([streamed,finalSave]);
  assert.equal(h.state.stageReadiness.childhood.percent, 50);
  assert.equal(h.timers.size, 0);
});

for (const status of [409,503]) test(`a revision-fenced ${status} read retries without erasing the last good ring`, async () => {
  const h = harness();
  h.state.stageReadiness = stage(10).stages;
  const pending = h.context.refreshStageReadiness();
  h.requests[0].reject(fenceError(status)); await settle();
  assert.equal(h.state.stageReadiness.childhood.percent, 10);
  await h.nextTimer();
  h.requests[1].reject(fenceError(status)); await settle();
  await h.nextTimer();
  h.requests[2](stage(50)); await pending;
  assert.deepEqual(h.renders.map(value => value.childhood.percent), [50]);
  assert.equal(h.timers.size, 0);
});

test('navigation aborts a queued recovery timer immediately', async () => {
  const h = harness();
  const pending = h.context.refreshStageReadiness();
  h.requests[0](stage(0,true)); await settle();
  h.context.invalidateProjectNavigation(); await settle();
  assert.equal(h.timers.size, 0);
  await pending;
  assert.equal(h.requests.length, 1);
});

test('navigation aborts an in-flight read; a later project cannot paint its late result', async () => {
  const h = harness();
  const old = h.context.refreshStageReadiness();
  h.context.invalidateProjectNavigation();
  assert.equal(h.requests[0].signal?.aborted, true);
  h.state.project = {id:'other'};
  const fresh = h.context.refreshStageReadiness();
  h.requests[1](stage(30)); await fresh;
  h.requests[0](stage(10)); await old;
  assert.deepEqual(h.renders.map(value => value.childhood.percent), [30]);
  assert.equal(h.timers.size, 0);
});

test('a hung read is aborted and retried; its late response cannot overwrite fresh progress', async () => {
  const h = harness();
  const pending = h.context.refreshStageReadiness();
  await h.nextTimer();
  assert.equal(h.requests[0].signal?.aborted, true);
  assert.ok(h.now() <= 10_000, 'A hung read cannot consume the extraction recovery window');
  await h.nextTimer();
  h.requests[1](stage(50)); await pending;
  h.requests[0](stage(10)); await settle();
  assert.deepEqual(h.renders.map(value => value.childhood.percent), [50]);
});

test('persistent pending work or transient failures stop at a finite five-minute deadline', async () => {
  for (const failure of [false,true]) {
    const h = harness();
    const pending = h.context.refreshStageReadiness();
    let index = 0;
    while (index < 40) {
      if (h.requests[index]) {
        if (failure) h.requests[index].reject(fenceError());
        else h.requests[index](stage(0,true));
        index++; await settle();
      }
      if (!h.timers.size) break;
      await h.nextTimer();
    }
    await pending;
    assert.ok(h.now() >= 240_000 && h.now() <= 300_000);
    assert.ok(h.requests.length <= 25);
    assert.equal(h.timers.size, 0);
  }
});

test('permanent authentication failure stops recovery without discarding saved progress', async () => {
  const h = harness();
  h.state.stageReadiness = stage(10).stages;
  const pending = h.context.refreshStageReadiness();
  h.requests[0].reject(Object.assign(new Error('Session unavailable'), {status:401}));
  await pending;
  assert.equal(h.state.stageReadiness.childhood.percent, 10);
  assert.equal(h.timers.size, 0);
});

test('a later explicit save receives a full supported recovery window', async () => {
  const h = harness();
  const first = h.context.refreshStageReadiness();
  let index = 0;
  while (h.now() < 240_000) {
    h.requests[index++](stage(0,true)); await settle();
    await h.nextTimer();
  }
  const savedAt = h.now();
  const later = h.context.refreshStageReadiness();
  for (; index < 50; index++) {
    const ready = h.now() >= savedAt + 240_000;
    h.requests[index](stage(ready ? 50 : 0, !ready)); await settle();
    if (!h.timers.size) break;
    if (h.requests.length <= index + 1) await h.nextTimer();
  }
  await Promise.all([first,later]);
  assert.equal(h.state.stageReadiness.childhood.percent, 50);
  assert.ok(h.now() >= savedAt + 240_000 && h.now() <= savedAt + 300_000);
  assert.equal(h.timers.size, 0);
});
