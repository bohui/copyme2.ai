-- Bounded canonical lanes. Only exact page partitions cross the worker boundary.
-- Roots attest durable delta coverage against a predecessor; prose is paged,
-- never concatenated into a lifetime-sized request or a false whole snapshot.
begin;
alter table public.user_memoir_project add column draft_revision bigint not null default 0;
-- Separate presentation revision: accepting prose does not revoke testimony or
-- churn collector policy. The unchanged read guard exact-compares this field.
alter function public.capture_lifetime_read_fence(text) rename to capture_lifetime_read_fence_before_drafts;
revoke all on function public.capture_lifetime_read_fence_before_drafts(text) from public,anon,authenticated,service_role;
create function public.capture_lifetime_read_fence(p_project_id text) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare fence jsonb;
begin
 fence:=public.capture_lifetime_read_fence_before_drafts(p_project_id);
 return fence||(select jsonb_build_object('draft_revision',draft_revision,'event_revision',event_sequence)
   from public.user_memoir_project where user_id=auth.uid() and project_id=p_project_id);
end $$;
revoke all on function public.capture_lifetime_read_fence(text) from public,anon;
grant execute on function public.capture_lifetime_read_fence(text) to authenticated;

create table public.user_lifetime_lane_snapshot (
 id uuid primary key default gen_random_uuid(), lane_id uuid not null references public.user_memoir_lane(id) on delete cascade,
 user_id uuid not null, project_id text not null, conversation_id uuid not null,
 policy_epoch bigint not null, preference_revision bigint not null, privacy_digest text not null, locale text not null,
 source_high_water bigint not null, event_high_water bigint not null, round_high_water bigint not null,
 milestone bigint not null, base_revision bigint not null, predecessor uuid references public.user_lifetime_lane_snapshot(id),
 base_event bigint not null default 0, last_source bigint not null default 0, next_offset integer not null default 0,
 last_event bigint not null default 0, last_event_id text not null default '', last_ref text not null default '',
 page_number bigint not null default 0, root_digest text not null,
 state text not null default 'pending' check(state in ('pending','completed','proposed','stale')),
 created_at timestamptz not null default clock_timestamp(),
 foreign key(user_id,conversation_id) references public.user_lifetime_conversation(user_id,conversation_id) on delete cascade
);
create function public.advance_lifetime_draft_publication() returns trigger
language plpgsql security definer set search_path=public,auth as $$
begin
 if tg_table_name='user_lifetime_lane_snapshot' then
   if not (coalesce(old.state,'') in ('completed','proposed') or coalesce(new.state,'') in ('completed','proposed')) then
     return coalesce(new,old);
   end if;
 end if;
 if tg_op<>'UPDATE' or old is distinct from new then
   update public.user_memoir_project set draft_revision=draft_revision+1
     where user_id=coalesce(new.user_id,old.user_id) and project_id=coalesce(new.project_id,old.project_id);
 end if;
 return coalesce(new,old);
end $$;
create trigger lifetime_root_publication_revision after insert or update or delete on public.user_lifetime_lane_snapshot
 for each row execute function public.advance_lifetime_draft_publication();
create trigger lifetime_manuscript_publication_revision after insert or update or delete on public.user_memoir_manuscript
 for each row execute function public.advance_lifetime_draft_publication();
revoke all on function public.advance_lifetime_draft_publication() from public,anon,authenticated;

create index lifetime_lane_pending on public.user_lifetime_lane_snapshot(lane_id,created_at desc);
create table public.user_lifetime_memoir_section (
 user_id uuid not null,project_id text not null,locale text not null,partition_key text not null,
 event_id text not null,event_revision bigint not null,source_id uuid not null,source_version bigint not null,
 char_start integer not null,char_end integer not null,evidence_hash text not null,
 snapshot_id uuid not null references public.user_lifetime_lane_snapshot(id) on delete cascade,
 bundle jsonb not null,approved boolean not null default false,human_locked boolean not null default false,proposal jsonb,
 primary key(user_id,project_id,locale,partition_key,snapshot_id),
 foreign key(user_id,project_id) references public.user_memoir_project(user_id,project_id) on delete cascade
);
create index lifetime_section_order on public.user_lifetime_memoir_section(user_id,project_id,locale,partition_key);
create index lifetime_section_source on public.user_lifetime_memoir_section(user_id,project_id,source_id);
create index lifetime_section_event on public.user_lifetime_memoir_section(user_id,project_id,event_id);
alter table public.user_lifetime_lane_snapshot enable row level security;
alter table public.user_lifetime_memoir_section enable row level security;
revoke all on public.user_lifetime_lane_snapshot,public.user_lifetime_memoir_section from public,anon,authenticated;

-- Source windows have a stable version-scoped cursor independent of a
-- disposable lane epoch, so policy invalidation cannot extract a prefix twice.
create table public.user_lifetime_source_extraction (
 user_id uuid not null,project_id text not null,source_id uuid not null,source_version bigint not null,next_offset integer not null,
 primary key(user_id,project_id,source_id,source_version),
 foreign key(user_id,project_id,source_id) references public.user_narrator_source(user_id,project_id,id) on delete cascade
);
alter table public.user_lifetime_source_extraction enable row level security;
revoke all on public.user_lifetime_source_extraction from public,anon,authenticated;

-- Do not fossilize restricted bytes in append-only composer bookkeeping.
-- Withdrawals/corrections retain unrelated protected sections byte-for-byte.
create function public.invalidate_lifetime_lane_event() returns trigger
language plpgsql security definer set search_path=public,auth as $$
begin
 if tg_op='DELETE' or new.status='withdrawn' then
   delete from public.user_lifetime_memoir_section where user_id=old.user_id and project_id=old.project_id and event_id=old.id;
 elsif old.revision is distinct from new.revision or old.status is distinct from new.status then
   -- Ordinary evidence additions do not revoke protected original prose.
   -- Policy-invalidated projections are discarded; the source trigger below
   -- independently covers source mutations before their policy epoch advances.
   delete from public.user_lifetime_memoir_section section using public.user_lifetime_lane_snapshot root,public.user_memoir_project project
     where section.snapshot_id=root.id and section.user_id=old.user_id and section.project_id=old.project_id and section.event_id=old.id
       and project.user_id=old.user_id and project.project_id=old.project_id and root.policy_epoch<>project.policy_epoch;
 end if;
 return coalesce(new,old);
end $$;
create trigger lifetime_lane_event_invalidation after update or delete on public.user_memory_event
 for each row execute function public.invalidate_lifetime_lane_event();
revoke all on function public.invalidate_lifetime_lane_event() from public,anon,authenticated;

-- Source mutators may revise affected events before bumping project policy.
-- Invalidate by the exact dependency at the source boundary, independent of
-- that ordering, including every protected copy and pending proposal.
create function public.invalidate_lifetime_lane_source() returns trigger
language plpgsql security definer set search_path=public,auth as $$
begin
 if tg_op='DELETE' or old.version is distinct from new.version or old.status is distinct from new.status then
   delete from public.user_lifetime_memoir_section where user_id=old.user_id and project_id=old.project_id and source_id=old.id;
 end if;
 return coalesce(new,old);
end $$;
create trigger lifetime_lane_source_invalidation after update or delete on public.user_narrator_source
 for each row execute function public.invalidate_lifetime_lane_source();
revoke all on function public.invalidate_lifetime_lane_source() from public,anon,authenticated;

create function public.lock_lifetime_memoir_lane(p_lane_id uuid,p_token uuid) returns public.user_lifetime_lane_snapshot
language plpgsql security definer set search_path=public,auth as $$
declare lane public.user_memoir_lane%rowtype; snapshot public.user_lifetime_lane_snapshot%rowtype;
 identity public.user_lifetime_conversation%rowtype; project public.user_memoir_project%rowtype;
