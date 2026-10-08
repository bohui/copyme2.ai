import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {createConversationScroll} from '../../apps/web/client/memoir/conversation-scroll.mjs';

const source = fs.readFileSync(new URL('../../apps/web/client/memoir/client.js', import.meta.url), 'utf8');
const selectLifeStage = source.match(/function selectLifeStage\([^]*?\n\}/)[0];

test('life-stage navigation pauses auto-follow before workspace reflow', () => {
  let following = true;
  let scrollTop = 0;
  const calls = [];
  const context = vm.createContext({
    state: {lifeStage: 'childhood', selectedPlace: 'saved-place'},
    LIFE_STAGES: [{id: 'childhood'}, {id: 'toddler'}],
    conversationScroll: {pause: () => { following = false; calls.push('pause'); }},
    // renderStory follows the new bottom unless the reading controller was
    // paused. Model the observed 0 -> 642 reflow without a user scroll event.
    render: () => { if (following) scrollTop = 642; calls.push('render'); },
    document: {querySelector: () => ({focus: options => {
      assert.equal(options.preventScroll, true); calls.push('focus');
    }})},
  });
  vm.runInContext(selectLifeStage, context);
  context.selectLifeStage('toddler', true);
  assert.equal(scrollTop, 0);
  assert.equal(context.state.lifeStage, 'toddler');
  assert.equal(context.state.selectedPlace, null);
  assert.deepEqual(calls, ['pause', 'render', 'focus']);
});

test('an invalid life stage does not change following or render the workspace', () => {
  const context = vm.createContext({
    state: {lifeStage: 'childhood', selectedPlace: 'saved-place'},
    LIFE_STAGES: [{id: 'childhood'}],
    conversationScroll: {pause: () => assert.fail('invalid navigation must not pause')},
    render: () => assert.fail('invalid navigation must not render'),
  });
  vm.runInContext(selectLifeStage, context);
  context.selectLifeStage('invalid');
  assert.equal(context.state.lifeStage, 'childhood');
  assert.equal(context.state.selectedPlace, 'saved-place');
});

test('real controller preserves queued reflow and streaming position, then resumes on intent', t => {
  const names = ['requestAnimationFrame', 'cancelAnimationFrame', 'ResizeObserver', 'MutationObserver'];
  const originals = Object.fromEntries(names.map(name => [name, globalThis[name]]));
  t.after(() => names.forEach(name => {
    if (originals[name] === undefined) delete globalThis[name];
    else globalThis[name] = originals[name];
  }));
  const frames = new Map();
  let nextFrame = 1;
  globalThis.requestAnimationFrame = callback => {
    const id = nextFrame++;
    frames.set(id, callback);
    return id;
  };
  globalThis.cancelAnimationFrame = id => frames.delete(id);
  const resizers = [], mutators = [];
  globalThis.ResizeObserver = class {
    constructor(callback) { this.callback = callback; resizers.push(this); }
    observe() {}
    disconnect() {}
  };
  globalThis.MutationObserver = class {
    constructor(callback) { this.callback = callback; mutators.push(this); }
    observe() {}
    disconnect() {}
  };
  const flush = () => {
    while (frames.size) {
      const callbacks = [...frames.values()];
      frames.clear();
      for (const callback of callbacks) callback();
    }
  };
  const node = height => {
    let top = 0;
    return {
      scrollHeight: height, clientHeight: 400, children: [], events: {},
      get scrollTop() { return top; },
      set scrollTop(value) { top = Math.max(0, Math.min(value, this.scrollHeight - this.clientHeight)); },
      getBoundingClientRect: () => ({right: 800}),
      addEventListener(name, callback) { this.events[name] = callback; },
      removeEventListener(name) { delete this.events[name]; },
    };
  };
  const controller = createConversationScroll();
  let current = node(400);
  controller.mount(current);
  flush();
  let renders = 0;
  const context = vm.createContext({
    state: {lifeStage: 'childhood', selectedPlace: 'saved-place'},
    LIFE_STAGES: [{id: 'childhood'}, {id: 'toddler'}],
    conversationScroll: controller,
    document: {querySelector: () => ({focus() {}})},
    render: () => {
      renders++;
      const previous = current.scrollTop;
      const following = controller.following();
      current = node(1042);
      current.scrollTop = following ? current.scrollHeight : previous;
      if (following) controller.follow();
      else controller.pause();
      controller.mount(current);
    },
  });
  vm.runInContext(selectLifeStage, context);
  controller.refresh();
  context.selectLifeStage('toddler', true);
  flush();
  assert.equal(current.scrollTop, 0);
  assert.equal(controller.following(), false);
  current.scrollHeight = 1500;
  mutators.at(-1).callback();
  resizers.at(-1).callback();
  controller.refresh();
  flush();
  assert.equal(current.scrollTop, 0);
  current.scrollTop = 1100;
  current.events.scroll();
  assert.equal(controller.following(), true);
  current.scrollHeight = 1900;
  controller.refresh();
  flush();
  assert.equal(current.scrollTop, 1500);
  context.selectLifeStage('invalid');
  assert.equal(renders, 1);
  assert.equal(controller.following(), true);
  context.selectLifeStage('childhood');
  flush();
  assert.equal(controller.following(), false);
  controller.follow();
  current.scrollHeight = 2100;
  controller.refresh();
  flush();
  assert.equal(current.scrollTop, 1700);
});
