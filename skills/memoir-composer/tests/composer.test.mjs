import test from 'node:test';
import assert from 'node:assert/strict';
import {preparePlan,validateDraft,countWords,chapterText,chapterFingerprint,snapshotFingerprint,renderArtifacts,counter,inspectEvidence} from '../scripts/lib.mjs';
import {focusedFixture,broadFixture,formalFixture,progressiveFixture,chineseFixture,ref,block,sync} from './fixtures.mjs';
const has=(r,code)=>r.errors.some(e=>e.code===code);
test('stage-tagged sources remain compatible with grounded plans and reject invalid stages',()=>{
 const r=focusedFixture().request;
 r.sources[0].life_stage='childhood';r.sources[0].source_order=1780000000000000;
 r.sources[1].life_stage='unplaced';r.sources[1].source_order=1780000000000001;
 const p=preparePlan(r);assert.equal(p.ready,true);
 r.sources[0].life_stage='midlife';assert.notEqual(preparePlan(r).input_fingerprint,p.input_fingerprint);
 r.sources[0].life_stage='invented';assert.equal(preparePlan(r).status,'invalid_request');
});
test('host-authorized private checkpoint at five preserves twenty-round quota and cannot authorize full prose',()=>{
 const p=focusedFixture();p.request.trigger={...p.request.trigger,type:'private_draft_checkpoint',free_round_limit:20,
   private_draft_authorized:true,private_rounds_completed:5,private_draft_cadence:5};
 assert.equal(preparePlan(p.request).ready,true);
 assert.equal(preparePlan(p.request).kind,'sample_chapter');
 p.request.trigger.private_draft_authorized=false;
 assert.equal(preparePlan(p.request).status,'private_draft_not_authorized');
 p.request.trigger.private_draft_authorized=true;p.request.trigger.composition_authorized=true;
 assert.equal(preparePlan(p.request).status,'invalid_private_draft_scope');
 p.request.trigger.composition_authorized=false;p.request.trigger.type='free_rounds_completed';
 assert.equal(preparePlan(p.request).status,'trial_not_finished');
});
const exactLength=(n)=>{const p=focusedFixture(),c=p.draft.chapters[0];c.title='Chapter';c.subtitle='';c.blocks=[block('length_block',Array(n-1).fill('memory').join(' '),[ref('s_home')])];p.draft.outline[0].title=c.title;return p;};
for(const [name,fn] of Object.entries({focused:focusedFixture,broad:broadFixture,formal:formalFixture,progressive:()=>progressiveFixture(false),protected:()=>progressiveFixture(true),Chinese:chineseFixture}))
 test(`synthetic ${name} fixture validates`,()=>{const p=fn();const v=validateDraft(p.request,p.draft);assert.equal(v.ok,true,JSON.stringify(v.errors));});

