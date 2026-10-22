import { historicalContext } from "./historical-news.mjs";

export function createConversationHistory({
  cleanAssistantText, state
}) {
  const CHAT_HISTORY_STORAGE_PREFIX = "memory-spark-chat-history:";

  let assistantMessageSequence = 0;

  function chatHistoryStorageKey(projectId = state.project?.id) {
    const ownerId = state.supabase?.user?.id;
    return projectId ? `${CHAT_HISTORY_STORAGE_PREFIX}${ownerId ? `${encodeURIComponent(ownerId)}:` : ""}${projectId}` : "";
  }

  function savedProjectStorageKey() {
    const ownerId = state.supabase?.user?.id;
    return `memory-spark-project${ownerId ? `:${encodeURIComponent(ownerId)}` : ""}`;
  }

  function readBrowserValues(key) {
    const values = [];
    for (const storage of [() => localStorage, () => sessionStorage]) {
      try {
        const value = storage().getItem(key);
        if (typeof value === "string") values.push(value);
      } catch { /* Try the tab cache when durable storage is unavailable. */ }
    }
    return values;
  }

  function readBrowserValue(key) {
    // A successful tab write can be newer than a readable durable value when
    // storage is full. Another tab can also make the durable pointer newer.
    let newest = null, updatedAt = -1;
    for (const value of readBrowserValues(key)) {
      let timestamp = 0;
      try { timestamp = Number(JSON.parse(value)?.updatedAt) || 0; } catch { /* Legacy raw pointer. */ }
      if (timestamp > updatedAt) { newest = value; updatedAt = timestamp; }
    }
    return newest;
  }

  function mergeChatHistoryCopies(copies) {
    const messages = [], positions = new Map();
    for (const copy of copies) {
      let saved;
      try { saved = JSON.parse(copy); } catch { continue; }
      if (!Array.isArray(saved)) continue;
      const occurrences = new Map();
      for (const item of saved) {
        if (!["user", "assistant"].includes(item?.role) || typeof item.text !== "string") continue;
        const signature = JSON.stringify([item.role, item.text]);
        const occurrence = occurrences.get(signature) || 0;
        occurrences.set(signature, occurrence + 1);
        const message = { ...item, cacheId: item.cacheId || `legacy:${signature}:${occurrence}` };
        const index = positions.get(message.cacheId);
        if (index === undefined) {
          positions.set(message.cacheId, messages.length);
          messages.push(message);
        } else if (!(messages[index].text.startsWith(message.text) && messages[index].text.length > message.text.length)
            && (message.text.startsWith(messages[index].text) && message.text.length > messages[index].text.length
              || (Number(message.updatedAt) || 0) >= (Number(messages[index].updatedAt) || 0))) {
          messages[index] = message;
        }
      }
    }
    return messages;
  }

  function saveBrowserValue(key, value) {
    for (const storage of [() => localStorage, () => sessionStorage]) {
      try { storage().setItem(key, value); } catch { /* The in-memory conversation remains usable. */ }
    }
  }

  function savedProjectId() {
    // A legacy pointer is only a recovery candidate. Authorize it before reading its history.
    const value = readBrowserValue(savedProjectStorageKey()) || readBrowserValue("memory-spark-project");
    try { return JSON.parse(value)?.projectId || value; } catch { return value; }
  }

  function rememberProject(projectId) {
    const key = savedProjectStorageKey();
    let updatedAt = Date.now();
    for (const value of readBrowserValues(key)) {
      try { updatedAt = Math.max(updatedAt, (Number(JSON.parse(value)?.updatedAt) || 0) + 1); } catch { /* Legacy pointer. */ }
    }
    saveBrowserValue(key, JSON.stringify({ projectId, updatedAt }));
  }

  function persistChatHistory() {
    if (state.projectPrincipalId && state.projectPrincipalId !== state.supabase?.user?.id) return;
    const key = chatHistoryStorageKey();
    if (!key) return;
    try {
      if (!state.chat.length) return;
      const messages = state.chat.filter((message) => !message.provisional && (message.text || message.error)).map((message) => {
        message.cacheId ||= globalThis.crypto?.randomUUID?.() || `message-${Date.now()}-${Math.random().toString(36).slice(2)}`;
        const saved = {
          cacheId: message.cacheId,
          id: message.id,
          role: message.role,
          text: message.role === "assistant" ? cleanAssistantText(message.text) : String(message.text || ""),
          error: message.error || "",
        };
        if (message.clientTurnId) saved.clientTurnId = message.clientTurnId;
        if (message.historicalContext) saved.historicalContext = historicalContext(message.historicalContext);
        if (message.responsePhotos?.length) saved.responsePhotos = state.photoTurns?.cards(message.responsePhotos);
        if (Array.isArray(message.cues) && message.cues.length) saved.cues = message.cues;
        if (Array.isArray(message.trace) && message.trace.length) {
          saved.trace = message.trace.map(({question_pool, ...step}) => step);
          saved.traceMode = message.traceMode;
        }
        if (message.action && typeof message.action === "object") {
          saved.action = { name: message.action.name, label: message.action.label };
        }
        const fingerprint = JSON.stringify(saved);
        // Rendering an unchanged old tab must not make its snapshot newer.
        if (message.cacheFingerprint && message.cacheFingerprint !== fingerprint) {
          message.updatedAt = Math.max(Date.now(), (Number(message.updatedAt) || 0) + 1);
        } else message.updatedAt ||= Date.now();
        message.cacheFingerprint = fingerprint;
        saved.updatedAt = message.updatedAt;
        return saved;
      });
      const provisional = state.chat.filter(message => message.provisional);
      const previous = mergeChatHistoryCopies([...readBrowserValues(key), JSON.stringify(messages)])
        .filter(saved => !provisional.some(message => message.cacheId && message.cacheId === saved.cacheId
          || message.clientTurnId && saved.role === 'assistant' && message.clientTurnId === saved.clientTurnId));
      saveBrowserValue(key, JSON.stringify(previous));
    } catch {
      // The conversation remains usable when browser storage is unavailable or full.
    }
  }

  function restoreChatHistory(projectId) {
    const key = chatHistoryStorageKey(projectId);
    if (!key) return [];
    try {
      const copies = readBrowserValues(key);
      if (!copies.length) {
        try { copies.push(sessionStorage.getItem(`${CHAT_HISTORY_STORAGE_PREFIX}${projectId}`) || "[]"); } catch { /* Optional legacy tab cache. */ }
      }
      const saved = mergeChatHistoryCopies(copies);
      const messages = saved
        .filter((message) => ["user", "assistant"].includes(message?.role) && typeof message.text === "string")
        .map((message) => {
          const action = message.action && typeof message.action === "object"
            && typeof message.action.name === "string"
            && /^[a-z-]+$/.test(message.action.name)
            && typeof message.action.label === "string"
            ? { name: message.action.name, label: message.action.label }
            : undefined;
          return {
            cacheId: typeof message.cacheId === "string" ? message.cacheId : undefined,
            updatedAt: Number(message.updatedAt) || 0,
            id: typeof message.id === "string" ? message.id : undefined,
            role: message.role,
            text: message.role === "assistant" ? cleanAssistantText(message.text) : message.text,
            error: typeof message.error === "string" ? message.error : "",
            clientTurnId: typeof message.clientTurnId === "string" ? message.clientTurnId : undefined,
            responsePhotos: state.photoTurns?.cards(message.responsePhotos),
            historicalContext: message.historicalContext ? historicalContext(message.historicalContext) : null,
            cues: Array.isArray(message.cues) ? message.cues : undefined,
            trace: Array.isArray(message.trace) ? message.trace : undefined,
            traceMode: typeof message.traceMode === "string" ? message.traceMode : undefined,
            action,
          };
        });
      const sequence = messages.reduce((highest, message) => {
        const match = message.id?.match(/^assistant-message-(\d+)$/);
        return match ? Math.max(highest, Number(match[1])) : highest;
      }, 0);
      assistantMessageSequence = Math.max(assistantMessageSequence, sequence);
      return messages;
    } catch {
      return [];
    }
  }

  function nextAssistantMessageId() {
    assistantMessageSequence += 1;
    return `assistant-message-${assistantMessageSequence}`;
  }

  return {
    nextAssistantMessageId, persistChatHistory, rememberProject, restoreChatHistory, savedProjectId
  };
}
