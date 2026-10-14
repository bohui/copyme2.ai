-- Five-round message summaries and bounded progressive manuscript changes.
begin;
alter table public.user_lifetime_memoir_section add column source_dependencies jsonb not null default '[]',
 add column event_dependencies jsonb not null default '[]',add column composition_config text,
 add column retired boolean not null default false;

create function public.lifetime_composer_source(p_owner uuid,p_project text,p_source uuid,p_version bigint,p_lo integer,p_hi integer) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare s public.user_narrator_source%rowtype;
begin
 select * into s from public.user_narrator_source where user_id=p_owner and project_id=p_project and id=p_source and version=p_version and status='active';
 if not found or p_lo<0 or p_hi<=p_lo or p_hi>length(s.text) or p_hi-p_lo>2304 then raise exception 'invalid progressive source window' using errcode='22023';end if;
 return jsonb_build_object('id',s.id,'project_id',s.project_id,'version',s.version,'sequence',s.sequence,
  'text',substring(s.text from p_lo+1 for p_hi-p_lo),'char_start',p_lo,'char_end',p_hi,'original_length',length(s.text),
  'kind',s.kind,'language',s.language,'status',s.status,'author_role','storyteller');
end $$;
revoke all on function public.lifetime_composer_source(uuid,text,uuid,bigint,integer,integer) from public,anon,authenticated,service_role;

alter function public.read_lifetime_memoir_lane_page(uuid,uuid) rename to read_lifetime_memoir_lane_page_before_batches;
revoke all on function public.read_lifetime_memoir_lane_page_before_batches(uuid,uuid) from public,anon,authenticated,service_role;
create function public.read_lifetime_memoir_lane_page(p_lane_id uuid,p_token uuid) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare snap public.user_lifetime_lane_snapshot%rowtype; lane public.user_memoir_lane%rowtype; predecessor public.user_lifetime_lane_snapshot%rowtype;
 page jsonb; batch jsonb; link record; src jsonb; old_src jsonb; ev jsonb; sources jsonb:='[]'; events jsonb:='[]'; messages jsonb:='[]';
 s public.user_narrator_source%rowtype; prior record; previous jsonb; previous_sections jsonb:='[]'; previous_events jsonb:='[]';
 cursor_seq bigint; cursor_event text; cursor_ref text; start_source bigint; end_source bigint; end_offset integer;
  lo integer; hi integer; i integer; event_index integer; source_index integer; ref jsonb; reference_key text; summary jsonb; prior_ref jsonb; support record; supported boolean;
