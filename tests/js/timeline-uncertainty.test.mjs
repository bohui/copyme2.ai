import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source = fs.readFileSync(new URL('../../apps/web/client/memoir/client.js', import.meta.url), 'utf8');

function setup(state) {
  const context = vm.createContext({
    state,
    escapeHtml: String,
    translate: key => key.split('.').at(-1),
    translateWith: key => key.split('.').at(-1),
    formatDateExpression: expression => expression || '',
    currentUiLocale: () => 'en-AU',
    referencesWorkspace: () => '',
  });
  vm.runInContext(source.match(/function timelineDate\([^]*?\n\}/)[0], context);
  vm.runInContext(source.match(/function timelineWorkspace\([^]*?\n\}/)[0], context);
  return context;
}

test('an omitted period end stays unknown, while an explicit ongoing expression survives', () => {
  const context = setup({timeline: [
    {title: 'School', kind: 'period', start_expression: 'around 1955'},
    {title: 'Present life', kind: 'period', start_expression: '2008', end_expression: 'ongoing'},
  ]});
  const html = context.timelineWorkspace();
  assert.match(html, /around 1955 → dateUnknown/);
  assert.match(html, /2008 → ongoing/);
});

test('renders the backend timeline in its supplied order without merging or extra headings', () => {
  const state = {timeline: [
    {title: '回到大石庙镇', kind: 'event', date_expression: '2018年', precision: 'year'},
    {title: '在承德市做木工', kind: 'period', start_expression: '1986年', end_expression: '2005年'},
    {title: '暑假看外祖母', kind: 'event', date_expression: '1958年暑假', precision: 'season'},
    {title: '童年玩耍', kind: 'event', date_expression: '童年', precision: 'age'},
  ]};
  const original = structuredClone(state);
  const html = setup(state).timelineWorkspace();
  assert.equal((html.match(/class="timeline-list"/g) || []).length, 1);
  assert.equal((html.match(/class="timeline-row"/g) || []).length, 4);
  assert.equal((html.match(/<h2>/g) || []).length, 1);
  assert.doesNotMatch(html, /timeline-periods|class="eyebrow"/);
  assert.deepEqual([...html.matchAll(/<strong>(.*?)<\/strong>/g)].map(match => match[1]),
    ['回到大石庙镇', '在承德市做木工', '暑假看外祖母', '童年玩耍']);
  assert.match(html, /1986年 → 2005年/);
  assert.match(html, /1958年暑假/);
  assert.match(html, /童年 · datePrecision/);
  assert.deepEqual(state, original);
});

test('event-only and period-only timelines have no empty state', () => {
  for (const state of [
    {timeline: [{title: 'An event', kind: 'event', date_expression: '1958'}]},
    {timeline: [{title: 'A period', kind: 'period', start_expression: '1986'}]},
  ]) {
    const html = setup(state).timelineWorkspace();
    assert.equal((html.match(/class="timeline-row"/g) || []).length, 1);
    assert.doesNotMatch(html, /workspace-empty|momentsEmpty/);
  }
  const empty = setup({timeline: []}).timelineWorkspace();
  assert.equal((empty.match(/class="workspace-empty"/g) || []).length, 1);
  assert.match(empty, /momentsEmpty/);
});

test('the visual adapter reads event points and period ranges from the same backend list', () => {
  const context = setup({timeline: [
    {id: 'event1', kind: 'event', title: 'Visit', date_expression: '1958'},
    {id: 'period1', kind: 'period', title: 'Work', start_expression: '1986', end_expression: '2005'},
    {id: 'unknown', kind: 'event', title: 'Playing', date_expression: '童年'},
  ]});
  vm.runInContext(source.match(/function timelineRendererItems\([^]*?\n\}/)[0], context);
  const items = Array.from(context.timelineRendererItems());
  assert.deepEqual(items.map(item => item.id), ['event1', 'period1']);
  assert.equal(items[0].end, null);
  assert.equal(items[1].end, '2005-12-31');
  assert.equal(items[1].className, 'memoir-period');
});
