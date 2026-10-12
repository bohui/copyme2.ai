-- Issue 60 W1: additive lifetime identity. No historical backfill or activation.
begin;

create table public.user_lifetime_conversation (
  conversation_id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  product text not null default 'memoir' check(product='memoir'),
  project_id text not null,
  execution_generation bigint not null default 1 check(execution_generation>0),
  preference_revision bigint not null default 0 check(preference_revision>=0),
  created_at timestamptz not null default clock_timestamp(),
  unique(user_id, product),
  unique(user_id, project_id),
  unique(user_id, conversation_id),
  foreign key(user_id,project_id) references public.user_memoir_project(user_id,project_id)
);
alter table public.user_lifetime_conversation enable row level security;
revoke all on public.user_lifetime_conversation from public, anon, authenticated;
grant select on public.user_lifetime_conversation to authenticated;
create policy lifetime_conversation_owner on public.user_lifetime_conversation for select to authenticated
  using(user_id=auth.uid());

-- Authenticated resolution never picks a historical project, even a sole one.
-- Approved historical mappings are a separately reviewed service-side operation;
-- no callable authenticated mapping mutator or automatic migration is installed.
create function public.resolve_lifetime_conversation(p_project_id text default null)
returns jsonb language plpgsql security definer set search_path=public,auth as $$
declare
  owner uuid := auth.uid();
  identity public.user_lifetime_conversation%rowtype;
  projects jsonb;
  new_project text;
  guest boolean;
begin
  if owner is null then raise exception 'authenticated owner required'; end if;
  -- Serialize first resolution across tabs; no browser supplied identity is used.
  select is_anonymous into guest from auth.users where id=owner for update;
  if not found or guest then raise exception 'verified account required'; end if;
  select * into identity from public.user_lifetime_conversation where user_id=owner and product='memoir';
  if found then
    if p_project_id is not null and p_project_id<>identity.project_id then
      raise exception 'project does not match canonical conversation';
    end if;
  else
    if p_project_id is not null and not exists(select 1 from public.user_memoir_project where user_id=owner and project_id=p_project_id) then
      raise exception 'owned project required';
    end if;
    select coalesce(jsonb_agg(project_id order by project_id),'[]'::jsonb) into projects
      from public.user_memoir_project where user_id=owner;
    if jsonb_array_length(projects)>0 then
      return jsonb_build_object('schema_version',1,'outcome','mapping_required','project_ids',projects);
    end if;
    new_project := 'lifetime-' || gen_random_uuid()::text;
    insert into public.user_memoir_project(user_id,project_id) values(owner,new_project);
    insert into public.user_lifetime_conversation(user_id,project_id) values(owner,new_project) returning * into identity;
  end if;
  return jsonb_build_object('schema_version',1,'outcome','resolved','owner_id',owner,
    'conversation_id',identity.conversation_id,'product',identity.product,'project_id',identity.project_id);
end;
$$;
revoke all on function public.resolve_lifetime_conversation(text) from public,anon;
grant execute on function public.resolve_lifetime_conversation(text) to authenticated;

commit;