begin
 select * into lane from public.user_memoir_lane where id=p_lane_id;
 if not found then raise exception 'canonical lane unavailable' using errcode='40001';end if;
 select * into project from public.user_memoir_project where user_id=lane.user_id and project_id=lane.project_id for update;
 perform 1 from public.user_profile where user_id=lane.user_id for share;
 select * into identity from public.user_lifetime_conversation where user_id=lane.user_id and project_id=lane.project_id for share;
 select * into lane from public.user_memoir_lane where id=p_lane_id for update;
 select * into snapshot from public.user_lifetime_lane_snapshot where lane_id=lane.id and state='pending' order by created_at desc limit 1 for update;
 if snapshot.id is null or lane.token is null or lane.token is distinct from p_token or lane.lease_until<=clock_timestamp()
   or lane.run_deadline<=clock_timestamp() or snapshot.policy_epoch<>project.policy_epoch
   or snapshot.preference_revision<>identity.preference_revision or snapshot.locale<>lane.active_locale
   or (lane.skill='composer' and snapshot.event_high_water<>project.event_sequence) then
   raise exception 'stale canonical lane page' using errcode='40001';
 end if;
 return snapshot;
end $$;
revoke all on function public.lock_lifetime_memoir_lane(uuid,uuid) from public,anon,authenticated,service_role;

create function public.read_lifetime_memoir_lane_page(p_lane_id uuid,p_token uuid) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare snap public.user_lifetime_lane_snapshot%rowtype; lane public.user_memoir_lane%rowtype;
 source public.user_narrator_source%rowtype; event public.user_memory_event%rowtype; link record;
 payload jsonb; source_data jsonb; event_data jsonb; candidates jsonb:='[]'; preferences jsonb; ref jsonb;
 core integer; lo integer; hi integer; key text; reusable boolean:=false; previous_owner text;
begin
 snap:=public.lock_lifetime_memoir_lane(p_lane_id,p_token);
 select * into lane from public.user_memoir_lane where id=p_lane_id;
 previous_owner:=current_setting('request.jwt.claim.sub',true);
 perform set_config('request.jwt.claim.sub',snap.user_id::text,true);
 preferences:=public.read_lifetime_pinned(snap.conversation_id);
 -- Make optional transport defaults explicit without changing authoritative data.
 preferences:=jsonb_set(preferences,'{known_continuity}',coalesce((select jsonb_agg(
   jsonb_build_object('schema_version',1)||record||jsonb_build_object('data',
     jsonb_build_object('schema_version',1,'uncertainty',null)||(record->'data')||jsonb_build_object('source_refs',
       (select jsonb_agg(jsonb_build_object('schema_version',1)||continuity_ref) from jsonb_array_elements(record->'data'->'source_refs') continuity_ref))))
   from jsonb_array_elements(preferences->'known_continuity') record),'[]'));
 perform set_config('request.jwt.claim.sub',coalesce(previous_owner,''),true);
 payload:=jsonb_build_object('schema_version',1,'protocol','lifetime_composer_pages','lane_id',lane.id,'token',p_token,
   'snapshot_id',snap.id,'user_id',snap.user_id,'project_id',snap.project_id,'conversation_id',snap.conversation_id,
   'skill',lane.skill,'locale',snap.locale,'policy_epoch',snap.policy_epoch,'preference_revision',snap.preference_revision,
   'source_high_water',snap.source_high_water,'event_high_water',snap.event_high_water,'page_number',snap.page_number,
   'root_digest',snap.root_digest,'coverage_round',snap.round_high_water,'base_revision',snap.base_revision,
   'preferences',preferences,'previous',null,'reuse',false,'complete',false);
 if lane.skill='timeline' then
   select * into source from public.user_narrator_source where user_id=snap.user_id and project_id=snap.project_id
     and status='active' and processing_status<>'succeeded' and sequence<=snap.source_high_water
     and (sequence>snap.last_source or (sequence=snap.last_source and snap.next_offset<length(text)))
     order by sequence limit 1;
   if not found then return payload||jsonb_build_object('complete',true,'source',null,'events','[]'::jsonb,'partition',null);end if;
   core:=greatest(case when source.sequence=snap.last_source then snap.next_offset else 0 end,
     coalesce((select next_offset from public.user_lifetime_source_extraction where user_id=snap.user_id and project_id=snap.project_id
       and source_id=source.id and source_version=source.version),0));
   if core>=length(source.text) then core:=0;end if;
   lo:=greatest(core-256,0);hi:=least(core+2048,length(source.text));
   -- Indexed, bounded candidate pools. Preserve the current interview identity
   -- even when it is older than the recent tail; no full-event history sort.
   with active as (
     select e.id,0 priority from public.user_interview_plan p join public.user_memory_event e
       on e.user_id=p.user_id and e.project_id=p.project_id and e.id=p.plan->>'active_event_id'
     where p.user_id=snap.user_id and p.project_id=snap.project_id and e.status='active' and e.change_sequence<=snap.event_high_water
   ), same_source as (
     select e.id,1 priority from public.user_memory_event_source r join public.user_memory_event e
       on e.user_id=r.user_id and e.project_id=r.project_id and e.id=r.event_id
     where r.user_id=snap.user_id and r.project_id=snap.project_id and r.source_id=source.id
       and e.status<>'withdrawn' and e.change_sequence<=snap.event_high_water order by r.event_id limit 8
   ), recent as (
     select id,2 priority from public.user_memory_event where user_id=snap.user_id and project_id=snap.project_id
       and status<>'withdrawn' and change_sequence<=snap.event_high_water order by change_sequence desc,id desc limit 8
   ), selected as (
     select id,min(priority) priority from (select * from active union all select * from same_source union all select * from recent) pool group by id
   )
   select coalesce(jsonb_agg(item order by priority,change_sequence desc,id),'[]') into candidates from (
     select e.id,e.change_sequence,c.priority,jsonb_build_object('id',e.id,'revision',e.revision,'kind',e.kind,
       'title',left(e.data->>'title',300),'life_stage',e.life_stage,'status',e.status,'source_refs','[]'::jsonb,
       'identity_context_only',true,'active_interview_context',c.priority=0) item
     from selected c join public.user_memory_event e on e.user_id=snap.user_id and e.project_id=snap.project_id and e.id=c.id
     order by c.priority,e.change_sequence desc,e.id limit 8) bounded;
   source_data:=jsonb_build_object('id',source.id,'project_id',source.project_id,'version',source.version,'sequence',source.sequence,
     'text',substring(source.text from lo+1 for hi-lo),'char_start',lo,'char_end',hi,'original_length',length(source.text),
     'kind',source.kind,'language',source.language,'status',source.status,'author_role','storyteller');
   return payload||jsonb_build_object('source',source_data,'events',candidates,'partition',null,'core_start',core,'core_end',hi);
 end if;
 -- Keyset over event revisions and exact evidence rows, including unsupported
 -- or withdrawn events as explicit coverage dispositions. No aggregate manifest.
 select e.*,r.source_id,r.source_version,r.evidence_hash,r.evidence, p.id as photo_link_id,p.photo_id,p.quote as photo_quote,p.description as photo_description into link
   from public.user_memory_event e left join public.user_memory_event_source r
     on r.user_id=e.user_id and r.project_id=e.project_id and r.event_id=e.id
   left join public.user_interview_photo_link p on p.user_id=e.user_id and p.project_id=e.project_id and p.event_id=e.id
     and p.source_id=r.source_id and p.source_version=r.source_version and p.status='confirmed' and p.provenance='narrator_metadata'
     and strpos(r.evidence->>'quote',p.quote)>0 and public.interview_photo_available(e.user_id,e.project_id,p.photo_id)
   where e.user_id=snap.user_id and e.project_id=snap.project_id and e.change_sequence>snap.base_event
     and e.change_sequence<=snap.event_high_water
     and (e.change_sequence,e.id,coalesce(r.source_id::text||':'||r.source_version::text||':'||r.evidence_hash||':'||coalesce(p.id::text,''),''))>
       (snap.last_event,snap.last_event_id,snap.last_ref)
   order by e.change_sequence,e.id,coalesce(r.source_id::text||':'||r.source_version::text||':'||r.evidence_hash||':'||coalesce(p.id::text,''),'') limit 1;
 if not found then return payload||jsonb_build_object('complete',true,'source',null,'events','[]'::jsonb,'partition',null);end if;
 key:=coalesce(link.source_id::text||':'||link.source_version::text||':'||link.evidence_hash||':'||coalesce(link.photo_link_id::text,''),'');
 event_data:=jsonb_build_object('id',link.id,'revision',link.revision,'kind',link.kind,'life_stage',link.life_stage,
   'status',link.status,'change_sequence',link.change_sequence,'title',left(link.data->>'title',300),
   'uncertainty',left(link.data->>'uncertainty',2000),
   'temporal',jsonb_build_object('expression',left(link.data->'temporal'->>'expression',500),'precision','unknown'),
   'source_refs','[]'::jsonb);
 if link.status='active' and link.source_id is not null then
   select * into source from public.user_narrator_source where user_id=snap.user_id and project_id=snap.project_id
     and id=link.source_id and version=link.source_version and status='active';
   if found then
     ref:=link.evidence;lo:=coalesce((ref->>'char_start')::integer,strpos(source.text,ref->>'quote')-1);
     hi:=coalesce((ref->>'char_end')::integer,lo+length(ref->>'quote'));
     if lo<0 or hi<=lo or hi>length(source.text) or hi-lo>2000 or
       substring(source.text from lo+1 for hi-lo) is distinct from ref->>'quote' or
       (not ref ? 'char_start' and strpos(substring(source.text from lo+2),ref->>'quote')>0) then
       raise exception 'canonical evidence requires an exact unambiguous span' using errcode='22023';
     end if;
     ref:=ref||jsonb_build_object('char_start',lo,'char_end',hi);
     source_data:=jsonb_build_object('id',source.id,'project_id',source.project_id,'version',source.version,'sequence',source.sequence,
       'text',substring(source.text from lo+1 for hi-lo),'char_start',lo,'char_end',hi,'original_length',length(source.text),
       'kind',source.kind,'language',source.language,'status',source.status,'author_role','storyteller');
     event_data:=event_data||jsonb_build_object('source_refs',jsonb_build_array(ref),
       'photo_associations',case when link.photo_link_id is null then '[]'::jsonb else jsonb_build_array(jsonb_build_object(
         'id',link.photo_link_id,'photo_id',link.photo_id,'event_id',link.id,'source_id',source.id,'source_version',source.version,
         'quote',link.photo_quote,'description',link.photo_description,'status','confirmed','provenance','narrator_metadata')) end);
     select exists(select 1 from public.user_lifetime_memoir_section s join public.user_lifetime_lane_snapshot ss on ss.id=s.snapshot_id
       where s.user_id=snap.user_id and s.project_id=snap.project_id and s.locale=snap.locale
       and s.partition_key=link.id||':'||key and s.event_revision=link.revision and s.source_version=source.version
       and ss.state='completed' and ss.preference_revision=snap.preference_revision and ss.policy_epoch=snap.policy_epoch)
       into reusable;
   end if;
 end if;
 return payload||jsonb_build_object('source',source_data,'partition',event_data,'events','[]'::jsonb,
   'partition_key',link.id||':'||key,'ref_key',key,'reuse',reusable);
