import { escapeHtml } from "./dom.mjs";

export function mountStoryGame(root, game, t, useMarkup = false) {
  const texts = new Map(game.texts.map(item => [item.id, item.text]));
  const scenes = new Map(game.scenes.map(scene => [scene.id, scene]));
  let scene = scenes.get(game.start_scene_id), x = scene.spawn_x, direction = 0, frame = 0, last = 0;
  let dialogue = null, destroyed = false;
  if (!useMarkup) root.innerHTML = `<p class="game-framing">${escapeHtml(t("framing"))}</p>
    <div class="game-stage" tabindex="0" role="region" aria-label="${escapeHtml(t("movement"))}">
      <div class="game-world"><div class="game-player" aria-hidden="true"></div></div>
    </div><p class="game-scene-label" aria-live="polite"></p>
    <div class="game-controls" role="group" aria-label="${escapeHtml(t("controls"))}">
      <button type="button" data-game-move="-1" aria-label="${escapeHtml(t("left"))}">←</button>
      <button type="button" data-game-interact>${escapeHtml(t("interact"))}</button>
      <button type="button" data-game-move="1" aria-label="${escapeHtml(t("right"))}">→</button>
    </div><div class="game-dialogue" hidden role="status"></div>
    <details class="game-text-equivalent"><summary>${escapeHtml(t("textVersion"))}</summary></details>`;
  const stage = root.querySelector(".game-stage"), world = root.querySelector(".game-world");
  const player = root.querySelector(".game-player"), line = root.querySelector(".game-dialogue");
  const listeners = new AbortController();
  const on = (node, event, callback) => node.addEventListener(event, callback, { signal: listeners.signal });
  const npcButtons = new Map();
  root.querySelector(".game-framing").textContent = t("framing");
  stage.setAttribute("aria-label", t("movement"));
  for (const [selector, key] of [["[data-game-move='-1']", "left"], ["[data-game-move='1']", "right"],
    ["[data-game-interact]", "interact"], [".game-text-equivalent summary", "textVersion"]]) {
    root.querySelector(selector).textContent = t(key);
    root.querySelector(selector).setAttribute("aria-label", t(key));
  }
  const nearest = () => game.npcs.find(npc => npc.scene_id === scene.id && Math.abs(npc.x - x) < 130);

  function paint() {
    player.style.left = `${x}px`;
    const camera = Math.max(0, Math.min(scene.width - stage.clientWidth, x - stage.clientWidth / 2));
    world.style.transform = `translateX(${-Math.max(0, camera)}px)`;
    root.dataset.gameScene = scene.id;
    root.dataset.gamePosition = String(Math.round(x));
    for (const npc of game.npcs) {
      const button = npcButtons.get(npc.id);
      button.hidden = npc.scene_id !== scene.id;
      button.disabled = npc.scene_id !== scene.id || Math.abs(npc.x - x) >= 130;
    }
    root.querySelector("[data-game-interact]").disabled = !nearest();
  }
  function enter(id, spawn) {
    scene = scenes.get(id); x = Math.max(0, Math.min(scene.width - 40, spawn)); dialogue = null;
    world.style.width = `${scene.width}px`;
    stage.dataset.art = scene.asset_key;
    stage.dataset.sceneIndex = String(game.scenes.findIndex(item => item.id === scene.id));
    root.querySelector(".game-scene-label").textContent = texts.get(scene.title_text_id);
    line.hidden = true; paint();
  }
  function talk(npc = nearest()) {
    if (!npc) return;
    direction = 0;
    dialogue = npc.id;
    line.textContent = `${texts.get(npc.alias_text_id)} — ${npc.dialogue_text_ids.map(id => texts.get(id)).join(" ")}`;
    line.hidden = false;
  }
  for (const npc of game.npcs) {
    const button = document.createElement("button");
    button.type = "button"; button.className = "game-npc"; button.style.left = `${npc.x}px`;
    button.textContent = texts.get(npc.alias_text_id);
    on(button, "click", () => talk(npc)); world.append(button); npcButtons.set(npc.id, button);
  }
  const equivalent = root.querySelector(".game-text-equivalent");
  for (const item of game.scenes) {
    const section = document.createElement("section"), heading = document.createElement("h4");
    heading.textContent = texts.get(item.title_text_id); section.append(heading);
    for (const npc of game.npcs.filter(npc => npc.scene_id === item.id)) {
      const paragraph = document.createElement("p");
      paragraph.textContent = `${texts.get(npc.alias_text_id)} — ${npc.dialogue_text_ids.map(id => texts.get(id)).join(" ")}`;
      section.append(paragraph);
    }
    equivalent.append(section);
  }
  function tick(now) {
    if (destroyed) return;
    const seconds = Math.min(.05, (now - (last || now)) / 1000); last = now;
    if (direction && !dialogue) {
      x += direction * seconds * 420;
      if (x >= scene.width - 40 && scene.right) enter(scene.right.scene_id, scene.right.spawn_x);
      else if (x < 0 && scene.left) enter(scene.left.scene_id, scene.left.spawn_x);
      else x = Math.max(0, Math.min(scene.width - 40, x));
      paint();
    }
    frame = requestAnimationFrame(tick);
  }
  on(stage, "keydown", event => {
    if (["ArrowLeft", "ArrowRight", "a", "d"].includes(event.key)) {
      event.preventDefault(); dialogue = null; line.hidden = true;
      direction = ["ArrowLeft", "a"].includes(event.key) ? -1 : 1;
    } else if (["Enter", " ", "e"].includes(event.key)) { event.preventDefault(); talk(); }
    else if (event.key === "Escape") { dialogue = null; line.hidden = true; }
  });
  on(stage, "keyup", () => { direction = 0; });
  on(stage, "blur", () => { direction = 0; });
  for (const button of root.querySelectorAll("[data-game-move]")) {
    on(button, "pointerdown", event => {
      event.preventDefault(); button.setPointerCapture?.(event.pointerId);
      dialogue = null; line.hidden = true; direction = Number(button.dataset.gameMove);
    });
    for (const event of ["pointerup", "pointercancel", "lostpointercapture", "blur"]) on(button, event, () => { direction = 0; });
    on(button, "keydown", event => {
      if (["Enter", " "].includes(event.key)) {
        event.preventDefault(); dialogue = null; line.hidden = true; direction = Number(button.dataset.gameMove);
      }
    });
    on(button, "keyup", () => { direction = 0; });
  }
  on(root.querySelector("[data-game-interact]"), "click", () => talk());
  on(window, "blur", () => { direction = 0; });
  on(window, "resize", paint);
  enter(scene.id, x); frame = requestAnimationFrame(tick);
  return () => {
    destroyed = true; cancelAnimationFrame(frame); listeners.abort(); root.replaceChildren();
    delete root.dataset.gameScene; delete root.dataset.gamePosition;
  };
}


