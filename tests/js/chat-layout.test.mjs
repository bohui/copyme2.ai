import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const clientSource = fs.readFileSync(new URL('../../apps/web/client/memoir/client.js', import.meta.url), 'utf8');
const styleSource = fs.readFileSync(new URL('../../apps/web/public/styles.css', import.meta.url), 'utf8');

test('keeps the conversation heading inside the scroll region', () => {
  const scrollStart = clientSource.indexOf('<div id="chat-scroll"');
  const headingStart = clientSource.indexOf('<div class="chat-heading">', scrollStart);
  assert.ok(scrollStart >= 0);
  assert.ok(headingStart > scrollStart);
  assert.equal(clientSource.lastIndexOf('<div class="chat-heading">', scrollStart), -1);
});

test('leaves the chat composer outside the scroll region', () => {
  const scrollStart = clientSource.indexOf('<div id="chat-scroll"');
  const scrollEnd = clientSource.indexOf('</div>\n          ${chatComposer()}', scrollStart);
  const composerStart = clientSource.indexOf('${chatComposer()}', scrollStart);
  assert.ok(scrollEnd > scrollStart);
  assert.ok(composerStart > scrollEnd);
  assert.match(styleSource, /\.chat-main \{[^}]*grid-template-rows: minmax\(0, 1fr\) auto;/);
});
