import test from 'node:test';
import assert from 'node:assert/strict';
import {textEdits} from '../../apps/web/client/memoir/map-memory-card-updates.mjs';

test('text changes preserve separate unchanged Chinese passages and whole emoji',()=>{
  const before='小时候👨‍👩‍👧在承德市学校玩，后来和朋友去河边。';
  const after='小时候👨‍👩‍👧在大石庙镇学校玩，后来和朋友去山上。';
  const edits=textEdits(before,after);
  assert.ok(edits.length>1);
  for (const edit of edits) assert.doesNotMatch(before.slice(edit.start,edit.end),/小时候|👨|学校玩|后来和朋友/);
  let actual=before;
  for (const edit of [...edits].reverse()) actual=actual.slice(0,edit.start)+edit.text+actual.slice(edit.end);
  assert.equal(actual,after);
});

test('text edits reconstruct additions, deletions and repeated graphemes',()=>{
  let seed=7;
  const random=()=>((seed=(seed*1664525+1013904223)>>>0)/2**32);
  const alphabet=['承','德','a',' ', '👩‍👧','é'];
  for (let sample=0;sample<300;sample++) {
    const text=()=>Array.from({length:Math.floor(random()*25)},()=>alphabet[Math.floor(random()*alphabet.length)]).join('');
    const before=text(), after=text();
    let actual=before;
    for (const edit of textEdits(before,after).reverse()) actual=actual.slice(0,edit.start)+edit.text+actual.slice(edit.end);
    assert.equal(actual,after);
  }
});