export function mountStoryGameWebpage(root, game, t, onClose) {
  if (game.novel_game) return mountNovelGameWebpage(root, game.novel_game, t, onClose);
  if (!game.webpage) return mountStoryGame(root, game, t);
  const frame = document.createElement("iframe");
  frame.className = "story-game-frame";
  frame.title = t("title");
  frame.setAttribute("sandbox", "allow-scripts");
  frame.referrerPolicy = "no-referrer";
  const nonce = crypto.randomUUID().replaceAll("-", "");
  const doc = new DOMParser().parseFromString(game.webpage, "text/html");
  const policy = doc.createElement("meta");
  policy.httpEquiv = "Content-Security-Policy";
  policy.content = `default-src 'none'; script-src 'nonce-${nonce}'; style-src 'unsafe-inline'; ` +
    "base-uri 'none'; form-action 'none'; frame-src 'none'; connect-src 'none'; object-src 'none'";
  doc.head.prepend(policy);
  const script = doc.createElement("script");
  script.setAttribute("nonce", nonce);
  const { webpage, ...data } = game;
  const labels = Object.fromEntries(["framing", "movement", "controls", "left", "right", "interact", "textVersion"].map(key => [key, t(key)]));
  const encode = value => JSON.stringify(value).replaceAll("<", "\\u003c");
  script.textContent = `const escapeHtml=${escapeHtml.toString()};const mountStoryGame=${mountStoryGame.toString()};
    const labels=${encode(labels)};const cleanup=mountStoryGame(document.getElementById("memoir-game"),${encode(data)},key=>labels[key],true);
    window.addEventListener("pagehide",cleanup,{once:true});
    document.addEventListener("keydown",event=>{if(event.key==="Escape")parent.postMessage({type:"memoir-game-close"},"*")});`;
  doc.body.append(script);
  frame.srcdoc = "<!doctype html>" + doc.documentElement.outerHTML;
  const listeners = new AbortController();
  window.addEventListener("message", event => {
    if (event.source === frame.contentWindow && event.data?.type === "memoir-game-close") onClose?.();
  }, { signal: listeners.signal });
  root.replaceChildren(frame);
  return () => { listeners.abort(); root.replaceChildren(); };
}


