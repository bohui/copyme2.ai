import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../../apps/web/client/memoir/client.js', import.meta.url), 'utf8');

async function restore(path, cached, available) {
  const storage = new Map(cached ? [['memory-spark-project', cached]] : []);
  const requests = [], history = [];
  let resumed = false;
  const state = { supabase: null, chat: [] };
  const context = vm.createContext({ state, FALLBACK_STORY_PLANS: [],
    MEMOIR_ROUTES: { start: '/memoir/start', home: '/memoir', interview: '/memoir/interview' },
    sessionStorage: { getItem: () => null },
    localStorage: { getItem: key => storage.get(key) || null,
      setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
    window: { history: { replaceState() {} } }, currentPath: () => path,
    ensureAuth: async () => {}, guestTransfer: { complete: async () => false },
    syncProfileUiLocale: async () => {}, hydrateAccountHistory: async () => {},
    hydratePlaceJourney: async () => {}, refreshFamilyEntitlement: async () => {},
    refreshStageReadiness: async () => {}, refreshPrivateDraft: async () => {},
    persistChatHistory() {}, preserveConversationLocale: profile => profile,
    profileHasContext: () => true, render() {}, renderLanding() {}, toast() {},
    restoreChatHistory: id => { history.push(id); return []; },
    startCodexConversation: async () => { resumed = true; },
    api: async url => {
      requests.push(url);
      if (url === `/v1/projects/${available}`) return { id: available, profile: {} };
      if (url === `/v1/projects/${available}/journey`) return { active_session: null };
      throw Object.assign(new Error('Project not found'), { status: 404 });
    },
  });
  for (const name of ['captureProjectScope', 'isCurrentProjectScope', 'invalidateProjectNavigation', 'readBrowserValues', 'savedProjectStorageKey', 'readBrowserValue', 'saveBrowserValue', 'savedProjectId', 'rememberProject', 'preserveConversationLocale', 'refreshProject', 'boot']) {
    vm.runInContext(source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0], context);
  }
  await context.boot();
  return { state, storage, requests, history, resumed };
}

test('refresh restores the URL project despite a stale cached project', async () => {
  const result = await restore('/memoir/interview/project_url', 'project_stale', 'project_url');
  assert.equal(result.state.project?.id, 'project_url');
  assert.deepEqual(result.requests, ['/v1/projects/project_url', '/v1/projects/project_url/journey']);
  assert.deepEqual(result.history, ['project_url']);
  assert.equal(JSON.parse(result.storage.get('memory-spark-project')).projectId, 'project_url');
  assert.equal(result.resumed, true);
});

test('a direct interview link restores without a cached project', async () => {
  const result = await restore('/memoir/interview/project_url', null, 'project_url');
  assert.equal(result.state.project?.id, 'project_url');
  assert.equal(result.resumed, true);
});

test('an unavailable URL project does not substitute a different cached interview', async () => {
  const result = await restore('/memoir/interview/project_missing', 'project_cached', 'project_cached');
  assert.deepEqual(result.requests, ['/v1/projects/project_missing']);
  assert.equal(result.state.project, null);
  assert.equal(result.resumed, false);
});

test('routes without an explicit project still restore the saved project', async () => {
  const result = await restore('/memoir/start', 'project_cached', 'project_cached');
  assert.equal(result.state.project?.id, 'project_cached');
  assert.equal(result.resumed, true);
});

for (const status of [401, 403, 404]) test(`a cached interview with status ${status} recovers the verified project`, async () => {
  const state = { project: { id: 'project_saved' }, supabase: { user: { id: 'owner' }, accessToken: 'session' } };
  const context = vm.createContext({ state, preserveConversationLocale: profile => profile,
    mergePlaces: values => values, refreshStageReadiness() {}, refreshPrivateDraft() {},
    storyApi: async () => ({}),
    api: async (path, options) => {
      if (path === '/v1/projects/project_saved') throw Object.assign(new Error('Shell needs recovery'), { status });
      if (path === '/v1/projects') {
        assert.equal(JSON.parse(options.body).restore_project_id, 'project_saved');
        assert.equal(options.headers.Authorization, 'Bearer session');
        return { id: 'project_saved', profile: {}, requires_supabase_auth: true };
      }
      assert.equal(options.headers.Authorization, 'Bearer session');
      return { active_session: null };
    },
  });
  for (const name of ['captureProjectScope', 'isCurrentProjectScope']) vm.runInContext(source.match(new RegExp(`function ${name}\\([^]*?\\n\}`))[0], context);
  vm.runInContext(source.match(/async function refreshProject\([^]*?\n\}/)[0], context);
  await context.refreshProject();
  assert.equal(state.project.id, 'project_saved');
  assert.equal(state.project.requires_supabase_auth, true);
});
