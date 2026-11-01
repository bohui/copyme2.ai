import { escapeHtml } from "./dom.mjs";
import { buildMapMemoryJourney, cityEventCards, map2DViewRectangle, mapCityInView, mapCityOverlapsView, mapTrailWindow, matchesEventPlace, memoryEventCardMarkup, memoryTrailLegs } from "./map-memory-journey.mjs";
import { placeHistoryKey } from "./places.mjs";

export function createMapMemoryEvents({getEvents, getGroups, getProfile, getScope, getIdentity = getScope, getStage,
  getInitialPlace = () => null,
  getQuestionFocus = () => null,
  getPage = () => null, getReadiness = () => ({}), getCanAddMemory = () => true, readPlaces, resolvePlaces = async places => places,
  t, lifeStageText, onExplore, onAdd, onLoadMore, onOverview = () => {}, onChange = () => {}}) {
  let layer, sceneElement, viewer, cesium, removePostRender, removeMoveEnd, scope, journey, signature, selectedKey;
  let focusedCity = null, viewCity = null, listView, lastMode, initialIdentity, overviewRequested = false, overviewMode = true;
  let cityScope, activeCityKey, flyingToCity = null, flightRevision = 0;
  let visibleCityKeys = [];
  let arrivalCity;
  let placeGroups = [];
  const places = new Map();
  const footprint = typeof Image === "undefined" ? null : new Image();
  if (footprint) footprint.src = "/static/map-footprints.svg";

  function activeCity(groups = placeGroups) {
    const initial = getInitialPlace();
    const focus = getQuestionFocus();
    const nextScope = JSON.stringify([getIdentity(), focus || (initial && [placeHistoryKey(initial), initial.source_sequence || initial.revision || 0])]);
    if (cityScope !== nextScope) {
      cityScope = nextScope;
      activeCityKey = undefined;
      try {
        const saved = JSON.parse(localStorage.getItem(`memory-spark-map-city:${getIdentity()}`));
        if (saved?.scope === cityScope && (saved.city === null || typeof saved.city === "string")) activeCityKey = saved.city;
      } catch { /* Storage is optional; keep the city for this page. */ }
    }
    if (activeCityKey !== undefined) return activeCityKey;
    if (focus?.place) {
      const matches = groups.filter(group => matchesEventPlace({place:focus.place},group.city)
        || group.members.some(member => matchesEventPlace({place:focus.place},member)));
      if (matches.length === 1) return matches[0].key;
    }
    if (!initial) return null;
    const key = placeHistoryKey(initial);
    return groups.find(group => placeHistoryKey(group.city) === key
      || group.members.some(member => placeHistoryKey(member) === key))?.key || null;
  }

  function rememberCity(city) {
    activeCity();
    if (activeCityKey === city) return;
    activeCityKey = city;
    try {
      localStorage.setItem(`memory-spark-map-city:${getIdentity()}`, JSON.stringify({scope:cityScope, city}));
    } catch { /* The current viewer still retains its selection. */ }
  }

  function loadPlaces(events) {
    for (const event of events) {
      if (!event.canonical || event.status !== "active") continue;
      const key = `${event.id}:${event.revision}`;
      if (places.has(key)) continue;
      const captured = scope;
      const supplied = Array.isArray(event.places);
      const entry = {items:supplied ? event.places.filter(item => !item.status || item.status === "supported") : [],
        conflicted:event.place_conflicts?.includes("setting") || event.places?.some(item => item.status === "conflicted")};
      places.set(key, entry);
      // Event locations have their own bounded pages; never infer them from a
      // shared source passage that may describe several different memories.
      void (async () => {
        let cursor;
        const seen = new Set();
        try {
          if (!supplied) do {
              const page = await readPlaces(event.id, cursor);
              if (getScope() !== captured || places.get(key) !== entry) return;
              entry.conflicted ||= page.items?.some(item => item.status === "conflicted");
              entry.items.push(...(page.items || []).filter(item => item.status === "supported"));
              cursor = page.next_cursor;
              if (cursor && seen.has(cursor)) throw new Error("Repeated event location page");
              seen.add(cursor);
            } while (cursor);
          if (!entry.items.length && !entry.conflicted && event.location && event.locationConfidenceScore > 0) {
            entry.items.push({role:"setting",status:"candidate",place:event.location});
          }
          const resolved = await resolvePlaces(entry.items.map(item => item.place));
          if (getScope() !== captured || places.get(key) !== entry) return;
          entry.items = entry.items.map((item,index) => ({...item,place:resolved[index] || item.place}));
          entry.complete = true;
        } catch { entry.items = []; entry.failed = true; }
        if (getScope() === captured) sync(sceneElement?.isConnected ? sceneElement : null);
      })();
    }
  }

  function sync(scene, focusedKey = null) {
    const nextScope = getScope();
    if (nextScope !== scope) {
      scope = nextScope;places.clear();selectedKey = null;listView = null;signature = null;
      visibleCityKeys = [];
      activeCity();
      if (initialIdentity !== cityScope) { focusedCity = null;viewCity = null;overviewMode = true; }
    }
    sceneElement = scene;
    const events = getEvents();
    loadPlaces(events);
    const stage = getStage();
    const visible = events.filter(event => stage === "all" || event.life_stage === stage)
      .map(event => ({...event, map_places:places.get(`${event.id}:${event.revision}`)?.items || event.places}));
    const eventPlaces = visible.filter(event => !event.status || event.status === "active")
      .flatMap(event => (event.map_places || []).filter(link => link.status !== "conflicted"
        && !event.place_conflicts?.includes(link.role)).map(link => link.place));
    placeGroups = getGroups(eventPlaces);
    journey = buildMapMemoryJourney(visible, placeGroups, getProfile());
    if (!scene) return;
    layer = scene.querySelector(".map-memory-layer");
    if (!layer) {
      layer = document.createElement("div");
      layer.className = "map-memory-layer";
      layer.innerHTML = '<canvas class="map-memory-trail" aria-hidden="true"></canvas><div class="map-memory-toolbar"></div><div class="map-memory-cards"></div><div class="map-memory-overflow"></div>';
      layer.addEventListener("click", event => {
        const target = event.target.closest("[data-map-memory], [data-memory-city], [data-memory-overview], [data-memory-explore], [data-memory-add], [data-memory-retry], [data-memory-more]");
        if (!target) return;
        if (target.hasAttribute("data-memory-add")) { if (getCanAddMemory()) onAdd(); return; }
        if (target.hasAttribute("data-memory-overview")) { overview(); return; }
        if (target.hasAttribute("data-memory-explore")) { onExplore(target.dataset.memoryExplore); return; }
        if (target.hasAttribute("data-memory-more")) { onLoadMore(); return; }
        if (target.hasAttribute("data-memory-retry")) {
          for (const [key, entry] of places) if (entry.failed) places.delete(key);
          sync(sceneElement);
          return;
        }
        const key = target.dataset.mapMemory;
        const unlocated = journey.unlocated.find(node => node.key === key);
        if (unlocated) { onExplore(unlocated.event.id); return; }
        const city = cityEventCards([...journey.nodes,...journey.unlocated]).find(city => target.hasAttribute("data-memory-city")
          ? city.groupKey === target.dataset.memoryCity : city.key === key);
        if (city) {
          const focused = document.activeElement === target;
          focusedCity = city.groupKey;
          overviewMode = false;
          selectedKey = null;
          if (city.groupKey !== "unlocated") rememberCity(city.groupKey);
          if (city.groupKey !== "unlocated") frame(city.nodes,2500,city.groupKey);
          position();
          if (focused) [...layer.querySelectorAll("[data-map-memory]")]
            .find(button => button.dataset.mapMemory === city.nodes[0].key)?.focus({preventScroll:true});
        } else {
          const node = journey.nodes.find(node => node.key === key);
          if (!node) return;
          selectedKey = node.key;
          rememberCity(node.groupKey);
          frame([node],2500,node.groupKey);
          position();
        }
      });
      layer.addEventListener("keydown", event => {
        if (event.key === "Escape") { selectedKey = null; position(); }
      });
      scene.append(layer);
      signature = null;
    }
    const page = getPage();
    layer.hidden = !journey.nodes.length && !journey.unmapped && !places.size && !page?.next_cursor && !page?.page_error;
    scene.classList.toggle("has-map-memories", journey.nodes.length > 0);
    const failed = [...places.values()].some(entry => entry.failed);
    const pending = [...places.values()].some(entry => !entry.complete && !entry.failed);
    const note = failed ? t("mapEventLocationsUnavailable") : pending ? t("mapEventLocationsLoading") : page?.page_error ? t("savedPageChanged")
      : "";
    layer.querySelector(".map-memory-toolbar").innerHTML = `<span class="map-memory-caption"><img src="/static/map-footprints.svg" alt="" />${escapeHtml(t("mapMemoryJourney"))}</span><button type="button" data-memory-overview>${escapeHtml(t("mapMemoryOverview"))}</button>${note || page?.next_cursor ? `<span class="map-memory-status" role="status">${escapeHtml(note)}${failed ? `<button type="button" data-memory-retry>${escapeHtml(t("mapEventRetry"))}</button>` : ""}${page?.next_cursor || page?.page_error ? `${page?.next_cursor ? escapeHtml(t("mapEventsPartial")) : ""}<button type="button" data-memory-more ${page.loading_page ? "disabled" : ""}>${escapeHtml(t(page.page_error ? "reloadSavedPages" : page.loading_page ? "loadingSavedPage" : "loadMoreEvents"))}</button>` : ""}</span>` : ""}`;
    signature = null;
    position();
    if (focusedKey) [...layer.querySelectorAll("[data-map-memory]")]
      .find(button => button.dataset.mapMemory === focusedKey)?.focus({preventScroll:true});
    onChange(scene);
  }

  function overview() {
    rememberCity(null);
    flyingToCity = null;
    focusedCity = null;
    viewCity = null;
    overviewMode = true;
    selectedKey = null;
    overviewRequested = true;
    onOverview();
    sync(sceneElement);
  }

  function frame(nodes, minimum, city = null) {
    if (!viewer || viewer.isDestroyed() || !nodes.length) return;
    const origin = nodes[0].longitude;
    const longitudes = nodes.map(node => origin + ((node.longitude - origin + 540) % 360 - 180));
    const latitudes = nodes.map(node => node.latitude);
    const latitude = (Math.min(...latitudes) + Math.max(...latitudes)) / 2;
    const longitude = ((Math.min(...longitudes) + Math.max(...longitudes)) / 2 + 540) % 360 - 180;
    const span = Math.max((Math.max(...latitudes) - Math.min(...latitudes)) * 111320,
      (Math.max(...longitudes) - Math.min(...longitudes)) * 111320 * Math.cos(latitude * Math.PI / 180));
    const aspect = Math.max(1, (sceneElement.clientHeight || layer.clientHeight)
      / Math.max(1, sceneElement.clientWidth || layer.clientWidth));
    flyingToCity = city;
    const revision = ++flightRevision;
    const finish = () => { if (revision === flightRevision) { flyingToCity = null;position(); } };
    viewer.camera.flyTo({destination:cesium.Cartesian3.fromDegrees(longitude, latitude, Math.max(minimum, span * 3.5 * aspect)),
      duration:window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 1.1,
      complete:finish, cancel:finish});
  }

  function position() {
    if (!layer?.isConnected || !sceneElement || getScope() !== scope) return;
    const width = sceneElement.clientWidth || layer.clientWidth, height = sceneElement.clientHeight || layer.clientHeight;
    const desktop = !window.matchMedia("(max-width: 760px)").matches;
    layer.classList.toggle("is-compact",width < 500);
    layer.classList.toggle("is-desktop",desktop);
    if (!viewer || viewer.isDestroyed()) return;
    const ready = sceneElement.classList.contains("is-cesium-map");
    layer.classList.toggle("is-ready", ready);
    if (!ready) return;
    const city = activeCity();
    if (initialIdentity !== cityScope || overviewRequested) {
      const group = !overviewRequested && placeGroups.find(group => group.key === city);
      const nodes = group ? [...journey.nodes.filter(node => node.groupKey === group.key),
        ...group.members.map(member => Object.hasOwn(member,"map_pin") ? member.map_pin : member)]
        .filter(place => Number.isFinite(place?.latitude) && Number.isFinite(place?.longitude))
        : journey.nodes.length ? journey.nodes : !window.matchMedia("(max-width: 760px)").matches || overviewRequested
        ? placeGroups.flatMap(group => group.members.map(member => Object.hasOwn(member,"map_pin") ? member.map_pin : member))
          .filter(place => Number.isFinite(place?.latitude) && Number.isFinite(place?.longitude)) : [];
      const pending = [...places.values()].some(entry => !entry.complete && !entry.failed);
      if (nodes.length && (group || !city || !pending || overviewRequested)) {
        initialIdentity = cityScope;overviewRequested = false;
        if (group) { focusedCity = group.key;overviewMode = false; }
        if (!group || group.key !== arrivalCity) frame(nodes,group ? 12000 : 40000,group?.key);
        arrivalCity = undefined;
      }
    }
    // Photo-only maps still need a city scope while the event layer is hidden.
    const zoom = viewer.scene.mode === cesium.SceneMode.SCENE2D ? viewer.camera.frustum.right - viewer.camera.frustum.left
      : viewer.camera.positionCartographic.height;
    const detailed = zoom < 18000;
    if (detailed && lastMode === false) overviewMode = false;
    if (lastMode === true && !detailed) focusedCity = null;
    lastMode = detailed;
    const project = point => cesium.SceneTransforms.worldToWindowCoordinates(viewer.scene,
      cesium.Cartesian3.fromDegrees(point.longitude,point.latitude));
    const cities = cityEventCards(journey.nodes);
    const previousCity = viewCity;
    const eventCities = placeGroups.filter(group => cities.some(city => city.groupKey === group.key));
    const cityLocations = placeGroups.map(group => {
      const matches = eventCities.filter(candidate => candidate.key === group.key || matchesEventPlace(group.city,candidate.city));
      const groupKey = matches.length === 1 ? matches[0].key : group.key;
      return {...group.city,groupKey,
        nodes:[...journey.nodes.filter(node => node.groupKey === groupKey),
          ...group.members.map(member => Object.hasOwn(member,"map_pin") ? member.map_pin : member)
            .filter(place => Number.isFinite(place?.latitude) && Number.isFinite(place?.longitude))]};
    });
    const rectangle = viewer.scene.mode === cesium.SceneMode.SCENE2D && viewer.scene.mapProjection
      ? map2DViewRectangle(viewer.camera,point=>viewer.scene.mapProjection.unproject(point))
      : viewer.camera.computeViewRectangle?.(viewer.scene.globe?.ellipsoid);
    const visibleCities = new Set(cityLocations.filter(city => rectangle ? mapCityOverlapsView(city,rectangle)
      : !viewer.camera.computeViewRectangle && mapCityInView([city],project,width,height) !== null)
      .map(city => city.groupKey));
    const nextVisibleCityKeys = [...visibleCities].sort();
    const visibilityChanged = JSON.stringify(nextVisibleCityKeys) !== JSON.stringify(visibleCityKeys);
    visibleCityKeys = nextVisibleCityKeys;
    if (focusedCity && !cities.some(city => city.groupKey === focusedCity) && !placeGroups.some(group => group.key === focusedCity)) {
      focusedCity = null;overviewMode = true;
    }
    if (focusedCity && focusedCity !== "unlocated" && !visibleCities.has(focusedCity) && !flyingToCity) focusedCity = null;
    if (!detailed && visibleCities.size > 1 && !focusedCity) overviewMode = true;
    viewCity = flyingToCity ?? (overviewMode ? null : focusedCity ?? (visibleCities.size === 1 ? [...visibleCities][0]
      : detailed ? mapCityInView(cityLocations,project,width,height) : null));
    const locatedCards = viewCity !== null || detailed ? (cities.find(city => city.groupKey === viewCity)?.nodes || []) : cities;
    const cards = (overviewMode ? cities : locatedCards).filter(card => visibleCities.has(card.groupKey));
    if (selectedKey && !cards.some(card => card.key === selectedKey || card.nodes?.some(node => node.key === selectedKey))) {
      selectedKey = null;
    }
    const options = {t,lifeStageText,profile:getProfile(),readiness:getReadiness(),canAddMemory:getCanAddMemory()};
    const next = JSON.stringify([cards, width < 500, selectedKey, desktop, options.profile?.avatar_style, options.readiness, options.canAddMemory]);
    const container = layer.querySelector(".map-memory-cards");
    const overflow = layer.querySelector(".map-memory-overflow");
    if (signature !== next) {
      const focused = document.activeElement?.dataset?.mapMemory;
      const nextView = JSON.stringify([viewCity]);
      const scroll = listView === nextView ? container.scrollTop : 0;
      listView = nextView;
      signature = next;
      container.innerHTML = cards.map(card => `<div class="map-memory-anchor" data-memory-key="${escapeHtml(card.key)}"><span class="map-memory-stem" aria-hidden="true"></span>${memoryEventCardMarkup(card,{...options,active:card.key === selectedKey})}</div>`).join("");
      overflow.replaceChildren();
      container.scrollTop = scroll;
      if (focused) [...container.querySelectorAll("[data-map-memory]")].find(button => button.dataset.mapMemory === focused)?.focus({preventScroll:true});
    }
    if (previousCity !== viewCity || visibilityChanged) onChange(sceneElement);
    for (const anchor of layer.querySelectorAll(".map-memory-anchor")) {
      anchor.hidden = false;
      anchor.removeAttribute("style");
      if (anchor.parentElement !== container) container.append(anchor);
    }
    overflow.hidden = true;
    drawTrail(project, width, height);
  }

  function drawTrail(project, width, height) {
    const canvas = layer.querySelector("canvas");
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    if (canvas.width !== width * ratio || canvas.height !== height * ratio) { canvas.width = width * ratio; canvas.height = height * ratio; }
    const context = canvas.getContext("2d");
    context.setTransform(ratio,0,0,ratio,0,0);
    context.clearRect(0,0,width,height);
    if (!window.matchMedia("(max-width: 760px)").matches) {
      const bounds = layer.getBoundingClientRect(), list = layer.querySelector(".map-memory-cards").getBoundingClientRect();
      for (const anchor of layer.querySelectorAll(".map-memory-anchor")) {
        const node = journey.nodes.find(node => node.key === anchor.dataset.memoryKey)
          || cityEventCards(journey.nodes).find(city => city.key === anchor.dataset.memoryKey);
        if (!node) continue;
        const point = project(lastMode || node.nodes ? node : {latitude:node.cityLatitude,longitude:node.cityLongitude});
        const card = anchor.getBoundingClientRect();
        if (!point || point.x < 0 || point.x > width || point.y < 0 || point.y > height
            || card.top < list.top || card.bottom > list.bottom) continue;
        context.beginPath();context.moveTo(card.right-bounds.left,card.top+card.height/2-bounds.top);
        context.lineTo(point.x,point.y);context.strokeStyle = "#45665266";context.lineWidth = 1;context.stroke();
      }
    }
    const projectLeg = leg => {
      const from = project(leg.from), to = project(leg.to);
      const range = mapTrailWindow(from,to,width,height);
      if (!range) return null;
      const dx = to.x - from.x, dy = to.y - from.y, distance = Math.hypot(dx,dy);
      return distance < 12 ? null : {leg,from,to,dx,dy,distance,range};
    };
    const localNodes = journey.nodes.filter(node => node.groupKey === viewCity);
    const local = new Set(localNodes.map(node => node.event.id)).size > 1
      ? memoryTrailLegs(localNodes).map(projectLeg).filter(Boolean) : [];
    const segments = local.length ? local : journey.legs.map(projectLeg).filter(Boolean);
    const size = local.length ? 10 : 16, spacing = local.length ? 18 : 30;
    for (const {leg,from,to,dx,dy,distance,range} of segments) {
      const bend = Math.min(50, distance * .12), cx = (from.x + to.x) / 2 - dy / distance * bend,
        cy = (from.y + to.y) / 2 + dx / distance * bend;
      context.beginPath();context.moveTo(from.x,from.y);context.quadraticCurveTo(cx,cy,to.x,to.y);
      context.strokeStyle = leg.stageTransition ? "#9b5a39" : "#456652";
      context.lineWidth = 1.5;context.setLineDash([2,7]);context.globalAlpha = .5;context.stroke();context.setLineDash([]);
      const steps = Math.min(Number.MAX_SAFE_INTEGER, Math.max(2, Math.ceil(distance / spacing)));
      if (footprint?.complete && footprint.naturalWidth) for (let step = Math.max(1,Math.ceil(range.start*steps)); step < Math.min(steps,Math.ceil(range.end*steps)); step++) {
        const at = step / steps, rest = 1 - at;
        const x = rest * rest * from.x + 2 * rest * at * cx + at * at * to.x;
        const y = rest * rest * from.y + 2 * rest * at * cy + at * at * to.y;
        if (x < -20 || x > width + 20 || y < -20 || y > height + 20) continue;
        context.save();context.translate(x,y);context.rotate(Math.atan2(2 * rest * (cy-from.y)+2*at*(to.y-cy),2*rest*(cx-from.x)+2*at*(to.x-cx)) + Math.PI/2);
        context.globalAlpha = .78;context.drawImage(footprint,-size/2,-size/2,size,size);context.restore();
      }
      context.globalAlpha = 1;
    }
    const pins = lastMode ? journey.nodes.filter(node => node.groupKey === viewCity) : cityEventCards(journey.nodes);
    for (const pin of pins) {
      const point = project(pin);
      if (!point) continue;
      context.beginPath();context.arc(point.x,point.y,4,0,Math.PI*2);
      context.fillStyle = "#456652";context.fill();context.strokeStyle = "#fffdf5";context.lineWidth = 2;context.stroke();
    }
  }

  function attach(nextViewer, library, framedCity) {
    removePostRender?.();
    removeMoveEnd?.();
    viewer = nextViewer;cesium = library;
    arrivalCity = framedCity;
    removePostRender = viewer.scene.postRender.addEventListener(position);
    removeMoveEnd = viewer.camera.moveEnd?.addEventListener(() => {
      if (getScope() !== scope) return;
      position();
      if (viewCity && viewCity !== "unlocated") rememberCity(viewCity);
    });
    position();
  }
  function dispose() {
    removeMoveEnd?.();removeMoveEnd = null;
    removePostRender?.();removePostRender = null;viewer = null;layer = null;sceneElement = null;signature = null;lastMode = null;selectedKey = null;viewCity = null;
    initialIdentity = undefined;focusedCity = null;overviewRequested = false;
    flyingToCity = null;
    flightRevision++;
    overviewMode = true;
    visibleCityKeys = [];
    arrivalCity = undefined;
  }
  return {sync, attach, dispose, overview, activeCity,
    visibleCities:() => getScope() === scope ? visibleCityKeys : [],
    nodes:() => getScope() === scope ? journey?.nodes || [] : [],
    viewCity:() => { const city = activeCity();return initialIdentity !== cityScope ? city : flyingToCity ?? viewCity; }};
}