let novelRuntime;
export function mountNovelGameWebpage(root, game, t, onClose) {
  const frame = document.createElement("iframe"), listeners = new AbortController();
  let closed = false;
  frame.className = "story-game-frame"; frame.title = t("title");
  frame.setAttribute("sandbox", "allow-scripts"); frame.referrerPolicy = "no-referrer";
  root.textContent = t("title");
  if (!novelRuntime) novelRuntime = fetch("/api/v1/memoir/agent/story-game-runtime")
    .then(response => { if (!response.ok) throw new Error("Game runtime unavailable"); return response.json(); })
    .catch(error => { novelRuntime = null; throw error; });
  novelRuntime.then(runtime => {
    if (closed) return;
    const media = Object.fromEntries(Object.entries(runtime.media).map(([name, path]) => [name, new URL(path, location.origin).href]));
    const plan = structuredClone(game.plan), library = runtime.places;
    plan.stock_url = "";
    plan.audio = { theme: media["blue-gate-theme.mp3"], cue: media["memory-cue.mp3"] };
    plan.illustrations = [{ url: media.places, columns: library.columns, rows: library.rows,
      width: library.width, height: library.height, scenes: Object.keys(game.scene_bindings),
      cells: Object.fromEntries(Object.entries(game.scene_bindings).map(([id, cell]) => [id, library.cells.indexOf(cell)])) }];
    const encode = value => JSON.stringify(value).replaceAll("<", "\\u003c").replaceAll(">", "\\u003e").replaceAll("&", "\\u0026");
    const html = runtime.template.replace("<!-- MEMOIR_SOURCE -->", `<script id="memoir-source" type="application/json">${encode(game.source)}</script>`)
      .replace("<!-- MEMOIR_JOURNEY -->", `<script id="memoir-journey" type="application/json">${encode(plan)}</script>`);
    const doc = new DOMParser().parseFromString(html, "text/html"), nonce = crypto.randomUUID().replaceAll("-", "");
    const policy = doc.createElement("meta"); policy.httpEquiv = "Content-Security-Policy";
    const assetOrigin = location.origin + "/api/v1/memoir/agent/story-game-assets/";
    policy.content = `default-src 'none'; script-src 'nonce-${nonce}'; style-src 'unsafe-inline'; img-src ${assetOrigin}; media-src ${assetOrigin}; base-uri 'none'; form-action 'none'; frame-src 'none'; connect-src 'none'; object-src 'none'`;
    doc.head.prepend(policy);
    const style = doc.createElement("style");
    style.textContent = runtime.css.replace(/url\(([^)]+)\)/g, (_, name) => `url("${media[name.replaceAll(/["' ]/g, "")]}")`) + "\n" + game.css;
    doc.head.append(style);
    const script = doc.createElement("script"); script.setAttribute("nonce", nonce);
    script.textContent = runtime.javascript + '\n document.addEventListener("keydown", event => { if(event.key === "Escape" && !document.querySelector("dialog[open]")) parent.postMessage({type:"memoir-game-close"},"*"); }, {capture:true});';
    doc.body.append(script); frame.srcdoc = "<!doctype html>" + doc.documentElement.outerHTML;
    root.replaceChildren(frame);
  }).catch(() => { if (!closed) root.textContent = t("unavailable"); });
  window.addEventListener("message", event => {
    if (event.source === frame.contentWindow && event.data?.type === "memoir-game-close") onClose?.();
  }, { signal: listeners.signal });
  return () => { closed = true; listeners.abort(); root.replaceChildren(); };
}


export function rankSceneOptions(options) {
  const groups = new Map();
  for (const option of options) {
    if (!groups.has(option.life_stage)) groups.set(option.life_stage, []);
    groups.get(option.life_stage).push(option);
  }
  for (const group of groups.values()) group.sort((a, b) => Number(b.recommended) - Number(a.recommended));
  const ranked = [];
  for (let i = 0; ranked.length < options.length; i++) {
    for (const group of groups.values()) if (group[i]) ranked.push(group[i]);
  }
  return ranked;
}


