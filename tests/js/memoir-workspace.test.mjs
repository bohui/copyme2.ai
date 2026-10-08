import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../../apps/web/client/memoir/client.js', import.meta.url), 'utf8');
const messages = JSON.parse(fs.readFileSync(new URL('../../apps/web/messages/zh-CN.json', import.meta.url))).Memoir.workspace;
const extract = name => source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0];
const escapeHtml = value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));
function setup(overrides = {}) {
  const state = {project: {id:'p'}, workspaceTab:'memoir', workspaceUnlocked:false, compositionStage:0,
    familyFeaturesEnabled:true, familyContext:{}, storyPlans:[{}], checkout:{},
    showThinkingSteps:false, recallStatus:null, privateDraft:null,
    people:[], timeline:[], chapters:[], selectedMemoirChapter:null, placeJourney:{place:'Chengde'}, ...overrides};
  const translate = key => messages[key.split('.').at(-1)] || key;
  const context = vm.createContext({state, escapeHtml, translate,
    translateWith:(key, values) => translate(key).replace(/\{(\w+)\}/g, (_, name) => values[name]),
    formatText:escapeHtml, sourcePills:() => 'sources', referencesWorkspace:() => '',
    familyWorkspace:() => '<div>family view</div>', timelineWorkspace:() => '<div>timeline view</div>',
    workspaceIsVisible:() => true, workspaceMediaOverview:() => '<section class="workspace-media-overview">places and pictures</section>',
    lifeStageNavigator:() => '<section>life stages</section>', render:() => {},
    document:{querySelector:() => null},
  });
  for (const name of ['freeRecallFinished','privateDraftPreview','composingWorkspaceActive','workspaceTabs','activeWorkspaceTab','workspaceDetail',
    'chapterSourceIds','chapterBlockMarkup','memoirChapters','memoirChapterKey','selectMemoirChapter','memoirWorkspace']) vm.runInContext(extract(name), context);
  return context;
}

test('interview keeps place/photo panels without family or payment tabs', () => {
  const context = setup({people: [{id: 'author'}], timeline: [{id: 'birth'}]});
  assert.equal(context.workspaceTabs().length, 0);
  const markup = context.workspaceDetail();
  assert.match(markup, /workspace-media-overview/);
  assert.doesNotMatch(markup, /data-workspace-tab/);
});

test('composition adds Family tabs only with entitlement and suppresses media on every tab', () => {
  for (const signal of [{compositionStage:3}, {workspaceUnlocked:true}, {project:{id:'p', workspace_unlocked:true}}]) {
    for (const fixture of [
      {enabled: true, tabs: ['family','timeline','memoir'], labels: ['家族树','时间线','章节']},
      {enabled: false, tabs: ['memoir'], labels: ['章节']},
    ]) {
      const context = setup({...signal, familyFeaturesEnabled:fixture.enabled});
      assert.deepEqual(Array.from(context.workspaceTabs(), item => item[0]), fixture.tabs);
      assert.deepEqual(Array.from(context.workspaceTabs(), item => item[1]), fixture.labels);
      for (const tab of fixture.tabs) {
        context.state.workspaceTab = tab;
        const markup = context.workspaceDetail();
        assert.equal((markup.match(/data-workspace-tab=/g) || []).length, fixture.tabs.length);
        assert.doesNotMatch(markup, /workspace-media-overview|places and pictures|life stages/);
      }
    }
  }
});

