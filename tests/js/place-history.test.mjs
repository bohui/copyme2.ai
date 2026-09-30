import test from 'node:test';
import assert from 'node:assert/strict';
import {mergePlaces, placeHistoryKey, mapTarget} from '../../apps/web/client/memoir/places.mjs';
const city = {place:'承德', hierarchy:['Earth','中国','河北','承德'], granularity:'city', latitude:40.97, longitude:117.93};
const suburb = {place:'大石庙镇', hierarchy:[...city.hierarchy,'大石庙镇'], granularity:'suburb'};
test('merges stage duplicates, retains pictures and all stages', () => {
 const places = mergePlaces([{...suburb, life_stage:'childhood', pictures:[{asset_id:'a'}]}, {...suburb}, {...suburb, life_stage:'adolescence', pictures:[{asset_id:'b'}]}]);
 assert.equal(places.length, 1);
 assert.deepEqual(places[0].life_stages, ['childhood','adolescence']);
 assert.equal(places[0].pictures.length, 2);
 assert.equal(placeHistoryKey(suburb), placeHistoryKey({...suburb,life_stage:'childhood'}));
});
test('keeps suburb with parent reference and uses parent only as map target', () => {
 const places = mergePlaces([city, suburb]);
 assert.equal(places.length,2);
 assert.equal(places[1].parent_place_key,placeHistoryKey(city));
 assert.equal(mapTarget(places[1], places).place,'承德');
 assert.equal(places[1].place,'大石庙镇');
 assert.equal(mapTarget({...suburb,latitude:40.921285,longitude:117.961817}, places).place,'大石庙镇');
});
test('does not merge same names in different regions', () => {
 assert.equal(mergePlaces([city,{...city,hierarchy:['Earth','other','承德']}]).length,2);
});

test('normalizes labels and handles hierarchy with or without leaf', () => {
 assert.equal(placeHistoryKey(suburb),placeHistoryKey({...suburb,hierarchy:city.hierarchy}));
 assert.equal(placeHistoryKey(city),placeHistoryKey({...city,place:' 承德 '}));
});
test('preserves known coordinates when later mention omits them', () => {
 const result = mergePlaces([city,{...city,latitude:null,longitude:null}]);
 assert.equal(result[0].latitude,city.latitude);
});
test('orders places by life-stage chronology instead of mention order', () => {
 const places = mergePlaces([
  {...city, place:'Sydney', hierarchy:['Earth','Australia','Sydney'], life_stage:'young_adulthood', source_sequence:1},
  {...city, place:'Chengde', hierarchy:['Earth','China','Hebei','Chengde'], life_stage:'childhood', source_sequence:2},
  {...city, place:'Shanghai', hierarchy:['Earth','China','Shanghai'], life_stage:'adolescence', source_sequence:3},
 ]);
 assert.deepEqual(places.map(place => place.place), ['Chengde','Shanghai','Sydney']);
});

test('uses source sequence only for places without a distinct stage', () => {
 const places = mergePlaces([
  {...city, place:'Later place', hierarchy:['Earth','Australia','Later place'], life_stage:'midlife', source_sequence:1},
  {...city, place:'Early place', hierarchy:['Earth','Australia','Early place'], life_stage:'childhood', source_sequence:2},
  {...city, place:'Unstaged place', hierarchy:['Earth','Australia','Unstaged place'], source_sequence:3},
 ]);
 assert.deepEqual(places.map(place => place.place), ['Early place','Later place','Unstaged place']);
});

test('renders the place history navigation in chronological order', async () => {
 const fs = await import('node:fs');
 const vm = await import('node:vm');
 const source = fs.readFileSync(new URL('../../apps/web/client/memoir/client.js', import.meta.url), 'utf8');
 const context = vm.createContext({
  escapeHtml: String, translate: key => key, lifeStageText: stage => stage, placeHistoryKey,
 });
 vm.runInContext(source.match(/function placeHistoryChoices\([^]*?\n\}/)[0], context);
 const places = mergePlaces([
  {...city, place:'Sydney', hierarchy:['Earth','Australia','Sydney'], life_stage:'young_adulthood'},
  {...city, place:'Chengde', hierarchy:['Earth','China','Hebei','Chengde'], life_stage:'childhood'},
 ]);
 const markup = context.placeHistoryChoices(places, places.at(-1));
 assert.ok(markup.indexOf('>Chengde<') < markup.indexOf('>Sydney<'));
});