export function createStoryGameDialog({ state, storyApi, captureProjectScope, isCurrentProjectScope, translate }) {
  let view = null;
  const t = key => translate(`Memoir.game.${key}`);
  const path = active => `/v1/agent/projects/${encodeURIComponent(active.scope.projectId)}`;
  const current = () => view && isCurrentProjectScope(view.scope);
  const request = (suffix, options = {}, active = view) => {
    if (view !== active || !isCurrentProjectScope(active.scope)) throw new DOMException("Closed", "AbortError");
    return storyApi(path(active) + suffix, { ...options, signal: active.controller.signal });
  };

  function clearRenderer() { view?.cleanup?.(); if (view) view.cleanup = null; }
  function clearPool(active) {
    active.pool = null; active.poolDigest = null; active.selected = new Set(); active.confirmed = false;
  }
  function close() {
    if (!view) return;
    const old = view; view = null;
    old.controller.abort(); old.cleanup?.(); clearInterval(old.poll);
    document.removeEventListener("visibilitychange", old.visibility);
    old.dialog.remove();
    (old.opener?.isConnected ? old.opener : document.querySelector("[data-story-game]"))?.focus();
  }
  function sync() {
    if (view && (!isCurrentProjectScope(view.scope)
        || state.currentInterviewMode?.mode !== "shape")) close();
  }
  async function refresh(active = view) {
    if (!current()) return close();
    const revision = active.revision;
    const before = JSON.stringify([active.status?.adaptation, active.status?.eligibility]);
    const status = await request("/story-game", {}, active);
    if (view !== active || !current() || active.revision !== revision) return;
    active.status = status;
    if (status.adaptation?.status === "stale") active.gameRequest = crypto.randomUUID();
    if (status.formal?.run?.status === "stale") active.formalRequest = crypto.randomUUID();
    const adaptation = view.status.adaptation;
    const after = JSON.stringify([adaptation, view.status.eligibility]);
    if (view.status.eligibility?.available && status.composer_ready !== false && adaptation?.game_id && adaptation.status === "published") {
      if (!view.content || before !== after) {
        const content = await request(`/story-game/${adaptation.game_id}`, {}, active);
        if (view !== active || !current() || active.revision !== revision) return;
        active.content = content;
      }
    } else {
      view.content = null; clearRenderer();
      if (adaptation?.pool_digest) {
        const plan = await request(`/story-game/${adaptation.game_id}`, {}, active);
        if (view !== active || !current() || active.revision !== revision) return;
        if (plan.pool && active.poolDigest !== plan.pool_digest) {
          active.pool = plan.pool;
          active.poolDigest = plan.pool_digest;
          active.selected = new Set(plan.selected_scene_ids || plan.pool.scenes.filter(s => s.recommended).map(s => s.id));
        }
        active.confirmed = !!plan.selected_scene_ids;
        if (active.confirmed) active.selected = new Set(plan.selected_scene_ids);
      } else clearPool(active);
    }
    if (before !== after || !view.rendered) draw();
  }
  async function action(callback) {
    if (!current() || view.busy) return;
    const active = view;
    active.revision++;
    active.busy = true; active.error = ""; draw();
    try { await callback(active); if (view === active && current()) await refresh(active); }
    catch (_) {
      if (view === active && current()) {
        active.error = t("retry"); clearRenderer(); active.content = null; clearPool(active);
        try { await refresh(active); if (active.content) active.error = ""; } catch (_) { /* Keep content withheld. */ }
      }
    }
    finally { if (view === active && current()) { active.busy = false; draw(); } }
  }
  async function completeMemoir(active) {
    let result = active.status.formal?.run;
    if (!result || !["pending", "running"].includes(result.status)) result = await request("/formal-memoir", {
      method: "POST", body: JSON.stringify({expected_revision: active.status.eligibility.revision || 0,
        request_id: active.formalRequest})}, active);
    for (let count = 0; view === active && current() && count < 16 && result.status !== "completed"; count++) {
      result = await request("/formal-memoir/advance", { method: "POST", body: JSON.stringify({run_id: result.run_id}) }, active);
    }
    if (result.status !== "completed") throw new Error("formal_pending");
  }
  async function generate(active) {
    if (!active.status.formal?.edition || active.status.eligibility.reasons.some(reason =>
        ["completion_required", "completion_stale"].includes(reason))) {
      await completeMemoir(active);
      active.status = await request("/story-game", {}, active);
    }
    const status = active.status, edition = status.formal.edition;
    if (status.eligibility.reasons.includes("adaptation_consent_required")) await request("/story-game/consent", {
      method:"PUT",body:JSON.stringify({edition_id:edition.edition_id,expected_digest:edition.manuscript_digest,
        expected_revision:status.eligibility.consent_revision,action:"grant"})}, active);
    await request("/story-game", {method:"POST",body:JSON.stringify({request_id:active.gameRequest})}, active);
  }
  async function revoke(active) {
    const status = active.status, edition = status.formal.edition;
    clearRenderer(); active.content = null;
    await request("/story-game/consent", {method:"PUT",body:JSON.stringify({edition_id:edition.edition_id,
      expected_digest:edition.manuscript_digest,expected_revision:status.eligibility.consent_revision,action:"revoke"})}, active);
  }
  async function confirmSelection(active) {
    await request(`/story-game/${active.status.adaptation.game_id}/selection`, {
      method: "POST", body: JSON.stringify({expected_pool_digest: active.poolDigest,
        scene_ids: active.pool.scenes.filter(s => active.selected.has(s.id)).map(s => s.id)})}, active);
  }
  function selectionMarkup(disabled) {
    const options = view.pool.scenes, groups = new Map();
    for (const option of options) {
      if (!groups.has(option.life_stage)) groups.set(option.life_stage, []);
      groups.get(option.life_stage).push(option);
    }
    const editingDisabled = view.confirmed ? "disabled" : disabled;
    return `<form data-scene-selection><h3>${escapeHtml(t("chooseScenes"))}</h3>
      <p>${escapeHtml(t("scenePoolIntro"))}</p><p class="game-cost-hint">${escapeHtml(t("sceneCost"))}</p>
      <label>${escapeHtml(t("sceneCount"))}<input data-scene-count type="number" min="1" max="${options.length}"
        value="${view.selected.size}" ${editingDisabled}></label>
      <button type="button" data-recommended-scenes ${editingDisabled}>${escapeHtml(t("useRecommended"))}</button>
      ${[...groups].map(([stage, scenes]) => `<fieldset ${editingDisabled}><legend>${escapeHtml(stage === "unplaced"
        ? translate("Memoir.workspace.unplacedStage") : translate(`Memoir.workspace.lifeStages.${stage}.label`))}</legend>
        ${scenes.map(s => `<div class="game-scene-option"><label><input type="checkbox" data-scene-option="${escapeHtml(s.id)}"
          ${view.selected.has(s.id) ? "checked" : ""}><span>${escapeHtml(s.title)}
          ${s.recommended ? `<small>${escapeHtml(t("recommended"))}</small>` : ""}</span></label>
          <p>${escapeHtml(s.reason)}</p><details><summary>${escapeHtml(t("viewPassage"))}</summary>
          <blockquote>${escapeHtml(s.quote)}</blockquote></details></div>`).join("")}</fieldset>`).join("")}
      <p data-selected-count role="status">${escapeHtml(t("selectedCount").replace("{count}", view.selected.size))}</p>
      <button type="submit" data-confirm-scenes ${disabled} ${view.selected.size ? "" : "disabled"}>${escapeHtml(t("confirmScenes"))}</button></form>`;
  }
  function bindSelection() {
    const form = view.body.querySelector("[data-scene-selection]");
    if (!form) return;
    const update = () => {
      form.querySelector("[data-scene-count]").value = view.selected.size;
      form.querySelector("[data-selected-count]").textContent = t("selectedCount").replace("{count}", view.selected.size);
      form.querySelector("[data-confirm-scenes]").disabled = view.busy || !view.selected.size;
    };
    form.addEventListener("submit", event => { event.preventDefault(); if (view.selected.size) void action(confirmSelection); });
    form.querySelector("[data-scene-count]").addEventListener("change", event => {
      const count = Math.min(view.pool.scenes.length, Math.max(1, Math.floor(Number(event.target.value) || 1)));
      view.selected = new Set(rankSceneOptions(view.pool.scenes).slice(0, count).map(s => s.id)); draw();
    });
    for (const input of form.querySelectorAll("[data-scene-option]")) input.addEventListener("change", () => {
      if (input.checked) view.selected.add(input.dataset.sceneOption); else view.selected.delete(input.dataset.sceneOption);
      update();
    });
    form.querySelector("[data-recommended-scenes]").addEventListener("click", () => {
      view.selected = new Set(view.pool.scenes.filter(s => s.recommended).map(s => s.id)); draw();
    });
  }
  function draw() {
    if (!view) return;
    clearRenderer(); view.rendered = true;
    const status = view.status, content = view.content;
    const building = status?.adaptation?.phase === "build" && status.adaptation.status === "running" && !status.adaptation.retryable;
    const disabled = view.busy || building ? "disabled" : "";
    let markup = `<p role="status">${escapeHtml(t("loading"))}</p>`;
    if (status) {
      if (status.composer_ready === false) {
        markup = `<p role="status">${escapeHtml(t("composerRequired"))}</p>`;
      } else if (content?.status === "published") {
        markup = `<a data-game-page-link href="/memoir/game/${encodeURIComponent(view.scope.projectId)}">${escapeHtml(t("openGamePage"))}</a>
          <div data-story-game-player></div><button type="button" class="text-button" data-revoke-game ${disabled}>${escapeHtml(t("revoke"))}</button>`;
      } else if (view.pool) {
        markup = `${building ? `<p role="status">${escapeHtml(t("loading"))}</p>` : ""}${selectionMarkup(disabled)}`;
      } else {
        markup = `<p>${escapeHtml(t("consentIntro"))}</p><form data-game-consent>
          <button type="submit" data-generate-game ${disabled}>${escapeHtml(t("generate"))}</button></form>`;
      }
    }
    view.body.innerHTML = `${view.busy ? `<p role="status">${escapeHtml(t("loading"))}</p>` : ""}
      ${view.error ? `<p role="alert">${escapeHtml(view.error)}</p>` : ""}${markup}`;
    view.body.querySelector("[data-game-consent]")?.addEventListener("submit", event => { event.preventDefault(); void action(generate); });
    view.body.querySelector("[data-revoke-game]")?.addEventListener("click", () => action(revoke));
    bindSelection();
    const root = view.body.querySelector("[data-story-game-player]");
    if (root && !document.hidden) view.cleanup = mountStoryGameWebpage(root, content.game, t, close);
  }
  async function open(opener) {
    close();
    const dialog = document.createElement("dialog"); dialog.className = "story-game-modal";
    dialog.setAttribute("aria-labelledby", "story-game-title");
    dialog.innerHTML = `<header><h2 id="story-game-title">${escapeHtml(t("title"))}</h2>
      <button type="button" data-close-game aria-label="${escapeHtml(t("close"))}">×</button></header><div class="story-game-body"></div>`;
    view = {scope:captureProjectScope(),dialog,body:dialog.querySelector(".story-game-body"),opener,
      controller:new AbortController(),formalRequest:crypto.randomUUID(),gameRequest:crypto.randomUUID(),
      busy:false,error:"",rendered:false,revision:0,polling:false,selected:new Set(),confirmed:false,visibility:() => {
        if (document.hidden) clearRenderer();
        else if (view) { view.content = null; view.rendered = false; void action(refresh); }
      }};
    dialog.querySelector("[data-close-game]").addEventListener("click", close);
    dialog.addEventListener("cancel", event => { event.preventDefault(); close(); });
    document.addEventListener("visibilitychange", view.visibility);
    window.addEventListener("popstate", close, {signal: view.controller.signal});
    window.addEventListener("pagehide", close, {signal: view.controller.signal});
    document.body.append(dialog); dialog.showModal(); draw();
    const active = view;
    await action(refresh);
    if (view === active) {
      view.poll = setInterval(() => {
        if (view !== active || view.busy || active.polling || document.hidden) return;
        const revision = active.revision;
        active.polling = true;
        void refresh(active).catch(() => {
          if (view === active && active.revision === revision) {
            clearRenderer(); active.content = null; clearPool(active); active.error = t("retry"); draw();
          }
        }).finally(() => { active.polling = false; });
      }, 15000);
    }
  }
  return {open,sync,close};
}
