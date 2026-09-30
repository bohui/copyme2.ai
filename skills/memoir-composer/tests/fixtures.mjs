import {preparePlan,counter,hash} from '../scripts/lib.mjs';
export const ref=(id)=>({source_id:id,version:'1'});
const source=(id,text,kind='narrator_chat',role='storyteller')=>({id,version:'1',project_id:'demo_memoir',kind,author_role:role,text,status:'active',allowed:true,derived_from:[]});
const date=(original,start=null,end=null,precision='unknown')=>({original_expression:original,start_year:start,end_year:end,precision});
export const block=(id,text,refs,type='paragraph')=>({id,type,text,asset_id:null,asset_version:null,caption:'',alt:'',credit:'',source_refs:refs,uncertainty:[]});
function requestBase(){return {schema_version:'1.0',request_id:'demo_request',event_id:'demo_event',project_id:'demo_memoir',
 trigger:{type:'free_rounds_completed',confirmed:true,free_rounds_completed:5,free_round_limit:5,storytelling_confirmation_ref:null,composition_authorized:false},
 target:{locale:'en-AU',audience:'storyteller',medium:'web'},
 snapshot:{id:'demo_snapshot',policy_epoch:1,expected_manuscript_revision:0,retrieval_complete:true,glossary_version:'1',preferences_version:'1'},
 policy:{max_chapter_words:7000,soft_chapter_words:6000,focus_threshold:0.65,max_followup_questions:3,preview_preference:'auto'},
 sources:[],assets:[],periods:[],events:[],prior_state:{kind:'none',revision:0,chapters:[],last_snapshot_fingerprint:''},
 authorised_retirements:[],context:{synthetic_fixture:true,storyteller_display_name:'Fictional storyteller',style:'plain, warm, faithful'}};}
export function sync(r,d){const p=preparePlan(r);d.input_snapshot_id=r.snapshot.id;d.input_fingerprint=p.input_fingerprint??'';d.expected_manuscript_revision=r.prior_state.revision;d.counter=counter();return d;}
function draftBase(r){return sync(r,{schema_version:'1.0',project_id:r.project_id,input_snapshot_id:'',input_fingerprint:'',expected_manuscript_revision:0,
 kind:preparePlan(r).kind,status:'draft',title:'A Life in My Own Words',title_source_refs:[],counter:counter(),source_summary:[],outline:[],chapters:[],
 storyline:{title:'',source_refs:[],event_ids:[],blocks:[]},carry_forward_chapter_ids:[],retired_chapter_ids:[],proposed_replacements:[],event_dispositions:[],questions_for_mira:[],review_flags:[],next_action:'review_preview'});}
const chapter=(id,title,period,eventIds,refs,blocks)=>({id,base_revision:0,title,subtitle:'',period_ids:[period],event_ids:eventIds,source_refs:refs,blocks,change_type:'create',update_reason:'Initial draft from the cited narrator statements.'});
const outline=(c,order,status='draft')=>({chapter_id:c.id,order,title:c.title,period_ids:c.period_ids,event_ids:c.event_ids,status,rationale:'A supported chronological stretch of the narrator’s life.',source_refs:c.source_refs});
const disposition=(event_id,chapter_ids=[],value='included',reason='Represented in the draft using its original evidence.')=>({event_id,disposition:value,chapter_ids,reason});

