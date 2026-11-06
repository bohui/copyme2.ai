import test from 'node:test';
import assert from 'node:assert/strict';
import { createGuestUsage, AUTH_REMINDER_DELAY } from '../../apps/web/client/memoir/auth-reminder.mjs';
import { createAuthReminder } from '../../apps/web/client/memoir/auth-reminder.js';

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

test('an idle guest returning to the tab does not fetch their auth user', async t => {
  const previous={window:globalThis.window,document:globalThis.document,setInterval:globalThis.setInterval};
  t.after(()=>Object.assign(globalThis,previous));
  const listeners={};
  const on=(name,callback)=>{(listeners[name] ||= []).push(callback);};
  Object.assign(globalThis,{window:{location:{search:'',hash:''},addEventListener:on},
    document:{visibilityState:'visible',addEventListener:on,querySelector:()=>null},setInterval:()=>{}});
  let reads=0;
  const account={user:{id:'guest',is_anonymous:true},client:{auth:{getUser:async()=>{reads++;return {data:{user:account.user}};}}}};
  createAuthReminder({getAuth:()=>account,busy:()=>false});
  for (const event of ['focus','visibilitychange']) for (const callback of listeners[event] || []) await callback();
  assert.equal(reads,0);
});
