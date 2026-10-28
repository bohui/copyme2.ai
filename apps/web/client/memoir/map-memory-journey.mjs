import { escapeHtml } from "./dom.mjs";
import { placeHistoryKey } from "./places.mjs";

const stages = ["baby", "childhood", "adolescence", "young_adulthood", "midlife", "later_life"];
const coordinates = place => Number.isFinite(place?.latitude) && Math.abs(place.latitude) <= 90
  && Number.isFinite(place?.longitude) && Math.abs(place.longitude) <= 180;
const label = value => String(value || "").normalize("NFKC").trim().toLowerCase().replace(/([\u3400-\u9fff])[市省]$/, "$1");
const number = value => Number.isInteger(value) && value >= 0 ? value : null;
const ageUnits = ["zero","one","two","three","four","five","six","seven","eight","nine","ten","eleven","twelve","thirteen","fourteen","fifteen","sixteen","seventeen","eighteen","nineteen"];
const ageTens = ["twenty","thirty","forty","fifty","sixty","seventy","eighty","ninety"];
const ageWord = `(?:${[...ageUnits,...ageTens].join("|")})(?:[- ](?:${ageUnits.slice(1,10).join("|")}))?`;
const wordAge = value => value.toLowerCase().split(/[- ]/).reduce((sum,word) =>
  sum + (ageUnits.includes(word) ? ageUnits.indexOf(word) : (ageTens.indexOf(word) + 2) * 10),0);

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
    return {start:null, end:null, expression};
  }
  const birth = number(profile.birth_year);
  const start = number(timing.year_start) ?? Number(expression.match(/\b([12]\d{3})\b/)?.[1] || 0);
  const end = number(timing.year_end) ?? start;
  if (birth && start >= birth && end >= start && !event.timing_conflict) {
    return {start:start - birth, end:end - birth, approximate:true};
  }
  return {start:null, end:null};
}

export function eventAgeLabel(age, t) {
  if (age.expression) return age.expression;
  if (age.start === null) return t("mapEventAgeUnknown");
  const value = age.start === age.end ? String(age.start) : `${age.start}–${age.end}`;
  return t(age.approximate ? "mapEventAgeApproximate" : "mapEventAge", {age:value});
}

// Only explicit event/place links supply locations. Shared testimony, a nearby
// city or a matching life stage does not establish an event's setting.
export function buildMapMemoryJourney(events, groups, profile = {}) {
  const nodes = [];
  let unmapped = 0;
  for (const [index, event] of events.entries()) {
    if (event.status && event.status !== "active") continue;
    const age = eventAge(event, profile);
    const stage = stages.indexOf(event.life_stage);
    const year = number(event.temporal?.year_start) ?? (age.start !== null && number(profile.birth_year)
      ? profile.birth_year + age.start : null);
    const links = Array.isArray(event.map_places) ? event.map_places : Array.isArray(event.places) ? event.places
      : event.canonical ? [] : event.place ? [{role:"setting", place:typeof event.place === "string" ? {place:event.place} : event.place}] : [];
    let located = false;
    const seen = new Set();
    for (const link of [...links].sort((a,b) => ["origin", "setting", "destination"].indexOf(a.role) - ["origin", "setting", "destination"].indexOf(b.role))) {
      if (link.status === "conflicted" || event.place_conflicts?.includes(link.role)) continue;
      const place = link.place;
      if (!place?.place) continue;
      const matches = groups.flatMap(group => group.members.filter(member =>
        place.hierarchy?.length ? placeHistoryKey(member) === placeHistoryKey(place) : label(member.place) === label(place.place))
        .map(member => ({group, member})));
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
      nodes.push({key, event, age, year, index, stage, role:link.role, groupKey:group.key,
        city:group.city.place, cityLatitude:city?.latitude ?? target.latitude, cityLongitude:city?.longitude ?? target.longitude,
        place:member.place, latitude:target.latitude, longitude:target.longitude, cityOnly,
        summary:event.summary || event.title, uncertainty:event.uncertainty || "",
        dated:!event.timing_conflict && (age.start !== null || year !== null)});
      located = true;
    }
    if (!located) unmapped++;
  }
  nodes.sort((a,b) => (a.year !== null && b.year !== null ? a.year - b.year
    : a.age.start !== null && b.age.start !== null ? a.age.start - b.age.start
      : a.stage >= 0 && b.stage >= 0 ? a.stage - b.stage : 0) || a.index - b.index);
  const legs = [];
  for (let i = 1; i < nodes.length; i++) {
    const from = nodes[i - 1], to = nodes[i];
    const different = from.latitude !== to.latitude || from.longitude !== to.longitude;
    const ordered = (from.dated && to.dated && ((from.year !== null && to.year !== null && from.year < to.year)
        || (from.age.start !== null && to.age.start !== null && from.age.start < to.age.start)))
      || (from.stage >= 0 && to.stage > from.stage && !from.event.timing_conflict && !to.event.timing_conflict)
      || (from.event.id === to.event.id && from.role === "origin" && to.role === "destination");
    if (different && ordered) legs.push({from, to, stageTransition:from.stage !== to.stage});
  }
  return {nodes, legs, unmapped};
}

export function cityEventCards(nodes) {
  const cities = new Map();
  for (const node of nodes) {
    if (!cities.has(node.groupKey)) cities.set(node.groupKey, {key:`city:${node.groupKey}`, groupKey:node.groupKey,
      city:node.city, latitude:node.cityLatitude, longitude:node.cityLongitude, nodes:[]});
    cities.get(node.groupKey).nodes.push(node);
  }
  return [...cities.values()].map(city => {
    const ages = city.nodes.map(node => node.age).filter(age => age.start !== null);
    return {...city, age:{start:ages.length ? Math.min(...ages.map(age => age.start)) : null,
      end:ages.length ? Math.max(...ages.map(age => age.end)) : null, approximate:ages.some(age => age.approximate)},
      count:new Set(city.nodes.map(node => node.event.id)).size};
  });
}

export function memoryEventCardMarkup(card, {t, lifeStageText, active = false}) {
  const city = Boolean(card.nodes);
  const stages = [...new Set((city ? card.nodes : [card]).map(node => node.event.life_stage).filter(stage => stage && stage !== "unplaced"))];
  const stage = stages.map(stage => lifeStageText(stage, "label")).join(" · ");
  const age = eventAgeLabel(card.age, t);
  const title = city ? card.city : card.place;
  const summary = city ? card.nodes[0].summary : card.summary;
  const count = city ? t(card.count === 1 ? "mapEventCountOne" : "mapEventCount", {count:card.count}) : "";
  return `<button type="button" class="map-memory-card${city ? " is-city" : ""}${active ? " is-active" : ""}" data-map-memory="${escapeHtml(card.key)}" aria-label="${escapeHtml([title,age,count,summary].filter(Boolean).join(" · "))}" aria-expanded="${active}"><span class="map-memory-meta"><span class="map-memory-age">${escapeHtml(age)}</span>${count ? `<span class="map-memory-count">${escapeHtml(count)}</span>` : ""}</span><strong>${escapeHtml(title)}</strong><span class="map-memory-summary">${escapeHtml(summary)}</span>${stage ? `<span class="map-memory-stage">${escapeHtml(stage)}</span>` : ""}<span class="map-memory-hint">${escapeHtml(t(city ? "mapEventZoomIn" : card.cityOnly ? "mapEventCityLocation" : "mapEventOpen"))}</span></button>`;
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
