import { $, escapeHtml } from "./dom.mjs";
import { createMapPhotoAlbums } from "./map-photo-albums.mjs";
import { createMapMemoryEvents } from "./map-memory-events.mjs";
import { matchesEventPlace } from "./map-memory-journey.mjs";
import { currentUiLocale, translate, translateWith } from "../i18n.js";
import { groupMapFrame, groupPlaces, mapTarget, matchesPlaceStage, mergePlaces, placeHistoryKey, specificPlaceChoices } from "./places.mjs";

export const PLACE_JOURNEY_PROJECT_STORAGE_KEY = "memory-spark-place-journey-project";

export function createPlaceWorkspace({
  api, captureProjectScope, isCurrentProjectScope, lifeStageText, loadPlacePictures, persistChatHistory,
  profile, recordWorkspaceSkillProgress, render, saveProfileUpdates, state, supabaseApi, workspaceHasContent,
  photos, storyApi, onExploreMapMemory, onLoadMoreMapEvents
}) {
  const { bindPhotoMemoryActions, favoritePhotoWall, photoRequestKey, pictureWall, renderablePictureItems, workspacePictureItems } = photos;

  const mapPhotoAlbums = createMapPhotoAlbums({
    getProjectId: () => state.project?.id,
    getAlbum: mapPhotoAlbum,
    getAlbums: mapPhotoAlbumsForScene,
    renderAlbum: album => favoritePhotoWall() + (pictureWall(album.pictures, album.entry) || mapPhotoAlbumStatus(album.entry)),
    bindAlbum: (content, album) => {
      bindPhotoMemoryActions(content);
      content.querySelector("[data-photo-more]")?.addEventListener("click", () => void loadPlacePictures(album.entry, state.project?.id, {more:true}));
      content.querySelector("[data-photo-retry]")?.addEventListener("click", () => void loadPlacePictures(album.entry, state.project?.id, {force:true}));
    },
    closeLabel: () => translate("Memoir.workspace.closePhotoAlbum"),
    onOpen: album => void loadPlacePictures(album.entry, state.project?.id),
  });

  const mapMemoryEvents = createMapMemoryEvents({
    getEvents: () => state.timeline || [],
    getGroups: mapMemoryPlaceGroups,
    getProfile: profile,
    getScope: () => JSON.stringify([state.project?.id, state.supabase?.user?.id,
      state.memoryEventPage?.policy_epoch, state.memoryEventPage?.source_revision, state.memoryEventPage?.event_revision,
      state.derivedWorkspace?.policy_epoch, state.derivedWorkspace?.source_revision]),
    getIdentity: () => JSON.stringify([state.project?.id, state.supabase?.user?.id,
      state.memoryEventPage?.policy_epoch, state.derivedWorkspace?.policy_epoch]),
    getStage: () => state.lifeStage || "all",
    getPage: () => state.memoryEventPage,
    readPlaces: (eventId, cursor) => storyApi(`/v1/story/events/${encodeURIComponent(state.project.id)}/${encodeURIComponent(eventId)}/places${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`),
    resolvePlaces: resolveMapMemoryPlaces,
    t: (key, values) => translateWith(`Memoir.workspace.${key}`, values),
    lifeStageText, onExplore: onExploreMapMemory, onLoadMore: onLoadMoreMapEvents,
    onOverview: () => { state.lifeStage = "all"; state.selectedPlace = null; render(); },
  });

  const CESIUM_VERSION = "1.145";

  const PLACE_MAP_VIEW_HEIGHTS = {
    country: 1_400_000,
    region: 420_000,
    city: 40_000,
    town: 28_000,
    suburb: 16_000,
    neighbourhood: 12_000,
    landmark: 6_000,
  };

  let cesiumPlaceJourneyViewer = null;

  let cesiumLoadPromise = null;

  const unavailablePlaceMaps = new Set();

  async function hydratePlaceJourney() {
    const scope = captureProjectScope();
    const savedPlaces = mergePlaces(profile().memory_places || [], profile(), state.chat || []);
    const projectId = state.project?.id;
    if (Array.isArray(profile().memory_places)
        && JSON.stringify(savedPlaces) !== JSON.stringify(profile().memory_places)) {
      await saveProfileUpdates({ memory_places: savedPlaces }, projectId);
      if (!isCurrentProjectScope(scope)) return;
    }
    if (Array.isArray(savedPlaces) && savedPlaces.length) {
      let restoredProgress = false;
      for (const message of state.chat || []) {
        if (message.role !== "assistant" || !message.sourceSequence
            || message.trace?.some(step => step.skill === "memoir-place-journey")) continue;
        const places = savedPlaces.filter(place => String(place.source_sequence) === String(message.sourceSequence));
        if (!places.length) continue;
        // Old turns have no execution log; describe this restoration, not an invented past call.
        (message.trace ||= []).push({id:"place-journey", kind:"skill", skill:"memoir-place-journey",
          label:"memoir-place-journey", status:"cached", lane:"B", execution:"cache", model_invoked:false,
          detail:`${translate("Memoir.trace.placeJourneyRestored")} · ${places.map(place => place.place).join(" · ")}`});
        message.traceMode = "live";
        restoredProgress = true;
      }
      if (restoredProgress) persistChatHistory();
      // History is ordered by life stage, while the current place follows the
      // most recent explicit mention. Server sequence/revision records recency.
      state.placeJourney = savedPlaces.reduce((current, place) =>
        Number(place.source_sequence || place.revision || 0) > Number(current.source_sequence || current.revision || 0)
          ? place : current, savedPlaces.at(-1));
      state.lifeStage = state.placeJourney.life_stage || "all";
      state.selectedPlace = placeHistoryKey(state.placeJourney);
      state.workspaceTab = "memoir";
      rememberPlaceJourneyProject(state.project?.id);
      for (const place of savedPlaces) void loadPlacePictures(place, projectId);
      resolvePlaceMap(state.placeJourney);
      return;
    }
    if (!state.supabase?.accessToken || !placeJourneyIsActivatedForProject()) return;
    try {
      const body = await supabaseApi("/v1/agent/place-journey");
      if (!isCurrentProjectScope(scope)) return;
      state.placeJourney = body.place_journey || null;
      state.placeJourneyChange = null;
      if (state.placeJourney) {
        state.lifeStage = state.placeJourney.life_stage || "all";
        state.selectedPlace = placeHistoryKey(state.placeJourney);
        resolvePlaceMap(state.placeJourney);
        void loadPlacePictures(state.placeJourney, state.project?.id);
      }
    } catch {
      // A missing journey endpoint must not prevent the memoir conversation.
    }
  }

  function placeJourneyIsActivatedForProject(projectId = state.project?.id) {
    if (!projectId) return false;
    try {
      return localStorage.getItem(PLACE_JOURNEY_PROJECT_STORAGE_KEY) === projectId;
    } catch {
      return false;
    }
  }

  function rememberPlaceJourneyProject(projectId = state.project?.id) {
    if (!projectId) return;
    try {
      localStorage.setItem(PLACE_JOURNEY_PROJECT_STORAGE_KEY, projectId);
    } catch {
      // The journey remains available for the current page when storage is restricted.
    }
  }

  function placeHistoryChoices(places, current) {
    if (!places.length) return "";
    const label = escapeHtml(translate("Memoir.workspace.placeHistory"));
    return `<nav class="place-choices" aria-label="${label}">${places.map(item => {
      const context = (item.hierarchy || []).filter(part => part !== "Earth" && part !== item.place).join(" · ");
      const stage = (item.life_stages || [item.life_stage]).filter(Boolean).map(stage => lifeStageText(stage, "label")).join(" · ");
      const selected = placeHistoryKey(item) === placeHistoryKey(current) || item.group_members?.includes(placeHistoryKey(current));
      return `<button type="button" data-place-choice="${escapeHtml(placeHistoryKey(item))}" aria-pressed="${selected}"><span>${escapeHtml(item.place)}</span><small>${escapeHtml([context, stage].filter(Boolean).join(" · "))}</small></button>`;
    }).join("")}</nav>`;
  }

  function placeWorkspaceSelection({allowUnmapped = false} = {}) {
    if (!state.placeJourney) return null;
    const places = mergePlaces(profile().memory_places || [], profile(), state.chat || []);
    const matching = state.lifeStage === "all"
      ? places
      : places.filter(item => matchesPlaceStage(item, state.lifeStage));
    const explicitlySelected = state.selectedPlace
      ? matching.find(item => placeHistoryKey(item) === state.selectedPlace)
      : null;
    let selected = state.placeJourney.preview && state.selectedPlace === placeHistoryKey(state.placeJourney)
      ? state.placeJourney : explicitlySelected;
    if (!selected && state.selectedPlace) {
      const group = workspacePlaceGroups(matching).find(item => placeHistoryKey(item.city) === state.selectedPlace);
      const member = group?.members.find(item => placeMapAvailable(item)) || (allowUnmapped ? group?.members.at(-1) : null);
      if (member) selected = member;
    }
    const current = matching.find(item => placeHistoryKey(item) === placeHistoryKey(state.placeJourney));
    selected ||= current || matching.filter(item => placeMapAvailable(item)).at(-1) || state.placeJourney;
    if (allowUnmapped) return selected;
    const previous = state.placeWorkspaceMap?.projectId === state.project?.id
      ? places.find(item => placeHistoryKey(item) === state.placeWorkspaceMap.key && placeMapAvailable(item)) : null;
    const mapped = placeMapAvailable(selected) ? selected
      : previous || matching.filter(item => placeMapAvailable(item)).at(-1) || places.find(item => placeMapAvailable(item));
    if (mapped) state.placeWorkspaceMap = {projectId:state.project?.id, key:placeHistoryKey(mapped)};
    return mapped || null;
  }

  function placeMapTarget(journey) {
    if (!journey) return null;
    const key = placeHistoryKey(journey);
    return mapTarget(journey, [])
      || resolvedPlaceTargets.get(key)
      || mapTarget(journey, mergePlaces(profile().memory_places || [], profile()));
  }

  function placeMapRenderKey(journey) {
    const target = placeMapTarget(journey);
    return JSON.stringify([state.project?.id, placeHistoryKey(journey), target?.latitude, target?.longitude,
      state.supabase?.geo_provider || "google"]);
  }

  function placeMapAvailable(journey) {
    return Boolean(placeMapTarget(journey));
  }

  function workspaceMediaOverview(toggle = "") {
    const t = (key) => escapeHtml(translate(`Memoir.workspace.${key}`));
    const current = placeWorkspaceSelection();
    if (!current || !placeMapTarget(current)) return "";
    const places = mergePlaces(profile().memory_places || [], profile(), state.chat || []);
    const matching = state.lifeStage === "all" ? places : places.filter(item => matchesPlaceStage(item, state.lifeStage));
    const groups = workspacePlaceGroups(matching);
    const activeGroup = current && groups.find(group => group.members.some(member => placeHistoryKey(member) === placeHistoryKey(current)));
    const photoGroup = current && (state.lifeStage === "all" ? activeGroup : workspacePlaceGroups(places)
      .find(group => group.members.some(member => placeHistoryKey(member) === placeHistoryKey(current))));
    const choices = current ? placeHistoryChoices(groupChoices(workspacePlaceGroups(places)), current) : "";
    const map = placeJourneyMarkup(current, "workspace", activeGroup);
    const pictureItems = current ? renderablePictureItems(workspacePictureItems(current, photoGroup)) : [];
    const pictures = favoritePhotoWall() + (pictureItems.length ? pictureWall(pictureItems, current) : "");
    const gallery = pictures ? `<div class="workspace-media-gallery"><div class="workspace-media-header workspace-media-gallery-header"><h2>${t("pictures")}</h2></div>${pictures}</div>` : "";
    return `<section class="workspace-media-overview${gallery ? "" : " no-gallery"}" aria-label="${t("placeJourney")}"><div class="workspace-media-map"><div class="workspace-media-header workspace-media-map-header"><div class="workspace-media-heading">${toggle}<div class="workspace-intro"><h2>${t("places")}</h2></div></div>${current && groups.length > 1 ? `<button class="text-button" data-all-places>${t("allPlaces")}</button>` : ""}</div>${choices}${map}</div>${gallery}</section>`;
  }

  function mapPhotoAlbumsForScene(scene) {
    const container = scene.querySelector("[data-cesium-place]");
    const pins = new Set(JSON.parse(container?.dataset.cesiumPins || "[]").map(pin => pin.key));
    const places = mergePlaces([...(profile().memory_places || []), ...(state.placeJourney ? [state.placeJourney] : [])], profile(), state.chat || []);
    const group = workspacePlaceGroups(places).find(item => item.key === container?.dataset.placeKey);
    const entries = group?.members || [placeWorkspaceSelection()].filter(Boolean);
    return entries.map(entry => mapPhotoAlbum(placeHistoryKey(entry))).filter(Boolean)
      .map(album => ({...album, pinned:pins.has(album.key)}));
  }

  function mapPhotoAlbum(key) {
    const places = mergePlaces([...(profile().memory_places || []), ...(state.placeJourney ? [state.placeJourney] : [])], profile(), state.chat || []);
    const entry = places.find(place => placeHistoryKey(place) === key);
    if (!entry) return null;
    const group = workspacePlaceGroups(places).find(item => item.members.some(member => placeHistoryKey(member) === key));
    const pictures = workspacePictureItems(entry, group);
    const request = state.photoRequests?.get(photoRequestKey(entry));
    const status = request?.loading ? "loading" : request?.error ? "error" : pictures.length ? "ready" : "empty";
    const detail = translate(`Memoir.workspace.${status === "loading" ? "picturesSearching" : status === "error" ? "picturesUnavailable" : "picturesNoMatch"}`);
    return {key, place:entry.place, entry, pictures, count:pictures.length, status,
      label: pictures.length ? translateWith("Memoir.workspace.openPhotoAlbum", {place:entry.place,count:pictures.length}) : `${entry.place} · ${detail}`};
  }

  function mapPhotoAlbumStatus(entry) {
    const t = key => escapeHtml(translate(`Memoir.workspace.${key}`));
    const request = state.photoRequests?.get(photoRequestKey(entry));
    if (request?.loading) return `<p class="workspace-photo-status is-loading" role="status">${t("picturesSearching")}</p>`;
    if (request?.error) return `<div class="workspace-photo-status"><p role="status">${t(request.failures?.some(failure => ["verification_required", "robots_denied", "http_403"].includes(failure.reason)) ? "picturesSourceBlocked" : "picturesUnavailable")}</p><button type="button" class="button button-secondary" data-photo-retry="${escapeHtml(placeHistoryKey(entry))}">${t("picturesSearchRetry")}</button></div>`;
    return `<p class="workspace-photo-status" role="status">${t(entry.photo_search_complete || Object.hasOwn(entry, "photo_next_cursor") ? "picturesNoMatch" : "picturesEmpty")}</p>`;
  }

  function placeMapViewHeight(journey, target = journey) {
    const granularity = target?.granularity
      || (target?.place === journey?.place ? journey?.granularity : "city");
    return PLACE_MAP_VIEW_HEIGHTS[granularity] || PLACE_MAP_VIEW_HEIGHTS.city;
  }

  function placeJourneyMarkup(journey, variant = "surface", group = null) {
    if (!journey) return "";
    const t = (key) => escapeHtml(translate(`Memoir.workspace.${key}`));
    const title = group?.city || journey;
    const target = group ? groupMapFrame(group, placeMapTarget(group.city) || placeMapTarget(journey)) : placeMapTarget(journey);
    if (!target) return "";
    const parentFallback = !group && target.place && placeHistoryKey({place: target.place}) !== placeHistoryKey({place: journey.place});
    const latitude = Number.isFinite(target?.latitude) ? target.latitude : "";
    const longitude = Number.isFinite(target?.longitude) ? target.longitude : "";
    const duration = Number(journey.duration_ms) || 5200;
    const pins = target.pins || (parentFallback ? [] : [{key:placeHistoryKey(journey),place:journey.place,latitude,longitude}]);
    const pinData = ` data-cesium-unavailable="${unavailablePlaceMaps.has(placeMapRenderKey(journey))}" data-cesium-pins="${escapeHtml(JSON.stringify(pins))}" data-cesium-height="${target.height || ""}"`;
    const legend = group && group.members.length > 1 ? `<ul class="place-map-pins">${group.members.filter(member => placeHistoryKey(member) !== placeHistoryKey(group.city)).map(member => `<li><span class="place-pin-dot" aria-hidden="true">●</span>${escapeHtml(member.place)}${pins.some(pin => pin.key === placeHistoryKey(member)) ? "" : `<small>${t("pinUnresolved")}</small>`}</li>`).join("")}</ul>` : "";
    const heading = variant === "workspace" ? "" : `<div class="place-journey-heading"><h2>${escapeHtml(title.place)}</h2></div>`;
    return `<section class="place-journey-card place-journey-${variant}" aria-label="${escapeHtml(title.place)} · ${t("placeJourney")}">${heading}<div class="place-journey-scene" style="--journey-duration:${duration}ms"><div class="cesium-place-journey" data-place-key="${escapeHtml(group ? group.key : placeHistoryKey(journey))}" data-cesium-place="${escapeHtml(target.place || journey.place)}" data-cesium-latitude="${latitude}" data-cesium-longitude="${longitude}" data-cesium-duration="${duration}"${pinData}></div><div class="place-journey-fallback"><span class="journey-earth" aria-hidden="true">◒</span><span class="journey-fallback-line">${t("mapPreview")}<small>${t("placeContextShown")}</small></span></div></div>${legend}</section>`;
  }

  function placeJourneySurface() {
    return state.placeJourney && placeMapAvailable(state.placeJourney) && !workspaceHasContent() ? placeJourneyMarkup(state.placeJourney) : "";
  }

  function disposeCesiumPlaceJourney() {
    mapMemoryEvents.dispose();
    mapPhotoAlbums.dispose();
    if (!cesiumPlaceJourneyViewer) return;
    try {
      if (!cesiumPlaceJourneyViewer.isDestroyed()) cesiumPlaceJourneyViewer.destroy();
    } catch {
      // A failed external Cesium load should never block the memoir conversation.
    }
    cesiumPlaceJourneyViewer = null;
  }

  function loadCesium() {
    if (window.Cesium) return Promise.resolve(window.Cesium);
    if (cesiumLoadPromise) return cesiumLoadPromise;
    const base = `https://cesium.com/downloads/cesiumjs/releases/${CESIUM_VERSION}/Build/Cesium`;
    if (!document.getElementById("cesium-place-journey-widgets")) {
      const stylesheet = document.createElement("link");
      stylesheet.id = "cesium-place-journey-widgets";
      stylesheet.rel = "stylesheet";
      stylesheet.href = `${base}/Widgets/widgets.css`;
      document.head.appendChild(stylesheet);
    }
    window.CESIUM_BASE_URL = `${base}/`;
    cesiumLoadPromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = `${base}/Cesium.js`;
      script.async = true;
      script.addEventListener("load", () => window.Cesium ? resolve(window.Cesium) : reject(new Error("CesiumJS did not expose its global.")));
      script.addEventListener("error", () => reject(new Error("CesiumJS could not be loaded.")));
      document.head.appendChild(script);
    });
    return cesiumLoadPromise;
  }

  const resolvedPlaceTargets = new Map();

  const pendingPlaceTargets = new Map();

  const placeGroupRecords = new Map();

  const placeGroupRequests = new Map();

  const placeGroupLatest = new Map();

  function publicPlaceFields(place) {
    return {place: place.place, hierarchy: place.hierarchy, granularity: place.granularity,
      latitude: place.latitude, longitude: place.longitude};
  }

  function selectPlace(key) {
    state.selectedPlace = key;
    state.lifeStage = "all";
    const entries = profile().memory_places || [];
    const place = entries.find(item => placeHistoryKey(item) === key)
      || workspacePlaceGroups(entries).find(group => placeHistoryKey(group.city) === key)?.members.at(-1);
    if (place) {
      state.placeJourney = place;
      resolvePlaceMap(place);
      void loadPlacePictures(place, state.project?.id);
    }
    render();
  }

  function workspacePlaceGroups(places) {
    const entries = mergePlaces([...places, ...(state.placeJourney?.preview ? [state.placeJourney] : [])], profile(), state.chat || []);
    return groupPlaces(entries.map(place => {
      const record = placeGroupRecords.get(`${state.project?.id}:${currentUiLocale()}:${placeHistoryKey(place)}`);
      return record && record.language === currentUiLocale() && record.input === JSON.stringify(publicPlaceFields(place))
        ? {...place, map_city: record.city, map_city_key: record.city_key, map_pin: record.pin} : place;
    }));
  }

  async function resolveMapMemoryPlaces(entries) {
    const scope = captureProjectScope();
    const known = workspacePlaceGroups(profile().memory_places || [])
      .flatMap(group => group.members.map(member => ({group,member})));
    const resolved = entries.map(place => {
      const exact = known.filter(({member}) => placeHistoryKey(place) === placeHistoryKey(member));
      const matches = exact.length ? exact : known.filter(({member}) => matchesEventPlace(place,member));
      if (matches.length !== 1) return place;
      const {group,member} = matches[0];
      return {...publicPlaceFields(member),map_city:group.city,map_city_key:group.key,
        map_pin:Object.hasOwn(member,"map_pin") ? member.map_pin : publicPlaceFields(member)};
    });
    const pending = resolved.map((place,index) => ({place,index})).filter(({place}) => {
      const pin = Object.hasOwn(place,"map_pin") ? place.map_pin : place;
      return !Number.isFinite(pin?.latitude) || !Number.isFinite(pin?.longitude);
    });
    if (!pending.length) return resolved;
    const path = state.supabase?.accessToken ? `/v1/agent/places/${state.project.id}/groups` : `/v1/projects/${state.project.id}/place-groups`;
    const result = await (state.supabase?.accessToken ? supabaseApi : api)(path, {method:"POST",
      body:JSON.stringify({places:pending.map(({place}) => publicPlaceFields(place)),language:currentUiLocale()})});
    if (!isCurrentProjectScope(scope)) return [];
    for (const record of result.places || []) {
      const item = pending[record.index];
      if (item) resolved[item.index] = {...item.place,map_city:record.city,map_city_key:record.city_key,map_pin:record.pin};
    }
    return resolved;
  }

  function mapMemoryPlaceGroups(eventPlaces) {
    const keys = new Set(eventPlaces.map(placeHistoryKey));
    let changed = false;
    if (state.placeJourney?.event_map_key && !keys.has(state.placeJourney.event_map_key)) {
      state.placeJourney = null;state.selectedPlace = null;changed = true;
    }
    if (!state.placeJourney || !placeMapAvailable(state.placeJourney)) {
      for (const place of eventPlaces) {
        const own = Object.hasOwn(place,"map_pin") ? place.map_pin : place;
        const target = Number.isFinite(own?.latitude) && Number.isFinite(own?.longitude) ? own : place.map_city;
        if (!Number.isFinite(target?.latitude) || !Number.isFinite(target?.longitude)) continue;
        state.placeJourney = {...target,preview:true,event_map_key:placeHistoryKey(place)};
        state.selectedPlace = placeHistoryKey(state.placeJourney);changed = true;
        break;
      }
    }
    if (changed) queueMicrotask(render);
    return workspacePlaceGroups([...(profile().memory_places || []),...eventPlaces]);
  }

  function groupChoices(groups) {
    return specificPlaceChoices(groups.map(group => ({...group.city,
      group_members: group.members.map(placeHistoryKey),
      life_stages: [...new Set(group.members.flatMap(member => member.life_stages || [member.life_stage]).filter(Boolean))]})));
  }

  function resolvePlaceGroups(journey, {onProgress = null} = {}) {
    const projectId = state.project?.id;
    if (!projectId || !journey) return;
    const merged = mergePlaces([...(profile().memory_places || []), journey], profile(), state.chat || []);
    const newest = merged.find(place => placeHistoryKey(place) === placeHistoryKey(journey));
    if (!newest) return;
    // Resolve the newest mention first even when history is sorted by life stage.
    const places = [newest,
      ...merged.filter(place => placeHistoryKey(place) !== placeHistoryKey(journey))];
    // The grouping service receives only public geographic fields.
    const publicPlaces = places.map(publicPlaceFields);
    const language = currentUiLocale();
    const signature = JSON.stringify([projectId, language, publicPlaces]);
    if (placeGroupRequests.has(signature)) return;
    const scope = captureProjectScope();
    const progressTurn = (state.chat || []).findLast(item => item.role === "assistant")?.clientTurnId;
    const report = (status, work = null) => {
      if (!isCurrentProjectScope(scope)) return;
      recordWorkspaceSkillProgress({id:work?.id || `place-groups:${signature}`, replaces_id:work?.id ? `place-groups:${signature}` : null, kind:"skill", skill:"memoir-place-groups",
        project_id:projectId, client_turn_id:progressTurn, lane:"B", execution:"deterministic", model_invoked:false,
        label:"memoir-place-groups", status,
        ...(work ? {started_at:work.started_at,finished_at:work.finished_at} : {}),
        detail:`${translate(`Memoir.trace.placeGroups.${status}`)} · ${journey.place}`}, onProgress);
    };
    report("running");
    placeGroupLatest.set(projectId, signature);
    const request = (state.supabase?.accessToken ? supabaseApi(`/v1/agent/places/${projectId}/groups`, {
      method:"POST",body:JSON.stringify({places:publicPlaces,language,...(progressTurn ? {client_turn_id:progressTurn} : {})}),
    }) : api(`/v1/projects/${projectId}/place-groups`, {
      method: "POST", body: JSON.stringify({places: publicPlaces, language}),
    })).then(result => {
      report("completed",result.skill_progress);
      if (state.project?.id !== projectId || placeGroupLatest.get(projectId) !== signature) return;
      for (const record of result.places || []) {
        const place = places[record.index];
        if (place) placeGroupRecords.set(`${projectId}:${language}:${placeHistoryKey(place)}`,
          {...record, language, input: JSON.stringify(publicPlaces[record.index])});
      }
      render();
    }).catch(() => { report("failed"); }).finally(() => {
      // Keep a completed signature briefly; renders must not repeat failed lookups.
      setTimeout(() => {
        if (placeGroupRequests.get(signature) === request) placeGroupRequests.delete(signature);
      }, 60_000);
    });
    placeGroupRequests.set(signature, request);
    while (placeGroupRequests.size > 32) placeGroupRequests.delete(placeGroupRequests.keys().next().value);
  }

  function resolvePlaceMap(journey, {onProgress = null} = {}) {
    if (!journey || !state.project?.id) return;
    void resolvePlaceGroups(journey, {onProgress});
    const key = placeHistoryKey(journey);
    if (mapTarget(journey, []) || resolvedPlaceTargets.has(key) || pendingPlaceTargets.has(key)) return;
    const projectId = state.project.id;
    const request = api(`/v1/projects/${projectId}/place-map`, {method: "POST", body: JSON.stringify(journey)})
      .then(result => {
        if (result.target) resolvedPlaceTargets.set(key, result.target);
        // Cache no-match as well to avoid repeated searches on every render.
        else resolvedPlaceTargets.set(key, null);
        if (result.target?.place === journey.place) void loadPlacePictures(journey, projectId);
        if (state.project?.id === projectId) render();
      }).catch(() => { resolvedPlaceTargets.set(key, null); })
      .finally(() => pendingPlaceTargets.delete(key));
    pendingPlaceTargets.set(key, request);
  }

  function initCesiumPlaceJourney() {
    const container = $("[data-cesium-place]");
    if (container) resolvePlaceMap(placeWorkspaceSelection());
    if (!container || !container.dataset.cesiumLatitude || !container.dataset.cesiumLongitude) return;
    const latitude = Number(container.dataset.cesiumLatitude);
    const longitude = Number(container.dataset.cesiumLongitude);
    const journey = placeWorkspaceSelection() || state.placeJourney;
    const projectId = state.project?.id;
    const mapKey = placeMapRenderKey(journey);
    // A denied tile provider must not hide saved places or retry on each render.
    if (unavailablePlaceMaps.has(mapKey)) {
      const fallback = container.parentElement.querySelector(".place-journey-fallback");
      if (fallback) {
        const t = key => escapeHtml(translate(`Memoir.workspace.${key}`));
        fallback.innerHTML = `<span class="journey-fallback-line" role="status">${t("mapUnavailable")}<small>${t("mapUnavailableDetail")}</small><button type="button" class="button button-primary" data-map-retry>${t("mapRetry")}</button></span>`;
        fallback.querySelector("[data-map-retry]")?.addEventListener("click", () => {
          if (!container.isConnected || state.project?.id !== projectId) return;
          unavailablePlaceMaps.delete(mapKey);
          cesiumLoadPromise = null;
          render();
        });
      }
      return;
    }
    const hideUnavailableMap = () => {
      if (!container.isConnected || state.project?.id !== projectId) return;
      unavailablePlaceMaps.add(mapKey);
      render();
    };
    const finalMapHeight = Number(container.dataset.cesiumHeight) || placeMapViewHeight(journey, placeMapTarget(journey));
    if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return;
    loadCesium().then((cesium) => {
      if (!container.isConnected) return;
      let viewer = null;
      let arrivalComplete = false;
      let mapLayerReady = false;
      let mapLayerFailed = false;
      let finalViewStarted = false;
      try {
        viewer = new cesium.Viewer(container, {
          animation: false,
          baseLayer: false,
          baseLayerPicker: false,
          fullscreenButton: false,
          geocoder: false,
          homeButton: false,
          infoBox: false,
          navigationHelpButton: false,
          sceneModePicker: false,
          selectionIndicator: false,
          timeline: false,
          scene3DOnly: false,
          mapProjection: new cesium.WebMercatorProjection(),
          shouldAnimate: false,
        });
        cesiumPlaceJourneyViewer = viewer;
        viewer.scene.backgroundColor = cesium.Color.fromCssColorString("#173f45");
        viewer.scene.globe.enableLighting = false;
        viewer.scene.globe.maximumScreenSpaceError = 1;
        viewer.scene.skyAtmosphere.show = true;
        viewer.scene.globe.baseColor = cesium.Color.fromCssColorString("#2a756b");
        const destination = cesium.Cartesian3.fromDegrees(longitude, latitude, finalMapHeight);
        const pins = container.dataset.cesiumPins ? JSON.parse(container.dataset.cesiumPins) : [
          {place: container.dataset.cesiumPlace, latitude, longitude}];
        for (const pin of pins) viewer.entities.add({
          id: pin.key,
          position: cesium.Cartesian3.fromDegrees(pin.longitude, pin.latitude),
          point: {
            color: cesium.Color.fromCssColorString("#f3c66b"),
            outlineColor: cesium.Color.fromCssColorString("#fff8e7"),
            outlineWidth: 2,
            pixelSize: 12,
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
          label: {
            text: pin.place || "Memory place",
            fillColor: cesium.Color.WHITE,
            font: "600 14px DM Sans, sans-serif",
            style: cesium.LabelStyle.FILL_AND_OUTLINE,
            outlineColor: cesium.Color.fromCssColorString("#173f45"),
            outlineWidth: 3,
            pixelOffset: new cesium.Cartesian2(0, -24),
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
        });
        viewer.screenSpaceEventHandler.setInputAction(event => {
          const picked = viewer.scene.pick(event.position)?.id;
          if (!picked?.id) return;
          if (mapPhotoAlbums.open(picked.id)) return;
          const member = (profile().memory_places || []).find(place => placeHistoryKey(place) === picked.id);
          if (!member) return;
          state.selectedPlace = picked.id;
          void loadPlacePictures(member, state.project?.id);
          render();
        }, cesium.ScreenSpaceEventType.LEFT_CLICK);
        mapPhotoAlbums.sync(container.closest(".place-journey-scene"));
        mapPhotoAlbums.attach(viewer, cesium, pins);
        mapMemoryEvents.sync(container.closest(".place-journey-scene"));
        mapMemoryEvents.attach(viewer, cesium);

        const showFinalRoadMap = () => {
          if (!arrivalComplete || !mapLayerReady || mapLayerFailed || finalViewStarted || !container.isConnected || viewer.isDestroyed()) return;
          finalViewStarted = true;
          // The flight already arrives looking straight down. Switch projection
          // without Cesium's world-scale unfolding animation pulling us away.
          viewer.scene.morphTo2D(0);
          viewer.camera.setView({
            destination,
            orientation: { heading: 0, pitch: -Math.PI / 2, roll: 0 },
          });
          container.closest(".place-journey-scene")?.classList.add("is-cesium-map");
          viewer.scene.requestRender();
        };

        // Fit the whole Earth in the narrower dimension of this panel. Looking
        // off-nadir at orbital altitude pushes the globe below the viewport.
        viewer.resize();
        const frustum = viewer.camera.frustum;
        const halfFov = Math.min(frustum.fovy / 2, Math.atan(Math.tan(frustum.fovy / 2) * frustum.aspectRatio));
        const radius = viewer.scene.globe.ellipsoid.maximumRadius;
        const startHeight = radius * (1.15 / Math.sin(halfFov) - 1);
        viewer.camera.setView({
          destination: cesium.Cartesian3.fromDegrees(0, 18, startHeight),
          orientation: { heading: 0, pitch: -Math.PI / 2, roll: 0 },
        });
        viewer.camera.flyTo({
          destination,
          orientation: { heading: 0, pitch: -Math.PI / 2, roll: 0 },
          duration: window.matchMedia("(prefers-reduced-motion: reduce)").matches
            ? 0 : Math.max(2.8, Math.min(9, Number(container.dataset.cesiumDuration || 5200) / 1000)),
          easingFunction: cesium.EasingFunction.QUADRATIC_IN_OUT,
          complete: () => {
            arrivalComplete = true;
            showFinalRoadMap();
          },
        });
        container.closest(".place-journey-scene")?.classList.add("is-cesium-live");
        container.parentElement.querySelector(".place-journey-fallback")?.setAttribute("aria-hidden", "true");

        const provider = state.supabase?.geo_provider || "google";
        let mapLayer;
        const showImageryFallback = () => {
          if (mapLayerFailed || !container.isConnected || viewer.isDestroyed()) return;
          mapLayerFailed = true;
          mapLayerReady = false;
          if (mapLayer) viewer.imageryLayers.remove(mapLayer);
          viewer.camera.cancelFlight();
          viewer.scene.morphTo3D(0);
          viewer.camera.setView({
            destination: cesium.Cartesian3.fromDegrees(0, 18, startHeight),
            orientation: { heading: 0, pitch: -Math.PI / 2, roll: 0 },
          });
          container.closest(".place-journey-scene")?.classList.remove("is-cesium-live", "is-cesium-map");
          container.parentElement.querySelector(".place-journey-fallback")?.removeAttribute("aria-hidden");
          viewer.scene.requestRender();
          hideUnavailableMap();
          console.warn("Place map imagery unavailable.");
        };
        let imagery;
        if (provider === "google") {
          const key = state.supabase?.google_maps_browser_api_key;
          if (!key || typeof cesium.Google2DImageryProvider?.fromUrl !== "function") { showImageryFallback(); return; }
          imagery = cesium.Google2DImageryProvider.fromUrl({
            key, mapType: "roadmap", language: currentUiLocale(),
            region: currentUiLocale() === "zh-CN" ? "CN" : "AU",
          });
        } else if (provider === "geoapify") {
          const key = state.supabase?.geoapify_browser_api_key;
          if (!key || typeof cesium.UrlTemplateImageryProvider !== "function") { showImageryFallback(); return; }
          imagery = new cesium.UrlTemplateImageryProvider({
            url: `https://maps.geoapify.com/v1/tile/osm-carto/{z}/{x}/{y}.png?apiKey=${encodeURIComponent(key)}`,
            credit: new cesium.Credit('© <a href="https://www.geoapify.com/">Geoapify</a> | © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>', true),
            maximumLevel: 20,
          });
        } else { showImageryFallback(); return; }
        Promise.resolve(imagery).then((layer) => {
          if (!container.isConnected || viewer.isDestroyed()) return;
          layer.errorEvent.addEventListener(showImageryFallback);
          const requestImage = layer.requestImage.bind(layer);
          layer.requestImage = (...args) => {
            const request = requestImage(...args);
            // Undefined means Cesium throttled the request; preserve its retry contract.
            if (!request) return request;
            return Promise.resolve(request).then(image => {
              if (image && !mapLayerFailed && container.isConnected && !viewer.isDestroyed()) {
                mapLayerReady = true;
                showFinalRoadMap();
              }
              return image;
            }, error => {
              showImageryFallback();
              throw error;
            });
          };
          mapLayer = viewer.imageryLayers.addImageryProvider(layer);
        }).catch(showImageryFallback);
      } catch (error) {
        if (viewer && !viewer.isDestroyed()) viewer.destroy();
        if (cesiumPlaceJourneyViewer === viewer) cesiumPlaceJourneyViewer = null;
        hideUnavailableMap();
        console.warn("Cesium place journey unavailable.", error);
      }
    }).catch((error) => {
      hideUnavailableMap();
      console.warn("Cesium place journey unavailable.", error);
    });
  }

  function resizeCesiumPlaceJourney() {
    cesiumPlaceJourneyViewer?.resize();
  }

  return {
    disposeCesiumPlaceJourney, hydratePlaceJourney, initCesiumPlaceJourney, loadCesium, mapPhotoAlbums, mapMemoryEvents,
    placeJourneySurface, placeMapTarget, placeWorkspaceSelection, rememberPlaceJourneyProject, resolvePlaceMap,
    selectPlace, workspaceMediaOverview, resizeCesiumPlaceJourney
  };
}
