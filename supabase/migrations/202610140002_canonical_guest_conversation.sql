-- Anonymous Supabase sessions are authenticated storytellers too. Resolve their
-- first canonical conversation without adopting any previously saved history.
begin;

create or replace function public.resolve_lifetime_conversation(p_project_id text default null)
returns jsonb language plpgsql security definer set search_path='' as $$
declare
  owner uuid:=auth.uid();
  identity public.user_lifetime_conversation%rowtype;
  projects jsonb;
  new_project text;
  guest boolean;
  unscoped boolean;
  empty_guest_project boolean:=false;
begin
  if owner is null then raise exception 'authenticated owner required'; end if;
  select is_anonymous into guest from auth.users where id=owner for update;
  if not found then raise exception 'authenticated owner required'; end if;
  select * into identity from public.user_lifetime_conversation where user_id=owner and product='memoir';
  if found then
    if p_project_id is not null and p_project_id<>identity.project_id then
      raise exception 'project does not match canonical conversation';
    end if;
  else
    select coalesce(pg_catalog.jsonb_agg(project_id order by project_id),'[]'::jsonb) into projects from (
      select project_id from public.user_memoir_project where user_id=owner
      union select project_id from public.user_memory where user_id=owner and project_id is not null
      union select project_id from public.user_conversation_attachment where user_id=owner
    ) owned;
    if p_project_id is not null and not (projects ? p_project_id) then
      raise exception 'owned project required';
    end if;
    select exists(select 1 from public.user_memory where user_id=owner and project_id is null) into unscoped;
    -- Older guest onboarding created an empty project before the first answer.
    -- Preserve that server-owned ID only when no testimony was ever accepted.
    if guest and not unscoped and pg_catalog.jsonb_array_length(projects)=1 then
      new_project:=projects->>0;
      select exists(select 1 from public.user_memoir_project
        where user_id=owner and project_id=new_project and source_sequence=0 and event_sequence=0)
        and not exists(select 1 from public.user_narrator_source where user_id=owner)
        and not exists(select 1 from public.user_memory where user_id=owner)
        and not exists(select 1 from public.user_conversation_attachment where user_id=owner)
        and not exists(select 1 from public.user_completed_round where user_id=owner)
        into empty_guest_project;
    end if;
    if (pg_catalog.jsonb_array_length(projects)>0 or unscoped) and not empty_guest_project then
      return pg_catalog.jsonb_build_object('schema_version',1,'outcome','mapping_required','project_ids',projects)
        || case when unscoped then pg_catalog.jsonb_build_object('unscoped_history',true) else '{}'::jsonb end;
    end if;
    if not empty_guest_project then
      new_project:='lifetime-' || pg_catalog.gen_random_uuid()::text;
      insert into public.user_memoir_project(user_id,project_id) values(owner,new_project);
    end if;
    insert into public.user_lifetime_conversation(user_id,project_id) values(owner,new_project) returning * into identity;
  end if;
  return pg_catalog.jsonb_build_object('schema_version',1,'outcome','resolved','owner_id',owner,
    'conversation_id',identity.conversation_id,'product',identity.product,'project_id',identity.project_id);
end $$;
revoke all on function public.resolve_lifetime_conversation(text) from public,anon,authenticated;
grant execute on function public.resolve_lifetime_conversation(text) to authenticated;

notify pgrst, 'reload schema';
commit;
