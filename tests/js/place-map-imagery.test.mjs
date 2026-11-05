import test from 'node:test';
import assert from 'node:assert/strict';
import {harness, tick} from './helpers/place-map-imagery.mjs';

for (const provider of ['google','geoapify']) test(`${provider}: planned views preload before one continuous flight`,async()=>{
  const h=await harness(provider,{reducedMotion:false});
  const pending=h.imagery.requestImage(0,0,0);
  h.resolveImage({width:256,height:256});await pending;h.loadedTiles();
  assert.equal(h.flights.length,0,'Loading the opening globe must not start an unprepared zoom');
  let loadedViews=0;
  while (!h.flights.length && loadedViews<32) {
    h.frame();h.frame();
    assert.equal(h.flights.length,0,'A pending zoom view must hold the animation');
    h.loadedTiles();loadedViews++;
  }
  assert.ok(loadedViews>3 && loadedViews<32);
  assert.ok(h.views.some(view=>view.mode===2 && view.destination.height===40000),'Preload the final 2D view too');
  assert.equal(h.flights.length,1);
  assert.equal(h.viewer.scene.globe.preloadSiblings,false,'Restore normal loading once preparation finishes');
  assert.equal(h.flights[0].options.destination.height,40000);
  h.viewer.completeFlight();h.loadedTiles();
  assert.equal(h.flights.length,1,'The visible zoom must not stop for intermediate tile queues');
  assert.equal(h.classes.has('is-cesium-map'),true);
  assert.equal(h.viewer.scene.screenSpaceCameraController.enableInputs,true);
  assert.equal(h.viewer.scene.postRender.listeners.size,0);
  assert.equal(h.timers.size,0);
});

test('the imagery layer is attached before the opening flight starts',async()=>{
  const h=await harness('google',{reducedMotion:false});
  assert.equal(h.flights.length,0,'An initialized provider is not a loaded globe');
  const pending=h.imagery.requestImage(0,0,0);
  h.resolveImage({width:256,height:256});
  await pending;
  h.frame();h.frame();
  assert.equal(h.flights.length,0,'One tile must not start a flight while other tiles are loading');
  h.loadedTiles();
  for (let i=0;!h.flights.length && i<32;i++) h.loadedTiles();
  assert.equal(h.flights.length,1);
  assert.ok(h.flights[0].layer,'The descent must not outrun imagery initialization');
});

test('an unresolved question shows a usable globe without choosing or animating a city',async()=>{
  const h=await harness('google',{pendingFocus:true,reducedMotion:false});
  const pending=h.imagery.requestImage(0,0,0);
  h.resolveImage({width:256,height:256});await pending;h.loadedTiles();
  assert.equal(h.classes.has('is-cesium-map'),true);
  assert.equal(h.flights.length,0);
  assert.equal(h.viewer.view.destination.longitude,0);
  assert.equal(h.viewer.scene.mode,3);
  assert.equal(h.viewer.scene.screenSpaceCameraController.enableInputs,true);
  assert.equal(h.context.mapMemoryEvents.hasAnimatedCity('city:chengde'),false);
});

test('prepared imagery is reused during the flight and released after arrival',async()=>{
  const h=await harness('google',{reducedMotion:false});
  const pending=h.imagery.requestImage(0,0,0);
  assert.equal(h.imagery.requestImage(0,0,0),pending);
  h.resolveImage({width:256,height:256});await pending;
  for (let i=0;!h.flights.length && i<32;i++) h.loadedTiles();
  assert.equal(h.flights.length,1);
  assert.equal(h.imagery.requestImage(0,0,0),pending);
  h.viewer.completeFlight();h.loadedTiles();
  const afterArrival=h.imagery.requestImage(0,0,0);
  assert.notEqual(afterArrival,pending,'The temporary preload cache must not grow during later map use');
  await afterArrival;
});

test('recreating a viewer for an already animated city skips the Earth flight',async()=>{
  const h=await harness('google',{reducedMotion:false,animated:true});
  assert.equal(h.flights.length,0);
  assert.equal(h.viewer.scene.mode,2);
  const pending=h.imagery.requestImage(0,0,0);
  h.resolveImage({width:256,height:256});await pending;
  h.loadedTiles();
  assert.equal(h.classes.has('is-cesium-map'),true);
  assert.equal(h.flights.length,0,'An in-page city return should open directly at city scale');
});

