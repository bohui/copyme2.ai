import { readMemoirClientSource } from './helpers/memoir-source.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = readMemoirClientSource();

for (const locale of ['en-AU', 'zh-CN']) test(`${locale} landing exposes and binds Google and Facebook sign-in`, () => {
  const messages = JSON.parse(fs.readFileSync(new URL(`../../apps/web/messages/${locale}.json`, import.meta.url)));
  const app = { innerHTML: '' };
  const calls = [];
  const buttons = ['google', 'facebook'].map(provider => ({
    dataset: { authProvider: provider },
    addEventListener(event, handler) { assert.equal(event, 'click'); this.click = handler; },
  }));
  const context = vm.createContext({
    state: { supabase: { accessToken: 'guest-token', user: { is_anonymous: true } } },
    MEMOIR_ROUTES: { home: '/memoir' },
    escapeHtml: String,
    translate: key => key.split('.').reduce((value, part) => value[part], messages),
    $: selector => selector === '#app' ? app : null,
    document: { querySelectorAll: selector => selector === '[data-auth-provider]' ? buttons : [] },
    supabaseOAuthSignIn: provider => calls.push(provider),
  });
  vm.runInContext(source.match(/function renderMemoirLanding\([^]*?\n\}/)[0], context);
  context.renderMemoirLanding();
  for (const provider of ['google', 'facebook']) {
    assert.match(app.innerHTML, new RegExp(`data-auth-provider="${provider}"`));
    assert.ok(app.innerHTML.includes(messages.AuthReminder[provider]));
  }
  assert.ok(app.innerHTML.includes(messages.Memoir.landing.required));
  assert.ok(!app.innerHTML.includes(messages.Memoir.landing.connected));
  buttons.forEach(button => button.click());
  assert.deepEqual(calls, ['google', 'facebook']);
  context.state.supabase.user.is_anonymous = false;
  context.renderMemoirLanding();
  assert.ok(app.innerHTML.includes(messages.Memoir.landing.connected));
});

function setup(overrides = {}) {
  const calls = [];
  const state = { supabase: { user: { id: 'guest', is_anonymous: true }, client: { auth: {
    signInWithOAuth: async options => { calls.push(['oauth', options]); return {}; },
  } } }, ...overrides };
  const context = vm.createContext({
    state, MEMOIR_ROUTES: { start: '/memoir/start' },
    window: { location: { origin: 'https://memoir.test' } },
    guestTransfer: { signIn: async provider => calls.push(['transfer', provider]) },
    translate: key => key, toast: message => calls.push(['toast', message]),
  });
  const fn = source.match(/async function supabaseOAuthSignIn\([^]*?\n\}/);
  assert.ok(fn, 'Landing needs an OAuth sign-in handler');
  vm.runInContext(fn[0], context);
  return { calls, state, context };
}

for (const provider of ['google', 'facebook']) test(`${provider} landing sign-in uses OAuth with the configured return route`, async () => {
  const { context, calls } = setup();
  await context.supabaseOAuthSignIn(provider);
  const options = JSON.parse(JSON.stringify(calls[0][1]));
  assert.deepEqual(options, { provider, options: {
    redirectTo: 'https://memoir.test/memoir/start',
    ...(provider === 'google' ? { queryParams: { prompt: 'consent select_account' } } : {}),
  } });
});

test('landing sign-in preserves an existing guest conversation through the transfer flow', async () => {
  const { context, calls } = setup({ project: { id: 'guest-story' } });
  await context.supabaseOAuthSignIn('facebook');
  assert.deepEqual(calls, [['transfer', 'facebook']]);
});

test('landing sign-in uses OAuth for a permanent account with a saved project', async () => {
  const { context, calls, state } = setup({ project: { id: 'saved-story' } });
  state.supabase.user.is_anonymous = false;
  await context.supabaseOAuthSignIn('google');
  assert.equal(calls[0][0], 'oauth');
});

test('landing sign-in leaves a guest conversation alone while a reply is in progress', async () => {
  const { context, calls } = setup({ loading: true, project: { id: 'guest-story' } });
  await context.supabaseOAuthSignIn('google');
  assert.deepEqual(calls, []);
});

test('landing OAuth waits for authentication initialization', async () => {
  let finish;
  const { context, calls } = setup({ authPromise: new Promise(resolve => { finish = resolve; }) });
  const signingIn = context.supabaseOAuthSignIn('google');
  assert.deepEqual(calls, []);
  finish();
  await signingIn;
  assert.equal(calls[0][0], 'oauth');
});

test('landing OAuth reports missing configuration and provider errors', async () => {
  const missing = setup({ supabase: null });
  await missing.context.supabaseOAuthSignIn('google');
  assert.deepEqual(missing.calls, [['toast', 'Errors.supabaseNotConfigured']]);
  const failed = setup();
  failed.state.supabase.client.auth.signInWithOAuth = async () => ({ error: { code: 'provider_disabled' } });
  await failed.context.supabaseOAuthSignIn('facebook');
  assert.deepEqual(failed.calls, [['toast', 'Errors.authFailed']]);
});
