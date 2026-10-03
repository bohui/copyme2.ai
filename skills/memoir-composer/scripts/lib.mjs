import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';

export const VERSION = '1.0.0';
export const HARD_MAX = 7000;
export const counter = () => ({algorithm: 'intl-segmenter-wordlike-v1', node: process.version,
  icu: process.versions.icu ?? 'unknown', unicode: process.versions.unicode ?? 'unknown'});
export function stable(value) {
  if (Array.isArray(value)) return `[${value.map(stable).join(',')}]`;
  if (value !== null && typeof value === 'object') return `{${Object.keys(value).sort()
    .map(k => `${JSON.stringify(k)}:${stable(value[k])}`).join(',')}}`;
  return JSON.stringify(value);
}
export const hash = value => createHash('sha256').update(stable(value)).digest('hex');
export const sourceKey = ref => `${ref.source_id ?? ref.id}@${ref.version}`;
export const assetKey = asset => `${asset.asset_id ?? asset.id}@${asset.asset_version ?? asset.version}`;
const requestSchema = JSON.parse(readFileSync(new URL('../schemas/request.schema.json', import.meta.url), 'utf8'));
const draftSchema = JSON.parse(readFileSync(new URL('../schemas/draft.schema.json', import.meta.url), 'utf8'));

// Dependency-free validator for the JSON Schema subset used in this bundle.
// It is not a general-purpose replacement for a complete JSON Schema implementation.
export function schemaErrors(value, schema, root = schema, at = '$') {
  if (schema.$ref) {
    if (!schema.$ref.startsWith('#/$defs/')) return [{code:'SCHEMA_REF', at}];
    return schemaErrors(value, root.$defs[schema.$ref.slice(8)], root, at);
  }
  const errors = [];
  const add = message => errors.push({code:'SCHEMA', at, message});
  if (schema.const !== undefined && stable(value) !== stable(schema.const)) add('Value differs from required constant');
  if (schema.enum && !schema.enum.includes(value)) add('Value is outside the allowed enumeration');
  if (schema.type) {
    const types = Array.isArray(schema.type) ? schema.type : [schema.type];
    const match = types.some(t => t === 'null' ? value === null
      : t === 'array' ? Array.isArray(value)
      : t === 'object' ? value !== null && typeof value === 'object' && !Array.isArray(value)
      : t === 'integer' ? Number.isSafeInteger(value)
      : t === 'number' ? typeof value === 'number' && Number.isFinite(value)
      : typeof value === t);
    if (!match) {add(`Expected ${types.join('|')}`); return errors;}
  }
  if (typeof value === 'string') {
    if (schema.minLength !== undefined && [...value].length < schema.minLength) add('String is too short');
    if (schema.pattern && !new RegExp(schema.pattern, 'u').test(value)) add('String does not match required pattern');
  }
  if (typeof value === 'number') {
    if (schema.minimum !== undefined && value < schema.minimum) add('Number is below minimum');
    if (schema.maximum !== undefined && value > schema.maximum) add('Number exceeds maximum');
  }
  if (Array.isArray(value)) {
    if (schema.minItems !== undefined && value.length < schema.minItems) add('Array has too few items');
    if (schema.maxItems !== undefined && value.length > schema.maxItems) add('Array has too many items');
    value.forEach((v,i) => errors.push(...schemaErrors(v,schema.items ?? {},root,`${at}[${i}]`)));
  } else if (value !== null && typeof value === 'object') {
    for (const k of schema.required ?? []) if (!(k in value)) errors.push({code:'SCHEMA',at:`${at}.${k}`,message:'Required field missing'});
    for (const [k,v] of Object.entries(value)) {
      if (schema.properties?.[k]) errors.push(...schemaErrors(v,schema.properties[k],root,`${at}.${k}`));
      else if (schema.additionalProperties === false) errors.push({code:'SCHEMA',at:`${at}.${k}`,message:'Unknown field'});
    }
  }
  return errors;
}

export function countWords(text, locale) {
  if (typeof text !== 'string' || typeof locale !== 'string') throw new TypeError('Text and locale must be strings');
  if (typeof Intl.Segmenter !== 'function' || Intl.Segmenter.supportedLocalesOf([locale]).length === 0)
    throw new Error(`Word segmentation is unavailable for locale ${locale}`);
  let total = 0;
  for (const part of new Intl.Segmenter(locale,{granularity:'word'}).segment(text.normalize('NFC')))
    if (part.isWordLike) total++;
  return total;
}
export const blockText = b => [b.text,b.caption,b.alt,b.credit].filter(Boolean).join('\n');
export const chapterText = c => [c.title,c.subtitle,...c.blocks.map(blockText)].filter(Boolean).join('\n');
export const chapterRefs = c => [...c.source_refs,...c.blocks.flatMap(b=>b.source_refs)];
export const chapterAssetRefs = c => c.blocks.filter(b=>b.type==='image').map(b=>({asset_id:b.asset_id,version:b.asset_version}));
export const chapterFingerprint = c => hash({id:c.id,title:c.title,subtitle:c.subtitle,
  period_ids:c.period_ids,event_ids:c.event_ids,source_refs:c.source_refs,blocks:c.blocks});