test('a background repaint cannot restart an opening city flight already underway',async()=>{
  const h=await harness('google',{reducedMotion:false});
  const pending=h.imagery.requestImage(0,0,0);
  h.resolveImage({width:256,height:256});await pending;h.loadedTiles();
  for (let i=0;!h.flights.length && i<32;i++) h.loadedTiles();
  assert.equal(h.flights.length,1);
  h.context.disposeCesiumPlaceJourney();h.context.initCesiumPlaceJourney();await tick();
  assert.equal(h.context.cesiumPlaceJourneyViewer.scene.mode,2);
  assert.equal(h.flights.length,1,'The replacement viewer must open directly at city scale');
});

for (const provider of ['google','geoapify']) for (const [mode,options] of [
  ['reduced motion',{}],['opening flight',{reducedMotion:false}],
  ['unresolved focus',{reducedMotion:false,pendingFocus:true}],
]) test(`${provider}: slow ${mode} recovers after the deadline without reload`,async()=>{
  const h=await harness(provider,options);
  const pending=h.imagery.requestImage(0,0,0);
  const layer=h.viewer.imageryLayers.layer;
  h.expireTileWait();
  assert.equal(h.unavailable.size,0);
  assert.equal(h.viewer.imageryLayers.layer,layer);
  assert.equal(h.viewer.scene.screenSpaceCameraController.enableInputs,true);
  assert.equal(h.classes.has('is-cesium-map'),false);
  assert.equal(h.viewer.scene.mode,options.pendingFocus ? 3 : 2);
  h.resolveImage({width:256,height:256});await pending;
  h.frame();h.frame();assert.equal(h.classes.has('is-cesium-map'),false);
  h.loadedTiles();
  assert.equal(h.classes.has('is-cesium-map'),true);
  assert.equal(h.flights.length,0);
  assert.equal(h.loads(),1);
  assert.equal(h.renders(),0);
  assert.equal(h.timers.size,0);
  assert.equal(h.viewer.scene.postRender.listeners.size,0);
});

test('a deadline during preparation abandons the animation but keeps the destination recoverable',async()=>{
  const h=await harness('google',{reducedMotion:false});
  const pending=h.imagery.requestImage(0,0,0);
  h.resolveImage({width:256,height:256});await pending;h.loadedTiles();
  assert.equal(h.classes.has('is-cesium-live'),false,'Preparation camera changes must stay hidden');
  h.expireTileWait();h.loadedTiles();
  assert.equal(h.classes.has('is-cesium-live'),true);
  assert.equal(h.classes.has('is-cesium-map'),true);
  assert.equal(h.viewer.scene.mode,2);
  assert.equal(h.viewer.view.destination.height,40000);
  assert.equal(h.flights.length,0);
  assert.equal(h.unavailable.size,0);
});

test('a slow Google session can attach and load after the deadline',async()=>{
  const h=await harness('google',{sessionPending:true});
  h.expireTileWait();
  h.finishSession();await tick();
  assert.ok(h.viewer.imageryLayers.layer);
  const pending=h.viewer.imageryLayers.layer.imageryProvider.requestImage(0,0,0);
  h.resolveImage({width:256,height:256});await pending;h.loadedTiles();
  assert.equal(h.classes.has('is-cesium-map'),true);
  assert.equal(h.unavailable.size,0);
});

test('a queued deadline cannot move a map after navigation or disposal',async()=>{
  for (const change of ['project','detach','dispose']) {
    const h=await harness('google',{reducedMotion:false});
    const timeout=[...h.timers.values()][0];
    if (change==='project') h.context.state.project.id='other';
    else if (change==='detach') h.container.isConnected=false;
    else h.context.disposeCesiumPlaceJourney();
    timeout();
    assert.equal(h.viewer.scene.mode,3);
    assert.equal(h.unavailable.size,0);
    assert.equal(h.viewer.scene.postRender.listeners.size,0);
    assert.equal(h.timers.size,0);
  }
});

test('disposing a map cancels its pending descent and tile timeout',async()=>{
  const h=await harness('google',{reducedMotion:false});
  h.context.disposeCesiumPlaceJourney();
  assert.equal(h.viewer.isDestroyed(),true);
  assert.equal(h.viewer.scene.postRender.listeners.size,0);
  assert.equal(h.timers.size,0);
  assert.equal(h.flights.length,0);
});

