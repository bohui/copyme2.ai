import test from 'node:test';
import assert from 'node:assert/strict';
import { defaultLocale, resolveUiLocale } from '../../apps/web/i18n/config.js';

function matchLocale(requested, _supported, fallback) {
  const first = requested[0] || '';
  if (first.toLowerCase().startsWith('zh')) return 'zh-CN';
  if (first.toLowerCase().startsWith('en')) return 'en-AU';
  return fallback;
}

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
    acceptLanguage: 'en-AU;q=0.4, zh-TW;q=0.9',
    matchLocale,
  }), 'zh-CN');
  assert.equal(resolveUiLocale({
    cookieLocale: '',
    acceptLanguage: 'fr-FR, de;q=0.8',
    matchLocale,
  }), defaultLocale);
});