end $$;
revoke all on function public.read_lifetime_memoir_lane_page(uuid,uuid) from public,anon,authenticated;
grant execute on function public.read_lifetime_memoir_lane_page(uuid,uuid) to service_role;

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
   select * into previous from public.user_lifetime_lane_snapshot where lane_id=lane.id and state='completed' order by created_at desc limit 1;
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

-- A result receipt stores digests and dispositions, never another copy of prose.
create table public.user_lifetime_lane_page_receipt (
 snapshot_id uuid not null references public.user_lifetime_lane_snapshot(id) on delete cascade,
 page_number bigint not null,page_digest text not null,result_digest text not null,root_digest text not null,
 disposition text not null,primary key(snapshot_id,page_number)
);
alter table public.user_lifetime_lane_page_receipt enable row level security;
revoke all on public.user_lifetime_lane_page_receipt from public,anon,authenticated;

alter function public.read_lifetime_memoir_lane_page(uuid,uuid) rename to read_lifetime_memoir_lane_page_body;
revoke all on function public.read_lifetime_memoir_lane_page_body(uuid,uuid) from public,anon,authenticated,service_role;
create function public.read_lifetime_memoir_lane_page(p_lane_id uuid,p_token uuid) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare result jsonb;
begin
 result:=public.read_lifetime_memoir_lane_page_body(p_lane_id,p_token);
 -- The input identity survives lease renewal; the admission digest additionally
 -- binds the current token. Keep both authoritative and exactly compared.
 result:=result||jsonb_build_object('input_digest',encode(sha256(convert_to((result-'token')::text,'UTF8')),'hex'));
 return result||jsonb_build_object('page_digest',encode(sha256(convert_to(result::text,'UTF8')),'hex'));
end $$;
revoke all on function public.read_lifetime_memoir_lane_page(uuid,uuid) from public,anon,authenticated;
grant execute on function public.read_lifetime_memoir_lane_page(uuid,uuid) to service_role;

-- Per-page phase checkpoints carry their actual dependency, never the empty
-- legacy lane manifest. Existing exact source withdrawal purge remains valid.
alter table public.user_memoir_checkpoint add column lifetime_snapshot_id uuid,
 add column lifetime_page bigint,add column lifetime_policy bigint,add column lifetime_preference bigint,add column lifetime_input_digest text;
alter function public.read_memoir_checkpoint(uuid,uuid,text) rename to read_memoir_checkpoint_before_lifetime_pages;
alter function public.save_memoir_checkpoint(uuid,uuid,text,text,jsonb) rename to save_memoir_checkpoint_before_lifetime_pages;
revoke all on function public.read_memoir_checkpoint_before_lifetime_pages(uuid,uuid,text),
 public.save_memoir_checkpoint_before_lifetime_pages(uuid,uuid,text,text,jsonb) from public,anon,authenticated,service_role;
create function public.read_memoir_checkpoint(p_lane_id uuid,p_token uuid,p_key text) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare page jsonb;
begin
 if not exists(select 1 from public.user_memoir_lane l join public.user_lifetime_conversation c
   on c.user_id=l.user_id and c.project_id=l.project_id where l.id=p_lane_id) then
   return public.read_memoir_checkpoint_before_lifetime_pages(p_lane_id,p_token,p_key);
 end if;
 page:=public.read_lifetime_memoir_lane_page(p_lane_id,p_token);
 return (select value from public.user_memoir_checkpoint where lane_id=p_lane_id and key=p_key
   and lifetime_snapshot_id=(page->>'snapshot_id')::uuid and lifetime_page=(page->>'page_number')::bigint
   and lifetime_policy=(page->>'policy_epoch')::bigint and lifetime_preference=(page->>'preference_revision')::bigint
   and lifetime_input_digest=(page->>'input_digest')
   and created_at>clock_timestamp()-interval '7 days');
