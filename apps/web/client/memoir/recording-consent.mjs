import {currentUiLocale, translate} from '../i18n.js';

export function createRecordingConsent({storyApi, captureProjectScope, isCurrentProjectScope, openIdentity, onRevoke, toast}) {
  let pending;
  const t = key => translate(`RecordingConsent.${key}`);

  function review(status, scope) {
    return new Promise(resolve => {
      const dialog = document.createElement('dialog');
      dialog.className = 'profile-settings';
      dialog.dataset.recordingConsent = '';
      dialog.setAttribute('aria-labelledby', 'recording-consent-title');
      dialog.innerHTML = `<form><header><h2 id="recording-consent-title"></h2><button type="button" data-close>×</button></header><p data-description></p><label><input type="checkbox" name="retain" required><span data-retain></span></label><label><input type="checkbox" name="processing" required><span data-processing></span></label><p data-withdrawal></p><p role="status" aria-live="polite"></p><button class="button button-primary" type="submit" data-save></button><button class="text-button" type="button" data-revoke></button></form>`;
      for (const [selector, key] of [['h2','title'],['[data-description]','description'],['[data-retain]','retain'],
        ['[data-processing]','processing'],['[data-withdrawal]','withdrawal'],['[data-save]','allow'],['[data-revoke]','revoke']]) {
        dialog.querySelector(selector).textContent = t(key);
      }
      dialog.querySelector('[data-close]').setAttribute('aria-label', t('close'));
      dialog.querySelector('[data-close]').onclick = () => dialog.close();
      dialog.querySelector('[data-revoke]').hidden = !status.consented;
      dialog.querySelector('[data-save]').disabled = !status.enabled || !status.recoverable_identity;
      dialog.querySelector('[name=retain]').checked = status.consented;
      dialog.querySelector('[name=processing]').checked = status.consented;
      const save = async action => {
        if (!isCurrentProjectScope(scope)) { dialog.close(); return; }
        const buttons = dialog.querySelectorAll('button');
        buttons.forEach(button => { button.disabled = true; });
        try {
          const result = await storyApi('/v1/story/recording-consent', {method:'PUT', body:JSON.stringify({
            action, policy_version:status.policy_version, expected_revision:status.revision,
            retain_originals:dialog.querySelector('[name=retain]').checked,
            ai_processing:dialog.querySelector('[name=processing]').checked, locale:currentUiLocale(),
          })});
          if (!isCurrentProjectScope(scope)) { dialog.close(); return; }
          dialog.returnValue = result.consented ? 'granted' : '';
          if (action === 'revoke') onRevoke?.();
          dialog.close();
        } catch (error) {
          if (!isCurrentProjectScope(scope)) { dialog.close(); return; }
          dialog.querySelector('[role=status]').textContent = error.message;
        } finally { buttons.forEach(button => { button.disabled = false; }); }
      };
      dialog.querySelector('form').onsubmit = event => { event.preventDefault(); void save('grant'); };
      dialog.querySelector('[data-revoke]').onclick = () => void save('revoke');
      dialog.addEventListener('close', () => {
        dialog.remove();
        resolve(isCurrentProjectScope(scope) && dialog.returnValue === 'granted');
      }, {once:true});
      document.body.append(dialog);
      dialog.showModal();
    });
  }

  async function check(manage) {
    const scope = captureProjectScope();
    try {
      const status = await storyApi('/v1/story/recording-consent');
      if (!isCurrentProjectScope(scope)) return false;
      if (!status.enabled && !manage) { toast(translate('Errors.recordingRetentionDisabled')); return false; }
      if (!status.recoverable_identity && !(manage && status.consented)) { toast(t('identity')); openIdentity(); return false; }
      if (status.consented && !manage) return true;
      return await review(status, scope);
    } catch (error) { if (isCurrentProjectScope(scope)) toast(error.message); return false; }
  }

  function ensure() {
    if (!pending) pending = check(false).finally(() => { pending = null; });
    return pending;
  }
  return {ensure, open:() => pending || (pending = check(true).finally(() => { pending = null; }))};
}
