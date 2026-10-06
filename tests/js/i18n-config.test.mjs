import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { defaultLocale, resolveUiLocale } from '../../apps/web/i18n/config.js';

const { match: matchLocale } = createRequire(new URL('../../apps/web/package.json', import.meta.url))('@formatjs/intl-localematcher');

test('explicit UI cookie wins over browser negotiation', () => {
  assert.equal(resolveUiLocale({
    cookieLocale: 'zh-CN',
    acceptLanguage: 'en-AU,en;q=0.8',
    matchLocale,
  }), 'zh-CN');
});

test('browser negotiation respects quality order and falls back safely', () => {
  assert.equal(resolveUiLocale({
    cookieLocale: 'unsupported',
    acceptLanguage: 'en-AU;q=0.4, zh-CN;q=0.9',
    matchLocale,
  }), 'zh-CN');
  assert.equal(resolveUiLocale({
    cookieLocale: '',
    acceptLanguage: 'fr-FR, de;q=0.8',
    matchLocale,
  }), defaultLocale);
});

test('malformed browser tags are ignored without losing the next valid choice', () => {
  for (const acceptLanguage of ['en_US,zh-CN;q=0.9', 'not_a_locale,zh-cn;q=0.9', '*, zh-CN;q=0.9']) {
    assert.equal(resolveUiLocale({ acceptLanguage, matchLocale }), 'zh-CN');
  }
  for (const acceptLanguage of ['invalid_locale', '', '*', 'en-US;q=0,zh-CN;q=0']) {
    assert.equal(resolveUiLocale({ acceptLanguage, matchLocale }), defaultLocale);
  }
});

test('HTTP quality values exclude invalid, unacceptable and duplicate weights', () => {
  for (const quality of ['2', '-1', 'NaN', 'Infinity', '0.1234', '1.001', '1e0', '', '1;q=0', '0.8=invalid']) {
    assert.equal(resolveUiLocale({ acceptLanguage: `zh-CN;q=${quality},en-AU;q=0.8`, matchLocale }), 'en-AU', quality);
  }
  assert.equal(resolveUiLocale({ acceptLanguage: 'en-AU;q=0,zh-CN;q=0.8', matchLocale }), 'zh-CN');
  assert.equal(resolveUiLocale({ acceptLanguage: 'zh-CN;Q=0,en-AU;q=0.8', matchLocale }), 'en-AU');
});

test('real matcher negotiates supported preferences after unsupported languages', () => {
  assert.equal(resolveUiLocale({ acceptLanguage: 'fr-FR,zh-CN;q=0.8,en-AU;q=0.5', matchLocale }), 'zh-CN');
  assert.equal(resolveUiLocale({ acceptLanguage: 'en-US,en;q=0.8', matchLocale }), 'en-AU');
  assert.equal(resolveUiLocale({ cookieLocale: 'zh-CN', acceptLanguage: 'invalid_locale', matchLocale }), 'zh-CN');
});