for (const failure of ['sessionFailure','libraryFailure']) {
  test(`${failure}: a failed map keeps the workspace and explicit retry without an automatic retry loop`, async () => {
    const h = await harness('google', {[failure]:true});
    assert.equal(h.unavailable.has('map'), true);
    assert.equal(h.context.workspaceIsVisible(), true, 'Saved places must not disappear with external imagery');
    const markup = h.fallback.innerHTML;
    assert.match(markup, /role="status"[^]*mapUnavailable/);
    assert.match(markup, /data-map-retry/);
    assert.doesNotMatch(markup, /Captured|HTTP 403|synthetic-key/);
    const loads = h.loads();
    h.context.initCesiumPlaceJourney();
    await tick();
    assert.equal(h.loads(), loads, 'Re-renders must not retry a denied provider');
    h.restoreProvider();
    h.context.cesiumLoadPromise = Promise.reject(new Error('Old failed library'));
    h.context.cesiumLoadPromise.catch(()=>{});
    h.retryHandlers.get('click')();
    assert.equal(h.unavailable.size, 0);
    assert.equal(h.context.cesiumLoadPromise, null);
    await tick();
    assert.equal(h.loads(), loads + 1);
  });
}

test('a stale map retry cannot change a different project', async () => {
  const h = await harness('google', {sessionFailure:true});
  h.context.initCesiumPlaceJourney();
  h.context.state.project.id = 'other';
  const renders = h.renders();
  h.retryHandlers.get('click')();
  assert.equal(h.unavailable.has('map'), true);
  assert.equal(h.renders(), renders);
});

test('throttled tile requests preserve Cesium retry behavior', async () => {
  const h = await harness('geoapify', {throttled: true});
  assert.equal(h.imagery.requestImage(0, 0, 0), undefined);
  h.loadedTiles();
  assert.equal(h.classes.has('is-cesium-map'), false);
});

test('late tiles from a detached map cannot enter the final view', async () => {
  const h = await harness();
  const pending = h.imagery.requestImage(0, 0, 0);
  h.container.isConnected = false;
  h.resolveImage({width: 256, height: 256});
  await pending;
  h.loadedTiles();
  assert.equal(h.classes.has('is-cesium-map'), false);
  assert.equal(h.unavailable.size, 0, 'a stale map cannot hide a newly selected map');
});

test('a late successful tile cannot revive a failed map', async () => {
  const h = await harness();
  const pending = h.imagery.requestImage(0, 0, 0);
  h.imagery.errorEvent.raiseEvent({message: '403 forbidden'});
  h.resolveImage({width: 256, height: 256});
  await pending;
  h.loadedTiles();
  assert.equal(h.classes.has('is-cesium-map'), false);
  assert.equal(h.attributes.has('aria-hidden'), false);
});

for (const provider of ['google', 'geoapify']) {
  test(`${provider}: reduced-motion map waits for all destination tiles without a flight`, async () => {
    const h = await harness(provider);
    assert.equal(h.flights.length,0);
    assert.equal(h.viewer.view.destination.height,40000);
    assert.equal(h.classes.has('is-cesium-map'), false, 'An initialized provider is not a loaded tile');
    const pending = h.imagery.requestImage(0, 0, 0);
    assert.equal(h.classes.has('is-cesium-map'), false);
    h.resolveImage({width: 256, height: 256});
    await pending;
    await tick();
    h.frame();h.frame();
    assert.equal(h.classes.has('is-cesium-map'),false,'A successful image is not a loaded view');
    h.loadedTiles();
    assert.equal(h.classes.has('is-cesium-map'), true);
    assert.equal(h.viewer.scene.mode, 2);
  });

  test(`${provider}: asynchronous tile failure hides the unavailable map`, async () => {
    const h = await harness(provider);
    const pending = h.imagery.requestImage(0, 0, 0);
    const failed = assert.rejects(pending, /403/);
    h.rejectImage(new Error('403 forbidden'));
    await failed;
    h.imagery.errorEvent.raiseEvent({message: '403 forbidden', retry: false});
    await tick();
    assert.equal(h.classes.has('is-cesium-map'), false, 'A failed tile cannot leave a blank 2D map');
    assert.equal(h.attributes.has('aria-hidden'), false, 'The fallback must be visible to assistive technology');
    assert.equal(h.classes.has('is-cesium-live'), false);
    assert.equal(h.viewer.imageryLayers.layer, null);
    assert.equal(h.unavailable.has('map'), true);
  });

  test(`${provider}: a tile error after arrival removes the failed map`, async () => {
    const h = await harness(provider);
    const pending = h.imagery.requestImage(0, 0, 0);
    h.resolveImage({width: 256, height: 256});
    await pending;
    h.loadedTiles();
    await tick();
    assert.equal(h.classes.has('is-cesium-map'), true);
    h.imagery.errorEvent.raiseEvent({message: '429 quota exhausted', retry: false});
    assert.equal(h.classes.has('is-cesium-map'), false);
    assert.equal(h.viewer.scene.mode, 3);
    assert.equal(h.attributes.has('aria-hidden'), false);
    assert.equal(h.unavailable.has('map'), true);
  });
}