begin
 snap:=public.lock_lifetime_memoir_lane(p_lane_id,p_token);
 select * into lane from public.user_memoir_lane where id=p_lane_id;
 page:=public.read_lifetime_memoir_lane_page_before_batches(p_lane_id,p_token);
 if lane.skill<>'composer' then return page;end if;
 select * into snap from public.user_lifetime_lane_snapshot where id=snap.id;
 select * into predecessor from public.user_lifetime_lane_snapshot where id=snap.predecessor;
 if snap.page_number=0 and snap.last_source=0 and snap.next_offset=0 then
  update public.user_lifetime_lane_snapshot set last_source=coalesce(predecessor.source_high_water,0),next_offset=100000 where id=snap.id returning * into snap;
 end if;
 start_source:=snap.last_source;end_source:=start_source;end_offset:=snap.next_offset;
 for s in select * from public.user_narrator_source where user_id=snap.user_id and project_id=snap.project_id and status='active'
   and sequence<=snap.source_high_water and (sequence>snap.last_source or sequence=snap.last_source and snap.next_offset<length(text)) order by sequence limit 5 loop
  lo:=case when s.sequence=snap.last_source then snap.next_offset else 0 end;hi:=least(lo+2000,length(s.text));
  if hi>lo then messages:=messages||jsonb_build_array(public.lifetime_composer_source(snap.user_id,snap.project_id,s.id,s.version,lo,hi));end if;
  end_source:=s.sequence;end_offset:=case when hi=length(s.text) then 100000 else hi end;
  if hi<length(s.text) then exit;end if;
 end loop;
 cursor_seq:=snap.last_event;cursor_event:=snap.last_event_id;cursor_ref:=snap.last_ref;
 for link in select e.*,r.source_id,r.source_version,r.evidence_hash,r.evidence,
   coalesce(r.source_id::text||':'||r.source_version::text||':'||r.evidence_hash||':','') reference_key
   from public.user_memory_event e left join public.user_memory_event_source r on r.user_id=e.user_id and r.project_id=e.project_id and r.event_id=e.id
   where e.user_id=snap.user_id and e.project_id=snap.project_id and (e.change_sequence>snap.base_event or exists(select 1 from public.user_workspace_section_rework request
     where request.user_id=snap.user_id and request.project_id=snap.project_id and request.locale=snap.locale and request.event_id=e.id and request.status='pending')) and e.change_sequence<=snap.event_high_water
   and (e.change_sequence,e.id,coalesce(r.source_id::text||':'||r.source_version::text||':'||r.evidence_hash||':',''))>(snap.last_event,snap.last_event_id,snap.last_ref)
   order by e.change_sequence,e.id,reference_key limit 64 loop
  select ordinality::integer-1 into event_index from jsonb_array_elements(events) with ordinality where value->>'id'=link.id;
  if event_index is null and jsonb_array_length(events)>=8 then exit;end if;
  ref:=null;
  if link.status='active' and link.source_id is not null then
   lo:=coalesce((link.evidence->>'char_start')::integer,(select strpos(text,link.evidence->>'quote')-1 from public.user_narrator_source
     where user_id=snap.user_id and project_id=snap.project_id and id=link.source_id and version=link.source_version and status='active'));
   hi:=coalesce((link.evidence->>'char_end')::integer,lo+length(link.evidence->>'quote'));
   src:=public.lifetime_composer_source(snap.user_id,snap.project_id,link.source_id,link.source_version,lo,hi);
   if src->>'text' is distinct from link.evidence->>'quote' then raise exception 'progressive original evidence mismatch';end if;
   if not link.evidence ? 'char_start' and exists(select 1 from public.user_narrator_source where user_id=snap.user_id and project_id=snap.project_id and id=link.source_id
    and strpos(substring(text from lo+2),link.evidence->>'quote')>0) then raise exception 'ambiguous progressive original evidence';end if;
   ref:=link.evidence||jsonb_build_object('char_start',lo,'char_end',hi);
   select ordinality::integer-1,value into source_index,old_src from jsonb_array_elements(sources) with ordinality where value->>'id'=link.source_id::text;
   if source_index is not null then
    lo:=least(lo,(old_src->>'char_start')::integer);hi:=greatest(hi,(old_src->>'char_end')::integer);
    if hi-lo>2304 then exit;end if;
    src:=public.lifetime_composer_source(snap.user_id,snap.project_id,link.source_id,link.source_version,lo,hi);
    sources:=jsonb_set(sources,array[source_index::text],src);
   else
    if jsonb_array_length(sources)>=16 then exit;end if;
    sources:=sources||jsonb_build_array(src);
   end if;
  end if;
  if event_index is null then
   ev:=jsonb_build_object('id',link.id,'revision',link.revision,'kind',link.kind,'life_stage',link.life_stage,'status',link.status,
    'change_sequence',link.change_sequence,'title',left(link.data->>'title',300),'temporal',coalesce(link.data->'temporal','{}'),
    'source_refs',case when ref is null then '[]'::jsonb else jsonb_build_array(ref) end);
   events:=events||jsonb_build_array(ev);
  elsif ref is not null then
   events:=jsonb_set(events,array[event_index::text,'source_refs'],events->event_index->'source_refs'||jsonb_build_array(ref));
  end if;
  cursor_seq:=link.change_sequence;cursor_event:=link.id;cursor_ref:=link.reference_key;
  if octet_length(jsonb_build_object('sources',sources,'events',events)::text)>24000 then exit;end if;
 end loop;
 -- Only affected, independently supported prior passages enter the model.
 for prior in select distinct on (section.partition_key) section.* from public.user_lifetime_memoir_section section
  join public.user_lifetime_lane_snapshot root on root.id=section.snapshot_id
  where section.user_id=snap.user_id and section.project_id=snap.project_id and section.locale=snap.locale and not section.retired
   and (root.state='completed' or root.id=snap.id) and root.policy_epoch=snap.policy_epoch and root.preference_revision=snap.preference_revision
   and root.created_at<=snap.created_at and (section.event_id in (select value->>'id' from jsonb_array_elements(events))
     or exists(select 1 from jsonb_array_elements(section.event_dependencies) dependency,jsonb_array_elements(events) changed where dependency->>'id'=changed->>'id'))
  order by section.partition_key,root.created_at desc limit 8 loop
  if prior.bundle ? 'sections' then
   supported:=true;
   for prior_ref in select value from jsonb_path_query(prior.bundle->'sections','$.** ? (exists(@.source_id) && exists(@.version))') refs(value) loop
    select e.*,l.evidence into support from public.user_memory_event e join public.user_memory_event_source l
      on l.user_id=e.user_id and l.project_id=e.project_id and l.event_id=e.id
     where e.user_id=snap.user_id and e.project_id=snap.project_id and e.status='active' and e.change_sequence<=snap.event_high_water
      and l.source_id::text=prior_ref->>'source_id' and l.source_version::text=prior_ref->>'version'
      and coalesce((l.evidence->>'char_start')::integer,0)<=(prior_ref->>'char_start')::integer
      and coalesce((l.evidence->>'char_end')::integer,length(l.evidence->>'quote'))>=(prior_ref->>'char_end')::integer limit 1;
    if not found then supported:=false;exit;end if;
    select ordinality::integer-1,value into source_index,old_src from jsonb_array_elements(sources) with ordinality where value->>'id'=prior_ref->>'source_id';
    lo:=(prior_ref->>'char_start')::integer;hi:=(prior_ref->>'char_end')::integer;
    if source_index is not null then lo:=least(lo,(old_src->>'char_start')::integer);hi:=greatest(hi,(old_src->>'char_end')::integer);end if;
    if hi-lo>2304 or source_index is null and jsonb_array_length(sources)>=16 then supported:=false;exit;end if;
    src:=public.lifetime_composer_source(snap.user_id,snap.project_id,(prior_ref->>'source_id')::uuid,(prior_ref->>'version')::bigint,lo,hi);
    if source_index is null then sources:=sources||jsonb_build_array(src);else sources:=jsonb_set(sources,array[source_index::text],src);end if;
    if not exists(select 1 from jsonb_array_elements(events) where value->>'id'=support.id) then
     if jsonb_array_length(events)>=8 then supported:=false;exit;end if;
     events:=events||jsonb_build_array(jsonb_build_object('id',support.id,'revision',support.revision,'kind',support.kind,'status',support.status,'life_stage',support.life_stage,
       'change_sequence',support.change_sequence,'title',left(support.data->>'title',300),'temporal',coalesce(support.data->'temporal','{}'),
       'source_refs',jsonb_build_array(support.evidence||jsonb_build_object('char_start',(prior_ref->>'char_start')::integer,'char_end',(prior_ref->>'char_end')::integer))));
    end if;
   end loop;
   -- A prior passage is usable only when all its evidence is in this bounded packet.
   if supported and not exists(select 1 from jsonb_path_query(prior.bundle->'sections','$.** ? (exists(@.source_id) && exists(@.version))') r
     where not exists(select 1 from jsonb_array_elements(sources) a where a->>'id'=r->>'source_id' and a->>'version'=r->>'version'
       and (r->>'char_start')::integer>=(a->>'char_start')::integer and (r->>'char_end')::integer<=(a->>'char_end')::integer)) then
    previous_sections:=previous_sections||(prior.bundle->'sections');
    previous_events:=previous_events||coalesce(nullif(prior.event_dependencies,'[]'),jsonb_build_array(jsonb_build_object('id',prior.event_id,'revision',prior.event_revision)));
    previous:=jsonb_build_object('kind',coalesce(prior.bundle->>'kind',prior.bundle->'manuscript'->>'kind'),'content_config',prior.composition_config,
      'photo_association_manifest',coalesce(prior.bundle->'photo_association_manifest','{}'::jsonb));
   end if;
  end if;
 end loop;
 -- Keep confirmed photograph associations grounded in these original spans.
 select coalesce(jsonb_agg(event || jsonb_build_object('photo_associations',(
   select coalesce(jsonb_agg(jsonb_build_object('id',photo.id,'photo_id',photo.photo_id,'event_id',photo.event_id,
     'source_id',photo.source_id,'source_version',photo.source_version,'quote',photo.quote,'description',photo.description,
     'status','confirmed','provenance','narrator_metadata') order by photo.id),'[]')
   from public.user_interview_photo_link photo where photo.user_id=snap.user_id and photo.project_id=snap.project_id
    and photo.event_id=event->>'id' and photo.status='confirmed' and photo.provenance='narrator_metadata'
    and public.interview_photo_available(snap.user_id,snap.project_id,photo.photo_id)
    and exists(select 1 from jsonb_array_elements(event->'source_refs') evidence where evidence->>'source_id'=photo.source_id::text
      and evidence->>'version'=photo.source_version::text and strpos(evidence->>'quote',photo.quote)>0)
 ))),'[]') into events from jsonb_array_elements(events) event;
 if previous is not null then previous:=previous||jsonb_build_object('sections',previous_sections,'event_manifest',previous_events);end if;
 select value into summary from public.user_memoir_checkpoint c join public.user_lifetime_lane_snapshot root on root.id=c.lifetime_snapshot_id
  where c.lane_id=lane.id and c.kind='prepare' and root.policy_epoch=snap.policy_epoch and root.preference_revision=snap.preference_revision
   and root.created_at<=snap.created_at and (root.id<>snap.id or c.lifetime_page<snap.page_number)
   and c.value->>'event_id' like '%-messages-%' order by c.created_at desc limit 1;
 batch:=jsonb_build_object('schema_version',1,'starting_after',start_source,'through_source',end_source,'next_offset',end_offset,
  'cursor',jsonb_build_array(cursor_seq,cursor_event,cursor_ref),'sources',sources,'events',events,'new_messages',messages,'previous',previous,'previous_summary',summary);
 if octet_length(batch::text)>45000 then raise exception 'progressive batch resource budget exceeded' using errcode='22023';end if;
 page:=page-'input_digest'-'page_digest';
 page:=page||jsonb_build_object('batch',batch,'complete',jsonb_array_length(events)=0 and jsonb_array_length(messages)=0,
   'source',case when page->'source'='null'::jsonb and jsonb_array_length(messages)>0 then messages->0 else page->'source' end);
 page:=page||jsonb_build_object('input_digest',encode(sha256(convert_to((page-'token')::text,'UTF8')),'hex'));
 return page||jsonb_build_object('page_digest',encode(sha256(convert_to(page::text,'UTF8')),'hex'));
