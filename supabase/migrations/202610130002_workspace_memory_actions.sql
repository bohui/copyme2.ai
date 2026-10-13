-- Workspace tasks do not select a conversational mode or create testimony.
begin;
create function public.read_workspace_memory_focus(p_project_id text,p_focus jsonb) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare e public.user_memory_event%rowtype; stage text; owner uuid:=auth.uid();
begin
 perform 1 from public.user_memoir_project where user_id=owner and project_id=p_project_id for share;
 if not found then raise exception 'workspace unavailable' using errcode='42501';end if;
 if jsonb_typeof(p_focus)<>'object' then raise exception 'invalid workspace task' using errcode='22023';end if;
 if p_focus->>'kind'='add_memory' then
   stage:=p_focus->>'life_stage';
   if stage is null or stage not in ('baby','toddler','childhood','adolescence','young_adulthood','midlife','later_life','unplaced')
     or (select count(*) from jsonb_object_keys(p_focus))<>2 then raise exception 'invalid life stage' using errcode='22023';end if;
   return jsonb_build_object('kind','add_memory','life_stage',stage);
 elsif p_focus->>'kind'='explore_memory' then
   if (select count(*) from jsonb_object_keys(p_focus))<>3 then raise exception 'invalid memory focus' using errcode='22023';end if;
   select * into e from public.user_memory_event where user_id=owner and project_id=p_project_id
     and id=p_focus->>'event_id' and revision=(p_focus->>'event_revision')::bigint and status='active';
   if not found or not exists(select 1 from public.user_memory_event_source r join public.user_narrator_source s
     on s.user_id=r.user_id and s.project_id=r.project_id and s.id=r.source_id and s.version=r.source_version and s.status='active'
     where r.user_id=owner and r.project_id=p_project_id and r.event_id=e.id) or
     exists(select 1 from public.user_memory_event_source r where r.user_id=owner and r.project_id=p_project_id and r.event_id=e.id
       and not exists(select 1 from public.user_narrator_source s where s.user_id=owner and s.project_id=p_project_id
         and s.id=r.source_id and s.version=r.source_version and s.status='active')) then
     raise exception 'memory changed or unavailable' using errcode='40001';end if;
   return jsonb_build_object('kind','explore_memory','event_id',e.id,'event_revision',e.revision,
     'event',public.bounded_lifetime_event_record(e));
 end if;
 raise exception 'unknown workspace task' using errcode='22023';
end $$;
revoke all on function public.read_workspace_memory_focus(text,jsonb) from public,anon;
grant execute on function public.read_workspace_memory_focus(text,jsonb) to authenticated;

create table public.user_workspace_section_rework (
 user_id uuid not null,project_id text not null,request_id uuid not null,
 snapshot_id uuid not null references public.user_lifetime_lane_snapshot(id) on delete cascade,
 composed_snapshot_id uuid references public.user_lifetime_lane_snapshot(id) on delete set null,
 root_digest text not null,partition_key text not null,locale text not null,
 event_id text not null,event_revision bigint not null,source_id uuid not null,source_version bigint not null,
 instruction text not null check(length(instruction) between 1 and 1000),
 original_preview jsonb not null,
 status text not null default 'pending' check(status in ('pending','composed','stale')),
 created_at timestamptz not null default clock_timestamp(),
 primary key(user_id,project_id,request_id),
 foreign key(user_id,project_id) references public.user_memoir_project(user_id,project_id) on delete cascade,
 foreign key(user_id,project_id,source_id) references public.user_narrator_source(user_id,project_id,id) on delete cascade
);
create unique index workspace_section_one_pending on public.user_workspace_section_rework(user_id,project_id,locale,partition_key) where status='pending';
create index workspace_rework_photo_dependency
 on public.user_workspace_section_rework(user_id,project_id,(right(partition_key,37)));
create index workspace_rework_pending_event
 on public.user_workspace_section_rework(user_id,project_id,event_id) where status='pending';
alter table public.user_workspace_section_rework enable row level security;
revoke all on public.user_workspace_section_rework from public,anon,authenticated;

