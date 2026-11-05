import vm from 'node:vm';
import {readMemoirClientSource} from './memoir-source.mjs';
import {escapeHtml} from '../../../apps/web/client/memoir/dom.mjs';

const source = readMemoirClientSource();
const extract = name => source.match(new RegExp(`function ${name}\\([^]*?\\n\\}`))[0];
const init = extract('initCesiumPlaceJourney');
export const tick = () => new Promise(resolve => setImmediate(resolve));

class Event {
  listeners = new Set();
  addEventListener(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
  raiseEvent(value) { for (const listener of [...this.listeners]) listener(value); }
}

export async function harness(provider = 'geoapify', {journey = {place: '承德', granularity: 'city', latitude: 40.97, longitude: 117.93}, projectId = 'p', placeKey = 'city:chengde', throttled = false, sessionFailure = false, sessionPending = false, libraryFailure = false, reducedMotion = true, animated = false, pendingFocus = false} = {}) {
  let resolveImage, rejectImage;
  const image = new Promise((resolve, reject) => { resolveImage = resolve; rejectImage = reject; });
  const classes = new Set();
  const attributes = new Map();
  const retryHandlers = new Map();
  const retry = {addEventListener: (event, listener) => retryHandlers.set(event, listener)};
  const fallback = {innerHTML:'', querySelector:() => retry,
    setAttribute: (key, value) => attributes.set(key, value), removeAttribute: key => attributes.delete(key)};
  const sceneElement = {classList: {add: name => classes.add(name), remove: (...names) => names.forEach(name => classes.delete(name))}};
  const container = {isConnected: true, dataset: {placeKey,cesiumLatitude: String(journey.latitude), cesiumLongitude: String(journey.longitude), cesiumPlace: journey.place,cesiumHeight:journey.height ? String(journey.height) : ''},
    closest: () => sceneElement, parentElement: {querySelector: selector => selector === '[data-map-retry]' ? retry : fallback}};
  if (pendingFocus) container.dataset.cesiumPending='true';
  let viewer, imagery, finishSession, loads = 0, renders = 0;
  const views=[],flights=[], timers=new Map(),animatedCities=new Set(animated ? [placeKey] : []);
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
      if (sessionPending) await new Promise(resolve=>{finishSession=resolve;});
      return new Provider();
    }},
    Credit: class {}, WebMercatorProjection: class {}, Cartesian2: class {},
    Cartesian3: {fromDegrees: (longitude, latitude, height) => ({longitude, latitude, height})},
    Color: {fromCssColorString: value => value}, LabelStyle: {}, ScreenSpaceEventType: {}, EasingFunction: {},
    Viewer: class {
      constructor() {
        viewer = this;
        this.destroyed = false;
        this.scene = {mode: 3, globe: {ellipsoid: {maximumRadius: 6378137},tilesLoaded:false,preloadSiblings:false},
          screenSpaceCameraController:{enableInputs:true},postRender:new Event(),skyAtmosphere: {}, requestRender() {},
          morphTo2D: () => { this.scene.mode = 2;this.scene.globe.tilesLoaded=false; }, morphTo3D: () => { this.scene.mode = 3; }};
        this.entities = {add() {}};
        this.screenSpaceEventHandler = {setInputAction() {}};
        this.camera = {frustum: {fovy: 1, aspectRatio: 1}, setView:options=>{this.view=options;views.push({mode:this.scene.mode,...options});this.scene.globe.tilesLoaded=false;}, cancelFlight() {},
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
    }, state: {project:{id:projectId}, placeJourney:journey, workspaceCollapsed:false, supabase: {geo_provider: provider,
      geoapify_browser_api_key: 'synthetic-key', google_maps_browser_api_key: 'synthetic-key'}},
    window: {matchMedia: () => ({matches: reducedMotion})}, currentUiLocale: () => 'en-AU',
    mapPhotoAlbums: {sync() {}, attach() {},dispose() {}}, mapMemoryEvents: {sync() {}, attach() {},dispose() {},
      hasAnimatedCity:city=>animatedCities.has(city),rememberFlight:city=>animatedCities.add(city)},
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
    views,finishSession, expireTileWait() { const [id, callback] = [...timers][0]; timers.delete(id); callback(); },
    unavailable:context.unavailablePlaceMaps, retryHandlers, loads:()=>loads, renders:()=>renders,
    restoreProvider:()=>{sessionFailure=false;libraryFailure=false;}};
}