end $$;
revoke all on function public.read_lifetime_memoir_lane_page(uuid,uuid) from public,anon,authenticated;
grant execute on function public.read_lifetime_memoir_lane_page(uuid,uuid) to service_role;

-- The batch, prior writing, and all original windows are authority-bearing bytes.
alter function public.lock_lifetime_memoir_lane_publication(jsonb) rename to lock_lifetime_memoir_lane_publication_before_batches;
revoke all on function public.lock_lifetime_memoir_lane_publication_before_batches(jsonb) from public,anon,authenticated,service_role;
create function public.lock_lifetime_memoir_lane_publication(p_fence jsonb) returns numeric
language plpgsql security definer set search_path=public,auth as $$
declare page jsonb;remaining numeric;
begin
 page:=public.read_lifetime_memoir_lane_page((p_fence->>'lane_id')::uuid,(p_fence->>'token')::uuid);
 if coalesce(p_fence->'batch','null'::jsonb) is distinct from coalesce(page->'batch','null'::jsonb)
   or coalesce((p_fence->>'base_revision')::bigint,0) is distinct from (page->>'base_revision')::bigint then
  raise exception 'stale progressive authority' using errcode='40001';end if;
 remaining:=public.lock_lifetime_memoir_lane_publication_before_batches(p_fence);
 return remaining;
