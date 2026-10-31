import { escapeHtml } from "./dom.mjs";
import { placeHistoryKey } from "./places.mjs";

const stages = ["baby", "childhood", "adolescence", "young_adulthood", "midlife", "later_life"];
const avatars = ["baby", "child", "adolescent", "young_adult", "middle_aged", "senior"];
const coordinates = place => Number.isFinite(place?.latitude) && Math.abs(place.latitude) <= 90
  && Number.isFinite(place?.longitude) && Math.abs(place.longitude) <= 180;
const label = value => String(value || "").normalize("NFKC").trim().toLowerCase().replace(/([\u3400-\u9fff])[市省]$/, "$1");
const number = value => Number.isInteger(value) && value >= 0 ? value : null;
const ageUnits = ["zero","one","two","three","four","five","six","seven","eight","nine","ten","eleven","twelve","thirteen","fourteen","fifteen","sixteen","seventeen","eighteen","nineteen"];
const ageTens = ["twenty","thirty","forty","fifty","sixty","seventy","eighty","ninety"];
const ageWord = `(?:${[...ageUnits,...ageTens].join("|")})(?:[- ](?:${ageUnits.slice(1,10).join("|")}))?`;
const wordAge = value => value.toLowerCase().split(/[- ]/).reduce((sum,word) =>
  sum + (ageUnits.includes(word) ? ageUnits.indexOf(word) : (ageTens.indexOf(word) + 2) * 10),0);

export function matchesEventPlace(place, candidate) {
  if (label(place.place) !== label(candidate.place)) return false;
  const path = item => (item.hierarchy || []).map(label).filter(part => !["earth","地球"].includes(part));
  const a = path(place), b = path(candidate);
  if (!a.length || !b.length) return true;
  if (a[0] !== b[0]) return false;
  const shorter = a.length <= b.length ? a : b, longer = a.length <= b.length ? b : a;
  let at = 0;
  for (const part of longer) if (part === shorter[at]) at++;
  return at === shorter.length;
}

function eventCalendar(event) {
  if (event.timing_conflict) return null;
  const timing = event.temporal || {};
  const expression = timing.expression || event.date_expression || "";
  const precision = timing.precision || event.precision;
  const exact = expression.match(/^([12]\d{3})[-/年](\d{1,2})(?:[-/月](\d{1,2})日?)?月?$/);
  if (exact && ["day","month","exact"].includes(precision)) {
    const year = Number(exact[1]), month = Number(exact[2]), day = Number(exact[3] || 1);
    const start = Date.UTC(year,month - 1,precision === "month" ? 1 : day);
    const date = new Date(start);
    if (date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === (precision === "month" ? 1 : day)) {
      return {start, end:precision === "month" ? Date.UTC(year,month,0) : start};
    }
  }
  const year = number(timing.year_start) ?? (/^[12]\d{3}$/.test(expression) ? Number(expression) : null);
  const end = number(timing.year_end) ?? year;
  return year && end >= year ? {start:Date.UTC(year,0,1),end:Date.UTC(end,11,31)} : null;
}

function estimatedAge(event, profile) {
  const estimate = event.temporal_estimate || {}, birth = number(profile.birth_year);
  const start = number(estimate.age_start) ?? (birth && estimate.year_start >= birth ? estimate.year_start - birth : null);
  const end = number(estimate.age_end) ?? (birth && estimate.year_end >= birth ? estimate.year_end - birth : start);
  return start !== null && end >= start && end <= 130 ? {start,end,approximate:true,estimated:true} : null;
}

