// Geographic identity is independent of the memories attached to it.
const normalize = value => String(value || '').normalize('NFKC').trim().toLocaleLowerCase().replace(/\s+/g, ' ');
const geographicLabel = value => normalize(value).replace(/([\u3400-\u9fff])[市省]$/, '$1');
const genericPlaces = new Set([
  '家属院', '市区', '城区', '老家', '故乡', '家乡', '村里', '镇上', '河边', '山里',
  '学校', '医院', '车站', '小区', '附近', '这里', '那里',
  'home', 'hometown', 'my hometown', 'city', 'the city', 'town', 'suburb', 'village',
  'the old river town', 'school compound', 'residential compound', 'family compound',
]);
const detailedPlace = /(?:医院|学校|大学|学院|中学|小学|车站|火车站|家属院|小区|大厦|大楼|街|路|巷)(?:\d+号)?$|\b(?:hospital|school|university|college|station|street|road|lane|avenue|building|compound)\b(?:\s+\d+)?$/i;
const isCoarseLabel = label => !genericPlaces.has(normalize(label)) && !detailedPlace.test(label);
export const isCoarsePlace = place => Boolean(place?.place
  && ['country', 'region', 'city', 'suburb'].includes(place.granularity)
  && isCoarseLabel(place.place) && (place.hierarchy || []).slice(1).every(isCoarseLabel));
const LIFE_STAGE_ORDER = new Map([
  ['baby', 0],
  ['childhood', 1],
  ['adolescence', 2],
  ['young_adulthood', 3],
  ['midlife', 4],
  ['later_life', 5],
]);
const path = place => {
  const labels = (place.hierarchy || []).filter(label => !['earth', '地球'].includes(normalize(label))).map(geographicLabel);
  if (labels.at(-1) !== geographicLabel(place.place)) labels.push(geographicLabel(place.place));
  return labels;
};
export const placeHistoryKey = place => JSON.stringify(path(place));
export const matchesPlaceStage = (place, stage) => stage === 'all' || (place.life_stages || [place.life_stage]).includes(stage);
const coordinates = place => Number.isFinite(place?.latitude) && Number.isFinite(place?.longitude);

const chronologyStageFromRecord = place => place.research?.basis === 'birth_decade' ? 0 : Math.min(
  ...(Array.from(new Set([...(place.life_stages || []), place.life_stage]))
    .map(stage => LIFE_STAGE_ORDER.get(stage))
    .filter(Number.isFinite)),
  Infinity,
);
const profilePlaceParts = profile => {
  const raw = normalize(profile?.birth_place);
  if (!raw) return {birth: '', current: ''};
  return {birth: raw, current: normalize(profile?.current_place)};
};
const placeMatchesProfileValue = (place, value) => {
  const source = normalize(value);
  if (!source) return false;
  return [place.place, geographicLabel(place.place)]
    .map(normalize)
    .filter(label => label.length > 1)
    .some(label => source.includes(label));
};
const profileChronologyStage = (place, profile) => {
  const parts = profilePlaceParts(profile);
  if (placeMatchesProfileValue(place, parts.birth)) return 0;
  if (placeMatchesProfileValue(place, profile?.childhood_place)) return 1;
  if (placeMatchesProfileValue(place, parts.current)) return LIFE_STAGE_ORDER.size;
  return null;
};
const chronologyStage = (place, profile) => {
  const profileStage = profileChronologyStage(place, profile);
  return profileStage === null ? chronologyStageFromRecord(place) : profileStage;
};
const sourceSequence = place => {
  const value = Number(place?.source_sequence);
  return Number.isSafeInteger(value) && value >= 0 ? value : Infinity;
};

// Place history is a life journey, not a replay of chat insertion order. Use
// explicit stages or profile chronology first. A source sequence only breaks
// ties within the same stage (or keeps undated entries stable).
export function sortPlacesChronologically(places, profile = null) {
  return places
    .map((place, index) => ({place, index}))
    .sort((left, right) => {
      const stageDelta = chronologyStage(left.place, profile) - chronologyStage(right.place, profile);
      if (stageDelta) return stageDelta;
      const sequenceDelta = sourceSequence(left.place) - sourceSequence(right.place);
      if (sequenceDelta) return sequenceDelta;
      return left.index - right.index;
    })
    .map(({place}) => place);
}