export const snapshotFingerprint = r => hash({skill:VERSION,project_id:r.project_id,target:r.target,
  snapshot:r.snapshot,policy:r.policy,sources:r.sources,assets:r.assets,periods:r.periods,events:r.events,
  prior_state:r.prior_state,authorised_retirements:r.authorised_retirements,context:r.context,counter:counter()});

function duplicateErrors(items, key, at) {
  const seen = new Set(), errors=[];
  for (const v of items) {const k=key(v); if(seen.has(k)) errors.push({code:'DUPLICATE_ID',at,ref:k}); seen.add(k);}
  return errors;
}
export function requestErrors(r) {
  const errors = schemaErrors(r, requestSchema);
  if(errors.length) return errors;
  const add=(code,at,message)=>errors.push({code,at,message});
  if (r.snapshot.expected_manuscript_revision !== r.prior_state.revision)
    add('BASE_REVISION_MISMATCH','snapshot.expected_manuscript_revision','Request and prior state revisions differ');
  if (r.prior_state.kind==='none' && (r.prior_state.chapters.length || r.prior_state.revision!==0))
    add('INVALID_PRIOR_STATE','prior_state','Empty state must have no chapters and revision zero');
  try { countWords('', r.target.locale); } catch(e) {add('UNSUPPORTED_LOCALE','target.locale',e.message);}
  errors.push(...duplicateErrors(r.sources,s=>sourceKey(s),'sources'),
    ...duplicateErrors(r.assets,a=>assetKey(a),'assets'),...duplicateErrors(r.periods,p=>p.id,'periods'),
    ...duplicateErrors(r.events,e=>e.id,'events'),...duplicateErrors(r.prior_state.chapters,c=>c.chapter.id,'prior_state.chapters'));
  errors.push(...duplicateErrors(r.sources.filter(s=>s.status==='active'),s=>s.id,'sources.active_versions'),
    ...duplicateErrors(r.assets.filter(a=>a.status==='active'),a=>a.id,'assets.active_versions'));
  for(const s of r.sources) if(s.project_id!==r.project_id) add('CROSS_PROJECT_SOURCE','sources',s.id);
  for(const a of r.assets) if(a.project_id!==r.project_id) add('CROSS_PROJECT_ASSET','assets',a.id);
  const periods=new Set(r.periods.map(p=>p.id));
  for(const e of r.events) {
    if(e.period_id!==null && !periods.has(e.period_id)) add('UNKNOWN_PERIOD','events',e.id);
    if(e.date.start_year!==null && e.date.end_year!==null && e.date.start_year>e.date.end_year)
      add('INVALID_DATE_RANGE','events',e.id);
  }
  errors.push(...duplicateErrors(r.periods,p=>p.order,'periods.order'));
  return errors;
}

