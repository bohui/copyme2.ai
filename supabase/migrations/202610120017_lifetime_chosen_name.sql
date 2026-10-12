-- A generated name is a disposable exact-source projection, never an
-- independently authoritative setting. No historical profile backfill.
begin;
create table public.user_lifetime_chosen_name (
 user_id uuid primary key references auth.users(id) on delete cascade,
 conversation_id uuid not null,
 project_id text not null,
 source_id uuid,
 source_version bigint check(source_version>0),
 chosen_name text check(chosen_name is null or length(chosen_name) between 1 and 120),
 authority text not null check(authority in ('generated','invalidated','explicit')),
 check(authority<>'generated' or (source_id is not null and source_version is not null and chosen_name is not null)),
 check(authority<>'invalidated' or chosen_name is null),
 check(authority<>'explicit' or (source_id is null and source_version is null)),
 foreign key(user_id,conversation_id) references public.user_lifetime_conversation(user_id,conversation_id) on delete cascade
);
alter table public.user_lifetime_chosen_name enable row level security;
revoke all on public.user_lifetime_chosen_name from public,anon,authenticated;

-- Policy AFTER triggers mutate identity. Take profile first so their later
-- source-projection cleanup cannot invert settings' profile→identity ordering.
create function public.lock_lifetime_policy_profile() returns trigger
language plpgsql security definer set search_path='' as $$
begin
 if old.policy_epoch is distinct from new.policy_epoch and exists(
   select 1 from public.user_lifetime_conversation where user_id=new.user_id and project_id=new.project_id) then
   perform 1 from public.user_profile where user_id=new.user_id for update;
 end if;
 return new;
end $$;
create trigger lifetime_policy_profile_lock before update of policy_epoch on public.user_memoir_project
 for each row execute function public.lock_lifetime_policy_profile();

-- Generic profile snapshots cannot alter or resurrect source-derived names.
-- This authority lives outside the client-writable JSON. An invalidated marker
-- retains no withdrawn name bytes, and survives profile deletion/reinsertion.
create function public.enforce_lifetime_chosen_name() returns trigger
language plpgsql security definer set search_path='' as $$
declare dependency public.user_lifetime_chosen_name%rowtype;
begin
 select * into dependency from public.user_lifetime_chosen_name where user_id=new.user_id;
 if found then
   if dependency.chosen_name is null then new.profile:=new.profile-'name';
   else new.profile:=pg_catalog.jsonb_set(new.profile,'{name}',pg_catalog.to_jsonb(dependency.chosen_name)); end if;
 end if;
 return new;
end $$;
create trigger lifetime_name_profile_guard before insert or update of profile on public.user_profile
 for each row execute function public.enforce_lifetime_chosen_name();

-- BEFORE INSERT precedes uniqueness and creation-gate waits. Revalidate after
-- those waits and the preference trigger's identity lock, before SQL RETURNING
-- or commit can expose a stale name. Reject rather than post-write cleanup:
-- retry will see current authority in the BEFORE guard. NEW.user_id also covers
-- service/security-definer writes without relying on a caller-supplied marker.
create function public.verify_lifetime_chosen_name_write() returns trigger
language plpgsql security definer set search_path='' as $$
declare dependency public.user_lifetime_chosen_name%rowtype;
begin
 select * into dependency from public.user_lifetime_chosen_name where user_id=new.user_id;
 if found and new.profile->>'name' is distinct from dependency.chosen_name then
   raise exception 'chosen-name authority changed; retry profile write' using errcode='40001';
 end if;
 return new;
end $$;
create trigger zz_lifetime_name_write_validation after insert or update of profile on public.user_profile
 for each row execute function public.verify_lifetime_chosen_name_write();

create function public.clear_deleted_lifetime_name() returns trigger
language plpgsql security definer set search_path='' as $$
begin
 update public.user_lifetime_chosen_name set authority='invalidated',chosen_name=null where user_id=old.user_id;
 return old;
end $$;
create trigger lifetime_name_deleted before delete on public.user_profile
 for each row execute function public.clear_deleted_lifetime_name();

create function public.persist_lifetime_chosen_name(p_conversation_id uuid,p_source_id uuid,p_source_version bigint,p_name text)
returns void language plpgsql security definer set search_path='' as $$
declare owner uuid:=auth.uid(); project text; current_name text; dependency public.user_lifetime_chosen_name%rowtype;
begin
 select project_id into project from public.user_lifetime_conversation where user_id=owner and conversation_id=p_conversation_id;
 if not found then raise exception 'conversation unavailable'; end if;
 -- Called only inside the exact-source validated, fenced turn commit, which
 -- already owns project and profile locks. No authenticated direct grant.
 select profile->>'name' into current_name from public.user_profile where user_id=owner for update;
 select * into dependency from public.user_lifetime_chosen_name where user_id=owner;
 if dependency.authority='explicit' or (current_name is not null and (not found or current_name is distinct from dependency.chosen_name)) then return; end if;
 if length(coalesce(p_name,'')) not between 1 and 120 or not exists(
   select 1 from public.user_narrator_source where user_id=owner and project_id=project and id=p_source_id
     and version=p_source_version and status='active' and position(p_name in text)>0) then
   raise exception 'exact active chosen-name evidence required';
 end if;
 insert into public.user_lifetime_chosen_name(user_id,conversation_id,project_id,source_id,source_version,chosen_name,authority)
 values(owner,p_conversation_id,project,p_source_id,p_source_version,p_name,'generated')
 on conflict(user_id) do update set conversation_id=excluded.conversation_id,project_id=excluded.project_id,
   source_id=excluded.source_id,source_version=excluded.source_version,chosen_name=excluded.chosen_name,authority='generated';
 update public.user_profile set profile=pg_catalog.jsonb_set(profile,'{name}',pg_catalog.to_jsonb(p_name)) where user_id=owner;