end $$;
create function public.save_memoir_checkpoint(p_lane_id uuid,p_token uuid,p_key text,p_kind text,p_value jsonb,p_page_digest text default null) returns boolean
language plpgsql security definer set search_path=public,auth as $$
declare page jsonb; sources jsonb; events jsonb;
begin
 if not exists(select 1 from public.user_memoir_lane l join public.user_lifetime_conversation c
   on c.user_id=l.user_id and c.project_id=l.project_id where l.id=p_lane_id) then
   return public.save_memoir_checkpoint_before_lifetime_pages(p_lane_id,p_token,p_key,p_kind,p_value);
 end if;
 page:=public.read_lifetime_memoir_lane_page(p_lane_id,p_token);
 if p_page_digest is distinct from page->>'page_digest' then raise exception 'stale phase checkpoint input' using errcode='40001';end if;
 if page->>'skill'<>'composer' or (page->>'complete')::boolean or page->'source'='null'::jsonb
   or p_key !~ '^[a-f0-9]{64}$' or p_kind not in ('prepare','compose') or jsonb_typeof(p_value) is distinct from 'object'
   or octet_length(p_value::text)>500000 then raise exception 'invalid bounded phase checkpoint' using errcode='22023';end if;
 sources:=jsonb_build_array(jsonb_build_object('id',page->'source'->>'id','version',page->'source'->'version'));
 events:=jsonb_build_array(jsonb_build_object('id',page->'partition'->>'id','revision',page->'partition'->'revision'));
 insert into public.user_memoir_checkpoint(lane_id,key,kind,value,source_manifest,event_manifest,
   lifetime_snapshot_id,lifetime_page,lifetime_policy,lifetime_preference,lifetime_input_digest)
 values(p_lane_id,p_key,p_kind,p_value,sources,events,(page->>'snapshot_id')::uuid,(page->>'page_number')::bigint,
   (page->>'policy_epoch')::bigint,(page->>'preference_revision')::bigint,(page->>'input_digest'))
 on conflict(lane_id,key) do update set value=excluded.value,source_manifest=excluded.source_manifest,event_manifest=excluded.event_manifest,
   lifetime_snapshot_id=excluded.lifetime_snapshot_id,lifetime_page=excluded.lifetime_page,lifetime_policy=excluded.lifetime_policy,
   lifetime_preference=excluded.lifetime_preference,lifetime_input_digest=excluded.lifetime_input_digest,created_at=clock_timestamp();
 return true;
end $$;
revoke all on function public.read_memoir_checkpoint(uuid,uuid,text),public.save_memoir_checkpoint(uuid,uuid,text,text,jsonb,text) from public,anon,authenticated;
grant execute on function public.read_memoir_checkpoint(uuid,uuid,text),public.save_memoir_checkpoint(uuid,uuid,text,text,jsonb,text) to service_role;

create table public.user_lifetime_lane_output (
 snapshot_id uuid not null references public.user_lifetime_lane_snapshot(id) on delete cascade,
 page_number bigint not null,phase text not null check(phase in ('extract','prepare','index','draft','review')),
 digest text not null check(digest ~ '^[0-9a-f]{64}$'),input_digest text not null check(input_digest ~ '^[0-9a-f]{64}$'),
 primary key(snapshot_id,page_number,phase,digest,input_digest)
);
alter table public.user_lifetime_lane_output enable row level security;
revoke all on public.user_lifetime_lane_output from public,anon,authenticated;
create function public.record_lifetime_lane_output(p_lane_id uuid,p_token uuid,p_page_number bigint,p_phase text,p_digest text,p_page_digest text) returns boolean
language plpgsql security definer set search_path=public,auth as $$
declare page jsonb;
begin
 page:=public.read_lifetime_memoir_lane_page(p_lane_id,p_token);
 if (page->>'page_number')::bigint is distinct from p_page_number or p_page_digest is distinct from page->>'page_digest' then
   raise exception 'stale derived lane output input' using errcode='40001';end if;
 insert into public.user_lifetime_lane_output(snapshot_id,page_number,phase,digest,input_digest)
 values((page->>'snapshot_id')::uuid,p_page_number,p_phase,p_digest,
   (page->>'input_digest')) on conflict do nothing;
 return true;
end $$;
revoke all on function public.record_lifetime_lane_output(uuid,uuid,bigint,text,text,text) from public,anon,authenticated;
grant execute on function public.record_lifetime_lane_output(uuid,uuid,bigint,text,text,text) to service_role;

create function public.lock_lifetime_memoir_lane_publication(p_fence jsonb) returns double precision
language plpgsql security definer set search_path=public,auth as $$
declare current_page jsonb; field text; proof jsonb; lane public.user_memoir_lane%rowtype;
begin
 if octet_length(p_fence::text)>65536 then raise exception 'bounded lane fence required';end if;
 if auth.uid() is null or auth.uid()::text is distinct from p_fence->>'user_id' then raise exception 'canonical lane owner mismatch' using errcode='42501';end if;
 current_page:=public.read_lifetime_memoir_lane_page((p_fence->>'lane_id')::uuid,(p_fence->>'token')::uuid);
 if (current_page->'preferences'->>'privacy_complete')::boolean is distinct from true then raise exception 'current privacy requires maintenance';end if;
 foreach field in array array['schema_version','protocol','lane_id','token','snapshot_id','user_id','project_id','conversation_id',
   'skill','locale','policy_epoch','preference_revision','source_high_water','event_high_water','page_number','root_digest','page_digest','input_digest','preferences','source','partition','events','coverage_round'] loop
   if p_fence->field is null or p_fence->field is distinct from current_page->field then
     raise exception 'stale canonical lane admission' using errcode='40001';end if;
 end loop;
 if jsonb_typeof(p_fence->'prior_outputs') is distinct from 'array' or jsonb_array_length(p_fence->'prior_outputs')>16 then raise exception 'bounded prior output proofs required';end if;
 for proof in select value from jsonb_array_elements(p_fence->'prior_outputs') loop
   if not exists(select 1 from public.user_lifetime_lane_output where snapshot_id=(current_page->>'snapshot_id')::uuid
      and page_number=(current_page->>'page_number')::bigint and phase=proof->>'phase' and digest=proof->>'digest'
      and input_digest=(current_page->>'input_digest')) then
     raise exception 'derived lane output belongs to another page' using errcode='40001';end if;
 end loop;
 select * into lane from public.user_memoir_lane where id=(p_fence->>'lane_id')::uuid;
 return greatest(0,extract(epoch from least(lane.lease_until,lane.run_deadline)-clock_timestamp()));
end $$;
revoke all on function public.lock_lifetime_memoir_lane_publication(jsonb) from public,anon,authenticated;
grant execute on function public.lock_lifetime_memoir_lane_publication(jsonb) to service_role,authenticated;

-- The existing canonical mutator, including attribution/uncertainty/correction
-- and photo reconciliation, remains authoritative. Its worker-only readback is
-- constant-sized, instead of materialising all originals/events twice per page.
alter function public.read_user_memory_events(text) rename to read_user_memory_events_before_lifetime_lane;
revoke all on function public.read_user_memory_events_before_lifetime_lane(text) from public,anon,authenticated,service_role;
create function public.read_user_memory_events(p_project_id text) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
begin
 if exists(select 1 from public.user_memoir_lane l join public.user_lifetime_conversation c
   on c.user_id=l.user_id and c.project_id=l.project_id where l.user_id=auth.uid() and l.project_id=p_project_id
     and l.id::text=current_setting('memoir.lifetime_lane',true) and l.token is not null and l.lease_until>clock_timestamp()) then
   return jsonb_build_object('schema_version',1,'project_id',p_project_id,'processing',jsonb_build_object('extracted_through',
     (select extraction_cursor from public.user_memoir_project where user_id=auth.uid() and project_id=p_project_id)));
 end if;
 return public.read_user_memory_events_before_lifetime_lane(p_project_id);
end $$;
revoke all on function public.read_user_memory_events(text) from public,anon;
grant execute on function public.read_user_memory_events(text) to authenticated;

create function public.commit_lifetime_memoir_lane_page(p_lane_id uuid,p_token uuid,p_page_number bigint,p_result jsonb,p_page_digest text) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare snap public.user_lifetime_lane_snapshot%rowtype; lane public.user_memoir_lane%rowtype;
 page jsonb; ref jsonb; section jsonb; item jsonb; result_hash text; new_root text; disposition text;
 prior public.user_lifetime_lane_page_receipt%rowtype; protected public.user_lifetime_memoir_section%rowtype; protected_safe boolean; manuscript_locked boolean:=false; source_id uuid; event_id text; current_source_version bigint;
 previous_setting text; previous_owner text;
