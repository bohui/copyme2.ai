'use strict';
const $ = id => document.getElementById(id);
const source = JSON.parse(document.getElementById('memoir-source').textContent);
source.chapters.forEach((chapter, index) => {
  const article = document.createElement('article'), heading = document.createElement('h3'), text = document.createElement('p');
  article.id = `memory-chapter-${index + 1}`;
  heading.textContent = chapter.title;
  text.textContent = chapter.text;
  article.append(heading, text); $('memory-passages').append(article);
});
const names = ['Left', 'Middle', 'Right'];
const layouts = [['clear', 'leak', 'surface'], ['leak', 'surface', 'clear']];
const zones = [...document.querySelectorAll('[data-zone]')];
function fresh(exercise) {
  return {exercise, selected: -1, observations: [0, 0, 0], mark: -1, glued: false, prep: 0, pressed: false, tested: false, result: '', message: 'Select a region, then observe. Compare two looks before choosing your mark.'};
}
function initial() { return {screen: 'intro', tests: 0, faults: [], ...fresh(0)}; }
let s = initial(), memoryOpener;
function available(action) {
  const open = !s.glued, chosen = s.selected >= 0;
  return s.screen === 'practice' && ({
    observe: open && chosen, mark: open && chosen && s.observations[s.selected] > 0,
    glue: open && s.mark >= 0, wait: s.glued && !s.pressed, press: s.glued && !s.pressed,
    test: s.pressed && !s.tested, retry: s.tested && s.result !== 'flat',
    continue: s.tested && s.result === 'flat'
  })[action];
}
function evidence(i) {
  const n = s.observations[i], kind = layouts[s.exercise][i];
  if (!n) return 'Not observed.';
  if (n === 1) return kind === 'clear' ? 'Look 1: no bubbles.' : 'Look 1: bubbles.';
  return kind === 'leak' ? 'Look 1: bubbles; look 2: bubbles return.' : kind === 'surface' ? 'Look 1: bubbles; look 2: clear.' : 'Both looks: no bubbles.';
}
function render() {
  const app = $('app'), leaking = s.tested && ['leak', 'both'].includes(s.result);
  app.dataset.screen = s.screen; app.dataset.exercise = s.exercise ? 'independent' : 'guided'; app.dataset.result = s.result || 'none';
  $('intro').hidden = s.screen !== 'intro'; $('workspace').hidden = s.screen !== 'practice'; $('ending').hidden = s.screen !== 'outcome';
  $('exercise-title').textContent = s.exercise ? '2 of 2 — Independent game tube' : '1 of 2 — Guided game tube';
  $('other-memories').hidden = s.exercise !== 1;
  $('objective').textContent = s.exercise ? 'A fresh game layout: investigate again rather than copying your first location.' : 'Find a continuing leak, then make a flat, sealed practice patch. Compare two observations before deciding.';
  $('test-count').textContent = `${s.tests} practice ${s.tests === 1 ? 'test' : 'tests'}`;
  zones.forEach((button, i) => {
    const kind = layouts[s.exercise][i], n = s.observations[i];
    button.disabled = s.glued || s.screen !== 'practice';
    button.setAttribute('aria-pressed', String(s.selected === i));
    button.classList.toggle('marked', s.mark === i && !s.pressed);
    button.classList.toggle('patched', s.mark === i && s.pressed);
    button.classList.toggle('curled', s.mark === i && s.tested && ['curl', 'both'].includes(s.result));
    button.classList.toggle('bubbling', (n > 0 && (kind === 'leak' || (kind === 'surface' && n === 1))) || (leaking && kind === 'leak'));
    const tag = s.mark === i ? (s.pressed ? ' · Patch pressed' : s.glued ? ' · Glue applied' : ' · Chalk mark') : '';
    $('evidence-' + button.dataset.zone).textContent = evidence(i) + tag + (leaking && kind === 'leak' ? ' · Test: bubbles remain' : '');
  });
  $('prep').value = s.prep;
  $('preparation').textContent = !s.glued ? 'Preparation — apply glue first.' : s.pressed ? `Preparation ${s.prep}/2 — locked when pressed.` : `Preparation ${s.prep}/2 — ${s.prep === 2 ? 'ready to press.' : 'not ready.'}`;
  ['observe', 'mark', 'glue', 'wait', 'press', 'test', 'retry', 'continue'].forEach(id => { $(id).disabled = !available(id); });
  $('retry').hidden = !available('retry'); $('continue').hidden = !available('continue');
  $('continue').textContent = s.exercise ? 'See practice ending' : 'Continue to independent tube';
  $('feedback').textContent = s.message;
  const faults = s.faults.map(f => f === 'curl' ? 'a curled edge' : 'a missed leak');
  $('outcome-stats').textContent = `${s.tests} practice tests across two tubes. ` + (faults.length ? `Faults encountered in game practice: ${faults.join(' and ')}.` : 'Both game patches were flat at their first test.');
}
function act(action) {
  if (action === 'memory-open') { memoryOpener = document.activeElement; $('memory').showModal(); $('memory-close').focus(); return; }
  if (action === 'memory-close') { $('memory').close(); return; }
  if (action === 'restart') {
    s = initial(); memoryOpener = null; if ($('memory').open) $('memory').close(); $('memory').scrollTop = 0;
    render(); $('start').focus(); return;
  }
  if (action === 'start' && s.screen === 'intro') { s = initial(); s.screen = 'practice'; render(); $('exercise-title').focus(); return; }
  if (!available(action)) return;
  let focus;
  switch (action) {
    case 'observe':
      s.observations[s.selected] = Math.min(2, s.observations[s.selected] + 1);
      s.message = `${names[s.selected]} — ${evidence(s.selected)} ` + (s.observations[s.selected] === 1 ? 'Observe again to compare.' : 'Two looks recorded.');
      break;
    case 'mark':
      s.mark = s.selected; s.message = `Chalk marks the ${names[s.mark].toLowerCase()} region. You can move the mark before applying glue.`; break;
    case 'glue':
      s.glued = true; s.selected = s.mark; s.message = 'Glue applied at the chalk mark. The location is locked. Use Wait to prepare the patch in game turns.'; focus = 'wait'; break;
    case 'wait':
      s.prep = Math.min(2, s.prep + 1);
      s.message = s.prep === 2 ? 'Preparation 2/2: ready in this game. Press, then Test.' : 'Preparation 1/2: not ready. Wait once more before pressing.'; break;
    case 'press':
      s.pressed = true; s.message = `Patch pressed with preparation ${s.prep}/2. Preparation is now locked. Test the patch.`; focus = 'test'; break;
    case 'test': {
      const leak = s.mark !== layouts[s.exercise].indexOf('leak'), curl = s.prep < 2;
      s.tested = true; s.tests++; s.result = leak ? (curl ? 'both' : 'leak') : (curl ? 'curl' : 'flat');
      if (leak && !s.faults.includes('leak')) s.faults.push('leak');
      if (curl && !s.faults.includes('curl')) s.faults.push('curl');
      s.message = s.result === 'flat' ? 'Flat and sealed: the patch covers the leak and its edge stays down in this game.' : [
        leak ? 'Bubbles remain: the patch missed the leak.' : '',
        curl ? 'The edge curls: you pressed before the game preparation reached 2/2.' : '',
        'Retry keeps your observations.'
      ].filter(Boolean).join(' ');
      focus = s.result === 'flat' ? 'continue' : 'retry'; break;
    }
    case 'retry': {
      const kept = s.observations; Object.assign(s, fresh(s.exercise), {observations: kept});
      s.message = 'New practice attempt. Your observations are kept; choose a region to mark again.'; focus = 'zone-left'; break;
    }
    case 'continue':
      if (s.exercise === 0) { Object.assign(s, fresh(1)); focus = 'exercise-title'; }
      else { s.screen = 'outcome'; focus = 'outcome-title'; }
      break;
  }
  render(); if (focus) $(focus).focus();
}
document.querySelectorAll('[data-action]').forEach(button => button.addEventListener('click', () => act(button.dataset.action)));
zones.forEach((button, i) => button.addEventListener('click', () => {
  if (s.screen !== 'practice' || s.glued) return;
  s.selected = i; s.message = `${names[i]} selected. ${evidence(i)}`; render();
}));
$('memory').addEventListener('close', () => { if (memoryOpener) memoryOpener.focus(); });
render();
