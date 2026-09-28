import test from 'node:test';
import assert from 'node:assert/strict';
import { createGuestUsage, AUTH_REMINDER_DELAY } from '../../apps/web/client/memoir/auth-reminder.mjs';

const storage = () => {
  const values = new Map();
  return { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) };
};
test('prompts at ten minutes and remains due', () => {
  const usage = createGuestUsage(storage(), 'guest');
  assert.equal(usage.add(AUTH_REMINDER_DELAY - 1), false);
  assert.equal(usage.add(1), true);
  assert.equal(usage.add(0), true);
});
test('retains elapsed usage after reload, isolated by guest', () => {
  const store = storage();
  createGuestUsage(store, 'a').add(300000);
  assert.equal(createGuestUsage(store, 'a').add(300000), true);
  assert.equal(createGuestUsage(store, 'b').add(300000), false);
});
test('blocked storage still supports the reminder', () => {
  const usage = createGuestUsage(undefined, 'guest');
  assert.equal(usage.add(300000), false);
  assert.equal(usage.add(300000), true);
});
