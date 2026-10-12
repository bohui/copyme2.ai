// The server owns conversation guidance. This client holds only a scoped display
// snapshot; choosing guidance never submits narration or creates a recall round.
const PHASES = ['comfort', 'explore', 'shape'];
const ACTIONS = [...PHASES, 'automatic', 'skip'];
const sameScope = (a, b) => a?.ownerId === b?.ownerId && a?.projectId === b?.projectId && a?.generation === b?.generation;
const validPhase = value => value?.schema_version === 1 && PHASES.includes(value.phase)
  && ['automatic', 'explicit'].includes(value.selection)
  && Number.isSafeInteger(value.revision) && value.revision >= 0;

export function createConversationPhase({scope, api, onChange = () => {}}) {
  let active;
  function entry() {
    const next = scope();
    if (!sameScope(active?.scope, next)) {
      active = {scope:next, value:null, busy:false, notice:null, loaded:false, request:null};
    }
    return active;
  }
  const current = item => active === item && sameScope(item.scope, scope());
  const endpoint = item => `/v1/agent/projects/${encodeURIComponent(item.scope.projectId)}/conversation-phase`;
  function accept(captured, value, {notify = true} = {}) {
    const item = entry();
    if (!sameScope(captured, item.scope) || !validPhase(value)) return false;
    if (item.value && value.revision < item.value.revision) return false;
    item.value = {...value};
    item.loaded = true;
    if (notify) { item.notice = null; onChange(); }
    return true;
  }
  async function read(item) {
    const result = await api(endpoint(item), {method:'GET', cache:'no-store'});
    if (!current(item)) return;
    if (!validPhase(result?.conversation_phase)) throw new Error('Invalid conversation guidance response');
    accept(item.scope, result.conversation_phase, {notify:false});
  }
  function refresh() {
    const item = entry();
    if (!item.scope.ownerId || !item.scope.projectId) return Promise.resolve();
    if (item.busy) return item.request || Promise.resolve();
    item.busy = true;
    item.notice = null;
    item.request = (async () => {
      try { await read(item); }
      catch { if (current(item)) item.notice = 'unavailable'; }
      finally {
        if (current(item)) { item.busy = false; item.loaded = true; item.request = null; onChange(); }
      }
    })();
    return item.request;
  }
  function ensure() {
    const item = entry();
    return item.loaded ? Promise.resolve() : refresh();
  }
  async function act(action) {
    const item = entry();
    if (!ACTIONS.includes(action) || item.busy || !item.value || item.notice === 'unavailable') return;
    item.busy = true;
    item.notice = null;
    onChange();
    try {
      const result = await api(endpoint(item), {method:'PATCH', body:JSON.stringify({action, expected_revision:item.value.revision})});
      if (!current(item)) return;
      if (!validPhase(result?.conversation_phase)) throw new Error('Invalid conversation guidance response');
      accept(item.scope, result.conversation_phase, {notify:false});
      if (action === 'skip') item.notice = 'skipped';
    } catch (error) {
      if (!current(item)) return;
      // A failed response may have followed a commit. Reconcile once, and never
      // replay the intent automatically or let a stale tab overwrite a choice.
      item.notice = error.status === 409 ? 'conflict' : 'saveError';
      try { await read(item); }
      catch { if (current(item)) item.notice = 'unavailable'; }
    } finally {
      if (current(item)) { item.busy = false; item.request = null; onChange(); }
    }
  }
  function view() {
    const item = entry();
    return {value:item.value, busy:item.busy, notice:item.notice};
  }
  return {view, ensure, refresh, act, accept};
}

const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[char]));
export function conversationPhaseMarkup({value, busy, notice}, translate, disabled = false) {
  const t = key => escape(translate(key));
  const locked = busy || !value || notice === 'unavailable';
  const selected = action => action === 'automatic' ? value?.selection === 'automatic'
    : value?.selection === 'explicit' && value?.preferred_phase === action;
  const button = action => `<button type="button" class="phase-choice" data-phase-action="${action}"${[...PHASES, 'automatic'].includes(action) ? ` aria-pressed="${Boolean(selected(action))}"` : ''}${locked || disabled ? ' disabled' : ''}>${t(action)}</button>`;
  const status = notice || (value ? `${value.phase}Status` : 'loading');
  return `<section class="conversation-phase" aria-label="${t('label')}"><div class="phase-heading"><span>${t('label')}</span><span class="phase-status" role="status" aria-live="polite">${t(busy && value ? 'saving' : status)}</span></div><div class="phase-choices" role="group" aria-label="${t('choices')}">${ACTIONS.map(button).join('')}${notice === 'unavailable' ? `<button type="button" class="phase-choice" data-phase-retry${busy ? ' disabled' : ''}>${t('retry')}</button>` : ''}</div></section>`;
}
