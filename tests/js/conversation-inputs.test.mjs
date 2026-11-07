import test from 'node:test';
import assert from 'node:assert/strict';
import {createConversationInputs} from '../../apps/web/client/memoir/conversation-inputs.mjs';

const tick = () => new Promise(resolve => setImmediate(resolve));
function fixture(run) {
  const owner = {ownerId:'narrator', projectId:'memoir', generation:0};
  const values = new Map(), loading = [];
  const options = {scope:() => ({...owner}), current:value => JSON.stringify(value) === JSON.stringify(owner),
    storage:{getItem:key => values.get(key), setItem:(key,value) => values.set(key,value), removeItem:key => values.delete(key)},
    busy:value => loading.push(value), run};
  return {owner, values, loading, options, queue:createConversationInputs(options)};
}

test('queued text sends one batch and keeps every original through an uncertain retry', async () => {
  const calls = [];
  const h = fixture(async (input, delivery) => {
    calls.push([...delivery.priorInputs, input].map(item => item.id));
    if (calls.length === 1) return {failed:true};
    delivery.accepted();
    assert.equal(delivery.controller.signal.aborted, false);
    delivery.saved();
  });
  const finished = h.queue.enqueue({id:'one', text:'We moved in 1985.', batchable:true});
  h.queue.enqueue({id:'two', text:'Actually, it was 1986.', batchable:true});
  await finished;
  assert.deepEqual(h.queue.inputs().map(input => input.id), ['one', 'two']);
  await h.queue.restore();
  assert.deepEqual(calls, [['one', 'two'], ['one', 'two']]);
  assert.equal(h.queue.pending(), false);
});

test('rapid inputs stay separate and only cancel after each source is accepted', async () => {
  const calls = [], saved = [], controls = [];
  const h = fixture(async (input, delivery) => {
    calls.push(input.id); controls.push(delivery);
    await new Promise(resolve => {
      delivery.controller.signal.addEventListener('abort', resolve, {once:true});
      delivery.finish = resolve;
    });
  });
  const finished = h.queue.enqueue({id:'one', text:'My first part'});
  await tick();
  h.queue.enqueue({id:'two', text:'Actually, it was 1986.'});
  h.queue.enqueue({id:'three', text:'And my sister was there.'});
  assert.deepEqual(calls, ['one']);
  assert.equal(controls[0].controller.signal.aborted, false);
  saved.push('one'); controls[0].accepted();
  await tick();
  assert.deepEqual(calls, ['one', 'two']);
  saved.push('two'); controls[1].accepted();
  await tick();
  assert.deepEqual(calls, ['one', 'two', 'three']);
  saved.push('three'); controls[2].accepted();
  assert.equal(controls[2].controller.signal.aborted, false);
  controls[2].saved(); controls[2].finish();
  await finished;
  assert.deepEqual(saved, calls);
  assert.deepEqual(h.loading, [true, false]);
  assert.equal(h.values.size, 0);
  assert.equal(h.queue.pending(), false);
});

test('a committed reply finishes before the next input and is never retracted', async () => {
  let finish, first;
  const h = fixture(async (input, delivery) => {
    delivery.accepted(); delivery.saved();
    if (input.id === 'one') {first = delivery; await new Promise(resolve => {finish = resolve;});}
  });
  const finished = h.queue.enqueue({id:'one', text:'Part one'});
  await tick();
  h.queue.enqueue({id:'two', text:'Part two'});
  assert.equal(first.controller.signal.aborted, false);
  finish(); await finished;
  assert.equal(h.queue.pending(), false);
});

test('reload retains queued IDs, and navigation cannot send another owner’s inputs', async () => {
  let first;
  const h = fixture(async (input, delivery) => {
    first = delivery;
    await new Promise(resolve => delivery.controller.signal.addEventListener('abort', resolve, {once:true}));
  });
  const stopped = h.queue.enqueue({id:'one', text:'First'});
  h.queue.enqueue({id:'two', text:'Second'});
  await tick();
  h.queue.detach();
  h.owner.generation++;
  await stopped;
  assert.equal(first.controller.signal.aborted, true);
  const restored = [];
  const queue = createConversationInputs({...h.options, run:async input => {restored.push(input);}});
  await queue.restore();
  assert.deepEqual(restored.map(input => input.id), ['one', 'two']);
  assert.equal(h.values.size, 0);
  h.owner.ownerId = 'someone-else';
  await createConversationInputs({...h.options, run:() => assert.fail('cross-owner input')}).restore();
});

test('uncertain admission preserves the original input and its queue for a retry', async () => {
  const calls = [];
  let failed = true;
  const h = fixture(async input => {calls.push(input.id); return failed ? {failed:true} : {};});
  await h.queue.enqueue({id:'one', text:'Keep this original'});
  assert.equal(h.queue.pending(), true);
  assert.equal(h.values.size, 1);
  failed = false;
  await h.queue.enqueue({id:'two', text:'A correction'});
  assert.deepEqual(calls, ['one', 'one', 'two']);
});
