import { translate } from '../i18n.js';

const t = key => translate(`AuthReminder.${key}`);
function dialog(title) {
  const node = document.createElement('dialog');
  node.className = 'profile-settings';
  node.innerHTML = '<header><h2></h2><button type="button" data-close>×</button></header><div data-content></div>';
  node.querySelector('h2').textContent = title;
  node.setAttribute('aria-label', title);
  node.querySelector('[data-close]').setAttribute('aria-label', t('later'));
  node.querySelector('[data-close]').onclick = () => node.close();
  node.addEventListener('close', () => node.remove(), { once: true });
  document.body.append(node);
  node.showModal();
  return node;
}

export async function openAttachedConversations(api) {
  const node = dialog(t('attachedHistory'));
  const content = node.querySelector('[data-content]');
  content.textContent = t('historyLoading');
  try {
    const { items } = await api('/v1/user/conversations');
    content.replaceChildren();
    if (!items.length) content.textContent = t('historyEmpty');
    for (const item of items) {
      const entry = document.createElement('details');
      const summary = document.createElement('summary');
      summary.textContent = item.messages.find(message => message.role === 'user')?.text.slice(0, 100) || item.project_id;
      entry.append(summary);
      for (const message of item.messages) {
        const paragraph = document.createElement('p');
        const label = document.createElement('strong');
        label.textContent = t(message.role === 'user' ? 'historyYou' : 'historyMemoir') + ': ';
        paragraph.append(label, document.createTextNode(message.text));
        entry.append(paragraph);
      }
      if (item.workspace && Object.keys(item.workspace).length) {
        const download = document.createElement('button');
        download.type = 'button';
        download.className = 'button button-secondary';
        download.textContent = t('downloadContext');
        download.onclick = () => {
          const url = URL.createObjectURL(new Blob([JSON.stringify(item.workspace, null, 2)], { type: 'application/json' }));
          const link = document.createElement('a');
          link.href = url;
          link.download = `memoir-context-${item.id}.json`;
          link.click();
          setTimeout(() => URL.revokeObjectURL(url), 1000);
        };
        entry.append(download);
      }
      content.append(entry);
    }
  } catch { content.textContent = t('historyError'); }
}

export function retryConversationTransfer(complete, restoreGuest) {
  const node = dialog(t('mergeExisting'));
  const content = node.querySelector('[data-content]');
  const status = document.createElement('p');
  status.setAttribute('role', 'status');
  status.textContent = t('mergeError');
  const retry = document.createElement('button');
  retry.className = 'button button-primary';
  retry.textContent = t('retryMerge');
  const restore = document.createElement('button');
  restore.className = 'button button-secondary';
  restore.textContent = t('returnGuest');
  restore.onclick = async () => {
    retry.disabled = true;
    restore.disabled = true;
    try { await restoreGuest(); }
    catch { status.textContent = t('restoreError'); }
    finally { retry.disabled = false; restore.disabled = false; }
  };
  retry.onclick = async () => {
    retry.disabled = true;
    restore.disabled = true;
    try {
      await complete();
      status.textContent = t('mergeSuccess');
      retry.remove();
      restore.remove();
    } catch { status.textContent = t('mergeError'); }
    finally { retry.disabled = false; restore.disabled = false; }
  };
  content.append(status, retry, restore);
}
