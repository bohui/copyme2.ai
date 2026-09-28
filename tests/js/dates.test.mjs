import test from 'node:test';
import assert from 'node:assert/strict';
import { formatDateExpression } from '../../apps/web/client/memoir/dates.mjs';

test('localises exact dates and times by UI locale', () => {
  assert.equal(formatDateExpression('1976-06-04', 'en-AU'), '4 June 1976');
  assert.equal(formatDateExpression('1976-06-04', 'zh-CN'), '1976年6月4日');
  assert.match(formatDateExpression('1976-06-04T13:05:00Z', 'en-AU'), /4 June 1976/);
  assert.match(formatDateExpression('1976-06-04T13:05:00Z', 'en-AU'), /1:05 pm/);
});

test('preserves uncertainty and non-machine date expressions', () => {
  assert.equal(formatDateExpression('around 1976', 'zh-CN'), 'around 1976');
  assert.equal(formatDateExpression('the late 1960s', 'en-AU'), 'the late 1960s');
  assert.equal(formatDateExpression('1976–1978', 'zh-CN'), '1976–1978');
  assert.equal(formatDateExpression('1976', 'zh-CN'), '1976');
});
