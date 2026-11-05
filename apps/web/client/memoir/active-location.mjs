import {placeHistoryKey} from './places.mjs';

export function applyCurrentActiveLocation(state, location, {reset = false, sourceRevision} = {}) {
  const previous = state.currentActiveLocation;
  if (!reset && previous && (location ? location.source_sequence < previous.source_sequence
      : sourceRevision <= previous.source_sequence)) return false;
  const changed = (previous ? placeHistoryKey(previous) : null) !== (location ? placeHistoryKey(location) : null);
  state.currentActiveLocation = location;
  if (changed && previous !== undefined) state.activeLocationChange = (state.activeLocationChange || 0) + 1;
  return changed;
}