// Trust in allowed/status comes from the host's authenticated projection, not from an LLM.
// A source reference resolves recursively to original testimony/context, never a prior AI draft alone.
export function inspectEvidence(r, ref, category='personal', stack=[]) {
  const errors=[]; const key=sourceKey(ref);
  const err=code=>errors.push({code,ref:key});
  const s=r.sources.find(s=>sourceKey(s)===key);
  if(!s) return [{code:'UNRESOLVED_SOURCE',ref:key}];
  if(stack.includes(key)) return [{code:'SOURCE_LINEAGE_CYCLE',ref:key}];
  if(s.project_id!==r.project_id) err('CROSS_PROJECT_SOURCE');
  if(!s.allowed || s.status!=='active') err('INELIGIBLE_SOURCE');
  if(('char_start' in ref)!==('char_end' in ref)) err('INCOMPLETE_SPAN');
  if('char_start' in ref && (!(ref.char_start<ref.char_end) || ref.char_end>[...s.text].length)) err('INVALID_SPAN');
  if(s.kind==='assistant_message') err('ASSISTANT_IS_NOT_TESTIMONY');
  if(s.kind==='derived_memory') {
    if(!s.derived_from.length) err('MISSING_ORIGINAL_EVIDENCE');
    for(const parent of s.derived_from) errors.push(...inspectEvidence(r,parent,category,[...stack,key]));
  } else {
    const isPersonal=['narrator_chat','transcript','diary','photo_caption','family_statement'].includes(s.kind)
      && ['storyteller','family'].includes(s.author_role);
    const isHistorical=s.kind==='historical_context' && s.author_role==='archive';
    if(category==='personal' && !isPersonal) err('NOT_PERSONAL_EVIDENCE');
    if(category==='historical' && !isHistorical) err('NOT_HISTORICAL_EVIDENCE');
    if(category==='any' && !(isPersonal||isHistorical)) err('UNSUPPORTED_EVIDENCE_ROLE');
  }
  return errors;
}
export function eligibleEvents(r) {
  return r.events.filter(e=>e.status==='active' && e.narrative && e.source_refs.length
    && e.source_refs.every(ref=>inspectEvidence(r,ref,'personal').length===0));
}
export function preparePlan(r) {
  const errors=requestErrors(r);
  if(errors.length) return {ready:false,status:'invalid_request',errors};
  const base={skill_version:VERSION,project_id:r.project_id,input_snapshot_id:r.snapshot.id,
    input_fingerprint:snapshotFingerprint(r),expected_manuscript_revision:r.prior_state.revision,counter:counter(),
    hard_max_chapter_words:HARD_MAX};
  const block=(status,reason)=>({...base,ready:false,status,reason});
  if(!r.snapshot.retrieval_complete) return block('retrieval_incomplete','Finish retrieving the authorised snapshot before selecting coverage.');
  if(!r.trigger.confirmed) return block('awaiting_event_confirmation','Only a confirmed application event may start this skill.');
  let kind;
  if(r.trigger.type==='private_draft_checkpoint') {
    if(r.trigger.private_draft_authorized!==true || !Number.isInteger(r.trigger.private_draft_cadence) ||
       !Number.isInteger(r.trigger.private_rounds_completed) || r.trigger.private_rounds_completed<r.trigger.private_draft_cadence)
      return block('private_draft_not_authorized','The host must authorize a completed private draft checkpoint.');
    if(r.target.audience!=='storyteller'||r.target.medium!=='web'||r.trigger.composition_authorized||r.prior_state.kind==='formal_memoir')
      return block('invalid_private_draft_scope','Private checkpoints cannot authorize a full or published manuscript.');
  } else if(r.trigger.type==='free_rounds_completed') {
    if(r.trigger.free_rounds_completed<r.trigger.free_round_limit) return block('trial_not_finished','Primary free sessions are not complete.');
    if(r.prior_state.kind==='formal_memoir') return block('invalid_transition','Do not downgrade an existing formal memoir to a free preview.');
  } else if(r.trigger.type==='storytelling_complete') {
    if(!r.trigger.storytelling_confirmation_ref) return block('awaiting_storyteller_confirmation','Ask whether the storyteller is ready to compose from the existing material.');
    if(!r.trigger.composition_authorized) return block('composition_not_authorized','The application has not authorised full composition.');
    kind='formal_memoir';
  } else {
    if(r.prior_state.kind==='none') return block('no_prior_composition','Use the free-preview or confirmed formal-composition trigger first.');
    if(r.prior_state.kind==='formal_memoir' && !r.trigger.composition_authorized)
      return block('composition_not_authorized','New full-draft processing is not currently authorised.');
    kind=r.prior_state.kind;
  }
  const events=eligibleEvents(r);
  if(!events.length) return block('insufficient_context','No usable personal events; keep source access and return a supported note or next-step suggestion.');
  const eligiblePeriods=r.periods.filter(p=>p.source_refs.length && p.source_refs.every(ref=>inspectEvidence(r,ref,'personal').length===0));
  const periodIds=new Set(eligiblePeriods.map(p=>p.id));
  const grouped=new Map();
  for(const e of events) if(e.period_id && periodIds.has(e.period_id)) {
    if(!grouped.has(e.period_id)) grouped.set(e.period_id,[]); grouped.get(e.period_id).push(e.id);
  }
  const groups=[...grouped].map(([id,ids])=>({period_id:id,event_ids:ids,count:ids.length,
    order:eligiblePeriods.find(p=>p.id===id).order})).sort((a,b)=>b.count-a.count||a.order-b.order);
  const placed=groups.reduce((n,g)=>n+g.count,0);
  const share=placed ? groups[0].count/placed : 0;
  if(!kind) {
    const pref=r.policy.preview_preference;
    if(pref==='sample_storyline' && groups.length<2) return block('preview_preference_unsupported','An overview preference requires at least two grounded periods; use an honest focused sample.');
    kind=pref!=='auto'?pref:groups.length>=3 && share<r.policy.focus_threshold ? 'sample_storyline':'sample_chapter';
  }
  const knownChapterIds=new Set(r.prior_state.chapters.map(p=>p.chapter.id));
  const affected=r.prior_state.chapters.map(p=>{
    const reasons=[];
    for(const ref of chapterRefs(p.chapter)) if(inspectEvidence(r,ref,'any').length) reasons.push('source_missing_changed_or_restricted');
    for(const ref of chapterAssetRefs(p.chapter)) {
      const asset=r.assets.find(a=>assetKey(a)===assetKey(ref));
      if(!asset || !asset.allowed || asset.status!=='active' || !asset.capabilities[r.target.medium]) reasons.push('media_missing_changed_or_restricted');
    }
    if(chapterText(p.chapter) && countWords(chapterText(p.chapter),r.target.locale)>HARD_MAX) reasons.push('over_word_limit');
    const newEvents=events.filter(e=>p.chapter.period_ids.includes(e.period_id)&&!p.chapter.event_ids.includes(e.id));
    if(newEvents.length) reasons.push('new_events_in_period');
    return {chapter_id:p.chapter.id,base_revision:p.revision,protected:p.approved||p.human_locked,
      needs_attention:!!reasons.length,reasons:[...new Set(reasons)]};
  });
  return {...base,ready:true,status:'ready_to_compose',kind,
    operation:r.prior_state.kind==='none'?'initial':r.trigger.type==='storytelling_complete'?'formal_composition':'update',
    selection:{period_count:groups.length,dominant_share:share,focus_period_id:groups[0]?.period_id??null,
      reason:kind==='sample_storyline'?'Several grounded periods with no dominant period.':kind==='sample_chapter'?'Use a focused supported episode; do not imply a complete life.':'Compose all supported material chronologically.',
      heuristic_not_quality_score:true},
    period_coverage:groups.sort((a,b)=>a.order-b.order),eligible_event_ids:events.map(e=>e.id),
    unplaced_event_ids:events.filter(e=>!e.period_id||!periodIds.has(e.period_id)).map(e=>e.id),
    affected_chapters:affected,known_chapter_ids:[...knownChapterIds],
    host_run_key:hash({event_id:r.event_id,kind,fingerprint:base.input_fingerprint}),
    note:'Confirm title grounding, true event deduplication, factual entailment and complete change detection editorially; these are not established by this utility.'};
}