end $$;
revoke all on function public.lock_lifetime_memoir_lane_publication(jsonb) from public,anon;
grant execute on function public.lock_lifetime_memoir_lane_publication(jsonb) to authenticated,service_role;

alter function public.save_memoir_checkpoint(uuid,uuid,text,text,jsonb,text) rename to save_memoir_checkpoint_before_batches;
revoke all on function public.save_memoir_checkpoint_before_batches(uuid,uuid,text,text,jsonb,text) from public,anon,authenticated,service_role;
create function public.save_memoir_checkpoint(p_lane_id uuid,p_token uuid,p_key text,p_kind text,p_value jsonb,p_page_digest text default null) returns boolean
language plpgsql security definer set search_path=public,auth as $$
declare page jsonb; sources jsonb;events jsonb; result boolean;
begin
 page:=public.read_lifetime_memoir_lane_page(p_lane_id,p_token);
 result:=public.save_memoir_checkpoint_before_batches(p_lane_id,p_token,p_key,p_kind,p_value,p_page_digest);
 if page->'batch' is not null then
  select coalesce(jsonb_agg(distinct jsonb_build_object('id',s->'id','version',s->'version')),'[]') into sources
   from jsonb_array_elements((page->'batch'->'sources')||(page->'batch'->'new_messages')) s;
  select coalesce(jsonb_agg(jsonb_build_object('id',e->'id','revision',e->'revision')),'[]') into events from jsonb_array_elements(page->'batch'->'events') e;
  update public.user_memoir_checkpoint set source_manifest=sources,event_manifest=events where lane_id=p_lane_id and key=p_key;
 end if;
 return result;
end $$;
revoke all on function public.save_memoir_checkpoint(uuid,uuid,text,text,jsonb,text) from public,anon,authenticated;
grant execute on function public.save_memoir_checkpoint(uuid,uuid,text,text,jsonb,text) to service_role;

alter function public.commit_lifetime_memoir_lane_page(uuid,uuid,bigint,jsonb,text) rename to commit_lifetime_memoir_lane_page_before_batches;
revoke all on function public.commit_lifetime_memoir_lane_page_before_batches(uuid,uuid,bigint,jsonb,text) from public,anon,authenticated,service_role;
create function public.commit_lifetime_memoir_lane_page(p_lane_id uuid,p_token uuid,p_page_number bigint,p_result jsonb,p_page_digest text) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare snap public.user_lifetime_lane_snapshot%rowtype; page jsonb;batch jsonb;item jsonb;ref jsonb;e jsonb;s jsonb;deps jsonb;
 result_hash text;new_root text;key text;source_deps jsonb;event_deps jsonb; prior public.user_lifetime_lane_page_receipt%rowtype;
 title text; preview jsonb; protected public.user_lifetime_memoir_section%rowtype;locked boolean;protected_safe boolean;
