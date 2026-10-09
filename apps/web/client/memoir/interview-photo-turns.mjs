// This client keeps transport identity and display state only. Photo ownership,
// evidence, and question planning are validated and persisted by the server.
export function responsePhotoCards(value) {
  if (!Array.isArray(value)) return [];
  return value.slice(0, 10).flatMap(photo => {
    if (!photo || typeof photo.photo_id !== 'string' || !['public_reference', 'private_upload'].includes(photo.kind)) return [];
    const card = {photo_id:photo.photo_id, kind:photo.kind, title:String(photo.title || ''), description:String(photo.description || '')};
    if (photo.kind === 'public_reference') {
      for (const key of ['image_url', 'source_url']) if (typeof photo[key] === 'string') card[key] = photo[key];
    }
    return [card];
  });
}

export function createInterviewPhotoState({state, scope, render, api, storage,
  uuid = () => globalThis.crypto.randomUUID(), onRecovered = () => {}}) {
  if (!storage) { try { storage = globalThis.sessionStorage; } catch { /* Storage can be disabled. */ } }
  let active = null;
  const images = new Map();
  const current = turn => turn && turn.projectId === scope().projectId && turn.ownerId === scope().ownerId
    && turn.generation === scope().generation;
  const key = () => `memory-spark-pending-turn:${encodeURIComponent(scope().ownerId || '')}:${encodeURIComponent(scope().projectId || '')}`;
  function save(turn) {
    active = turn;
    try { storage.setItem(key(), JSON.stringify(turn)); } catch { /* In-memory retry still works. */ }
  }
  function pending() { return current(active) ? active : null; }
  function prepare(options) {
    const retry = options.retry || pending();
    if (current(retry) && (options.retry || retry.conversationText === options.conversationText && retry.text === options.text)) return retry;
    const saved = state.project?.profile?.photo_memories?.[scope().projectId] || {};
    const attachments = options.attachments || [];
    const turn = {...scope(), id:uuid(), text:options.text, conversationText:options.conversationText,
      sourceKind:options.sourceKind || 'narrator_chat', language:options.language,
      firstReplyLocalization:options.firstReplyLocalization || false, serverAction:options.serverAction || null,
      photoSelection:saved.selected ? {key:saved.selected, revision:saved.selection_revision || null} : null,
      uploadedPhotoIds:attachments.map(item => item.privatePhoto?.id).filter(Boolean),
      // Non-photo attachments remain supported, but cannot become private photo IDs.
      attachmentIds:attachments.map(item => item.privatePhoto?.id || item.asset?.id).filter(Boolean), accepted:false};
    save(turn);
    return turn;
  }
  function accept(turn, data) {
    if (!current(turn)) return;
    const accepted = data?.conversation_saved === true || ['source_accepted', 'conversation_saved'].includes(data?.state);
    if (!accepted) return;
    turn.accepted = true;
    const cue = data.photo_cue;
    const saved = state.project?.profile?.photo_memories?.[turn.projectId];
    // Compare the selection generation as well as its identity: selecting the
    // same photo again creates a new cue and must survive an older receipt.
    if (cue?.consumed && saved?.selected && saved.selected === cue.key
        && (saved.selection_revision ?? null) === cue.revision
        && turn.photoSelection?.key === cue.key && turn.photoSelection?.revision === cue.revision) {
      state.project.profile = {...state.project.profile, photo_memories:{...state.project.profile.photo_memories,
        [turn.projectId]:{...saved, selected:null}}};
      state.photoMemoryRevision = (state.photoMemoryRevision || 0) + 1;
    }
    state.attachments = (state.attachments || []).filter(item => !turn.attachmentIds.includes(item.privatePhoto?.id || item.asset?.id));
    if (!state.attachments.length) state.attachmentRights = false;
    state.attachmentProgress = '';
    if (pending()?.id === turn.id) save(turn);
    render();
  }
  function finish(turn, data) {
    accept(turn, data);
    if (!current(turn) || pending()?.id !== turn.id || !data?.reply
        || !(data.conversation_saved || data.state === 'conversation_saved')) return;
    active = null;
    try { storage.removeItem(key()); } catch { /* Optional cache. */ }
  }
  async function recover() {
    if (!scope().projectId) return;
    let saved;
    try { saved = JSON.parse(storage.getItem(key()) || 'null'); } catch { return; }
    if (!saved?.id || saved.projectId !== scope().projectId || saved.ownerId !== scope().ownerId) return;
    active = {...saved, generation:scope().generation};
    const turn = active;
    try {
      const receipt = await api(`/v1/agent/turns/${encodeURIComponent(turn.id)}?project_id=${encodeURIComponent(turn.projectId)}`);
      if (!current(turn)) return;
      accept(turn, receipt);
      if (receipt.state === 'conversation_saved' && receipt.reply) {
        await onRecovered(turn, {...receipt, response_photos:responsePhotoCards(receipt.response_photos)});
        finish(turn, receipt);
      }
    } catch { /* Keep the original turn available for an explicit retry. */ }
    if (current(turn)) render();
  }
  function clearDisplay() {
    active = null;
    for (const image of images.values()) {
      image.controller?.abort();
      if (image.url) URL.revokeObjectURL(image.url);
    }
    images.clear();
    const attachments = [...(state.attachments || []), ...(state.chat || []).flatMap(message => message.attachments || [])];
    for (const url of new Set(attachments.map(item => item.url).filter(Boolean))) URL.revokeObjectURL(url);
    state.attachments = [];
    state.attachmentRights = false;
    state.attachmentProgress = '';
  }
  async function bindImages(root, {path, errorText}) {
    const ownerScope = scope();
    for (const node of root.querySelectorAll('[data-private-response-photo]')) {
      const id = node.dataset.privateResponsePhoto;
      if (!/^[0-9a-f-]{36}$/i.test(id)) { node.alt = errorText; continue; }
      const cacheKey = `${ownerScope.ownerId}:${ownerScope.projectId}:${id}`;
      let entry = images.get(cacheKey);
      if (!entry) {
        entry = {controller:new AbortController()};
        images.set(cacheKey, entry);
        entry.promise = (async () => {
          const response = await fetch(path(`/v1/agent/projects/${encodeURIComponent(ownerScope.projectId)}/photos/${id}/content`), {
            headers:{Authorization:`Bearer ${state.supabase.accessToken}`}, signal:entry.controller.signal, cache:'no-store'});
          if (!response.ok || !/^image\/(jpeg|png|webp)(?:;|$)/i.test(response.headers.get('Content-Type') || '')) throw new Error('Photo unavailable');
          const blob = await response.blob();
          if (!current(ownerScope) || images.get(cacheKey) !== entry) return null;
          entry.url = URL.createObjectURL(blob);
          return entry.url;
        })().catch(() => null);
      }
      void entry.promise.then(url => {
        if (!current(ownerScope) || !node.isConnected) return;
        if (url) { node.src = url; node.hidden = false; }
        else { node.hidden = true; node.closest('figure')?.querySelector('[data-photo-unavailable]')?.removeAttribute('hidden'); }
      });
    }
  }
  return {prepare, pending, accept, finish, recover, clearDisplay, bindImages, cards:responsePhotoCards};
}
