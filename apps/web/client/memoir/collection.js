import { translate } from '../i18n.js';

const stages = ['baby', 'toddler', 'childhood', 'adolescence', 'young_adulthood', 'midlife', 'later_life'];
const escape = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[c]));
const t = (key) => escape(translate(`Collection.${key}`));

export async function openCollectionReview({ api, projectId, language }) {
  if (document.querySelector('[data-collection-review]')) return;
  const path = `/v1/agent/collection/${encodeURIComponent(projectId)}`;
  let saved = await api(path);
  if (document.querySelector('[data-collection-review]')) return;
  saved.tasks ||= [];
  const dialog = document.createElement('dialog');
  dialog.className = 'collection-review';
  dialog.dataset.collectionReview = '';
  dialog.setAttribute('aria-labelledby', 'collection-heading');
  dialog.innerHTML = `<form><header><h2 id="collection-heading">${t('title')}</h2><button type="button" data-close aria-label="${t('close')}">×</button></header>
    <p>${t('intro')}</p><div class="collection-periods">${stages.map((stage) => {
      const period = saved.periods[stage] || {};
      return `<fieldset data-stage="${stage}"><legend>${escape(translate(`Memoir.workspace.lifeStages.${stage}.label`))}</legend>
        <label>${t('coverage')}<select data-status><option value="">${t('review')}</option>${['recorded', 'skipped', 'not_applicable'].map((status) => `<option value="${status}" ${period.status === status ? 'selected' : ''}>${t(status)}</option>`).join('')}</select></label>
        <label>${t('memories')}<select data-memories multiple size="3">${saved.sources.map((source) => `<option value="${escape(source.id)}" ${(period.memory_ids || []).includes(source.id) ? 'selected' : ''}>${escape(source.content.slice(0, 180))}</option>`).join('')}</select></label>
        <label>${t('note')}<textarea data-note maxlength="500">${escape(period.note || '')}</textarea></label></fieldset>`;
    }).join('')}</div>
    <label class="collection-confirm"><input type="checkbox" data-confirm> ${t('confirm')}</label>
    <footer><button type="button" data-save class="button button-secondary">${t('save')}</button><button type="submit" class="button button-primary">${t('organise')}</button></footer>
    <p data-status-message role="status"></p><section data-results aria-label="${t('results')}"></section></form>`;
  document.body.append(dialog);
  dialog.showModal();
  dialog.querySelector('[data-close]').onclick = () => dialog.close();
  let timer;
  dialog.addEventListener('close', () => { clearTimeout(timer); dialog.remove(); }, { once: true });
  const message = dialog.querySelector('[data-status-message]');
  const results = dialog.querySelector('[data-results]');
  function renderTasks(tasks) {
    results.innerHTML = tasks.map((task) => `<article class="collection-task"><h3>${task.result?.title ? escape(task.result.title) : t(task.kind)}</h3><p>${t(task.status)}</p>${task.result?.sections ? `<ol>${task.result.sections.map((section) => `<li>${escape(section.title)} (${section.memory_ids.length})</li>`).join('')}</ol>` : ''}<button type="button" data-task="${escape(task.id)}">${t('refresh')}</button>${task.status === 'SUCCEEDED' ? `<button type="button" data-download="${escape(task.id)}">${t('download')}</button>` : ''}</article>`).join('');
    results.querySelectorAll('[data-task]').forEach((button) => { button.onclick = async () => {
      try {
        const updated = await api(`/v1/agent/tasks/${button.dataset.task}`);
        saved.tasks = saved.tasks.map((task) => task.id === updated.id ? updated : task);
        renderTasks(saved.tasks);
      } catch (error) { message.textContent = error.message; }
    }; });
    results.querySelectorAll('[data-download]').forEach((button) => { button.onclick = () => {
      const task = saved.tasks.find((entry) => entry.id === button.dataset.download);
      const url = URL.createObjectURL(new Blob([JSON.stringify(task.result, null, 2)], { type: 'application/json' }));
      const link = document.createElement('a'); link.href = url; link.download = 'memoir-structure.json'; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }; });
  }
  renderTasks(saved.tasks || []);
  async function save(confirm) {
    const periods = {};
    for (const fieldset of dialog.querySelectorAll('[data-stage]')) {
      const status = fieldset.querySelector('[data-status]').value;
      if (!status) {
        if (confirm) throw new Error(translate('Collection.missing'));
        continue;
      }
      const memoryIds = Array.from(fieldset.querySelector('[data-memories]').selectedOptions, (option) => option.value);
      const note = fieldset.querySelector('[data-note]').value.trim();
      if ((status === 'recorded' && !memoryIds.length) || (status !== 'recorded' && !note)) throw new Error(translate('Collection.missing'));
      periods[fieldset.dataset.stage] = { status, memory_ids: status === 'recorded' ? memoryIds : [], note };
    }
    const updated = await api(path, { method: 'PUT', body: JSON.stringify({ expected_revision: saved.revision, periods, confirm_ready: confirm }) });
    saved = { ...saved, ...updated };
    message.textContent = translate('Collection.saved');
  }
  dialog.querySelector('[data-save]').onclick = async () => {
    try { await save(false); } catch (error) { message.textContent = error.message; }
  };
  dialog.querySelector('form').onsubmit = async (event) => {
    event.preventDefault();
    if (!dialog.querySelector('[data-confirm]').checked) { message.textContent = translate('Collection.confirmFirst'); return; }
    const button = dialog.querySelector('[type=submit]');
    button.disabled = true;
    try {
      await save(true);
      message.textContent = translate('Collection.organising');
      const task = await api(`${path}/organise`, { method: 'POST', body: JSON.stringify({ expected_revision: saved.revision, language }) });
      saved.tasks = [task, ...(saved.tasks || []).filter((entry) => entry.id !== task.id)];
      renderTasks(saved.tasks);
      message.textContent = translate('Collection.queued');
      let polls = 0;
      async function poll() {
        if (!dialog.isConnected) return;
        try {
          const updated = await api(`/v1/agent/tasks/${task.id}`);
          saved.tasks = saved.tasks.map((entry) => entry.id === task.id ? updated : entry);
          renderTasks(saved.tasks);
          if (['QUEUED', 'RUNNING'].includes(updated.status) && ++polls < 60) timer = setTimeout(poll, 2000);
        } catch (error) { message.textContent = error.message; }
      }
      timer = setTimeout(poll, 2000);
    } catch (error) { message.textContent = error.message; }
    finally { button.disabled = false; }
  };
}