test('focused trial chooses one sample chapter',()=>assert.equal(preparePlan(focusedFixture().request).kind,'sample_chapter'));
test('backend configured twenty-round trial gates composition',()=>{const r=focusedFixture().request;r.trigger.free_round_limit=20;r.trigger.free_rounds_completed=19;assert.equal(preparePlan(r).status,'trial_not_finished');r.trigger.free_rounds_completed=20;assert.equal(preparePlan(r).kind,'sample_chapter');});
test('broad trial chooses a chronological narrative preview',()=>assert.equal(preparePlan(broadFixture().request).kind,'sample_storyline'));
test('four completed free rounds do not trigger the sample',()=>{const {request:r}=focusedFixture();r.trigger.free_rounds_completed=4;assert.equal(preparePlan(r).status,'trial_not_finished');});
test('incomplete retrieval is not treated as absence of memories',()=>{const {request:r}=focusedFixture();r.snapshot.retrieval_complete=false;assert.equal(preparePlan(r).status,'retrieval_incomplete');});
test('unconfirmed event cannot initiate composition',()=>{const {request:r}=focusedFixture();r.trigger.confirmed=false;assert.equal(preparePlan(r).status,'awaiting_event_confirmation');});
test('inferred readiness needs storyteller confirmation',()=>{const {request:r}=formalFixture();r.trigger.storytelling_confirmation_ref=null;assert.equal(preparePlan(r).status,'awaiting_storyteller_confirmation');});
test('formal work needs host authorisation',()=>{const {request:r}=formalFixture();r.trigger.composition_authorized=false;assert.equal(preparePlan(r).status,'composition_not_authorized');});
test('formal composition does not require every life stage',()=>{const {request:r}=focusedFixture();r.trigger.type='storytelling_complete';r.trigger.storytelling_confirmation_ref='confirmed';r.trigger.composition_authorized=true;assert.equal(preparePlan(r).kind,'formal_memoir');});
test('progressive trial update stays a sample',()=>{const p=focusedFixture();p.request.prior_state={kind:'sample_chapter',revision:1,chapters:[{revision:1,approved:false,human_locked:false,chapter:p.draft.chapters[0]}],last_snapshot_fingerprint:p.draft.input_fingerprint};p.request.snapshot.expected_manuscript_revision=1;p.request.trigger.type='new_context';assert.equal(preparePlan(p.request).kind,'sample_chapter');});
test('duplicate events cannot inflate coverage',()=>{const {request:r}=broadFixture();r.events.push(structuredClone(r.events[0]));assert.equal(preparePlan(r).status,'invalid_request');});
test('assistant text is not testimony',()=>{const p=focusedFixture();p.request.sources[0].kind='assistant_message';p.request.sources[0].author_role='assistant';sync(p.request,p.draft);assert.ok(has(validateDraft(p.request,p.draft),'ASSISTANT_IS_NOT_TESTIMONY'));});
test('historical captions cannot become personal evidence',()=>{const p=focusedFixture();p.request.sources[0].kind='historical_context';p.request.sources[0].author_role='archive';sync(p.request,p.draft);assert.ok(has(validateDraft(p.request,p.draft),'NOT_PERSONAL_EVIDENCE'));});
test('derived memory can resolve to original testimony',()=>{const p=focusedFixture();p.request.sources.push({...p.request.sources[0],id:'derived',kind:'derived_memory',author_role:'assistant',derived_from:[ref('s_home')]});p.draft.chapters[0].blocks[0].source_refs=[ref('derived')];sync(p.request,p.draft);assert.equal(validateDraft(p.request,p.draft).ok,true);});
test('orphan summaries are rejected as evidence',()=>{const p=focusedFixture();p.request.sources.push({...p.request.sources[0],id:'derived',kind:'derived_memory',author_role:'assistant',derived_from:[]});p.draft.chapters[0].blocks[0].source_refs=[ref('derived')];sync(p.request,p.draft);assert.ok(has(validateDraft(p.request,p.draft),'MISSING_ORIGINAL_EVIDENCE'));});
test('lineage cycles are rejected',()=>{const p=focusedFixture();p.request.sources.push({...p.request.sources[0],id:'derived',kind:'derived_memory',author_role:'assistant',derived_from:[ref('derived')]});assert.equal(inspectEvidence(p.request,ref('derived'))[0].code,'SOURCE_LINEAGE_CYCLE');});
test('revoked personal sources are not reused',()=>{const p=focusedFixture();p.request.sources[1].status='revoked';sync(p.request,p.draft);assert.ok(has(validateDraft(p.request,p.draft),'INELIGIBLE_SOURCE'));});
test('cross-project source references are rejected',()=>{const p=focusedFixture();p.request.sources[0].project_id='other_project';assert.ok(has(validateDraft(p.request,p.draft),'CROSS_PROJECT_SOURCE'));});
test('printing checks a distinct media capability',()=>{const p=focusedFixture();p.request.target.medium='print';sync(p.request,p.draft);assert.ok(has(validateDraft(p.request,p.draft),'INELIGIBLE_ASSET'));});
test('a mentioned but missing image is not silently fabricated',()=>{const p=focusedFixture();p.request.assets=[];sync(p.request,p.draft);assert.ok(has(validateDraft(p.request,p.draft),'INELIGIBLE_ASSET'));});
test('an exact quote uses a source span',()=>{const p=focusedFixture();const text=p.request.sources[1].text;p.draft.chapters[0].blocks[1]=block('b_room',text,[{...ref('s_room'),char_start:0,char_end:[...text].length}],'quote');assert.equal(validateDraft(p.request,p.draft).ok,true);});
test('invented dialogue cannot pass as an exact quote',()=>{const p=focusedFixture();p.draft.chapters[0].blocks[1]=block('b_room','My brother said we would always be happy.',[{...ref('s_room'),char_start:0,char_end:10}],'quote');assert.ok(has(validateDraft(p.request,p.draft),'QUOTE_MISMATCH'));});
test('span coordinates use Unicode code points rather than UTF-16',()=>{const p=focusedFixture();p.request.sources[1].text='🙂 我们的家';const t='我们的家';p.draft.chapters[0].blocks[1]=block('b_room',t,[{...ref('s_room'),char_start:2,char_end:6}],'quote');sync(p.request,p.draft);assert.equal(validateDraft(p.request,p.draft).ok,true);});
test('exactly 7000 chapter words are accepted by the structural cap',()=>{const p=exactLength(7000);assert.equal(countWords(chapterText(p.draft.chapters[0]),'en-AU'),7000);assert.equal(validateDraft(p.request,p.draft).ok,true);});
test('7001 chapter words are rejected, not truncated',()=>{const p=exactLength(7001);assert.ok(has(validateDraft(p.request,p.draft),'CHAPTER_TOO_LONG'));assert.equal(countWords(chapterText(p.draft.chapters[0]),'en-AU'),7001);});
test('caption and alternative text count toward the chapter cap',()=>{const p=exactLength(7000);p.draft.chapters[0].blocks.push({...block('image_limit','',[ref('s_photo')],'image'),asset_id:'photo_door',asset_version:'1',caption:'Door',alt:'Door'});assert.ok(has(validateDraft(p.request,p.draft),'CHAPTER_TOO_LONG'));});
test('Chinese without spaces is segmented as multiple words',()=>{assert.ok(countWords('我小时候住在苏州的小巷里。','zh-CN')>3);});
test('punctuation-only text is not charged as words',()=>assert.equal(countWords('—— … !!!','en-AU'),0));
test('stale source snapshots are rejected',()=>{const p=focusedFixture();p.draft.input_fingerprint='stale';assert.ok(has(validateDraft(p.request,p.draft),'STALE_SNAPSHOT'));});
test('counter runtime mismatch forces revalidation',()=>{const p=focusedFixture();p.draft.counter.icu='other';assert.ok(has(validateDraft(p.request,p.draft),'COUNTER_RUNTIME_CHANGED'));});
test('approved chapter cannot be upserted even with a valid base revision',()=>{const p=progressiveFixture(false);p.request.prior_state.chapters[2].approved=true;sync(p.request,p.draft);assert.ok(has(validateDraft(p.request,p.draft),'PROTECTED_CHAPTER_WRITE'));});
test('protected proposal is not substituted into the assembled manuscript',()=>{const p=progressiveFixture(true);const out=renderArtifacts(p.request,p.draft);const m=JSON.parse(out['manuscript.json']);assert.ok(!m.chapters.at(-1).event_ids.includes('e_friend'));assert.equal(JSON.parse(out['composition-candidate.json']).proposed_replacements.length,1);});
test('stale chapter revision cannot overwrite later editing',()=>{const p=progressiveFixture();p.draft.chapters[0].base_revision=0;assert.ok(has(validateDraft(p.request,p.draft),'STALE_CHAPTER_REVISION'));});
test('prior chapters cannot disappear without an action',()=>{const p=progressiveFixture();p.draft.carry_forward_chapter_ids=[];assert.ok(has(validateDraft(p.request,p.draft),'PRIOR_CHAPTER_DROPPED'));});
test('chronological chapter order is enforced against supplied grounded periods',()=>{const p=formalFixture();[p.draft.outline[0].order,p.draft.outline[2].order]=[2,0];assert.ok(has(validateDraft(p.request,p.draft),'NONCHRONOLOGICAL_OUTLINE'));});
test('HTML source content is escaped and no scripts are executed',()=>{const p=focusedFixture();p.draft.chapters[0].blocks[0].text='<script>alert(1)</script>';const html=renderArtifacts(p.request,p.draft)['memoir.html'];assert.ok(html.includes('&lt;script&gt;'));assert.ok(!html.includes('<script>'));assert.ok(html.includes("default-src 'none'"));});
test('every event has a disposition',()=>{const p=focusedFixture();p.draft.event_dispositions.pop();assert.ok(has(validateDraft(p.request,p.draft),'UNACCOUNTED_EVENT'));});
test('formal outline cannot claim a chapter exists when absent',()=>{const p=formalFixture();p.draft.chapters.pop();assert.ok(has(validateDraft(p.request,p.draft),'MISSING_FORMAL_CHAPTER'));});
test('a carried locked over-limit chapter still blocks a new ready artifact',()=>{const p=progressiveFixture(true);const old=p.request.prior_state.chapters[0].chapter;old.title='Chapter';old.blocks=[block('too_long',Array(7000).fill('word').join(' '),[ref('s_child')])];p.request.prior_state.chapters[0].human_locked=true;p.draft.outline[0].title=old.title;sync(p.request,p.draft);assert.ok(has(validateDraft(p.request,p.draft),'CHAPTER_TOO_LONG'));});
test('validated output never grants publication',()=>{const p=formalFixture();assert.equal(validateDraft(p.request,p.draft).publication_authorized,false);});
test('the same frozen request produces the same idempotency key',()=>{const p=focusedFixture();assert.equal(preparePlan(p.request).host_run_key,preparePlan(structuredClone(p.request)).host_run_key);});
test('a changed policy epoch changes the snapshot fingerprint',()=>{const p=focusedFixture();const old=snapshotFingerprint(p.request);p.request.snapshot.policy_epoch++;assert.notEqual(old,snapshotFingerprint(p.request));});
test('asset rights changes invalidate existing candidate fingerprints',()=>{const p=focusedFixture();p.request.assets[0].capabilities.download=false;assert.ok(has(validateDraft(p.request,p.draft),'STALE_SNAPSHOT'));});
test('unsupported metadata fields cannot hide extra narrative from counting',()=>{const p=focusedFixture();p.draft.chapters[0].hidden_appendix='A long extra chapter';assert.ok(has(validateDraft(p.request,p.draft),'SCHEMA'));});
test('the hard cap cannot be configured above 7000',()=>{const p=focusedFixture();p.request.policy.max_chapter_words=8000;assert.equal(preparePlan(p.request).status,'invalid_request');});
test('active competing source versions must be resolved',()=>{const p=focusedFixture();p.request.sources.push({...p.request.sources[0],version:'2'});assert.equal(preparePlan(p.request).status,'invalid_request');});
test('an invalid draft is never rendered as ready',()=>{const p=exactLength(7001);assert.throws(()=>renderArtifacts(p.request,p.draft));});
test('chapter fingerprints are independent of incidental update explanations',()=>{const p=focusedFixture();const c=p.draft.chapters[0],a=chapterFingerprint(c);c.update_reason='Replayed run';assert.equal(a,chapterFingerprint(c));});
test('an explicit overview preference can cover two supported periods',()=>{const p=broadFixture();p.request.events.pop();p.request.periods.pop();p.request.policy.preview_preference='sample_storyline';assert.equal(preparePlan(p.request).kind,'sample_storyline');});
test('overview preference does not manufacture extra life periods',()=>{const p=focusedFixture();p.request.policy.preview_preference='sample_storyline';assert.equal(preparePlan(p.request).status,'preview_preference_unsupported');});

