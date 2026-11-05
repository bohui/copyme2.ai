export function installMapFlightPreloader({viewer, cesium, provider, isCurrent, onPreparing}) {
  const {camera, scene} = viewer;
  const {globe, screenSpaceCameraController: controller} = scene;
  const flyTo = camera.flyTo, cancelFlight = camera.cancelFlight, requestImage = provider.requestImage;
  let active, nativeStarting = false, disposed = false;
  const current = () => !disposed && isCurrent();

  function release(job) {
    if (active !== job) return false;
    active = null;
    job.stopWait?.(false);
    job.images.clear();
    if (!viewer.isDestroyed()) {
      globe.preloadSiblings = job.preloadSiblings;
      controller.enableInputs = job.enableInputs;
      onPreparing(false);
    }
    return true;
  }

  function wrappedRequestImage(...args) {
    const images = active?.images, key = args.slice(0, 3).join(":");
    if (images?.has(key)) return images.get(key);
    const image = requestImage.apply(provider, args);
    // Undefined is Cesium's throttle signal; it must be requested again later.
    if (image && active?.preparing) images.set(key, image);
    return image;
  }

  function wrappedCancelFlight() {
    const job = active;
    const result = cancelFlight.call(camera);
    // Cesium cancels its previous flight internally when starting the prepared one.
    if (!nativeStarting && job && release(job) && job.preparing) job.options.cancel?.();
    return result;
  }

  function waitForTiles(job) {
    return new Promise(resolve => {
      let frames = 0;
      const stop = loaded => {
        remove();
        clearTimeout(timer);
        if (job.stopWait === stop) job.stopWait = null;
        resolve(loaded);
      };
      const remove = scene.postRender.addEventListener(() => {
        if (active !== job || !current()) { release(job);stop(false);return; }
        // Let the new view populate its tile queue before checking readiness.
        if (++frames >= 2 && globe.tilesLoaded) stop(true);
      });
      const timer = setTimeout(() => stop(false), 20000);
      job.stopWait = stop;
      scene.requestRender();
    });
  }

  function skipSlowFlight(job) {
    if (active !== job || !current()) return;
    // Keep pending imagery alive and skip animation when a view is too slow.
    camera.setView({destination:job.options.destination, orientation:job.options.orientation});
    release(job);
    job.options.complete?.();
  }

  async function prepare(job, target, startHeight) {
    const view = height => ({destination:cesium.Cartesian3.fromDegrees(
      cesium.Math.toDegrees(target.longitude), cesium.Math.toDegrees(target.latitude), height),
    ...(job.options.orientation ? {orientation:job.options.orientation} : {})});
    let height = startHeight;
    while (active === job && current()) {
      camera.setView(view(height));
      if (!await waitForTiles(job)) { skipSlowFlight(job);return; }
      if (height === target.height) break;
      height = Math.max(target.height, height / Math.SQRT2);
    }
    if (active !== job || !current()) { release(job);return; }
    globe.preloadSiblings = job.preloadSiblings;
    camera.setView(view(startHeight));
    if (!await waitForTiles(job)) { skipSlowFlight(job);return; }
    job.preparing = false;
    onPreparing(false);
    nativeStarting = true;
    try {
      flyTo.call(camera, {...job.options, maximumHeight:startHeight,
        complete:() => { if (release(job)) job.options.complete?.(); },
        cancel:() => { if (release(job)) job.options.cancel?.(); }});
    } finally {
      nativeStarting = false;
    }
  }

  function wrappedFlyTo(options) {
    wrappedCancelFlight();
    if (!current()) return;
    if (options.duration === 0) return flyTo.call(camera, options);
    const target = cesium.Cartographic.fromCartesian(options.destination);
    if (!Number.isFinite(target?.height) || target.height <= 0) return flyTo.call(camera, options);
    const job = {options, images:new Map(), preparing:true,
      preloadSiblings:globe.preloadSiblings, enableInputs:controller.enableInputs};
    active = job;
    controller.enableInputs = false;
    // Neighbours cover the view bounds between the sampled zoom levels.
    globe.preloadSiblings = true;
    onPreparing(true);
    const startHeight = Math.max(camera.positionCartographic.height, target.height * 16);
    void prepare(job, target, startHeight).catch(() => {
      if (release(job)) job.options.cancel?.();
    });
  }

  provider.requestImage = wrappedRequestImage;
  camera.flyTo = wrappedFlyTo;
  camera.cancelFlight = wrappedCancelFlight;
  return () => {
    disposed = true;
    wrappedCancelFlight();
    if (camera.flyTo === wrappedFlyTo) camera.flyTo = flyTo;
    if (camera.cancelFlight === wrappedCancelFlight) camera.cancelFlight = cancelFlight;
    if (provider.requestImage === wrappedRequestImage) provider.requestImage = requestImage;
  };
}
