(() => {
'use strict';
const $ = s => document.querySelector(s);
const game = $('#game'), viewport = $('#viewport'), player = $('#player');
const interact = $('#interact'), left = $('#left'), right = $('#right');
const fullText = $('#full-text'), sourcePassages = $('#source-passages');
const dialogs = {memory: $('#dialogue'), source: $('#full-source'), ending: $('#ending')};
const names = {hub: 'Blue-gate junction', school: 'School memories', shed: 'Shed behind the house', outings: 'Outing memories', garden: 'Garden beside the blue gate'};
const groups = {school: ['first-day', 'reading', 'lunch', 'play'], shed: ['tyre'], outings: ['market', 'library', 'grandma']};
const memories = [
 ['arrival', 'Blue-gate house · moving in'],
 ['first-day', 'Footbridge and classroom · first day'],
 ['reading', 'Classroom · reading aloud'],
 ['lunch', 'Schoolyard · lunch wall'],
 ['tyre', 'Shed · tyre lessons'],
 ['market', 'Market · list and coins'],
 ['library', 'Public library · first card'],
 ['grandma', 'Grandma’s house · two nights'],
 ['play', 'School hall · tree and sun'],
 ['beans', 'Garden · beans beside the fence']
].map(([key, title], i) => ({key, title, source: 'C' + (i + 1), text: null}));
const accounts = new Map(memories.map(m => [m.key, m]));
const targets = [...document.querySelectorAll('.target')];
const labels = new Map(targets.map(t => [t, t.querySelector('span').textContent]));
const sceneTargets = Object.fromEntries(Object.keys(names).map(s => [s, [...$('#scene-' + s).querySelectorAll('.target')]]));
const visited = new Set(), keys = new Map(), pointers = new Map();
let scene = 'hub', x = 80, phase = 'exploring', facing = 'right';
let overlay = null, moving = false, last = 0, sourceOK = false;
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const say = (el, text) => { if (el.textContent !== text) el.textContent = text; };

try {
 const data = JSON.parse($('#memoir-source')?.textContent || 'null');
 if (!data || data.fictional !== true || !Array.isArray(data.chapters) || data.chapters.length !== 10) throw new Error();
 for (const m of memories) {
  const entry = data.chapters.find(c => c && c.id === m.source);
  if (!entry || typeof entry.text !== 'string' || !entry.text.trim()) throw new Error();
  m.text = entry.text;
 }
 sourceOK = true;
} catch (_) {
 sourceOK = false;
}
game.dataset.sourceReady = String(sourceOK);
sourcePassages.replaceChildren();
if (sourceOK) {
 for (const m of memories) {
  const entry = $('#source-entry').content.cloneNode(true);
  entry.querySelector('h3').textContent = m.title;
  entry.querySelector('.passage').textContent = m.text;
  sourcePassages.append(entry);
 }
} else {
 sourcePassages.textContent = 'The original passages are unavailable. The supplied fictional memoir is needed to read and credit memories.';
}

function direction() {
 const held = [...keys.values(), ...Array.from(pointers.values(), p => p.dir)];
 return Number(held.includes(1)) - Number(held.includes(-1));
}
function stop() {
 keys.clear();
 const held = [...pointers.entries()];
 pointers.clear();
 for (const [id, p] of held) {
  try { if (p.button.hasPointerCapture(id)) p.button.releasePointerCapture(id); } catch (_) {}
 }
 moving = false;
 player.dataset.moving = 'false';
 last = 0;
}
function settle() {
 if (!direction()) {
  moving = false;
  player.dataset.moving = 'false';
 }
}
function locked(t) {
 if (t.dataset.memory && !sourceOK) return true;
 if (Number(t.dataset.requiredCount || 0) > visited.size) return true;
 if (t.dataset.requiredMemory && !visited.has(t.dataset.requiredMemory)) return true;
 return t.dataset.action === 'next-morning' && phase !== 'exploring';
}
function nearest() {
 let result = null, distance = 97;
 for (const t of sceneTargets[scene]) {
  const d = Math.abs(Number(t.dataset.x) - x);
  if (d <= 96 && d < distance) { result = t; distance = d; }
 }
 return result;
}
function labelFor(t) {
 if (t.dataset.to === 'garden') {
  if (visited.size < 9) return 'Garden · explore 9 first';
  if (phase === 'morning') return 'Garden · opened seedling →';
  if (visited.has('beans')) return 'Garden · morning path →';
  return 'Garden →';
 }
 if (t.dataset.action === 'next-morning' && phase === 'morning') return 'Return to opened seedling ←';
 if (t.dataset.memory === 'beans' && phase === 'morning') return 'Opened seedling · drawing';
 const group = groups[t.dataset.to];
 if (group && group.every(k => visited.has(k))) return labels.get(t).replace(' →', '') + ' · explored →';
 return labels.get(t);
}
function render() {
 const px = Math.round(x), camera = Math.round(clamp(x - 240, 0, 1440));
 game.dataset.scene = scene;
 game.dataset.playerX = String(px);
 game.dataset.cameraX = String(camera);
 game.dataset.count = String(visited.size);
 game.dataset.phase = phase;
 game.dataset.overlay = overlay ? overlay.kind : 'none';
 game.style.setProperty('--player-x', String(px));
 game.style.setProperty('--camera-x', String(camera));
 player.dataset.moving = String(moving && !overlay && phase !== 'complete');
 player.dataset.facing = facing;
 say($('#scene-name'), scene === 'garden' && phase === 'morning' ? 'Garden · next-morning memory' : names[scene]);
 say($('#position'), 'Author ' + px + ' · Camera ' + camera);
 say($('#progress'), visited.size + ' / 10 memories explored' + (phase === 'morning' ? ' · Next-morning memory' : phase === 'complete' ? ' · Journey complete' : ''));
 const near = nearest();
 for (const t of targets) {
  t.dataset.visited = String(!!t.dataset.memory && visited.has(t.dataset.memory));
  t.dataset.locked = String(locked(t));
  t.dataset.nearby = String(t === near && !overlay && phase !== 'complete');
  const group = groups[t.dataset.to];
  const done = !!group && group.every(k => visited.has(k));
  t.dataset.complete = String(done);
  const span = t.querySelector('span');
  say(span, labelFor(t));
  span.style.opacity = done ? '0.75' : '';
 }
 left.disabled = right.disabled = !!overlay || phase === 'complete';
 interact.disabled = !near || locked(near) || !!overlay || phase === 'complete';
 interact.dataset.target = near ? (near.dataset.memory || near.dataset.to || near.dataset.action || '') : '';
 let action = 'Approach a marker', prompt = 'Walk towards a memory marker or signpost.';
 if (near) {
  if (locked(near)) {
   action = 'Path locked';
   if (near.dataset.memory && !sourceOK) prompt = 'Original passages unavailable; memory credit is disabled.';
   else if (near.dataset.to === 'garden') prompt = 'Garden locked: explore ' + (9 - visited.size) + ' more memories. This is exploration progress, not a timeline.';
   else if (phase === 'morning') prompt = 'Walk left to the opened seedling and its drawing memory.';
   else prompt = 'Read the beans memory before taking the next-morning path.';
  } else {
   const key = near.dataset.memory;
   action = key ? (key === 'beans' && phase === 'morning' ? 'See the drawing' : visited.has(key) ? 'Read again' : 'Read memory') : near.dataset.action === 'next-morning' ? 'Next morning' : 'Travel';
   prompt = 'Nearby: ' + labelFor(near) + '.';
   if (key && visited.has(key) && phase !== 'morning') prompt += ' Explored; revisiting adds no credit.';
  }
 }
 say(interact, action);
 say($('#nearby'), phase === 'complete' ? 'Journey complete — The Blue Gate' : prompt);
}
function focus(el) {
 const target = el && el.isConnected && !el.disabled && el !== document.body ? el : viewport;
 target.focus({preventScroll: true});
}
function openDialog(kind, memory = null) {
 if (overlay) return;
 const node = dialogs[kind];
 overlay = {kind, node, memory, restore: document.activeElement};
 stop();
 if (memory) {
  $('#dialogue-title').textContent = memory.title;
  $('#memory-text').textContent = memory.text;
 }
 render();
 node.showModal();
 node.scrollTop = 0;
 node.querySelectorAll('.scroll').forEach(el => { el.scrollTop = 0; });
 focus(kind === 'ending' ? $('#restart') : kind === 'memory' ? $('#close') : $('#source-close'));
}
function closeDialog() {
 const old = overlay;
 if (!old || old.kind === 'ending') return;
 overlay = null;
 stop();
 if (old.node.open) old.node.close();
 if (old.kind === 'memory' && sourceOK && old.memory) visited.add(old.memory.key);
 render();
 focus(old.restore);
}
function interactNow() {
 if (overlay || phase === 'complete') return;
 const t = nearest();
 if (!t || locked(t)) return;
 stop();
 if (t.dataset.memory) {
  if (t.dataset.memory === 'beans' && phase === 'morning' && visited.size === 10) {
   phase = 'complete';
   openDialog('ending');
  } else {
   openDialog('memory', accounts.get(t.dataset.memory));
  }
 } else if (t.dataset.action === 'next-morning') {
  phase = 'morning';
  scene = 'garden';
  x = 80;
  facing = 'right';
  render();
  focus(viewport);
 } else if (names[t.dataset.to]) {
  scene = t.dataset.to;
  x = clamp(Number(t.dataset.returnX || 80), 80, 1840);
  render();
  focus(viewport);
 }
}
function reset() {
 overlay = null;
 stop();
 for (const node of Object.values(dialogs)) {
  if (node.open) node.close();
  node.scrollTop = 0;
  node.querySelectorAll('.scroll').forEach(el => { el.scrollTop = 0; });
 }
 visited.clear();
 scene = 'hub';
 x = 80;
 phase = 'exploring';
 facing = 'right';
 $('#dialogue-title').textContent = 'Memory';
 $('#memory-text').textContent = 'Approach a memory to read the original account.';
 render();
 focus(viewport);
 window.scrollTo(0, 0);
}

interact.addEventListener('click', interactNow);
fullText.addEventListener('click', () => openDialog('source'));
$('#close').addEventListener('click', () => { if (overlay?.kind === 'memory') closeDialog(); });
$('#source-close').addEventListener('click', () => { if (overlay?.kind === 'source') closeDialog(); });
$('#restart').addEventListener('click', reset);
for (const node of Object.values(dialogs)) {
 node.addEventListener('cancel', e => {
  e.preventDefault();
  if (overlay?.node === node) closeDialog();
 });
 node.addEventListener('close', () => {
  if (overlay?.node !== node || node.open) return;
  if (overlay.kind === 'ending') {
   node.showModal();
   focus($('#restart'));
  } else closeDialog();
 });
}

document.addEventListener('keydown', e => {
 const k = e.key.toLowerCase();
 if (k === 'escape' && overlay) {
  e.preventDefault();
  closeDialog();
  return;
 }
 if (overlay) {
  if (e.repeat && (k === 'enter' || k === ' ')) e.preventDefault();
  return;
 }
 if (e.ctrlKey || e.altKey || e.metaKey) return;
 const movementButton = e.target.closest?.('[data-action="move"]');
 const buttonDirection = movementButton && (k === 'enter' || k === ' ') ? Number(movementButton.dataset.direction) : 0;
 const d = buttonDirection || (k === 'arrowleft' || k === 'a' ? -1 : k === 'arrowright' || k === 'd' ? 1 : 0);
 if (d) {
  e.preventDefault();
  if (!e.repeat && phase !== 'complete') keys.set(e.code || k, d);
  return;
 }
 if (k === 'e' || k === 'enter') {
  if (k === 'enter' && e.target === fullText) {
   if (e.repeat) e.preventDefault();
   return;
  }
  e.preventDefault();
  if (!e.repeat) interactNow();
 }
});
document.addEventListener('keyup', e => {
 keys.delete(e.code || e.key.toLowerCase());
 settle();
});
for (const button of [left, right]) {
 button.addEventListener('pointerdown', e => {
  if (e.button !== 0 || overlay || phase === 'complete') return;
  e.preventDefault();
  pointers.set(e.pointerId, {button, dir: Number(button.dataset.direction)});
  focus(button);
  try { button.setPointerCapture(e.pointerId); } catch (_) {}
 }, {passive: false});
 button.addEventListener('lostpointercapture', e => releasePointer(e.pointerId));
 button.addEventListener('contextmenu', e => e.preventDefault());
}
function releasePointer(id) {
 const p = pointers.get(id);
 if (!p) return;
 pointers.delete(id);
 try { if (p.button.hasPointerCapture(id)) p.button.releasePointerCapture(id); } catch (_) {}
 settle();
}
document.addEventListener('pointerup', e => releasePointer(e.pointerId), true);
document.addEventListener('pointercancel', e => releasePointer(e.pointerId), true);
window.addEventListener('blur', stop);
window.addEventListener('pagehide', stop);
document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); });

function tick(now) {
 if (!last) last = now;
 const dt = clamp((now - last) / 1000, 0, 0.05);
 last = now;
 const d = overlay || phase === 'complete' ? 0 : direction();
 const before = x, oldFacing = facing;
 if (d) {
  x = clamp(x + d * 400 * dt, 80, 1840);
  facing = d < 0 ? 'left' : 'right';
 }
 const changed = x !== before;
 if (changed || moving !== changed || facing !== oldFacing) {
  moving = changed;
  render();
 }
 requestAnimationFrame(tick);
}
say($('.layout-note'), 'Explore nine memories to open the garden. After reading the beans memory, walk to its next-morning path. Walking changes exploration, not history.');
reset();
requestAnimationFrame(tick);
})();
