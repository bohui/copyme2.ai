-- Scheduled narrator-profile work shares the existing timeline owner and token.
begin;
create table public.lifetime_profile_cadence (
 singleton boolean primary key default true check(singleton),
 initial_rounds bigint[] not null default array[1,5]::bigint[],
 interval_rounds integer not null default 10 check(interval_rounds between 1 and 1000),
 check(array_length(initial_rounds,1) between 1 and 16 and 0<all(initial_rounds))
);
insert into public.lifetime_profile_cadence default values;
alter table public.lifetime_profile_cadence enable row level security;
revoke all on public.lifetime_profile_cadence from public,anon,authenticated,service_role;

create function public.lifetime_profile_due_round(p_round bigint) returns bigint
language sql stable security definer set search_path='' as $$
 select greatest(coalesce((select max(r) from unnest(c.initial_rounds) r where r<=p_round),0),
   (greatest(p_round,0)/c.interval_rounds)*c.interval_rounds)
 from public.lifetime_profile_cadence c where singleton
$$;

create table public.user_lifetime_profile_authority (
 user_id uuid primary key, conversation_id uuid not null,
 revision bigint not null default 0,
 auto_enabled boolean not null default true,
 manual_complete boolean not null default false,
 name_released boolean not null default false,
 invalidated_fields text[] not null default '{}',
 field_locks jsonb not null default '{}' check(jsonb_typeof(field_locks)='object'),
 foreign key(user_id,conversation_id) references public.user_lifetime_conversation(user_id,conversation_id) on delete cascade
);
create table public.user_lifetime_profile_progress (
 user_id uuid not null, project_id text not null,
 requested_round bigint not null default 0, requested_frontier bigint not null default 0,
 active_round bigint not null default 0, source_frontier bigint not null default 0,
 covered_round bigint not null default 0, covered_frontier bigint not null default 0,
 skipped_round bigint not null default 0,
 primary key(user_id,project_id),
 foreign key(user_id,project_id) references public.user_memoir_project(user_id,project_id) on delete cascade
);
create table public.user_lifetime_profile_coverage (
 user_id uuid not null, project_id text not null, source_id uuid not null, source_version bigint not null,
 next_offset integer not null check(next_offset>=0),
 primary key(user_id,project_id,source_id,source_version),
 foreign key(user_id,project_id,source_id) references public.user_narrator_source(user_id,project_id,id) on delete cascade
);
create table public.user_lifetime_profile_receipt (
 user_id uuid not null, project_id text not null, page_digest text not null,
 snapshot_id uuid not null references public.user_lifetime_lane_snapshot on delete cascade,
 result_digest text not null, target_round bigint not null,
 source_id uuid, source_version bigint, char_start integer, char_end integer,
 skipped boolean not null, primary key(user_id,project_id,page_digest),
 foreign key(user_id,project_id) references public.user_memoir_project(user_id,project_id) on delete cascade
);
-- No source text or historical profile values in bookkeeping.
create table public.user_lifetime_profile_dependency (
 user_id uuid not null, field text not null check(field in
   ('name','birth_year','birth_date_expression','birth_place','childhood_place','avatar_style')),
 project_id text not null, source_id uuid not null, source_version bigint not null,
 char_start integer not null, char_end integer not null,
 primary key(user_id,field,project_id,source_id,source_version,char_start,char_end),
 foreign key(user_id,project_id,source_id) references public.user_narrator_source(user_id,project_id,id) on delete cascade
);
alter table public.user_lifetime_profile_authority enable row level security;
alter table public.user_lifetime_profile_progress enable row level security;
alter table public.user_lifetime_profile_coverage enable row level security;
alter table public.user_lifetime_profile_receipt enable row level security;
alter table public.user_lifetime_profile_dependency enable row level security;
revoke all on public.user_lifetime_profile_authority,public.user_lifetime_profile_progress,
 public.user_lifetime_profile_coverage,public.user_lifetime_profile_receipt,public.user_lifetime_profile_dependency
 from public,anon,authenticated,service_role;

create function public.ensure_lifetime_profile_authority(p_owner uuid) returns void
language plpgsql security definer set search_path='' as $$
begin
 insert into public.user_lifetime_profile_authority(user_id,conversation_id,field_locks)
 select c.user_id,c.conversation_id,coalesce((select jsonb_object_agg(k,case when k='name' and exists(
     select 1 from public.user_lifetime_chosen_name n where n.user_id=p_owner and n.authority='explicit') then 'manual' else 'preserved' end)
   from unnest(array['name','birth_year','birth_date_expression','birth_place','childhood_place','avatar_style']) k
   where ((p.profile->k is not null and p.profile->k<>'null'::jsonb and p.profile->>k<>'')
     or (k='name' and exists(select 1 from public.user_lifetime_chosen_name n where n.user_id=p_owner and n.authority='explicit')))
     and not(k='name' and exists(select 1 from public.user_lifetime_chosen_name n
       where n.user_id=p_owner and n.authority='generated' and n.chosen_name=p.profile->>'name'))),'{}')
 from public.user_lifetime_conversation c left join public.user_profile p on p.user_id=c.user_id
 where c.user_id=p_owner and c.product='memoir' on conflict do nothing;
end $$;

create function public.lifetime_profile_automation(p_owner uuid) returns jsonb
language sql stable security definer set search_path='' as $$
 select jsonb_build_object('schema_version',1,'revision',a.revision,'auto_enabled',a.auto_enabled,
   'stopped',not a.auto_enabled or a.manual_complete,'manual_complete',a.manual_complete,'field_locks',a.field_locks)
 from public.user_lifetime_profile_authority a where a.user_id=p_owner
$$;

