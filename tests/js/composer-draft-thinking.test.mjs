import { readMemoirClientSource } from './helpers/memoir-source.mjs';
import { escapeHtml } from '../../apps/web/client/memoir/dom.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';

const source = readMemoirClientSource();
function setup(overrides = {}) {
  const state = {project:{id:'p'}, showThinkingSteps:true, showDraftUpdates:false,
    backgroundDraftTurn:'turn-five', privateDraft:{preview:{title:'Garden', text:'Saved garden memory.'}}, ...overrides};
  const context = vm.createContext({state, escapeHtml, formatText:escapeHtml, translate:String});
  for (const name of ['privateDraftThinkingStep', 'renderAgentTrace']) {
    vm.runInContext(source.match(new RegExp(`function ${name}\\([^]*?\\n\\}`))[0], context);
  }
  return context;
}

test('progressive saved drafts appear in a collapsed composer entry under thinking steps', () => {
  const context = setup();
  let html = context.renderAgentTrace([], 'live', false, 'turn-five');
  assert.match(html, /class="agent-loop"/);
  assert.match(html, /<details class="agent-composer-draft" ><summary><span>memoir-composer/);
  assert.match(html, /Saved garden memory/);
  assert.doesNotMatch(html, /private-draft-status|retry-private-draft|data-draft-locale/);
  context.state.privateDraft.preview.text = 'A later garden checkpoint.';
  context.state.privateDraftThinkingExpanded = true;
  html = context.renderAgentTrace([], 'live', true, 'turn-five');
  assert.match(html, /class="agent-composer-draft" open/);
  assert.match(html, /A later garden checkpoint/);
  assert.doesNotMatch(html, /Saved garden memory/);
  assert.equal(context.renderAgentTrace([], 'live', false, 'other-turn'), '');
});

test('the thinking-step flag gates generated text even with draft debugging enabled', () => {
  const context = setup({showThinkingSteps:false, showDraftUpdates:true});
  assert.equal(context.privateDraftThinkingStep('turn-five'), '');
  assert.equal(context.renderAgentTrace([], 'live', false, 'turn-five'), '');
});

test('canonical preview uses its frozen source coverage rather than the newest composer turn', () => {
  const context = setup({backgroundDraftTurn:'turn-ten', privateDraft:{source_revision:5,
    preview:{title:'Garden', text:'Round-five content'}, skill_progress:{project_id:'p', items:[
      {skill:'memoir-composer', coverage_end:5, client_turn_id:'turn-five'},
      {skill:'memoir-composer', coverage_end:10, client_turn_id:'turn-ten'},
    ]}}});
  assert.match(context.privateDraftThinkingStep('turn-five'), /Round-five content/);
  assert.equal(context.privateDraftThinkingStep('turn-ten'), '');
  // Restored history can render the saved result before receipts restore its live trace.
  assert.match(context.renderAgentTrace([], undefined, false, 'turn-five'), /Round-five content/);
  context.state.privateDraft.skill_progress.project_id = 'other';
  assert.equal(context.privateDraftThinkingStep('turn-five'), '');
});

test('event previews remain escaped, deduplicated and pageable without exposing withheld proposals', () => {
  const first = {id:'one', event_id:'event-one', preview:{title:'<Garden>', text:'Safe <script>words</script>'}};
  const context = setup({privateDraft:{first_record:first, selected_record:first, next_cursor:'page-two', pages:[
    {id:'two', event_id:'event-two', preview:{title:'School', text:'A school event.'}},
    {id:'three', original_withheld:true, proposed_preview:{title:'Proposal', text:'Unapproved secret'}},
  ]}});
  const html = context.privateDraftThinkingStep('turn-five');
  assert.equal((html.match(/data-event-id="event-one"/g) || []).length, 1);
  assert.match(html, /data-event-id="event-two"/);
  assert.match(html, /&lt;Garden&gt;|&lt;script&gt;/);
  assert.match(html, /data-action="load-more-private-draft"/);
  assert.doesNotMatch(html, /<script>|Unapproved secret|retry-private-draft/);
  context.state.privateDraft = {preview:null, original_withheld:true, proposed_preview:{text:'Unapproved secret'}};
  assert.equal(context.privateDraftThinkingStep('turn-five'), '');
});
