-- Selected saved progressive writing is an editorial task, independent of
-- canonical event/message cursors. Preserve bounded evidence and SQL publication.
begin;
create or replace function public.read_lifetime_memoir_lane_page_before_batches(p_lane_id uuid,p_token uuid) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare page jsonb; request public.user_workspace_section_rework%rowtype;
 snap public.user_lifetime_lane_snapshot%rowtype;
begin
 snap:=public.lock_lifetime_memoir_lane(p_lane_id,p_token);
 -- Editorial partitions can predate the predecessor's canonical watermark.
 -- Start the cursor before those explicit tasks, retaining base_event so only
 -- canonical deltas and the selected editorial partitions are visited.
 if snap.page_number=0 and exists(select 1 from public.user_memoir_lane where id=p_lane_id and skill='composer')
   and exists(select 1 from public.user_workspace_section_rework
   where user_id=snap.user_id and project_id=snap.project_id and locale=snap.locale and status='pending' and partition_key not like 'progressive:%') then
   update public.user_lifetime_lane_snapshot set last_event=0,last_event_id='',last_ref='' where id=snap.id;
 end if;
 page:=public.read_lifetime_memoir_lane_page_before_rework(p_lane_id,p_token);
 select * into request from public.user_workspace_section_rework where user_id=(page->>'user_id')::uuid
   and project_id=page->>'project_id' and locale=page->>'locale' and partition_key=page->>'partition_key'
   and event_revision=(page->'partition'->>'revision')::bigint and source_version=(page->'source'->>'version')::bigint and status='pending';
 page:=page-'input_digest'-'page_digest';
 if found then
   page:=page||jsonb_build_object('reuse',false,'editorial_request',jsonb_build_object('schema_version',1,'request_id',request.request_id,'instruction',request.instruction,'original_preview',request.original_preview));
 else page:=page||jsonb_build_object('editorial_request',null);end if;
 page:=page||jsonb_build_object('input_digest',encode(sha256(convert_to((page-'token')::text,'UTF8')),'hex'));
 return page||jsonb_build_object('page_digest',encode(sha256(convert_to(page::text,'UTF8')),'hex'));
end $$;

create or replace function public.read_lifetime_memoir_lane_page_before_summary_windows(p_lane_id uuid,p_token uuid) returns jsonb
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
     where request.user_id=snap.user_id and request.project_id=snap.project_id and request.locale=snap.locale and request.event_id=e.id and request.status='pending' and request.partition_key not like 'progressive:%')) and e.change_sequence<=snap.event_high_water
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

create or replace function public.claim_memoir_lane(p_lane_id uuid,p_run_seconds integer default 300) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare lane public.user_memoir_lane%rowtype; identity public.user_lifetime_conversation%rowtype;
 project public.user_memoir_project%rowtype; snap public.user_lifetime_lane_snapshot%rowtype;
 previous public.user_lifetime_lane_snapshot%rowtype; run_token uuid:=gen_random_uuid(); rounds bigint; seed text; pins jsonb; privacy_hash text; previous_owner text;
