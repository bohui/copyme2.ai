import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../../apps/web/client/memoir/client.js', import.meta.url), 'utf8');

for (const method of ['GET', 'PATCH']) {
  test(`recovered project ${method} sends the current verified session`, async () => {
    const state = { project: { id: 'saved', requires_supabase_auth: true },
      supabase: { user: { id: 'owner' }, accessToken: 'owner-session' } };
    const requests = [];
    const context = vm.createContext({ state, memoirApiPath: path => path, readCookie: () => '',
      fetch: async (path, options) => {
        requests.push(options);
        return { ok: true, headers: { get: () => 'application/json' }, json: async () => ({}) };
      } });
    vm.runInContext(source.match(/async function api\([^]*?\n\}/)[0], context);
    await context.api('/v1/projects/saved', { method });
    assert.equal(requests[0].headers.Authorization, 'Bearer owner-session');
    state.supabase = { user: { id: 'other' }, accessToken: 'other-session' };
    await context.api('/v1/projects/saved', { method });
    assert.equal(requests[1].headers.Authorization, 'Bearer other-session');
    await context.api('/v1/projects', { method: 'POST', headers: { Authorization: 'Bearer explicit-session' } });
    assert.equal(requests[2].headers.Authorization, 'Bearer explicit-session');
  });
}

test('guest adapters retain their existing transport', async () => {
  const context = vm.createContext({ state: { project: { id: 'guest' }, supabase: { accessToken: 'session' } },
    memoirApiPath: path => path,
    fetch: async (_path, options) => {
      assert.equal(options.headers.Authorization, undefined);
      return { ok: true, headers: { get: () => '' }, json: async () => ({}) };
    } });
  vm.runInContext(source.match(/async function api\([^]*?\n\}/)[0], context);
  await context.api('/v1/projects/guest');
});

test('fresh project creation after recovery does not inherit its prior adapter token', async () => {
  const context = vm.createContext({ state: { project: { requires_supabase_auth: true },
      supabase: { accessToken: 'owner-session' } }, memoirApiPath: path => path, readCookie: () => '',
    fetch: async (_path, options) => {
      assert.equal(options.headers.Authorization, undefined);
      return { ok: true, headers: { get: () => '' }, json: async () => ({}) };
    } });
  vm.runInContext(source.match(/async function api\([^]*?\n\}/)[0], context);
  await context.api('/v1/projects', { method: 'POST' });
});