export function assembledChapters(r,d) {
  const kept=r.prior_state.chapters.filter(p=>d.carry_forward_chapter_ids.includes(p.chapter.id)).map(p=>p.chapter);
  const order=new Map(d.outline.map(o=>[o.chapter_id,o.order]));
  return [...kept,...d.chapters].sort((a,b)=>(order.get(a.id)??Infinity)-(order.get(b.id)??Infinity));
}
export function validateDraft(r,d) {
  let errors=requestErrors(r); let warnings=[];
  if(errors.length) return {ok:false,errors,warnings};
  errors.push(...schemaErrors(d,draftSchema));
  if(errors.length) return {ok:false,errors,warnings};
  const add=(code,at,message)=>errors.push({code,at,message});
  const warn=(code,at,message)=>warnings.push({code,at,message});
  const plan=preparePlan(r);
  if(!plan.ready) {add('TRIGGER_BLOCKED','$',plan.status); return {ok:false,errors,warnings,plan};}
  if(d.project_id!==r.project_id) add('CROSS_PROJECT_DRAFT','project_id','Project mismatch');
  if(d.input_snapshot_id!==r.snapshot.id || d.input_fingerprint!==plan.input_fingerprint)
    add('STALE_SNAPSHOT','input_fingerprint','Regenerate against the exact current snapshot');
  if(d.expected_manuscript_revision!==r.prior_state.revision) add('STALE_REVISION','expected_manuscript_revision','Expected revision differs');
  if(d.kind!==plan.kind) add('WRONG_COMPOSITION_MODE','kind',`Expected ${plan.kind}`);
  if(stable(d.counter)!==stable(counter())) add('COUNTER_RUNTIME_CHANGED','counter','Recount/review with the pinned deployment runtime');
  const checkRefs=(refs,category,at,required=false)=>{
    if(required && refs.length===0) add('MISSING_EVIDENCE',at,'At least one source reference is required');
    for(const ref of refs) for(const e of inspectEvidence(r,ref,category)) errors.push({...e,at});
  };
  const periods=new Map(r.periods.map(p=>[p.id,p]));
  const events=new Map(r.events.map(e=>[e.id,e]));
  const prior=new Map(r.prior_state.chapters.map(p=>[p.chapter.id,p]));
  const count=[];
  errors.push(...duplicateErrors(d.chapters,c=>c.id,'chapters'),...duplicateErrors(d.outline,o=>o.chapter_id,'outline'),
    ...duplicateErrors(d.outline,o=>o.order,'outline.order'),...duplicateErrors(d.event_dispositions,e=>e.event_id,'event_dispositions'),
    ...duplicateErrors(d.carry_forward_chapter_ids,x=>x,'carry_forward_chapter_ids'),
    ...duplicateErrors(d.retired_chapter_ids,x=>x,'retired_chapter_ids'),
    ...duplicateErrors(d.proposed_replacements,x=>x.target_chapter_id,'proposed_replacements'));
  checkRefs(d.title_source_refs,'personal','title_source_refs');
  if(countWords(d.title,r.target.locale)>40) add('TITLE_TOO_LONG','title','Use a concise title, not an extra narrative');
  for(const s of d.source_summary) {
    checkRefs(s.source_refs,'personal',`source_summary.${s.id}`,true);
    for(const id of s.event_ids) if(!events.has(id)) add('UNKNOWN_EVENT',`source_summary.${s.id}`,id);
  }
  function checkChapter(c,at) {
    checkRefs(c.source_refs,'personal',`${at}.source_refs`,true);
    errors.push(...duplicateErrors(c.blocks,b=>b.id,`${at}.blocks`),...duplicateErrors(c.event_ids,x=>x,`${at}.event_ids`));
    for(const p of c.period_ids) {
      if(!periods.has(p)) add('UNKNOWN_PERIOD',at,p);
      else checkRefs(periods.get(p).source_refs,'personal',at,true);
    }
    for(const id of c.event_ids) {
      const e=events.get(id);
      if(!e) add('UNKNOWN_EVENT',at,id);
      else {if(e.status!=='active') add('INACTIVE_EVENT_IN_CHAPTER',at,id); checkRefs(e.source_refs,'personal',at,true);}
    }
    for(const b of c.blocks) {
      const bp=`${at}.blocks.${b.id}`;
      if(b.type!=='image' && (b.asset_id!==null||b.asset_version!==null||b.caption||b.alt||b.credit))
        add('UNEXPECTED_IMAGE_FIELDS',bp,'Only image blocks can carry image fields');
      checkRefs(b.source_refs,b.type==='context'?'historical':b.type==='image'?'any':'personal',bp,
        ['paragraph','quote','context'].includes(b.type));
      if(b.type==='image') {
        if(!b.asset_id || !b.asset_version) add('MISSING_ASSET_REF',bp,'Image needs stable ID and version');
        const a=r.assets.find(a=>assetKey(a)===assetKey(b));
        if(!a || !a.allowed || a.status!=='active' || !a.capabilities[r.target.medium]) add('INELIGIBLE_ASSET',bp,b.asset_id??'missing');
        if(!b.alt.trim()) add('MISSING_ALT',bp,'Image requires alternative text');
        if(b.text) add('IMAGE_TEXT_NOT_ALLOWED',bp,'Use caption, alt and credit fields');
        if(a?.origin==='external') {
          if(!b.credit.trim()) add('MISSING_EXTERNAL_CREDIT',bp,'External material needs a credit and separate role label');
          warn('EXTERNAL_MEDIA_REVIEW',bp,'Confirm its role is labelled and its rights cover this exact use');
        }
        if(b.caption && !b.source_refs.length) warn('CAPTION_METADATA_ONLY',bp,'Use only a nonfactual asset-description caption until details are supported');
      }
      if(b.type==='quote') {
        const exact=b.source_refs.some(ref=>{
          const s=r.sources.find(s=>sourceKey(s)===sourceKey(ref));
          return s && s.kind!=='derived_memory' && 'char_start'in ref && 'char_end'in ref &&
            [...s.text].slice(ref.char_start,ref.char_end).join('')===b.text;
        });
        if(!exact) add('QUOTE_MISMATCH',bp,'Quote must match an original immutable source span exactly');
      }
    }
    const words=countWords(chapterText(c),r.target.locale);
    count.push({chapter_id:c.id,scope:at,words,characters:[...chapterText(c)].length,hard_limit:HARD_MAX});
    if(words>HARD_MAX) add('CHAPTER_TOO_LONG',at,`${words} words exceeds ${HARD_MAX}`);
    else if(words>r.policy.soft_chapter_words) warn('NEAR_CHAPTER_LIMIT',at,`${words} words; preserve editing headroom`);
  }
  let lastOrder=-Infinity;
  for(const o of [...d.outline].sort((a,b)=>a.order-b.order)) {
    checkRefs(o.source_refs,'personal',`outline.${o.chapter_id}`,o.status!=='needs_context');
    if(o.status!=='needs_context' && !o.event_ids.length) add('OUTLINE_WITHOUT_EVENTS','outline',o.chapter_id);
    for(const id of o.event_ids) if(!events.has(id)) add('UNKNOWN_EVENT','outline',id);
    for(const id of o.period_ids) if(!periods.has(id)) add('UNKNOWN_PERIOD','outline',id);
    const os=o.period_ids.map(id=>periods.get(id)?.order).filter(Number.isFinite);
    if(os.length) {
      const current=Math.min(...os);
      if(current<lastOrder) add('NONCHRONOLOGICAL_OUTLINE','outline',o.chapter_id);
      lastOrder=current;
    }
  }
  for(const c of d.chapters) {
    checkChapter(c,`chapters.${c.id}`);
    const old=prior.get(c.id);
    if(old) {
      if(c.base_revision!==old.revision) add('STALE_CHAPTER_REVISION',c.id,'Base revision mismatch');
      if(old.human_locked||old.approved) add('PROTECTED_CHAPTER_WRITE',c.id,'Keep the old revision and supply a proposed replacement');
    } else if(c.base_revision!==0) add('INVALID_NEW_CHAPTER_REVISION',c.id,'New chapters start from base revision zero');
    if(d.carry_forward_chapter_ids.includes(c.id)||d.retired_chapter_ids.includes(c.id)) add('AMBIGUOUS_CHAPTER_ACTION',c.id,'Chapter has multiple actions');
  }
  for(const id of d.carry_forward_chapter_ids) {
    const old=prior.get(id);
    if(!old) {add('UNKNOWN_PRIOR_CHAPTER','carry_forward_chapter_ids',id); continue;}
    if(d.retired_chapter_ids.includes(id)) add('AMBIGUOUS_CHAPTER_ACTION',id,'Cannot carry and retire');
    checkChapter(old.chapter,`carried.${id}`);
  }
  for(const id of d.retired_chapter_ids) {
    const old=prior.get(id);
    if(!old) add('UNKNOWN_PRIOR_CHAPTER','retired_chapter_ids',id);
    else if((old.approved||old.human_locked)&&!r.authorised_retirements.includes(id))
      add('PROTECTED_CHAPTER_RETIREMENT',id,'Explicit authorised restructuring or retirement is required');
  }
  for(const [id] of prior) if(!d.carry_forward_chapter_ids.includes(id)&&!d.retired_chapter_ids.includes(id)&&!d.chapters.some(c=>c.id===id))
    add('PRIOR_CHAPTER_DROPPED',id,'Every previous chapter needs an explicit action');
  for(const p of d.proposed_replacements) {
    const old=prior.get(p.target_chapter_id);
    if(!old||old.revision!==p.expected_revision||p.chapter.id!==p.target_chapter_id||p.chapter.base_revision!==p.expected_revision)
      add('INVALID_REPLACEMENT_PROPOSAL',p.target_chapter_id,'Proposal must target an exact existing chapter revision');
    checkChapter(p.chapter,`proposal.${p.target_chapter_id}`);
    warn('PROPOSAL_NOT_APPLIED',p.target_chapter_id,'Human approval is still required; this proposal is not in the assembled memoir');
  }
  const active=assembledChapters(r,d), activeIds=new Set(active.map(c=>c.id));
  for(const c of active) {
    const o=d.outline.find(o=>o.chapter_id===c.id);
    if(!o||o.status!=='draft') add('CHAPTER_MISSING_FROM_OUTLINE',c.id,'Every active chapter needs a draft outline entry');
    else if(o.title!==c.title||stable(o.period_ids)!==stable(c.period_ids)||stable([...o.event_ids].sort())!==stable([...c.event_ids].sort()))
      add('OUTLINE_CHAPTER_MISMATCH',c.id,'Title, period and event assignment must match');
  }
  if(d.kind==='sample_chapter'&&active.length!==1) add('SAMPLE_CHAPTER_COUNT','$','A focused preview must contain exactly one chapter');
  if(d.kind==='sample_storyline'&&active.length) add('STORYLINE_CONTAINS_FULL_CHAPTERS','$','Use a compact storyline plus proposed outline, not a full manuscript');
  if(d.kind==='formal_memoir') for(const o of d.outline) if(o.status==='draft'&&!activeIds.has(o.chapter_id)) add('MISSING_FORMAL_CHAPTER','outline',o.chapter_id);
  if(d.kind==='formal_memoir'&&!active.length) add('EMPTY_FORMAL_MEMOIR','$','Formal composition needs at least one supported chapter');
  const storylineWords=countWords([d.storyline.title,...d.storyline.blocks.map(blockText)].join('\n'),r.target.locale);
  if(d.kind==='sample_storyline') {
    if(!d.storyline.blocks.length) add('EMPTY_STORYLINE','storyline','The preview needs readable narrative, not only headings');
    checkChapter({id:'sample_storyline',title:d.storyline.title,subtitle:'',source_refs:d.storyline.source_refs,
      blocks:d.storyline.blocks,event_ids:d.storyline.event_ids,period_ids:[]},'storyline');
    const withOutline=storylineWords+countWords(d.outline.map(o=>o.title).join('\n'),r.target.locale);
    if(withOutline>HARD_MAX) add('STORYLINE_TOO_LONG','storyline',`${withOutline} words including outline headings`);
  } else if(d.storyline.blocks.length||d.storyline.title||d.storyline.source_refs.length||d.storyline.event_ids.length) add('UNEXPECTED_STORYLINE','$','This mode uses chapters, not an extra unbounded narrative');
  const dispositions=new Map(d.event_dispositions.map(x=>[x.event_id,x]));
  for(const e of r.events.filter(e=>e.status!=='superseded')) if(!dispositions.has(e.id)) add('UNACCOUNTED_EVENT','event_dispositions',e.id);
  for(const entry of d.event_dispositions) {
    if(!events.has(entry.event_id)) add('UNKNOWN_EVENT','event_dispositions',entry.event_id);
    if(!entry.reason.trim()) add('MISSING_DISPOSITION_REASON','event_dispositions',entry.event_id);
    for(const id of entry.chapter_ids) if(!activeIds.has(id)) add('UNKNOWN_DISPOSITION_CHAPTER','event_dispositions',id);
    if(entry.disposition==='included'&&d.kind==='sample_storyline'&&!d.storyline.event_ids.includes(entry.event_id)) add('INCLUDED_EVENT_NOT_PLACED','storyline',entry.event_id);
    if(entry.disposition==='included'&&d.kind!=='sample_storyline'&& !entry.chapter_ids.some(id=>active.find(c=>c.id===id)?.event_ids.includes(entry.event_id)))
      add('INCLUDED_EVENT_NOT_PLACED','event_dispositions',entry.event_id);
  }
  for(const c of active) for(const id of c.event_ids) if(dispositions.get(id)?.disposition!=='included'||!dispositions.get(id)?.chapter_ids.includes(c.id))
    add('PLACED_EVENT_DISPOSITION_MISMATCH',c.id,id);
  for(const id of d.storyline.event_ids) if(dispositions.get(id)?.disposition!=='included') add('PLACED_EVENT_DISPOSITION_MISMATCH','storyline',id);
  const seenEvents=new Map();
  for(const c of active) for(const id of c.event_ids) {if(seenEvents.has(id)) warn('EVENT_IN_MULTIPLE_CHAPTERS',id,'Editorially check that this is a brief cross-reference, not duplicated storytelling');seenEvents.set(id,c.id);}
  if(d.questions_for_mira.length>r.policy.max_followup_questions) add('TOO_MANY_FOLLOWUPS','questions_for_mira','Respect the configured optional queue size');
  for(const q of d.questions_for_mira) checkRefs(q.source_refs,'personal',`questions_for_mira.${q.id}`);
  for(const f of d.review_flags) if(f.severity==='blocking') add('EDITORIAL_BLOCKER',f.scope,f.code);
  warn('SEMANTIC_REVIEW_REQUIRED','$','Reference existence and exact quoting do not prove prose entailment, chronology or caption accuracy. This is a review-only artifact, never publication approval.');
  return {ok:errors.length===0,errors,warnings,kind:d.kind,input_fingerprint:plan.input_fingerprint,
    counter:counter(),chapter_counts:count,storyline_words:storylineWords,active_chapter_ids:[...activeIds],
    source_summary_words:countWords(d.source_summary.map(s=>s.text).join('\n'),r.target.locale),
    publication_authorized:false};
}

