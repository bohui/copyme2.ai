import { updateMemoryCards } from "./map-memory-card-updates.mjs";
import { escapeHtml } from "./dom.mjs";
import { buildMapMemoryJourney, cityEventCards, map2DViewRectangle, mapCityInView, mapCityOverlapsView, mapTrailWindow, matchesEventPlace, memoryEventCardMarkup, memoryTrailLegs } from "./map-memory-journey.mjs";
import { placeHistoryKey } from "./places.mjs";

export function createMapMemoryEvents({getEvents, getGroups, getProfile, getScope, getIdentity = getScope, getStage,
  getActiveLocation = () => null, getLocationChange = () => 0,
  getPage = () => null, getReadiness = () => ({}), getCanAddMemory = () => true, readPlaces, resolvePlaces = async places => places,
  t, lifeStageText, onExplore, onAdd, onLoadMore, onOverview = () => {}, onChange = () => {}}) {
  let layer, sceneElement, viewer, cesium, removePostRender, scope, journey, stage, signature, selectedKey;
  let focusedCity = null, viewCity = null, listView, lastMode, hasView, overviewRequested = false, overviewMode = true;
  let cityIdentity, handledLocationChange = 0, flyingToCity = null, flightRevision = 0, restoreCity;
  let visibleCityKeys = [];
  let renderedIdentity, toolbarSignature;
  let placeGroups = [];
  const places = new Map();
  const retainedPlaces = new Map();
  const footprint = typeof Image === "undefined" ? null : new Image();
  if (footprint) footprint.src = "/static/map-footprints.svg";

  function activeCity(groups = placeGroups) {
    const identity = getIdentity();
    if (cityIdentity !== identity) {
      handledLocationChange = Math.min(handledLocationChange,getLocationChange());
      cityIdentity = identity;focusedCity = null;restoreCity = null;
      viewCity = null;flyingToCity = null;hasView = undefined;flightRevision++;
    }
    const location = getActiveLocation();
    if (!location) return null;
    const matches = groups.filter(group => matchesEventPlace(location,group.city)
      || group.members.some(member => matchesEventPlace(location,member)));
    return matches.length === 1 ? matches[0].key : undefined;
  }

  function selectCity(city) {
    activeCity();
    restoreCity = city;
    focusedCity = city;viewCity = city;overviewMode = false;selectedKey = null;
    const nodes = journey?.nodes.filter(node => node.groupKey === city) || [];
    if (viewer && nodes.length) frame(nodes,12000,city);
  }

  function loadPlaces(events) {
    for (const event of events) {
      if (!event.canonical || event.status !== "active") {
        retainedPlaces.delete(event.id);
        continue;
      }
      const key = `${event.id}:${event.revision}`;
      if (places.has(key)) continue;
      const captured = scope, identity = getIdentity(), known = retainedPlaces.get(event.id);
      const current = () => getScope() === captured && getIdentity() === identity && places.get(key) === entry;
      const supplied = Array.isArray(event.places);
      const cached = (known?.items || []).filter(link => !event.place_conflicts?.includes(link.role)
        && !(link.role === "setting" && (event.locationConfidenceScore === 0
          || event.location && placeHistoryKey(link.place) !== placeHistoryKey(event.location)
          || Object.hasOwn(event,"location") && !event.location && known.locationKey)));
      const entry = {eventId:event.id, items:supplied ? event.places.filter(item => !item.status || item.status === "supported") : cached,
        conflicted:event.place_conflicts?.includes("setting") || event.places?.some(item => item.status === "conflicted")
          || known?.revision === event.revision && known.conflicted};
      places.set(key, entry);
      if (!supplied && known?.complete && known.revision === event.revision) {
        entry.complete = true;
        continue;
      }
      const retain = () => retainedPlaces.set(event.id,{items:entry.items, revision:event.revision,
        locationKey:event.location ? placeHistoryKey(event.location) : null, conflicted:entry.conflicted, complete:Boolean(entry.complete)});
      // Read into a separate buffer so incomplete pages cannot replace a visible card.
      void (async () => {
        let cursor, readComplete = supplied;
        const items = supplied ? [...entry.items] : [], seen = new Set();
        try {
          if (!supplied) do {
              const page = await readPlaces(event.id, cursor);
              if (!current()) return;
              entry.conflicted ||= page.items?.some(item => item.status === "conflicted");
              items.push(...(page.items || []).filter(item => item.status === "supported"));
              cursor = page.next_cursor;
              if (cursor && seen.has(cursor)) throw new Error("Repeated event location page");
              seen.add(cursor);
            } while (cursor);
          readComplete = true;
          if (!items.length && !entry.conflicted && event.location && event.locationConfidenceScore > 0) {
            items.push({role:"setting",status:"candidate",place:event.location});
          }
          entry.items = items.map(item => {
            const previous = cached.find(link => link.role === item.role && placeHistoryKey(link.place) === placeHistoryKey(item.place));
            return previous ? {...item,place:{...previous.place,...item.place}} : item;
          });
          const resolved = await resolvePlaces(entry.items.map(item => item.place));
          if (!current()) return;
          entry.items = entry.items.map((item,index) => ({...item,place:resolved[index] || item.place}));
          entry.complete = true;
          retain();
        } catch {
          if (!current()) return;
          entry.failed = true;
          if (readComplete) retain();
        }
        if (current()) sync(sceneElement?.isConnected ? sceneElement : null);
      })();
    }
  }

  function updateJourney() {
    const nextScope = getScope();
    const identity = getIdentity();
    if (identity !== renderedIdentity) {
      if (layer) layer.querySelector(".map-memory-cards").innerHTML = "";
      retainedPlaces.clear();
      renderedIdentity = identity;selectedKey = null;listView = null;signature = null;
    }
    if (nextScope !== scope) {
      scope = nextScope;places.clear();signature = null;
      visibleCityKeys = [];
      activeCity();
    }
    const events = getEvents();
    loadPlaces(events);
    stage = getStage();
    const visible = events.filter(event => stage === "all" || event.life_stage === stage)
      .map(event => {
        const entry = places.get(`${event.id}:${event.revision}`);
        return {...event,map_places:entry?.items || event.places,
          map_location_status:entry?.failed ? "failed" : entry && !entry.complete ? "refreshing" : null};
      });
    const eventPlaces = visible.filter(event => !event.status || event.status === "active")
      .flatMap(event => (event.map_places || []).filter(link => link.status !== "conflicted"
        && !event.place_conflicts?.includes(link.role)).map(link => link.place));
    placeGroups = getGroups(eventPlaces);
    journey = buildMapMemoryJourney(visible, placeGroups, getProfile());
  }

  function prepareNodes() {
    if (!journey || getScope() !== scope || getStage() !== stage) updateJourney();
    return journey.nodes;
  }

  function sync(scene, focusedKey = null) {
    updateJourney();
    sceneElement = scene;
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
          const key = target.dataset.memoryRetry;
          const card = journey.nodes.find(node => node.key === key) || cityEventCards(journey.nodes).find(city => city.key === key);
          if (!card) return;
          const ids = new Set((card.nodes || [card]).map(node => node.event.id));
          for (const [key, entry] of places) if (entry.failed && ids.has(entry.eventId)) places.delete(key);
          sync(sceneElement,document.activeElement === target ? card.key : null);
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
          if (city.groupKey !== "unlocated") frame(city.nodes,2500,city.groupKey,{preloadTiles:false});
          position();
          if (focused) [...layer.querySelectorAll("[data-map-memory]")]
            .find(button => button.dataset.mapMemory === city.nodes[0].key)?.focus({preventScroll:true});
        } else {
          const node = journey.nodes.find(node => node.key === key);
          if (!node) return;
          selectedKey = node.key;
          frame([node],2500,node.groupKey);
          position();
        }
      });
      layer.addEventListener("keydown", event => {
        if (event.key === "Escape") { selectedKey = null; position(); }
      });
      scene.append(layer);
      signature = null;toolbarSignature = null;
    }
    const page = getPage();
    layer.hidden = !journey.nodes.length && !journey.unmapped && !places.size && !page?.next_cursor && !page?.page_error;
    scene.classList.toggle("has-map-memories", journey.nodes.length > 0);
    const note = page?.page_error ? t("savedPageChanged") : "";
    const toolbar = layer.querySelector(".map-memory-toolbar");
    const toolbarMarkup = `<span class="map-memory-caption"><img src="/static/map-footprints.svg" alt="" />${escapeHtml(t("mapMemoryJourney"))}</span><button type="button" data-memory-overview>${escapeHtml(t("mapMemoryOverview"))}</button>${note || page?.next_cursor ? `<span class="map-memory-status" role="status">${escapeHtml(note)}${page?.next_cursor || page?.page_error ? `${page?.next_cursor ? escapeHtml(t("mapEventsPartial")) : ""}<button type="button" data-memory-more ${page.loading_page ? "disabled" : ""}>${escapeHtml(t(page.page_error ? "reloadSavedPages" : page.loading_page ? "loadingSavedPage" : "loadMoreEvents"))}</button>` : ""}</span>` : ""}`;
    if (toolbarSignature !== toolbarMarkup) {
      toolbar.innerHTML = toolbarMarkup;
      toolbarSignature = toolbarMarkup;
    }
    position();
    if (focusedKey) [...layer.querySelectorAll("[data-map-memory]")]
      .find(button => button.dataset.mapMemory === focusedKey)?.focus({preventScroll:true});
    onChange(scene);
  }

  function overview() {
    flyingToCity = null;
    focusedCity = null;
    viewCity = null;
    overviewMode = true;
    selectedKey = null;
    overviewRequested = true;
    onOverview();
    sync(sceneElement);
  }

  function frame(nodes, minimum, city = null, {animate = true, preloadTiles = true} = {}) {
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
    viewer.camera.cancelFlight?.();
    const finish = () => { if (revision === flightRevision) { flyingToCity = null;position(); } };
    const destination = cesium.Cartesian3.fromDegrees(longitude, latitude, Math.max(minimum, span * 3.5 * aspect));
    if (!animate) {
      viewer.camera.setView({destination});
      flyingToCity = null;
      return;
    }
    viewer.camera.flyTo({destination, preloadTiles,
      duration:window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 2.8,
      complete:finish, cancel:() => { if (revision === flightRevision) { flyingToCity = null;position(); } }});
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
    // Frame the opening view before Cesium starts checking its tile queue.
    if (!ready && (hasView || !sceneElement.classList.contains("is-cesium-opening"))) return;
    const city = activeCity();
    const locationChanged = getLocationChange() !== handledLocationChange;
    const pendingLocation = locationChanged && city === undefined;
    if (!hasView || locationChanged && !pendingLocation || overviewRequested) {
      const group = !overviewRequested && placeGroups.find(group => group.key === (locationChanged ? city : restoreCity));
      const nodes = group ? [...journey.nodes.filter(node => node.groupKey === group.key),
        ...group.members.map(member => Object.hasOwn(member,"map_pin") ? member.map_pin : member)]
        .filter(place => Number.isFinite(place?.latitude) && Number.isFinite(place?.longitude))
        : [...journey.nodes,...placeGroups.flatMap(group => group.members.map(member => Object.hasOwn(member,"map_pin") ? member.map_pin : member))]
          .filter(place => Number.isFinite(place?.latitude) && Number.isFinite(place?.longitude));
      const pending = [...places.values()].some(entry => !entry.complete && !entry.failed);
      if (nodes.length && (group || !city || !pending || overviewRequested)) {
        hasView = true;
        if (!pendingLocation) handledLocationChange = getLocationChange();
        overviewRequested = false;
        restoreCity = null;
        if (group) { focusedCity = group.key;overviewMode = false; }
        frame(nodes,group ? 12000 : 40000,group?.key,{animate:ready && locationChanged && Boolean(group)});
      }
    }
    if (!ready) return;
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
    viewCity = flyingToCity ?? focusedCity ?? (visibleCities.size === 1 ? [...visibleCities][0]
      : detailed ? mapCityInView(cityLocations,project,width,height) : null);
    const locatedCards = viewCity !== null || detailed ? (cities.find(city => city.groupKey === viewCity)?.nodes || []) : cities;
    const cards = (overviewMode ? cities : locatedCards).filter(card => visibleCities.has(card.groupKey));
    if (selectedKey && !cards.some(card => card.key === selectedKey || card.nodes?.some(node => node.key === selectedKey))) {
      selectedKey = null;
    }
    const options = {t,lifeStageText,profile:getProfile(),readiness:getReadiness(),canAddMemory:getCanAddMemory()};
    const next = JSON.stringify([cards, width < 500, selectedKey, desktop, options.profile?.avatar_style, options.readiness, options.canAddMemory, t("mapMemoryOverview")]);
    const container = layer.querySelector(".map-memory-cards");
    const overflow = layer.querySelector(".map-memory-overflow");
    if (signature !== next) {
      const focused = document.activeElement?.dataset?.mapMemory;
      const nextView = JSON.stringify([viewCity]);
      const scroll = listView === nextView ? container.scrollTop : 0;
      listView = nextView;
      signature = next;
      updateMemoryCards(container,cards.map(card => `<div class="map-memory-anchor" data-memory-key="${escapeHtml(card.key)}"><span class="map-memory-stem" aria-hidden="true"></span>${memoryEventCardMarkup(card,{...options,active:card.key === selectedKey})}</div>`).join(""));
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

  function attach(nextViewer, library) {
    removePostRender?.();
    viewer = nextViewer;cesium = library;
    removePostRender = viewer.scene.postRender.addEventListener(position);
    position();
  }
  function dispose() {
    if (viewer) restoreCity = focusedCity ?? viewCity;
    removePostRender?.();removePostRender = null;viewer = null;layer = null;sceneElement = null;signature = null;lastMode = null;selectedKey = null;viewCity = null;
    hasView = undefined;focusedCity = null;overviewRequested = false;
    flyingToCity = null;
    flightRevision++;
    overviewMode = true;
    visibleCityKeys = [];
  }
  return {sync, attach, dispose, overview, activeCity, selectCity, prepareNodes,
    visibleCities:() => getScope() === scope ? visibleCityKeys : [],
    nodes:() => getScope() === scope ? journey?.nodes || [] : [],
    viewCity:() => { const city = activeCity();return getLocationChange() !== handledLocationChange ? city : flyingToCity ?? viewCity; }};
}
