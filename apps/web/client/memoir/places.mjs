// Geographic identity is independent of the memories attached to it.
const normalize = value => String(value || '').normalize('NFKC').trim().toLocaleLowerCase().replace(/\s+/g, ' ');
const LIFE_STAGE_ORDER = new Map([
  ['baby', 0],
  ['toddler', 1],
  ['childhood', 2],
  ['adolescence', 3],
  ['young_adulthood', 4],
  ['midlife', 5],
  ['later_life', 6],
]);
const path = place => {
  const labels = (place.hierarchy || []).filter(label => normalize(label) !== 'earth').map(normalize);
  if (labels.at(-1) !== normalize(place.place)) labels.push(normalize(place.place));
  return labels;
};
export const placeHistoryKey = place => JSON.stringify(path(place));
export const matchesPlaceStage = (place, stage) => stage === 'all' || (place.life_stages || [place.life_stage]).includes(stage);
const coordinates = place => Number.isFinite(place?.latitude) && Number.isFinite(place?.longitude);

const chronologyStage = place => Math.min(
  ...(Array.from(new Set([...(place.life_stages || []), place.life_stage]))
    .map(stage => LIFE_STAGE_ORDER.get(stage))
    .filter(Number.isFinite)),
  Infinity,
);
const sourceSequence = place => {
  const value = Number(place?.source_sequence);
  return Number.isSafeInteger(value) && value >= 0 ? value : Infinity;
};

// Place history is a life journey, not a replay of chat insertion order. When
// the storyteller gave us a life stage, use that chronology first. A source
// sequence only breaks ties within the same stage (or keeps undated entries
// stable); it must never move a childhood place after a later-life place.
export function sortPlacesChronologically(places) {
  return places
    .map((place, index) => ({place, index}))
    .sort((left, right) => {
      const stageDelta = chronologyStage(left.place) - chronologyStage(right.place);
      if (stageDelta) return stageDelta;
      const sequenceDelta = sourceSequence(left.place) - sourceSequence(right.place);
      if (sequenceDelta) return sequenceDelta;
      return left.index - right.index;
    })
    .map(({place}) => place);
}

export function mergePlaces(entries) {
  const merged = new Map();
  for (const entry of entries) {
    const key = placeHistoryKey(entry);
    const previous = merged.get(key) || {};
    const pictures = new Map([...(previous.pictures || []), ...(entry.pictures || [])].map(picture => [picture.asset_id || picture.id || picture.source_url || JSON.stringify(picture), picture]));
    const life_stages = [...new Set([...(previous.life_stages || []), ...(entry.life_stages || []), entry.life_stage].filter(Boolean))];
    const item = {...previous, ...entry, life_stage: entry.life_stage || previous.life_stage || null, life_stages, pictures: [...pictures.values()]};
    if (!coordinates(entry) && coordinates(previous)) Object.assign(item, {latitude:previous.latitude, longitude:previous.longitude});
    merged.set(key, item);
  }
  const places = sortPlacesChronologically([...merged.values()]);
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
    return coordinates(other) && ancestor.length < labels.length && ancestor.every((label,index) => labels[index] === label);
  }).sort((a,b) => path(b).length - path(a).length)[0] || null;
}
