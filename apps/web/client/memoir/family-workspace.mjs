import { $, escapeHtml, formatText } from "./dom.mjs";
import { currentUiLocale, translate, translateWith } from "../i18n.js";
import { formatDateExpression } from "./dates.mjs";

export function createFamilyWorkspace({
  LIFE_STAGES, api, captureProjectScope, isCurrentProjectScope, lifeStageText, profile, referencesWorkspace,
  refreshPrivateDraft, refreshProject, render, state, storyApi, supabaseApi, toast
}) {
  const FAMILY_CHART_VERSION = "0.9.0";

  const VIS_TIMELINE_VERSION = "7.7.3";

  const visualizationLoadPromises = new Map();

  let familyChartMountId = 0;

  const familyCharts = new WeakMap();

  let timelineMountId = 0;

  function applyPersistedFamilyContext(context) {
    if (!context || typeof context !== "object") return;
    if (state.familyContext?.project_id === context.project_id
        && Number.isInteger(state.familyContext?.revision) && Number.isInteger(context.revision)
        && state.familyContext.revision > context.revision) return;
    const previous = state.familyContext?.project_id === context.project_id ? state.people : [];
    state.familyContext = context;
    state.people = Array.isArray(context.people) ? context.people.map(person => {
      const saved = previous.find(item => item.id === person.id && item.photo_path && item.photo_path === person.photo_path);
      return saved?.photo_url && !person.photo_url ? { ...person, photo_url: saved.photo_url } : person;
    }) : [];
    state.relationships = Array.isArray(context.relationships) ? context.relationships : [];
    if (state.memoryEventProject !== context.project_id) state.timeline = Array.isArray(context.timeline) ? context.timeline : [];
  }

  let memoryEventTimer = null;

  async function refreshFamilyContext() {
    const scope = captureProjectScope();
    if (!state.project?.id || !state.supabase?.accessToken) return null;
    const projectId = state.project.id;
    try {
      const body = state.familyFeaturesEnabled
        ? await supabaseApi(`/v1/agent/family-context?project_id=${encodeURIComponent(projectId)}`) : null;
      if (!isCurrentProjectScope(scope)) return null;
      if (body?.family_features_enabled === true && body.family_context) applyPersistedFamilyContext(body.family_context);
      const collection = state.familyFeaturesEnabled ? 'events' : 'map-events';
      const snapshot = await storyApi(`/v1/story/${collection}?project_id=${encodeURIComponent(projectId)}`);
      if (!isCurrentProjectScope(scope)) return null;
      if (Array.isArray(snapshot?.events)) {
        state.memoryEventProject = projectId;
        state.memoryEventPage = snapshot;
        state.timeline = snapshot.events.map(event => ({ ...event,
          date_expression: event.temporal?.expression || "unknown",
          start_expression: event.temporal?.legacy_start_expression || event.temporal?.expression || "unknown",
          end_expression: event.temporal?.legacy_end_expression || event.temporal?.year_end?.toString() || "unknown",
          precision: event.temporal?.precision || "unknown", canonical: true }));
        render();
        if (memoryEventTimer) clearTimeout(memoryEventTimer);
        if (snapshot.processing?.pending_inputs) memoryEventTimer = setTimeout(refreshFamilyContext, 15000);
      }
      return body?.family_context || null;
    } catch (failure) {
      if (failure.status === 403 && isCurrentProjectScope(scope)) {
        state.familyFeaturesEnabled = false;
        state.timeline = [];
        state.memoryEventPage = null;
        state.familyContext = null;
        state.people = [];
        state.relationships = [];
        state.memoryEventEdit = null;
        render();
      }
      return null;
    }
  }

  function loadVisualizationStylesheet(href) {
    const existing = Array.from(document.querySelectorAll("link[rel='stylesheet']")).some((link) => link.href === href);
    if (existing) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = href;
    link.dataset.memorySparkVisualization = href;
    document.head.appendChild(link);
  }

  function loadVisualizationScript(src) {
    if (visualizationLoadPromises.has(src)) return visualizationLoadPromises.get(src);
    const promise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = src;
      script.async = true;
      script.dataset.memorySparkVisualization = src;
      script.onload = () => resolve();
      script.onerror = () => reject(new Error(`Unable to load visualization renderer: ${src}`));
      document.head.appendChild(script);
    });
    visualizationLoadPromises.set(src, promise);
    return promise;
  }

  async function loadFamilyChartRenderer() {
    if (globalThis.f3?.createChart) return globalThis.f3;
    loadVisualizationStylesheet(`https://unpkg.com/family-chart@${FAMILY_CHART_VERSION}/dist/styles/family-chart.css`);
    if (!globalThis.d3) await loadVisualizationScript("https://unpkg.com/d3@7.9.0/dist/d3.min.js");
    await loadVisualizationScript(`https://unpkg.com/family-chart@${FAMILY_CHART_VERSION}/dist/family-chart.min.js`);
    if (!globalThis.f3?.createChart) throw new Error("Family chart renderer is unavailable");
    return globalThis.f3;
  }

  async function loadVisTimelineRenderer() {
    if (globalThis.vis?.Timeline) return globalThis.vis;
    loadVisualizationStylesheet(`https://unpkg.com/vis-timeline@${VIS_TIMELINE_VERSION}/styles/vis-timeline-graph2d.min.css`);
    await loadVisualizationScript(`https://unpkg.com/vis-timeline@${VIS_TIMELINE_VERSION}/standalone/umd/vis-timeline-graph2d.min.js`);
    if (!globalThis.vis?.Timeline) throw new Error("Timeline renderer is unavailable");
    return globalThis.vis;
  }

  function familyChartData() {
    const records = state.people
      .filter((person) => person?.id && person?.name)
      .map((person) => {
        const parts = String(person.name).trim().split(/\s+/).filter(Boolean);
        const data = {
          "first name": parts.shift() || person.name,
          "last name": parts.join(" "),
          gender: person.gender || "U",
        };
        if (person.family_title) data["family title"] = person.family_title;
        if (person.birth_date_expression) data.birthday = person.birth_date_expression;
        return { id: String(person.id), data, rels: { parents: [], children: [], spouses: [] } };
      });
    const byId = new Map(records.map((record) => [record.id, record]));
    const connect = (record, key, targetId) => {
      if (record && !record.rels[key].includes(targetId)) record.rels[key].push(targetId);
    };
    state.relationships.forEach((relation) => {
      const fromId = String(relation?.from_person_id || "");
      const toId = String(relation?.to_person_id || "");
      const from = byId.get(fromId);
      const to = byId.get(toId);
      if (!from || !to) return;
      switch (relation.relationship_type) {
        case "parent":
        case "adoptive_parent":
        case "step_parent":
          connect(from, "children", toId);
          connect(to, "parents", fromId);
          break;
        case "child":
        case "adopted_child":
        case "step_child":
          connect(from, "parents", toId);
          connect(to, "children", fromId);
          break;
        case "spouse":
          connect(from, "spouses", toId);
          connect(to, "spouses", fromId);
          break;
        default:
          break;
      }
    });
    return records;
  }

  function timelineDate(expression, end = false) {
    if (typeof expression !== "string") return null;
    const cleaned = expression.trim();
    const exact = cleaned.match(/\b(\d{4})[-/](\d{1,2})(?:[-/](\d{1,2}))?\b/);
    if (exact) {
      const month = String(Number(exact[2])).padStart(2, "0");
      const day = String(Number(exact[3] || (end ? 28 : 1))).padStart(2, "0");
      return `${exact[1]}-${month}-${day}`;
    }
    const year = cleaned.match(/\b([12]\d{3})\b/);
    if (!year) return null;
    return `${year[1]}-${end ? "12-31" : "07-01"}`;
  }

  function timelineRendererItems() {
    return state.timeline.map((item) => ({
      id: String(item.id),
      content: escapeHtml(item.title),
      start: timelineDate(item.kind === "period" ? item.start_expression : item.date_expression),
      end: item.kind === "period" ? timelineDate(item.end_expression, true) : null,
      className: item.kind === "period" ? "memoir-period" : "memoir-event",
    }))
      .filter((item) => item.start)
      .map((item) => (item.end && item.end <= item.start ? { ...item, end: null } : item));
  }

  async function mountFamilyChartAdapter(container) {
    try {
      const data = familyChartData();
      if (!data.length) return;
      const f3 = await loadFamilyChartRenderer();
      if (!document.body.contains(container)) return;
      const mount = document.createElement("div");
      mount.className = "family-chart-library f3";
      mount.id = `family-chart-renderer-${familyChartMountId += 1}`;
      mount.setAttribute("aria-label", translate("Memoir.workspace.familyChart"));
      container.insertBefore(mount, container.querySelector(".family-chart-fallback"));
      const chart = f3.createChart(`#${mount.id}`, data);
      chart.setSingleParentEmptyCard(false);
      chart.setShowSiblingsOfMain(true);
      chart.setCardXSpacing(210);
      chart.setCardYSpacing(230);
      const author = familyAuthor();
      if (author) chart.updateMainId(String(author.id));
      chart.setCardHtml()
        .setCardInnerHtmlCreator((datum) => familyPersonCard(state.people.find(person => String(person.id) === datum.data.id)))
        .setOnCardClick((event, datum) => selectFamilyPerson(datum.data.id));
      chart.updateTree({ initial: true, transition_time: 0, tree_position: "fit" });
      familyCharts.set(container, { chart, f3 });
      container.querySelectorAll("[data-family-zoom]").forEach(button => { button.disabled = false; });
      const renderedIds = new Set(Array.from(mount.querySelectorAll("[data-family-person]"), button => button.dataset.familyPerson));
      const fallback = container.querySelector(".family-chart-fallback");
      fallback?.querySelectorAll("[data-family-person]").forEach(button => {
        if (renderedIds.has(button.dataset.familyPerson)) button.remove();
      });
      if (fallback) {
        fallback.hidden = !fallback.querySelector("[data-family-person]");
        if (!fallback.hidden) fallback.insertAdjacentHTML("afterbegin", `<p class="family-chart-hint">${escapeHtml(translate("Memoir.workspace.familyUnlinked"))}</p>`);
      }
      mount.dataset.libraryMounted = "family-chart";
      container.dataset.rendererStatus = "family-chart";
    } catch (error) {
      container.querySelector(".family-chart-library")?.remove();
      container.dataset.rendererStatus = "fallback";
      console.warn("Family chart renderer unavailable; using the accessible person cards.", error);
    }
  }

  async function mountVisTimelineAdapter(container) {
    try {
      const items = timelineRendererItems();
      if (!items.length) return;
      const vis = await loadVisTimelineRenderer();
      if (!document.body.contains(container)) return;
      const mount = document.createElement("div");
      mount.className = "vis-timeline-library";
      mount.id = `vis-timeline-renderer-${timelineMountId += 1}`;
      mount.setAttribute("aria-hidden", "true");
      container.appendChild(mount);
      const dataset = vis.DataSet ? new vis.DataSet(items) : items;
      new vis.Timeline(mount, dataset, {
        stack: true,
        zoomMin: 31_536_000_000,
        orientation: "top",
        height: "280px",
        margin: { item: 12, axis: 8 },
      });
      mount.dataset.libraryMounted = "vis-timeline";
      container.dataset.rendererStatus = "vis-timeline";
    } catch (error) {
      container.dataset.rendererStatus = "fallback";
      console.warn("Timeline renderer unavailable; using the accessible list.", error);
    }
  }

  function initFamilyVisualizations() {
    const family = document.querySelector("[data-renderer='family-chart']");
    const timeline = document.querySelector("[data-renderer='vis-timeline']");
    if (family) mountFamilyChartAdapter(family);
    if (timeline) mountVisTimelineAdapter(timeline);
  }

  async function loadMoreMemoryEvents() {
    const scope = captureProjectScope();
    const saved = state.memoryEventPage;
    if (!saved?.next_cursor || saved.loading_page) return;
    saved.loading_page = true;
    saved.page_error = false;
    render();
    try {
      const query = new URLSearchParams({project_id: state.project.id, cursor: saved.next_cursor});
      const collection = state.familyFeaturesEnabled ? 'events' : 'map-events';
      const page = await storyApi(`/v1/story/${collection}?${query}`);
      if (!isCurrentProjectScope(scope) || state.memoryEventPage !== saved) return;
      const known = new Set(state.timeline.map(event => event.id));
      state.timeline.push(...(page.events || []).filter(event => !known.has(event.id)).map(event => ({...event,
        date_expression: event.temporal?.expression || "unknown",
        start_expression: event.temporal?.legacy_start_expression || event.temporal?.expression || "unknown",
        end_expression: event.temporal?.legacy_end_expression || event.temporal?.year_end?.toString() || "unknown",
        precision: event.temporal?.precision || "unknown", canonical: true})));
      saved.next_cursor = page.next_cursor || null;
      saved.complete = page.complete === true;
    } catch (_) {
      if (isCurrentProjectScope(scope) && state.memoryEventPage === saved) saved.page_error = true;
    } finally {
      saved.loading_page = false;
      if (isCurrentProjectScope(scope) && state.memoryEventPage === saved) render();
    }
  }

  async function loadMoreEventEvidence(eventId) {
    const scope = captureProjectScope();
    const saved = state.memoryEventPage;
    const event = state.timeline.find(item => item.id === eventId);
    if (!state.familyFeaturesEnabled || !event?.evidence_next_cursor || event.loading_evidence) return;
    event.loading_evidence = true;
    event.evidence_error = false;
    render();
    try {
      const query = new URLSearchParams({cursor: event.evidence_next_cursor});
      const page = await storyApi(`/v1/story/events/${encodeURIComponent(state.project.id)}/${encodeURIComponent(eventId)}/sources?${query}`);
      if (!isCurrentProjectScope(scope) || state.memoryEventPage !== saved) return;
      event.source_refs.push(...(page.source_refs || []));
      event.evidence_next_cursor = page.next_cursor || null;
      event.evidence_complete = page.complete === true;
    } catch (_) {
      if (isCurrentProjectScope(scope) && state.memoryEventPage === saved) event.evidence_error = true;
    } finally {
      event.loading_evidence = false;
      if (isCurrentProjectScope(scope) && state.memoryEventPage === saved) render();
    }
  }

  async function loadMoreEventDetails(eventId) {
    const scope = captureProjectScope();
    const saved = state.memoryEventPage;
    const event = state.timeline.find(item => item.id === eventId);
    if (!state.familyFeaturesEnabled || !event || event.details_complete || event.loading_details) return;
    event.loading_details = true;
    event.details_error = false;
    render();
    try {
      const query = new URLSearchParams();
      if (event.details_next_cursor) query.set('cursor', event.details_next_cursor);
      const page = await storyApi(`/v1/story/events/${encodeURIComponent(state.project.id)}/${encodeURIComponent(eventId)}/details?${query}`);
      if (!isCurrentProjectScope(scope) || state.memoryEventPage !== saved) return;
      event.detail_records = [...(event.detail_records || []), ...(page.details || [])];
      event.details_next_cursor = page.next_cursor || null;
      event.details_complete = page.complete === true;
    } catch (_) {
      if (isCurrentProjectScope(scope) && state.memoryEventPage === saved) event.details_error = true;
    } finally {
      event.loading_details = false;
      if (isCurrentProjectScope(scope) && state.memoryEventPage === saved) render();
    }
  }

  function familyWorkspace() {
    const t = (key) => escapeHtml(translate(`Memoir.workspace.${key}`));
    const people = state.people.filter(person => person?.id && person?.name);
    const fallback = people.length ? `<div class="family-chart-fallback">${people.map(familyPersonCard).join("")}</div>` : `<div class="workspace-empty"><span>♧</span><p>${t("peopleEmpty")}</p></div>`;
    return `<div class="workspace-scroll family-workspace"><div class="workspace-intro"><div class="workspace-heading-row"><div><h2>${t("family")}</h2><p>${t("familyIntro")}</p></div><button class="button button-secondary button-small" data-action="add-person">${t("addPerson")}</button></div></div><div class="family-chart-adapter" data-renderer="family-chart" aria-label="${t("familyChart")}"><div class="family-chart-toolbar"><span class="eyebrow">${t("familyChart")}</span><div class="family-chart-controls" role="group" aria-label="${t("familyZoomControls")}"><button type="button" data-family-zoom="out" disabled aria-label="${t("familyZoomOut")}" title="${t("familyZoomOut")}">−</button><button type="button" data-family-zoom="in" disabled aria-label="${t("familyZoomIn")}" title="${t("familyZoomIn")}">+</button><button type="button" class="family-chart-fit" data-family-zoom="fit" disabled>${t("familyZoomFit")}</button></div></div>${fallback}</div><div id="family-person-detail" aria-live="polite">${familyPersonDetail()}</div><div class="reference-note">${t("familyReferenceNote")}</div>${referencesWorkspace()}</div>`;
  }

  function familyAuthor() {
    const normalize = value => String(value || "").normalize("NFKC").trim().replace(/\s+/g, " ").toLocaleLowerCase();
    const name = normalize(profile().name);
    const matches = name ? state.people.filter(person => [person.name, person.chinese_name, ...(person.aliases || [])].some(alias => normalize(alias) === name)) : [];
    if (matches.length) return matches.length === 1 ? matches[0] : null;
    const self = state.people.filter(person => ["self", "me", "author", "storyteller", "我", "本人", "作者"].includes(normalize(person.family_title)));
    return self.length === 1 ? self[0] : null;
  }

  function familyPersonCard(person) {
    if (!person) return "";
    const author = familyAuthor()?.id === person.id;
    const selected = state.selectedFamilyPerson?.projectId === state.project?.id && state.selectedFamilyPerson?.id === String(person.id);
    const label = translateWith("Memoir.workspace.familyPersonOpen", { name: person.name });
    return `<button type="button" class="card-inner family-person-card${author ? " is-author" : ""}" data-family-person="${escapeHtml(person.id)}" aria-label="${escapeHtml(label)}" aria-controls="family-person-detail" aria-pressed="${selected}">${familyPersonPortrait(person)}<strong>${escapeHtml(person.name)}</strong>${author ? `<span class="family-author-badge">${escapeHtml(translate("Memoir.workspace.familyAuthor"))}</span>` : `<small>${escapeHtml(person.family_title || "")}</small>`}</button>`;
  }

  function familyPhotoUrl(person) {
    try {
      const url = new URL(person.photo_url);
      return ["https:", "http:"].includes(url.protocol) ? url.href : "";
    } catch { return ""; }
  }

  function familyPersonPortrait(person) {
    const url = familyPhotoUrl(person);
    return `<span class="family-person-portrait" aria-hidden="true"><span>${escapeHtml(Array.from(person.name)[0] || "?")}</span>${url ? `<img src="${escapeHtml(url)}" alt="" referrerpolicy="no-referrer" data-family-portrait>` : ""}</span>`;
  }

  function familyPersonDetail() {
    const selected = state.selectedFamilyPerson;
    const person = selected?.projectId === state.project?.id && state.people.find(person => String(person.id) === selected.id);
    const t = (key, values = {}) => escapeHtml(translateWith(`Memoir.workspace.${key}`, values));
    if (!person) return `<p class="family-person-prompt">${t("familyPersonHint")}</p>`;
    const facts = [["familyPersonAliases", (person.aliases || []).join(" · ")], ["familyPersonBirth", person.birth_date_expression], ["familyPersonDeath", person.death_date_expression]]
      .filter(([, value]) => value).map(([label, value]) => `<div><dt>${t(label)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("");
    const task = state.familyPhotoTask?.projectId === selected.projectId && state.familyPhotoTask?.id === selected.id ? state.familyPhotoTask : null;
    const busy = state.familyPhotoTask?.busy;
    const hasPhoto = Boolean(person.photo_path || familyPhotoUrl(person));
    const controls = state.familyFeaturesEnabled && state.supabase?.accessToken ? `<div class="family-photo-editor"><div class="family-photo-actions"><input type="file" id="family-person-photo" accept="image/jpeg,image/png,image/webp" hidden><button type="button" class="button button-secondary button-small" data-family-photo-upload ${busy ? "disabled" : ""}>${t(hasPhoto ? "familyPhotoReplace" : "familyPhotoAdd")}</button>${hasPhoto ? `<button type="button" class="text-button" data-family-photo-remove ${busy ? "disabled" : ""}>${t("familyPhotoRemove")}</button>` : ""}</div><p class="family-photo-hint">${t("familyPhotoHint")}</p>${task?.message ? `<p class="family-photo-status${task.error ? " is-error" : ""}" role="${task.error ? "alert" : "status"}">${t(task.message)}</p>` : ""}</div>` : "";
    return `<section class="family-person-detail" aria-labelledby="family-person-name" aria-busy="${Boolean(task?.busy)}"><div class="family-person-heading">${familyPersonPortrait(person)}<div class="family-person-heading-text"><span class="eyebrow">${t("familyPersonIntroduction")}</span><h3 id="family-person-name" tabindex="-1">${escapeHtml(person.name)}</h3>${familyAuthor()?.id === person.id ? `<span class="family-author-badge">${t("familyAuthor")}</span>` : ""}</div><button type="button" class="text-button" data-family-person-close aria-label="${t("familyPersonClose")}">×</button></div>${controls}${person.introduction ? `<p class="family-person-introduction">${formatText(person.introduction)}</p>` : `<p class="family-person-introduction">${t("familyPersonIntroductionEmpty", { name: person.name })}</p>`}${facts ? `<dl class="family-person-facts">${facts}</dl>` : ""}</section>`;
  }

  function updateFamilyPersonViews() {
    const focused = document.activeElement;
    const focusSelector = focused?.matches("[data-family-photo-upload]") ? "[data-family-photo-upload]" : focused?.matches("[data-family-photo-remove]") ? "[data-family-photo-remove]" : null;
    document.querySelectorAll("[data-family-person]").forEach(button => {
      const person = state.people.find(item => String(item.id) === button.dataset.familyPerson);
      if (person) button.outerHTML = familyPersonCard(person);
    });
    const detail = document.querySelector("#family-person-detail");
    if (detail) detail.innerHTML = familyPersonDetail();
    if (focusSelector) document.querySelector(focusSelector)?.focus({ preventScroll: true });
  }

  async function saveFamilyPersonPhoto(file = null) {
    const selected = state.selectedFamilyPerson;
    const person = selected?.projectId === state.project?.id && state.people.find(item => String(item.id) === selected.id);
    if (!person || state.familyPhotoTask?.busy || !state.supabase?.accessToken || !state.familyFeaturesEnabled) return;
    const task = { ...selected, ownerId: state.supabase.user?.id, busy: false, message: null, error: false };
    state.familyPhotoTask = task;
    if (file && !["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
      task.message = "familyPhotoInvalidType";
      task.error = true;
      updateFamilyPersonViews();
      return;
    }
    if (file && (!file.size || file.size > 10 * 1024 * 1024)) {
      task.message = "familyPhotoTooLarge";
      task.error = true;
      updateFamilyPersonViews();
      return;
    }
    task.busy = true;
    task.message = file ? "familyPhotoSaving" : "familyPhotoRemoving";
    updateFamilyPersonViews();
    try {
      const result = await supabaseApi(`/v1/agent/family-context/${encodeURIComponent(task.projectId)}/people/${encodeURIComponent(task.id)}/photo`, file ? { method: "PUT", body: file, headers: { "Content-Type": file.type } } : { method: "DELETE" });
      if (state.project?.id !== task.projectId || state.supabase?.user?.id !== task.ownerId) return;
      if (!result?.person || String(result.person.id) !== task.id) throw new Error("Missing saved person");
      if (Number.isInteger(state.familyContext?.revision) && state.familyContext.revision > result.revision) {
        await refreshFamilyContext();
      } else {
        state.people = state.people.map(item => {
          if (String(item.id) !== task.id) return item;
          const { photo_path, photo_url, ...previous } = item;
          return { ...previous, ...result.person };
        });
        if (state.familyContext) state.familyContext = { ...state.familyContext, people: state.people, revision: result.revision };
      }
      task.message = file ? "familyPhotoSaved" : "familyPhotoRemoved";
    } catch {
      if (state.project?.id !== task.projectId || state.supabase?.user?.id !== task.ownerId) return;
      // Check the persisted result before allowing a retry after an uncertain save.
      await refreshFamilyContext();
      task.message = "familyPhotoFailed";
      task.error = true;
    } finally {
      task.busy = false;
      if (state.project?.id === task.projectId && state.supabase?.user?.id === task.ownerId) {
        updateFamilyPersonViews();
        if (state.selectedFamilyPerson?.id === task.id) document.querySelector("[data-family-photo-upload]")?.focus({ preventScroll: true });
      }
    }
  }

  function zoomFamilyChart(action) {
    const container = document.querySelector(".family-chart-adapter");
    const renderer = familyCharts.get(container);
    if (!renderer) return;
    if (action === "fit") renderer.chart.updateTree({ transition_time: 0, tree_position: "fit" });
    else renderer.f3.handlers.manualZoom({ amount: action === "in" ? 1.25 : 0.8, svg: renderer.chart.svg, transition_time: 0 });
  }

  function selectFamilyPerson(id) {
    if (!state.people.some(person => String(person.id) === String(id))) return;
    state.selectedFamilyPerson = { projectId: state.project?.id, id: String(id) };
    const detail = document.querySelector("#family-person-detail");
    if (detail) detail.innerHTML = familyPersonDetail();
    document.querySelectorAll("[data-family-person]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.familyPerson === String(id))));
    document.querySelector("#family-person-name")?.focus({ preventScroll: true });
    detail?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  function closeFamilyPerson() {
    const id = state.selectedFamilyPerson?.id;
    state.selectedFamilyPerson = null;
    const detail = document.querySelector("#family-person-detail");
    if (detail) detail.innerHTML = familyPersonDetail();
    document.querySelectorAll("[data-family-person]").forEach(button => {
      button.setAttribute("aria-pressed", "false");
      if (button.dataset.familyPerson === id) button.focus({ preventScroll: true });
    });
  }

  function timelineWorkspace() {
    const t = (key, values = {}) => escapeHtml(translateWith(`Memoir.workspace.${key}`, values));
    const items = state.timeline.length ? state.timeline.map((item) => {
      const period = item.kind === "period";
      const date = period ? item.start_expression : item.date_expression;
      const start = formatDateExpression(date, currentUiLocale()) || translate("Memoir.workspace.dateUnknown");
      let details;
      if (period) {
        const end = formatDateExpression(item.end_expression, currentUiLocale()) || translate("Memoir.workspace.dateUnknown");
        details = `${escapeHtml(start)} → ${escapeHtml(end)}`;
      } else {
        const precisionKey = { approximate: "precision.approximate", range: "precision.range", exact: "precision.exact", year: "precision.year", decade: "precision.decade", month: "precision.month", day: "precision.day", season: "precision.season", age: "precision.age" }[item.precision];
        const precision = precisionKey ? t("datePrecision", { precision: t(precisionKey) }) : t("dateUnknown");
        const place = item.place ? ` · ${item.place}` : "";
        details = `${escapeHtml(start)} · ${precision}${escapeHtml(place)}`;
      }
      const stage = item.life_stage ? (item.life_stage === "unplaced" ? t("unplacedStage") : escapeHtml(lifeStageText(item.life_stage,"label"))) : "";
      const edit = item.canonical && state.familyFeaturesEnabled ? `<button type="button" class="text-button" data-edit-memory-event="${escapeHtml(item.id)}">${t("editEventTags")}</button>` : "";
      const explore = item.canonical && item.status === "active" ? `<button type="button" class="text-button" data-explore-workspace-memory="${escapeHtml(item.id)}" ${state.loading || state.recallStatus?.payment_required ? "disabled" : ""}>${t("exploreThisMemory")}</button>` : "";
      const evidence = item.canonical && item.source_refs?.length ? `<details><summary>${t("eventOriginalEvidence")}</summary>${item.source_refs.map(ref => `<p>${escapeHtml(ref.quote || "")}</p>`).join("")}${item.evidence_next_cursor ? `<button type="button" class="text-button" data-more-event-evidence="${escapeHtml(item.id)}" ${item.loading_evidence ? "disabled" : ""}>${t(item.loading_evidence ? "loadingSavedPage" : "loadMoreEvidence")}</button>` : ""}${item.evidence_error ? `<p role="status">${t("savedPageChanged")}</p>` : ""}</details>` : "";
      const uncertainty = [item.uncertainty, item.assertion === "inferred" ? t("eventInferred") : "", item.status === "unresolved" ? t("eventUnresolved") : "", item.timing_conflict ? t("eventConflictingDates") : ""].filter(Boolean);
      const contextRecords = (item.detail_records || []).map(record => `<p>${t(`eventDetailKinds.${record.kind}`)}: ${escapeHtml(typeof record.value === "string" ? record.value : record.value?.expression || `${record.value?.kind || ""} ${record.value?.event_id || ""}`)}</p>`).join("");
      const contextButton = item.details_complete === false ? `<button type="button" class="text-button" data-more-event-details="${escapeHtml(item.id)}" ${item.loading_details ? "disabled" : ""}>${t(item.loading_details ? "loadingSavedPage" : "loadMoreEventContext")}</button>` : "";
      const qualifications = `${uncertainty.map(note => `<p class="event-uncertainty">${escapeHtml(note)}</p>`).join("")}${contextRecords}${contextButton}${item.details_error ? `<p role="status">${t("savedPageChanged")}</p>` : ""}`;
      return `<article class="timeline-row"><span class="timeline-dot"></span><div><strong>${escapeHtml(item.title)}</strong><small>${details}${stage ? ` · ${stage}` : ""}</small>${qualifications}${explore}${edit}${evidence}${state.memoryEventEdit?.id === item.id ? memoryEventEditForm() : ""}</div></article>`;
    }).join("") : `<div class="workspace-empty"><span>⌁</span><p>${t("momentsEmpty")}</p></div>`;
    const page = state.memoryEventPage;
    const pagination = page?.next_cursor ? `<p role="status">${t("timelinePagesPartial")}</p><button type="button" class="button button-secondary button-small" data-action="load-more-memory-events" ${page.loading_page ? "disabled" : ""}>${t(page.loading_page ? "loadingSavedPage" : "loadMoreEvents")}</button>` : "";
    const pageError = page?.page_error ? `<p role="status">${t("savedPageChanged")}</p><button type="button" class="text-button" data-action="refresh-memory-events">${t("reloadSavedPages")}</button>` : "";
    return `<div class="workspace-scroll"><div class="workspace-intro"><div class="workspace-heading-row"><div><h2>${t("timeline")}</h2><p>${t("timelineIntro")}</p></div><button class="button button-secondary button-small" data-add-workspace-memory ${state.loading || state.recallStatus?.payment_required ? "disabled" : ""}>${t("addMemory")}</button></div></div><div class="vis-timeline-adapter" data-renderer="vis-timeline" aria-label="${t("timelineFallback")}"><div class="timeline-list">${items}</div></div>${pagination}${pageError}${referencesWorkspace()}</div>`;
  }

  function memoryEventEditForm() {
    const edit = state.memoryEventEdit;
    const t = key => escapeHtml(translate(`Memoir.workspace.${key}`));
    const field = (name,label,type="text") => `<label>${t(label)}<input id="event-${name}" name="${name}" type="${type}" value="${escapeHtml(edit[name] ?? "")}" ${type === "number" ? 'min="1" max="9999"' : 'maxlength="500"'} /></label>`;
    const stages = [...LIFE_STAGES.map(stage => [stage.id,lifeStageText(stage.id,"label")]),["unplaced",translate("Memoir.workspace.unplacedStage")]];
    const precisions = ["unknown","day","month","year","range","approximate","age","season"];
    return `<form id="memory-event-edit-form" class="memory-event-edit-form"><label>${t("eventLifeStage")}<select id="event-life-stage" name="life-stage">${stages.map(([id,label]) => `<option value="${id}"${edit["life-stage"] === id ? " selected" : ""}>${escapeHtml(label)}</option>`).join("")}</select></label>${field("date-expression","eventDateExpression")}<label>${t("eventDatePrecision")}<select id="event-date-precision" name="date-precision">${precisions.map(id => `<option value="${id}"${edit["date-precision"] === id ? " selected" : ""}>${id === "unknown" ? t("dateUnknown") : t(`precision.${id}`)}</option>`).join("")}</select></label>${field("year-start","eventYearStart","number")}${field("year-end","eventYearEnd","number")}<label>${t("eventCorrectionStatement")}<textarea id="event-correction-statement" name="correction-statement" required maxlength="2000">${escapeHtml(edit["correction-statement"] || "")}</textarea></label><button type="submit" class="button button-primary button-small">${t("saveEventTags")}</button><button type="button" class="text-button" data-action="cancel-event-edit">${t("cancelEventEdit")}</button></form>`;
  }

  function openMemoryEventEdit(id) {
    const event = state.timeline.find(item => item.id === id && item.canonical);
    if (!event || !state.familyFeaturesEnabled) return;
    state.memoryEventEdit = {id,revision:event.revision,"life-stage":event.life_stage,
      original:{life_stage:event.life_stage,temporal:{...event.temporal}},
      "date-expression":event.temporal?.expression || "unknown","date-precision":event.temporal?.precision || "unknown",
      "year-start":event.temporal?.year_start ?? "","year-end":event.temporal?.year_end ?? "","correction-statement":""};
    render();
    $("#event-life-stage")?.focus();
  }

  async function saveMemoryEventEdit(event) {
    event.preventDefault();
    const edit = state.memoryEventEdit;
    if (!edit || !state.familyFeaturesEnabled) return;
    const temporal = {expression:edit["date-expression"] || "unknown",precision:edit["date-precision"]};
    if (edit["year-start"] !== "") temporal.year_start = Number(edit["year-start"]);
    if (edit["year-end"] !== "") temporal.year_end = Number(edit["year-end"]);
    const patch = {};
    if (edit["life-stage"] !== edit.original.life_stage) patch.life_stage = edit["life-stage"];
    if (["expression","precision","year_start","year_end"].some(key => String(temporal[key] ?? "") !== String(edit.original.temporal[key] ?? ""))) patch.temporal = temporal;
    if (!Object.keys(patch).length) { state.memoryEventEdit = null; render(); return; }
    try {
      await storyApi(`/v1/story/events/${encodeURIComponent(state.project.id)}/${encodeURIComponent(edit.id)}`,{method:"PATCH",body:JSON.stringify({expected_revision:edit.revision,patch,statement:edit["correction-statement"]})});
      state.memoryEventEdit = null;
      await refreshFamilyContext();
      await refreshPrivateDraft();
    } catch (failure) {
      if (failure.status === 409) { state.memoryEventEdit = null; await refreshFamilyContext(); }
      toast(translate(`Memoir.workspace.${failure.status === 409 ? "eventRevisionConflict" : "eventCorrectionUnavailable"}`));
    }
  }

  async function addPerson() {
    const olderBrother = translate("Memoir.storyFlow.olderBrother");
    const name = prompt(translate("Memoir.storyFlow.whoIsThis"), olderBrother);
    if (!name) return;
    try { await api(`/v1/projects/${state.project.id}/people`, { method: "POST", body: JSON.stringify({ name, family_title: name === olderBrother ? olderBrother : null }) }); await refreshProject(); render(); } catch (error) { toast(error.message); }
  }

  return {
    addPerson, applyPersistedFamilyContext, closeFamilyPerson, familyWorkspace, initFamilyVisualizations,
    loadMoreEventDetails, loadMoreEventEvidence, loadMoreMemoryEvents, openMemoryEventEdit,
    refreshFamilyContext, saveFamilyPersonPhoto, saveMemoryEventEdit, selectFamilyPerson, timelineWorkspace,
    zoomFamilyChart
  };
}