begin
 snap:=public.lock_lifetime_memoir_lane(p_lane_id,p_token);
 select * into lane from public.user_memoir_lane where id=p_lane_id;
 if jsonb_typeof(p_result) is distinct from 'object' or octet_length(p_result::text)>131072 then
   raise exception 'bounded page result required' using errcode='22023';end if;
 result_hash:=encode(sha256(convert_to(p_result::text,'UTF8')),'hex');
 if p_page_number<snap.page_number then
   select * into prior from public.user_lifetime_lane_page_receipt where snapshot_id=snap.id and page_number=p_page_number;
   if found and prior.result_digest=result_hash and prior.page_digest=p_page_digest then return jsonb_build_object('status','page_saved','replayed',true);end if;
   raise exception 'canonical page replay conflict' using errcode='40001';
 end if;
 if p_page_number is distinct from snap.page_number then raise exception 'canonical page order conflict' using errcode='40001';end if;
 page:=public.read_lifetime_memoir_lane_page(lane.id,p_token);
 if p_page_digest is distinct from page->>'page_digest' then raise exception 'stale canonical page digest' using errcode='40001';end if;
 if (page->>'complete')::boolean then raise exception 'snapshot completion requires root commit';end if;
 source_id:=(page->'source'->>'id')::uuid;current_source_version:=(page->'source'->>'version')::bigint;
 if lane.skill='timeline' then
   if jsonb_typeof(p_result->'events') is distinct from 'array' or jsonb_array_length(p_result->'events')>100 then
     raise exception 'bounded event proposals required';end if;
   for item in select value from jsonb_array_elements(p_result->'events') loop
     if item ? 'existing_id' and not exists(select 1 from jsonb_array_elements(page->'events') e
       where e->>'id'=item->>'existing_id' and e->>'revision'=item->>'expected_revision') then
       raise exception 'canonical event identity outside current page';end if;
   end loop;
   for ref in select value from jsonb_path_query(p_result->'events','$.** ? (exists(@.source_id) && exists(@.version))') value loop
     if ref->>'source_id' is distinct from source_id::text or ref->>'version' is distinct from current_source_version::text
       or jsonb_typeof(ref->'char_start') is distinct from 'number' or jsonb_typeof(ref->'char_end') is distinct from 'number'
       or (ref->>'char_start')::integer<(page->'source'->>'char_start')::integer
       or (ref->>'char_end')::integer>(page->'source'->>'char_end')::integer then
       raise exception 'evidence outside claimed original window';end if;
   end loop;
   previous_setting:=current_setting('memoir.lifetime_lane',true);previous_owner:=current_setting('request.jwt.claim.sub',true);
   perform set_config('memoir.lifetime_lane',lane.id::text,true);perform set_config('request.jwt.claim.sub',lane.user_id::text,true);
   perform public.apply_user_memory_events(lane.project_id,jsonb_build_array(jsonb_build_object('id',source_id,'version',current_source_version)),p_result->'events');
   perform set_config('memoir.lifetime_lane',coalesce(previous_setting,''),true);perform set_config('request.jwt.claim.sub',coalesce(previous_owner,''),true);
   if (page->>'core_end')::integer<(page->'source'->>'original_length')::integer then
     update public.user_narrator_source set processing_status='pending' where user_id=lane.user_id and project_id=lane.project_id and id=source_id;
     update public.user_memoir_project set extraction_cursor=coalesce((select min(sequence)-1 from public.user_narrator_source
       where user_id=lane.user_id and project_id=lane.project_id and status='active' and processing_status<>'succeeded'),source_sequence)
       where user_id=lane.user_id and project_id=lane.project_id;
   end if;
   insert into public.user_lifetime_source_extraction(user_id,project_id,source_id,source_version,next_offset)
     values(lane.user_id,lane.project_id,source_id,current_source_version,(page->>'core_end')::integer)
     on conflict on constraint user_lifetime_source_extraction_pkey do update set next_offset=excluded.next_offset;
   update public.user_lifetime_lane_snapshot set last_source=(page->'source'->>'sequence')::bigint,next_offset=(page->>'core_end')::integer,
     event_high_water=(select event_sequence from public.user_memoir_project where user_id=lane.user_id and project_id=lane.project_id) where id=snap.id;
   disposition:='extracted';
 else
   event_id:=page->'partition'->>'id';
   if (p_result->>'reuse')::boolean is true then
     if (page->>'reuse')::boolean is distinct from true then raise exception 'unavailable reusable section';end if;
     disposition:='reused';
   elsif source_id is null or page->'partition'->>'status'<>'active' then
     if p_result->>'status' is distinct from 'no_authorized_evidence' then raise exception 'unsupported canonical partition';end if;
     disposition:='no_authorized_evidence';
   else
     if p_result->>'status' is distinct from 'ready' or (p_result->'validation'->>'ok')::boolean is distinct from true
       or (p_result->'review'->>'ready_for_user_review')::boolean is distinct from true
       or (p_result->'review'->>'publication_approved')::boolean is distinct from false
       or jsonb_typeof(p_result->'sections') is distinct from 'array' or jsonb_array_length(p_result->'sections') not between 1 and 256
       or jsonb_typeof(p_result->'preview') is distinct from 'object' or p_result->'preview'->>'locale' is distinct from snap.locale
       or exists(select 1 from jsonb_array_elements(p_result->'review'->'findings') f where f->>'severity'='blocking') then
       raise exception 'canonical partition review failed';end if;
     for section in select value from jsonb_array_elements(p_result->'sections') loop
       if section->'event_ids' is distinct from jsonb_build_array(event_id) or jsonb_array_length(section->'source_refs')=0 then
         raise exception 'canonical section event identity mismatch';end if;
       for ref in select value from jsonb_array_elements(section->'source_refs') loop
         if ref->>'source_id' is distinct from source_id::text or ref->>'version' is distinct from current_source_version::text
           or (ref->>'char_start')::integer is distinct from (page->'source'->>'char_start')::integer
           or (ref->>'char_end')::integer is distinct from (page->'source'->>'char_end')::integer then
           raise exception 'canonical section span mismatch';end if;
       end loop;
     end loop;
     select coalesce(human_locked,false) into manuscript_locked from public.user_memoir_manuscript
       where user_id=lane.user_id and project_id=lane.project_id and locale=snap.locale;
     manuscript_locked:=coalesce(manuscript_locked,false);
     select s.* into protected from public.user_lifetime_memoir_section s join public.user_lifetime_lane_snapshot prior_root on prior_root.id=s.snapshot_id
       where s.user_id=lane.user_id and s.project_id=lane.project_id and s.locale=snap.locale and s.partition_key=page->>'partition_key'
         and s.source_version=current_source_version
         and (s.approved or s.human_locked or manuscript_locked) and prior_root.state in ('completed','proposed')
       order by prior_root.created_at desc limit 1;
     protected_safe:=protected.snapshot_id is not null and exists(select 1 from public.user_lifetime_lane_snapshot prior_root
       where prior_root.id=protected.snapshot_id and prior_root.policy_epoch=snap.policy_epoch and prior_root.privacy_digest=snap.privacy_digest);
     insert into public.user_lifetime_memoir_section(user_id,project_id,locale,partition_key,event_id,event_revision,source_id,source_version,
       char_start,char_end,evidence_hash,snapshot_id,bundle,approved,human_locked,proposal)
     values(lane.user_id,lane.project_id,snap.locale,page->>'partition_key',event_id,(page->'partition'->>'revision')::bigint,
       source_id,current_source_version,(page->'source'->>'char_start')::integer,(page->'source'->>'char_end')::integer,
       page->>'ref_key',snap.id,case when protected.snapshot_id is null and not manuscript_locked then p_result-'request' when protected_safe then protected.bundle else '{}'::jsonb end,
       coalesce(protected.approved,false),coalesce(protected.human_locked,false) or manuscript_locked,
       case when protected.snapshot_id is not null or manuscript_locked then p_result-'request' else null end)
     on conflict(user_id,project_id,locale,partition_key,snapshot_id) do update set
       proposal=case when user_lifetime_memoir_section.approved or user_lifetime_memoir_section.human_locked then excluded.bundle else null end,
       bundle=case when user_lifetime_memoir_section.approved or user_lifetime_memoir_section.human_locked then user_lifetime_memoir_section.bundle else excluded.bundle end,
       snapshot_id=excluded.snapshot_id;
     disposition:='composed';
   end if;
   update public.user_lifetime_lane_snapshot set last_event=(page->'partition'->>'change_sequence')::bigint,
     last_event_id=event_id,last_ref=page->>'ref_key' where id=snap.id;
 end if;
 new_root:=encode(sha256(convert_to(jsonb_build_object('predecessor_digest',snap.root_digest,'page_digest',page->>'page_digest',
   'result_digest',result_hash,'source_high_water',snap.source_high_water,'event_high_water',
   (select event_high_water from public.user_lifetime_lane_snapshot where id=snap.id))::text,'UTF8')),'hex');
 insert into public.user_lifetime_lane_page_receipt(snapshot_id,page_number,page_digest,result_digest,root_digest,disposition)
   values(snap.id,snap.page_number,page->>'page_digest',result_hash,new_root,disposition);
 update public.user_lifetime_lane_snapshot set page_number=page_number+1,root_digest=new_root where id=snap.id;
 if lane.lease_until<=clock_timestamp() or lane.run_deadline<=clock_timestamp() then raise exception 'canonical page lease expired' using errcode='40001';end if;
 return jsonb_build_object('status','page_saved','root_digest',new_root,'page_number',snap.page_number+1);
