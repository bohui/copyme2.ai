import assert from 'node:assert/strict';
import test from 'node:test';
import {createReplyRevision} from '../../apps/web/client/memoir/reply-revision.mjs';

function harness(text = '', reducedMotion = false) {
  const message = {text}, frames = [], queue = new Map();
  let next = 0, active = true;
  const controller = createReplyRevision({message, reducedMotion:() => reducedMotion,
    current:() => active, render:() => frames.push(message.text),
    schedule:callback => {queue.set(++next, callback); return next;}, cancel:id => queue.delete(id)});
  function drain() {
    let count = 0;
    while (queue.size) {
      assert.ok(++count < 100, 'revision animation must be bounded');
      const [id, callback] = queue.entries().next().value;
      queue.delete(id); callback();
    }
  }
  return {message, frames, queue, controller, drain, navigate:() => {active = false;}};
}

test('streams immediately, deletes graphemes, and rejects cancelled revision tokens', async () => {
  const h = harness();
  assert.equal(h.controller.begin(0), true);
  h.controller.append('姐姐 👩‍👩‍👧‍👦', 0);
  assert.equal(h.message.text, '姐姐 👩‍👩‍👧‍👦');
  assert.equal(h.message.provisional, true);
  assert.equal(h.queue.size, 0, 'ordinary token delivery adds no animation delay');
  assert.equal(h.controller.begin(1), true);
  h.controller.append('late old tokens', 0);
  h.controller.append('好的，我们换个话题。', 1);
  h.drain();
  assert.equal(h.message.text, '好的，我们换个话题。');
  assert.ok(h.frames.includes('姐姐 '), 'family emoji is removed as one grapheme');
  assert.ok(h.frames.includes(''), 'old reply is erased before replacement appears');
  assert.equal(h.frames.some(value => value.includes('late old')), false);
  assert.equal(h.controller.begin(1), false);
  assert.equal(h.controller.begin(0), false);
  await h.controller.finish('好的，我们换个话题。');
  assert.equal(h.message.provisional, false);
});

test('a newer revision interrupts an unfinished replacement', async () => {
  const h = harness('Old draft.');
  h.controller.begin(0);
  h.controller.append('Replacement one.', 0);
  h.controller.begin(1);
  h.controller.append('Final replacement.', 1);
  const finished = h.controller.finish('Final replacement.');
  h.drain(); await finished;
  assert.equal(h.message.text, 'Final replacement.');
  assert.equal(h.message.provisional, false);
});

test('reduced motion replaces immediately and navigation cancels pending paint', async () => {
  const reduced = harness('Old draft.', true);
  reduced.controller.begin(0);
  reduced.controller.append('Final.', 0);
  await reduced.controller.finish('Final.');
  assert.equal(reduced.message.text, 'Final.');
  assert.equal(reduced.queue.size, 0);
  const h = harness('Old draft.');
  h.controller.begin(0);
  const finished = h.controller.finish('Final.');
  const before = h.message.text;
  h.navigate(); h.drain(); await finished;
  assert.equal(h.message.text, before);
  assert.equal(h.message.provisional, true);
});

test('disconnect disposal settles completion without publishing a draft', async () => {
  const h = harness('Draft '.repeat(400));
  h.controller.begin(0);
  const finished = h.controller.finish('Final.');
  h.controller.dispose(); await finished;
  h.drain();
  assert.equal(h.message.provisional, true);
  assert.equal(h.queue.size, 0);
});