export function eventAge(event, profile = {}) {
  if (event.timing_conflict) return {start:null, end:null};
  const timing = event.temporal || {};
  const expression = timing.expression || event.date_expression || "";
  if ((timing.precision || event.precision) === "age") {
    const match = expression.match(/(?:\bage(?:d)?\s*|\bat\s+|\bwhen I was\s+)(\d{1,3})(?:\s*[-–至到]\s*(\d{1,3}))?|(?<!\d)(\d{1,3})(?:\s*[-–至到]\s*(\d{1,3}))?\s*(?:岁|years? old)/i);
    if (match) return {start:Number(match[1] || match[3]), end:Number(match[2] || match[4] || match[1] || match[3]), approximate:false};
    const words = expression.match(new RegExp(`(?:\\bage(?:d)?\\s+|\\bat\\s+|\\bwhen I was\\s+)(${ageWord})\\b(?:\\s+(?:to|–)\\s+(${ageWord})\\b)?`,"i"));
    if (words) return {start:wordAge(words[1]),end:wordAge(words[2] || words[1]),approximate:false};
    const chinese = expression.match(/([零一二三四五六七八九十两]{1,3})岁/);
    if (chinese) {
      const digits = "零一二三四五六七八九";
      const parts = chinese[1].replaceAll("两","二").split("十");
      const value = parts.length === 1 ? digits.indexOf(parts[0]) : (parts[0] ? digits.indexOf(parts[0]) : 1) * 10 + (parts[1] ? digits.indexOf(parts[1]) : 0);
      if (value >= 0) return {start:value,end:value,approximate:false};
    }
    return estimatedAge(event,profile) || {start:null, end:null, expression};
  }
  const birth = number(profile.birth_year);
  const start = number(timing.year_start) ?? Number(expression.match(/\b([12]\d{3})\b/)?.[1] || 0);
  const end = number(timing.year_end) ?? start;
  if (birth && start >= birth && end >= start && !event.timing_conflict) {
    return {start:start - birth, end:end - birth, approximate:true};
  }
  return estimatedAge(event,profile) || {start:null, end:null};
}

export function eventAgeLabel(age, t) {
  if (age.expression) return age.expression;
  if (age.start === null) return t("mapEventAgeUnknown");
  const value = age.start === age.end ? String(age.start) : `${age.start}–${age.end}`;
  return t(age.approximate ? "mapEventAgeApproximate" : "mapEventAge", {age:value});
}

export function memoryEventTiming(event, profile = {}, index = 0) {
  const age = eventAge(event, profile), stated = eventCalendar(event);
  const estimate = event.timing_conflict ? null : event.temporal_estimate;
  const statedYear = number(event.temporal?.year_start) ?? (stated ? new Date(stated.start).getUTCFullYear() : null);
  const year = event.timing_conflict ? null : statedYear ?? number(estimate?.year_start)
    ?? (age.start !== null && number(profile.birth_year) ? profile.birth_year + age.start : null);
  const yearEnd = statedYear !== null ? number(event.temporal?.year_end) ?? statedYear : number(estimate?.year_end)
    ?? (year !== null && age.start !== null ? year + age.end - age.start : year);
  const inferred = Boolean(estimate && (statedYear === null || age.estimated));
  const calendar = stated || (inferred && year !== null ? {start:Date.UTC(year,0,1),end:Date.UTC(yearEnd,11,31)} : null);
  const lifeStage = stages.indexOf(event.life_stage);
  const stage = lifeStage < 0 && !event.timing_conflict && !calendar && age.start === null && event.temporal_anchor === "present"
    ? stages.length : lifeStage;
  return {age, year, yearEnd, calendar, stage, index, inferred, approximateYear:statedYear === null && year !== null,
    dated:!event.timing_conflict && (age.start !== null || year !== null || Boolean(calendar))};
}

const chronological = (a,b) => ((a.inferred || b.inferred) && a.calendar && b.calendar
    && a.calendar.start <= b.calendar.end && b.calendar.start <= a.calendar.end && a.stage >= 0 && b.stage >= 0
    ? a.stage - b.stage : a.calendar && b.calendar ? a.calendar.start - b.calendar.start
  : a.year !== null && b.year !== null ? a.year - b.year
  : a.age.start !== null && b.age.start !== null ? a.age.start - b.age.start
  : a.stage >= 0 && b.stage >= 0 ? a.stage - b.stage
  : (a.stage < 0 && !a.dated) - (b.stage < 0 && !b.dated)) || a.index - b.index;

