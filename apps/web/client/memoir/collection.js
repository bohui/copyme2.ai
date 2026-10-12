import { translate } from '../i18n.js';

const stages = ['baby', 'toddler', 'childhood', 'adolescence', 'young_adulthood', 'midlife', 'later_life'];
const escape = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[c]));
const t = (key) => escape(translate(`Collection.${key}`));


export function mergeCollectionSelection(previous, visible, selected) {
  const shown = new Set(visible), chosen = new Set(selected);
  return [...previous.filter((id) => !shown.has(id) || chosen.has(id)),
    ...selected.filter((id) => !previous.includes(id))];
}

export function canRetryCollectionTask(task) {
  return task.status === 'FAILED' && task.error === 'BOUNDED_JOB_RETRY';
}

export function appendCollectionTaskPage(previous, next, cursor) {
  if (previous.tasks_next_cursor !== cursor || previous.revision !== next.revision
      || previous.source_fingerprint !== next.source_fingerprint
      || (next.tasks_complete === false && (!next.tasks_next_cursor || next.tasks_next_cursor === cursor))) {
    throw new Error(translate('Collection.resultChanged'));
  }
  const known = new Set(previous.tasks.map((task) => task.id));
  return { ...previous, tasks: [...previous.tasks, ...(next.tasks || []).filter((task) => !known.has(task.id))],
    tasks_next_cursor: next.tasks_next_cursor, tasks_complete: next.tasks_complete };
}

export async function collectCollectionTaskResult(api, taskId, active = () => true) {
  let cursor = null, root, result;
  const seen = new Set();
  do {
    if (!active()) throw new Error(translate('Collection.closed'));
    const page = await api(`/v1/agent/tasks/${encodeURIComponent(taskId)}${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''}`);
    if (!active()) throw new Error(translate('Collection.closed'));
    if (page.status !== 'SUCCEEDED' || !page.result || (root && page.root_digest !== root)) {
      throw new Error(translate('Collection.resultChanged'));
    }
    if (!result) {
      root = page.root_digest;
      result = { ...page.result, sources: [...(page.result.sources || [])], blocks: [...(page.result.blocks || [])] };
    } else {
      result.sources.push(...(page.result.sources || []));
      result.blocks.push(...(page.result.blocks || []));
    }
    if (page.complete !== false) return result;
    if (!page.next_cursor || seen.has(page.next_cursor)) throw new Error(translate('Collection.resultChanged'));
    cursor = page.next_cursor;
    seen.add(cursor);
  } while (true);
}

