import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const layout = fs.readFileSync(new URL('../../apps/web/app/layout.jsx', import.meta.url), 'utf8');
const shell = fs.readFileSync(new URL('../../apps/web/components/MemoirClientShell.jsx', import.meta.url), 'utf8');

test('server HTML does not make an optional remote font stylesheet block bootstrap', () => {
  assert.doesNotMatch(layout, /<link(?=[^>]*rel="stylesheet")(?=[^>]*href="https:\/\/fonts\.googleapis\.com)[^>]*>/s);
});

test('optional fonts are requested only after the memoir client import resolves', () => {
  assert.match(shell, /import\("\.\.\/client\/memoir\/client\.js"\)\.then\(\(\) => \{\s*if \(mounted\) ensureMemoirFonts\(document\);/);
});

test('font loading is idempotent and never waits for a stylesheet response', async () => {
  const {ensureMemoirFonts, MEMOIR_FONT_STYLESHEET} = await import('../../apps/web/client/memoir/optional-fonts.mjs');
  const links = [];
  const document = {
    head: {append: link => links.push(link)},
    querySelector: () => links[0] || null,
    createElement: tag => ({tagName: tag, dataset: {}}),
  };
  const pending = ensureMemoirFonts(document);
  assert.equal(pending, links[0]);
  assert.equal(pending.rel, 'stylesheet');
  assert.equal(pending.href, MEMOIR_FONT_STYLESHEET);
  assert.equal(pending.dataset.memoirFonts, 'true');
  // Neither load nor error fires: initialization must still return immediately.
  assert.equal(typeof pending.then, 'undefined');
  assert.equal(ensureMemoirFonts(document), pending);
  assert.equal(links.length, 1);
  assert.equal(ensureMemoirFonts(null), null);
  assert.equal(ensureMemoirFonts({...document, querySelector: () => null,
    head: {append: () => { throw new Error('Optional stylesheet blocked'); }}}), null);
});