export function chronologicalEvents(events, profile = {}) {
  const ordered = events.map((event,index) => ({event,...memoryEventTiming(event,profile,index)}))
    .sort(chronological).map(item => item.event);
  const dependencies = new Map(events.map(event => [event.id,new Set()]));
  for (const event of events) for (const relation of event.relations || []) {
    if (event.timing_conflict || !dependencies.has(relation.event_id) || event.id === relation.event_id) continue;
    if (relation.kind === "before") dependencies.get(relation.event_id).add(event.id);
    if (relation.kind === "after") dependencies.get(event.id).add(relation.event_id);
  }
  const pending = new Set(events.map(event => event.id)), result = [];
  while (pending.size) {
    const next = ordered.find(event => pending.has(event.id) && ![...dependencies.get(event.id)].some(id => pending.has(id)));
    // Conflicting relations cannot establish an order; retain supported dates.
    if (!next) return ordered;
    pending.delete(next.id);result.push(next);
  }
  return result;
}

export function mapCityInView(cities, project, width, height) {
  let closest = null, distance = Infinity;
  for (const city of cities) for (const location of [city,...(city.nodes || [])]) {
    if (!coordinates(location)) continue;
    const point = project(location);
    if (!point || !Number.isFinite(point.x) || !Number.isFinite(point.y)
        || point.x < 0 || point.y < 0 || point.x > width || point.y > height) continue;
    const next = Math.hypot(point.x - width/2,point.y - height/2);
    if (next < distance) { closest = city.groupKey; distance = next; }
  }
  return closest;
}