begin
 if p_run_seconds is null or p_run_seconds not between 1 and 1800 then raise exception 'invalid run duration';end if;
 select * into lane from public.user_memoir_lane where id=p_lane_id;
 if not found then return null;end if;
 select * into identity from public.user_lifetime_conversation where user_id=lane.user_id and project_id=lane.project_id;
 if not found then return public.claim_memoir_lane_legacy_lifetime(p_lane_id,p_run_seconds);end if;
 select * into project from public.user_memoir_project where user_id=lane.user_id and project_id=lane.project_id for update;
 perform 1 from public.user_profile where user_id=lane.user_id for share;
 select * into identity from public.user_lifetime_conversation where user_id=lane.user_id and project_id=lane.project_id for share;
 select * into lane from public.user_memoir_lane where id=p_lane_id for update;
 if lane.token is not null and lane.lease_until>clock_timestamp() and lane.run_deadline>clock_timestamp() then return null;end if;
 if not lane.pending and lane.token is null or lane.available_at>clock_timestamp() or lane.attempts>=3 then return null;end if;
 if lane.skill='composer' and not exists(select 1 from public.user_lifetime_lane_snapshot where lane_id=lane.id and state in ('completed','proposed'))
   and (exists(select 1 from public.user_memoir_manuscript where user_id=lane.user_id and project_id=lane.project_id and locale=lane.locale
       and (bundle is not null or reuse is not null)) or exists(select 1 from public.user_memoir_section_revision
       where user_id=lane.user_id and project_id=lane.project_id and locale=lane.locale)) then
   update public.user_memoir_lane set pending=true,token=null,lease_until=null,run_deadline=null,
     error='LIFETIME_LEGACY_MANUSCRIPT_MIGRATION_REQUIRED',available_at=clock_timestamp()+interval '5 minutes' where id=lane.id;
   return null;
 end if;
 previous_owner:=current_setting('request.jwt.claim.sub',true);
 perform set_config('request.jwt.claim.sub',lane.user_id::text,true);
 pins:=public.read_lifetime_pinned(identity.conversation_id);
 perform set_config('request.jwt.claim.sub',coalesce(previous_owner,''),true);
 privacy_hash:=encode(sha256(convert_to(jsonb_build_object('excluded_topics',pins->'excluded_topics',
   'paused_topics',pins->'paused_topics','privacy_complete',pins->'privacy_complete')::text,'UTF8')),'hex');
 select coalesce(max(ordinal),0) into rounds from public.user_completed_round where user_id=lane.user_id and project_id=lane.project_id;
 if lane.skill='composer' and (rounds<lane.target_milestone or lane.target_milestone=0 or exists(select 1 from public.user_narrator_source
   where user_id=lane.user_id and project_id=lane.project_id and status='active' and processing_status<>'succeeded')) then return null;end if;
 update public.user_lifetime_lane_snapshot set state='stale' where lane_id=lane.id and state='pending' and
   (policy_epoch<>project.policy_epoch or preference_revision<>identity.preference_revision or locale<>lane.locale
    or (lane.skill='composer' and event_high_water<>project.event_sequence));
 select * into snap from public.user_lifetime_lane_snapshot where lane_id=lane.id and state='pending' order by created_at desc limit 1;
 if not found then
   select * into previous from public.user_lifetime_lane_snapshot where lane_id=lane.id and locale=lane.locale and state='completed' order by created_at desc limit 1;
   seed:=jsonb_build_object('owner',lane.user_id,'project',lane.project_id,'conversation',identity.conversation_id,
     'policy',project.policy_epoch,'preferences',identity.preference_revision,'privacy_digest',privacy_hash,'source',project.source_sequence,
     'events',project.event_sequence,'predecessor',previous.id,'predecessor_digest',previous.root_digest)::text;
   insert into public.user_lifetime_lane_snapshot(lane_id,user_id,project_id,conversation_id,policy_epoch,preference_revision,privacy_digest,locale,
     source_high_water,event_high_water,round_high_water,milestone,base_revision,predecessor,base_event,last_event,root_digest)
   values(lane.id,lane.user_id,lane.project_id,identity.conversation_id,project.policy_epoch,identity.preference_revision,privacy_hash,lane.locale,
     project.source_sequence,project.event_sequence,rounds,lane.target_milestone,
     coalesce((select revision from public.user_memoir_manuscript where user_id=lane.user_id and project_id=lane.project_id and locale=lane.locale),0),
     previous.id,case when previous.preference_revision=identity.preference_revision and previous.policy_epoch=project.policy_epoch and previous.locale=lane.locale then previous.event_high_water else 0 end,
     case when previous.preference_revision=identity.preference_revision and previous.policy_epoch=project.policy_epoch and previous.locale=lane.locale then previous.event_high_water else 0 end,
     encode(sha256(convert_to(seed,'UTF8')),'hex')) returning * into snap;
 end if;
 update public.user_memoir_lane set token=run_token,lease_until=least(clock_timestamp()+interval '60 seconds',clock_timestamp()+make_interval(secs=>p_run_seconds)),
   run_deadline=clock_timestamp()+make_interval(secs=>p_run_seconds),pending=false,active_manifest='[]',active_events='[]',
   active_policy=snap.policy_epoch,active_through=snap.source_high_water,active_event=snap.event_high_water,
   active_round=snap.round_high_water,active_milestone=snap.milestone,active_locale=snap.locale,
   active_manuscript_revision=snap.base_revision,attempts=attempts+1,error=null where id=lane.id;
 return public.read_lifetime_memoir_lane_page(lane.id,run_token);
