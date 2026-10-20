// Replay real history API pages through the production refresh path.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {readMemoirClientSource} from './memoir-source.mjs';

const {pages, expected} = JSON.parse(readFileSync(0, 'utf8'));
const projectId = pages[0].project_id;
const source = readMemoirClientSource();
for (let refresh = 0; refresh < 2; refresh++) {
  const state = {project: {id: projectId}, supabase: {user: {id: 'owner', is_anonymous: true}},
    navigationGeneration: 1, chat: []};
  let page = 0;
  const context = vm.createContext({state, openingMessages: ['Welcome'],
    conversationMessage: () => 'Welcome', cleanAssistantText: text => text,
    persistChatHistory() {}, storyApi: async path => {
      const cursor = page ? `&cursor=${encodeURIComponent(pages[page - 1].next_cursor)}` : '';
      assert.equal(path, `/v1/user/projects/${projectId}/history?limit=100${cursor}`);
      return pages[page++];
    }});
  for (const name of ['captureProjectScope', 'isCurrentProjectScope', 'originalConversationText',
    'normalizeHistoryOpening', 'hydrateAccountHistory']) {
    vm.runInContext(source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0], context);
  }
  // A fresh page has no local cache. Repeated hydration must not duplicate turns.
  for (let hydration = 0; hydration < 2; hydration++) {
    page = 0;
    await context.hydrateAccountHistory();
    assert.deepEqual(Array.from(state.chat.slice(1), message => [message.role, message.text]), expected);
    assert.equal(page, pages.length);
  }
}
console.log('Refresh restored every user/AI exchange in order without duplicates.');