end $$;
revoke all on function public.commit_lifetime_memoir_lane_page(uuid,uuid,bigint,jsonb,text) from public,anon,authenticated;
grant execute on function public.commit_lifetime_memoir_lane_page(uuid,uuid,bigint,jsonb,text) to service_role;

create function public.yield_lifetime_memoir_lane(p_lane_id uuid,p_token uuid) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare snap public.user_lifetime_lane_snapshot%rowtype;
begin
 snap:=public.lock_lifetime_memoir_lane(p_lane_id,p_token);
 update public.user_memoir_lane set token=null,lease_until=null,run_deadline=null,pending=true,attempts=0,error=null,
   available_at=clock_timestamp() where id=p_lane_id;
 return jsonb_build_object('status','pending','snapshot_id',snap.id,'pages',snap.page_number,'retrieval_complete',false);
end $$;
revoke all on function public.yield_lifetime_memoir_lane(uuid,uuid) from public,anon,authenticated;
grant execute on function public.yield_lifetime_memoir_lane(uuid,uuid) to service_role;

create function public.complete_lifetime_memoir_lane(p_lane_id uuid,p_token uuid) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare snap public.user_lifetime_lane_snapshot%rowtype; lane public.user_memoir_lane%rowtype; page jsonb; locked boolean:=false;
begin
 snap:=public.lock_lifetime_memoir_lane(p_lane_id,p_token);
 select * into lane from public.user_memoir_lane where id=p_lane_id;
 page:=public.read_lifetime_memoir_lane_page(lane.id,p_token);
 if (page->>'complete')::boolean is distinct from true then raise exception 'canonical coverage remains incomplete';end if;
 if lane.skill='composer' then
   insert into public.user_memoir_manuscript(user_id,project_id,locale) values(lane.user_id,lane.project_id,snap.locale) on conflict do nothing;
   select human_locked into locked from public.user_memoir_manuscript where user_id=lane.user_id and project_id=lane.project_id and locale=snap.locale for update;
   locked:=locked or exists(select 1 from public.user_lifetime_memoir_section where user_id=lane.user_id and project_id=lane.project_id and locale=snap.locale and snapshot_id=snap.id and proposal is not null);
   if (select revision from public.user_memoir_manuscript where user_id=lane.user_id and project_id=lane.project_id and locale=snap.locale)<>snap.base_revision then
     raise exception 'canonical manuscript revision changed' using errcode='40001';end if;
   if not locked then
     update public.user_memoir_manuscript set revision=revision+1,covered_round=snap.round_high_water,
       source_sequence=snap.source_high_water,event_sequence=snap.event_high_water,completed_milestone=snap.milestone
       where user_id=lane.user_id and project_id=lane.project_id and locale=snap.locale;
   end if;
   update public.user_memoir_milestone set state=case when locked then 'proposed' else 'completed' end,
     covered_round=snap.round_high_water,manuscript_revision=snap.base_revision+case when locked then 0 else 1 end
     where user_id=lane.user_id and project_id=lane.project_id and locale=snap.locale and milestone<=snap.milestone and state='pending';
 end if;
 update public.user_lifetime_lane_snapshot set state=case when locked then 'proposed' else 'completed' end where id=snap.id;
 update public.user_memoir_lane set token=null,lease_until=null,run_deadline=null,successful_source=snap.source_high_water,
   successful_event=case when skill='composer' then snap.event_high_water else successful_event end,successful_round=snap.round_high_water,
   pending=pending or target_source>snap.source_high_water or (skill='composer' and target_event>snap.event_high_water),attempts=0,error=null,
   active_manifest='[]',active_events='[]' where id=lane.id;
 return jsonb_build_object('status',case when locked then 'proposed' else 'saved' end,'snapshot_id',snap.id,
   'root_digest',snap.root_digest,'retrieval_complete',true,'pages',snap.page_number,'publication_approved',false);
end $$;
revoke all on function public.complete_lifetime_memoir_lane(uuid,uuid) from public,anon,authenticated;
grant execute on function public.complete_lifetime_memoir_lane(uuid,uuid) to service_role;

create table public.user_lifetime_memoir_cursor (
 id uuid primary key default gen_random_uuid(),snapshot_id uuid not null references public.user_lifetime_lane_snapshot(id) on delete cascade,
 user_id uuid not null,project_id text not null,last_partition text not null,root_digest text not null,
 unique(snapshot_id,last_partition,root_digest)
);
alter table public.user_lifetime_memoir_cursor enable row level security;
revoke all on public.user_lifetime_memoir_cursor from public,anon,authenticated;

create function public.read_lifetime_private_draft_page(p_project_id text,p_snapshot_id uuid,p_after text default null,p_limit integer default 8)
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
     'source_refs',jsonb_build_array(jsonb_build_object('source_id',s.source_id,'version',s.source_version,'char_start',s.char_start,'char_end',s.char_end)),
     'preview',case when root.state='proposed' and s.snapshot_id=root.id and s.proposal is null then null else s.bundle->'preview' end,
     'proposed_preview',case when root.state='proposed' and s.snapshot_id=root.id and s.proposal is null then s.bundle->'preview' else s.proposal->'preview' end,
     'proposal_digest',case when s.proposal is not null then encode(sha256(convert_to(s.proposal::text,'UTF8')),'hex') else null end,
     'original_withheld',s.proposal is not null and not(s.bundle ? 'preview'),'approval_required',root.state='proposed',
     'approved',s.approved,'human_locked',s.human_locked) item
   from public.user_lifetime_memoir_section s join public.user_lifetime_lane_snapshot ss on ss.id=s.snapshot_id
     join public.user_memory_event e on e.user_id=s.user_id and e.project_id=s.project_id and e.id=s.event_id and e.revision=s.event_revision and e.status='active'
     join public.user_narrator_source n on n.user_id=s.user_id and n.project_id=s.project_id and n.id=s.source_id and n.version=s.source_version and n.status='active'
   where s.user_id=owner and s.project_id=p_project_id and s.locale=root.locale and s.partition_key>after_key
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

