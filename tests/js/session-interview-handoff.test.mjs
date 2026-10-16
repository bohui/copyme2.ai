import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readMemoirClientSource} from './helpers/memoir-source.mjs';

const source = readMemoirClientSource();

function harness({followUps = 3, turns = 4, accepted = false} = {}) {
  const input = {value: 'A new memory'};
  const requests = [], generations = [], notices = [];
  const pending = accepted ? {id: 'accepted-turn', accepted: true} : null;
  const state = {project: {id: 'project'}, supabase: {user: {id: 'owner'}}, chat: [],
    dictationStatus: 'off', audioTranscript: '', attachments: [], profileIntakePending: false,
    session: {id: 'session', turns: Array.from({length: turns}, () => ({})), follow_ups_used: followUps},
    photoTurns: {pending: () => pending}};
  const context = vm.createContext({state, $: () => input, profile: () => ({}),
    captureProjectScope: () => ({}), isCurrentProjectScope: () => true,
    conversationLanguage: () => 'en-AU', conversationMessage: () => 'Fallback', translate: key => key,
    conversationScroll: {follow() {}}, render() {}, refreshFamilyContext() {},
    ensureMemorySession: async () => state.session, memoryFollowUpPrompt: () => 'Fallback',
    api: async path => {requests.push(path); return state.session;},
    agentTurn: async (...args) => {generations.push(args); return {reply: 'Who joined you?'};},
    streamAssistantMessage: async () => {}, toast: message => notices.push(message)});
  vm.runInContext(source.match(/async function sendChatMessage\([^]*?\n\}/)[0], context);
  return {context, state, input, requests, generations, notices, pending};
}

for (const [followUps, turns] of [[3, 4], [2, 5]]) {
  test(`an exhausted optional session (${followUps} follow-ups, ${turns} turns) does not reject a continuing interview`, async () => {
    const h = harness({followUps, turns});
    await h.context.sendChatMessage();
    assert.deepEqual(h.requests, [], 'Do not submit an answer the optional adapter must reject');
    assert.equal(h.generations.length, 1);
    assert.equal(h.generations[0][5], 'A new memory');
    assert.equal(h.state.session.id, 'session', 'Keep its saved cues and avoid recreating the exhausted session');
  });
}

test('an available optional session still receives the answer', async () => {
  const h = harness({followUps: 2, turns: 3});
  await h.context.sendChatMessage();
  assert.deepEqual(h.requests, ['/v1/memory-sessions/session/answers']);
  assert.equal(h.generations.length, 1);
});

test('an accepted unanswered turn keeps its retry identity and leaves a new draft untouched', async () => {
  const h = harness({accepted: true});
  await h.context.sendChatMessage();
  assert.deepEqual(h.requests, []);
  assert.equal(h.generations.length, 0);
  assert.equal(h.input.value, 'A new memory');
  assert.equal(h.state.chat.length, 0);
  assert.equal(h.state.photoTurns.pending().id, 'accepted-turn');
  assert.deepEqual(h.notices, ['Memoir.story.retryTurn']);
  vm.runInContext(source.match(/async function retryInterviewTurn\([^]*?\n\}/)[0], h.context);
  await h.context.retryInterviewTurn();
  assert.equal(h.state.audioTranscript, 'A new memory', 'Keep the draft through the retry render');
  assert.equal(h.generations[0][8].retry.id, 'accepted-turn');
});

test('other conversation actions cannot replace an accepted unanswered turn', async () => {
  const h = harness({accepted: true});
  h.context.simulatedLoopTrace = () => [];
  h.context.workspaceTurnFocus = () => null;
  h.state.supabase.accessToken = 'synthetic';
  h.state.photoTurns.prepare = () => {throw new Error('The accepted retry would be replaced');};
  vm.runInContext(source.match(/async function agentTurn\([^]*?\n\}/)[0], h.context);
  await assert.rejects(h.context.agentTurn('Continue with a different memory'), /Memoir.story.retryTurn/);
  assert.equal(h.state.photoTurns.pending().id, 'accepted-turn');
});