begin
 snap:=public.lock_lifetime_memoir_lane(p_lane_id,p_token);
 page:=public.read_lifetime_memoir_lane_page(p_lane_id,p_token);batch:=page->'batch';
 if batch is null then return public.commit_lifetime_memoir_lane_page_before_batches(p_lane_id,p_token,p_page_number,p_result,p_page_digest);end if;
 if jsonb_typeof(p_result)<>'object' or octet_length(p_result::text)>131072 then raise exception 'bounded progressive result required';end if;
 result_hash:=encode(sha256(convert_to(p_result::text,'UTF8')),'hex');
 if p_page_number<snap.page_number then
  select * into prior from public.user_lifetime_lane_page_receipt where snapshot_id=snap.id and page_number=p_page_number;
  if found and prior.page_digest=p_page_digest and prior.result_digest=result_hash then return jsonb_build_object('status','page_saved','replayed',true);end if;
  raise exception 'progressive replay conflict' using errcode='40001';
 end if;
 if p_page_number<>snap.page_number or p_page_digest is distinct from page->>'page_digest' then raise exception 'stale progressive batch' using errcode='40001';end if;
 if jsonb_array_length(batch->'new_messages')>0 and not exists(select 1 from public.user_lifetime_lane_output where snapshot_id=snap.id
  and page_number=snap.page_number and phase='prepare' and input_digest=page->>'input_digest') then raise exception 'new messages require a saved background summary';end if;
 if p_result->>'status' not in ('ready','insufficient_context') then raise exception 'progressive composition failed';end if;
 if p_result->>'status'='ready' then
  if not exists(select 1 from public.user_lifetime_lane_output where snapshot_id=snap.id and page_number=snap.page_number and phase='draft' and input_digest=page->>'input_digest')
    or not exists(select 1 from public.user_lifetime_lane_output where snapshot_id=snap.id and page_number=snap.page_number and phase='review' and input_digest=page->>'input_digest') then
   raise exception 'progressive model draft and review evidence required';end if;
  if (p_result->'validation'->>'ok')::boolean is distinct from true or (p_result->'review'->>'ready_for_user_review')::boolean is distinct from true
   or (p_result->'review'->>'publication_approved')::boolean is distinct from false
   or exists(select 1 from jsonb_array_elements(p_result->'review'->'findings') f where f->>'severity'='blocking')
   or jsonb_typeof(p_result->'sections') is distinct from 'array' or jsonb_array_length(p_result->'sections') not between 1 and 256 then raise exception 'progressive review required';end if;
  for item in select value from jsonb_array_elements(p_result->'sections') loop
   if not item ? 'block' then continue;end if;
   if jsonb_array_length(item->'source_refs')=0 or jsonb_array_length(item->'event_ids')=0 then raise exception 'progressive original evidence required';end if;
   for ref in select value from jsonb_array_elements(item->'source_refs') loop
    if not exists(select 1 from jsonb_array_elements(batch->'events') ev,jsonb_array_elements(ev->'source_refs') evidence
      where item->'event_ids' ? (ev->>'id') and evidence->>'source_id'=ref->>'source_id' and evidence->>'version'=ref->>'version'
       and (evidence->>'char_start')::integer<=(ref->>'char_start')::integer and (evidence->>'char_end')::integer>=(ref->>'char_end')::integer) then
     raise exception 'progressive evidence outside current canonical events';end if;
   end loop;
   select value into e from jsonb_array_elements(batch->'events') where value->>'id'=item->'event_ids'->>0;
   ref:=item->'source_refs'->0;
   select coalesce(jsonb_agg(distinct jsonb_build_object('id',r->'source_id','version',(r->>'version')::bigint)),'[]') into source_deps from (
    select value r from jsonb_array_elements(item->'source_refs') union all
    select r from jsonb_array_elements(p_result->'sections') h,jsonb_array_elements(h->'source_refs') r
      where h ? 'heading' and h->>'chapter_id'=item->>'chapter_id') dependencies;
   select coalesce(jsonb_agg(jsonb_build_object('id',v->'id','revision',v->'revision')),'[]') into event_deps from jsonb_array_elements(batch->'events') v where item->'event_ids' ? (v->>'id')
    or exists(select 1 from jsonb_array_elements(p_result->'sections') h where h ? 'heading' and h->>'chapter_id'=item->>'chapter_id' and h->'event_ids' ? (v->>'id'));
   select coalesce(human_locked,false) into locked from public.user_memoir_manuscript where user_id=snap.user_id and project_id=snap.project_id and locale=snap.locale;
   -- Model-local IDs alone collide across independent message batches. Anchor
   -- a passage to its canonical event as well as its stable writing ID.
   key:='progressive:'||(e->>'id')||':'||(item->>'id');
   select section.* into protected from public.user_lifetime_memoir_section section join public.user_lifetime_lane_snapshot root on root.id=section.snapshot_id
    where section.user_id=snap.user_id and section.project_id=snap.project_id and section.locale=snap.locale and section.partition_key=key
      and (section.approved or section.human_locked or coalesce(locked,false)) and root.state in ('completed','proposed')
    order by root.created_at desc limit 1;
   protected_safe:=protected.snapshot_id is not null and exists(select 1 from public.user_lifetime_lane_snapshot root
     where root.id=protected.snapshot_id and root.policy_epoch=snap.policy_epoch and root.privacy_digest=snap.privacy_digest);
   locked:=coalesce(locked,false) or protected.snapshot_id is not null;
   -- A bounded packet may omit older writing it cannot safely reconstruct.
   -- Such writing must never be replaced by a model that did not receive it.
   if not locked and not exists(select 1 from jsonb_array_elements(coalesce(batch->'previous'->'sections','[]')) previous_item
     where previous_item->>'id'=item->>'id') and exists(select 1 from public.user_lifetime_memoir_section section
     where section.user_id=snap.user_id and section.project_id=snap.project_id and section.locale=snap.locale and section.partition_key=key) then
    key:=key||':delta:'||snap.id::text;
   end if;
   title:=coalesce(item->'heading'->>'title',(select value->'heading'->>'title' from jsonb_array_elements(p_result->'sections') where value->>'chapter_id'=item->>'chapter_id' and value ? 'heading' limit 1),'Memories');
   preview:=jsonb_build_object('id',item->>'id','title',title,'text',coalesce(item->'block'->>'text',''),'locale',snap.locale);
   insert into public.user_lifetime_memoir_section(user_id,project_id,locale,partition_key,event_id,event_revision,source_id,source_version,char_start,char_end,evidence_hash,snapshot_id,
     bundle,approved,human_locked,proposal,source_dependencies,event_dependencies,composition_config)
   values(snap.user_id,snap.project_id,snap.locale,key,e->>'id',(e->>'revision')::bigint,(ref->>'source_id')::uuid,(ref->>'version')::bigint,
     (ref->>'char_start')::integer,(ref->>'char_end')::integer,encode(sha256(convert_to((item->'source_refs')::text,'UTF8')),'hex'),snap.id,
     case when locked then case when protected_safe then protected.bundle else '{}'::jsonb end else jsonb_build_object('kind',p_result->'manuscript'->>'kind','preview',preview,'source_refs',item->'source_refs',
       'photo_association_manifest',coalesce(p_result->'photo_association_manifest','{}'::jsonb),
       'sections',jsonb_build_array(item)||(select coalesce(jsonb_agg(value),'[]') from jsonb_array_elements(p_result->'sections') where value ? 'heading' and value->>'chapter_id'=item->>'chapter_id')) end,
     coalesce(protected.approved,false),locked,case when locked then jsonb_build_object('kind',p_result->'manuscript'->>'kind','preview',preview,'source_refs',item->'source_refs','sections',jsonb_build_array(item)) else null end,
     source_deps,event_deps,p_result->>'content_config')
   on conflict(user_id,project_id,locale,partition_key,snapshot_id) do nothing;
  end loop;
 end if;
 new_root:=encode(sha256(convert_to(jsonb_build_object('predecessor_digest',snap.root_digest,'page_digest',p_page_digest,'result_digest',result_hash)::text,'UTF8')),'hex');
 insert into public.user_lifetime_lane_page_receipt values(snap.id,snap.page_number,p_page_digest,result_hash,new_root,'composed');
 update public.user_lifetime_lane_snapshot set page_number=page_number+1,root_digest=new_root,
  last_source=(batch->>'through_source')::bigint,next_offset=(batch->>'next_offset')::integer,
  last_event=(batch->'cursor'->>0)::bigint,last_event_id=batch->'cursor'->>1,last_ref=batch->'cursor'->>2 where id=snap.id;
 return jsonb_build_object('status','page_saved','root_digest',new_root,'page_number',snap.page_number+1);
