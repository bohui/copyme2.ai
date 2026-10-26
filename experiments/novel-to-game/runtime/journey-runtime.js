(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const game = $('game'), player = $('player'), forward = $('right'), read = $('interact');
  const plan = JSON.parse($('memoir-journey').textContent);
  const source = JSON.parse($('memoir-source').textContent);
  const chapters = new Map(source.chapters.map(c => [c.id, c]));
  const visited = new Set(), held = new Set(), panels = [], markers = [];
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const ns = 'http://www.w3.org/2000/svg';
  const clamp = (n, a, b) => Math.max(a, Math.min(b, n));
  let x = 80, last = null, modal = null, current = null, focusBack = null, finished = false;
  let musicEnabled = false, audioPending = false;
  const music = $('memory-music'), cue = $('memory-cue');
  music.src = plan.stock_url + 'blue-gate-theme.mp3';
  cue.src = plan.stock_url + 'memory-cue.mp3';
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
  plan.segments.forEach(segment => {
    const panel = document.createElement('div');
    panel.className = 'scene-panel'; panel.dataset.segment = segment.id;
    const art = plan.illustrations.find(a => a.scenes.includes(segment.scene));
    if (art) {
      const i = art.scenes.indexOf(segment.scene), w = art.width / art.columns, h = art.height / art.rows;
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
  function stopMoving() { held.clear(); last = null; player.dataset.moving = 'false'; game.dataset.moving = 'false'; }
  function render() {
    const segmentIndex = Math.max(0, plan.segments.findLastIndex(s => x >= s.start));
    const segment = plan.segments[segmentIndex], total = plan.segments.at(-1).end;
    const camera = clamp(x - 240, 0, total - 640), stop = nextStop();
    game.style.setProperty('--x', String(x)); game.style.setProperty('--camera', String(camera));
    game.dataset.x = String(Math.round(x)); game.dataset.camera = String(Math.round(camera));
    game.dataset.scene = segment.scene; game.dataset.segment = segment.id;
    game.dataset.visited = String(visited.size); game.dataset.phase = finished ? 'complete' : modal ? 'reading' : 'explore';
    game.dataset.next = stop ? stop.chapter : 'none';
    $('scene-name').textContent = segment.title;
    $('stage-label').textContent = segment.age_label + (segment.profession ? ' · ' + segment.profession : '');
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
      const s = plan.segments[i];
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
    read.disabled = !near || !!modal || finished;
    forward.disabled = !!modal || finished;
    $('full-text').disabled = !!modal;
    $('ending').hidden = !finished;
    $('nearby').textContent = modal ? 'Reading pauses the walk. Continue whenever you are ready.' : finished ? 'Every memory visited. Your journey is complete.' : near ? 'You have reached a memory. Read it, then continue forward.' : 'Keep walking forward. The next memory is waiting along the path.';
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
    if (visited.size === plan.stops.length) finished = true;
    stopMoving(); dialog.close(); render();
    const target = finished ? $('restart') : focusBack && !focusBack.disabled ? focusBack : game;
    target.focus({preventScroll:true}); focusBack = null;
  }
  function interact() {
    const stop = nextStop();
    if (modal || finished || !stop || Math.abs(stop.x - x) > 65) return;
    current = stop.chapter;
    $('memory-title').textContent = chapters.get(current).title;
    $('passage').textContent = chapters.get(current).text;
    $('memory-period').textContent = $('stage-label').textContent;
    open($('memory-dialog'));
    if (musicEnabled) { cue.currentTime = 0; cue.play().catch(() => {}); }
  }
  function move(distance) {
    if (modal || finished || distance <= 0) return;
    const target = nextStop();
    const next = Math.min(x + distance, target ? target.x : x);
    const moving = next > x; x = next;
    player.dataset.moving = String(moving); game.dataset.moving = String(moving); render();
  }
  function reset() {
    if (modal) { const d = modal; modal = null; d.close(); }
    stopMoving(); visited.clear(); x = 80; current = null; finished = false; focusBack = null;
    $('passage').textContent = ''; render(); game.focus({preventScroll:true});
  }
  document.addEventListener('keydown', event => {
    if (event.ctrlKey || event.metaKey || event.altKey || event.defaultPrevented) return;
    if (modal) { if (event.key === 'Escape') { event.preventDefault(); close(); } return; }
    if (event.key === 'ArrowRight' || event.key.toLowerCase() === 'd' || event.target === forward && ['Enter',' '].includes(event.key)) {
      event.preventDefault(); if (!event.repeat) held.add(event.code || event.key);
    } else if (event.key.toLowerCase() === 'e') { event.preventDefault(); if (!event.repeat) interact(); }
  });
  document.addEventListener('keyup', event => { held.delete(event.code || event.key); if (!held.size) stopMoving(); });
  forward.addEventListener('pointerdown', event => {
    if (modal || finished || event.pointerType === 'mouse' && event.button !== 0) return;
    event.preventDefault(); forward.focus(); held.add('pointer-' + event.pointerId); forward.setPointerCapture(event.pointerId);
  });
  const release = event => { held.delete('pointer-' + event.pointerId); if (!held.size) stopMoving(); };
  window.addEventListener('pointerup', release, true); window.addEventListener('pointercancel', release, true);
  forward.addEventListener('lostpointercapture', release);
  forward.addEventListener('contextmenu', e => e.preventDefault());
  forward.addEventListener('click', e => { e.preventDefault(); if (e.detail === 0) move(48); });
  read.addEventListener('click', interact);
  $('continue').addEventListener('click', close); $('source-close').addEventListener('click', close);
  $('full-text').addEventListener('click', () => open($('source-dialog')));
  $('restart').addEventListener('click', reset);
  for (const dialog of [$('memory-dialog'), $('source-dialog')]) {
    dialog.addEventListener('cancel', e => { e.preventDefault(); close(); });
    dialog.addEventListener('close', () => { if (modal === dialog) close(); });
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
    if (held.size && !document.hidden) move(560 * dt);
    requestAnimationFrame(frame);
  }
  reset(); labelAudio(); requestAnimationFrame(frame);
})();