create function public.read_lifetime_private_draft_head(p_project_id text,p_locale text) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare identity public.user_lifetime_conversation%rowtype; project public.user_memoir_project%rowtype;
 root public.user_lifetime_lane_snapshot%rowtype; lane public.user_memoir_lane%rowtype; page jsonb; output_locale text;
begin
 if auth.uid() is null then raise exception 'authenticated owner required';end if;
 if p_locale is not null and p_locale not in ('en-AU','zh-CN') then raise exception 'invalid memoir edition' using errcode='22023';end if;
 select * into identity from public.user_lifetime_conversation where user_id=auth.uid();
 if not found then return null;end if;
 if identity.project_id is distinct from p_project_id then
   return jsonb_build_object('schema_version',1,'owner_id',auth.uid(),'conversation_id',identity.conversation_id,
     'project_id',identity.project_id,'status','pending','preview',null,'updating',false,'retrieval_complete',false,'error','LIFETIME_PROJECT_REQUIRED');
 end if;
 select * into project from public.user_memoir_project where user_id=auth.uid() and project_id=p_project_id for share;
 perform 1 from public.user_profile where user_id=auth.uid() for share;
 select * into identity from public.user_lifetime_conversation where conversation_id=identity.conversation_id for share;
 select case when profile->>'preferred_language'='zh-CN' then 'zh-CN' else 'en-AU' end into output_locale from public.user_profile where user_id=auth.uid();
 output_locale:=coalesce(p_locale,output_locale,'en-AU');
 select * into lane from public.user_memoir_lane where user_id=auth.uid() and project_id=p_project_id and skill='composer';
 select * into root from public.user_lifetime_lane_snapshot where lane_id=lane.id and state in ('completed','proposed') and policy_epoch=project.policy_epoch
   and preference_revision=identity.preference_revision and user_lifetime_lane_snapshot.locale=output_locale order by created_at desc limit 1;
 if root.id is not null then page:=public.read_lifetime_private_draft_page(p_project_id,root.id,null,1);end if;
 return jsonb_build_object('schema_version',1,'owner_id',auth.uid(),'conversation_id',identity.conversation_id,
   'project_id',p_project_id,'locale',output_locale,'policy_epoch',project.policy_epoch,
   'source_revision',coalesce(root.source_high_water,project.source_sequence),'event_revision',root.event_high_water,
   'current_source_revision',project.source_sequence,'current_event_revision',project.event_sequence,'coverage_scope','frozen_root',
   'status',case when root.id is not null then case when jsonb_array_length(page->'records')>0 then 'ready' else 'insufficient_context' end else 'pending' end,
   'first_record',page->'records'->0,'preview',page->'records'->0->'preview','proposed_preview',page->'records'->0->'proposed_preview',
   'snapshot_state',root.state,'approval_required',root.state='proposed','original_withheld',page->'records'->0->'original_withheld','updating',coalesce(lane.pending or lane.token is not null,false),
   'retrieval_complete',root.id is not null,'snapshot_id',root.id,'root_digest',root.root_digest,
   'page_complete',page->'complete','next_cursor',page->'next_cursor','coverage_round',root.round_high_water,
   'revision',root.base_revision+case when root.state='completed' then 1 else 0 end,'publication_approved',false,
   'error',case when root.id is null then coalesce(lane.error,case when exists(select 1 from public.user_memoir_manuscript
       where user_id=auth.uid() and project_id=p_project_id and locale=output_locale and (bundle is not null or reuse is not null))
       or exists(select 1 from public.user_memoir_section_revision where user_id=auth.uid() and project_id=p_project_id and locale=output_locale)
       then 'LIFETIME_LEGACY_MANUSCRIPT_MIGRATION_REQUIRED' else 'LIFETIME_COMPOSITION_PENDING' end) else null end);
end $$;
revoke all on function public.read_lifetime_private_draft_head(text,text) from public,anon;
grant execute on function public.read_lifetime_private_draft_head(text,text) to authenticated;
create or replace function public.read_lifetime_private_draft_head(p_project_id text) returns jsonb
language sql security definer set search_path=public,auth as $$
 select public.read_lifetime_private_draft_head(p_project_id,null)
$$;
revoke all on function public.read_lifetime_private_draft_head(text) from public,anon;
grant execute on function public.read_lifetime_private_draft_head(text) to authenticated;

-- Edition choice is separate from conversation language and never creates a
-- commercial milestone, completed round, or an eligible composer lane.
create function public.set_lifetime_draft_edition(p_project_id text,p_locale text) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare owner uuid:=auth.uid(); lane public.user_memoir_lane%rowtype;
begin
 if owner is null then raise exception 'authenticated owner required' using errcode='42501';end if;
 if p_locale is null or p_locale not in ('en-AU','zh-CN') then raise exception 'invalid memoir edition' using errcode='22023';end if;
 perform 1 from public.user_memoir_project where user_id=owner and project_id=p_project_id for update;
 perform 1 from public.user_profile where user_id=owner for share;
 perform 1 from public.user_lifetime_conversation where user_id=owner and project_id=p_project_id for share;
 if not found then raise exception 'canonical conversation unavailable' using errcode='42501';end if;
 select * into lane from public.user_memoir_lane where user_id=owner and project_id=p_project_id and skill='composer' for update;
 if lane.id is null then return jsonb_build_object('status','pending','locale',p_locale,'error','LIFETIME_DRAFT_NOT_ELIGIBLE');end if;
 if lane.token is not null and lane.lease_until>clock_timestamp() and lane.run_deadline>clock_timestamp() then
   raise exception 'composer edition currently running' using errcode='40001';end if;
 update public.user_lifetime_lane_snapshot set state='stale' where lane_id=lane.id and state='pending' and locale<>p_locale;
 update public.user_memoir_lane set locale=p_locale,pending=true,attempts=0,error=null,available_at=clock_timestamp(),
   token=null,lease_until=null,run_deadline=null,active_manifest='[]',active_events='[]' where id=lane.id;
 update public.user_memoir_project set draft_revision=draft_revision+1 where user_id=owner and project_id=p_project_id;
 return jsonb_build_object('status','pending','locale',p_locale,'publication_approved',false);
end $$;
revoke all on function public.set_lifetime_draft_edition(text,text) from public,anon;
grant execute on function public.set_lifetime_draft_edition(text,text) to authenticated;

-- Owner review is a one-section CAS. It cannot grant publication, visibility,
-- entitlements, extra rounds, or permission to rewrite another protected section.
create function public.set_lifetime_private_draft_proposal(p_project_id text,p_snapshot_id uuid,p_root_digest text,
 p_partition_id text,p_expected_proposal_digest text,p_accept boolean) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare owner uuid:=auth.uid(); project public.user_memoir_project%rowtype; identity public.user_lifetime_conversation%rowtype;
 root public.user_lifetime_lane_snapshot%rowtype; section public.user_lifetime_memoir_section%rowtype;
 pins jsonb; still_pending boolean; next_digest text; current_revision bigint;