end $$;
revoke all on function public.commit_lifetime_memoir_lane_page(uuid,uuid,bigint,jsonb,text) from public,anon,authenticated;
grant execute on function public.commit_lifetime_memoir_lane_page(uuid,uuid,bigint,jsonb,text) to service_role;

-- Existing withdrawal cleanup is extended to every dependency of a passage.
create function public.invalidate_progressive_originals() returns trigger
language plpgsql security definer set search_path=public,auth as $$
begin
 if tg_op='UPDATE' and old is not distinct from new then return new;end if;
 if tg_table_name='user_narrator_source' then
  if tg_op='UPDATE' and new.version=old.version and new.status=old.status then return new;end if;
  delete from public.user_lifetime_memoir_section where user_id=old.user_id and project_id=old.project_id
    and source_dependencies @> jsonb_build_array(jsonb_build_object('id',old.id,'version',old.version));
 else
  if tg_op='UPDATE' and new.status=old.status then return new;end if;
  delete from public.user_lifetime_memoir_section where user_id=old.user_id and project_id=old.project_id
    and event_dependencies @> jsonb_build_array(jsonb_build_object('id',old.id,'revision',old.revision));
 end if;
 return coalesce(new,old);
end $$;
create trigger progressive_source_withdrawal before delete or update of version,status on public.user_narrator_source
 for each row execute function public.invalidate_progressive_originals();
