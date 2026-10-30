import { escapeHtml } from "./dom.mjs";
import { buildMapMemoryJourney, cityEventCards, eventAgeLabel, layoutMemoryCards, memoryEventCardMarkup } from "./map-memory-journey.mjs";

export function createMapMemoryEvents({getEvents, getGroups, getProfile, getScope, getIdentity = getScope, getStage,
  getPage = () => null, readPlaces, resolvePlaces = async places => places,
  t, lifeStageText, onExplore, onLoadMore, onOverview = () => {}, onChange = () => {}}) {
  let layer, sceneElement, viewer, cesium, removePostRender, scope, journey, signature, selectedKey;
  let expandedCity = null, lastMode, initialIdentity, overviewRequested = false;
  const places = new Map();
  const footprint = typeof Image === "undefined" ? null : new Image();
  if (footprint) footprint.src = "/static/map-footprints.svg";

  function loadPlaces(events) {
    for (const event of events) {
      if (!event.canonical || event.status !== "active") continue;
      const key = `${event.id}:${event.revision}`;
      if (places.has(key)) continue;
      const captured = scope;
      const supplied = Array.isArray(event.places);
      const entry = {items:supplied ? event.places.filter(item => !item.status || item.status === "supported") : []};
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
              entry.items.push(...(page.items || []).filter(item => item.status === "supported"));
              cursor = page.next_cursor;
              if (cursor && seen.has(cursor)) throw new Error("Repeated event location page");
              seen.add(cursor);
            } while (cursor);
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
    if (nextScope !== scope) { scope = nextScope; places.clear(); selectedKey = null; expandedCity = null; signature = null; }
    sceneElement = scene;
    const events = getEvents();
    loadPlaces(events);
    const stage = getStage();
    const visible = events.filter(event => stage === "all" || event.life_stage === stage)
      .map(event => ({...event, map_places:places.get(`${event.id}:${event.revision}`)?.items || event.places}));
    const eventPlaces = visible.filter(event => !event.status || event.status === "active")
      .flatMap(event => (event.map_places || []).filter(link => link.status !== "conflicted"
        && !event.place_conflicts?.includes(link.role)).map(link => link.place));
    journey = buildMapMemoryJourney(visible, getGroups(eventPlaces), getProfile());
    if (!scene) return;
    layer = scene.querySelector(".map-memory-layer");
    if (!layer) {
      layer = document.createElement("div");
      layer.className = "map-memory-layer";
      layer.innerHTML = '<canvas class="map-memory-trail" aria-hidden="true"></canvas><div class="map-memory-toolbar"></div><div class="map-memory-cards"></div><div class="map-memory-overflow"></div><section class="map-memory-detail" hidden></section>';
      layer.addEventListener("click", event => {
        const target = event.target.closest("[data-map-memory], [data-memory-overview], [data-memory-close], [data-memory-explore], [data-memory-retry], [data-memory-more]");
        if (!target) return;
        if (target.hasAttribute("data-memory-overview")) { overview(); return; }
        if (target.hasAttribute("data-memory-close")) { selectedKey = null; updateDetail(); return; }
        if (target.hasAttribute("data-memory-explore")) { onExplore(target.dataset.memoryExplore); return; }
        if (target.hasAttribute("data-memory-more")) { onLoadMore(); return; }
        if (target.hasAttribute("data-memory-retry")) {
          for (const [key, entry] of places) if (entry.failed) places.delete(key);
          sync(sceneElement);
          return;
        }
        const key = target.dataset.mapMemory;
        const city = cityEventCards(journey.nodes).find(city => city.key === key);
        if (city) {
          expandedCity = city.groupKey;
          selectedKey = null;
          frame(city.nodes, 2500);
          signature = null;
          position();
        } else {
          selectedKey = key;
          if (!window.matchMedia("(max-width: 760px)").matches) {
            const node = journey.nodes.find(node => node.key === key);
            if (node) frame([node],2500);
          }
          updateDetail();
        }
      });
      layer.addEventListener("keydown", event => {
        if (event.key === "Escape") { selectedKey = null; updateDetail(); }
      });
      scene.append(layer);
      signature = null;
    }
    const page = getPage();
    layer.hidden = !journey.nodes.length && !places.size && !page?.next_cursor;
    scene.classList.toggle("has-map-memories", journey.nodes.length > 0);
    const failed = [...places.values()].some(entry => entry.failed);
    const pending = [...places.values()].some(entry => !entry.complete && !entry.failed);
    const note = failed ? t("mapEventLocationsUnavailable") : pending ? t("mapEventLocationsLoading")
      : journey.unmapped ? t("mapEventsUnmapped", {count:journey.unmapped}) : "";
    layer.querySelector(".map-memory-toolbar").innerHTML = `<span class="map-memory-caption"><img src="/static/map-footprints.svg" alt="" />${escapeHtml(t("mapMemoryJourney"))}</span><button type="button" data-memory-overview>${escapeHtml(t("mapMemoryOverview"))}</button>${note || page?.next_cursor ? `<span class="map-memory-status" role="status">${escapeHtml(note)}${failed ? `<button type="button" data-memory-retry>${escapeHtml(t("mapEventRetry"))}</button>` : ""}${page?.next_cursor ? `${escapeHtml(t("mapEventsPartial"))}<button type="button" data-memory-more ${page.loading_page ? "disabled" : ""}>${escapeHtml(t(page.loading_page ? "loadingSavedPage" : "loadMoreEvents"))}</button>` : ""}</span>` : ""}`;
    signature = null;
    if (viewer && !viewer.isDestroyed()) position();
    updateDetail();
    if (focusedKey) [...layer.querySelectorAll("[data-map-memory]")]
      .find(button => button.dataset.mapMemory === focusedKey)?.focus({preventScroll:true});
    onChange(scene);
  }

  function overview() {
    expandedCity = null;
    selectedKey = null;
    overviewRequested = true;
    onOverview();
    sync(sceneElement);
  }

  function frame(nodes, minimum) {
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
    viewer.camera.flyTo({destination:cesium.Cartesian3.fromDegrees(longitude, latitude, Math.max(minimum, span * 3.5 * aspect)),
      duration:window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 1.1});
  }

  function updateDetail() {
    if (!layer) return;
    const panel = layer.querySelector(".map-memory-detail");
    const node = journey?.nodes.find(node => node.key === selectedKey);
    const wasOpen = !panel.hidden;
    panel.hidden = !node;
    if (!node) {
      if (wasOpen) [...layer.querySelectorAll("[data-map-memory]")].find(button => button.getAttribute("aria-expanded") === "true")?.focus({preventScroll:true});
      for (const button of layer.querySelectorAll("[data-map-memory]")) button.setAttribute("aria-expanded", "false");
      return;
    }
    const titleId = "map-memory-detail-title";
    const detail = node.event.summary || node.event.source_refs?.[0]?.quote || "";
    panel.setAttribute("aria-labelledby", titleId);
    panel.innerHTML = `<header><span class="map-memory-age">${escapeHtml(eventAgeLabel(node.age,t))}</span><button type="button" data-memory-close aria-label="${escapeHtml(t("mapEventClose"))}">×</button></header><h3 id="${titleId}">${escapeHtml(node.event.title)}</h3>${detail && detail !== node.event.title ? `<p>${escapeHtml(detail)}</p>` : ""}<small>${escapeHtml(node.place)}${node.event.life_stage && node.event.life_stage !== "unplaced" ? ` · ${escapeHtml(lifeStageText(node.event.life_stage,"label"))}` : ""}</small>${node.cityOnly ? `<p class="map-memory-uncertainty">${escapeHtml(t("mapEventCityLocation"))}</p>` : ""}${node.uncertainty || node.event.timing_conflict ? `<p class="map-memory-uncertainty">${escapeHtml(node.uncertainty || t("mapEventTimeUncertain"))}</p>` : ""}<button type="button" class="text-button" data-memory-explore="${escapeHtml(node.event.id)}">${escapeHtml(t("exploreThisMemory"))}</button>`;
    for (const button of layer.querySelectorAll("[data-map-memory]")) button.setAttribute("aria-expanded", String(button.dataset.mapMemory === selectedKey));
    if (!wasOpen) panel.querySelector("[data-memory-close]").focus({preventScroll:true});
  }

  function position() {
    if (!layer?.isConnected || !viewer || viewer.isDestroyed() || getScope() !== scope) return;
    const ready = sceneElement.classList.contains("is-cesium-map");
    layer.classList.toggle("is-ready", ready);
    if (!ready) return;
    const identity = getIdentity();
    if (initialIdentity !== identity || overviewRequested) {
      const nodes = journey.nodes.length ? journey.nodes : !window.matchMedia("(max-width: 760px)").matches || overviewRequested
        ? getGroups([]).flatMap(group => group.members.map(member => Object.hasOwn(member,"map_pin") ? member.map_pin : member))
          .filter(place => Number.isFinite(place?.latitude) && Number.isFinite(place?.longitude)) : [];
      if (nodes.length) { initialIdentity = identity;overviewRequested = false;frame(nodes,40000); }
    }
    const width = layer.clientWidth, height = layer.clientHeight;
    layer.classList.toggle("is-compact",width < 500);
    const desktop = !window.matchMedia("(max-width: 760px)").matches;
    layer.classList.toggle("is-desktop",desktop);
    const zoom = viewer.scene.mode === cesium.SceneMode.SCENE2D ? viewer.camera.frustum.right - viewer.camera.frustum.left
      : viewer.camera.positionCartographic.height;
    const detailed = zoom < 18000;
    if ((lastMode === true && !detailed) || zoom > 80000) expandedCity = null;
    lastMode = detailed;
    const cards = desktop ? journey.nodes.map(node => ({...node,place:detailed ? node.place : node.city,overview:!detailed}))
      : detailed ? journey.nodes : cityEventCards(journey.nodes).flatMap(city => city.groupKey === expandedCity ? city.nodes : [city]);
    const next = JSON.stringify([cards, width < 500, selectedKey, desktop]);
    const container = layer.querySelector(".map-memory-cards");
    const overflow = layer.querySelector(".map-memory-overflow");
    if (signature !== next) {
      const focused = document.activeElement?.dataset?.mapMemory;
      const scroll = container.scrollTop;
      signature = next;
      container.innerHTML = cards.map(card => `<div class="map-memory-anchor" data-memory-key="${escapeHtml(card.key)}"><span class="map-memory-stem" aria-hidden="true"></span>${memoryEventCardMarkup(card,{t,lifeStageText,active:card.key === selectedKey})}</div>`).join("");
      overflow.replaceChildren();
      container.scrollTop = scroll;
      if (focused) [...container.querySelectorAll("[data-map-memory]")].find(button => button.dataset.mapMemory === focused)?.focus({preventScroll:true});
    }
    const project = point => cesium.SceneTransforms.worldToWindowCoordinates(viewer.scene,
      cesium.Cartesian3.fromDegrees(point.longitude,point.latitude));
    if (desktop) {
      for (const anchor of layer.querySelectorAll(".map-memory-anchor")) {
        anchor.hidden = false;
        anchor.removeAttribute("style");
        if (anchor.parentElement !== container) container.append(anchor);
      }
      overflow.hidden = true;
      drawTrail(project,width,height);
      return;
    }
    const points = cards.map(card => ({key:card.key,...project(card)}));
    const cardWidth = width < 500 ? 164 : 194;
    const boxes = layoutMemoryCards(points,width,height,cardWidth,126,88,
      Math.max(54,layer.querySelector(".map-memory-toolbar").offsetHeight + 18));
    for (const anchor of layer.querySelectorAll(".map-memory-anchor")) {
      const box = boxes.find(box => box.key === anchor.dataset.memoryKey);
      anchor.hidden = !box;
      if (!box) continue;
      const parent = box.overflow ? overflow : container;
      if (anchor.parentElement !== parent) parent.append(anchor);
      if (box.overflow) { anchor.removeAttribute("style"); continue; }
      anchor.style.left = `${box.left}px`;
      anchor.style.top = `${box.top}px`;
      const dx = box.x - box.left - cardWidth / 2, dy = box.y - box.top - 126;
      const stem = anchor.querySelector(".map-memory-stem");
      stem.style.height = `${Math.hypot(dx,dy)}px`;
      stem.style.transform = `rotate(${Math.atan2(-dx,dy)}rad)`;
    }
    overflow.hidden = !overflow.querySelector(".map-memory-anchor:not([hidden])");
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
        const node = journey.nodes.find(node => node.key === anchor.dataset.memoryKey);
        if (!node) continue;
        const point = project(lastMode ? node : {latitude:node.cityLatitude,longitude:node.cityLongitude});
        const card = anchor.getBoundingClientRect();
        if (!point || point.x < 0 || point.x > width || point.y < 0 || point.y > height
            || card.top < list.top || card.bottom > list.bottom) continue;
        context.beginPath();context.moveTo(card.right-bounds.left,card.top+card.height/2-bounds.top);
        context.lineTo(point.x,point.y);context.strokeStyle = "#45665266";context.lineWidth = 1;context.stroke();
      }
    }
    for (const leg of journey.legs) {
      const from = project(leg.from), to = project(leg.to);
      if (!from || !to) continue;
      const dx = to.x - from.x, dy = to.y - from.y, distance = Math.hypot(dx,dy);
      if (distance < 12 || distance > Math.max(width,height) * 4) continue;
      const bend = Math.min(50, distance * .12), cx = (from.x + to.x) / 2 - dy / distance * bend,
        cy = (from.y + to.y) / 2 + dx / distance * bend;
      context.beginPath();context.moveTo(from.x,from.y);context.quadraticCurveTo(cx,cy,to.x,to.y);
      context.strokeStyle = leg.stageTransition ? "#9b5a39" : "#456652";
      context.lineWidth = 1.5;context.setLineDash([2,7]);context.globalAlpha = .5;context.stroke();context.setLineDash([]);
      const steps = Math.min(80, Math.floor(distance / 30));
      if (footprint?.complete && footprint.naturalWidth) for (let step = 1; step < steps; step++) {
        const at = step / steps, rest = 1 - at;
        const x = rest * rest * from.x + 2 * rest * at * cx + at * at * to.x;
        const y = rest * rest * from.y + 2 * rest * at * cy + at * at * to.y;
        if (x < -20 || x > width + 20 || y < -20 || y > height + 20) continue;
        context.save();context.translate(x,y);context.rotate(Math.atan2(2 * rest * (cy-from.y)+2*at*(to.y-cy),2*rest*(cx-from.x)+2*at*(to.x-cx)) + Math.PI/2);
        context.globalAlpha = .78;context.drawImage(footprint,-8,-8,16,16);context.restore();
      }
      context.globalAlpha = 1;
    }
    const pins = lastMode ? journey.nodes : cityEventCards(journey.nodes);
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
    removePostRender?.();removePostRender = null;viewer = null;layer = null;sceneElement = null;signature = null;lastMode = null;selectedKey = null;
  }
  return {sync, attach, dispose, overview, nodes:() => journey?.nodes || []};
}
