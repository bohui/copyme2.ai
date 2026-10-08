import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {groupPlaces, groupMapPins, mergePlaces, placeHistoryKey} from '../../apps/web/client/memoir/places.mjs';

const source=fs.readFileSync(new URL('../../apps/web/client/memoir/client.js',import.meta.url),'utf8');
const city={place:'承德',hierarchy:['Earth','中国','河北','承德'],granularity:'city',latitude:40.97,longitude:117.93,pictures:[{asset_id:'city-only'}]};
const children=['双桥区','大石庙镇'].map((place,index)=>({...city,place,hierarchy:[...city.hierarchy,place],granularity:'suburb',latitude:40.94+index*.001,longitude:117.96,pictures:[{asset_id:`child-${index}`}]}));

function albums(entries) {
  const group=groupPlaces(entries)[0];
  const pins=groupMapPins(group);
  const context=vm.createContext({
    state:{placeJourney:entries.at(-1)},profile:()=>({memory_places:entries}),mergePlaces,placeHistoryKey,
    workspacePlaceGroups:groupPlaces,placeWorkspaceSelection:()=>entries.at(-1),
    mapPhotoAlbum:key=>{const entry=entries.find(item=>placeHistoryKey(item)===key);return entry&&{key,place:entry.place,pictures:entry.pictures};},
  });
  const helper=source.match(/function mapPhotoAlbumsForScene\([^]*?\n\}/);
  assert.ok(helper,'scene album collection must be independent of resolved pins');
  vm.runInContext(helper[0],context);
  return context.mapPhotoAlbumsForScene({querySelector:()=>({dataset:{placeKey:group.key,cesiumPins:JSON.stringify(pins)}})});
}

test('the parent city album survives independent child pins and photos',()=>{
  const entries=[city,...children];
  assert.equal(groupMapPins(groupPlaces(entries)[0]).length,2);
  const result=albums(entries);
  assert.deepEqual(Array.from(result,album=>album.place),['承德','双桥区','大石庙镇']);
  assert.deepEqual(Array.from(result,album=>album.pinned),[false,true,true]);
  assert.deepEqual(Array.from(result,album=>album.pictures[0].asset_id),['city-only','child-0','child-1']);
});

test('unresolved group members retain album entry points without inventing map pins',()=>{
  const result=albums([city,...children].map(entry=>({...entry,map_pin:null})));
  assert.equal(result.length,3);
  assert.ok(result.every(album=>album.pinned===false));
  assert.deepEqual(Array.from(result,album=>album.pictures[0].asset_id),['city-only','child-0','child-1']);
});
