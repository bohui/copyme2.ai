import { readFileSync } from 'node:fs';

// Existing VM tests isolate individual functions. Follow their module moves
// and undo factory indentation so those behavior checks keep their fixtures.
export function readMemoirClientSource() {
  const directory = new URL('../../../apps/web/client/memoir/', import.meta.url);
  return ['client.js', 'photo-workspace.mjs', 'place-workspace.mjs',
    'family-workspace.mjs', 'private-draft.mjs', 'story-checkout.mjs',
    'conversation-audio.mjs', 'conversation-history.mjs', 'ui-locale.mjs',
    'dom.mjs', 'audio-utils.mjs'].map(file => {
      const source = readFileSync(new URL(file, directory), 'utf8');
      return file === 'client.js' ? source : source.replace(/^  /gm, '');
    }).join('\n');
}
