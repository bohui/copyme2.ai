import test from 'node:test';
import assert from 'node:assert/strict';
import { createGuestConversationTransfer, GUEST_TRANSFER_KEY } from '../../apps/web/client/memoir/guest-conversation-transfer.mjs';

function setup() {
  const values = new Map();
  const storage = { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) };
  const calls = [];
  const account = { user: { id: 'guest', is_anonymous: true }, client: { auth: {
    getSession: async () => ({ data: { session: { access_token: 'guest-token', refresh_token: 'guest-refresh', user: account.user } } }),
    setSession: async session => { assert.equal(session.refresh_token, 'guest-refresh'); account.user = { id: 'guest', is_anonymous: true }; return {}; },
    signInWithOAuth: async options => { calls.push(['oauth', options]); assert.ok(storage.getItem(GUEST_TRANSFER_KEY)); return {}; },
  } } };
  const options = {
    getAuth: () => account, storage, redirectTo: 'https://memoir.test/memoir/interview/project',
    getConversation: () => ({ project_id: 'project', messages: [{ role: 'user', text: 'My childhood' }],
      workspace_profile: { preferred_language: 'zh-CN', memory_places: [{ place: 'Anshan', pictures: [{ id: 'photo' }] }] }, ui_locale: 'zh-CN' }),
    api: async (path, request) => { calls.push([path, JSON.parse(request.body)]); return {}; },
  };
  return { account, options, calls, storage, transfer: createGuestConversationTransfer(options) };
}

test('prepare under guest, sign in, redeem under permanent user after reload', async () => {
  const { account, calls, transfer, options, storage } = setup();
  await transfer.signIn('google');
  assert.equal(calls[0][0], '/v1/user/conversation-transfer');
  assert.match(calls[0][1].token, /^[a-f0-9]{64}$/);
  assert.equal(calls[0][1].messages[0].text, 'My childhood');
  assert.equal(calls[0][1].workspace_profile.memory_places[0].pictures[0].id, 'photo');
  assert.equal(calls[0][1].ui_locale, 'zh-CN');
  assert.equal('guestSession' in calls[0][1], false);
  assert.equal(calls[1][1].options.queryParams.prompt, 'consent select_account');
  assert.equal(await transfer.complete(), false);
  account.user = { id: 'existing', is_anonymous: false };
  const reloaded = createGuestConversationTransfer(options);
  assert.equal(await reloaded.complete(), true);
  assert.equal(calls[2][0], '/v1/user/conversation-transfer/attach');
  assert.equal(calls[2][1].token, calls[0][1].token);
  assert.equal(storage.getItem(GUEST_TRANSFER_KEY), undefined);
  assert.equal(await reloaded.complete(), false);
});

test('failed attachment retains its capability for an idempotent retry', async () => {
  const { account, options, transfer, storage } = setup();
  await transfer.signIn('google');
  const saved = storage.getItem(GUEST_TRANSFER_KEY);
  account.user = { id: 'existing', is_anonymous: false };
  const retry = createGuestConversationTransfer({ ...options, api: async () => { throw new Error('offline'); } });
  await assert.rejects(retry.complete());
  assert.equal(storage.getItem(GUEST_TRANSFER_KEY), saved);
  assert.equal(await transfer.complete(), true);
});

test('unavailable storage or preparation blocks OAuth, preserving the guest', async () => {
  const { options, calls } = setup();
  const blocked = createGuestConversationTransfer({ ...options, storage: { setItem() { throw new Error('blocked'); } } });
  await assert.rejects(blocked.signIn('google'));
  assert.deepEqual(calls, []);
  const offline = createGuestConversationTransfer({ ...options, api: async () => { throw new Error('offline'); } });
  await assert.rejects(offline.signIn('google'));
  assert.deepEqual(calls, []);
});

test('canceling merge for a different account removes the pending transfer', async () => {
  const { transfer, storage } = setup();
  await transfer.signIn('google');
  transfer.cancel();
  assert.equal(storage.getItem(GUEST_TRANSFER_KEY), undefined);
});

test('failed merge can restore the original guest session without losing history', async () => {
  const { transfer, account, storage } = setup();
  await transfer.signIn('google');
  account.user = { id: 'existing', is_anonymous: false };
  await transfer.restoreGuest();
  assert.equal(account.user.id, 'guest');
  assert.equal(storage.getItem(GUEST_TRANSFER_KEY), undefined);
});

test('workspace hydration must finish before the recovery session is discarded', async () => {
  const { options, account, storage } = setup();
  const transfer = createGuestConversationTransfer({ ...options, onMerged: async () => { throw new Error('profile hydration offline'); } });
  await transfer.signIn('google');
  account.user = { id: 'existing', is_anonymous: false };
  await assert.rejects(transfer.complete());
  assert.ok(storage.getItem(GUEST_TRANSFER_KEY));
  assert.equal(await createGuestConversationTransfer(options).complete(), true);
});
