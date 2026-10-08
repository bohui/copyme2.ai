const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

export function albumStackMarkup(album, origin = 'https://memoir.invalid') {
  const images = (album.pictures || []).filter(photo => photo.allowed_actions?.embed).map(photo => {
    if (typeof photo.image_url !== 'string' || !photo.image_url.trim()) return '';
    try {
      const url = new URL(photo.image_url, origin);
      return url.protocol === 'https:' || (url.origin === origin && url.pathname.startsWith('/static/')) ? url.href : '';
    } catch { return ''; }
  }).filter(Boolean).slice(0, 3);
  const count = album.status === 'loading' ? '…' : album.status === 'error' ? '!' : album.count ?? 0;
  return `<button type="button" class="map-photo-album ${album.status === 'loading' ? 'is-loading' : ''}" data-photo-album="${escape(album.key)}" aria-label="${escape(album.label)}" aria-haspopup="dialog"><span class="map-album-stack" aria-hidden="true">${images.length ? images.map(src => `<img src="${escape(src)}" alt="" draggable="false" />`).join('') : '<span class="map-album-placeholder">▧</span>'}<span class="map-album-count">${count}</span></span><span class="map-album-place">${escape(album.place)}</span></button>`;
}

// Displace nearby albums while retaining a line to their actual geographic pin.
// If the panel cannot fit them, expose the remainder in a scrollable album tray.
export function layoutMapAlbums(points, width, height, reserve = 50) {
  const size = 74, step = 82, inset = 8;
  const boxes = [];
  const bottom = height - reserve;
  for (const point of points) {
    if (!Number.isFinite(point.x) || !Number.isFinite(point.y) || point.x < 0 || point.y < 0 || point.x > width || point.y > height) continue;
    let box;
    const columns = Math.ceil(width / step), rows = Math.ceil(height / step);
    for (let row = 0; row < rows && !box; row++) {
      for (let column = 0; column <= columns * 2 && !box; column++) {
        const dx = column === 0 ? 0 : Math.ceil(column / 2) * step * (column % 2 ? -1 : 1);
        const left = Math.max(inset, Math.min(width - size - inset, point.x - size / 2 + dx));
        const top = Math.max(inset, Math.min(bottom - size - inset, point.y - size - 22 - row * step));
        if (width < size + 2 * inset || bottom < size + 2 * inset) break;
        if (boxes.some(other => !other.overflow && left < other.left + step && left + step > other.left && top < other.top + step && top + step > other.top)) continue;
        box = {...point, left, top};
      }
    }
    boxes.push(box || {...point, overflow:true});
  }
  return reserve === 50 && boxes.some(box => box.overflow) ? layoutMapAlbums(points,width,height,122) : boxes;
}