-- Keep the read projection application-owned, including generic JSON saves.
create function public.project_lifetime_profile_authority() returns trigger
language plpgsql security definer set search_path='' as $$
declare fields text[];
begin
 perform public.ensure_lifetime_profile_authority(new.user_id);
 if tg_op='UPDATE' and (old.profile->'memory_preferences'->'excluded_topics' is distinct from new.profile->'memory_preferences'->'excluded_topics'
   or old.profile->'memory_preferences'->'paused_topics' is distinct from new.profile->'memory_preferences'->'paused_topics') then
   select array_agg(distinct d.field) into fields from public.user_lifetime_profile_dependency d where d.user_id=new.user_id;
   if fields is not null then
     update public.user_lifetime_chosen_name set authority='invalidated',chosen_name=null
       where user_id=new.user_id and authority='generated' and 'name'=any(fields);
     delete from public.user_lifetime_profile_dependency where user_id=new.user_id and field=any(fields);
     update public.user_lifetime_profile_authority set invalidated_fields=(select array_agg(distinct k)
       from unnest(invalidated_fields||fields) k) where user_id=new.user_id;
   end if;
 end if;
 select a.invalidated_fields into fields from public.user_lifetime_profile_authority a where a.user_id=new.user_id;
 new.profile:=new.profile-coalesce(fields,'{}');
 if tg_op='UPDATE' and exists(select 1 from unnest(array['name','birth_year','birth_date_expression',
   'birth_place','childhood_place','avatar_style']) k where old.profile->k is distinct from new.profile->k) then
   update public.user_lifetime_profile_authority set revision=revision+1 where user_id=new.user_id;
 end if;
 if exists(select 1 from public.user_lifetime_profile_authority where user_id=new.user_id) then
   new.profile:=jsonb_set(new.profile,'{profile_automation}',public.lifetime_profile_automation(new.user_id));
 else new.profile:=new.profile-'profile_automation';end if;
 return new;
end $$;
create trigger zz_lifetime_profile_authority before insert or update of profile on public.user_profile
 for each row execute function public.project_lifetime_profile_authority();
select public.ensure_lifetime_profile_authority(user_id) from public.user_lifetime_conversation;
update public.user_profile set profile=profile where user_id in(select user_id from public.user_lifetime_profile_authority);

-- Retain the existing canonical language and chosen-name writer.
alter function public.set_lifetime_profile_settings(jsonb,uuid) rename to set_lifetime_profile_settings_before_background_profile;
revoke all on function public.set_lifetime_profile_settings_before_background_profile(jsonb,uuid)
 from public,anon,authenticated,service_role;