test('memoir pages show one chapter, persist selection and handle removed chapters', () => {
  const chapters = [
    {id:'c2', chapter_number:2, title:'迁居悉尼', text:'第二章正文'},
    {id:'c1', chapter_number:1, title:'童年 <故事>', blocks:[{type:'paragraph', text:'第一章正文'}]},
    {id:'c3', chapter_number:3, title:'第三章'},
  ];
  const context = setup({compositionStage:3, chapters});
  let markup = context.memoirWorkspace();
  assert.equal((markup.match(/class="workspace-card chapter-card"/g) || []).length, 1);
  assert.equal((markup.match(/aria-current="(?:page|false)"/g) || []).length, 3);
  assert.match(markup, /童年 &lt;故事&gt;|第一章正文/);
  assert.doesNotMatch(markup, /第二章正文/);
  assert.match(markup, /disabled>上一章/);
  context.selectMemoirChapter('p:c2');
  markup = context.memoirWorkspace();
  assert.match(markup, /迁居悉尼|第二章正文/);
  assert.doesNotMatch(markup, /第一章正文/);
  context.state.workspaceTab = 'family'; context.workspaceDetail();
  context.state.workspaceTab = 'memoir';
  assert.match(context.workspaceDetail(), /第二章正文/);
  context.selectMemoirChapter('p:c3');
  assert.match(context.memoirWorkspace(), /本章内容正在整理中。/);
  assert.match(context.memoirWorkspace(), /disabled>下一章/);
  context.state.chapters = [chapters[1]];
  assert.match(context.memoirWorkspace(), /第一章正文/);
  assert.equal(context.state.selectedMemoirChapter, 'p:c1');
  context.selectMemoirChapter('unknown');
  assert.equal(context.state.selectedMemoirChapter, 'p:c1');
});

test('empty compositions and text-only first chapters remain readable', () => {
  const context = setup({compositionStage:3, storyChapter:{title:'第一章', text:'已保存的内容'}});
  assert.match(context.memoirWorkspace(), /已保存的内容/);
  context.state.storyChapter = null;
  const markup = context.memoirWorkspace();
  assert.ok(markup.includes(messages.firstChapterEmpty));
  assert.doesNotMatch(markup, /chapter-pagination/);
});

const savedDraft = {covered_round:5, preview:{title:'童年草稿', text:'已保存的童年回忆'}};

test('ordinary storytellers cannot see early draft content or background status', () => {
  for (const rounds of [0, 5, 19]) {
    for (const privateDraft of [savedDraft, {updating:true, progress:{composition:{target_milestone:5}}}, {error:'Draft failed'}]) {
      const context = setup({privateDraft, recallStatus:{rounds_completed:rounds, free_rounds:20, paid:true}});
      assert.equal(context.privateDraftPreview(), '');
      assert.equal(context.privateDraftPreview({inChapters:true}), '');
      assert.equal(context.workspaceTabs().length, 0);
      assert.doesNotMatch(context.workspaceDetail(), /private-draft-status|童年草稿/);
      context.state.workspaceUnlocked = true;
      assert.doesNotMatch(context.workspaceDetail(), /private-draft-status|童年草稿/);
    }
  }
});

test('the existing developer flag shows early checkpoint previews', () => {
  const context = setup({showThinkingSteps:true, privateDraft:savedDraft,
    recallStatus:{rounds_completed:5, free_rounds:20}});
  assert.match(context.privateDraftPreview(), /童年草稿|已保存的童年回忆/);
  assert.match(context.workspaceDetail(), /private-draft-status/);
  assert.equal(context.workspaceTabs().length, 0);
});

test('paid Family storytellers retain their selected Family and Timeline tabs at round 20 before composition', () => {
  for (const compositionStage of [0, 1, 2]) {
    for (const tab of ['family', 'timeline']) {
      const context = setup({compositionStage, workspaceTab:tab, privateDraft:savedDraft,
        people:[{id:'author'}], timeline:[{id:'birth'}],
        recallStatus:{rounds_completed:19, free_rounds:20, paid:true, payment_required:false}});
      assert.deepEqual(Array.from(context.workspaceTabs(), item => item[0]), []);
      context.state.recallStatus.rounds_completed = 20;
      assert.deepEqual(Array.from(context.workspaceTabs(), item => item[0]), ['family', 'timeline', 'memoir']);
      assert.equal(context.activeWorkspaceTab(), tab);
      const markup = context.workspaceDetail();
      assert.equal((markup.match(/data-workspace-tab=/g) || []).length, 3);
      assert.ok(markup.includes(`${tab} view`));
      assert.doesNotMatch(markup, /private-draft-status|童年草稿/);
      context.state.workspaceTab = 'memoir';
      assert.match(context.workspaceDetail(), /童年草稿/);
    }
  }
});