begin
 if owner is null or p_accept is null or length(p_partition_id) not between 1 and 512
   or p_root_digest !~ '^[0-9a-f]{64}$' or p_expected_proposal_digest !~ '^[0-9a-f]{64}$' then
   raise exception 'bounded owner proposal decision required' using errcode='22023';end if;
 select * into project from public.user_memoir_project where user_id=owner and project_id=p_project_id for update;
 perform 1 from public.user_profile where user_id=owner for share;
 select * into identity from public.user_lifetime_conversation where user_id=owner and project_id=p_project_id for share;
 if identity.conversation_id is null then raise exception 'canonical conversation unavailable' using errcode='42501';end if;
 select * into root from public.user_lifetime_lane_snapshot where id=p_snapshot_id and user_id=owner and project_id=p_project_id for update;
 if root.id is null or root.state<>'proposed' or root.root_digest is distinct from p_root_digest
   or root.policy_epoch<>project.policy_epoch or root.preference_revision<>identity.preference_revision
   or exists(select 1 from public.user_lifetime_lane_snapshot newer where newer.lane_id=root.lane_id and newer.locale=root.locale
      and newer.state in ('completed','proposed') and newer.created_at>root.created_at) then
   raise exception 'stale memoir proposal root' using errcode='40001';end if;
 pins:=public.read_lifetime_pinned(identity.conversation_id);
 if (pins->>'privacy_complete')::boolean is distinct from true then raise exception 'privacy maintenance required' using errcode='40001';end if;
 select * into section from public.user_lifetime_memoir_section where user_id=owner and project_id=p_project_id
   and snapshot_id=root.id and partition_key=p_partition_id for update;
 if section.snapshot_id is null or section.proposal is null
   or encode(sha256(convert_to(section.proposal::text,'UTF8')),'hex') is distinct from p_expected_proposal_digest
   or not exists(select 1 from public.user_memory_event e where e.user_id=owner and e.project_id=p_project_id
      and e.id=section.event_id and e.revision=section.event_revision and e.status='active')
   or not exists(select 1 from public.user_narrator_source n where n.user_id=owner and n.project_id=p_project_id
      and n.id=section.source_id and n.version=section.source_version and n.status='active') then
   raise exception 'stale memoir section proposal' using errcode='40001';end if;
 select revision into current_revision from public.user_memoir_manuscript where user_id=owner and project_id=p_project_id and locale=root.locale for update;
 if current_revision is distinct from root.base_revision then raise exception 'manuscript revision changed' using errcode='40001';end if;
 update public.user_lifetime_memoir_section set bundle=case when p_accept then proposal else bundle end,proposal=null
   where user_id=owner and project_id=p_project_id and snapshot_id=root.id and partition_key=p_partition_id;
 next_digest:=encode(sha256(convert_to(jsonb_build_object('predecessor_digest',root.root_digest,'partition_id',p_partition_id,
   'proposal_digest',p_expected_proposal_digest,'accepted',p_accept)::text,'UTF8')),'hex');
 select exists(select 1 from public.user_lifetime_memoir_section where snapshot_id=root.id and proposal is not null) into still_pending;
 update public.user_lifetime_lane_snapshot set root_digest=next_digest,state=case when still_pending then 'proposed' else 'completed' end where id=root.id;
 if not still_pending then
   update public.user_memoir_manuscript set revision=revision+1,covered_round=root.round_high_water,source_sequence=root.source_high_water,
     event_sequence=root.event_high_water,completed_milestone=root.milestone where user_id=owner and project_id=p_project_id and locale=root.locale;
   update public.user_memoir_milestone set state='completed',manuscript_revision=root.base_revision+1
     where user_id=owner and project_id=p_project_id and locale=root.locale and milestone<=root.milestone and state='proposed';
 end if;
 return jsonb_build_object('schema_version',1,'status',case when p_accept then 'accepted' else 'rejected' end,'snapshot_id',root.id,
   'root_digest',next_digest,'locale',root.locale,'approval_required',still_pending,'revision',root.base_revision+case when still_pending then 0 else 1 end,
   'publication_approved',false);
end $$;
revoke all on function public.set_lifetime_private_draft_proposal(text,uuid,text,text,text,boolean) from public,anon;
grant execute on function public.set_lifetime_private_draft_proposal(text,uuid,text,text,text,boolean) to authenticated;

create index lifetime_lane_source_pending on public.user_narrator_source(user_id,project_id,sequence) where status='active' and processing_status<>'succeeded';
create index lifetime_lane_event_pages on public.user_memory_event(user_id,project_id,change_sequence,id);
create function public.defer_lifetime_memoir_lane(p_lane_id uuid,p_token uuid,p_reason text) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
begin
 perform public.lock_lifetime_memoir_lane(p_lane_id,p_token);
 if p_reason not in ('LIFETIME_PRIVACY_MAINTENANCE_REQUIRED','LIFETIME_MODEL_BUDGET_REQUIRED','LIFETIME_GENERATION_PAUSED') then raise exception 'invalid lane maintenance reason';end if;
 update public.user_memoir_lane set token=null,lease_until=null,run_deadline=null,pending=true,attempts=0,error=p_reason,
   available_at=clock_timestamp()+interval '5 minutes' where id=p_lane_id;
 return jsonb_build_object('status','pending','error',p_reason,'retrieval_complete',false);
end $$;
revoke all on function public.defer_lifetime_memoir_lane(uuid,uuid,text) from public,anon,authenticated;
grant execute on function public.defer_lifetime_memoir_lane(uuid,uuid,text) to service_role;
create function public.invalidate_lifetime_lane_fences() returns trigger
language plpgsql security definer set search_path=public,auth as $$
begin
 if tg_table_name='user_memoir_project' then
  if old.policy_epoch is distinct from new.policy_epoch then
   update public.user_lifetime_lane_snapshot set state='stale' where user_id=new.user_id and project_id=new.project_id and state='pending';
   -- Phase requests can also contain bounded source-backed pinned continuity.
   -- Unknown derived dependencies are conservatively discarded on any fence change.
   delete from public.user_memoir_checkpoint c using public.user_memoir_lane l
     where c.lane_id=l.id and l.user_id=new.user_id and l.project_id=new.project_id and c.lifetime_snapshot_id is not null;
  end if;
 elsif tg_table_name='user_lifetime_conversation' then
  if old.preference_revision is distinct from new.preference_revision then
   update public.user_lifetime_lane_snapshot set state='stale' where user_id=new.user_id and conversation_id=new.conversation_id and state='pending';
   delete from public.user_memoir_checkpoint c using public.user_memoir_lane l
     where c.lane_id=l.id and l.user_id=new.user_id and l.project_id=new.project_id and c.lifetime_snapshot_id is not null;
  end if;
 end if;
 return new;
end $$;
create trigger lifetime_lane_policy_fence after update of policy_epoch on public.user_memoir_project
 for each row execute function public.invalidate_lifetime_lane_fences();
create trigger lifetime_lane_preferences_fence after update of preference_revision on public.user_lifetime_conversation
 for each row execute function public.invalidate_lifetime_lane_fences();
revoke all on function public.invalidate_lifetime_lane_fences() from public,anon,authenticated;
-- Existing per-source request bound, host policy validation only. The full
-- original never enters the model packet or the phase/checkpoint payload.
create function public.read_lifetime_lane_policy_source(p_lane_id uuid,p_token uuid) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare page jsonb; original public.user_narrator_source%rowtype;
begin
 page:=public.read_lifetime_memoir_lane_page(p_lane_id,p_token);
 if page->>'skill'<>'timeline' or (page->>'complete')::boolean then raise exception 'timeline source page required';end if;
 select * into original from public.user_narrator_source where user_id=(page->>'user_id')::uuid and project_id=page->>'project_id'
   and id=(page->'source'->>'id')::uuid and version=(page->'source'->>'version')::bigint and status='active';
 if not found then raise exception 'stale source policy original';end if;
 return public.narrator_source_record(original);
end $$;
revoke all on function public.read_lifetime_lane_policy_source(uuid,uuid) from public,anon,authenticated;
grant execute on function public.read_lifetime_lane_policy_source(uuid,uuid) to service_role;
create function public.invalidate_lifetime_lane_photo() returns trigger
language plpgsql security definer set search_path=public,auth as $$
begin
 delete from public.user_lifetime_memoir_section where user_id=coalesce(new.user_id,old.user_id)
   and project_id=coalesce(new.project_id,old.project_id) and event_id in (new.event_id,old.event_id);
 return coalesce(new,old);
end $$;
create trigger lifetime_lane_photo_invalidation after insert or update or delete on public.user_interview_photo_link
 for each row execute function public.invalidate_lifetime_lane_photo();
revoke all on function public.invalidate_lifetime_lane_photo() from public,anon,authenticated;
create index lifetime_lane_photo_scope on public.user_interview_photo_link(user_id,project_id,event_id,source_id,source_version,id)
 where status='confirmed' and provenance='narrator_metadata';
commit;
