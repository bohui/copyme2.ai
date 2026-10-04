-- Tag every captured response and support ordered stage retrieval for composition.
begin;

alter table public.user_memory drop constraint user_memory_life_stage_check;
alter table public.user_memory add constraint user_memory_life_stage_check
  check (life_stage in ('baby','toddler','childhood','adolescence','young_adulthood','midlife','later_life','unplaced'));
alter table public.user_memory alter column life_stage set default 'unplaced';
update public.user_memory set life_stage='unplaced' where life_stage is null;
alter table public.user_memory alter column life_stage set not null;
alter table public.user_memory add column life_stage_order smallint generated always as
  (case life_stage when 'baby' then 0 when 'toddler' then 1 when 'childhood' then 2
    when 'adolescence' then 3 when 'young_adulthood' then 4 when 'midlife' then 5
    when 'later_life' then 6 else 7 end) stored;
create index user_memory_stage_sources on public.user_memory
  (user_id,project_id,life_stage_order,created_at,id);

-- Old guest attachment snapshots may contain an explicit null stage.
create function public.normalize_response_stage() returns trigger
language plpgsql set search_path='' as $$
begin
  new.life_stage:=coalesce(new.life_stage,'unplaced');
  return new;
end $$;
create trigger normalize_response_stage before insert or update on public.user_memory
  for each row execute function public.normalize_response_stage();

-- Publish a known stage together with the exchange and round/outbox boundary.
drop function public.commit_user_agent_turn(uuid,text,text,text[],bigint,text,uuid,boolean);
create function public.commit_user_agent_turn(
  p_lease_token uuid,p_thread_id text,p_content text,p_source_paths text[] default '{}',
  p_source_sequence bigint default null,p_project_id text default null,
  p_client_turn_id uuid default null,p_user_response boolean default true,
  p_life_stage text default 'unplaced'
) returns jsonb language plpgsql security definer set search_path='' as $$
declare owner_id uuid:=auth.uid(); saved public.user_memory%rowtype; result jsonb;
begin
  if owner_id is null then raise exception 'authenticated user required' using errcode='42501'; end if;
  if p_project_id is not null and p_project_id !~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$' then
    raise exception 'invalid project' using errcode='22023'; end if;
  if p_client_turn_id is not null then
    select * into saved from public.user_memory where user_id=owner_id and client_turn_id=p_client_turn_id
      and project_id is not distinct from p_project_id;
    if found then return pg_catalog.jsonb_build_array(pg_catalog.to_jsonb(saved)); end if;
  end if;
  result:=public.commit_user_agent_turn_legacy(p_lease_token,p_thread_id,p_content,p_source_paths,p_source_sequence);
  update public.user_memory set project_id=p_project_id,client_turn_id=p_client_turn_id,
      life_stage=coalesce(p_life_stage,'unplaced'),
      kind=case when p_user_response then 'agent' else 'agent_greeting' end
    where id=(result->0->>'id')::uuid and user_id=owner_id returning * into saved;
  if not p_user_response then
    update public.user_recall_usage set rounds_completed=greatest(rounds_completed-1,0) where user_id=owner_id;
  end if;
  return pg_catalog.jsonb_build_array(pg_catalog.to_jsonb(saved));
end $$;
revoke all on function public.commit_user_agent_turn(uuid,text,text,text[],bigint,text,uuid,boolean,text) from public,anon;
grant execute on function public.commit_user_agent_turn(uuid,text,text,text[],bigint,text,uuid,boolean,text) to authenticated;

commit;
