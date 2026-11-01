import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readMemoirClientSource} from './helpers/memoir-source.mjs';
import {escapeHtml} from '../../apps/web/client/memoir/dom.mjs';

const source = readMemoirClientSource();
const extract = name => source.match(new RegExp(`function ${name}\\([^]*?\\n\\}`))[0];
const init = extract('initCesiumPlaceJourney');
const tick = () => new Promise(resolve => setImmediate(resolve));

class Event {
  listeners = new Set();
  addEventListener(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
  raiseEvent(value) { for (const listener of [...this.listeners]) listener(value); }
}

async function harness(provider = 'geoapify', {throttled = false, sessionFailure = false, libraryFailure = false, reducedMotion = true} = {}) {
  let resolveImage, rejectImage;
  const image = new Promise((resolve, reject) => { resolveImage = resolve; rejectImage = reject; });
  const classes = new Set();
  const attributes = new Map();
  const retryHandlers = new Map();
  const retry = {addEventListener: (event, listener) => retryHandlers.set(event, listener)};
  const fallback = {innerHTML:'', querySelector:() => retry,
    setAttribute: (key, value) => attributes.set(key, value), removeAttribute: key => attributes.delete(key)};
  const sceneElement = {classList: {add: name => classes.add(name), remove: (...names) => names.forEach(name => classes.delete(name))}};
  const journey = {place: '承德', granularity: 'city', latitude: 40.97, longitude: 117.93};
  const container = {isConnected: true, dataset: {cesiumLatitude: '40.97', cesiumLongitude: '117.93', cesiumPlace: '承德'},
    closest: () => sceneElement, parentElement: {querySelector: selector => selector === '[data-map-retry]' ? retry : fallback}};
  let viewer, imagery, loads = 0, renders = 0;
  const flights=[], timers=new Map();
  let timerId=0;
  class Provider {
    errorEvent = new Event();
    requestImage() { return throttled ? undefined : image; }
    constructor() { imagery = this; }
  }
  const cesium = {
    UrlTemplateImageryProvider: Provider,
    Google2DImageryProvider: {fromUrl: async () => {
      if (sessionFailure) throw new Error('Captured Google createSession HTTP 403');
      return new Provider();
    }},
    Credit: class {}, WebMercatorProjection: class {}, Cartesian2: class {},
    Cartesian3: {fromDegrees: (longitude, latitude, height) => ({longitude, latitude, height})},
    Color: {fromCssColorString: value => value}, LabelStyle: {}, ScreenSpaceEventType: {}, EasingFunction: {},
    Viewer: class {
      constructor() {
        viewer = this;
        this.destroyed = false;
        this.scene = {mode: 3, globe: {ellipsoid: {maximumRadius: 6378137},tilesLoaded:false},
          screenSpaceCameraController:{enableInputs:true},postRender:new Event(),skyAtmosphere: {}, requestRender() {},
          morphTo2D: () => { this.scene.mode = 2;this.scene.globe.tilesLoaded=false; }, morphTo3D: () => { this.scene.mode = 3; }};
        this.entities = {add() {}};
        this.screenSpaceEventHandler = {setInputAction() {}};
        this.camera = {frustum: {fovy: 1, aspectRatio: 1}, setView:options=>{this.view=options;}, cancelFlight() {},
          flyTo: options => { flights.push({options,layer:this.imageryLayers.layer});
            this.completeFlight=()=>{this.scene.globe.tilesLoaded=false;options.complete();}; }};
        this.imageryLayers = {
          layer: null,
          addImageryProvider(value) { return this.layer = {imageryProvider: value}; },
          remove(value) { if (this.layer === value) this.layer = null; },
        };
      }
      resize() {}
      isDestroyed() { return this.destroyed; }
      destroy() { this.destroyed = true; }
    },
  };
  const context = vm.createContext({
    $: () => container, resolvePlaceMap() {},
    placeWorkspaceSelection: () => context.placeMapAvailable(journey) ? journey : null,
    placeMapTarget: value => value, placeMapViewHeight: () => 40000,
    loadCesium: async () => {
      loads++;
      if (libraryFailure) throw new Error('Captured Cesium load failure');
      return cesium;
    }, state: {project:{id:'p'}, placeJourney:journey, workspaceCollapsed:false, supabase: {geo_provider: provider,
      geoapify_browser_api_key: 'synthetic-key', google_maps_browser_api_key: 'synthetic-key'}},
    window: {matchMedia: () => ({matches: reducedMotion})}, currentUiLocale: () => 'en-AU',
    mapPhotoAlbums: {sync() {}, attach() {},dispose() {}}, mapMemoryEvents: {sync() {}, attach() {},dispose() {}},
    cesiumPlaceJourneyViewer: null, cesiumLoadPromise:null,disposeOpeningFlight:null,console: {warn() {}},
    setTimeout:callback=>{timers.set(++timerId,callback);return timerId;},clearTimeout:id=>timers.delete(id),
    placeMapRenderKey: () => 'map', unavailablePlaceMaps: new Set(), render() {renders++;context.initCesiumPlaceJourney();},
    composingWorkspaceActive: () => false, freeRecallFinished: () => false,
    escapeHtml, translate: key => key,
  });
  for (const name of ['placeMapAvailable','workspaceContentAvailable','workspaceHasContent','workspaceIsVisible']) {
    vm.runInContext(extract(name), context);
  }
  vm.runInContext(init, context);
  vm.runInContext(extract('disposeCesiumPlaceJourney'),context);
  context.initCesiumPlaceJourney();
  await tick();
  const frame=()=>viewer.scene.postRender.raiseEvent();
  const loadedTiles=()=>{viewer.scene.globe.tilesLoaded=true;frame();frame();};
  return {viewer, imagery, container, classes, attributes, resolveImage, rejectImage, context, fallback,flights,frame,loadedTiles,timers,
    unavailable:context.unavailablePlaceMaps, retryHandlers, loads:()=>loads, renders:()=>renders,
    restoreProvider:()=>{sessionFailure=false;libraryFailure=false;}};
}

test('the imagery layer is attached before the opening flight starts',async()=>{
  const h=await harness('google',{reducedMotion:false});
  assert.equal(h.flights.length,0,'An initialized provider is not a loaded globe');
  const pending=h.imagery.requestImage(0,0,0);
  h.resolveImage({width:256,height:256});
  await pending;
  h.frame();h.frame();
  assert.equal(h.flights.length,0,'One tile must not start a flight while other tiles are loading');
  h.loadedTiles();
  assert.equal(h.flights.length,1);
  assert.ok(h.flights[0].layer,'The descent must not outrun imagery initialization');
});

test('the descent waits for each rendered zoom level and reaches the city without a final snap',async()=>{
  const h=await harness('geoapify',{reducedMotion:false});
  const pending=h.imagery.requestImage(0,0,0);
  h.resolveImage({width:256,height:256});await pending;
  h.loadedTiles();
  assert.equal(h.flights[0].options.destination.height,640000);
  h.viewer.completeFlight();h.frame();h.frame();
  assert.equal(h.viewer.scene.mode,3,'Do not switch projection before the regional tiles load');
  h.loadedTiles();
  assert.equal(h.viewer.scene.mode,2);
  assert.equal(h.flights.length,1,'The new projection must render its own loaded tiles');
  h.loadedTiles();
  assert.equal(h.flights[1].options.destination.height,160000);
  h.viewer.completeFlight();h.frame();h.frame();
  assert.equal(h.flights.length,2,'Hold the regional view while detail is loading');
  h.loadedTiles();
  assert.equal(h.flights[2].options.destination.height,40000);
  assert.ok(h.flights.every(flight=>flight.options.duration>=2.8));
  h.viewer.completeFlight();
  assert.equal(h.classes.has('is-cesium-map'),false);
  h.loadedTiles();
  assert.equal(h.classes.has('is-cesium-map'),true);
  assert.equal(h.viewer.scene.screenSpaceCameraController.enableInputs,true);
  assert.equal(h.viewer.scene.postRender.listeners.size,0);
  assert.equal(h.timers.size,0);
});

test('a stalled tile queue restores the explicit retry and clears the opening listeners',async()=>{
  const h=await harness();
  [...h.timers.values()][0]();
  assert.equal(h.unavailable.has('map'),true);
  assert.equal(h.viewer.scene.screenSpaceCameraController.enableInputs,true);
  assert.equal(h.viewer.scene.postRender.listeners.size,0);
  assert.equal(h.timers.size,0);
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
