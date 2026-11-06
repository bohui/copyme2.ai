export function createAtlasUpdates({scope, current, token, url, onUpdate, onUnavailable = () => {}, request = fetch}) {
  let active, enabled = false;

  function stop() {
    active?.controller.abort();
    active = null;
    enabled = false;
  }

  function start() {
    const captured = scope(), accessToken = token();
    if (!captured?.projectId || !accessToken) return false;
    if (active && current(active.scope) && active.accessToken === accessToken) return false;
    stop();
    enabled = true;
    const job = {scope:captured, accessToken, controller:new AbortController()};
    active = job;
    const {signal} = job.controller;
    const watching = () => active === job && current(captured) && !signal.aborted;
    let hydrated = false;
    const fallbackRead = () => {
      if (!watching()) return;
      hydrated = true;
      onUnavailable();
    };
    const fallback = setTimeout(() => { if (!hydrated) fallbackRead(); }, 8_000);
    signal.addEventListener('abort', () => clearTimeout(fallback), {once:true});

    void (async () => {
      try {
        let retries = 0;
        while (watching()) {
          let opened;
          try {
            const response = await request(url(captured.projectId), {signal, headers:{
              Accept:'text/event-stream', Authorization:`Bearer ${accessToken}`}});
            if (!watching()) return;
            if ([400,401,403,404,422].includes(response.status)) return;
            if (!response.ok) throw new Error('Atlas connection unavailable');
            if (!response.body || !response.headers.get('Content-Type')?.startsWith('text/event-stream')) return;
            opened = Date.now();
            let buffer = '';
            for await (const chunk of response.body.pipeThrough(new TextDecoderStream())) {
              if (!watching()) return;
              buffer += chunk;
              const frames = buffer.split('\n\n');
              buffer = frames.pop();
              for (const frame of frames) {
                if (!watching()) return;
                const prefix = 'event: atlas-update\ndata: ';
                if (!frame.startsWith(prefix)) continue;
                const snapshot = JSON.parse(frame.slice(prefix.length));
                if (snapshot?.project_id !== captured.projectId) continue;
                hydrated = job.receiving = true;
                clearTimeout(fallback);
                await onUpdate(snapshot, captured);
              }
            }
          } catch { /* Retry an interrupted connection within this scope. */ }
          job.receiving = false;
          if (opened !== undefined && Date.now() - opened >= 15_000) retries = 0;
          if (!watching() || ++retries > 2) return;
          await new Promise(resolve => {
            const finish = () => {
              clearTimeout(timer);
              signal.removeEventListener('abort', finish);
              resolve();
            };
            const timer = setTimeout(finish, retries * 2_000);
            signal.addEventListener('abort', finish, {once:true});
          });
        }
      } finally {
        clearTimeout(fallback);
        if (!hydrated) fallbackRead();
        if (active === job) active = null;
      }
    })();
    return true;
  }

  return {start, stop, receiving: () => Boolean(active?.receiving), renew() { if (enabled) start(); }};
}
