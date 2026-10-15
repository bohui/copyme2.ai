import {readMemoirClientSource} from './helpers/memoir-source.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';

const source = readMemoirClientSource();
const extract = name => source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0];

function harness() {
  const requests = [];
  const timers = [];
  const state = {project:{id:'p'}, supabase:{accessToken:'synthetic',user:{id:'owner'}},
    stageReadiness:{}, chat:[]};
  const context = vm.createContext({state, AbortController, setTimeout:callback => timers.push(callback), workspaceTurnFocus:() => null,
    markWorkspaceFocusStarted() {}, conversationLanguage:() => 'en-AU', simulatedLoopTrace:() => [],
    refreshPrivateDraft() {}, applyCommittedConversationLocale:async () => {},
    render() {}, toast: message => {throw new Error(message);},
    nextAssistantMessageId:() => 'reply', updateStreamingAssistantMessage() {},
    storyApi:() => new Promise(resolve => requests.push(resolve)),
    streamAgentTurn: async () => ({conversation_saved:true, reply:'Saved reply.'})});
  for (const name of ['captureProjectScope','isCurrentProjectScope','refreshStageReadiness','agentTurn']) {
    vm.runInContext(extract(name), context);
  }
  return {context,state,requests,timers};
}

test('a canonical saved reply refreshes rings without a workspace update or private draft', async () => {
  const h = harness();
  const result = await h.context.agentTurn('A memory.');
  assert.equal(result.reply, 'Saved reply.');
  assert.equal(h.requests.length, 1);
  h.requests[0]({stages:{childhood:{percent:10,color:'red',word_equivalents:100}}});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.state.stageReadiness.childhood.percent, 10);
});

test('a slower initial read cannot replace newer same-project stage totals', async () => {
  const h = harness();
  const old = h.context.refreshStageReadiness();
  const fresh = h.context.refreshStageReadiness();
  h.requests[1]({stages:{midlife:{percent:30,color:'amber',word_equivalents:300}}});
  await fresh;
  h.requests[0]({stages:{}});
  await old;
  assert.equal(h.state.stageReadiness.midlife?.percent, 30);
});

test('the streamed save receipt refreshes before the optional workspace tail finishes', async () => {
  const h = harness();
  let finish;
  h.context.streamAgentTurn = async (_text, _delta, onEvent) => {
    await onEvent({type:'conversation_saved',data:{}});
    return new Promise(resolve => {finish = resolve;});
  };
  const turn = h.context.agentTurn('A streamed memory.');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.requests.length, 1);
  h.requests[0]({stages:{childhood:{percent:10,color:'red',word_equivalents:100}}});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.state.stageReadiness.childhood.percent, 10);
  finish({conversation_saved:true,reply:'Saved reply.'});
  await turn;
  assert.equal(h.requests.length, 2);
  h.requests[1]({stages:{childhood:{percent:10,color:'red',word_equivalents:100}}});
});

for (const transition of ['project','owner','navigation']) test(`late readiness cannot cross a ${transition} transition`, async () => {
  const h = harness();
  const pending = h.context.refreshStageReadiness();
  if (transition === 'project') h.state.project = {id:'other'};
  if (transition === 'owner') h.state.supabase.user.id = 'other';
  if (transition === 'navigation') h.state.navigationGeneration = 1;
  h.requests[0]({stages:{childhood:{percent:50}}});
  await pending;
  assert.deepEqual(h.state.stageReadiness, {});
});

test('pending extraction refreshes boundedly and stops when stage evidence is ready', async () => {
  const h = harness();
  const pending = h.context.refreshStageReadiness();
  h.requests[0]({stages:{}, pending:true});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.timers.length, 1);
  h.timers.shift()();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.requests.length, 2);
  h.requests[1]({stages:{childhood:{percent:15.7,color:'red',word_equivalents:157}}, pending:false});
  await pending;
  assert.equal(h.state.stageReadiness.childhood.percent, 15.7);
  assert.equal(h.timers.length, 0);
});

test('a queued extraction refresh stops on navigation and cannot revive old progress', async () => {
  const h = harness();
  const pending = h.context.refreshStageReadiness();
  h.requests[0]({stages:{}, pending:true});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.timers.length, 1);
  h.state.navigationGeneration = 1;
  h.timers.shift()();
  await pending;
  assert.equal(h.requests.length, 1);
});

test('a persistently pending extractor does not poll indefinitely', async () => {
  const h = harness();
  const pending = h.context.refreshStageReadiness({attempt:15});
  h.requests[0]({stages:{}, pending:true});
  await pending;
  assert.equal(h.timers.length, 0);
});