test('renderer keeps detailed title and labels parent map coordinates', async () => {
 const fs = await import('node:fs');
 const vm = await import('node:vm');
 const source=fs.readFileSync(new URL('../../apps/web/client/memoir/client.js',import.meta.url),'utf8');
 const context=vm.createContext({mapTarget, mergePlaces, placeHistoryKey, resolvedPlaceTargets:new Map(), profile:()=>({memory_places:[city,suburb]}), escapeHtml:String, translate:k=>k, translateWith:(k,v)=>`${k} ${v.place || ''}`, currentUiLocale:()=> 'en-AU'});
 for (const name of ['placeMapTarget','placeMapUrl','placeJourneyMarkup']) vm.runInContext(source.match(new RegExp(`function ${name}\\([^]*?\\n\\}`))[0],context);
 const markup=context.placeJourneyMarkup(suburb);
 assert.match(markup,/<h2>大石庙镇<\/h2>/);
 assert.match(markup,/data-cesium-place="承德"/);
 assert.match(markup,/data-cesium-latitude="40.97"/);
 assert.equal(context.placeMapUrl({latitude: 40.97, longitude: 117.93}), 'https://www.google.com/maps/search/?api=1&query=40.97%2C117.93');
 assert.doesNotMatch(markup,/openstreetmap/);
 assert.match(markup,/parentMap 承德/);
 assert.doesNotMatch(markup,/placeNote/);
});

test('does not render a place card when no map target is available', async () => {
 const fs = await import('node:fs');
 const vm = await import('node:vm');
 const source = fs.readFileSync(new URL('../../apps/web/client/memoir/client.js', import.meta.url), 'utf8');
 const context = vm.createContext({
  mapTarget, mergePlaces, placeHistoryKey, resolvedPlaceTargets: new Map(),
  profile: () => ({memory_places: []}), escapeHtml: String,
  translate: key => key, translateWith: (key, values) => `${key} ${values.place || ''}`,
  currentUiLocale: () => 'en-AU',
 });
 for (const name of ['placeMapTarget', 'placeJourneyMarkup']) {
  vm.runInContext(source.match(new RegExp(`function ${name}\\([^]*?\\n\\}`))[0], context);
 }
 assert.equal(context.placeJourneyMarkup({
  place: 'Somewhere unknown', hierarchy: ['Earth', 'Somewhere unknown'], granularity: 'city',
 }), '');
});

test('does not activate the workspace without a map target', async () => {
 const fs = await import('node:fs');
 const vm = await import('node:vm');
 const source = fs.readFileSync(new URL('../../apps/web/client/memoir/client.js', import.meta.url), 'utf8');
 const unknown = {place: 'Somewhere unknown', hierarchy: ['Earth', 'Somewhere unknown'], granularity: 'city'};
 const mapped = {place: 'Hobart', hierarchy: ['Earth', 'Australia', 'Hobart'], granularity: 'city', latitude: -42.88, longitude: 147.33};
 const context = vm.createContext({
  state: {placeJourney: unknown, lifeStage: 'all', selectedPlace: placeHistoryKey(unknown)},
  mapTarget, mergePlaces, placeHistoryKey, resolvedPlaceTargets: new Map(),
  profile: () => ({memory_places: [unknown, mapped]}), workspaceTabs: () => [],
 });
 for (const name of ['placeMapTarget', 'placeWorkspaceSelection', 'workspaceHasContent']) {
  vm.runInContext(source.match(new RegExp(`function ${name}\\([^]*?\\n\\}`))[0], context);
 }
 assert.equal(context.workspaceHasContent(), false);
 context.state.placeJourney = mapped;
 context.state.selectedPlace = placeHistoryKey(mapped);
 assert.equal(context.workspaceHasContent(), true);
});

test('map framing retains a geocoded place scale and uses a saved parent scale', async () => {
 const fs = await import('node:fs');
 const vm = await import('node:vm');
 const source = fs.readFileSync(new URL('../../apps/web/client/memoir/client.js', import.meta.url), 'utf8');
 const context = vm.createContext({});
 vm.runInContext(source.match(/const PLACE_MAP_VIEW_HEIGHTS = \{[^]*?\n\};/)[0], context);
 vm.runInContext(source.match(/function placeMapViewHeight\([^]*?\n\}/)[0], context);
 const country = {place: 'China', granularity: 'country'};
 assert.equal(context.placeMapViewHeight(country, {place: 'China'}), context.placeMapViewHeight(country));
 assert.ok(context.placeMapViewHeight(country) > context.placeMapViewHeight(city));
 assert.equal(context.placeMapViewHeight(suburb, city), context.placeMapViewHeight(city));
 assert.ok(context.placeMapViewHeight(suburb) < context.placeMapViewHeight(suburb, city));
});
