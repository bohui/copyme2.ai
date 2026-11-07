import {placeHistoryKey} from './places.mjs';
import {applyCurrentActiveLocation} from './active-location.mjs';

// An authorized full snapshot is distinct from an empty/failed B delta.
// This function changes derived place state only; it never saves preferences,
// moves navigation, starts recording, or marks an interview question delivered.
export function applyDerivedWorkspace(state, update, atlasScope = null) {
  if (!update || update.authoritative !== true || update.project_id !== state.project?.id
      || !Array.isArray(update.places) || !Number.isSafeInteger(update.source_revision)
      || !Number.isSafeInteger(update.policy_epoch)) return false;
  const prior = state.derivedWorkspace;
  if (prior?.project_id === update.project_id
      && (update.policy_epoch < prior.policy_epoch
        || (update.policy_epoch === prior.policy_epoch && update.source_revision < prior.source_revision))) return false;
  const focus = update.workspace_focus;
  const focusCurrent = !state.workspaceFocus || (prior && prior.policy_epoch !== update.policy_epoch)
    || (focus ? focus.source_sequence >= state.workspaceFocus.source_sequence : update.source_revision > state.workspaceFocus.source_sequence);
  const focusChanged = Object.hasOwn(update,'workspace_focus') && focusCurrent
    && JSON.stringify(state.workspaceFocus || null) !== JSON.stringify(focus);
  if (focusChanged) state.workspaceFocus = update.workspace_focus;
  const locationChanged = Object.hasOwn(update,'current_active_location') && applyCurrentActiveLocation(
    state, update.current_active_location, {sourceRevision:update.source_revision,
      reset:Boolean(prior && prior.policy_epoch !== update.policy_epoch)});
  const previousPlaces = state.project.profile?.memory_places || [];
  const preserve = prior ? prior.policy_epoch === update.policy_epoch : update.policy_epoch === 1;
  const previous = new Map(previousPlaces.map(p => [placeHistoryKey(p),p]));
  const decorations = ['pictures','map_city','map_city_key','map_pin','life_stage','life_stages','period'];
  const places = update.places.filter(p => p?.status === 'active' && p.place && Array.isArray(p.hierarchy)).map(p => {
    const saved = preserve && previous.get(placeHistoryKey(p));
    return Object.fromEntries(Object.entries({...saved,...p}).filter(([key]) => Object.hasOwn(p,key)
      || decorations.includes(key) || key.startsWith('photo_search_') || key === 'photo_next_cursor'));
  });
  const streamedLocation = atlasScope && update.current_active_location?.place
    && state.currentActiveLocation === update.current_active_location;
  const previousAtlasScope = prior?.project_id === update.project_id && prior.policy_epoch === update.policy_epoch
    ? prior.atlasLocationScope : null;
  const atlasLocationScope = streamedLocation ? atlasScope : previousAtlasScope;
  state.derivedWorkspace = {project_id:update.project_id, policy_epoch:update.policy_epoch, source_revision:update.source_revision,
    ...(update.map_source ? {map_source:update.map_source} : {}),
    ...(places.length && atlasLocationScope ? {atlasLocationScope} : {})};
  if (!places.length) {
    state.placeWorkspaceMap = null;
  }
  if (JSON.stringify(previousPlaces) === JSON.stringify(places)
      && (!state.placeJourney || places.some(p => placeHistoryKey(p) === placeHistoryKey(state.placeJourney)))) return focusChanged || locationChanged;
  state.project = {...state.project,profile:{...state.project.profile,memory_places:places}};
  const currentKey = state.placeJourney && placeHistoryKey(state.placeJourney);
  const retained = currentKey && places.find(p => placeHistoryKey(p) === currentKey);
  if (retained) state.placeJourney = retained;
  else if (places.length) {
    state.placeJourney = places.at(-1);
    state.selectedPlace = placeHistoryKey(state.placeJourney);
  } else {
    state.placeJourney = null;
    state.selectedPlace = null;
  }
  return true;
}
