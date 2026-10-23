// Feed an actual saved API result through the production streaming client.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {historicalContext, historicalContextMarkup} from '../../apps/web/client/memoir/historical-news.mjs';
import {readMemoirClientSource} from '../js/helpers/memoir-source.mjs';

const {saved, replay, language} = JSON.parse(fs.readFileSync(0, 'utf8'));
const source = readMemoirClientSource();
const state = {supabase: {accessToken: 'synthetic'}, project: {id: saved.project_id}, chat: []};
const context = vm.createContext({state, historicalContext,
  conversationLanguage: () => language, simulatedLoopTrace: () => [],
  nextAssistantMessageId: () => 'current-reply', render() {}, updateStreamingAssistantMessage() {},
  refreshPrivateDraft: async () => {}, refreshStageReadiness: async () => {}, ensureRecallPreview: async () => {},
  toast: message => assert.fail(message), streamAgentTurn: async () => saved});
for (const name of ['freeRecallFinished', 'captureProjectScope', 'isCurrentProjectScope', 'currentWorkspaceMemoryFocus',
  'workspaceTurnFocus', 'markWorkspaceFocusStarted', 'readBrowserValues', 'mergeChatHistoryCopies', 'agentTurn']) {
  vm.runInContext(source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0], context);
}
const delivered = await context.agentTurn('What else could we explore?');
assert.equal(delivered.streamedMessage.streaming, false);
assert.equal(delivered.streamedMessage.historicalContext.id, saved.historical_context.id);
assert.equal(delivered.streamedMessage.historicalContext.source_url, saved.historical_context.source_url);
assert.equal(delivered.streamedMessage.historicalContext.receipt, undefined);
const markup = historicalContextMarkup(delivered.historicalContext, language);
assert.ok(markup.includes(saved.historical_context.source_url));
assert.equal(markup, historicalContextMarkup(historicalContext(replay.historical_context), language));
process.stdout.write('Saved API citation delivered and replayed by production client.\n');
