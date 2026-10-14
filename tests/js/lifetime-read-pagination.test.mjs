import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source = fs.readFileSync(new URL('../../apps/web/client/memoir/client.js', import.meta.url), 'utf8');
function load(context, name) {
  const match = source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`));
  assert.ok(match, `${name} exists`);
  vm.runInContext(match[0], context);
}
function setup(extra = {}) {
  const state = {project:{id:'project'}, supabase:{accessToken:'token'}, showThinkingSteps:true, showDraftUpdates:true,
    privateDraft:{snapshot_id:'root',next_cursor:'cursor',page_complete:false,coverage_round:5,
      preview:{title:'One',text:'First'},pages:[]}, ...extra};
  const context = vm.createContext({state, encodeURIComponent, URLSearchParams,
    captureProjectScope:()=>({id:'project'}),isCurrentProjectScope:scope=>scope.id===state.project.id,
    render(){},escapeHtml:String,formatText:String,translateWith:key=>key,freeRecallFinished:()=>true,
    profile:()=>state.project.profile || {}, currentUiLocale:()=> 'en-AU',
    currentSectionRework:()=>null, sectionReworkNotice:()=>'', sectionReworkMarkup:()=>'',
    storyApi:async()=>({snapshot_id:'root',complete:true,next_cursor:null,records:[{id:'two',preview:{title:'Two',text:'Second'}}]})});
  return context;
}

test('draft delivery failure offers reconnection while worker failure keeps generation retry',()=>{
  for(const [error,action] of [['PRIVATE_DRAFT_UNAVAILABLE','refresh-private-draft'], ['DRAFT_UNAVAILABLE','retry-private-draft']]) {
    const context=setup({privateDraft:{error,updating:false}});
    load(context,'privateDraftPreview');
    assert.match(context.privateDraftPreview(),new RegExp(`data-action="${action}"`));
  }
});

test('a pending draft shows the background status without a preview or thinking steps',()=>{
  const context=setup({showThinkingSteps:false,privateDraft:{updating:true}});
  load(context,'privateDraftPreview');
  assert.match(context.privateDraftPreview(),/privateDraftUpdating/);
  context.state.showDraftUpdates=false;
  assert.equal(context.privateDraftPreview(),'');
});
test('later frozen draft pages are reachable and first page is explicitly partial', async () => {
  const context = setup();
  load(context,'privateDraftPreview');
  assert.match(context.privateDraftPreview(), /load-more-private-draft/);
  assert.match(context.privateDraftPreview(), /draftPagesPartial/);
  load(context,'loadMorePrivateDraft');
  await context.loadMorePrivateDraft();
  assert.equal(context.state.privateDraft.pages[0].preview.text, 'Second');
  assert.equal(context.state.privateDraft.next_cursor, null);
  assert.match(context.privateDraftPreview(), /Second/);
  assert.doesNotMatch(context.privateDraftPreview(), /load-more-private-draft/);
});

test('draft language uses the requested Mandarin edition when a failed response omits its locale', () => {
  const context = setup({project:{id:'project',profile:{preferred_language:'zh-CN'}},
    privateDraft:{error:'MEMOIR_UNAVAILABLE'}});
  load(context,'privateDraftPreview');
  assert.match(context.privateDraftPreview(), /value="zh-CN" selected/);
  assert.doesNotMatch(context.privateDraftPreview(), /value="en-AU" selected/);
});
test('draft page response cannot overwrite newer root or newer project', async () => {
  for (const change of ['root','project']) {
    const context = setup();
    context.storyApi = async () => {
      if (change==='root') context.state.privateDraft={snapshot_id:'new-root'};
      else context.state.project.id='other';
      return {snapshot_id:'root',records:[{preview:{text:'Old'}}],next_cursor:null,complete:true};
    };
    load(context,'loadMorePrivateDraft');
    await context.loadMorePrivateDraft();
    assert.equal(context.state.privateDraft.pages?.length || 0, 0);
  }
});
test('rapid repeated page requests admit one call and preserve retry cursor on failure', async () => {
  const context = setup();let release;let calls=0;
  context.storyApi=()=>{calls++;return new Promise(resolve=>{release=resolve;});};
  load(context,'loadMorePrivateDraft');
  const first=context.loadMorePrivateDraft();
  await context.loadMorePrivateDraft();
  assert.equal(calls,1);
  release({snapshot_id:'root',records:[],next_cursor:null,complete:true});await first;
  assert.equal(context.state.privateDraft.loading_page,false);
});
test('timeline partial paging is explicit and uncertainty remains visible', () => {
  const context=setup({timeline:[{id:'event',title:'Ming at school',date_expression:'unknown',precision:'unknown',life_stage:'unplaced',
    canonical:true,status:'unresolved',assertion:'inferred',uncertainty:'Name and year uncertain',timing_conflict:true,
    details_complete:false,source_refs:[{quote:'Maybe 1963'}],evidence_next_cursor:'evidence'}],familyFeaturesEnabled:true,memoryEventPage:{next_cursor:'events'}});
  Object.assign(context,{translate:key=>key,currentUiLocale:()=>"en-AU",formatDateExpression:value=>value,referencesWorkspace:()=>'',lifeStageText:()=>''});
  load(context,'timelineWorkspace');
  const html=context.timelineWorkspace();
  for(const marker of ['Name and year uncertain','eventInferred','eventUnresolved','eventConflictingDates','timelinePagesPartial','load-more-memory-events','data-more-event-evidence','data-more-event-details']) assert.match(html,new RegExp(marker));
});
test('protected draft proposals remain explicitly review-only and missing originals are disclosed', () => {
  const context=setup({privateDraft:{snapshot_id:'root',snapshot_state:'proposed',approval_required:true,original_withheld:true,
    preview:null,proposed_preview:{title:'Suggestion',text:'Proposed words'},page_complete:true}});
  load(context,'privateDraftPreview');
  const html=context.privateDraftPreview();
  assert.match(html,/draftApprovalRequired/);assert.match(html,/draftOriginalWithheld/);
  assert.match(html,/draftProposalReview/);assert.match(html,/Proposed words/);
  assert.doesNotMatch(html,/privateDraftSaved/);
});
test('one explicit proposal decision carries exact root and proposal digests', async () => {
  const context=setup();const saved=context.state.privateDraft;
  Object.assign(saved,{root_digest:'root-digest',first_record:{id:'section',proposal_digest:'proposal-digest',proposed_preview:{text:'Proposed'}}});
  const calls=[];context.storyApi=async(path,options)=>{calls.push([path,JSON.parse(options.body)]);return {snapshot_id:'root',root_digest:'new-digest'};};
  load(context,'decidePrivateDraftProposal');await context.decidePrivateDraftProposal('section',false);
  assert.equal(calls.length,1);assert.deepEqual(calls[0][1],{project_id:'project',snapshot_id:'root',root_digest:'root-digest',partition_id:'section',expected_proposal_digest:'proposal-digest',accept:false});
  assert.equal(context.state.privateDraft.root_digest,'new-digest');
});
test('edition selection leaves conversation preference alone and requests a fresh view', async () => {
  const context=setup();context.state.project.profile={preferred_language:'en-AU'};
  let calls=0;context.refreshPrivateDraft=async()=>{calls++;};
  load(context,'selectPrivateDraftLocale');await context.selectPrivateDraftLocale('zh-CN');
  assert.equal(context.state.privateDraftLocale,'zh-CN');assert.equal(context.state.project.profile.preferred_language,'en-AU');assert.equal(calls,1);
});