test('finishing free rounds reveals the draft only in Chapters regardless of payment', () => {
  for (const paid of [false, true]) {
    const context = setup({privateDraft:savedDraft, placeJourney:null,
      recallStatus:{rounds_completed:20, free_rounds:20, paid, payment_required:!paid}});
    assert.deepEqual(Array.from(context.workspaceTabs(), item => item[0]), ['family', 'timeline', 'memoir']);
    assert.equal(context.privateDraftPreview(), '');
    const markup = context.workspaceDetail();
    assert.match(markup, /data-workspace-tab="memoir"/);
    assert.equal((markup.match(/private-draft-status/g) || []).length, 1);
    assert.match(markup, /童年草稿|已保存的童年回忆/);
    assert.doesNotMatch(markup, /workspace-empty|workspace-media-overview/);
    context.state.workspaceUnlocked = true;
    for (const tab of ['family', 'timeline']) {
      context.state.workspaceTab = tab;
      assert.doesNotMatch(context.workspaceDetail(), /private-draft-status|童年草稿/);
    }
  }
});

test('draft release follows the configured server limit and rejects incomplete usage', () => {
  const context = setup({privateDraft:savedDraft, recallStatus:{rounds_completed:2, free_rounds:3}});
  assert.equal(context.freeRecallFinished(), false);
  context.state.recallStatus.rounds_completed = 3;
  assert.equal(context.freeRecallFinished(), true);
  assert.match(context.workspaceDetail(), /童年草稿/);
  for (const recallStatus of [null, {payment_required:true}, {rounds_completed:20},
    {rounds_completed:20, free_rounds:0}, {rounds_completed:20, free_rounds:'20'}]) {
    context.state.recallStatus = recallStatus;
    assert.equal(context.freeRecallFinished(), false);
    assert.equal(context.privateDraftPreview({inChapters:true}), '');
  }
});

test('paid storytellers without Family entitlement keep Chapters alone', () => {
  for (const compositionStage of [2, 3]) {
    const context = setup({compositionStage, familyFeaturesEnabled:false,
      recallStatus:{rounds_completed:20, free_rounds:20, paid:true, payment_required:false}});
    assert.deepEqual(Array.from(context.workspaceTabs(), item => item[0]), ['memoir']);
  }
});

test('loads every server page rather than stopping at the first chapter collection', async () => {
  const calls = [];
  const context = vm.createContext({api:async path => {
    calls.push(path);
    return path.includes('cursor=') ? {items:[{id:'last'}], next_cursor:null}
      : {items:Array.from({length:100}, (_, index) => ({id:`c${index}`})), next_cursor:'next page'};
  }});
  vm.runInContext(extract('loadAllChapters'), context);
  const chapters = await context.loadAllChapters('p');
  assert.equal(chapters.length, 101);
  assert.equal(chapters.at(-1).id, 'last');
  assert.equal(calls[1], '/v1/projects/p/chapters?limit=100&cursor=next%20page');
});


test('completed recall keeps location and photo cues until composition unlock', () => {
  for (const familyFeaturesEnabled of [false, true]) {
    const context = setup({familyFeaturesEnabled, privateDraft:savedDraft,
      recallStatus:{rounds_completed:20, free_rounds:20, paid:true}});
    assert.match(context.workspaceDetail(), /workspace-media-overview/);
    assert.match(context.workspaceDetail(), /has-recall-chapters/);
    assert.match(context.workspaceDetail(), /童年草稿/);
    context.state.compositionStage = 3;
    assert.doesNotMatch(context.workspaceDetail(), /workspace-media-overview|has-recall-chapters/);
    assert.match(context.workspaceDetail(), /童年草稿/);
  }
});