create function public.set_lifetime_profile_settings(p_patch jsonb,p_lease_token uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
#variable_conflict use_column
declare owner uuid:=auth.uid(); project text; result jsonb; k text; val jsonb; locks jsonb;
 fields text[]:=array['name','birth_year','birth_date_expression','birth_place','childhood_place','avatar_style'];
begin
 select project_id into project from public.user_lifetime_conversation where user_id=owner and product='memoir';
 if not found then raise exception 'mapped conversation required' using errcode='42501';end if;
 if jsonb_typeof(p_patch) is distinct from 'object' or exists(select 1 from jsonb_object_keys(p_patch) k
   where k<>all(fields||array['preferred_language','profile_confirm_all','profile_auto_enabled','profile_release_fields']))
   or octet_length(p_patch::text)>4096 then raise exception 'invalid profile settings patch' using errcode='22023';end if;
 perform 1 from public.user_memoir_project where user_id=owner and project_id=project for update;
 insert into public.user_profile(user_id,profile) values(owner,'{}') on conflict do nothing;
 perform 1 from public.user_profile where user_id=owner for update;
 perform 1 from public.user_agent_turn_lease where user_id=owner and lease_token=p_lease_token
   and expires_at>clock_timestamp() for share;
 if not found then raise exception 'valid turn lease required' using errcode='40001';end if;
 foreach k in array array['profile_confirm_all','profile_auto_enabled'] loop
   if p_patch ? k and jsonb_typeof(p_patch->k) is distinct from 'boolean' then
     raise exception 'boolean profile control required' using errcode='22023';end if;
 end loop;
 if p_patch ? 'profile_release_fields' then
   if jsonb_typeof(p_patch->'profile_release_fields') is distinct from 'array'
     or jsonb_array_length(p_patch->'profile_release_fields')>6
     or exists(select 1 from jsonb_array_elements(p_patch->'profile_release_fields') f
       where jsonb_typeof(f)<>'string' or (f#>>'{}')<>all(fields)) then
     raise exception 'invalid profile release fields' using errcode='22023';end if;
 end if;
 foreach k in array fields loop
   if p_patch ? k then update public.user_lifetime_profile_authority set invalidated_fields=array_remove(invalidated_fields,k)
     where user_id=owner;end if;
 end loop;
 result:=public.set_lifetime_profile_settings_before_background_profile(p_patch-array[
   'birth_date_expression','avatar_style','profile_confirm_all','profile_auto_enabled','profile_release_fields'],p_lease_token);
 foreach k in array array['birth_date_expression','avatar_style'] loop
   if not(p_patch ? k) then continue;end if;
   val:=p_patch->k;
   if val<>'null'::jsonb then
     if jsonb_typeof(val)<>'string' or length(btrim(val#>>'{}'))>(case when k='birth_date_expression' then 120 else 160 end) then
       raise exception 'invalid profile text setting' using errcode='22023';end if;
     val:=to_jsonb(btrim(val#>>'{}'));
     if val='""'::jsonb then val:='null';end if;
     if k='avatar_style' and val<>'null'::jsonb and val#>>'{}' not in ('male','female') then
       raise exception 'invalid avatar style' using errcode='22023';end if;
   end if;
   if val='null'::jsonb then result:=result-k;else result:=jsonb_set(result,array[k],val);end if;
 end loop;
 select field_locks into locks from public.user_lifetime_profile_authority where user_id=owner for update;
 for k in select jsonb_array_elements_text(coalesce(p_patch->'profile_release_fields','[]')) loop
   locks:=locks-k;
   if k='name' then update public.user_lifetime_profile_authority set name_released=true where user_id=owner;end if;
 end loop;
 foreach k in array fields loop
   if p_patch ? k or p_patch->'profile_confirm_all'='true'::jsonb then
     locks:=jsonb_set(locks,array[k],'"manual"');
     delete from public.user_lifetime_profile_dependency where user_id=owner and field=k;
     if k='name' then update public.user_lifetime_profile_authority set name_released=false where user_id=owner;end if;
   end if;
 end loop;
 if p_patch->'profile_confirm_all'='true'::jsonb then
   insert into public.user_lifetime_chosen_name(user_id,conversation_id,project_id,chosen_name,authority)
   select owner,c.conversation_id,project,result->>'name','explicit' from public.user_lifetime_conversation c
   where c.user_id=owner and c.project_id=project
   on conflict(user_id) do update set authority='explicit',chosen_name=excluded.chosen_name,source_id=null,source_version=null;
 end if;
 update public.user_lifetime_profile_authority set field_locks=locks,revision=revision+1,
   auto_enabled=coalesce((p_patch->>'profile_auto_enabled')::boolean,auto_enabled),
   manual_complete=case when p_patch->'profile_confirm_all'='true'::jsonb then true
     when p_patch->'profile_auto_enabled'='true'::jsonb then false
     when (select bool_and(coalesce(locks->>f='manual',false)) from unnest(fields) f) then true
     else manual_complete end
 where user_id=owner;
 if p_patch->'profile_auto_enabled'='true'::jsonb then
   update public.user_lifetime_profile_progress set skipped_round=0,active_round=0 where user_id=owner;
 end if;
 update public.user_profile set profile=result where user_id=owner returning profile into result;
 -- Explicit controls may resume already due work, using the same timeline owner.
 update public.user_memoir_lane set pending=true,attempts=0,error=null,available_at=clock_timestamp()
 where user_id=owner and project_id=project and skill='timeline' and exists(
   select 1 from public.user_lifetime_profile_progress where user_id=owner and project_id=project
     and requested_round>greatest(covered_round,skipped_round));
 return result;
end $$;

-- Extend the single chosen-name writer with explicit UI release authority.
create or replace function public.persist_lifetime_chosen_name(p_conversation_id uuid,p_source_id uuid,p_source_version bigint,p_name text)
returns void language plpgsql security definer set search_path='' as $$
declare owner uuid:=auth.uid(); project text; current_name text; dependency public.user_lifetime_chosen_name%rowtype;
 released boolean; has_dependency boolean;
begin
 select project_id into project from public.user_lifetime_conversation where user_id=owner and conversation_id=p_conversation_id;
 if not found then raise exception 'conversation unavailable';end if;
 select p.profile->>'name' into current_name from public.user_profile p where p.user_id=owner for update;
 select * into dependency from public.user_lifetime_chosen_name where user_id=owner;
 has_dependency:=found;
 select name_released into released from public.user_lifetime_profile_authority where user_id=owner;
 if not coalesce(released,false) and (dependency.authority='explicit' or
   (current_name is not null and (not has_dependency or current_name is distinct from dependency.chosen_name))) then return;end if;
 if length(coalesce(p_name,'')) not between 1 and 120 or not exists(select 1 from public.user_narrator_source
   where user_id=owner and project_id=project and id=p_source_id and version=p_source_version and status='active'
     and position(p_name in text)>0) then raise exception 'exact active chosen-name evidence required';end if;
 insert into public.user_lifetime_chosen_name(user_id,conversation_id,project_id,source_id,source_version,chosen_name,authority)
 values(owner,p_conversation_id,project,p_source_id,p_source_version,p_name,'generated')
 on conflict(user_id) do update set conversation_id=excluded.conversation_id,project_id=excluded.project_id,
   source_id=excluded.source_id,source_version=excluded.source_version,chosen_name=excluded.chosen_name,authority='generated';
 update public.user_lifetime_profile_authority set name_released=false,invalidated_fields=array_remove(invalidated_fields,'name') where user_id=owner;
 update public.user_profile set profile=jsonb_set(profile,'{name}',to_jsonb(p_name)) where user_id=owner;
end $$;

create function public.schedule_lifetime_profile_round() returns trigger
language plpgsql security definer set search_path='' as $$
declare frontier bigint;
begin
 if public.lifetime_profile_due_round(new.ordinal)<>new.ordinal or not exists(
   select 1 from public.user_lifetime_conversation where user_id=new.user_id and project_id=new.project_id) then return new;end if;
 select source_sequence into frontier from public.user_memoir_project where user_id=new.user_id and project_id=new.project_id for update;
 insert into public.user_lifetime_profile_progress(user_id,project_id,requested_round,requested_frontier)
 values(new.user_id,new.project_id,new.ordinal,frontier)
 on conflict(user_id,project_id) do update set
   requested_frontier=case when excluded.requested_round>user_lifetime_profile_progress.requested_round
     then excluded.requested_frontier else user_lifetime_profile_progress.requested_frontier end,
   requested_round=greatest(user_lifetime_profile_progress.requested_round,excluded.requested_round);
 insert into public.user_memoir_lane(user_id,project_id,skill,pending,target_source,target_event)
 select new.user_id,new.project_id,'timeline',true,source_sequence,event_sequence from public.user_memoir_project
 where user_id=new.user_id and project_id=new.project_id
 on conflict(user_id,project_id,skill) do update set pending=true,attempts=0,error=null,available_at=clock_timestamp(),
   target_source=greatest(user_memoir_lane.target_source,excluded.target_source);
 return new;
end $$;
create trigger lifetime_profile_round after insert on public.user_completed_round
 for each row execute function public.schedule_lifetime_profile_round();

create function public.read_lifetime_profile_page(p_lane_id uuid,p_token uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
#variable_conflict use_column
declare snap public.user_lifetime_lane_snapshot%rowtype; job public.user_lifetime_profile_progress%rowtype;
 authority public.user_lifetime_profile_authority%rowtype; source public.user_narrator_source%rowtype;
 page jsonb; profile jsonb; facts jsonb; targets jsonb; mode text; core integer; lo integer; hi integer; due bigint; frontier bigint;
begin
 if not exists(select 1 from public.lifetime_two_lane_rollout where singleton and enabled) then return null;end if;
 snap:=public.lock_lifetime_memoir_lane(p_lane_id,p_token);
 if not exists(select 1 from public.user_memoir_lane where id=p_lane_id and skill='timeline') then return null;end if;
 perform 1 from public.user_agent_turn_lease where user_id=snap.user_id for share;
 if exists(select 1 from public.user_agent_turn_lease where user_id=snap.user_id and expires_at>clock_timestamp()) then return null;end if;
 perform public.ensure_lifetime_profile_authority(snap.user_id);
 select * into authority from public.user_lifetime_profile_authority where user_id=snap.user_id;
 -- Older sessions coalesce to their newest milestone; no historical job replay.
 select public.lifetime_profile_due_round(coalesce(max(ordinal),0)) into due from public.user_completed_round
 where user_id=snap.user_id and project_id=snap.project_id;
 select coalesce(max(pos.sequence),0) into frontier from public.user_completed_round r
 join public.user_narrator_source s on s.user_id=r.user_id and s.project_id=r.project_id and s.client_turn_id=r.turn_id
 join public.user_lifetime_source_position pos on pos.user_id=s.user_id and pos.project_id=s.project_id and pos.source_id=s.id
 where r.user_id=snap.user_id and r.project_id=snap.project_id and r.ordinal<=due;
 insert into public.user_lifetime_profile_progress(user_id,project_id,requested_round,requested_frontier)
 values(snap.user_id,snap.project_id,due,frontier) on conflict(user_id,project_id) do update set
   requested_round=excluded.requested_round,requested_frontier=excluded.requested_frontier
   where excluded.requested_round>user_lifetime_profile_progress.requested_round;
 select * into job from public.user_lifetime_profile_progress where user_id=snap.user_id and project_id=snap.project_id for update;
 if job.active_round=0 and job.requested_round<=greatest(job.covered_round,job.skipped_round) then return null;end if;
 if job.active_round=0 then
   update public.user_lifetime_profile_progress set active_round=requested_round,source_frontier=requested_frontier
   where user_id=snap.user_id and project_id=snap.project_id returning * into job;
 end if;
 select p.profile into profile from public.user_profile p where p.user_id=snap.user_id;
 select coalesce(jsonb_agg(f),'[]') into targets
 from unnest(array['name','birth_year','birth_date_expression','birth_place','childhood_place','avatar_style']) f
 where not(authority.field_locks ? f);
 -- Reference includes protected values, without leaking unrelated application state.
 select coalesce(jsonb_object_agg(f,jsonb_build_object('value',case when length(profile->>f)<=160
   and jsonb_typeof(profile->f) in ('string','number','null') then profile->f else null end,'authority',coalesce(authority.field_locks->>f,
   case when f='name' then (select n.authority from public.user_lifetime_chosen_name n where n.user_id=snap.user_id) end,'automatic'))),'{}')
 into facts from unnest(array['name','birth_year','birth_date_expression','birth_place','childhood_place','avatar_style']) f;
 mode:='extract';
 if not authority.auto_enabled or authority.manual_complete or jsonb_array_length(targets)=0 then mode:='skip';end if;
 select s.* into source from public.user_narrator_source s left join public.user_lifetime_profile_coverage c
 on c.user_id=s.user_id and c.project_id=s.project_id and c.source_id=s.id and c.source_version=s.version
 where s.user_id=snap.user_id and s.project_id=snap.project_id and s.status='active' and s.sequence<=job.source_frontier
   and coalesce(c.next_offset,0)<length(s.text) order by s.sequence limit 1;
 if source.id is null and mode<>'skip' then mode:='reply_only';end if;
 if source.id is not null then
   select coalesce((select next_offset from public.user_lifetime_profile_coverage where user_id=snap.user_id
     and project_id=snap.project_id and source_id=source.id and source_version=source.version),0) into core;
   hi:=least(core+2048,length(source.text));
   lo:=greatest(core-256,0);
   if mode='extract' and exists(select 1 from public.user_interview_turn t where t.user_id=snap.user_id
     and t.project_id=snap.project_id and t.source_id=source.id and t.source_version=source.version
     and t.collector->'plan'->'work'->>'mode'='reply_only') then mode:='reply_only';end if;
 end if;
 -- Read the base without recursively calling the profile-aware wrapper below.
 page:=public.read_lifetime_memoir_lane_page_before_background_profile(p_lane_id,p_token);
 page:=(page-array['input_digest','page_digest','memory_summary','batch'])||jsonb_build_object('complete',false,
   'two_lane',null,'base_revision',coalesce((page->>'base_revision')::bigint,0),
   'events','[]'::jsonb,'partition',null,'source',case when source.id is null or mode='skip' then null else
     jsonb_build_object('id',source.id,'project_id',source.project_id,'version',source.version,'sequence',source.sequence,
       'text',substring(source.text from lo+1 for hi-lo),'char_start',lo,'char_end',hi,'original_length',length(source.text),
       'kind',source.kind,'language',source.language,'status',source.status,'author_role','storyteller') end,
   'profile_context',jsonb_build_object('schema_version',1,'revision',authority.revision,'target_round',job.active_round,
     'covered_round',job.covered_round,'source_frontier',job.source_frontier,'targets',targets,'reference',facts,'work_mode',mode,
     'execution_generation',(select execution_generation from public.user_lifetime_conversation where user_id=snap.user_id
       and conversation_id=snap.conversation_id),'phase_revision',coalesce((select revision from public.user_conversation_phase
         where user_id=snap.user_id and project_id=snap.project_id),0),
     'cursor',jsonb_build_object('source_id',source.id,'version',source.version,
         'char_start',core,'char_end',hi)));
 page:=page||jsonb_build_object('input_digest',encode(sha256(convert_to((page-'token')::text,'UTF8')),'hex'));
 return page||jsonb_build_object('page_digest',encode(sha256(convert_to(page::text,'UTF8')),'hex'));
end $$;

alter function public.read_lifetime_memoir_lane_page(uuid,uuid) rename to read_lifetime_memoir_lane_page_before_background_profile;
revoke all on function public.read_lifetime_memoir_lane_page_before_background_profile(uuid,uuid)
 from public,anon,authenticated,service_role;
create function public.read_lifetime_memoir_lane_page(p_lane_id uuid,p_token uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare page jsonb;
begin
 page:=public.read_lifetime_memoir_lane_page_before_background_profile(p_lane_id,p_token);
 if page->>'skill'='timeline' and exists(select 1 from public.lifetime_two_lane_rollout where singleton and enabled)
   and exists(select 1 from public.user_lifetime_profile_progress where user_id=(page->>'user_id')::uuid
     and project_id=page->>'project_id' and (active_round>0 or requested_round>greatest(covered_round,skipped_round))) then
   page:=(page-'input_digest'-'page_digest')||jsonb_build_object('two_lane_maintenance_required',true);
   page:=page||jsonb_build_object('input_digest',encode(sha256(convert_to((page-'token')::text,'UTF8')),'hex'));
   page:=page||jsonb_build_object('page_digest',encode(sha256(convert_to(page::text,'UTF8')),'hex'));
 end if;
 return page;
end $$;

alter function public.lock_lifetime_memoir_lane_publication(jsonb) rename to lock_lifetime_memoir_lane_publication_before_background_profile;
revoke all on function public.lock_lifetime_memoir_lane_publication_before_background_profile(jsonb)
 from public,anon,authenticated,service_role;
create function public.lock_lifetime_memoir_lane_publication(p_fence jsonb) returns double precision
language plpgsql security definer set search_path='' as $$
declare page jsonb; k text; lane public.user_memoir_lane%rowtype;
begin
 if p_fence->'profile_context' is null or p_fence->'profile_context'='null'::jsonb then
   return public.lock_lifetime_memoir_lane_publication_before_background_profile(p_fence);
 end if;
 if octet_length(p_fence::text)>65536 or auth.uid() is null or auth.uid()::text is distinct from p_fence->>'user_id' then
   raise exception 'canonical profile owner required' using errcode='42501';end if;
 perform 1 from public.lifetime_two_lane_rollout where singleton and enabled for share;
 if not found then raise exception 'profile rollout disabled' using errcode='PT409';end if;
 page:=public.read_lifetime_profile_page((p_fence->>'lane_id')::uuid,(p_fence->>'token')::uuid);
 if page is null or page->'preferences'->'privacy_complete' is distinct from 'true'::jsonb
   or page->'profile_context'->>'work_mode'<>'extract' then
   raise exception 'profile admission deferred or stopped' using errcode='PT409';end if;
 foreach k in array array['schema_version','protocol','lane_id','token','snapshot_id','user_id','project_id','conversation_id',
   'skill','locale','policy_epoch','preference_revision','source_high_water','event_high_water','page_number','root_digest',
   'page_digest','input_digest','preferences','source','partition','events','coverage_round','base_revision',
   'profile_context','two_lane','batch','memory_summary','editorial_request'] loop
   if coalesce(p_fence->k,'null'::jsonb) is distinct from coalesce(page->k,'null'::jsonb) then
     raise exception 'stale canonical profile admission' using errcode='40001';end if;
 end loop;
 if p_fence->'prior_outputs' is distinct from '[]'::jsonb then
   raise exception 'profile cannot reuse timeline outputs' using errcode='22023';end if;
 select * into lane from public.user_memoir_lane where id=(p_fence->>'lane_id')::uuid;
 return greatest(0,extract(epoch from least(lane.lease_until,lane.run_deadline)-clock_timestamp()));
end $$;

create function public.commit_lifetime_profile_page(p_lane_id uuid,p_token uuid,p_page_digest text,p_result jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
#variable_conflict use_column
declare snap public.user_lifetime_lane_snapshot%rowtype; page jsonb; context jsonb; item jsonb; ref jsonb;
 current_profile jsonb; field text; val jsonb; source public.user_narrator_source%rowtype;
 receipt public.user_lifetime_profile_receipt%rowtype; result_digest text; skipped boolean; previous_owner text;
 cursor_data jsonb; target bigint; frontier bigint;
begin
 perform 1 from public.lifetime_two_lane_rollout where singleton and enabled for share;
 if not found then raise exception 'profile rollout disabled' using errcode='PT409';end if;
 -- Upgrade profile before the canonical identity SHARE lock: writes must not
 -- deadlock with another admission holding identity while waiting for profile.
 select l.user_id into snap.user_id from public.user_memoir_lane l where l.id=p_lane_id and l.skill='timeline';
 if not found then raise exception 'timeline owner required' using errcode='42501';end if;
 perform 1 from public.user_memoir_project p join public.user_memoir_lane l on l.user_id=p.user_id and l.project_id=p.project_id
   where l.id=p_lane_id for update of p;
 perform 1 from public.user_profile where user_id=snap.user_id for update;
 snap:=public.lock_lifetime_memoir_lane(p_lane_id,p_token);
 perform 1 from public.user_agent_turn_lease where user_id=snap.user_id for share;
 if exists(select 1 from public.user_agent_turn_lease where user_id=snap.user_id and expires_at>clock_timestamp()) then
   raise exception 'profile commit deferred during interactive turn' using errcode='PT409';end if;
 if jsonb_typeof(p_result) is distinct from 'object' or octet_length(p_result::text)>16384
   or exists(select 1 from jsonb_object_keys(p_result) k where k not in ('profile_patch','skipped'))
   or jsonb_typeof(p_result->'profile_patch') is distinct from 'array'
   or jsonb_array_length(p_result->'profile_patch')>6
   or (p_result ? 'skipped' and jsonb_typeof(p_result->'skipped') is distinct from 'boolean') then
   raise exception 'bounded profile patch required' using errcode='22023';end if;
 result_digest:=encode(sha256(convert_to(p_result::text,'UTF8')),'hex');
 select * into receipt from public.user_lifetime_profile_receipt where user_id=snap.user_id
   and project_id=snap.project_id and page_digest=p_page_digest;
 if found then
   if receipt.result_digest<>result_digest then raise exception 'profile retry body changed' using errcode='PT409';end if;
   return jsonb_build_object('status','page_saved','replayed',true);
 end if;
 page:=public.read_lifetime_profile_page(p_lane_id,p_token);
 if page is null or page->>'page_digest' is distinct from p_page_digest then
   raise exception 'stale profile page' using errcode='PT409';end if;
 context:=page->'profile_context';cursor_data:=context->'cursor';
 target:=(context->>'target_round')::bigint;frontier:=(context->>'source_frontier')::bigint;
 skipped:=coalesce((p_result->>'skipped')::boolean,false);
 if skipped is distinct from (context->>'work_mode'='skip')
   or (context->>'work_mode'<>'extract' and jsonb_array_length(p_result->'profile_patch')<>0)
   or (select count(*)<>count(distinct p->>'field') from jsonb_array_elements(p_result->'profile_patch') p) then
   raise exception 'profile disposition differs from admitted work' using errcode='22023';end if;
 select p.profile into current_profile from public.user_profile p where p.user_id=snap.user_id;
 select s.* into source from public.user_narrator_source s where s.user_id=snap.user_id and s.project_id=snap.project_id
   and s.id=(page->'source'->>'id')::uuid and s.version=(page->'source'->>'version')::bigint and s.status='active';
 for item in select value from jsonb_array_elements(p_result->'profile_patch') loop
   if jsonb_typeof(item) is distinct from 'object' or exists(select 1 from jsonb_object_keys(item) k
     where k not in ('field','value','source_refs')) or not(item ?& array['field','value','source_refs'])
     or jsonb_typeof(item->'field') is distinct from 'string' or not(context->'targets' ? (item->>'field'))
     or jsonb_typeof(item->'source_refs') is distinct from 'array' or jsonb_array_length(item->'source_refs') not between 1 and 4 then
     raise exception 'auto eligible profile field and original evidence required' using errcode='22023';end if;
   field:=item->>'field';val:=item->'value';
   if field='birth_year' then
     if jsonb_typeof(val) is distinct from 'number' or val::text !~ '^[0-9]{4}$'
       or val::text::integer not between 1800 and extract(year from current_date) then
       raise exception 'invalid profile birth year' using errcode='22023';end if;
   elsif jsonb_typeof(val) is distinct from 'string' or length(btrim(val#>>'{}')) not between 1 and
     (case when field in ('name','birth_date_expression') then 120 else 160 end) or val#>>'{}'<>btrim(val#>>'{}')
     or (field='avatar_style' and val#>>'{}' not in ('male','female')) then
     raise exception 'invalid profile value' using errcode='22023';
   end if;
   for ref in select value from jsonb_array_elements(item->'source_refs') loop
     if jsonb_typeof(ref) is distinct from 'object' or exists(select 1 from jsonb_object_keys(ref) k where k not in
       ('source_id','version','quote','char_start','char_end')) or not(ref ?& array['source_id','version','quote','char_start','char_end'])
       or ref->>'source_id' is distinct from source.id::text or ref->'version' is distinct from to_jsonb(source.version)
       or jsonb_typeof(ref->'quote') is distinct from 'string' or length(ref->>'quote') not between 1 and 2304
       or jsonb_typeof(ref->'char_start') is distinct from 'number' or coalesce(ref->>'char_start','') !~ '^[0-9]{1,6}$'
       or jsonb_typeof(ref->'char_end') is distinct from 'number' or coalesce(ref->>'char_end','') !~ '^[0-9]{1,6}$'
       or (ref->>'char_start')::integer<(page->'source'->>'char_start')::integer
       or (ref->>'char_end')::integer>(page->'source'->>'char_end')::integer
       or (ref->>'char_end')::integer-(ref->>'char_start')::integer<>length(ref->>'quote')
       or substring(source.text from (ref->>'char_start')::integer+1
         for (ref->>'char_end')::integer-(ref->>'char_start')::integer) is distinct from ref->>'quote' then
       raise exception 'exact current profile evidence required' using errcode='22023';end if;
   end loop;
   update public.user_lifetime_profile_authority set invalidated_fields=array_remove(invalidated_fields,field) where user_id=snap.user_id;
   if field='name' then
     if not exists(select 1 from jsonb_array_elements(item->'source_refs') r where strpos(r->>'quote',val#>>'{}')>0)
       or exists(select 1 from public.user_lifetime_chosen_name n join public.user_narrator_source s
         on s.user_id=n.user_id and s.project_id=n.project_id and s.id=n.source_id
         where n.user_id=snap.user_id and s.sequence>source.sequence) then
       raise exception 'newer chosen name authority' using errcode='PT409';end if;
     previous_owner:=current_setting('request.jwt.claim.sub',true);
     perform set_config('request.jwt.claim.sub',snap.user_id::text,true);
     perform public.persist_lifetime_chosen_name(snap.conversation_id,source.id,source.version,val#>>'{}');
     perform set_config('request.jwt.claim.sub',coalesce(previous_owner,''),true);
     if not exists(select 1 from public.user_lifetime_chosen_name where user_id=snap.user_id
       and authority='generated' and source_id=source.id and source_version=source.version and chosen_name=val#>>'{}') then
       raise exception 'chosen name authority changed' using errcode='PT409';end if;
   end if;
   current_profile:=jsonb_set(current_profile,array[field],val);
   delete from public.user_lifetime_profile_dependency d where d.user_id=snap.user_id and d.field=item->>'field';
   insert into public.user_lifetime_profile_dependency(user_id,field,project_id,source_id,source_version,char_start,char_end)
   select distinct snap.user_id,field,snap.project_id,source.id,source.version,(r->>'char_start')::integer,(r->>'char_end')::integer
   from jsonb_array_elements(item->'source_refs') r;
 end loop;
 if not skipped then
   update public.user_profile p set profile=current_profile where p.user_id=snap.user_id;
   if source.id is not null then
     insert into public.user_lifetime_profile_coverage values(snap.user_id,snap.project_id,source.id,source.version,
       (page->'source'->>'char_end')::integer)
     on conflict(user_id,project_id,source_id,source_version) do update set next_offset=excluded.next_offset;
   end if;
 end if;
 insert into public.user_lifetime_profile_receipt values(snap.user_id,snap.project_id,p_page_digest,snap.id,result_digest,target,
   (cursor_data->>'source_id')::uuid,(cursor_data->>'version')::bigint,(cursor_data->>'char_start')::integer,
   (cursor_data->>'char_end')::integer,skipped);
 if skipped then
   update public.user_lifetime_profile_progress set skipped_round=greatest(skipped_round,target),active_round=0
   where user_id=snap.user_id and project_id=snap.project_id;
 elsif not exists(select 1 from public.user_narrator_source s left join public.user_lifetime_profile_coverage c
   on c.user_id=s.user_id and c.project_id=s.project_id and c.source_id=s.id and c.source_version=s.version
   where s.user_id=snap.user_id and s.project_id=snap.project_id and s.status='active' and s.sequence<=frontier
     and coalesce(c.next_offset,0)<length(s.text)) then
   update public.user_lifetime_profile_progress set covered_round=greatest(covered_round,target),
     covered_frontier=greatest(covered_frontier,frontier),active_round=0
   where user_id=snap.user_id and project_id=snap.project_id;
 end if;
 -- Only this writer's own preference change may advance its existing snapshot.
 update public.user_lifetime_lane_snapshot s set preference_revision=c.preference_revision,state='pending'
 from public.user_lifetime_conversation c where s.id=snap.id and c.user_id=snap.user_id and c.conversation_id=snap.conversation_id;
 return jsonb_build_object('status','page_saved','replayed',false,'skipped',skipped);
end $$;

create function public.invalidate_lifetime_profile_evidence() returns trigger
language plpgsql security definer set search_path='' as $$
declare owner uuid; project text; fields text[]; k text;
begin
 owner:=old.user_id;project:=old.project_id;
 if tg_table_name='user_narrator_source' then
   if tg_op='UPDATE' and old.version=new.version and old.status=new.status then return new;end if;
   select array_agg(distinct d.field) into fields from public.user_lifetime_profile_dependency d
   where d.user_id=owner and d.project_id=project and d.source_id=old.id;
 else
   if old.policy_epoch=new.policy_epoch then return new;end if;
   -- A source edit also advances policy before revising its source row. Its
   -- source trigger below revokes only the affected fields, preserving others.
   if old.source_sequence<>new.source_sequence then return new;end if;
   -- Privacy changes revoke derived facts immediately. Explicit UI facts have
   -- no source dependencies and remain independent of conversation policy.
   select array_agg(distinct d.field) into fields from public.user_lifetime_profile_dependency d
   where d.user_id=owner and d.project_id=project;
 end if;
 if fields is not null then
   foreach k in array fields loop
     if k='name' then update public.user_lifetime_chosen_name set chosen_name=null,authority='invalidated'
       where user_id=owner and authority='generated';end if;
   end loop;
   delete from public.user_lifetime_profile_dependency d where d.user_id=owner and d.field=any(fields);
   update public.user_lifetime_profile_authority set invalidated_fields=(select array_agg(distinct f)
     from unnest(invalidated_fields||fields) f) where user_id=owner;
   update public.user_profile p set profile=p.profile-fields where p.user_id=owner;
 end if;
 return coalesce(new,old);
end $$;
create trigger lifetime_profile_source_invalidation after update of version,status on public.user_narrator_source
 for each row execute function public.invalidate_lifetime_profile_evidence();
create trigger lifetime_profile_source_deletion before delete on public.user_narrator_source
 for each row execute function public.invalidate_lifetime_profile_evidence();
create trigger lifetime_profile_policy_invalidation after update of policy_epoch on public.user_memoir_project
 for each row execute function public.invalidate_lifetime_profile_evidence();

create function public.invalidate_lifetime_profile_privacy() returns trigger
language plpgsql security definer set search_path='' as $$
declare owner uuid:=coalesce(new.user_id,old.user_id); fields text[];
begin
 if not((tg_op<>'INSERT' and old.kind in ('excluded_topic','paused_topic'))
   or (tg_op<>'DELETE' and new.kind in ('excluded_topic','paused_topic'))) then return coalesce(new,old);end if;
 if tg_op='UPDATE' and old.kind=new.kind and old.data=new.data then return new;end if;
 select array_agg(distinct d.field) into fields from public.user_lifetime_profile_dependency d
 join public.user_lifetime_conversation c on c.user_id=d.user_id and c.project_id=d.project_id
 where d.user_id=owner and c.conversation_id=coalesce(new.conversation_id,old.conversation_id);
 if fields is not null then
   update public.user_lifetime_chosen_name set authority='invalidated',chosen_name=null
     where user_id=owner and authority='generated' and 'name'=any(fields);
   delete from public.user_lifetime_profile_dependency d where d.user_id=owner and d.field=any(fields);
   update public.user_lifetime_profile_authority set invalidated_fields=(select array_agg(distinct f)
     from unnest(invalidated_fields||fields) f) where user_id=owner;
   update public.user_profile p set profile=p.profile-fields where p.user_id=owner;
 end if;
 return coalesce(new,old);
end $$;
create trigger lifetime_profile_privacy_invalidation after insert or update or delete on public.user_lifetime_continuity
 for each row execute function public.invalidate_lifetime_profile_privacy();

create function public.read_lifetime_profile_automation() returns jsonb
language plpgsql security definer set search_path='' as $$
declare identity public.user_lifetime_conversation%rowtype; automation jsonb; progress jsonb; dirty boolean;
begin
 select * into identity from public.user_lifetime_conversation where user_id=auth.uid() and product='memoir';
 if not found then raise exception 'mapped conversation required' using errcode='42501';end if;
 perform 1 from public.user_memoir_project where user_id=identity.user_id and project_id=identity.project_id for share;
 perform 1 from public.user_profile where user_id=identity.user_id for share;
 automation:=coalesce(public.lifetime_profile_automation(identity.user_id),jsonb_build_object('schema_version',1,
   'revision',0,'auto_enabled',true,'stopped',false,'manual_complete',false,'field_locks','{}'::jsonb));
 select to_jsonb(p)-'user_id'-'project_id'||jsonb_build_object('status',case
   when p.active_round>0 or p.requested_round>greatest(p.covered_round,p.skipped_round) then 'pending'
   when p.skipped_round>p.covered_round then 'skipped' when p.covered_round>0 then 'covered' else 'idle' end)
 into progress from public.user_lifetime_profile_progress p
 where p.user_id=identity.user_id and p.project_id=identity.project_id;
 select exists(select 1 from public.user_narrator_source s where s.user_id=identity.user_id and s.project_id=identity.project_id
   and s.status='active' and (s.sequence<=coalesce((progress->>'covered_frontier')::bigint,0)
     or exists(select 1 from public.user_lifetime_profile_coverage old where old.user_id=s.user_id
       and old.project_id=s.project_id and old.source_id=s.id and old.source_version<>s.version))
   and not exists(select 1 from public.user_lifetime_profile_coverage current where current.user_id=s.user_id
     and current.project_id=s.project_id and current.source_id=s.id and current.source_version=s.version
     and current.next_offset>=length(s.text))) into dirty;
 if dirty and progress->>'status'='covered' then progress:=jsonb_set(progress,'{status}','"awaiting_checkpoint"');end if;
 return automation||jsonb_build_object('progress',coalesce(progress,jsonb_build_object('requested_round',0,
   'requested_frontier',0,'active_round',0,'source_frontier',0,'covered_round',0,'covered_frontier',0,'skipped_round',0,'status','idle'))
   ||jsonb_build_object('pending_source_changes',dirty));
end $$;

revoke all on function public.lifetime_profile_due_round(bigint),public.ensure_lifetime_profile_authority(uuid),
 public.lifetime_profile_automation(uuid),public.project_lifetime_profile_authority(),public.schedule_lifetime_profile_round(),
 public.invalidate_lifetime_profile_evidence(),public.invalidate_lifetime_profile_privacy() from public,anon,authenticated,service_role;
revoke all on function public.read_lifetime_profile_page(uuid,uuid),public.commit_lifetime_profile_page(uuid,uuid,text,jsonb),
 public.read_lifetime_memoir_lane_page(uuid,uuid) from public,anon,authenticated;
grant execute on function public.read_lifetime_profile_page(uuid,uuid),public.commit_lifetime_profile_page(uuid,uuid,text,jsonb),
 public.read_lifetime_memoir_lane_page(uuid,uuid) to service_role;
revoke all on function public.set_lifetime_profile_settings(jsonb,uuid),public.lock_lifetime_memoir_lane_publication(jsonb),
 public.read_lifetime_profile_automation() from public,anon;
grant execute on function public.set_lifetime_profile_settings(jsonb,uuid),public.read_lifetime_profile_automation() to authenticated;
grant execute on function public.lock_lifetime_memoir_lane_publication(jsonb) to authenticated,service_role;
commit;