-- Match the composer's current evidence/photo partition membership. The first
-- qualifying photo replaces a source-only key; later photos add sibling keys.
create function public.workspace_rework_partition_current(p_owner uuid,p_project_id text,p_event_id text,p_partition_key text) returns boolean
language sql stable security definer set search_path=public,auth as $$
 select exists(select 1 from public.user_memory_event_source r
   left join public.user_interview_photo_link photo on photo.user_id=r.user_id and photo.project_id=r.project_id
     and photo.event_id=r.event_id and photo.source_id=r.source_id and photo.source_version=r.source_version
     and photo.status='confirmed' and photo.provenance='narrator_metadata' and strpos(r.evidence->>'quote',photo.quote)>0
     and public.interview_photo_available(r.user_id,r.project_id,photo.photo_id)
   where r.user_id=p_owner and r.project_id=p_project_id and r.event_id=p_event_id
     and p_partition_key=r.event_id||':'||r.source_id::text||':'||r.source_version::text||':'||r.evidence_hash||':'||coalesce(photo.id::text,''))
$$;
revoke all on function public.workspace_rework_partition_current(uuid,text,text,text) from public,anon,authenticated;

create function public.request_workspace_section_rework(p_project_id text,p_request_id uuid,p_snapshot_id uuid,
 p_root_digest text,p_partition_id text,p_instruction text) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare owner uuid:=auth.uid(); project public.user_memoir_project%rowtype;
 root public.user_lifetime_lane_snapshot%rowtype; section public.user_lifetime_memoir_section%rowtype;
 prior public.user_workspace_section_rework%rowtype; lane public.user_memoir_lane%rowtype; next_event bigint;
