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
test('renderer keeps detailed title and labels parent map coordinates', async () => {
 const fs = await import('node:fs');
 const vm = await import('node:vm');
 const source=fs.readFileSync(new URL('../../apps/web/client/memoir/client.js',import.meta.url),'utf8');
 const context=vm.createContext({mapTarget, mergePlaces, placeHistoryKey, resolvedPlaceTargets:new Map(), profile:()=>({memory_places:[city,suburb]}), escapeHtml:String, translate:k=>k, translateWith:(k,v)=>`${k} ${v.place || ''}`, currentUiLocale:()=> 'en-AU'});
 for (const name of ['placeMapUrl','placeJourneyMarkup']) vm.runInContext(source.match(new RegExp(`function ${name}\\([^]*?\\n\\}`))[0],context);
 const markup=context.placeJourneyMarkup(suburb);
 assert.match(markup,/<h2>大石庙镇<\/h2>/);
 assert.match(markup,/data-cesium-place="承德"/);
 assert.match(markup,/data-cesium-latitude="40.97"/);
 assert.match(markup,/parentMap 承德/);
});
