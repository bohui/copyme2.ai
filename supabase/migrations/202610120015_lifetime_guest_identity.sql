-- Issue 60 W1: preserve the established guest transfer and report the explicit
-- identity decision still required. This never creates or changes a mapping.
begin;

-- Legacy restoration predates user_memoir_project. Inventory every owned
-- restoration source before resolving a genuinely new account; never adopt,
-- rewrite or silently hide these older histories.
create or replace function public.resolve_lifetime_conversation(p_project_id text default null)
returns jsonb language plpgsql security definer set search_path='' as $$
declare
  owner uuid:=auth.uid();
  identity public.user_lifetime_conversation%rowtype;
  projects jsonb;
  new_project text;
  guest boolean;
  unscoped boolean;
begin
  if owner is null then raise exception 'authenticated owner required'; end if;
  select is_anonymous into guest from auth.users where id=owner for update;
  if not found or guest then raise exception 'verified account required'; end if;
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
    if pg_catalog.jsonb_array_length(projects)>0 or unscoped then
      return pg_catalog.jsonb_build_object('schema_version',1,'outcome','mapping_required','project_ids',projects)
        || case when unscoped then pg_catalog.jsonb_build_object('unscoped_history',true) else '{}'::jsonb end;
    end if;
    new_project:='lifetime-' || pg_catalog.gen_random_uuid()::text;
    insert into public.user_memoir_project(user_id,project_id) values(owner,new_project);
    insert into public.user_lifetime_conversation(user_id,project_id) values(owner,new_project) returning * into identity;
  end if;
  return pg_catalog.jsonb_build_object('schema_version',1,'outcome','resolved','owner_id',owner,
    'conversation_id',identity.conversation_id,'product',identity.product,'project_id',identity.project_id);
end $$;
revoke all on function public.resolve_lifetime_conversation(text) from public,anon,authenticated;
grant execute on function public.resolve_lifetime_conversation(text) to authenticated;

-- Choose only the compatibility execution lane, never a canonical project.
-- A mapped owner cannot downgrade by submitting another project identifier.
create or replace function public.read_lifetime_admission(p_project_id text default null)
returns text language plpgsql stable security definer set search_path='' as $$
declare owner uuid:=auth.uid(); guest boolean;
begin
  if owner is null then raise exception 'authenticated owner required' using errcode='42501'; end if;
  select is_anonymous into guest from auth.users where id=owner;
  if not found then raise exception 'authenticated owner required' using errcode='42501'; end if;
  if guest then return 'legacy'; end if;
  if exists(select 1 from public.user_lifetime_conversation where user_id=owner and product='memoir') then
    return 'governed';
  end if;
  if p_project_id is not null and (
      exists(select 1 from public.user_memoir_project where user_id=owner and project_id=p_project_id)
      or exists(select 1 from public.user_memory where user_id=owner and project_id=p_project_id)
      or exists(select 1 from public.user_conversation_attachment where user_id=owner and project_id=p_project_id)) then
    return 'legacy';
  end if;
  return 'governed';
end $$;
revoke all on function public.read_lifetime_admission(text) from public,anon,authenticated;
grant execute on function public.read_lifetime_admission(text) to authenticated;

do $$ begin
  if pg_catalog.to_regprocedure('public.attach_guest_conversation_before_lifetime(text,boolean)') is null then
    alter function public.attach_guest_conversation(text,boolean) rename to attach_guest_conversation_before_lifetime;
  end if;
end $$;
revoke all on function public.attach_guest_conversation_before_lifetime(text,boolean) from public,anon,authenticated;

create or replace function public.attach_guest_conversation(p_token text,p_guest_wins boolean default false)
returns jsonb language plpgsql security definer set search_path='' as $$
declare
  result jsonb;
  transferred_project text;
  canonical public.user_lifetime_conversation%rowtype;
  owner uuid := auth.uid();
begin
  -- The resolver locks this same owner row. Concurrent first-home resolution
  -- therefore sees the transferred history, or transfer sees the established
  -- canonical identity; neither ordering silently adopts the guest project.
  perform 1 from auth.users where id=owner for update;
  if not found then raise exception 'authenticated owner required' using errcode='42501'; end if;
  result := public.attach_guest_conversation_before_lifetime(p_token,p_guest_wins);
  select project_id into transferred_project from public.user_conversation_attachment
    where user_id=owner and id=(result->>'conversation_id')::uuid;
  select * into canonical from public.user_lifetime_conversation where user_id=owner and product='memoir';
  if found and transferred_project is not null and transferred_project<>canonical.project_id then
    result := result || pg_catalog.jsonb_build_object('lifetime_identity',pg_catalog.jsonb_build_object(
      'schema_version',1,'outcome','mapping_required',
      'transferred_project_id',transferred_project,'canonical_project_id',canonical.project_id,
      'conversation_id',canonical.conversation_id));
  end if;
  return result;
end $$;
revoke all on function public.attach_guest_conversation(text,boolean) from public,anon,authenticated;
grant execute on function public.attach_guest_conversation(text,boolean) to authenticated;

commit;