end $$;

-- A stored writing identity is required; an arbitrary progressive prefix is
-- never sufficient. Validate every original dependency, not only the first.
create function public.workspace_progressive_section_current(s public.user_lifetime_memoir_section) returns boolean
language sql stable security definer set search_path=public,auth as $$
 select s.partition_key like 'progressive:%' and not s.retired and s.bundle ? 'preview'
 and jsonb_array_length(s.source_dependencies)>0 and jsonb_array_length(s.event_dependencies)>0
 and exists(select 1 from public.user_lifetime_lane_snapshot root
   join public.user_memoir_project p on p.user_id=root.user_id and p.project_id=root.project_id
   join public.user_lifetime_conversation c on c.user_id=p.user_id and c.project_id=p.project_id
   where root.id=s.snapshot_id and root.state in ('completed','proposed')
     and root.policy_epoch=p.policy_epoch and root.preference_revision=c.preference_revision)
 and not exists(select 1 from jsonb_array_elements(s.source_dependencies) d where not exists(
   select 1 from public.user_narrator_source n where n.user_id=s.user_id and n.project_id=s.project_id
     and n.id::text=d->>'id' and n.version::text=d->>'version' and n.status='active'))
 and not exists(select 1 from jsonb_array_elements(s.event_dependencies) d where not exists(
   select 1 from public.user_memory_event e where e.user_id=s.user_id and e.project_id=s.project_id
     and e.id=d->>'id' and e.revision::text=d->>'revision' and e.status='active'))
$$;
revoke all on function public.workspace_progressive_section_current(public.user_lifetime_memoir_section) from public,anon,authenticated,service_role;

alter function public.workspace_rework_partition_current(uuid,text,text,text) rename to workspace_rework_partition_current_before_progressive;
revoke all on function public.workspace_rework_partition_current_before_progressive(uuid,text,text,text) from public,anon,authenticated,service_role;
create function public.workspace_rework_partition_current(p_owner uuid,p_project_id text,p_event_id text,p_partition_key text) returns boolean
language sql stable security definer set search_path=public,auth as $$
 select case when p_partition_key like 'progressive:%' then exists(
   select 1 from public.user_lifetime_memoir_section s where s.user_id=p_owner and s.project_id=p_project_id
     and s.event_id=p_event_id and s.partition_key=p_partition_key and public.workspace_progressive_section_current(s))
 else public.workspace_rework_partition_current_before_progressive(p_owner,p_project_id,p_event_id,p_partition_key) end
$$;
revoke all on function public.workspace_rework_partition_current(uuid,text,text,text) from public,anon,authenticated;

alter function public.read_lifetime_memoir_lane_page(uuid,uuid) rename to read_lifetime_memoir_lane_page_before_progressive_rework;
revoke all on function public.read_lifetime_memoir_lane_page_before_progressive_rework(uuid,uuid) from public,anon,authenticated,service_role;
create function public.read_lifetime_memoir_lane_page(p_lane_id uuid,p_token uuid) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare page jsonb; snap public.user_lifetime_lane_snapshot%rowtype; request public.user_workspace_section_rework%rowtype;
 section public.user_lifetime_memoir_section%rowtype; ref jsonb; evidence record; s jsonb; ev jsonb;
 sources jsonb:='[]'; events jsonb:='[]'; refs jsonb; previous jsonb; lo integer; hi integer; old jsonb; idx integer;
