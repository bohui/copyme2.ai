import test from 'node:test';
import assert from 'node:assert/strict';
import {installMapFlightPreloader} from '../../apps/web/client/memoir/map-flight-preload.mjs';

const tick = () => new Promise(resolve => setImmediate(resolve));

function harness() {
  const listeners = new Set(), views = [], flights = [], preparation = [];
  let current = true, requests = 0, throttled = false, running;
  const globe = {tilesLoaded:false, preloadSiblings:false};
  const camera = {
    positionCartographic:{height:32000},
    setView(options) { views.push(options);globe.tilesLoaded = false; },
    cancelFlight() { const previous = running;running = null;previous?.cancel?.(); },
    flyTo(options) { this.cancelFlight();flights.push(options);running = options; },
  };
  const provider = {requestImage() { requests++;return throttled ? undefined : Promise.resolve({width:256}); }};
  const scene = {globe, screenSpaceCameraController:{enableInputs:true}, requestRender() {},
    postRender:{addEventListener(listener) { listeners.add(listener);return () => listeners.delete(listener); }}};
  const original = {fly:camera.flyTo, cancel:camera.cancelFlight, image:provider.requestImage};
  const dispose = installMapFlightPreloader({viewer:{camera, scene, isDestroyed:() => false}, provider,
    cesium:{Cartesian3:{fromDegrees:(longitude, latitude, height) => ({longitude, latitude, height})},
      Cartographic:{fromCartesian:value => value}, Math:{toDegrees:value => value}},
    isCurrent:() => current, onPreparing:value => preparation.push(value)});
  const frame = () => { for (const listener of [...listeners]) listener(); };
  return {camera, scene, provider, original, dispose, views, flights, preparation, listeners,
    requests:() => requests, stale:() => { current = false; }, throttle:value => { throttled = value; },
    async loaded() { globe.tilesLoaded = true;frame();frame();await tick(); },
    complete() { const flight = running;running = null;flight.complete(); }};
}

test('a flight waits for every zoom view and reuses prepared imagery until completion', async t => {
  const h = harness();t.after(h.dispose);
  let complete = 0;
  const destination = {longitude:117.93, latitude:40.97, height:1000};
  h.camera.flyTo({destination, duration:2.8, complete:() => complete++});
  assert.equal(h.scene.screenSpaceCameraController.enableInputs, false);
  assert.equal(h.scene.globe.preloadSiblings, true);
  const image = h.provider.requestImage(1, 2, 3);
  for (let i = 0; !h.flights.length && i < 40; i++) {
    assert.equal(h.provider.requestImage(1, 2, 3), image);
    await h.loaded();
  }
  assert.equal(h.flights.length, 1);
  assert.ok(h.views.length > 4);
  assert.ok(h.views.some(view => view.destination.height === destination.height));
  assert.ok(h.views.every(view => view.destination.longitude === destination.longitude));
  assert.equal(h.scene.globe.preloadSiblings, false);
  assert.equal(h.provider.requestImage(1, 2, 3), image, 'Cesium internal cancellation must retain prepared imagery');
  assert.equal(h.requests(), 1);
  h.complete();
  assert.equal(complete, 1);
  assert.equal(h.scene.screenSpaceCameraController.enableInputs, true);
  assert.equal(h.listeners.size, 0);
  h.provider.requestImage(1, 2, 3);
  assert.equal(h.requests(), 2, 'Completed flights release their temporary cache');
});

test('a slow preparation skips animation, frees controls and keeps requests recoverable', async t => {
  t.mock.timers.enable({apis:['setTimeout']});
  const h = harness();t.after(h.dispose);
  let complete = 0;
  const destination = {longitude:151.2, latitude:-33.86, height:12000};
  h.camera.flyTo({destination, duration:2.8, complete:() => complete++});
  const image = h.provider.requestImage(1, 2, 3);
  t.mock.timers.tick(20000);await tick();
  assert.equal(h.flights.length, 0);
  assert.deepEqual(h.views.at(-1).destination, destination);
  assert.equal(complete, 1);
  assert.equal(h.scene.screenSpaceCameraController.enableInputs, true);
  assert.equal(h.scene.globe.preloadSiblings, false);
  assert.equal(h.listeners.size, 0);
  assert.deepEqual(await image, {width:256});
  h.provider.requestImage(1, 2, 3);
  assert.equal(h.requests(), 2);
});

test('cancellation, stale navigation and disposal cannot start an old prepared flight', async () => {
  for (const mode of ['cancel', 'stale', 'dispose']) {
    const h = harness();
    let cancelled = 0;
    h.camera.flyTo({destination:{longitude:1, latitude:2, height:1000}, duration:2.8,
      cancel:() => cancelled++});
    if (mode === 'cancel') h.camera.cancelFlight();
    if (mode === 'stale') h.stale();
    if (mode === 'dispose') h.dispose();
    await h.loaded();
    assert.equal(h.flights.length, 0);
    assert.equal(h.listeners.size, 0);
    assert.equal(h.scene.screenSpaceCameraController.enableInputs, true);
    assert.equal(cancelled, mode === 'stale' ? 0 : 1);
    h.dispose();
    assert.equal(h.camera.flyTo, h.original.fly);
    assert.equal(h.camera.cancelFlight, h.original.cancel);
    assert.equal(h.provider.requestImage, h.original.image);
  }
});

test('throttled requests are retried and reduced motion starts without preparation', async t => {
  const h = harness();t.after(h.dispose);
  h.camera.flyTo({destination:{longitude:1, latitude:2, height:1000}, duration:2.8});
  h.throttle(true);
  assert.equal(h.provider.requestImage(1, 2, 3), undefined);
  h.throttle(false);
  assert.ok(await h.provider.requestImage(1, 2, 3));
  assert.equal(h.requests(), 2);
  h.camera.cancelFlight();
  const views = h.views.length;
  h.camera.flyTo({destination:{longitude:3, latitude:4, height:12000}, duration:0});
  assert.equal(h.flights.length, 1);
  assert.equal(h.views.length, views);
  assert.equal(h.scene.screenSpaceCameraController.enableInputs, true);
});