export async function openCollectionReview({ api, projectId, language }) {
  if (document.querySelector('[data-collection-review]')) return;
  const path = `/v1/agent/collection/${encodeURIComponent(projectId)}`;
  let saved = await api(path);
  if (document.querySelector('[data-collection-review]')) return;
  saved.tasks ||= [];
  saved.periods ||= {};
  saved.sources ||= [];
  const selectedByStage = Object.fromEntries(stages.map((stage) => [stage, [...(saved.periods[stage]?.memory_ids || [])]]));
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
    <p>${t('sourcesLimit')}</p><p data-source-status role="status"></p><button type="button" data-more-sources>${t('moreSources')}</button>
    <label class="collection-confirm"><input type="checkbox" data-confirm> ${t('confirm')}</label>
    <footer><button type="button" data-save class="button button-secondary">${t('save')}</button><button type="submit" class="button button-primary">${t('organise')}</button></footer>
    <p data-status-message role="status"></p><section data-results aria-label="${t('results')}"></section><p data-task-status role="status"></p><button type="button" data-more-tasks>${t('moreTasks')}</button></form>`;
  document.body.append(dialog);
  dialog.showModal();
  dialog.querySelector('[data-close]').onclick = () => dialog.close();
  let timer;
  dialog.addEventListener('close', () => { clearTimeout(timer); dialog.remove(); }, { once: true });
  const message = dialog.querySelector('[data-status-message]');
  const results = dialog.querySelector('[data-results]');
  const moreSources = dialog.querySelector('[data-more-sources]');
  const moreTasks = dialog.querySelector('[data-more-tasks]');
  function captureSelections() {
    for (const fieldset of dialog.querySelectorAll('[data-stage]')) {
      const select = fieldset.querySelector('[data-memories]');
      selectedByStage[fieldset.dataset.stage] = mergeCollectionSelection(selectedByStage[fieldset.dataset.stage],
        Array.from(select.options, (option) => option.value), Array.from(select.selectedOptions, (option) => option.value));
    }
  }
  function renderSourceState() {
    moreSources.hidden = !saved.next_cursor;
    dialog.querySelector('[data-source-status]').textContent = saved.complete === false
      ? translate('Collection.sourcesPartial') : translate('Collection.sourcesComplete');
  }
  renderSourceState();
  moreSources.onclick = async () => {
    if (moreSources.disabled || !saved.next_cursor) return;
    moreSources.disabled = true;
    const cursor = saved.next_cursor, revision = saved.revision;
    captureSelections();
    try {
      const next = await api(`${path}?cursor=${encodeURIComponent(cursor)}`);
      if (!dialog.isConnected || saved.next_cursor !== cursor) return;
      if (saved.revision !== revision || next.revision !== revision || next.source_fingerprint !== saved.source_fingerprint) throw new Error(translate('Collection.resultChanged'));
      const known = new Set(saved.sources.map((source) => source.id));
      const added = (next.sources || []).filter((source) => !known.has(source.id));
      for (const fieldset of dialog.querySelectorAll('[data-stage]')) {
        const select = fieldset.querySelector('[data-memories]');
        for (const source of added) {
          const option = document.createElement('option');
          option.value = source.id;
          option.textContent = source.content.slice(0, 180);
          option.selected = selectedByStage[fieldset.dataset.stage].includes(source.id);
          select.append(option);
        }
      }
      saved.sources.push(...added);
      saved.next_cursor = next.next_cursor;
      saved.complete = next.complete;
      renderSourceState();
    } catch (error) { if (dialog.isConnected) message.textContent = error.message; }
    finally { moreSources.disabled = false; }
  };
  moreTasks.onclick = async () => {
    if (moreTasks.disabled || !saved.tasks_next_cursor) return;
    moreTasks.disabled = true;
    const cursor = saved.tasks_next_cursor;
    try {
      const next = await api(`${path}?task_cursor=${encodeURIComponent(cursor)}`);
      if (!dialog.isConnected || saved.tasks_next_cursor !== cursor) return;
      saved = appendCollectionTaskPage(saved, next, cursor);
      renderTasks(saved.tasks);
    } catch (error) { if (dialog.isConnected) message.textContent = error.message; }
    finally { moreTasks.disabled = false; }
  };
  function renderTasks(tasks) {
    moreTasks.hidden = !saved.tasks_next_cursor;
    dialog.querySelector('[data-task-status]').textContent = saved.tasks_complete === false ? translate('Collection.tasksPartial') : '';
    results.innerHTML = tasks.map((task) => `<article class="collection-task"><h3>${task.result?.title ? escape(task.result.title) : t(task.kind)}</h3><p>${t(task.status)}</p>${task.result?.proposed ? `<p>${t('proposalOnly')}</p>` : ''}${task.complete === false && task.result ? `<p>${t('resultPartial')}</p>` : ''}${task.result?.sections ? `<ol>${task.result.sections.map((section) => `<li>${escape(section.title)} (${section.memory_ids?.length ?? '…'})</li>`).join('')}</ol>` : ''}<button type="button" data-task="${escape(task.id)}">${t('refresh')}</button>${canRetryCollectionTask(task) ? `<button type="button" data-retry="${escape(task.id)}">${t('retry')}</button>` : ''}${task.status === 'SUCCEEDED' ? `<button type="button" data-download="${escape(task.id)}">${t('download')}</button>` : ''}</article>`).join('');
    results.querySelectorAll('[data-task]').forEach((button) => { button.onclick = async () => {
      try {
        const updated = await api(`/v1/agent/tasks/${button.dataset.task}`);
        saved.tasks = saved.tasks.map((task) => task.id === updated.id ? updated : task);
        renderTasks(saved.tasks);
      } catch (error) { message.textContent = error.message; }
    }; });
    results.querySelectorAll('[data-retry]').forEach((button) => { button.onclick = async () => {
      if (button.disabled) return;
      button.disabled = true;
      try {
        const updated = await api(`/v1/agent/tasks/${button.dataset.retry}/retry`, { method: 'POST' });
        if (!dialog.isConnected) return;
        saved.tasks = saved.tasks.map((task) => task.id === updated.id ? { ...task, ...updated, result: null } : task);
        renderTasks(saved.tasks);
      } catch (error) { if (dialog.isConnected) message.textContent = error.message; }
      finally { button.disabled = false; }
    }; });
    results.querySelectorAll('[data-download]').forEach((button) => { button.onclick = async () => {
      if (button.disabled) return;
      button.disabled = true;
      try {
        message.textContent = translate('Collection.downloading');
        const result = await collectCollectionTaskResult(api, button.dataset.download, () => dialog.isConnected);
        if (!dialog.isConnected) return;
        const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' }));
        const link = document.createElement('a'); link.href = url; link.download = 'memoir-structure.json'; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        message.textContent = translate('Collection.downloadReady');
      } catch (error) { if (dialog.isConnected) message.textContent = error.message; }
      finally { button.disabled = false; }
    }; });
  }
  renderTasks(saved.tasks || []);
  async function save(confirm) {
    captureSelections();
    const periods = {};
    for (const fieldset of dialog.querySelectorAll('[data-stage]')) {
      const status = fieldset.querySelector('[data-status]').value;
      if (!status) {
        if (confirm) throw new Error(translate('Collection.missing'));
        continue;
      }
      const memoryIds = selectedByStage[fieldset.dataset.stage];
      const note = fieldset.querySelector('[data-note]').value.trim();
      if ((status === 'recorded' && !memoryIds.length) || (status !== 'recorded' && !note)) throw new Error(translate('Collection.missing'));
      periods[fieldset.dataset.stage] = { status, memory_ids: status === 'recorded' ? memoryIds : [], note };
    }
    const updated = await api(path, { method: 'PUT', body: JSON.stringify({ expected_revision: saved.revision, periods, confirm_ready: confirm }) });
    saved = { ...saved, ...updated, tasks: saved.tasks, tasks_next_cursor: saved.tasks_next_cursor, tasks_complete: saved.tasks_complete };
    message.textContent = translate('Collection.saved');
  }
  dialog.querySelector('[data-save]').onclick = async () => {
    const button = dialog.querySelector('[data-save]');
    if (button.disabled) return;
    button.disabled = true;
    try { await save(false); } catch (error) { message.textContent = error.message; }
    finally { button.disabled = false; }
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