export function mergePlaces(entries, profile = null, messages = []) {
  const merged = new Map();
  for (const entry of entries) {
    if (!isCoarsePlace(entry)) continue;
    const key = placeHistoryKey(entry);
    const previous = merged.get(key) || {};
    const pictures = new Map([...(previous.pictures || []), ...(entry.pictures || [])].map(picture => [picture.asset_id || picture.id || picture.source_url || JSON.stringify(picture), picture]));
    const life_stage = entry.life_stage || previous.life_stage || null;
    const life_stages = [...new Set([...(previous.life_stages || []), ...(entry.life_stages || []), life_stage].filter(Boolean))];
    const item = {...previous, ...entry, life_stage, life_stages, pictures: [...pictures.values()]};
    if (!coordinates(entry) && coordinates(previous)) Object.assign(item, {latitude:previous.latitude, longitude:previous.longitude});
    merged.set(key, item);
  }
  const places = sortPlacesChronologically([...merged.values()], profile);
  for (const item of places) {
    const labels = path(item);
    const parent = places.filter(other => {
      const ancestor = path(other);
      return ancestor.length < labels.length && ancestor.every((label, index) => labels[index] === label);
    }).sort((a,b) => path(b).length - path(a).length)[0];
    item.parent_place_key = parent ? placeHistoryKey(parent) : null;
  }
  return places;
}
export function mapTarget(place, places) {
  if (coordinates(place)) return place;
  const labels = path(place);
  return places.filter(other => {
    const ancestor = path(other);
    return coordinates(other) && ancestor.length <= labels.length && ancestor.every((label,index) => labels[index] === label);
  }).sort((a,b) => path(b).length - path(a).length)[0] || null;
}

// Group the map presentation, while keeping every source place and its photos.
const groupLabel = value => {
  let label = normalize(value);
  label = ({chengde: '承德', china: '中国', hebei: '河北'})[label] || label;
  return label.replace(/[市省]$/, '');
};
const groupPath = place => path(place).map(groupLabel);
export const cityGroupKey = place => JSON.stringify(groupPath(place));

// Broad places still own their saved history, but a known descendant already
// supplies their geographic context in the map navigation.
export function specificPlaceChoices(places) {
  return places.filter(place => {
    if (!['country', 'region'].includes(place.granularity)) return true;
    const ancestor = groupPath(place);
    return !places.some(other => {
      const descendant = groupPath(other);
      return ancestor.length < descendant.length
        && ancestor.every((label, index) => descendant[index] === label);
    });
  });
}

export function groupPlaces(places) {
  const cities = places.filter(place => place.granularity === 'city');
  const groups = new Map();
  for (const place of places) {
    const labels = groupPath(place);
    const ancestors = cities.filter(city => {
      const ancestor = groupPath(city);
      return ancestor.length <= labels.length && ancestor.every((label, index) => labels[index] === label);
    }).sort((left, right) => groupPath(left).length - groupPath(right).length);
    const city = place.map_city || ancestors[0] || place;
    const key = place.map_city_key || cityGroupKey(city);
    if (!groups.has(key)) groups.set(key, {key, city, members: []});
    const group = groups.get(key);
    // Retain saved coordinates while using the requested display language.
    const savedCity = [...ancestors,...cities].find(item =>
      (item.map_city_key || cityGroupKey(item.map_city || item)) === key);
    if (savedCity) {
      group.city = {...savedCity,...(savedCity.map_city || city)};
      group.canonicalCity = savedCity;
    }
    group.members.push(place);
  }
  return [...groups.values()];
}

export function groupMapPins(group) {
  const pins = group.members.flatMap(place => {
    const own = Object.hasOwn(place, 'map_pin') ? place.map_pin : place;
    if (!coordinates(own)) return [];
    const isChild = cityGroupKey(place) !== cityGroupKey(group.canonicalCity || group.city);
    if (isChild && own.latitude === group.city.latitude && own.longitude === group.city.longitude) return [];
    return [{place: place.place, key: placeHistoryKey(place), latitude: own.latitude,
      longitude: own.longitude, granularity: place.granularity, isChild}];
  });
  return pins.some(pin => pin.isChild) ? pins.filter(pin => pin.isChild) : pins;
}

export function groupMapFrame(group, fallback) {
  const pins = groupMapPins(group);
  if (!pins.length) return fallback ? {...fallback, pins: []} : null;
  const latitudes = pins.map(pin => pin.latitude);
  const longitudes = pins.map(pin => pin.longitude);
  // Unwrap longitudes around the first pin for cities near the date line.
  const origin = longitudes[0];
  const unwrapped = longitudes.map(value => origin + ((value - origin + 540) % 360 - 180));
  const latitude = (Math.min(...latitudes) + Math.max(...latitudes)) / 2;
  const longitude = ((Math.min(...unwrapped) + Math.max(...unwrapped)) / 2 + 540) % 360 - 180;
  const span = Math.max((Math.max(...latitudes) - Math.min(...latitudes)) * 111_320,
    (Math.max(...unwrapped) - Math.min(...unwrapped)) * 111_320 * Math.cos(latitude * Math.PI / 180));
  return {place: group.city.place, latitude, longitude, pins,
    height: Math.max(pins.some(pin => pin.isChild) ? 1800 : 24_000, span * 3)};
}
