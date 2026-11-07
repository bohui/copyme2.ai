// Keep each input until it is acknowledged. Only then may a later input stop its reply.
export function createConversationInputs({scope, current, run, busy, storage}) {
  let batch = null;
  const key = value => `memory-spark-conversation-inputs:${encodeURIComponent(value.ownerId || '')}:${encodeURIComponent(value.projectId || '')}`;
  const cache = () => storage || globalThis.sessionStorage;
  function save(owner) {
    try {
      if (owner.inputs.length) cache().setItem(key(owner.scope), JSON.stringify(owner.inputs));
      else cache().removeItem(key(owner.scope));
    } catch { /* In-memory delivery remains available when browser storage is full. */ }
  }
  function interrupt(owner) {
    if (owner.active?.accepted && !owner.active.saved && owner.inputs.length > owner.active.count)
      owner.active.controller.abort('superseded');
  }
  function drain(owner) {
    if (owner.task) return owner.task;
    busy(true);
    owner.task = (async () => {
      await Promise.resolve();
      try {
        while (batch === owner && current(owner.scope) && owner.inputs.length) {
          const first = owner.inputs[0];
          if (first.batchable && owner.inputs.length === 1)
            await new Promise(resolve => setTimeout(resolve, 250));
          if (batch !== owner || !current(owner.scope)) return;
          const inputs = [first];
          if (first.batchable) {
            const encoder = new TextEncoder();
            let bytes = encoder.encode(first.text).length;
            for (const next of owner.inputs.slice(1, 8)) {
              if (!next.batchable) break;
              bytes += 2 + encoder.encode(next.text).length;
              if (bytes > 16000) break;
              inputs.push(next);
            }
          }
          const active = {controller:new AbortController(), accepted:false, saved:false, count:inputs.length};
          owner.active = active;
          const result = await run(inputs.at(-1), {
            controller:active.controller,
            priorInputs:inputs.slice(0, -1),
            accepted() { active.accepted = true; interrupt(owner); },
            saved() { active.accepted = true; active.saved = true; },
          });
          if (batch !== owner || !current(owner.scope)) return;
          // Retain an uncertain input under its original ID for explicit retry/recovery.
          if (result?.failed && !active.accepted) return;
          owner.inputs.splice(0, inputs.length);
          owner.active = null;
          save(owner);
        }
      } finally {
        owner.task = null;
        if (batch === owner && current(owner.scope)) busy(false);
      }
    })();
    return owner.task;
  }
  function owner() {
    if (!batch || !current(batch.scope)) batch = {scope:scope(), inputs:[], active:null, task:null};
    return batch;
  }
  return {
    pending: () => Boolean(batch && current(batch.scope) && batch.inputs.length),
    inputs: () => batch && current(batch.scope) ? batch.inputs : [],
    enqueue(input) {
      const value = owner();
      value.inputs.push(input);
      save(value);
      interrupt(value);
      return drain(value);
    },
    restore() {
      const value = owner();
      if (value.inputs.length) return drain(value);
      try {
        const saved = JSON.parse(cache().getItem(key(value.scope)) || '[]');
        if (Array.isArray(saved)) value.inputs = saved.filter(input => typeof input?.id === 'string' && typeof input.text === 'string');
      } catch { /* Invalid or unavailable cache is optional. */ }
      if (value.inputs.length) return drain(value);
    },
    detach() {
      batch?.active?.controller.abort('navigation');
      batch = null;
    },
  };
}