test('sample exports display a shared manuscript/body/heading title once',()=>{
 for(const fixture of [broadFixture,focusedFixture]) {
  const p=fixture();const chapter=p.draft.kind==='sample_storyline'?p.draft.storyline:p.draft.chapters[0];
  p.draft.title=chapter.title;
  chapter.blocks.unshift(block('title_heading',chapter.title,chapter.source_refs,'heading'));
  const before=structuredClone(p.draft);
  const artifacts=renderArtifacts(p.request,p.draft);
  assert.equal(artifacts['memoir.md'].split('\n').filter(line=>/^#{1,3} /.test(line)&&line.endsWith(chapter.title)).length,1);
  assert.equal((artifacts['memoir.html'].match(/<h[123]>[^]*?<\/h[123]>/g)||[]).filter(line=>line.includes(chapter.title)).length,1);
  assert.deepEqual(p.draft,before);
 }
});
test('exports retain different section titles and later headings',()=>{
 const p=broadFixture();const chapter=p.draft.storyline;
 chapter.blocks.unshift(block('title_heading',chapter.title,chapter.source_refs,'heading'));
 chapter.blocks.push(block('later_heading','Later memories',chapter.source_refs,'heading'));
 const artifacts=renderArtifacts(p.request,p.draft);
 assert.ok(artifacts['memoir.md'].includes(`# ${p.draft.title}`));
 assert.ok(artifacts['memoir.md'].includes(`## ${chapter.title}`));
 assert.ok(!artifacts['memoir.md'].includes(`### ${chapter.title}`));
 assert.ok(artifacts['memoir.md'].includes('### Later memories'));
});
