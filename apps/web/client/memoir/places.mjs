// Geographic identity is independent of the memories attached to it.
const normalize = value => String(value || '').normalize('NFKC').trim().toLocaleLowerCase().replace(/\s+/g, ' ');
const path = place => {
  const labels = (place.hierarchy || []).filter(label => normalize(label) !== 'earth').map(normalize);
  if (labels.at(-1) !== normalize(place.place)) labels.push(normalize(place.place));
  return labels;
};
export const placeHistoryKey = place => JSON.stringify(path(place));
export const matchesPlaceStage = (place, stage) => stage === 'all' || (place.life_stages || [place.life_stage]).includes(stage);
const coordinates = place => Number.isFinite(place?.latitude) && Number.isFinite(place?.longitude);
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
  const places = [...merged.values()];
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