export function createMapPhotoAlbums({getAlbum, getAlbums, getProjectId, renderAlbum, bindAlbum, closeLabel, onOpen = () => {}}) {
  let dialog, currentKey, currentProject, trigger, layer, signature, lastMarkup;
  let removePostRender;
  const mobile = () => window.matchMedia('(max-width: 760px)').matches;
  function hide() {
    const key = currentKey || trigger?.dataset.photoAlbum || trigger?.dataset.photoMarker;
    const restore = trigger?.isConnected ? trigger : [...(layer?.querySelectorAll('[data-photo-album]') || [])]
      .find(button => button.dataset.photoAlbum === key);
    if (dialog?.open) dialog.close();
    currentKey = null;
    currentProject = null;
    trigger = restore;
    restore?.focus({preventScroll:true});
    // Native dialog closing and the app's route listeners can detach/reinsert
    // the map. Resolve the current button after that work completes.
    requestAnimationFrame(() => {
      if (dialog?.open) return;
      const target = [...document.querySelectorAll('[data-photo-album]')].find(button => button.dataset.photoAlbum === key);
      target?.focus({preventScroll:true});
    });
  }
  function close() {
    if (window.history.state?.memoirPhotoAlbum?.projectId === currentProject) window.history.back();
    hide();
  }
  function updateDialog() {
    if (!dialog?.open || !currentKey) return;
    if (currentProject !== getProjectId()) { hide(); return; }
    const album = getAlbum(currentKey);
    if (!album) { hide(); return; }
    const content = dialog.querySelector('.map-photo-album-content');
    const scroll = content.scrollTop;
    const markup = renderAlbum(album);
    if (lastMarkup !== markup) {
      content.innerHTML = markup;
      lastMarkup = markup;
      bindAlbum(content, album);
      content.scrollTop = scroll;
    }
    dialog.querySelector('h2').textContent = album.place;
  }
  function open(key, source = null, restore = false) {
    if (!mobile()) return false;
    const album = getAlbum(key);
    if (!album) return false;
    trigger = source || document.activeElement;
    currentKey = key;
    currentProject = getProjectId();
    if (!dialog) {
      dialog = document.createElement('dialog');
      dialog.className = 'map-photo-album-viewer';
      dialog.setAttribute('aria-labelledby','map-photo-album-title');
      dialog.innerHTML = '<header><h2 id="map-photo-album-title"></h2><button type="button" data-close-photo-album>×</button></header><div class="map-photo-album-content"></div>';
      dialog.querySelector('[data-close-photo-album]').addEventListener('click',close);
      dialog.addEventListener('cancel',event => {event.preventDefault();close();});
      dialog.addEventListener('click',event => {if (event.target === dialog && event.clientX < dialog.getBoundingClientRect().left) close();});
      document.body.append(dialog);
    }
    dialog.querySelector('[data-close-photo-album]').setAttribute('aria-label',closeLabel());
    if (!restore) window.history.pushState({...window.history.state,memoirPhotoAlbum:{key,projectId:currentProject}},'',window.location.href);
    if (!dialog.open) dialog.showModal();
    updateDialog();
    dialog.querySelector('[data-close-photo-album]').focus({preventScroll:true});
    onOpen(album);
    return true;
  }
  window.addEventListener('popstate',() => {
    const saved = window.history.state?.memoirPhotoAlbum;
    if (saved?.projectId === getProjectId() && mobile()) open(saved.key,null,true);
    else hide();
  });
  window.matchMedia('(max-width: 760px)').addEventListener('change',event => {if (!event.matches && dialog?.open) close();});
  function sync(scene, focusedKey = null) {
    updateDialog();
    if (!scene) { layer = null; signature = null; return; }
    layer = scene.querySelector('.map-photo-album-layer');
    if (!layer) {
      layer = document.createElement('div');
      layer.className = 'map-photo-album-layer is-fallback';
      layer.addEventListener('click',event => {
        const button = event.target.closest('[data-photo-album], [data-photo-marker]');
        if (button) open(button.dataset.photoAlbum || button.dataset.photoMarker,button);
      });
      scene.append(layer);
    }
    const albums = getAlbums(scene);
    const next = JSON.stringify(albums);
    if (signature !== next || layer.dataset.signature !== next) {
      signature = next;
      layer.dataset.signature = next;
      layer.innerHTML = '<div class="map-album-overflow">' + albums.map(album => `<div class="map-album-anchor" data-album-key="${escape(album.key)}" data-album-pinned="${Boolean(album.pinned)}"><span class="map-album-stem" aria-hidden="true"></span>${albumStackMarkup(album,window.location.origin)}</div>`).join('') + '</div>'
        + albums.filter(album => album.pinned).map(album => `<button type="button" class="map-photo-marker" data-photo-marker="${escape(album.key)}" aria-label="${escape(album.label)}" aria-haspopup="dialog"></button>`).join('');
    }
    if (focusedKey && !dialog?.open) [...layer.querySelectorAll('[data-photo-album]')]
      .find(button => button.dataset.photoAlbum === focusedKey)?.focus({preventScroll:true});
  }
  function attach(viewer, cesium, pins) {
    removePostRender?.();
    const projectId = getProjectId();
    const points = pins.map(pin => ({...pin,position:cesium.Cartesian3.fromDegrees(pin.longitude,pin.latitude)}));
    const position = () => {
      if (!layer?.isConnected || viewer.isDestroyed() || getProjectId() !== projectId) return;
      const isMobile = mobile();
      for (const pin of pins) {
        const label = viewer.entities.getById(pin.key)?.label;
        if (label) label.show = !isMobile;
      }
      if (!isMobile) return;
      layer.classList.remove('is-fallback');
      const projected = points.map(pin => {
        const point = cesium.SceneTransforms.worldToWindowCoordinates(viewer.scene,pin.position);
        return {key:pin.key,x:point?.x,y:point?.y};
      });
      const hasUnpinnedAlbums = Boolean(layer.querySelector('[data-album-pinned="false"]'));
      const boxes = layoutMapAlbums(projected,layer.clientWidth,layer.clientHeight,hasUnpinnedAlbums ? 94 : 50);
      for (const marker of layer.querySelectorAll('[data-photo-marker]')) {
        const point = boxes.find(item => item.key === marker.dataset.photoMarker);
        marker.hidden = !point;
        if (point) { marker.style.left = `${point.x-22}px`; marker.style.top = `${point.y-22}px`; }
      }
      const overflow = layer.querySelector('.map-album-overflow');
      for (const anchor of layer.querySelectorAll('.map-album-anchor')) {
        if (anchor.dataset.albumPinned === 'false') {
          anchor.hidden = false;
          if (anchor.parentElement !== overflow) overflow.append(anchor);
          anchor.removeAttribute('style');
          continue;
        }
        const box = boxes.find(item => item.key === anchor.dataset.albumKey);
        anchor.hidden = !box;
        if (!box) continue;
        if (box.overflow) {
          if (anchor.parentElement !== overflow) overflow.append(anchor);
          anchor.removeAttribute('style');
          continue;
        }
        if (anchor.parentElement !== layer) layer.append(anchor);
        anchor.style.left = `${box.left}px`;
        anchor.style.top = `${box.top}px`;
        const dx = box.x - box.left - 37, dy = box.y - box.top - 74;
        const stem = anchor.querySelector('.map-album-stem');
        stem.style.height = `${Math.hypot(dx,dy)}px`;
        stem.style.transform = `rotate(${Math.atan2(-dx,dy)}rad)`;
      }
      overflow.hidden = !overflow.querySelector('.map-album-anchor:not([hidden])');
    };
    removePostRender = viewer.scene.postRender.addEventListener(position);
    position();
  }
  function dispose() { removePostRender?.(); removePostRender = null; layer = null; signature = null; }
  return {open,sync,attach,dispose};
}