create trigger progressive_event_withdrawal before delete or update of status on public.user_memory_event
 for each row execute function public.invalidate_progressive_originals();
create or replace function public.read_lifetime_private_draft_page(p_project_id text,p_snapshot_id uuid,p_after text default null,p_limit integer default 8)
returns jsonb language plpgsql security definer set search_path=public,auth as $$
declare owner uuid:=auth.uid(); identity public.user_lifetime_conversation%rowtype; project public.user_memoir_project%rowtype;
 root public.user_lifetime_lane_snapshot%rowtype; records jsonb; has_more boolean; next_key text; after_key text:=''; next_cursor uuid;
begin
 if owner is null or p_limit is null or p_limit not between 1 and 8 or length(coalesce(p_after,''))>512 then raise exception 'invalid memoir page';end if;
 select * into identity from public.user_lifetime_conversation where user_id=owner and project_id=p_project_id;
 if not found then raise exception 'canonical conversation unavailable';end if;
 select * into project from public.user_memoir_project where user_id=owner and project_id=p_project_id for share;
 perform 1 from public.user_profile where user_id=owner for share;
 select * into identity from public.user_lifetime_conversation where conversation_id=identity.conversation_id for share;
 select s.* into root from public.user_lifetime_lane_snapshot s join public.user_memoir_lane l on l.id=s.lane_id
   where s.id=p_snapshot_id and s.user_id=owner and s.project_id=p_project_id and s.conversation_id=identity.conversation_id
     and s.state in ('completed','proposed') and l.skill='composer' and s.policy_epoch=project.policy_epoch and s.preference_revision=identity.preference_revision;
 if not found then raise exception 'stale memoir root' using errcode='40001';end if;
 if p_after is not null then
   select last_partition into after_key from public.user_lifetime_memoir_cursor where id=p_after::uuid
     and snapshot_id=root.id and user_id=owner and project_id=p_project_id and root_digest=root.root_digest;
   if not found then raise exception 'memoir page cursor scope mismatch';end if;
 end if;
 select coalesce(jsonb_agg(item order by partition_key),'[]') into records from (
   select s.partition_key,jsonb_build_object('id',s.partition_key,'event_id',s.event_id,'event_revision',s.event_revision,
     'source_refs',coalesce(s.bundle->'source_refs',jsonb_build_array(jsonb_build_object('source_id',s.source_id,'version',s.source_version,'char_start',s.char_start,'char_end',s.char_end))),
     'preview',case when root.state='proposed' and s.snapshot_id=root.id and s.proposal is null then null else s.bundle->'preview' end,
     'proposed_preview',case when root.state='proposed' and s.snapshot_id=root.id and s.proposal is null then s.bundle->'preview' else s.proposal->'preview' end,
     'proposal_digest',case when s.proposal is not null then encode(sha256(convert_to(s.proposal::text,'UTF8')),'hex') else null end,
     'original_withheld',s.proposal is not null and not(s.bundle ? 'preview'),'approval_required',root.state='proposed',
     'approved',s.approved,'human_locked',s.human_locked) item
   from public.user_lifetime_memoir_section s join public.user_lifetime_lane_snapshot ss on ss.id=s.snapshot_id
     join public.user_memory_event e on e.user_id=s.user_id and e.project_id=s.project_id and e.id=s.event_id and e.revision=s.event_revision and e.status='active'
     join public.user_narrator_source n on n.user_id=s.user_id and n.project_id=s.project_id and n.id=s.source_id and n.version=s.source_version and n.status='active'
   where s.user_id=owner and s.project_id=p_project_id and s.locale=root.locale and s.partition_key>after_key and not s.retired
     and not exists(select 1 from jsonb_array_elements(s.source_dependencies) dependency where not exists(
       select 1 from public.user_narrator_source original where original.user_id=s.user_id and original.project_id=s.project_id
        and original.id::text=dependency->>'id' and original.version::text=dependency->>'version' and original.status='active'))
     and not exists(select 1 from jsonb_array_elements(s.event_dependencies) dependency where not exists(
       select 1 from public.user_memory_event original where original.user_id=s.user_id and original.project_id=s.project_id
        and original.id=dependency->>'id' and original.revision::text=dependency->>'revision' and original.status='active'))
     and (ss.state='completed' or ss.id=root.id and ss.state='proposed') and ss.preference_revision=root.preference_revision and ss.policy_epoch=root.policy_epoch and ss.created_at<=root.created_at
     and not exists(select 1 from public.user_lifetime_memoir_section newer join public.user_lifetime_lane_snapshot ns on ns.id=newer.snapshot_id
       where newer.user_id=s.user_id and newer.project_id=s.project_id and newer.locale=s.locale and newer.partition_key=s.partition_key
         and (ns.state='completed' or ns.id=root.id and ns.state='proposed') and ns.created_at>ss.created_at and ns.created_at<=root.created_at)
   order by s.partition_key limit p_limit+1) selected;
 has_more:=jsonb_array_length(records)>p_limit;
 if has_more then
   records:=records-p_limit;next_key:=records->-1->>'id';
   insert into public.user_lifetime_memoir_cursor(snapshot_id,user_id,project_id,last_partition,root_digest) values(root.id,owner,p_project_id,next_key,root.root_digest)
     on conflict(snapshot_id,last_partition,root_digest) do update set last_partition=excluded.last_partition returning id into next_cursor;
 end if;
 return jsonb_build_object('schema_version',1,'owner_id',owner,'conversation_id',identity.conversation_id,'project_id',p_project_id,
   'snapshot_id',root.id,'root_digest',root.root_digest,'locale',root.locale,'source_revision',root.source_high_water,'event_revision',root.event_high_water,
   'policy_epoch',root.policy_epoch,'preference_revision',root.preference_revision,'snapshot_complete',true,
   'snapshot_state',root.state,'approval_required',root.state='proposed',
   'records',records,'complete',not has_more,'next_cursor',next_cursor,'publication_approved',false);