begin
 page:=public.read_lifetime_memoir_lane_page_before_progressive_rework(p_lane_id,p_token);
 if not(page ? 'batch') then return page;end if;
 snap:=public.lock_lifetime_memoir_lane(p_lane_id,p_token);
 -- Recover tasks stranded before an invalidation trigger was installed. An
 -- old instruction is never rebound to a newer privacy/preference authority.
 delete from public.user_workspace_section_rework obsolete where obsolete.user_id=snap.user_id
   and obsolete.project_id=snap.project_id and obsolete.locale=snap.locale and obsolete.status='pending'
   and obsolete.partition_key like 'progressive:%' and (not public.workspace_rework_partition_current(
     obsolete.user_id,obsolete.project_id,obsolete.event_id,obsolete.partition_key) or not exists(
       select 1 from public.user_lifetime_lane_snapshot original where original.id=obsolete.snapshot_id
        and original.policy_epoch=snap.policy_epoch and original.preference_revision=snap.preference_revision));
 select * into request from public.user_workspace_section_rework where user_id=snap.user_id and project_id=snap.project_id
   and locale=snap.locale and status='pending' and partition_key like 'progressive:%'
   and composed_snapshot_id is distinct from snap.id
   order by (select change_sequence from public.user_memory_event e where e.user_id=snap.user_id and e.project_id=snap.project_id and e.id=event_id),event_id,partition_key,request_id limit 1;
 if not found then return page;end if;
 select s.* into section from public.user_lifetime_memoir_section s join public.user_lifetime_lane_snapshot root on root.id=s.snapshot_id
   where s.user_id=request.user_id and s.project_id=request.project_id and s.locale=request.locale and s.partition_key=request.partition_key
     and root.created_at<=(select created_at from public.user_lifetime_lane_snapshot where id=request.snapshot_id)
     and root.state in ('completed','proposed') order by root.created_at desc limit 1;
 if not found or not public.workspace_progressive_section_current(section) then
   raise exception 'selected writing evidence changed' using errcode='PT409';end if;
 -- Include only references actually used by the selected writing and its
 -- heading. Each must still be contained in current canonical event evidence.
 for ref in select distinct r from jsonb_array_elements(section.bundle->'sections') item,
   jsonb_array_elements(item->'source_refs') r loop
   lo:=(ref->>'char_start')::integer;hi:=(ref->>'char_end')::integer;
   if lo is null or hi is null then raise exception 'selected writing requires exact evidence spans';end if;
   s:=public.lifetime_composer_source(snap.user_id,snap.project_id,(ref->>'source_id')::uuid,(ref->>'version')::bigint,lo,hi);
   select ordinality::integer-1,value into idx,old from jsonb_array_elements(sources) with ordinality where value->>'id'=s->>'id';
   if idx is null then sources:=sources||jsonb_build_array(s);
   else
     s:=public.lifetime_composer_source(snap.user_id,snap.project_id,(ref->>'source_id')::uuid,(ref->>'version')::bigint,
       least(lo,(old->>'char_start')::integer),greatest(hi,(old->>'char_end')::integer));
     sources:=jsonb_set(sources,array[idx::text],s);
   end if;
 end loop;
 for evidence in select e.* from public.user_memory_event e where e.user_id=snap.user_id and e.project_id=snap.project_id
   and exists(select 1 from jsonb_array_elements(section.event_dependencies) d where d->>'id'=e.id and d->>'revision'=e.revision::text) loop
   select coalesce(jsonb_agg(r),'[]') into refs from (select distinct r from jsonb_array_elements(section.bundle->'sections') item,
     jsonb_array_elements(item->'source_refs') r where item->'event_ids' ? evidence.id) selected;
   if exists(select 1 from jsonb_array_elements(refs) r where not exists(select 1 from public.user_memory_event_source original
      where original.user_id=snap.user_id and original.project_id=snap.project_id and original.event_id=evidence.id
       and original.source_id::text=r->>'source_id' and original.source_version::text=r->>'version'
       and coalesce((original.evidence->>'char_start')::integer,(select strpos(text,original.evidence->>'quote')-1 from public.user_narrator_source where user_id=snap.user_id and project_id=snap.project_id and id=original.source_id))<=(r->>'char_start')::integer
       and coalesce((original.evidence->>'char_end')::integer,(select strpos(text,original.evidence->>'quote')-1+length(original.evidence->>'quote') from public.user_narrator_source where user_id=snap.user_id and project_id=snap.project_id and id=original.source_id))>=(r->>'char_end')::integer
       and substring((select text from public.user_narrator_source where user_id=snap.user_id and project_id=snap.project_id and id=original.source_id)
         from (r->>'char_start')::integer+1 for (r->>'char_end')::integer-(r->>'char_start')::integer)<>''
       and strpos(original.evidence->>'quote',substring((select text from public.user_narrator_source where user_id=snap.user_id and project_id=snap.project_id and id=original.source_id)
         from (r->>'char_start')::integer+1 for (r->>'char_end')::integer-(r->>'char_start')::integer))>0)) then
      raise exception 'selected writing outside canonical evidence' using errcode='PT409';end if;
   -- Match the normal batch event shape; references retain their exact quote.
   select jsonb_agg(r||jsonb_build_object('quote',substring(n.text from (r->>'char_start')::integer+1 for (r->>'char_end')::integer-(r->>'char_start')::integer)))
     into refs from jsonb_array_elements(refs) r join public.user_narrator_source n on n.user_id=snap.user_id and n.project_id=snap.project_id and n.id::text=r->>'source_id';
   ev:=jsonb_build_object('id',evidence.id,'revision',evidence.revision,'kind',evidence.kind,'status',evidence.status,'life_stage',evidence.life_stage,
     'change_sequence',evidence.change_sequence,'title',left(evidence.data->>'title',300),'temporal',coalesce(evidence.data->'temporal','{}'),'source_refs',refs,'photo_associations','[]'::jsonb);
   events:=events||jsonb_build_array(ev);
 end loop;
 if jsonb_array_length(sources) not between 1 and 16 or jsonb_array_length(events) not between 1 and 8 then
   raise exception 'selected writing exceeds bounded editorial context' using errcode='22023';end if;
 previous:=jsonb_build_object('kind',section.bundle->>'kind','sections',section.bundle->'sections',
   'event_manifest',section.event_dependencies,'content_config',section.composition_config,
   'photo_association_manifest',coalesce(section.bundle->'photo_association_manifest','{}'::jsonb));
 page:=jsonb_set(page,'{batch,new_messages}','[]'::jsonb);
 page:=jsonb_set(page,'{batch,starting_after}',to_jsonb(snap.last_source));
 page:=jsonb_set(page,'{batch,through_source}',to_jsonb(snap.last_source));
 page:=jsonb_set(page,'{batch,next_offset}',to_jsonb(snap.next_offset));
 page:=jsonb_set(page,'{batch,cursor}',jsonb_build_array(snap.last_event,snap.last_event_id,snap.last_ref));
 page:=jsonb_set(page,'{batch,sources}',sources);page:=jsonb_set(page,'{batch,events}',events);
 page:=jsonb_set(page,'{batch,previous}',previous);
 page:=page||jsonb_build_object('complete',false,'reuse',false,'partition_key',request.partition_key,
   'partition',(select value from jsonb_array_elements(events) where value->>'id'=section.event_id),
   'source',sources->0,'editorial_request',jsonb_build_object('schema_version',1,'request_id',request.request_id,
      'instruction',request.instruction,'original_preview',request.original_preview));
 if octet_length((page->'batch')::text)>45000 then raise exception 'selected writing exceeds bounded editorial context' using errcode='22023';end if;
 page:=page-'input_digest'-'page_digest';
 page:=page||jsonb_build_object('input_digest',encode(sha256(convert_to((page-'token')::text,'UTF8')),'hex'));
 return page||jsonb_build_object('page_digest',encode(sha256(convert_to(page::text,'UTF8')),'hex'));
