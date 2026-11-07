import { readMemoirClientSource } from './helpers/memoir-source.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const clientSource = readMemoirClientSource();
const styleSource = fs.readFileSync(new URL('../../apps/web/public/styles.css', import.meta.url), 'utf8');

test('keeps the conversation heading inside the scroll region', () => {
  assert.match(clientSource, /heading: `<div class="chat-heading">/);
  assert.match(clientSource, /<div id="chat-scroll"[^\n]+\$\{parts\.heading\}[^\n]*<\/div>/);
});

test('leaves the chat composer outside the scroll region', () => {
  assert.match(clientSource, /<div id="chat-scroll"[^\n]+<\/div>\s*\$\{parts\.composer\}/);
  assert.match(styleSource, /\.chat-main \{[^}]*grid-template-rows: minmax\(0, 1fr\) auto;/);
});