end $$;
revoke all on function public.read_lifetime_private_draft_page(text,uuid,text,integer) from public,anon;
grant execute on function public.read_lifetime_private_draft_page(text,uuid,text,integer) to authenticated;

create index memoir_checkpoint_recent_progress on public.user_memoir_checkpoint(lane_id,created_at desc);
alter function public.read_lifetime_private_draft_head(text,text) rename to read_lifetime_private_draft_head_before_progress;
revoke all on function public.read_lifetime_private_draft_head_before_progress(text,text) from public,anon,authenticated,service_role;
create function public.read_lifetime_private_draft_head(p_project_id text,p_locale text) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare result jsonb;lane public.user_memoir_lane%rowtype;progress jsonb;phase text;target bigint;rounds bigint;state text;
begin
 result:=public.read_lifetime_private_draft_head_before_progress(p_project_id,p_locale);
 if result is null then return null;end if;
 select * into lane from public.user_memoir_lane where user_id=auth.uid() and project_id=p_project_id and skill='composer';
 select coalesce(max(ordinal),0) into rounds from public.user_completed_round where user_id=auth.uid() and project_id=p_project_id;
 target:=greatest(coalesce(lane.target_milestone,0),(rounds/5)*5);
 if target<5 then return result;end if;
 progress:=public.memoir_lane_progress(lane);state:=progress->>'state';
 if state='finished' and coalesce((result->>'coverage_round')::bigint,0)<target then state:='pending';end if;
 select c.value->>'phase' into phase from public.user_memoir_checkpoint c join public.user_lifetime_lane_snapshot root on root.id=c.lifetime_snapshot_id
  where c.lane_id=lane.id and c.kind='compose' and root.state='pending' and root.locale=coalesce(p_locale,result->>'locale')
  order by c.created_at desc limit 1;
 if phase not in ('summarizing','drafting','reviewing','saving') then phase:=null;end if;
 progress:=progress||jsonb_build_object('state',state,'target_milestone',target);
 return result||jsonb_build_object('background_progress',jsonb_build_object('state',state,'phase',phase,'target_milestone',target),
  'progress',jsonb_build_object('composition',progress),'updating',state in ('pending','running'));
end $$;
revoke all on function public.read_lifetime_private_draft_head(text,text) from public,anon;
grant execute on function public.read_lifetime_private_draft_head(text,text) to authenticated;
notify pgrst,'reload schema';
commit;
