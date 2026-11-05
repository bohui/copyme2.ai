import { readFileSync } from 'node:fs';
import {randomUUID} from 'node:crypto';
import vm from 'node:vm';
import {createConversationInputs} from '../../../apps/web/client/memoir/conversation-inputs.mjs';

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

export function installConversationInputs(context) {
  context.crypto ||= {randomUUID};
  vm.runInContext(readMemoirClientSource().match(/async function processChatMessage\([^]*?\n\}/)[0], context);
  context.state.conversationInputs = createConversationInputs({
    scope:() => context.captureProjectScope(), current:scope => context.isCurrentProjectScope(scope),
    run:(...args) => context.processChatMessage(...args),
    busy:loading => {context.state.loading = loading; context.render();},
  });
}
