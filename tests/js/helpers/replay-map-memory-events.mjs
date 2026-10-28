import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {buildMapMemoryJourney,cityEventCards} from '../../../apps/web/client/memoir/map-memory-journey.mjs';
import {groupPlaces} from '../../../apps/web/client/memoir/places.mjs';

const {events,locations,places} = JSON.parse(readFileSync(0,'utf8'));
const journey = buildMapMemoryJourney(events.map(event => ({...event,canonical:true,
  map_places:locations[event.id].items})),groupPlaces(places));
assert.equal(journey.nodes.length,2,'Both canonical API events need separate map cards');
const cities = cityEventCards(journey.nodes);
assert.equal(cities.length,1,'The initial map groups both events under Sydney');
assert.equal(cities[0].city,'Sydney');
assert.equal(cities[0].count,2);
assert.deepEqual(journey.nodes.map(node=>node.place),['Newtown','Pyrmont']);
assert.deepEqual(journey.nodes.map(node=>node.age.start),[6,25]);
assert.notEqual(journey.nodes[0].latitude,journey.nodes[1].latitude,
  'Zooming in must retain actual event coordinates instead of the city centre');
assert.ok(journey.nodes.every(node=>!node.cityOnly));
assert.equal(journey.legs.length,1,'The footprint trail connects the two age stages');