// Only explicit event/place links supply locations. Shared testimony, a nearby
// city or a matching life stage does not establish an event's setting.
export function buildMapMemoryJourney(events, groups, profile = {}) {
  const nodes = [];
  let unmapped = 0;
  for (const [index, event] of chronologicalEvents(events,profile).entries()) {
    if (event.status && event.status !== "active") continue;
    const timing = memoryEventTiming(event,profile,index);
    const {age,year,calendar,stage} = timing;
    const links = Array.isArray(event.map_places) ? event.map_places : Array.isArray(event.places) ? event.places
      : event.canonical ? [] : event.place ? [{role:"setting", place:typeof event.place === "string" ? {place:event.place} : event.place}] : [];
    let located = false;
    const seen = new Set();
    for (const link of [...links].sort((a,b) => ["origin", "setting", "destination"].indexOf(a.role) - ["origin", "setting", "destination"].indexOf(b.role))) {
      if (link.status === "conflicted" || event.place_conflicts?.includes(link.role)) continue;
      const place = link.place;
      if (!place?.place) continue;
      let matches = groups.flatMap(group => group.members.filter(member =>
        place.hierarchy?.length ? placeHistoryKey(member) === placeHistoryKey(place) : label(member.place) === label(place.place))
        .map(member => ({group, member})));
      if (!matches.length) matches = groups.flatMap(group => group.members.filter(member => matchesEventPlace(place,member))
        .map(member => ({group,member})));
      if (matches.length !== 1) continue;
      const {group, member} = matches[0];
      const own = Object.hasOwn(member, "map_pin") ? member.map_pin : member;
      const city = coordinates(group.city) ? group.city : group.members.find(item => item.granularity === "city" && coordinates(item));
      const target = coordinates(own) ? own : city;
      if (!coordinates(target)) continue;
      const key = `${event.id}:${placeHistoryKey(member)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      const cityOnly = !coordinates(own) || member.granularity === "city"
        || (member.granularity !== "city" && target.latitude === city?.latitude && target.longitude === city?.longitude);
      nodes.push({key, event, ...timing, role:link.role, groupKey:group.key,
        location:{place:member.place,hierarchy:member.hierarchy,granularity:member.granularity,
          latitude:member.latitude,longitude:member.longitude,map_city:member.map_city,map_city_key:member.map_city_key,
          ...(Object.hasOwn(member,"map_pin") ? {map_pin:member.map_pin} : {})},
        city:group.city.place, cityLatitude:city?.latitude ?? target.latitude, cityLongitude:city?.longitude ?? target.longitude,
        place:member.place, latitude:target.latitude, longitude:target.longitude, cityOnly,
        summary:event.summary || event.title, uncertainty:event.uncertainty || "",
        dated:!event.timing_conflict && (age.start !== null || year !== null || Boolean(calendar))});
      located = true;
    }
    if (!located) unmapped++;
  }
  const legs = [];
  for (let i = 1; i < nodes.length; i++) {
    const from = nodes[i - 1], to = nodes[i];
    const different = from.latitude !== to.latitude || from.longitude !== to.longitude;
    const ordered = (from.dated && to.dated && ((from.calendar && to.calendar && from.calendar.end < to.calendar.start)
        || (from.age.start !== null && to.age.start !== null && from.age.end < to.age.start)))
      || (from.stage >= 0 && to.stage > from.stage && !(from.calendar && to.calendar)
        && !(from.age.start !== null && to.age.start !== null) && !from.event.timing_conflict && !to.event.timing_conflict)
      || (from.event.id === to.event.id && from.role === "origin" && to.role === "destination");
    const related = from.event.relations?.some(relation => relation.kind === "before" && relation.event_id === to.event.id)
      || to.event.relations?.some(relation => relation.kind === "after" && relation.event_id === from.event.id);
    if (different && (ordered || (related && !from.event.timing_conflict && !to.event.timing_conflict))) legs.push({from, to, stageTransition:from.stage !== to.stage});
  }
  return {nodes, legs, unmapped};
}

export function cityEventCards(nodes) {
  const cities = new Map();
  for (const node of nodes) {
    if (!cities.has(node.groupKey)) cities.set(node.groupKey, {key:`city:${node.groupKey}`, groupKey:node.groupKey,
      city:node.city, latitude:node.cityLatitude, longitude:node.cityLongitude, nodes:[]});
    const members = cities.get(node.groupKey).nodes;
    if (!members.some(member => member.event.id === node.event.id)) members.push(node);
  }
  return [...cities.values()].map(city => {
    const ages = city.nodes.map(node => node.age).filter(age => age.start !== null);
    return {...city, age:{start:ages.length ? Math.min(...ages.map(age => age.start)) : null,
      end:ages.length ? Math.max(...ages.map(age => age.end)) : null, approximate:ages.some(age => age.approximate)},
      count:new Set(city.nodes.map(node => node.event.id)).size};
  });
}

export function memoryEventTimingMarkup(card, t) {
  const node = card.nodes?.[0] || card;
  const temporal = node.event.temporal;
  const years = `${node.year}${node.yearEnd > node.year ? `–${node.yearEnd}` : ""}`;
  const year = node.event.timing_conflict ? t("mapEventYearUnknown")
    : node.year !== null ? node.approximateYear ? t("mapEventYearApproximate",{year:years}) : years
    : temporal?.precision !== "unknown" && temporal?.expression && temporal.precision !== "age"
      ? temporal.expression : t("mapEventYearUnknown");
  const score = node.inferred ? node.event.temporal_estimate?.confidence : node.event.yearConfidenceScore;
  const confidence = node.event.timing_conflict ? 0 : Number.isFinite(score) ? Math.round(Math.max(0,Math.min(1,score))*100) : 0;
  return `<span class="map-memory-date">${escapeHtml(year)} · ${escapeHtml(eventAgeLabel(node.age,t))}</span><span class="map-memory-confidence"${node.inferred ? ` title="${escapeHtml(node.event.temporal_estimate.rationale)}"` : ""}>${escapeHtml(t(node.inferred ? "mapEventEstimatedConfidence" : "mapEventDateConfidence",{percent:confidence}))}</span>`;
}

export function memoryEventAvatars(card, {t, lifeStageText, profile = {}, readiness = {}}) {
  const related = new Set((card.nodes || [card]).map(node => node.event.life_stage));
  const selected = stages.filter(stage => related.has(stage));
  if ([...related].some(stage => !stages.includes(stage))) selected.push("unplaced");
  const artwork = profile.avatar_style === "female" ? "female" : "male";
  return `<span class="map-memory-avatars">${selected.map(stage => {
    if (stage === "unplaced") return `<span class="map-memory-avatar is-unknown" role="img" aria-label="${escapeHtml(t("unplacedStage"))}" title="${escapeHtml(t("unplacedStage"))}"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 22v-3a8 8 0 0 1 16 0v3z"/></svg></span>`;
    const context = readiness[stage] || {};
    const percent = Math.max(0,Math.min(100,Number(context.percent) || 0));
    const color = ["red","amber","green"].includes(context.color) ? context.color : "red";
    const description = t("contextReadiness",{stage:lifeStageText(stage,"label"),percent,words:context.word_equivalents || 0});
    return `<span class="map-memory-avatar readiness-${color}" role="img" aria-label="${escapeHtml(description)}" title="${escapeHtml(description)}" style="--readiness:${percent}%"><img src="/static/timeline_avatar_${avatars[stages.indexOf(stage)]}_${artwork}.png" alt="" /><small>${percent}%</small></span>`;
  }).join("")}</span>`;
}

export function memoryEventCardMarkup(card, {t, lifeStageText, active = false, profile, readiness}) {
  const city = Boolean(card.nodes);
  const stages = [...new Set((city ? card.nodes : [card]).map(node => node.event.life_stage).filter(stage => stage && stage !== "unplaced"))];
  const stage = stages.map(stage => lifeStageText(stage, "label")).join(" · ");
  const age = eventAgeLabel(card.age, t);
  const title = city ? card.city : card.place;
  const summary = city ? card.nodes[0].summary : card.summary;
  const count = city ? t(card.count === 1 ? "mapEventCountOne" : "mapEventCount", {count:card.count}) : "";
  return `<button type="button" class="map-memory-card${city ? " is-city" : ""}${active ? " is-active" : ""}" data-map-memory="${escapeHtml(card.key)}" aria-label="${escapeHtml([title,age,count,summary].filter(Boolean).join(" · "))}" aria-expanded="${active}"><span class="map-memory-meta">${memoryEventAvatars(card,{t,lifeStageText,profile,readiness})}${count ? `<span class="map-memory-count">${escapeHtml(count)}</span>` : ""}</span><strong>${escapeHtml(title)}</strong>${memoryEventTimingMarkup(card,t)}<span class="map-memory-summary">${escapeHtml(summary)}</span>${stage ? `<span class="map-memory-stage">${escapeHtml(stage)}</span>` : ""}<span class="map-memory-hint">${escapeHtml(t(city ? active ? "mapEventCollapse" : "mapEventExpand" : card.cityOnly ? "mapEventCityLocation" : "mapEventOpen"))}</span></button>`;
}

// Move colliding cards while preserving a stem to the true map position.
export function layoutMemoryCards(points, width, height, cardWidth = 194, cardHeight = 126, reserve = 88, topInset = 54) {
  const boxes = [];
  for (const point of points) {
    if (!Number.isFinite(point.x) || !Number.isFinite(point.y) || point.x < 0 || point.y < 0 || point.x > width || point.y > height) continue;
    let box;
    for (let row = 0; row < Math.ceil(height / (cardHeight + 10)) && !box; row++) {
      for (const side of [0, -1, 1, -2, 2]) {
        const left = Math.max(8, Math.min(width - cardWidth - 8, point.x - cardWidth / 2 + side * (cardWidth + 10)));
        const top = Math.max(topInset, Math.min(height - cardHeight - reserve, point.y - cardHeight - 18 + row * (cardHeight + 10)));
        if (width < cardWidth + 16 || height < cardHeight + reserve + topInset) break;
        if (boxes.some(other => !other.overflow && left < other.left + cardWidth + 8 && left + cardWidth + 8 > other.left
            && top < other.top + cardHeight + 8 && top + cardHeight + 8 > other.top)) continue;
        box = {...point, left, top};
        break;
      }
    }
    boxes.push(box || {...point, overflow:true});
  }
  return reserve === 88 && boxes.some(box => box.overflow)
    ? layoutMemoryCards(points,width,height,cardWidth,cardHeight,reserve + cardHeight + 12,topInset) : boxes;
}