const esc=s=>String(s).replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const md=s=>String(s).replace(/[\\`*_{}\[\]<>()#!|]/g,'\\$&');
function blockMarkdown(b) {
  if(b.type==='image') return `> Photo slot: \`${b.asset_id}@${b.asset_version}\`\n> ${md(b.caption)}\n> ${md(b.alt)}${b.credit?'\n> '+md(b.credit):''}`;
  if(b.type==='heading') return `### ${md(b.text)}`;
  if(b.type==='quote'||b.type==='context'||b.type==='editorial_note') return `> ${b.type==='context'?'Historical context: ':b.type==='editorial_note'?'Editorial note: ':''}${md(b.text).replace(/\n/g,'\n> ')}`;
  return md(b.text);
}
function blockHtml(b) {
  if(b.type==='image') return `<figure data-asset-ref="${esc(b.asset_id+'@'+b.asset_version)}"><div class="photo-slot" role="img" aria-label="${esc(b.alt)}">Photo placement • resolve authorised asset ${esc(b.asset_id)}</div><figcaption>${esc(b.caption)}${b.credit?'<small>'+esc(b.credit)+'</small>':''}</figcaption></figure>`;
  if(b.type==='heading') return `<h3>${esc(b.text)}</h3>`;
  if(b.type==='quote') return `<blockquote>${esc(b.text)}</blockquote>`;
  if(b.type==='context'||b.type==='editorial_note') return `<aside><strong>${b.type==='context'?'Historical context':'Editorial note'}</strong><p>${esc(b.text)}</p></aside>`;
  return `<p>${esc(b.text).replace(/\n/g,'<br>')}</p>`;
}
function bodyBlocks(chapter) {
  let first=0;
  while(chapter.blocks[first]?.type==='heading' && chapter.blocks[first].text.trim()===chapter.title.trim()) first++;
  return chapter.blocks.slice(first);
}
export function renderArtifacts(r,d) {
  const report=validateDraft(r,d);
  if(!report.ok) throw new Error('Draft validation failed; refusing to render a ready-to-review artifact');
  const chapters=assembledChapters(r,d);
  const bodies=d.kind==='sample_storyline' ? [{id:'sample_storyline',title:d.storyline.title,subtitle:'',blocks:d.storyline.blocks}] : chapters;
  const mdParts=[`# ${md(d.title)}`,'_AI-assisted draft for review. Not an approved publication._'];
  const htmlParts=[`<h1>${esc(d.title)}</h1>`,`<p class="notice">AI-assisted draft for review. Not an approved publication.</p>`];
  for(const c of bodies) {
    const showTitle=d.kind==='formal_memoir' || c.title.trim()!==d.title.trim();
    const blocks=bodyBlocks(c);
    mdParts.push(...(showTitle?[`## ${md(c.title)}`]:[]),...(c.subtitle?[md(c.subtitle)]:[]),...blocks.map(blockMarkdown));
    htmlParts.push(`<section id="${esc(c.id)}">${showTitle?'<h2>'+esc(c.title)+'</h2>':''}${c.subtitle?'<p class="period">'+esc(c.subtitle)+'</p>':''}${blocks.map(blockHtml).join('\n')}</section>`);
  }
  if(d.kind==='sample_storyline') {
    mdParts.push('## Proposed chapters',...d.outline.map(o=>`${o.order+1}. ${md(o.title)}${o.status==='needs_context'?' — topic only, more context needed':''}`));
    htmlParts.push('<h2>Proposed chapters</h2><ol>'+d.outline.map(o=>`<li>${esc(o.title)}${o.status==='needs_context'?' — topic only, more context needed':''}</li>`).join('')+'</ol>');
  }
  const css=`:root{color-scheme:light}body{margin:auto;max-width:760px;padding:48px 24px;color:#243c34;background:#faf8f3;font:18px/1.75 Georgia,serif}h1,h2{line-height:1.25}h1{font-size:40px}h2{font-size:29px;margin-top:48px}h3{font-size:23px}.notice,.period,small{font:14px/1.6 system-ui,sans-serif;color:#536457}blockquote,aside{margin:24px 0;padding:12px 20px;border-left:3px solid #74947f;background:#edf2e9}figure{margin:30px 0}figcaption{font:15px/1.6 system-ui,sans-serif}small{display:block}.photo-slot{padding:28px;border:1px dashed #74947f;border-radius:12px;font:14px system-ui,sans-serif}.notice{padding:12px;border:1px solid #ddd}p{overflow-wrap:anywhere}`;
  const html=`<!doctype html><html lang="${esc(r.target.locale)}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; base-uri 'none'; form-action 'none'"><title>${esc(d.title)}</title><style>${css}</style></head><body>${htmlParts.join('\n')}</body></html>`;
  return {'memoir.md':mdParts.join('\n\n')+'\n','memoir.html':html,
    'outline.json':JSON.stringify(d.outline,null,2)+'\n','source-summary.json':JSON.stringify(d.source_summary,null,2)+'\n',
    'validation.json':JSON.stringify(report,null,2)+'\n',
    'manuscript.json':JSON.stringify({project_id:r.project_id,kind:d.kind,status:'draft',title:d.title,outline:d.outline,chapters,
      storyline:d.storyline,input_fingerprint:d.input_fingerprint,publication_authorized:false},null,2)+'\n',
    'composition-candidate.json':JSON.stringify(d,null,2)+'\n',
    'CHANGELOG.md':`# Composition changes\n\nSnapshot: ${r.snapshot.id}\n\n`+d.chapters.map(c=>`- ${c.id}: ${c.change_type} — ${md(c.update_reason)}`).join('\n')+
      `\n\nUnchanged: ${d.carry_forward_chapter_ids.join(', ')||'none'}\nRetired: ${d.retired_chapter_ids.join(', ')||'none'}\nPending protected-edit proposals: ${d.proposed_replacements.length}\n\nNo publication or printing was authorised by this run.\n`};
}
