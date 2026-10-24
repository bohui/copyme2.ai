// Feed an actual saved API result through the production streaming client.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {historicalContext, historicalContextMarkup} from '../../apps/web/client/memoir/historical-news.mjs';
import {readMemoirClientSource} from '../js/helpers/memoir-source.mjs';

const {saved, replay, language, prior, text = 'What else could we explore?'} = JSON.parse(fs.readFileSync(0, 'utf8'));
const source = readMemoirClientSource();
const state = {supabase: {accessToken: 'synthetic'}, project: {id: saved.project_id}, chat: []};
if (prior) state.chat.push({id: 'prior-reply', role: 'assistant', text: prior.reply});
const context = vm.createContext({state, historicalContext,
  conversationLanguage: () => language, simulatedLoopTrace: () => [],
  nextAssistantMessageId: () => 'current-reply', render() {}, updateStreamingAssistantMessage() {},
  refreshPrivateDraft: async () => {}, refreshStageReadiness: async () => {}, ensureRecallPreview: async () => {},
  toast: message => assert.fail(message), streamAgentTurn: async () => saved});
for (const name of ['freeRecallFinished', 'captureProjectScope', 'isCurrentProjectScope', 'currentWorkspaceMemoryFocus',
  'workspaceTurnFocus', 'markWorkspaceFocusStarted', 'readBrowserValues', 'mergeChatHistoryCopies', 'agentTurn']) {
  vm.runInContext(source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0], context);
}
const delivered = await context.agentTurn(text);
assert.equal(delivered.streamedMessage.streaming, false);
assert.equal(delivered.streamedMessage.text, saved.reply);
if (prior) assert.equal(state.chat.find(message => message.id === 'prior-reply').text, prior.reply);
const markup = historicalContextMarkup(delivered.historicalContext, language);
if (saved.historical_context) {
  assert.equal(delivered.streamedMessage.historicalContext.id, saved.historical_context.id);
  assert.equal(delivered.streamedMessage.historicalContext.source_url, saved.historical_context.source_url);
  assert.equal(delivered.streamedMessage.historicalContext.receipt, undefined);
  assert.ok(markup.includes(saved.historical_context.source_url));
} else {
  assert.equal(delivered.streamedMessage.historicalContext, null);
  assert.equal(markup, '');
  assert.equal(replay.reply, saved.reply);
}
assert.equal(markup, historicalContextMarkup(historicalContext(replay.historical_context), language));
process.stdout.write('Saved API reply and optional citation delivered and replayed by production client.\n');
