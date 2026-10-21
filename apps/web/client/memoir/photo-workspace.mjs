import { currentUiLocale, translate, translateWith } from "../i18n.js";
import { escapeHtml } from "./dom.mjs";
import { formatDateExpression } from "./dates.mjs";
import { placeHistoryKey } from "./places.mjs";

export function createPhotoWorkspace({
  api, captureProjectScope, isCurrentProjectScope, loadPlacePictures, placeMapTarget, profile, render, state, toast
}) {
  let photoPaginationObserver = null;

  function mergePlacePictures(existing, incoming) {
    const seen = new Set();
    const unique = [];
    for (const picture of [...existing, ...incoming]) {
      const keys = [picture.asset_id && `asset:${picture.asset_id}`, picture.content_hash && `hash:${picture.content_hash}`];
      for (const value of [picture.original_url, picture.image_url]) {
        if (!value) continue;
        try {
          const url = new URL(value, window.location.origin);
          url.hash = "";
          let filename = "";
          const decodedPath = decodeURIComponent(url.pathname);
          if (["upload.wikimedia.org", "thumb.wikimedia.org"].includes(url.hostname)) {
            let path = decodedPath.replace("/thumb/", "/");
            if (decodedPath.includes("/thumb/")) path = path.slice(0, path.lastIndexOf("/"));
            filename = path.split("/").at(-1).replace(/^\d{14}!/, "");
          } else if (url.hostname === "commons.wikimedia.org" || url.hostname.endsWith(".wikipedia.org")) {
            const match = decodedPath.match(/\/(?:Special:(?:FilePath|Redirect\/file)\/|(?:File|文件|檔案):)(.+)$/i);
            filename = (match?.[1] || url.searchParams.get("title") || "").replace(/^(?:File|文件|檔案):/i, "");
          }
          if (/\.(?:jpe?g|png|webp|gif|tiff?)$/i.test(filename)) keys.push(`wikimedia:${filename.replaceAll("_", " ").trim()}`);
          if (["upload.wikimedia.org", "thumb.wikimedia.org"].includes(url.hostname) && url.pathname.includes("/thumb/")) {
            url.hostname = "upload.wikimedia.org";
            url.pathname = url.pathname.replace("/thumb/", "/").split("/").slice(0, -1).join("/");
          }
          if (/^(live|farm\d+)\.staticflickr\.com$/.test(url.hostname)) {
            url.hostname = "staticflickr.com";
            url.pathname = url.pathname.replace(/_[sqtmnzcbhokw](\.[a-z]+)$/i, "$1");
          }
          for (const key of [...url.searchParams.keys()]) {
            if (key.startsWith("utm_") || ["width", "height", "w", "h", "fbclid", "gclid"].includes(key)) url.searchParams.delete(key);
          }
          url.searchParams.sort();
          keys.push(`image:${url.href}`);
        } catch { /* Invalid URLs cannot create image identities. */ }
      }
      try {
        const source = new URL(picture.source_url);
        const id = source.pathname.match(/^\/photos\/[^/]+\/(\d+)\/?$/)?.[1];
        if (["www.flickr.com", "flickr.com"].includes(source.hostname) && id) keys.push(`flickr:${id}`);
      } catch { /* Source links are optional. */ }
      const valid = keys.filter(Boolean);
      const similar = /^[0-9a-f]{16}$/.test(picture.perceptual_hash || "") && unique.some(other => {
        if (!/^[0-9a-f]{16}$/.test(other.perceptual_hash || "")) return false;
        let difference = BigInt(`0x${picture.perceptual_hash}`) ^ BigInt(`0x${other.perceptual_hash}`);
        let bits = 0;
        while (difference) { difference &= difference - 1n; bits++; }
        return bits <= 6;
      });
      const duplicate = valid.some(key => seen.has(key)) || similar;
      valid.forEach(key => seen.add(key));
      if (!duplicate) unique.push(picture);
    }
    return unique.filter(picture => picture.search_fallback !== "gps_time" || !unique.some(other =>
      other.search_fallback && other.search_fallback !== "gps_time"
      && other.requested_period === picture.requested_period && other.search_place === picture.search_place));
  }

  function placePhotoCenter(entry) {
    const target = entry?.place && typeof placeMapTarget === "function" ? placeMapTarget(entry) : null;
    const candidates = [entry, target?.place === entry?.place ? target : null,
      {latitude: entry?.photo_search_latitude, longitude: entry?.photo_search_longitude}];
    for (const candidate of candidates) {
      if (!candidate || candidate.latitude == null || candidate.longitude == null
          || String(candidate.latitude).trim() === "" || String(candidate.longitude).trim() === ""
          || typeof candidate.latitude === "boolean" || typeof candidate.longitude === "boolean") continue;
      const latitude = Number(candidate.latitude), longitude = Number(candidate.longitude);
      if (Number.isFinite(latitude) && Number.isFinite(longitude) && Math.abs(latitude) <= 90 && Math.abs(longitude) <= 180) {
        return {latitude, longitude};
      }
    }
    return null;
  }

  function photoRequestKey(entry, projectId = state.project?.id) {
    const center = placePhotoCenter({...entry, photo_search_latitude: undefined, photo_search_longitude: undefined});
    return JSON.stringify([projectId, placeHistoryKey(entry), photoSearchPeriod(entry, profile().story_focus),
      center?.latitude ?? null, center?.longitude ?? null, Number.isInteger(entry.research_year) ? entry.research_year : null]);
  }

  function photoMatchesScope(picture, entry, focus = null) {
    const period = photoSearchPeriod(entry, focus);
    const relaxedGps = ["gps", "gps_time"].includes(picture.search_fallback)
      && picture.requested_period === period
      && placeHistoryKey({place: picture.search_place}) === placeHistoryKey({place: entry.photo_search_place || entry.place});
    const relaxedTime = relaxedGps && picture.search_fallback === "gps_time";
    const range = picture.scene_date_range;
    const expression = range?.start && range?.end ? `${range.start}–${range.end}` : picture.date_expression || "";
    const years = Array.from(expression.matchAll(/(?<!\d)((?:18|19|20)\d{2})(?!\d)/g), match => Number(match[1]));
    const normalizedDate = /^(?:18|19|20)\d{2}(?:s|年代|年|(?:[-/]\d{1,2}){1,2})?(?:[–—-](?:18|19|20)\d{2}(?:[-/]\d{1,2}){0,2})?$/;
    const basis = range?.basis || picture.date_basis;
    if ((!relaxedTime && (!years.length || !normalizedDate.test(expression)))
        || basis && !["source_caption","provider_date_taken","original_exif","catalogue","album_caption", ...(relaxedTime ? ["unknown"] : [])].includes(basis)) return false;
    const today = new Date().toLocaleDateString("en-CA", {timeZone: "Australia/Sydney"});
    const isoDate = expression.match(/^(\d{4}-\d{2}-\d{2})(?:[T ].*)?$/)?.[1];
    if (Math.max(...years) > Number(today.slice(0, 4)) || (isoDate && (isoDate > today
        || !Number.isFinite(Date.parse(isoDate)) || new Date(isoDate).toISOString().slice(0, 10) !== isoDate))) return false;
    const bounds = (value, expandBareYear = false) => {
      const years = Array.from(value.matchAll(/(?<!\d)((?:18|19|20)\d{2})(?!\d)/g), match => Number(match[1]));
      if (!years.length) return null;
      return /(?:18|19|20)\d0\s*(?:s|年代)/i.test(value)
        || (expandBareYear && /^\s*(?:18|19|20)\d{2}\s*$/.test(value))
        ? [years[0], years[0] + 9] : [Math.min(...years), Math.max(...years)];
    };
    const requested = bounds(period, true), captured = bounds(expression);
    if (!relaxedTime && requested) {
      const yearOnly = /^(?:18|19|20)\d{2}年?$/.test(period);
      const tolerance = requested[0] === requested[1] && yearOnly ? 10 : 0;
      const decade = Math.floor(requested[0] / 10) * 10;
      const sameDecade = picture.period_match === "decade" && picture.requested_period === period
        && picture.matched_period === `${decade}s` && Math.floor(requested[1] / 10) * 10 === decade
        && captured[0] >= decade && captured[1] <= decade + 9;
      if (!sameDecade && (captured[0] < requested[0] - tolerance || captured[1] > requested[1] + tolerance)) return false;
    } else if (!relaxedTime) {
      const recent = new Date(`${today}T00:00:00Z`);
      const day = recent.getUTCDate();
      recent.setUTCDate(1);
      recent.setUTCFullYear(recent.getUTCFullYear() - 2);
      recent.setUTCDate(Math.min(day, new Date(Date.UTC(recent.getUTCFullYear(), recent.getUTCMonth() + 1, 0)).getUTCDate()));
      const exact = expression.match(/^(\d{4}-\d{2}-\d{2})(?:[T ].*)?$/)?.[1];
      const parsed = /^[A-Za-z]+ \d{1,2},? \d{4}$/.test(expression) ? new Date(expression) : null;
      const date = exact || (parsed && Number.isFinite(parsed.getTime()) ? parsed.toISOString().slice(0, 10) : null);
      const start = date || `${captured[0]}-01-01`, end = date || `${captured[1]}-12-31`;
      if (start < recent.toISOString().slice(0, 10) || end > today) return false;
    }
    if (relaxedGps) return true;
    const center = placePhotoCenter(entry);
    const point = placePhotoCenter({latitude: picture.latitude, longitude: picture.longitude});
    if (!center || !point) return false;
    const radians = value => value * Math.PI / 180;
    const deltaLat = radians(point.latitude - center.latitude), deltaLon = radians(point.longitude - center.longitude);
    const haversine = Math.sin(deltaLat / 2) ** 2 + Math.cos(radians(center.latitude)) * Math.cos(radians(point.latitude)) * Math.sin(deltaLon / 2) ** 2;
    return 6371.0088 * 2 * Math.asin(Math.sqrt(Math.min(1, Math.max(0, haversine)))) <= 20;
  }

  function photoPaginationMarkup(entry) {
    if (!entry) return "";
    const requestKey = photoRequestKey(entry);
    const request = state.photoRequests?.get(requestKey);
    if (!entry.photo_next_cursor) {
      if (request?.loading) return `<p class="photo-search-status assistant-progress-shimmer" role="status">${escapeHtml(translate("Memoir.workspace.picturesLoading"))}</p>`;
      if (request?.error) return `<button type="button" class="button button-secondary button-small" data-photo-retry="${escapeHtml(placeHistoryKey(entry))}">${escapeHtml(translate("Memoir.workspace.picturesSearchRetry"))}</button>`;
      return "";
    }
    const label = request?.loading ? "picturesLoading" : request?.error ? "picturesRetry" : "picturesMore";
    return `<div class="photo-pagination"><button type="button" class="button button-secondary button-small" data-photo-more="${escapeHtml(placeHistoryKey(entry))}" ${request?.loading ? 'disabled aria-busy="true"' : ""}>${escapeHtml(translate(`Memoir.workspace.${label}`))}</button></div>`;
  }

  function bindPhotoPagination() {
    photoPaginationObserver?.disconnect();
    const retry = document.querySelector("[data-photo-retry]");
    if (retry) retry.addEventListener("click", () => {
      const entry = (profile().memory_places || []).find(item => placeHistoryKey(item) === retry.dataset.photoRetry);
      if (entry) void loadPlacePictures(entry, state.project?.id, { force: true });
    });
    const button = document.querySelector("[data-photo-more]");
    if (!button) return;
    const projectId = state.project?.id;
    const entry = (profile().memory_places || []).find(item => placeHistoryKey(item) === button.dataset.photoMore);
    if (!entry || !entry.photo_next_cursor) return;
    const load = () => {
      if (button.isConnected && state.project?.id === projectId) void loadPlacePictures(entry, projectId, { more: true });
    };
    button.addEventListener("click", load);
    const requestKey = photoRequestKey(entry, projectId);
    if (state.photoRequests?.get(requestKey)?.error || !("IntersectionObserver" in window)) return;
    const wall = button.closest(".place-pictures");
    photoPaginationObserver = new IntersectionObserver(entries => {
      if (entries.some(item => item.isIntersecting)) load();
    }, { root: wall && wall.scrollHeight > wall.clientHeight + 1 ? wall : null,
      rootMargin: "0px 0px 160px 0px" });
    photoPaginationObserver.observe(button);
  }

  function photoSearchPeriod(entry) {
    if (typeof entry?.research_period === "string") return entry.research_period;
    // Compatibility for already saved numeric calendar fields only.
    return /^(?:18|19|20)\d{2}(?:s|年代|年(?:\d{1,2}月(?:\d{1,2}日)?)?|[-–—](?:18|19|20)\d{2})?$/.test(entry?.period || "") ? entry.period : "";
  }

  function referenceUrl(value) {
    try {
      const url = new URL(value, window.location.origin);
      return url.protocol === "https:" || (url.origin === window.location.origin && url.pathname.startsWith("/static/")) ? url.href : "";
    } catch { return ""; }
  }

  function pictureWall(pictures = [], entry = null) {
    const t = key => escapeHtml(translate(`Memoir.workspace.${key}`));
    const renderablePictures = mergePlacePictures([], pictures).filter((picture) => picture.allowed_actions?.embed
      && (!entry || photoMatchesScope(picture, entry, profile().story_focus)));
    if (!renderablePictures.length) return "";
    return `<section class="place-pictures" ${entry ? `data-photo-place="${escapeHtml(placeHistoryKey(entry))}"` : ""} aria-label="${t("publicReferenceCues")}">${renderablePictures.map((picture) => {
      const src = referenceUrl(picture.image_url);
      const source = referenceUrl(picture.source_url);
      const sceneDate = formatDateExpression(picture.date_expression ||
        [picture.scene_date_range?.start, picture.scene_date_range?.end].filter(Boolean).join("–"), currentUiLocale())
        || translate("Memoir.workspace.dateUnknown");
      const detail = [...new Set([picture.reference_place,
        picture.attribution || picture.location || picture.label || t("historicalReference")].filter(Boolean))].join(" · ");
      const sourceLink = source
        ? `<a href="${escapeHtml(source)}" target="_blank" rel="noreferrer">${escapeHtml(picture.title || t("historicalReference"))}</a>`
        : `<strong>${escapeHtml(picture.title || t("historicalReference"))}</strong>`;
      const media = src
        ? `<img src="${escapeHtml(src)}" alt="${escapeHtml(picture.title || "")}" loading="lazy" />`
        : `<div class="picture-wall-placeholder ${picture.kind === "video" ? "video-art" : "image-art"}" aria-hidden="true"><span>${picture.kind === "video" ? "▶" : "✦"}</span></div>`;
      const periodNote = picture.period_match === "decade" ? ` · ${t("sameDecadeReference")}`
        : picture.period_match === "nearby" ? ` · ${t("nearbyPeriodReference")}`
        : picture.period_match === "any_time" ? ` · ${t("otherPeriodReference")}` : "";
      const locationNote = ["gps", "gps_time"].includes(picture.search_fallback)
        ? ` · ${t("sourceLocationReference")}` : "";
      const controls = photoMemoryControls(picture, entry, media, Boolean(src));
      return `<figure>${controls.media}<figcaption>${sourceLink}<small>${escapeHtml(sceneDate)} · ${escapeHtml(detail)}${periodNote}${locationNote}</small>${controls.favorite}</figcaption></figure>`;
    }).join("")}${photoPaginationMarkup(entry)}</section>`;
  }

  function photoMemoryState() {
    return profile().photo_memories?.[state.project?.id] || {favorites: [], selected: null};
  }

  function photoMemoryControls(picture, entry, media, selectable) {
    if (!selectable) return {media: `<div class="picture-wall-media">${media}</div>`, favorite: ""};
    const t = key => escapeHtml(translate(`Memoir.workspace.${key}`));
    const photo = Object.fromEntries(["image_url", "original_url", "source_url", "asset_id", "title", "attribution", "date_expression"]
      .map(key => [key, picture[key] || ""]));
    photo.place = picture.place || picture.reference_place || entry?.place || "";
    photo.period = picture.period || (entry ? photoSearchPeriod(entry, profile().story_focus) : "");
    const key = photo.original_url || photo.image_url;
    const saved = photoMemoryState();
    const favorite = saved.favorites.some(item => item.key === key);
    const selected = saved.selected === key;
    const disabled = state.loading || state.photoMemoryTask ? "disabled" : "";
    const attrs = `data-photo-reference="${escapeHtml(JSON.stringify(photo))}" data-photo-key="${escapeHtml(key)}"`;
    return {
      media: `<button type="button" class="picture-wall-media photo-memory-select ${selected ? "is-selected" : ""}" data-photo-memory="select" ${attrs} aria-pressed="${selected}" aria-label="${t("recallFromPhoto")}: ${escapeHtml(photo.title)}" ${disabled}>${media}<span class="photo-memory-hint">${t(selected ? "photoSelected" : "recallFromPhoto")}</span></button>`,
      favorite: `<button type="button" class="photo-favorite ${favorite ? "is-favorite" : ""}" data-photo-memory="${favorite ? "unfavorite" : "favorite"}" ${attrs} aria-pressed="${favorite}" aria-label="${t(favorite ? "removePhotoFavorite" : "favoritePhoto")}: ${escapeHtml(photo.title)}" ${disabled}><span aria-hidden="true">${favorite ? "★" : "☆"}</span> ${t(favorite ? "photoFavorited" : "favoritePhoto")}</button>`,
    };
  }

  function favoritePhotoWall() {
    const favorites = photoMemoryState().favorites;
    if (!favorites.length) return "";
    return `<details class="photo-favorites" ${state.photoFavoritesOpen ? "open" : ""}><summary>${escapeHtml(translateWith("Memoir.workspace.favoritePhotos", {count:favorites.length}))}</summary>${pictureWall(favorites.map(photo => ({...photo, allowed_actions:{embed:true}})))}</details>`;
  }

  function selectedPhotoCue() {
    const saved = photoMemoryState();
    const photo = saved.favorites.find(item => item.key === saved.selected);
    if (!photo) return "";
    const src = referenceUrl(photo.image_url);
    return `<div class="selected-photo-cue" role="status">${src ? `<img src="${escapeHtml(src)}" alt="" />` : ""}<div><strong>${escapeHtml(translate("Memoir.workspace.photoSelected"))}</strong><span>${escapeHtml(photo.title || photo.place)}</span><small>${escapeHtml(translate("Memoir.workspace.photoQuestionCue"))}</small></div><button type="button" class="text-button" data-photo-memory="clear" aria-label="${escapeHtml(translate("Memoir.workspace.clearPhotoCue"))}" ${state.loading || state.photoMemoryTask ? "disabled" : ""}>×</button></div>`;
  }

  function bindPhotoMemoryActions(root = document) {
    const scope = captureProjectScope();
    for (const details of root.querySelectorAll(".photo-favorites")) {
      if (details.photoMemoryBound) continue;
      details.photoMemoryBound = true;
      details.addEventListener("toggle", () => {
        if (details.isConnected && isCurrentProjectScope(scope)) state.photoFavoritesOpen = details.open;
      });
    }
    for (const button of root.querySelectorAll("[data-photo-memory]")) {
      if (button.photoMemoryBound) continue;
      button.photoMemoryBound = true;
      button.addEventListener("click", () => {
        const photo = button.dataset.photoReference ? JSON.parse(button.dataset.photoReference) : null;
        void savePhotoMemory(button.dataset.photoMemory, photo);
      });
    }
  }

  async function savePhotoMemory(action, photo = null) {
    if (!state.project || state.loading || state.photoMemoryTask) return;
    const scope = captureProjectScope();
    const task = {};
    task.done = new Promise(resolve => { task.finish = resolve; });
    state.photoMemoryTask = task;
    render();
    try {
      const saved = await api(`/v1/projects/${scope.projectId}/photo-memories`, {
        method:"PUT", body:JSON.stringify({action, ...(photo ? {photo} : {})}),
      });
      if (!isCurrentProjectScope(scope)) return;
      state.project.profile = {...profile(), photo_memories:{...(profile().photo_memories || {}), [scope.projectId]:saved}};
      state.photoMemoryRevision = (state.photoMemoryRevision || 0) + 1;
    } catch (error) {
      if (isCurrentProjectScope(scope)) toast(translate(`Memoir.workspace.${error.status === 409 ? "photoSaveBusy" : "photoSaveError"}`));
    } finally {
      if (state.photoMemoryTask === task) state.photoMemoryTask = null;
      task.finish();
      if (isCurrentProjectScope(scope)) {
        render();
        const key = photo?.original_url || photo?.image_url;
        const root = document.querySelector(".map-photo-album-viewer[open]") || document;
        [...root.querySelectorAll("[data-photo-memory]")].find(button => button.dataset.photoKey === key
          && (action === "select" ? button.dataset.photoMemory === "select"
            : ["favorite", "unfavorite"].includes(button.dataset.photoMemory)))?.focus({preventScroll:true});
      }
    }
  }

  function searchedPictures() {
    const items = [];
    const seen = new Set();
    for (const message of state.chat) {
      for (const cue of message.cues || []) {
        const key = cue.asset_id || cue.id || cue.source_url || cue.title;
        if (!key || seen.has(key)) continue;
        seen.add(key);
        items.push(cue);
      }
    }
    return items;
  }

  function renderablePictureItems(pictures = []) {
    return pictures.filter((picture) => picture.allowed_actions?.embed);
  }

  function workspacePictureItems(place, group = null) {
    const period = photoSearchPeriod(place, profile().story_focus);
    const matchesPeriod = source => !source || !Object.hasOwn(source, "photo_search_period") || source.photo_search_period === period;
    const eligible = pictures => renderablePictureItems(pictures).filter(picture => photoMatchesScope(picture, place, profile().story_focus));
    let pictures = matchesPeriod(place) ? eligible(place?.pictures || []) : [];
    if (!pictures.length && group) {
      // Grouping changes the map, while photographs remain attached to their
      // source. Keep the city's saved references visible during a child search.
      const members = group.members.filter(member => placeHistoryKey(member) !== placeHistoryKey(place));
      const cityKey = placeHistoryKey(group.city);
      const ordered = [...members.filter(member => placeHistoryKey(member) === cityKey),
        ...members.filter(member => placeHistoryKey(member) !== cityKey)];
      const samePeriod = ordered.filter(member => matchesPeriod(member) && eligible(member.pictures).length);
      pictures = (samePeriod.length ? samePeriod : ordered).flatMap(member =>
        eligible(member.pictures).map(picture => ({...picture, reference_place: member.place})));
    }
    if (!pictures.length) pictures = eligible(place?.pictures || []);
    return mergePlacePictures([], [...pictures, ...searchedPictures()])
      .filter(picture => photoMatchesScope(picture, place, profile().story_focus));
  }

  function responsePhotoMarkup(photos) {
    const cards = state.photoTurns.cards(photos);
    return `<div class="response-photo-cards">${cards.map(photo => {
      const privatePhoto = photo.kind === "private_upload";
      const id = privatePhoto ? photo.photo_id.replace(/^upload:/, "") : "";
      const image = privatePhoto ? `<img data-private-response-photo="${escapeHtml(id)}" alt="${escapeHtml(photo.title)}" hidden />`
        : referenceUrl(photo.image_url) ? `<img src="${escapeHtml(referenceUrl(photo.image_url))}" alt="${escapeHtml(photo.title)}" loading="lazy" />` : "";
      const source = !privatePhoto && referenceUrl(photo.source_url);
      return `<figure class="response-photo-card" data-photo-kind="${photo.kind}">${image}<figcaption><small>${escapeHtml(translate(`Memoir.story.${privatePhoto ? "privatePhoto" : "publicPhoto"}`))}</small><strong>${escapeHtml(photo.title)}</strong>${photo.description ? `<p>${escapeHtml(photo.description)}</p>` : ""}<p data-photo-unavailable hidden>${escapeHtml(translate("Memoir.story.photoUnavailable"))}</p>${source ? `<a href="${escapeHtml(source)}" target="_blank" rel="noreferrer">${escapeHtml(translate("Memoir.story.photoSource"))}</a>` : ""}</figcaption></figure>`;
    }).join("")}</div>`;
  }

  return {
    bindPhotoMemoryActions, bindPhotoPagination, favoritePhotoWall, mergePlacePictures, photoMatchesScope,
    photoRequestKey, photoSearchPeriod, pictureWall, placePhotoCenter, renderablePictureItems,
    responsePhotoMarkup, searchedPictures, selectedPhotoCue, workspacePictureItems
  };
}