begin
 select * into project from public.user_memoir_project where user_id=owner and project_id=p_project_id for update;
 if not found then raise exception 'workspace unavailable' using errcode='42501';end if;
 if p_request_id is null or p_instruction is null or length(btrim(p_instruction)) not between 1 and 1000 then
   raise exception 'bounded revision request required' using errcode='22023';end if;
 select * into prior from public.user_workspace_section_rework where user_id=owner and project_id=p_project_id and request_id=p_request_id;
 if found then
   if prior.snapshot_id is distinct from p_snapshot_id or prior.root_digest is distinct from p_root_digest
     or prior.partition_key is distinct from p_partition_id or prior.instruction is distinct from btrim(p_instruction) then
     raise exception 'revision request replay conflict' using errcode='40001';end if;
   -- A lost acknowledgement may be retried after another edition ran. Recover
   -- the pending task without changing its identity or interrupting a lease.
   if prior.status='pending' then
     select l.* into lane from public.user_memoir_lane l join public.user_lifetime_lane_snapshot s on s.lane_id=l.id
       where s.id=prior.snapshot_id and l.user_id=owner and l.project_id=p_project_id and l.skill='composer' for update of l;
     if found and not(lane.token is not null and lane.lease_until>clock_timestamp() and lane.run_deadline>clock_timestamp()) then
       if not exists(select 1 from public.user_lifetime_lane_snapshot where lane_id=lane.id and state='pending') then
         update public.user_memoir_lane set locale=prior.locale where id=lane.id;
       end if;
       perform public.retry_user_memoir_lane(p_project_id,'composer');
     end if;
   end if;
   return jsonb_build_object('request_id',prior.request_id,'status',prior.status);
 end if;
 select * into root from public.user_lifetime_lane_snapshot r where r.id=p_snapshot_id and r.user_id=owner and r.project_id=p_project_id
   and r.root_digest=p_root_digest and r.state in ('completed','proposed') and r.policy_epoch=project.policy_epoch
   and r.preference_revision=(select preference_revision from public.user_lifetime_conversation where user_id=owner and project_id=p_project_id);
 if not found or exists(select 1 from public.user_lifetime_lane_snapshot newer where newer.lane_id=root.lane_id
   and newer.locale=root.locale and newer.state in ('completed','proposed') and newer.created_at>root.created_at) then
   raise exception 'section root changed' using errcode='40001';end if;
 select * into lane from public.user_memoir_lane where id=root.lane_id and skill='composer' for update;
 if not found or (lane.token is not null and lane.lease_until>clock_timestamp() and lane.run_deadline>clock_timestamp()) then
   raise exception 'section is already changing' using errcode='40001';end if;
 select s.* into section from public.user_lifetime_memoir_section s join public.user_lifetime_lane_snapshot r on r.id=s.snapshot_id
   where s.user_id=owner and s.project_id=p_project_id and s.locale=root.locale and s.partition_key=p_partition_id
     and r.state in ('completed','proposed') and r.created_at<=root.created_at and r.policy_epoch=root.policy_epoch
     and r.preference_revision=root.preference_revision order by r.created_at desc limit 1 for update of s;
 if not found or section.proposal is not null or not(section.bundle ? 'preview') or
   not exists(select 1 from public.user_memory_event where user_id=owner and project_id=p_project_id and id=section.event_id
     and revision=section.event_revision and status='active') or
   not exists(select 1 from public.user_narrator_source where user_id=owner and project_id=p_project_id and id=section.source_id
     and version=section.source_version and status='active') or
   not public.workspace_rework_partition_current(owner,p_project_id,section.event_id,p_partition_id)
   then raise exception 'section changed' using errcode='40001';end if;
 if exists(select 1 from public.user_workspace_section_rework where user_id=owner and project_id=p_project_id
   and locale=root.locale and partition_key=p_partition_id and status='pending') then raise exception 'revision already queued' using errcode='40001';end if;
 if octet_length((section.bundle->'preview')::text)>12288 then raise exception 'section exceeds revision context budget' using errcode='22023';end if;
 insert into public.user_workspace_section_rework(user_id,project_id,request_id,snapshot_id,root_digest,partition_key,locale,event_id,event_revision,source_id,source_version,instruction,original_preview)
 values(owner,p_project_id,p_request_id,root.id,root.root_digest,p_partition_id,root.locale,section.event_id,section.event_revision,section.source_id,section.source_version,btrim(p_instruction),
   jsonb_build_object('schema_version',1,'title',section.bundle->'preview'->>'title','text',section.bundle->'preview'->>'text'));
 -- Protect the current text so the normal commit path creates a review proposal.
 update public.user_lifetime_memoir_section set human_locked=true where user_id=owner and project_id=p_project_id
   and locale=root.locale and partition_key=p_partition_id and snapshot_id=section.snapshot_id;
 -- Advance scheduling metadata only. Neither event facts nor their revision change.
 update public.user_memoir_project set event_sequence=event_sequence+1 where user_id=owner and project_id=p_project_id returning event_sequence into next_event;
 update public.user_memory_event set change_sequence=next_event where user_id=owner and project_id=p_project_id and id=section.event_id;
 -- Keep an unfinished edition resumable; the completion wrapper drains the
 -- other editions after this root has become available for review.
 if not exists(select 1 from public.user_lifetime_lane_snapshot where lane_id=lane.id and state='pending') then
   update public.user_memoir_lane set locale=root.locale where id=lane.id;
 end if;
 perform public.retry_user_memoir_lane(p_project_id,'composer');
 return jsonb_build_object('request_id',p_request_id,'status','pending');
end $$;
revoke all on function public.request_workspace_section_rework(text,uuid,uuid,text,text,text) from public,anon;
grant execute on function public.request_workspace_section_rework(text,uuid,uuid,text,text,text) to authenticated;

create function public.read_workspace_draft_section(p_project_id text,p_snapshot_id uuid,p_partition_id text) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare root public.user_lifetime_lane_snapshot%rowtype; after_key text; cursor_id uuid; page jsonb;
begin
 select * into root from public.user_lifetime_lane_snapshot where id=p_snapshot_id and user_id=auth.uid() and project_id=p_project_id;
 if not found or p_partition_id is null or length(p_partition_id)>512 then raise exception 'section unavailable' using errcode='42501';end if;
 select coalesce(max(partition_key),'') into after_key from public.user_lifetime_memoir_section where user_id=auth.uid()
   and project_id=p_project_id and locale=root.locale and partition_key<p_partition_id;
 insert into public.user_lifetime_memoir_cursor(snapshot_id,user_id,project_id,last_partition,root_digest)
   values(root.id,auth.uid(),p_project_id,after_key,root.root_digest)
   on conflict(snapshot_id,last_partition,root_digest) do update set last_partition=excluded.last_partition returning id into cursor_id;
 -- Reuse the canonical page reader's ownership, policy, evidence and root fences.
 page:=public.read_lifetime_private_draft_page(p_project_id,p_snapshot_id,cursor_id::text,1);
 if page->'records'->0->>'id' is distinct from p_partition_id then raise exception 'section changed' using errcode='40001';end if;
 return page->'records'->0;
