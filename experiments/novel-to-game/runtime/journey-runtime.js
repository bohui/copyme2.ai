(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const game = $('game'), player = $('player'), forward = $('right'), backward = $('left'), read = $('interact');
  const plan = JSON.parse($('memoir-journey').textContent);
  const source = JSON.parse($('memoir-source').textContent);
  const chapters = new Map(source.chapters.map(c => [c.id, c]));
  const visited = new Set(), held = new Map(), panels = [], markers = [];
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const ns = 'http://www.w3.org/2000/svg';
  const clamp = (n, a, b) => Math.max(a, Math.min(b, n));
  let x = 80, last = null, modal = null, current = null, focusBack = null, finished = false;
  let musicEnabled = false, audioPending = false;
  const music = $('memory-music'), cue = $('memory-cue');
  music.src = plan.audio?.theme || plan.stock_url + 'blue-gate-theme.mp3';
  cue.src = plan.audio?.cue || plan.stock_url + 'memory-cue.mp3';
  music.volume = .22; cue.volume = .18;
  game.style.setProperty('--length', String(plan.segments.at(-1).end));
  game.dataset.art = plan.illustrations.length ? 'illustrated' : 'whitebox';
  $('title').textContent = source.title + (source.fictional ? ' — fictional example' : '');
  $('route-note').textContent = plan.order_note + ' Places are illustrated memory settings, not a street map.';
  $('ending-title').textContent = 'Journey complete — ' + plan.stops.length + '/' + plan.stops.length + ' memories';

  const defs = document.createElementNS(ns, 'svg');
  defs.setAttribute('width', '0'); defs.setAttribute('height', '0'); defs.setAttribute('aria-hidden', 'true');
  defs.style.position = 'absolute';
  const definitions = document.createElementNS(ns, 'defs'); defs.append(definitions);
  plan.illustrations.forEach((art, i) => {
    const image = document.createElementNS(ns, 'image');
    image.id = 'scene-atlas-' + i; image.setAttribute('href', art.url);
    image.setAttribute('width', art.width); image.setAttribute('height', art.height); definitions.append(image);
  });
  $('scenery').append(defs);
  const panRanges = [];
  let panRun = null;
  // Consecutive views of one illustration share its full pan, including at a memory boundary.
  plan.segments.forEach(segment => {
    const panel = document.createElement('div');
    panel.className = 'scene-panel'; panel.dataset.segment = segment.id;
    const art = plan.illustrations.find(a => a.scenes.includes(segment.scene));
    const cell = art && (art.cells?.[segment.scene] ?? art.scenes.indexOf(segment.scene));
    const key = JSON.stringify(art ? [art.url, cell] : ['placeholder', segment.scene]);
    if (!panRun || panRun.key !== key) panRun = {key, start: segment.start, end: segment.end};
    else panRun.end = segment.end;
    panRanges.push(panRun);
    if (art) {
      const i = cell, w = art.width / art.columns, h = art.height / art.rows;
      const svg = document.createElementNS(ns, 'svg'), use = document.createElementNS(ns, 'use');
      svg.setAttribute('viewBox', '0 0 ' + w + ' ' + h);
      svg.setAttribute('preserveAspectRatio', 'xMidYMax slice');
      use.setAttribute('href', '#scene-atlas-' + plan.illustrations.indexOf(art));
      use.setAttribute('x', -(i % art.columns) * w); use.setAttribute('y', -Math.floor(i / art.columns) * h);
      svg.append(use); panel.append(svg);
    }
    $('scenery').append(panel); panels.push(panel);
  });
  plan.stops.forEach(stop => {
    const chapter = chapters.get(stop.chapter);
    const marker = document.createElement('div'), label = document.createElement('span');
    marker.className = 'memory-marker'; marker.dataset.chapter = stop.chapter;
    marker.style.left = 'calc(' + stop.x + '*var(--u))'; label.textContent = chapter.title;
    marker.append(label); $('markers').append(marker); markers.push(marker);
    const heading = document.createElement('h3'), passage = document.createElement('p');
    heading.textContent = chapter.title; passage.textContent = chapter.text;
    $('source-passages').append(heading, passage);
  });

  const nextStop = () => plan.stops.find(s => !visited.has(s.chapter));
  const nearestStop = () => plan.stops.reduce((near, stop) => Math.abs(stop.x - x) <= 65 && (!near || Math.abs(stop.x - x) < Math.abs(near.x - x)) ? stop : near, null);
  const direction = () => Number([...held.values()].includes(1)) - Number([...held.values()].includes(-1));
  function stopMoving() { held.clear(); last = null; player.dataset.moving = 'false'; game.dataset.moving = 'false'; }
  function render() {
    const segmentIndex = Math.max(0, plan.segments.findLastIndex(s => x >= s.start));
    const segment = plan.segments[segmentIndex], total = plan.segments.at(-1).end;
    const camera = clamp(x - 240, 0, total - 640), stop = nearestStop();
    game.style.setProperty('--x', String(x)); game.style.setProperty('--camera', String(camera));
    game.dataset.x = String(Math.round(x)); game.dataset.camera = String(Math.round(camera));
    game.dataset.scene = segment.scene; game.dataset.segment = segment.id;
    game.dataset.visited = String(visited.size); game.dataset.phase = modal ? 'reading' : finished ? 'complete' : 'explore';
    game.dataset.next = nextStop()?.chapter || 'none'; game.dataset.near = stop ? stop.chapter : 'none';
    $('scene-name').textContent = segment.title;
    $('stage-label').textContent = (stop?.age_label || segment.age_label) + (segment.profession ? ' · ' + segment.profession : '');
    player.dataset.avatar = segment.avatar;
    $('progress').textContent = 'Memories ' + visited.size + '/' + plan.stops.length;
    let blend = null;
    if (!reduced.matches) {
      for (let i = 1; i < plan.segments.length; i++) {
        const edge = plan.segments[i].start;
        if (x >= edge - plan.blend / 2 && x <= edge + plan.blend / 2) {
          blend = { previous: i - 1, next: i, mix: (x - edge + plan.blend / 2) / plan.blend }; break;
        }
      }
    }
    panels.forEach((panel, i) => {
      const s = panRanges[i];
      const progress = clamp((x - s.start) / (s.end - s.start), 0, 1);
      const opacity = blend ? i === blend.previous ? 1 : i === blend.next ? blend.mix : 0 : i === segmentIndex ? 1 : 0;
      panel.style.opacity = String(opacity);
      panel.style.transform = reduced.matches ? 'none' : 'translateX(' + (-progress * 37.5) + '%)';
      panel.dataset.visible = String(opacity > 0);
    });
    game.dataset.transition = blend ? 'blending' : 'steady';
    game.dataset.blend = blend ? blend.mix.toFixed(3) : '0';
    markers.forEach((marker, i) => {
      marker.dataset.visited = String(visited.has(plan.stops[i].chapter));
      marker.dataset.nearby = String(stop === plan.stops[i] && Math.abs(stop.x - x) <= 65);
    });
    const near = stop && Math.abs(stop.x - x) <= 65;
    read.disabled = !near || !!modal;
    read.textContent = stop && visited.has(stop.chapter) ? 'Read again' : 'Read memory';
    forward.disabled = backward.disabled = !!modal;
    $('full-text').disabled = !!modal;
    $('ending').hidden = !finished;
    $('nearby').textContent = modal ? 'Reading pauses the walk. Continue whenever you are ready.' : near ? visited.has(stop.chapter) ? 'You can read this memory again, or keep exploring in either direction.' : 'You have reached a memory. Read it whenever you like.' : finished ? 'Every memory visited. Keep exploring in either direction or restart your journey.' : 'Walk in either direction and approach a memory marker to read.';
  }
  function open(dialog) {
    if (modal) return;
    stopMoving(); focusBack = document.activeElement; modal = dialog;
    dialog.showModal(); dialog.querySelector('.scroll').scrollTop = 0;
    render(); dialog.querySelector('h2').focus({preventScroll:true});
  }
  function close() {
    if (!modal) return;
    const dialog = modal; modal = null;
    if (dialog === $('memory-dialog') && current) { visited.add(current); current = null; }
    const justCompleted = !finished && visited.size === plan.stops.length;
    if (justCompleted) finished = true;
    stopMoving(); dialog.close(); render();
    const target = justCompleted ? $('restart') : focusBack && !focusBack.disabled ? focusBack : game;
    target.focus({preventScroll:true}); focusBack = null;
  }
  function interact() {
    const stop = nearestStop();
    if (modal || !stop) return;
    current = stop.chapter;
    $('memory-title').textContent = chapters.get(current).title;
    $('passage').textContent = chapters.get(current).text;
    $('memory-period').textContent = $('stage-label').textContent;
    open($('memory-dialog'));
    if (musicEnabled) { cue.currentTime = 0; cue.play().catch(() => {}); }
  }
  function move(distance) {
    if (modal || distance === 0) { player.dataset.moving = game.dataset.moving = 'false'; return; }
    const next = clamp(x + distance, 40, plan.segments.at(-1).end - 40);
    const moving = next !== x; x = next;
    player.dataset.facing = distance < 0 ? 'left' : 'right';
    player.dataset.moving = String(moving); game.dataset.moving = String(moving); render();
  }
  function reset() {
    if (modal) { const d = modal; modal = null; d.close(); }
    stopMoving(); visited.clear(); x = 80; current = null; finished = false; focusBack = null;
    player.dataset.facing = 'right';
    $('passage').textContent = ''; render(); game.focus({preventScroll:true});
  }
  document.addEventListener('keydown', event => {
    if (event.ctrlKey || event.metaKey || event.altKey || event.defaultPrevented) return;
    if (modal) { if (event.key === 'Escape') { event.preventDefault(); close(); } return; }
    const button = event.target instanceof Element ? event.target.closest('button[data-move]') : null;
    let dir = ['ArrowLeft','a','A'].includes(event.key) ? -1 : ['ArrowRight','d','D'].includes(event.key) ? 1 : 0;
    if (button && ['Enter',' '].includes(event.key)) dir = Number(button.dataset.move);
    if (dir) {
      event.preventDefault(); if (!event.repeat) held.set(event.code || event.key, dir);
    } else if (event.key.toLowerCase() === 'e') { event.preventDefault(); if (!event.repeat) interact(); }
  });
  document.addEventListener('keyup', event => { held.delete(event.code || event.key); if (!held.size) stopMoving(); });
  for (const button of [backward, forward]) {
    button.addEventListener('pointerdown', event => {
      if (modal || event.pointerType === 'mouse' && event.button !== 0) return;
      event.preventDefault(); button.focus(); held.set('pointer-' + event.pointerId, Number(button.dataset.move)); button.setPointerCapture(event.pointerId);
    });
    button.addEventListener('lostpointercapture', event => { held.delete('pointer-' + event.pointerId); if (!held.size) stopMoving(); });
    button.addEventListener('contextmenu', e => e.preventDefault());
    button.addEventListener('click', e => { e.preventDefault(); if (e.detail === 0) move(Number(button.dataset.move) * 48); });
  }
  const release = event => { held.delete('pointer-' + event.pointerId); if (!held.size) stopMoving(); };
  window.addEventListener('pointerup', release, true); window.addEventListener('pointercancel', release, true);
  read.addEventListener('click', interact);
  $('continue').addEventListener('click', close); $('source-close').addEventListener('click', close);
  $('full-text').addEventListener('click', () => open($('source-dialog')));
  $('restart').addEventListener('click', reset);
  for (const dialog of [$('memory-dialog'), $('source-dialog')]) {
    dialog.addEventListener('cancel', e => { e.preventDefault(); close(); });
    dialog.addEventListener('close', () => { if (modal === dialog && !dialog.open) close(); });
  }
  const labelAudio = () => document.querySelectorAll('[data-audio-toggle]').forEach(b => {
    b.textContent = musicEnabled ? 'Music on' : 'Music off'; b.setAttribute('aria-pressed', String(musicEnabled));
  });
  document.querySelectorAll('[data-audio-toggle]').forEach(button => button.addEventListener('click', async () => {
    if (audioPending) return;
    if (musicEnabled) { musicEnabled = false; music.pause(); cue.pause(); labelAudio(); return; }
    audioPending = true;
    try { await music.play(); musicEnabled = true; } catch (_) { button.textContent = 'Music unavailable'; }
    finally { audioPending = false; labelAudio(); }
  }));
  window.addEventListener('blur', stopMoving);
  window.addEventListener('pagehide', () => { stopMoving(); music.pause(); cue.pause(); });
  document.addEventListener('visibilitychange', () => {
    stopMoving(); if (document.hidden) { music.pause(); cue.pause(); }
    else if (musicEnabled) music.play().catch(() => { musicEnabled = false; labelAudio(); });
  });
  reduced.addEventListener('change', render);
  function frame(now) {
    const dt = last === null ? 0 : Math.min((now - last) / 1000, .05); last = now;
    if (held.size && !document.hidden) move(direction() * 560 * dt);
    requestAnimationFrame(frame);
  }
  reset(); labelAudio(); requestAnimationFrame(frame);
})();
