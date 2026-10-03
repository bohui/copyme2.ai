import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,readdirSync} from 'node:fs';
import {dirname,join,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {counter,hash,preparePlan,renderArtifacts,validateDraft} from '../scripts/lib.mjs';

const repoRoot=resolve(dirname(fileURLToPath(import.meta.url)),'../../../');
const fixturePath=join(repoRoot,'tests/evaluation/memoir_progressive_cases.json');
const fixture=JSON.parse(readFileSync(fixturePath,'utf8'));
const requiredSkills=fixture.required_skills;
const phaseIds=['childhood','young_adulthood','midlife','later_life'];
const phaseTitles={
  'zh-CN':['在熟悉的地方长大','离开熟悉的街道','承担与改变','回望普通日子'],
  'en-AU':['The Place Where I Began','Leaving What I Knew','Work, Family and Change','What I Carry Forward'],
};

const ref=(source_id)=>({source_id,version:'1'});
const phaseFor=(round)=>round<=8?0:round<=16?1:round<=24?2:3;
const lifeStageFor=(round)=>phaseIds[phaseFor(round)];

function roundText(profile,number){
  const cue=profile.round_cues[String(number)] || '';
  const lead=profile.locale==='zh-CN' ? `第${number}轮，我记得` : `Round ${number}: I remember`;
  const sentence=`${lead}${profile.life_arc[phaseFor(number)]}。`;
  const detail=number===16 ? profile.family_detail : number===21 ? profile.date_detail : number===26 ? profile.photo_detail : '';
  return `${sentence}${cue ? ` ${cue}` : ''}${detail ? ` ${detail}` : ''}`;
}

function source(id,text,projectId,number){
  return {id,version:'1',project_id:projectId,kind:'narrator_chat',author_role:'storyteller',text,
    status:'active',allowed:true,derived_from:[],life_stage:lifeStageFor(number),source_order:number};
}

function requestFor(profile,rounds,{type='storytelling_complete',revision=0,priorState=null}={}){
  const projectId=`progressive-${profile.id}`;
  const sources=rounds.map((text,index)=>source(`round_${String(index+1).padStart(2,'0')}`,text,projectId,index+1));
  const periods=phaseIds.map((id,phase)=>{
    const first=sources.find(item=>item.life_stage===id);
    return {id,order:phase,label:profile.life_arc[phase],source_refs:first?[ref(first.id)]:[]};
  });
  const events=sources.map((item,index)=>({
    id:`event_${String(index+1).padStart(2,'0')}`,
    period_id:item.life_stage,
    summary:item.text,
    source_refs:[ref(item.id)],
    date:{original_expression:index===20?profile.date_detail:`${profile.life_arc[phaseFor(index+1)]} · round ${index+1}`,
      start_year:null,end_year:null,precision:index===20?'relative':'relative'},
    status:'active',narrative:true,
  }));
  const photoSource=sources.find(item=>item.id==='round_26');
  const assets=photoSource?[{
    id:'memory_photo',version:'1',project_id:projectId,origin:'user_upload',
    resolver_ref:`asset://${projectId}/memory_photo/1`,
    content_sha256:hash(`${profile.id}:photo-slot`),status:'active',allowed:true,
    capabilities:{web:true,download:true,print:false},metadata_source_refs:[ref(photoSource.id)],
  }]:[];
  return {
    schema_version:'1.0',request_id:`request-${profile.id}-${rounds.length}-${type}`,event_id:`event-${profile.id}-${rounds.length}-${type}`,
    project_id:projectId,
    trigger:{type,confirmed:true,free_rounds_completed:rounds.length,free_round_limit:20,
      storytelling_confirmation_ref:type==='storytelling_complete'?'confirmed-by-storyteller':null,
      composition_authorized:type!=='free_rounds_completed'},
    target:{locale:profile.locale,audience:'storyteller',medium:'web'},
    snapshot:{id:`snapshot-${profile.id}-${rounds.length}-${revision}`,policy_epoch:1,expected_manuscript_revision:revision,
      retrieval_complete:true,glossary_version:'1',preferences_version:'1'},
    policy:{max_chapter_words:7000,soft_chapter_words:6000,focus_threshold:0.65,max_followup_questions:3,preview_preference:'auto'},
    sources,assets,periods,events,
    prior_state:priorState || {kind:'none',revision:0,chapters:[],last_snapshot_fingerprint:''},
    authorised_retirements:[],
    context:{synthetic_fixture:true,storyteller_display_name:profile.id,enabled_skills:requiredSkills,
      region:profile.country,place:profile.place},
  };
}

function privateRequest(profile,rounds){
  const request=requestFor(profile,rounds,{type:'private_draft_checkpoint'});
  request.trigger={...request.trigger,private_draft_authorized:true,private_rounds_completed:rounds.length,private_draft_cadence:5,composition_authorized:false};
  return request;
}

function chapterFor(profile,request,phase,{baseRevision=0,changeType='create',updateReason='Initial grounded draft from the storyteller statements.'}={}){
  const periodId=phaseIds[phase];
  const events=request.events.filter(item=>item.period_id===periodId);
  const blocks=events.map((event,index)=>({
    id:`${phase}_block_${index+1}`,type:'paragraph',text:request.sources.find(item=>item.id===event.source_refs[0].source_id).text,
    asset_id:null,asset_version:null,caption:'',alt:'',credit:'',source_refs:event.source_refs,uncertainty:[],
  }));
  if(phase===3 && request.assets.length){
    const photo=request.sources.find(item=>item.id==='round_26');
    blocks.push({id:'later_life_photo',type:'image',text:'',asset_id:'memory_photo',asset_version:'1',
      caption:profile.photo_detail,alt:`A personal memory photograph connected to ${profile.place}.`,credit:'',source_refs:[ref(photo.id)],uncertainty:['The date is not established.']});
  }
  const sourceRefs=[...new Map(events.flatMap(item=>item.source_refs).map(item=>[`${item.source_id}@${item.version}`,item])).values()];
  return {id:`chapter_${phase}`,base_revision:baseRevision,title:phaseTitles[profile.locale][phase],subtitle:profile.life_arc[phase],
    period_ids:[periodId],event_ids:events.map(item=>item.id),source_refs:sourceRefs,blocks,change_type:changeType,update_reason:updateReason};
}

function outlineFor(chapter,order){
  return {chapter_id:chapter.id,order,title:chapter.title,period_ids:chapter.period_ids,event_ids:chapter.event_ids,status:'draft',
    rationale:'A chronological chapter supported by the storyteller statements for this period.',source_refs:chapter.source_refs};
}

function draftForSafe(profile,request,{priorChapters=[]}={}){
  const plan=preparePlan(request);
  assert.equal(plan.ready,true,`${profile.id}: request should be ready: ${JSON.stringify(plan)}`);
  const priorById=new Map(priorChapters.map(item=>[item.chapter.id,item]));
  const candidateChapters=phaseIds.map((_,phase)=>{
    const old=priorById.get(`chapter_${phase}`);
    const hasNewSource=request.sources.some(item=>item.source_order>20 && item.life_stage===phaseIds[phase]);
    return chapterFor(profile,request,phase,old && hasNewSource
      ? {baseRevision:old.revision,changeType:'enrich',updateReason:'Added later source-backed memories while preserving the chapter identity.'}
      : {});
  });
  const carried=candidateChapters.filter(chapter=>priorById.has(chapter.id) &&
    !request.sources.some(item=>item.source_order>20 && item.life_stage===chapter.period_ids[0])).map(chapter=>chapter.id);
  const activeById=new Map(candidateChapters.map(chapter=>[chapter.id,chapter]));
  const chapters=candidateChapters.filter(chapter=>!carried.includes(chapter.id));
  const sourceSummary=request.events.map(event=>({id:`summary_${event.id}`,text:event.summary,source_refs:event.source_refs,event_ids:[event.id],uncertainty:[]}));
  const chapterForEvent=event=>activeById.get(`chapter_${phaseFor(Number(event.source_refs[0].source_id.slice(-2)))}`)?.id;
  const d={schema_version:'1.0',project_id:request.project_id,input_snapshot_id:'',input_fingerprint:'',expected_manuscript_revision:request.prior_state.revision,
    kind:plan.kind,status:'draft',title:profile.locale==='zh-CN'?`${profile.place}记忆中的四段路`:`A Life Remembered from ${profile.place}`,
    title_source_refs:[ref(request.sources[0].id)],counter:counter(),source_summary:sourceSummary,outline:candidateChapters.map(outlineFor),chapters,
    storyline:{title:'',source_refs:[],event_ids:[],blocks:[]},carry_forward_chapter_ids:carried,retired_chapter_ids:[],proposed_replacements:[],
    event_dispositions:request.events.map(event=>({event_id:event.id,disposition:'included',chapter_ids:[chapterForEvent(event)],reason:'Placed in the chronological chapter for the source-backed period.'})),
    questions_for_mira:[],review_flags:[],next_action:'review_manuscript'};
  const planAgain=preparePlan(request);
  d.input_snapshot_id=request.snapshot.id;
  d.input_fingerprint=planAgain.input_fingerprint;
  d.expected_manuscript_revision=request.prior_state.revision;
  d.counter=counter();
  return d;
}

function skillSignals(profile){
  const signals=new Set(['app-auto-localization','memoir-memory-context','memoir-composer']);
  const cues=profile.round_cues;
  if(cues['1']) signals.add('memoir-place-journey');
  if(cues['8'] || cues['9'] || cues['10'] || cues['11']) signals.add('memoir-place-groups');
  if(cues['16']) signals.add('memoir-family-tree');
  if(cues['21']) signals.add('memoir-author-timeline');
  if(cues['26']) signals.add('place-photo-research');
  return signals;
}

test('the progressive fixture covers every checked-in skill and has ten distinct 31-round lives',()=>{
  const skillDirs=readdirSync(join(repoRoot,'skills'),{withFileTypes:true}).filter(item=>item.isDirectory()).map(item=>item.name);
  for(const skill of requiredSkills){
    assert.ok(skillDirs.includes(skill),`missing skill directory: ${skill}`);
    assert.ok(readFileSync(join(repoRoot,'skills',skill,'SKILL.md'),'utf8').trim().length>0,`empty skill: ${skill}`);
  }
  assert.equal(fixture.profiles.length,10);
  assert.equal(new Set(fixture.profiles.map(item=>item.id)).size,10);
  assert.deepEqual(new Set(fixture.profiles.map(item=>item.locale)),new Set(['en-AU','zh-CN']));
  for(const profile of fixture.profiles){
    const rounds=Array.from({length:fixture.rounds_per_profile},(_,index)=>roundText(profile,index+1));
    assert.equal(rounds.length,31,profile.id);
    assert.equal(skillSignals(profile).size,requiredSkills.length,`${profile.id} did not hit every skill`);
    assert.ok(rounds[0].includes(profile.place),`${profile.id} lacks a grounded place cue`);
    assert.ok(rounds[15].includes(profile.family_detail),`${profile.id} lacks a grounded family detail`);
    assert.ok(rounds[20].includes(profile.date_detail),`${profile.id} lacks a grounded date detail`);
    assert.ok(rounds[25].includes(profile.photo_detail),`${profile.id} lacks a grounded photo detail`);
    assert.ok(rounds[30].length>20,`${profile.id} lacks a composition-complete input`);
  }
});

test('ten profiles pass private checkpoint, free gate, formal composition, and a 31-round progressive update',()=>{
  for(const profile of fixture.profiles){
    const rounds=Array.from({length:31},(_,index)=>roundText(profile,index+1));
    const privatePlan=preparePlan(privateRequest(profile,rounds.slice(0,5)));
    assert.equal(privatePlan.kind,'sample_chapter',`${profile.id}: private checkpoint`);
    assert.equal(privatePlan.operation,'initial',`${profile.id}: private operation`);

    const freePlan=preparePlan(requestFor(profile,rounds.slice(0,20),{type:'free_rounds_completed'}));
    assert.equal(freePlan.kind,'sample_storyline',`${profile.id}: 20-round free gate`);
    assert.equal(freePlan.ready,true,`${profile.id}: free plan`);

    const initialRequest=requestFor(profile,rounds.slice(0,25));
    const initialDraft=draftForSafe(profile,initialRequest);
    const initialValidation=validateDraft(initialRequest,initialDraft);
    assert.equal(initialValidation.ok,true,`${profile.id}: initial ${JSON.stringify(initialValidation.errors)}`);
    const initialArtifacts=renderArtifacts(initialRequest,initialDraft);
    const initialManuscript=JSON.parse(initialArtifacts['manuscript.json']);
    assert.equal(initialManuscript.chapters.length,4,`${profile.id}: initial chapter count`);
    assert.equal(initialManuscript.publication_authorized,false,`${profile.id}: initial publication gate`);

    const priorState={kind:'formal_memoir',revision:1,chapters:initialDraft.chapters.map(chapter=>({revision:1,approved:false,human_locked:false,chapter:structuredClone(chapter)})),last_snapshot_fingerprint:initialDraft.input_fingerprint};
    const updateRequest=requestFor(profile,rounds,{type:'new_context',revision:1,priorState});
    updateRequest.trigger.composition_authorized=true;
    const updateDraft=draftForSafe(profile,updateRequest,{priorChapters:priorState.chapters});
    const updateValidation=validateDraft(updateRequest,updateDraft);
    assert.equal(updateValidation.ok,true,`${profile.id}: progressive ${JSON.stringify(updateValidation.errors)}`);
    const updateArtifacts=renderArtifacts(updateRequest,updateDraft);
    const updateManuscript=JSON.parse(updateArtifacts['manuscript.json']);
    assert.equal(updateRequest.sources.length,31,`${profile.id}: round count`);
    assert.equal(updateManuscript.chapters.length,4,`${profile.id}: progressive chapter count`);
    assert.deepEqual(updateManuscript.chapters.map(chapter=>chapter.id),['chapter_0','chapter_1','chapter_2','chapter_3'],`${profile.id}: stable chapter ids`);
    assert.equal(updateManuscript.publication_authorized,false,`${profile.id}: progressive publication gate`);
    const renderedUpdate=JSON.stringify(updateManuscript);
    assert.match(renderedUpdate,new RegExp(profile.family_detail.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')));
    assert.match(renderedUpdate,new RegExp(profile.date_detail.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')));
    assert.match(renderedUpdate,new RegExp(profile.photo_detail.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')));
    assert.match(updateArtifacts['memoir.html'],new RegExp(profile.place));
  }
});