end $$;
revoke all on function public.read_workspace_draft_section(text,uuid,text) from public,anon;
grant execute on function public.read_workspace_draft_section(text,uuid,text) to authenticated;

alter function public.read_lifetime_memoir_lane_page(uuid,uuid) rename to read_lifetime_memoir_lane_page_before_rework;
revoke all on function public.read_lifetime_memoir_lane_page_before_rework(uuid,uuid) from public,anon,authenticated,service_role;
create function public.read_lifetime_memoir_lane_page(p_lane_id uuid,p_token uuid) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare page jsonb; request public.user_workspace_section_rework%rowtype;
begin
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
revoke all on function public.read_lifetime_memoir_lane_page(uuid,uuid) from public,anon,authenticated;
grant execute on function public.read_lifetime_memoir_lane_page(uuid,uuid) to service_role;

alter function public.lock_lifetime_memoir_lane_publication(jsonb) rename to lock_lifetime_memoir_lane_publication_before_rework;
revoke all on function public.lock_lifetime_memoir_lane_publication_before_rework(jsonb) from public,anon,authenticated,service_role;
create function public.lock_lifetime_memoir_lane_publication(p_fence jsonb) returns double precision
language plpgsql security definer set search_path=public,auth as $$
declare remaining double precision; page jsonb;
begin
 remaining:=public.lock_lifetime_memoir_lane_publication_before_rework(p_fence);
 page:=public.read_lifetime_memoir_lane_page((p_fence->>'lane_id')::uuid,(p_fence->>'token')::uuid);
 if coalesce(p_fence->'editorial_request','null'::jsonb) is distinct from page->'editorial_request' then
   raise exception 'revision instruction changed' using errcode='40001';end if;
 return remaining;
end $$;
revoke all on function public.lock_lifetime_memoir_lane_publication(jsonb) from public,anon;
grant execute on function public.lock_lifetime_memoir_lane_publication(jsonb) to service_role,authenticated;

alter function public.commit_lifetime_memoir_lane_page(uuid,uuid,bigint,jsonb,text) rename to commit_lifetime_memoir_lane_page_before_rework;
revoke all on function public.commit_lifetime_memoir_lane_page_before_rework(uuid,uuid,bigint,jsonb,text) from public,anon,authenticated,service_role;
create function public.commit_lifetime_memoir_lane_page(p_lane_id uuid,p_token uuid,p_page_number bigint,p_result jsonb,p_page_digest text) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare page jsonb; result jsonb;
begin
 page:=public.read_lifetime_memoir_lane_page(p_lane_id,p_token);
 result:=public.commit_lifetime_memoir_lane_page_before_rework(p_lane_id,p_token,p_page_number,p_result,p_page_digest);
 if p_page_number=(page->>'page_number')::bigint and page->'editorial_request'<>'null'::jsonb then
   update public.user_workspace_section_rework set composed_snapshot_id=(page->>'snapshot_id')::uuid where user_id=(page->>'user_id')::uuid
     and project_id=page->>'project_id' and request_id=(page->'editorial_request'->>'request_id')::uuid;
 end if;
 return result;
end $$;
revoke all on function public.commit_lifetime_memoir_lane_page(uuid,uuid,bigint,jsonb,text) from public,anon,authenticated;
grant execute on function public.commit_lifetime_memoir_lane_page(uuid,uuid,bigint,jsonb,text) to service_role;

