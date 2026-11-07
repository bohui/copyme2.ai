import test from 'node:test';
import assert from 'node:assert/strict';
import {harness, tick} from './helpers/place-map-imagery.mjs';

for (const provider of ['google','geoapify']) {
  test(`${provider}: imagery initialization leaves automatic flights to current_active_location`,async()=>{
    const h=await harness(provider,{reducedMotion:false});
    const pending=h.imagery.requestImage(0,0,0);
    h.resolveImage({width:256,height:256});await pending;
    h.frame();h.frame();
    assert.equal(h.classes.has('is-cesium-map'),false);
    h.loadedTiles();
    assert.equal(h.classes.has('is-cesium-map'),true);
    assert.equal(h.flights.length,0,'Loading a map is not an active-location change');
    assert.equal(h.viewer.scene.mode,2);
    assert.equal(h.viewer.view.destination.longitude,117.93,'A map without a framed journey opens on its known place');
    assert.equal(h.viewer.view.destination.latitude,40.97);
    assert.equal(h.viewer.scene.screenSpaceCameraController.enableInputs,true);
  });

}

test('concurrent Google tiles share one viewport credit read', async () => {
  const h = await harness('google');
  const first = h.imagery.getViewportCredits();
  const second = h.imagery.getViewportCredits();
  assert.equal(first, second);
  assert.deepEqual(await first, ['Synthetic attribution']);
  assert.equal(h.viewportReads(), 1);
  assert.equal(await h.context.loadPlaceImagery({}), h.imagery);
});

for (const provider of ['google', 'geoapify']) for (const [mode, options] of [
  ['reduced motion', {}], ['opening flight', {reducedMotion:false}],
  ['unresolved focus', {reducedMotion:false,pendingFocus:true}],
]) {
  test(`${provider}: slow ${mode} recovers after the tile deadline without another viewer`,async()=>{
    const h=await harness(provider,options);
    const pending=h.imagery.requestImage(0,0,0);
    const layer=h.viewer.imageryLayers.layer;
    h.expireTileWait();
    assert.equal(h.unavailable.has('map'),false,'A slow response must remain recoverable');
    assert.equal(h.viewer.imageryLayers.layer,layer,'Keep pending requests alive');
    assert.equal(h.viewer.scene.screenSpaceCameraController.enableInputs,true);
    assert.equal(h.classes.has('is-cesium-map'),false,'Wait for destination tiles before declaring arrival');
    assert.equal(h.viewer.scene.mode,2);
    assert.equal(h.viewer.view.destination.longitude,117.93);
    h.resolveImage({width:256,height:256});await pending;
    h.frame();h.frame();
    assert.equal(h.classes.has('is-cesium-map'),false,'A late first image must still wait for the destination queue');
    h.loadedTiles();
    assert.equal(h.classes.has('is-cesium-map'),true);
    assert.equal(h.viewer.scene.postRender.listeners.size,0);
    assert.equal(h.timers.size,0);
    assert.equal(h.flights.length,0,'Late tiles must not restart the opening flight');
    assert.equal(h.loads(),1);
    assert.equal(h.renders(),0);
  });
}

test('a slow Google session can attach and load tiles after the opening deadline',async()=>{
  const h=await harness('google',{sessionPending:true});
  h.expireTileWait();
  h.finishSession();await tick();
  assert.ok(h.viewer.imageryLayers.layer);
  const pending=h.viewer.imageryLayers.layer.imageryProvider.requestImage(0,0,0);
  h.resolveImage({width:256,height:256});await pending;h.loadedTiles();
  assert.equal(h.classes.has('is-cesium-map'),true);
  assert.equal(h.unavailable.size,0);
  assert.equal(h.loads(),1);
});

test('a queued deadline cannot move a map after project navigation or disposal',async()=>{
  for (const change of ['project','detach','dispose']) {
    const h=await harness('google',{reducedMotion:false});
    const timeout=[...h.timers.values()][0];
    if (change==='project') h.context.state.project.id='other';
    else if (change==='detach') h.container.isConnected=false;
    else h.context.disposeCesiumPlaceJourney();
    timeout();
    assert.equal(h.viewer.scene.mode,2);
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
  assert.equal(h.imagery.errorEvent.listeners.size,0,'Cached providers must not retain a disposed viewer');
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
    assert.equal(h.viewer.view.destination.longitude,117.93);
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
