import { translate } from '../i18n.js';
import { createGuestUsage } from './auth-reminder.mjs';
import { linkSocialIdentity } from './social-auth.mjs';

export function createAuthReminder({ getAuth, busy, signInExisting, cancelTransfer, onUserChanged }) {
  let usage, userId, due = false, prompted = false;
  let last = performance.now();
  let visible = document.visibilityState === 'visible';
  let refreshing = false;
  const callbackParams = new URLSearchParams(window.location.search);
  const callbackHash = new URLSearchParams(window.location.hash.slice(1));
  const callbackError = callbackParams.get('error_code') || callbackHash.get('error_code') || callbackParams.get('error') || callbackHash.get('error');
  const t = (key) => translate(`AuthReminder.${key}`);
  const errorMessage = (code) => t(code === 'identity_already_exists' ? 'identityExists' : 'error');
  let conflict = callbackError === 'identity_already_exists';
  let conflictProvider = 'google';
  try { conflictProvider = sessionStorage.getItem('memoir-link-provider') || 'google'; } catch { /* use Google */ }
  if (!['google', 'facebook'].includes(conflictProvider)) conflictProvider = 'google';

  function refreshCopy(targetDialog = document.querySelector('[data-auth-reminder-dialog]')) {
    const reminder = document.querySelector('[data-auth-reminder]');
    reminder?.querySelector('[data-auth-reminder-message]')?.replaceChildren(document.createTextNode(t('message')));
    const reminderButton = reminder?.querySelector('[data-auth-reminder-trigger]');
    if (reminderButton) reminderButton.textContent = t('title');

    const dialog = targetDialog;
    if (!dialog) return;
    dialog.querySelector('h2').textContent = t('title');
    dialog.querySelector('[data-close]').setAttribute('aria-label', t('later'));
    dialog.querySelector('[data-intro]').textContent = t(dialog.dataset.authSignIn === 'true' ? 'loginMessage' : 'message');
    dialog.querySelector('[data-email-label]').textContent = t('email');
    dialog.querySelector('[data-email]').textContent = t('continueEmail');
    for (const button of dialog.querySelectorAll('[data-provider]')) button.textContent = t(button.dataset.provider);
    dialog.querySelector('[data-choice-copy]').textContent = t('choiceMessage');
    dialog.querySelector('[data-existing]').textContent = t('mergeExisting');
    dialog.querySelector('[data-new]').textContent = t('chooseNew');
  }

  function open({ signIn = false } = {}) {
    if (!getAuth()?.user?.is_anonymous || document.querySelector('[data-auth-reminder-dialog]')) return;
    const dialog = document.createElement('dialog');
    dialog.className = 'profile-settings';
    dialog.dataset.authReminderDialog = '';
    dialog.dataset.authSignIn = String(signIn);
    dialog.setAttribute('aria-labelledby', 'auth-reminder-title');
    // All translated copy is assigned as text, never interpolated into HTML.
    dialog.innerHTML = `<form><header><h2 id="auth-reminder-title"></h2><button type="button" data-close>×</button></header><p data-intro></p><fieldset><label><span data-email-label></span><input type="email" name="email" autocomplete="email" required></label><button class="button button-primary" type="submit" data-email></button><div class="story-auth-actions"><button class="button button-secondary" type="button" data-provider="google"></button><button class="button button-secondary" type="button" data-provider="facebook"></button></div><div data-conflict hidden><p data-choice-copy></p><div class="story-auth-actions"><button class="button button-primary" type="button" data-existing></button><button class="button button-secondary" type="button" data-new></button></div></div></fieldset><p role="status" aria-live="polite"></p></form>`;
    refreshCopy(dialog);
    if (callbackError) dialog.querySelector('[role=status]').textContent = errorMessage(callbackError);
    function showChoices() {
      const fieldset = dialog.querySelector('fieldset');
      for (const child of fieldset.children) {
        child.hidden = child.hasAttribute('data-conflict') ? !conflict
          : conflict || (signIn && (child.tagName === 'LABEL' || child.hasAttribute('data-email')));
      }
    }
    showChoices();
    dialog.querySelector('[data-close]').onclick = () => dialog.close();
    dialog.addEventListener('close', () => dialog.remove(), { once: true });
    const run = async (provider, merge = false) => {
      const fieldset = dialog.querySelector('fieldset');
      const status = dialog.querySelector('[role=status]');
      fieldset.disabled = true;
      try {
        if (busy()) throw new Error('Reply in progress');
        if (merge) {
          if (!signInExisting) throw new Error('Unavailable');
          await signInExisting(provider);
          status.textContent = t('redirecting');
          return;
        }
        cancelTransfer?.();
        const auth = getAuth()?.client?.auth;
        if (!auth) throw new Error('Unavailable');
        const redirectTo = window.location.origin + window.location.pathname;
        const result = provider
          ? await linkSocialIdentity(auth, provider, redirectTo)
          : await auth.updateUser({ email: dialog.querySelector('input').value.trim() }, { emailRedirectTo: redirectTo });
        if (result.error) throw result.error;
        if (result.data?.user && result.data.user.id === getAuth()?.user?.id) {
          getAuth().user = result.data.user;
          tick();
          onUserChanged?.();
        }
        status.textContent = t(provider ? 'redirecting' : 'checkEmail');
      } catch (error) {
        status.textContent = errorMessage(error?.code);
        if (error?.code === 'identity_already_exists') {
          conflict = true;
          if (provider) conflictProvider = provider;
          showChoices();
        }
      } finally { fieldset.disabled = false; }
    };
    dialog.querySelector('form').onsubmit = (event) => { event.preventDefault(); run(); };
    // Login enters the selected account; transfer saves the guest first.
    for (const button of dialog.querySelectorAll('[data-provider]')) button.onclick = () => run(button.dataset.provider, signIn);
    dialog.querySelector('[data-existing]').onclick = () => run(conflictProvider, true);
    dialog.querySelector('[data-new]').onclick = () => run(conflictProvider);
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
    refreshCopy();
    const chat = document.querySelector('#chat-scroll');
    if (!due || !chat || document.querySelector('[data-auth-reminder]')) return;
    const reminder = document.createElement('aside');
    reminder.dataset.authReminder = '';
    reminder.className = 'auth-history-reminder';
    reminder.setAttribute('aria-live', 'polite');
    const message = document.createElement('p');
    message.dataset.authReminderMessage = '';
    message.textContent = t('message');
    const button = document.createElement('button');
    button.dataset.authReminderTrigger = '';
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
        onUserChanged?.();
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
  return { mount, tick, open };
}
