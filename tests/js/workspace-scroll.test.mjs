import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

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
