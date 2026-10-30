import { translate } from '../i18n.js';

const escape = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[c]));
const fields = ['name', 'birth_year', 'birth_date_expression', 'birth_place', 'avatar_style'];

export async function openProfileSettings({ api, onSave, onLanguageChange, onClose, isCurrent = () => true }) {
  if (document.querySelector('[data-profile-settings]')) return;
  const t = (key) => escape(translate(`Profile.${key}`));
  const dialog = document.createElement('dialog');
  dialog.className = 'profile-settings';
  dialog.dataset.profileSettings = '';
  dialog.setAttribute('aria-labelledby', 'profile-settings-title');
  dialog.innerHTML = `<form>
    <header><h2 id="profile-settings-title">${t('title')}</h2><button type="button" data-close aria-label="${t('close')}">×</button></header>
    <p class="profile-settings-intro">${t('intro')}</p>
    <fieldset disabled>
      <label class="profile-settings-language">${t('preferred_language')}<select name="preferred_language">
        <option value="">${t('automatic')}</option><option value="en-AU">English</option><option value="zh-CN">简体中文</option>
      </select><small>${t('languageHint')}</small></label>
      <div class="profile-settings-fields">${fields.map((key) => `<div class="profile-settings-field"><label>${t(key)}${key === 'avatar_style'
        ? `<select name="avatar_style"><option value="">${t('unspecified')}</option><option value="male">${t('avatarMale')}</option><option value="female">${t('avatarFemale')}</option></select>`
        : `<input name="${key}" ${key === 'birth_year' ? `type="number" min="1800" max="${new Date().getFullYear()}" step="1"` : `type="text" maxlength="${['name', 'birth_date_expression'].includes(key) ? 120 : 160}"`} autocomplete="${key === 'name' ? 'name' : 'off'}">`}</label>
        <label class="profile-settings-confirm"><input type="checkbox" name="confirm_${key}">${t('confirmField')}</label>
        <button type="button" class="text-button" data-release="${key}" hidden>${t('releaseField')}</button></div>`).join('')}</div>
      <p class="profile-settings-note">${t('artworkHint')}</p>
      <div data-automation hidden><p data-automation-status></p><p class="profile-settings-note">${t('automationHint')}</p>
        <button type="button" class="button button-secondary" data-confirm-all>${t('confirmAll')}</button>
        <button type="button" class="text-button" data-enable hidden>${t('enableAutomatic')}</button></div>
    </fieldset>
    <p data-status role="status" aria-live="polite">${t('loading')}</p>
    <footer><button type="button" class="button button-secondary" data-cancel>${t('cancel')}</button><button type="submit" class="button button-primary" disabled>${t('save')}</button></footer>
  </form>`;
  document.body.append(dialog);
  dialog.showModal();
  const form = dialog.querySelector('form');
  const fieldset = dialog.querySelector('fieldset');
  const submit = dialog.querySelector('[type=submit]');
  const status = dialog.querySelector('[data-status]');
  const automation = dialog.querySelector('[data-automation]');
  const enable = dialog.querySelector('[data-enable]');
  let saving = false;
  let currentSettings;
  const dirtyFields = new Set();
  const current = () => {
    if (isCurrent()) return dialog.open;
    dialog.close();
    return false;
  };
  const showAuthority = (settings) => {
    const state = settings.profile_automation;
    automation.hidden = !state;
    enable.hidden = !state?.stopped;
    dialog.querySelector('[data-automation-status]').textContent = translate(state?.stopped ? 'Profile.automaticStopped' : 'Profile.automaticActive');
    for (const key of fields) {
      const confirmed = state?.field_locks?.[key] === 'manual';
      form.elements[`confirm_${key}`].checked = confirmed || dirtyFields.has(key);
      dialog.querySelector(`[data-release="${key}"]`).hidden = !state?.field_locks?.[key];
    }
  };
  const readValues = (all = false) => Object.fromEntries(['preferred_language', ...fields]
    .filter((key) => key === 'preferred_language' || all || form.elements[`confirm_${key}`].checked)
    .map((key) => {
      const value = form.elements[key].value.trim() || null;
      return [key, key === 'birth_year' && value !== null ? Number(value) : value];
    }));
  const close = () => { if (!saving) dialog.close(); };
  dialog.querySelector('[data-close]').onclick = close;
  dialog.querySelector('[data-cancel]').onclick = close;
  dialog.addEventListener('cancel', (event) => { if (saving) event.preventDefault(); });
  dialog.addEventListener('close', () => { dialog.remove(); onClose?.(); }, { once: true });
  try {
    const settings = await api('/v1/agent/profile');
    if (!current()) return;
    currentSettings = settings;
    for (const key of ['preferred_language', ...fields]) form.elements[key].value = settings[key] ?? '';
    showAuthority(settings);
    if (settings.preferred_language) await onLanguageChange?.(settings.preferred_language);
    if (!current()) return;
    fieldset.disabled = false;
    submit.disabled = false;
    status.textContent = '';
    form.elements.preferred_language.focus();
  } catch {
    status.textContent = translate('Profile.loadError');
    return;
  }
  form.addEventListener('input', (event) => {
    if (fields.includes(event.target.name)) {
      dirtyFields.add(event.target.name);
      form.elements[`confirm_${event.target.name}`].checked = true;
    }
  });
  const save = async (settings, closeAfterSave) => {
    if (saving || !current()) return;
    saving = true;
    fieldset.disabled = true;
    submit.disabled = true;
    status.textContent = translate('Profile.saving');
    let persisted = false;
    try {
      const saved = await api('/v1/agent/profile', { method: 'PATCH', body: JSON.stringify(settings) });
      persisted = true;
      if (!current()) return;
      currentSettings = saved;
      for (const key of [...Object.keys(settings), ...(settings.profile_release_fields || [])]) dirtyFields.delete(key);
      showAuthority(saved);
      await onSave?.(saved, { closeAfterSave });
      if (!current()) return;
      saving = false;
      if (closeAfterSave) dialog.close();
      else status.textContent = translate('Profile.saved');
      return true;
    } catch {
      status.textContent = translate(persisted ? 'Profile.syncError' : 'Profile.saveError');
    } finally {
      saving = false;
      fieldset.disabled = false;
      submit.disabled = false;
    }
  };
  form.onsubmit = (event) => {
    event.preventDefault();
    return save(readValues(), true);
  };
  dialog.querySelector('[data-confirm-all]').onclick = () => save({ ...readValues(true), profile_confirm_all: true }, true);
  enable.onclick = () => save({ profile_auto_enabled: true }, false);
  for (const key of fields) dialog.querySelector(`[data-release="${key}"]`).onclick = async () => {
    if (await save({ profile_release_fields: [key] }, false) && current()) form.elements[key].value = currentSettings[key] ?? '';
  };
}