end $$;

create function public.invalidate_lifetime_chosen_name() returns trigger
language plpgsql security definer set search_path='' as $$
declare dependency public.user_lifetime_chosen_name%rowtype;
begin
 if old.version is distinct from new.version or old.status is distinct from new.status then
   select * into dependency from public.user_lifetime_chosen_name where user_id=new.user_id
     and project_id=new.project_id and source_id=new.id and authority='generated';
   if found then
     update public.user_lifetime_chosen_name set authority='invalidated',chosen_name=null where user_id=new.user_id;
     update public.user_profile set profile=profile-'name' where user_id=new.user_id;
   end if;
 end if;
 return new;
end $$;
create trigger lifetime_chosen_name_invalidation after update of version,status on public.user_narrator_source
 for each row execute function public.invalidate_lifetime_chosen_name();

create function public.set_lifetime_profile_settings(p_patch jsonb,p_lease_token uuid)
returns jsonb language plpgsql security definer set search_path='' as $$
declare owner uuid:=auth.uid(); project text; current_profile jsonb; item record; value jsonb; locale text;
 previous jsonb; next_language jsonb; revision bigint;
begin
 select project_id into project from public.user_lifetime_conversation where user_id=owner and product='memoir';
 if not found then raise exception 'mapped conversation required' using errcode='42501'; end if;
 if pg_catalog.jsonb_typeof(p_patch) is distinct from 'object' or exists(select 1 from pg_catalog.jsonb_object_keys(p_patch) key
   where key not in ('name','preferred_language','birth_year','birth_place','childhood_place')) then
   raise exception 'invalid profile settings patch' using errcode='22023';
 end if;
 perform 1 from public.user_memoir_project where user_id=owner and project_id=project for update;
 insert into public.user_profile(user_id,profile) values(owner,'{}') on conflict do nothing;
 select profile into current_profile from public.user_profile where user_id=owner for update;
 perform 1 from public.user_agent_turn_lease where user_id=owner and lease_token=p_lease_token
   and expires_at>clock_timestamp() for share;
 if not found then raise exception 'valid turn lease required' using errcode='40001'; end if;
 for item in select * from pg_catalog.jsonb_each(p_patch) loop
   value:=item.value;
   if value<>'null'::jsonb then
     if item.key='birth_year' then
       if pg_catalog.jsonb_typeof(value)<>'number' or value::text !~ '^[0-9]+$'
         or value::text::numeric not between 1800 and extract(year from current_date) then
         raise exception 'invalid birth year' using errcode='22023'; end if;
     else
       if pg_catalog.jsonb_typeof(value)<>'string' then raise exception 'invalid text setting' using errcode='22023'; end if;
       value:=pg_catalog.to_jsonb(pg_catalog.btrim(value#>>'{}'));
       if length(value#>>'{}')>(case when item.key='name' then 120 else 160 end) then
         raise exception 'text setting exceeds limit' using errcode='22023'; end if;
       if value='""'::jsonb then value:='null'::jsonb; end if;
     end if;
   end if;
   if item.key='preferred_language' then
     locale:=value#>>'{}';
     if locale is not null and locale not in ('en-AU','zh-CN') then raise exception 'invalid language setting' using errcode='22023'; end if;
     previous:=current_profile->'conversation_language';
     if pg_catalog.jsonb_typeof(previous) is distinct from 'object' or previous->'version' is distinct from '1'::jsonb
       or previous->'initialized' is distinct from 'true'::jsonb then previous:=null; end if;
     revision:=case when coalesce(previous->>'revision','') ~ '^[0-9]{1,16}$' then (previous->>'revision')::bigint else 0 end;
     if locale is not null then
       next_language:=pg_catalog.jsonb_build_object('version',1,'initialized',true,'revision',revision+1,'locale',locale,'source','explicit',
         'first_reply_locale',previous->'first_reply_locale','first_reply_fallback',previous->'first_reply_fallback','first_reply_id',previous->'first_reply_id');
       current_profile:=pg_catalog.jsonb_set(current_profile,'{conversation_language}',next_language);
     elsif previous is not null then
       next_language:=previous||pg_catalog.jsonb_build_object('revision',revision+1,
         'locale',coalesce(nullif(previous->'first_reply_locale','null'::jsonb),previous->'first_reply_fallback'),'source','first_reply');
       current_profile:=pg_catalog.jsonb_set(current_profile,'{conversation_language}',next_language);
     end if;
   end if;
   if value='null'::jsonb then current_profile:=current_profile-item.key;
   else current_profile:=pg_catalog.jsonb_set(current_profile,array[item.key],value); end if;
 end loop;
 if p_patch ? 'name' then
   insert into public.user_lifetime_chosen_name(user_id,conversation_id,project_id,chosen_name,authority)
   select owner,conversation_id,project,current_profile->>'name','explicit' from public.user_lifetime_conversation where user_id=owner and product='memoir'
   on conflict(user_id) do update set authority='explicit',chosen_name=excluded.chosen_name,source_id=null,source_version=null;
 end if;
 update public.user_profile set profile=current_profile where user_id=owner;
 return current_profile;
end $$;

revoke all on function public.lock_lifetime_policy_profile(),public.enforce_lifetime_chosen_name(),public.verify_lifetime_chosen_name_write(),public.clear_deleted_lifetime_name(),
 public.persist_lifetime_chosen_name(uuid,uuid,bigint,text),public.invalidate_lifetime_chosen_name(),
 public.set_lifetime_profile_settings(jsonb,uuid) from public,anon,authenticated;
grant execute on function public.set_lifetime_profile_settings(jsonb,uuid) to authenticated;
commit;