end $$;
revoke all on function public.read_lifetime_memoir_lane_page(uuid,uuid) from public,anon,authenticated;
grant execute on function public.read_lifetime_memoir_lane_page(uuid,uuid) to service_role;

create or replace function public.commit_lifetime_memoir_lane_page_before_summary_windows(p_lane_id uuid,p_token uuid,p_page_number bigint,p_result jsonb,p_page_digest text) returns jsonb
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
  raise exception 'progressive replay conflict' using errcode='PT409';
 end if;
 if p_page_number<>snap.page_number or p_page_digest is distinct from page->>'page_digest' then raise exception 'stale progressive batch' using errcode='PT409';end if;
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
   key:=case when page->'editorial_request'<>'null'::jsonb and page->>'partition_key' like 'progressive:%'
     then page->>'partition_key' else 'progressive:'||(e->>'id')||':'||(item->>'id') end;
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

alter function public.commit_lifetime_memoir_lane_page(uuid,uuid,bigint,jsonb,text) rename to commit_lifetime_memoir_lane_page_before_progressive_rework;
revoke all on function public.commit_lifetime_memoir_lane_page_before_progressive_rework(uuid,uuid,bigint,jsonb,text) from public,anon,authenticated,service_role;
create function public.commit_lifetime_memoir_lane_page(p_lane_id uuid,p_token uuid,p_page_number bigint,p_result jsonb,p_page_digest text) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare page jsonb; result jsonb; block jsonb; original jsonb; ref jsonb;
begin
 page:=public.read_lifetime_memoir_lane_page(p_lane_id,p_token);
 if p_page_number=(page->>'page_number')::bigint and page->'editorial_request'<>'null'::jsonb
   and page->>'partition_key' like 'progressive:%' then
   if (select count(*) from jsonb_array_elements(p_result->'sections') item where item ? 'block')<>1 then
     raise exception 'editorial result must contain only the selected writing';end if;
   select value into block from jsonb_array_elements(p_result->'sections') where value ? 'block';
   select value into original from jsonb_array_elements(page->'batch'->'previous'->'sections') where value ? 'block';
   if block->'event_ids'->>0 is distinct from page->'partition'->>'id' or exists(
      select 1 from jsonb_array_elements_text(block->'event_ids') id where not(original->'event_ids' ? id)) then
     raise exception 'editorial result changes the selected event scope';end if;
   for ref in select value from jsonb_array_elements(block->'source_refs') loop
     if not exists(select 1 from jsonb_array_elements(original->'source_refs') prior
        where prior->>'source_id'=ref->>'source_id' and prior->>'version'=ref->>'version'
          and (prior->>'char_start')::integer<=(ref->>'char_start')::integer
          and (prior->>'char_end')::integer>=(ref->>'char_end')::integer) then
       raise exception 'editorial result widens the selected original evidence';end if;
   end loop;
 end if;
 result:=public.commit_lifetime_memoir_lane_page_before_progressive_rework(p_lane_id,p_token,p_page_number,p_result,p_page_digest);
 if p_page_number=(page->>'page_number')::bigint and page->'editorial_request'<>'null'::jsonb then
   update public.user_workspace_section_rework set composed_snapshot_id=(page->>'snapshot_id')::uuid
     where user_id=(page->>'user_id')::uuid and project_id=page->>'project_id'
       and request_id=(page->'editorial_request'->>'request_id')::uuid;
 end if;
 return result;
end $$;
revoke all on function public.commit_lifetime_memoir_lane_page(uuid,uuid,bigint,jsonb,text) from public,anon,authenticated;
grant execute on function public.commit_lifetime_memoir_lane_page(uuid,uuid,bigint,jsonb,text) to service_role;
notify pgrst,'reload schema';
commit;
