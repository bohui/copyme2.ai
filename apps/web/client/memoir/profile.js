import { translate } from '../i18n.js';

const escape = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[c]));
const fields = ['name', 'birth_year', 'birth_place', 'childhood_place'];

export async function openProfileSettings({ api, onSave, onClose }) {
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
      <div class="profile-settings-fields">${fields.map((key) => `<label>${t(key)}<input name="${key}" ${key === 'birth_year' ? `type="number" min="1800" max="${new Date().getFullYear()}" step="1"` : `type="text" maxlength="${key === 'name' ? 120 : 160}"`} autocomplete="${key === 'name' ? 'name' : 'off'}"></label>`).join('')}</div>
      <p class="profile-settings-note">${t('artworkHint')}</p>
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
  let saving = false;
  const close = () => { if (!saving) dialog.close(); };
  dialog.querySelector('[data-close]').onclick = close;
  dialog.querySelector('[data-cancel]').onclick = close;
  dialog.addEventListener('cancel', (event) => { if (saving) event.preventDefault(); });
  dialog.addEventListener('close', () => { dialog.remove(); onClose?.(); }, { once: true });
  try {
    const settings = await api('/v1/agent/profile');
    if (!dialog.open) return;
    for (const key of ['preferred_language', ...fields]) form.elements[key].value = settings[key] ?? '';
    fieldset.disabled = false;
    submit.disabled = false;
    status.textContent = '';
    form.elements.preferred_language.focus();
  } catch {
    status.textContent = translate('Profile.loadError');
    return;
  }
  form.onsubmit = async (event) => {
    event.preventDefault();
    if (saving) return;
    const settings = Object.fromEntries(['preferred_language', ...fields].map((key) => [key, form.elements[key].value.trim() || null]));
    if (settings.birth_year !== null) settings.birth_year = Number(settings.birth_year);
    saving = true;
    fieldset.disabled = true;
    submit.disabled = true;
    status.textContent = translate('Profile.saving');
    let persisted = false;
    try {
      const saved = await api('/v1/agent/profile', { method: 'PATCH', body: JSON.stringify(settings) });
      persisted = true;
      await onSave(saved);
      saving = false;
      dialog.close();
    } catch {
      status.textContent = translate(persisted ? 'Profile.syncError' : 'Profile.saveError');
    } finally {
      saving = false;
      fieldset.disabled = false;
      submit.disabled = false;
    }
  };
}