export function focusedFixture(){
 const r=requestBase();r.sources=[
  source('s_home','I grew up in a lane in Suzhou. Our house had a blue door. I think it was in the early 1960s.'),
  source('s_room','My older brother and I shared a small bedroom.'),
  source('s_noodles','On Sundays, my mother made noodles. I remember waiting in the kitchen.'),
  source('s_photo','This photograph shows our blue door. I do not know when it was taken.','photo_caption')];
 r.periods=[{id:'childhood',order:0,label:'Childhood, approximately the early 1960s',source_refs:[ref('s_home')]}];
 r.events=[
  {id:'e_home',period_id:'childhood',summary:'Childhood home with a blue door in Suzhou',source_refs:[ref('s_home')],date:date('I think it was in the early 1960s',1960,1964,'range'),status:'active',narrative:true},
  {id:'e_room',period_id:'childhood',summary:'Shared a bedroom with an older brother',source_refs:[ref('s_room')],date:date('during childhood',null,null,'relative'),status:'active',narrative:true},
  {id:'e_noodles',period_id:'childhood',summary:'Mother made noodles on Sundays',source_refs:[ref('s_noodles')],date:date('during childhood',null,null,'relative'),status:'active',narrative:true}];
 r.assets=[{id:'photo_door',version:'1',project_id:r.project_id,origin:'user_upload',resolver_ref:'asset://demo_memoir/photo_door/1',content_sha256:hash('synthetic asset reference; no photo bytes bundled'),status:'active',allowed:true,capabilities:{web:true,download:true,print:false},metadata_source_refs:[ref('s_photo')]}];
 const d=draftBase(r);d.title='The Beginning of My Story';
 const image={...block('b_photo','',[ref('s_photo')],'image'),asset_id:'photo_door',asset_version:'1',caption:'Our blue door; the date of the photograph is not known.',alt:'Photograph of a blue door.'};
 const c=chapter('ch_childhood','The House with the Blue Door','childhood',['e_home','e_room','e_noodles'],[ref('s_home')],[
  block('b_home','I grew up in a lane in Suzhou. Our house had a blue door. I think it was in the early 1960s.',[ref('s_home')]),
  block('b_room','My older brother and I shared a small bedroom.',[ref('s_room')]),image,
  block('b_noodles','On Sundays, my mother made noodles. I remember waiting in the kitchen.',[ref('s_noodles')])]);
 d.chapters=[c];d.outline=[outline(c,0)];d.event_dispositions=r.events.map(e=>disposition(e.id,[c.id]));
 d.source_summary=r.events.map(e=>({id:'summary_'+e.id,text:e.summary,source_refs:e.source_refs,event_ids:[e.id],uncertainty:e.id==='e_home'?['approximate date']:[]}));
 d.questions_for_mira=[{id:'q_door',question:'What do you remember seeing just outside the blue door?',reason:'An optional continuation of the narrator’s own detail.',event_ids:['e_home'],source_refs:[ref('s_home')]}];
 return {request:r,draft:sync(r,d)};
}
export function broadFixture(){
 const r=requestBase();r.sources=[source('s_child','I spent my childhood in Suzhou in the 1960s.'),
 source('s_work','I started work in a textile factory in 1974. I gave my first wages to my mother.'),
 source('s_sydney','I moved to Sydney in 1995. At first I lived in a small rented flat.')];
 r.periods=[{id:'childhood',order:0,label:'Childhood in the 1960s',source_refs:[ref('s_child')]},{id:'work',order:1,label:'Working life from 1974',source_refs:[ref('s_work')]},{id:'sydney',order:2,label:'Sydney from 1995',source_refs:[ref('s_sydney')]}];
 r.events=[{id:'e_child',period_id:'childhood',summary:'Childhood in Suzhou',source_refs:[ref('s_child')],date:date('in the 1960s',1960,1969,'decade'),status:'active',narrative:true},
 {id:'e_work',period_id:'work',summary:'First factory job and wages given to mother',source_refs:[ref('s_work')],date:date('in 1974',1974,1974,'year'),status:'active',narrative:true},
 {id:'e_sydney',period_id:'sydney',summary:'Moved to Sydney and lived in a rented flat',source_refs:[ref('s_sydney')],date:date('in 1995',1995,1995,'year'),status:'active',narrative:true}];
 const d=draftBase(r);d.title='The Places and Years I Remember';
 d.storyline={title:'From Suzhou to Sydney',source_refs:[ref('s_child'),ref('s_sydney')],event_ids:r.events.map(e=>e.id),blocks:r.sources.map((s,i)=>block('b_'+i,s.text,[ref(s.id)]))};
 d.outline=[['ch_child','Growing Up in Suzhou','childhood','e_child','s_child'],['ch_work','My First Wages','work','e_work','s_work'],['ch_sydney','A New Home in Sydney','sydney','e_sydney','s_sydney']].map(([id,title,p,e,s],i)=>outline(chapter(id,title,p,[e],[ref(s)],[block('unused_'+i,'',[])]),i,'planned'));
 d.source_summary=r.events.map(e=>({id:'summary_'+e.id,text:e.summary,source_refs:e.source_refs,event_ids:[e.id],uncertainty:[]}));
 d.event_dispositions=r.events.map(e=>disposition(e.id));
 return {request:r,draft:sync(r,d)};
}
export function formalFixture(){
 const {request:r,draft:b}=broadFixture();
 r.trigger.type='storytelling_complete';r.trigger.storytelling_confirmation_ref='app_confirmation_demo';r.trigger.composition_authorized=true;
 const d=draftBase(r);d.title=b.title;d.next_action='review_manuscript';d.source_summary=b.source_summary;
 d.chapters=b.outline.map((o,i)=>chapter(o.chapter_id,o.title,o.period_ids[0],o.event_ids,o.source_refs,[block('formal_'+i,r.sources[i].text,[ref(r.sources[i].id)])]));
 d.outline=d.chapters.map((c,i)=>outline(c,i));d.event_dispositions=r.events.map((e,i)=>disposition(e.id,[d.chapters[i].id]));
 return {request:r,draft:sync(r,d)};
}
export function progressiveFixture(protectedChapter=false){
 const {request:r,draft:old}=formalFixture();
 r.prior_state={kind:'formal_memoir',revision:1,chapters:old.chapters.map(c=>({revision:1,approved:protectedChapter&&c.id==='ch_sydney',human_locked:false,chapter:structuredClone(c)})),last_snapshot_fingerprint:old.input_fingerprint};
 r.snapshot.id='demo_snapshot_2';r.snapshot.expected_manuscript_revision=1;r.trigger.type='new_context';r.event_id='demo_new_context';
 r.sources.push(source('s_friend','The first friend I made in Sydney was a neighbour named Sam. We met outside our flats.'));
 r.events.push({id:'e_friend',period_id:'sydney',summary:'Met neighbour Sam in Sydney',source_refs:[ref('s_friend')],date:date('after arriving in Sydney',null,null,'relative'),status:'active',narrative:true});
 const d=draftBase(r);d.title=old.title;d.source_summary=[...old.source_summary,{id:'summary_friend',text:'The narrator met a neighbour called Sam after arriving in Sydney.',source_refs:[ref('s_friend')],event_ids:['e_friend'],uncertainty:[]}];
 d.outline=structuredClone(old.outline);d.carry_forward_chapter_ids=['ch_child','ch_work'];d.event_dispositions=structuredClone(old.event_dispositions);d.next_action='review_manuscript';
 const c=structuredClone(old.chapters[2]);c.base_revision=1;c.event_ids.push('e_friend');c.blocks.push(block('b_friend',r.sources.at(-1).text,[ref('s_friend')]));c.change_type='enrich';c.update_reason='Added a source-backed memory of the first neighbour in Sydney.';
 if(protectedChapter){d.carry_forward_chapter_ids.push('ch_sydney');d.proposed_replacements=[{target_chapter_id:'ch_sydney',expected_revision:1,reason:'The approved chapter receives a proposal, not an overwrite.',chapter:c}];d.event_dispositions.push(disposition('e_friend',[],'deferred','Awaiting approval of the protected chapter proposal.'));d.next_action='review_proposals';}
 else {d.chapters=[c];d.outline[2]=outline(c,2);d.event_dispositions.push(disposition('e_friend',['ch_sydney']));}
 return {request:r,draft:sync(r,d)};
}
export function chineseFixture(){
 const {request:r,draft:d}=focusedFixture();r.target.locale='zh-CN';r.assets=[];r.sources=[source('s_home','我小时候住在苏州的一条小巷里，家门是蓝色的。大概是二十世纪六十年代初。'),source('s_room','我和哥哥住在一间小卧室里。'),source('s_noodles','星期天，妈妈会做面条。我记得自己在厨房里等着。')];
 d.title='我的第一段回忆';const c=d.chapters[0];c.title='小巷里的蓝门';c.blocks=[block('b_home',r.sources[0].text,[ref('s_home')]),block('b_room',r.sources[1].text,[ref('s_room')]),block('b_noodles',r.sources[2].text,[ref('s_noodles')])];
 d.outline[0].title=c.title;d.questions_for_mira=[];
 d.source_summary=[{id:'summary_home',text:'讲述者记得童年住在苏州小巷里，家门是蓝色的，年份不确定。',source_refs:[ref('s_home')],event_ids:['e_home'],uncertainty:['年份不确定']}];
 return {request:r,draft:sync(r,d)};
}