-- A project has one composer lane, shared by its language editions. Completing
-- one edition must leave the lane queued for any remaining editorial requests.
alter function public.complete_lifetime_memoir_lane(uuid,uuid) rename to complete_lifetime_memoir_lane_before_rework;
revoke all on function public.complete_lifetime_memoir_lane_before_rework(uuid,uuid) from public,anon,authenticated,service_role;
create function public.complete_lifetime_memoir_lane(p_lane_id uuid,p_token uuid) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare result jsonb; next_locale text;
begin
 result:=public.complete_lifetime_memoir_lane_before_rework(p_lane_id,p_token);
 -- A saved page is not yet a readable proposal. Keep its request pending until
 -- the complete root is published, so stale/yielded snapshots can be retried.
 update public.user_workspace_section_rework set status='composed'
   where composed_snapshot_id=(result->>'snapshot_id')::uuid and status='pending';
 -- Never reschedule a request whose canonical partition no longer exists.
 delete from public.user_workspace_section_rework request using public.user_memoir_lane lane
   where lane.id=p_lane_id and lane.user_id=request.user_id and lane.project_id=request.project_id and lane.skill='composer'
     and request.status='pending' and not public.workspace_rework_partition_current(request.user_id,request.project_id,request.event_id,request.partition_key);
 select request.locale into next_locale from public.user_workspace_section_rework request join public.user_memoir_lane lane
   on lane.user_id=request.user_id and lane.project_id=request.project_id and lane.skill='composer'
   where lane.id=p_lane_id and request.status='pending' order by request.created_at,request.request_id limit 1;
 if found then
   update public.user_memoir_lane set locale=next_locale,pending=true,attempts=0,error=null,available_at=clock_timestamp() where id=p_lane_id;
 end if;
 return result;
end $$;
revoke all on function public.complete_lifetime_memoir_lane(uuid,uuid) from public,anon,authenticated;
grant execute on function public.complete_lifetime_memoir_lane(uuid,uuid) to service_role;

create function public.invalidate_workspace_rework() returns trigger
language plpgsql security definer set search_path=public,auth as $$
begin
 if tg_table_name='user_narrator_source' then
   if old.version is distinct from new.version or old.status is distinct from new.status then
     delete from public.user_workspace_section_rework where user_id=old.user_id and project_id=old.project_id and source_id=old.id;
   end if;
 elsif tg_table_name='user_memory_event' then
   if tg_op='DELETE' or old.revision is distinct from new.revision or old.status is distinct from new.status then
     delete from public.user_workspace_section_rework where user_id=old.user_id and project_id=old.project_id and event_id=old.id;
   end if;
 elsif tg_table_name='user_interview_photo_link' then
   if tg_op='UPDATE' and old is not distinct from new then return new;end if;
   if tg_op<>'INSERT' then
     -- The composer partition ends in its exact photo-link UUID. Retire its
     -- request in the same transaction as the prose, before completion can
     -- requeue an editorial task whose partition no longer exists.
     delete from public.user_workspace_section_rework where user_id=old.user_id and project_id=old.project_id
       and event_id=old.event_id and right(partition_key,37)=':'||old.id::text;
   end if;
   if tg_op<>'DELETE' and new.event_id is not null then
     -- Confirmation of the first qualifying photo removes its source-only
     -- partition. Keep other evidence spans and existing sibling photo tasks.
     delete from public.user_workspace_section_rework request where user_id=new.user_id and project_id=new.project_id
       and event_id=new.event_id and status='pending'
       and not public.workspace_rework_partition_current(request.user_id,request.project_id,request.event_id,request.partition_key);
   end if;
 end if;
 return coalesce(new,old);
end $$;
create trigger workspace_rework_source_invalidation after update on public.user_narrator_source for each row execute function public.invalidate_workspace_rework();
create trigger workspace_rework_event_invalidation after update or delete on public.user_memory_event for each row execute function public.invalidate_workspace_rework();
create trigger workspace_rework_photo_invalidation after insert or update or delete on public.user_interview_photo_link for each row execute function public.invalidate_workspace_rework();
revoke all on function public.invalidate_workspace_rework() from public,anon,authenticated;
commit;
