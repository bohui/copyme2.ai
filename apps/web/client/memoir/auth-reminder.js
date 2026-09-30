import { translate } from '../i18n.js';
import { createGuestUsage } from './auth-reminder.mjs';

export function createAuthReminder({ getAuth, busy }) {
  let usage, userId, due = false, prompted = false;
  let last = performance.now();
  let visible = document.visibilityState === 'visible';
  let refreshing = false;
  const callbackParams = new URLSearchParams(window.location.search);
  const callbackError = callbackParams.get('error_code') || callbackParams.get('error');
  const t = (key) => translate(`AuthReminder.${key}`);

  function open() {
    if (!getAuth()?.user?.is_anonymous || document.querySelector('[data-auth-reminder-dialog]')) return;
    const dialog = document.createElement('dialog');
    dialog.className = 'profile-settings';
    dialog.dataset.authReminderDialog = '';
    dialog.setAttribute('aria-labelledby', 'auth-reminder-title');
    // All translated copy is assigned as text, never interpolated into HTML.
    dialog.innerHTML = `<form><header><h2 id="auth-reminder-title"></h2><button type="button" data-close>×</button></header><p data-intro></p><fieldset><label><span data-email-label></span><input type="email" name="email" autocomplete="email" required></label><button class="button button-primary" type="submit" data-email></button><div class="story-auth-actions"><button class="button button-secondary" type="button" data-provider="google"></button><button class="button button-secondary" type="button" data-provider="facebook"></button></div></fieldset><p role="status" aria-live="polite"></p></form>`;
    dialog.querySelector('h2').textContent = t('title');
    dialog.querySelector('[data-close]').setAttribute('aria-label', t('later'));
    dialog.querySelector('[data-intro]').textContent = t('message');
    if (callbackError) dialog.querySelector('[role=status]').textContent = t(callbackError === 'identity_already_exists' ? 'identityExists' : 'error');
    dialog.querySelector('[data-email-label]').textContent = t('email');
    dialog.querySelector('[data-email]').textContent = t('continueEmail');
    for (const button of dialog.querySelectorAll('[data-provider]')) button.textContent = t(button.dataset.provider);
    dialog.querySelector('[data-close]').onclick = () => dialog.close();
    dialog.addEventListener('close', () => dialog.remove(), { once: true });
    const run = async (provider) => {
      const fieldset = dialog.querySelector('fieldset');
      const status = dialog.querySelector('[role=status]');
      fieldset.disabled = true;
      try {
        const auth = getAuth()?.client?.auth;
        if (!auth) throw new Error('Unavailable');
        const redirectTo = window.location.origin + window.location.pathname;
        const result = provider
          ? await auth.linkIdentity({ provider, options: { redirectTo } })
          : await auth.updateUser({ email: dialog.querySelector('input').value.trim() }, { emailRedirectTo: redirectTo });
        if (result.error) throw result.error;
        if (result.data?.user && result.data.user.id === getAuth()?.user?.id) {
          getAuth().user = result.data.user;
          tick();
        }
        status.textContent = t(provider ? 'redirecting' : 'checkEmail');
      } catch {
        status.textContent = t('error');
      } finally { fieldset.disabled = false; }
    };
    dialog.querySelector('form').onsubmit = (event) => { event.preventDefault(); run(); };
    for (const button of dialog.querySelectorAll('[data-provider]')) button.onclick = () => run(button.dataset.provider);
    document.body.append(dialog);
    dialog.showModal();
  }

  function mount() {
    const guest = getAuth()?.user?.is_anonymous;
    if (!guest) {
      document.querySelectorAll('[data-auth-reminder]').forEach(node => node.remove());
      document.querySelectorAll('[data-auth-reminder-dialog]').forEach(dialog => { dialog.close(); dialog.remove(); });
      return;
    }
    const chat = document.querySelector('#chat-scroll');
    if (!due || !chat || document.querySelector('[data-auth-reminder]')) return;
    const reminder = document.createElement('aside');
    reminder.dataset.authReminder = '';
    reminder.className = 'auth-history-reminder';
    reminder.setAttribute('aria-live', 'polite');
    const message = document.createElement('p');
    message.textContent = t('message');
    const button = document.createElement('button');
    button.className = 'button button-secondary button-small';
    button.textContent = t('title');
    button.onclick = open;
    reminder.append(message, button);
    chat.append(reminder);
  }

  function tick() {
    const now = performance.now();
    const user = getAuth()?.user;
    if (user?.is_anonymous) {
      if (!usage || userId !== user.id) {
        userId = user.id;
        let storage;
        try { storage = localStorage; } catch { /* memory fallback */ }
        usage = createGuestUsage(storage, `memory-spark-guest-usage:${userId || 'test'}`);
        prompted = false;
        last = now;
      }
      due = usage.add(visible ? now - last : 0);
      mount();
      if (due && !prompted && document.visibilityState === 'visible' && !busy() && !document.querySelector('dialog[open]')) {
        prompted = true;
        open();
      }
    } else { usage = null; due = false; prompted = false; mount(); }
    last = now;
    visible = document.visibilityState === 'visible';
  }
  // Email confirmation may complete in another tab while this page still has
  // the anonymous user cached. Verify on return without switching accounts.
  async function refreshUser() {
    const account = getAuth();
    if (refreshing || !account?.user?.is_anonymous || !account.client?.auth?.getUser) return;
    refreshing = true;
    try {
      const { data, error } = await account.client.auth.getUser();
      if (!error && data?.user && getAuth() === account && data.user.id === account.user?.id) {
        account.user = data.user;
        tick();
      }
    } catch { /* Keep the guest reminder when verification is unavailable. */ }
    finally { refreshing = false; }
  }
  window.addEventListener('focus', refreshUser);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') refreshUser();
  });
  setInterval(tick, 1000);
  document.addEventListener('visibilitychange', tick);
  window.addEventListener('pagehide', tick);
  return { mount, tick };
}
