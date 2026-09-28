begin;

-- The visible conversation and its later workspace enrichment can settle in
-- either order. Keep a per-user sequence in the authenticated data plane so
-- older enrichment cannot overwrite a newer correction.
alter table public.user_profile
  add column if not exists agent_source_sequences jsonb not null default '{}'::jsonb;

alter table public.user_memory
  add column if not exists source_sequence bigint not null default 0;

alter table public.user_agent_session
  add column if not exists turn_sequence bigint not null default 0;

alter table public.user_place_journey
  add column if not exists source_sequence bigint not null default 0;

drop function if exists public.upsert_user_place_journey(uuid, jsonb);

create or replace function public.upsert_user_place_journey(
  p_lease_token uuid,
  p_journey jsonb,
  p_source_sequence bigint default 0
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  owner_id uuid := auth.uid();
  held public.user_agent_turn_lease%rowtype;
  saved public.user_place_journey%rowtype;
begin
  if owner_id is null then
    raise exception 'authenticated user required' using errcode = '42501';
  end if;
  select * into held from public.user_agent_turn_lease
    where user_id = owner_id for update;
  if not found or held.lease_token is distinct from p_lease_token
      or held.expires_at <= pg_catalog.clock_timestamp() then
    raise exception 'Codex turn lease lost' using errcode = '42501';
  end if;
  if p_journey is null or pg_catalog.jsonb_typeof(p_journey) <> 'object' then
    raise exception 'place journey object required' using errcode = '22023';
  end if;

  insert into public.user_place_journey(
    user_id, schema_version, status, revision, source_sequence, place,
    hierarchy, granularity, latitude, longitude, duration_ms, created_at, updated_at
  ) values (
    owner_id,
    coalesce(nullif(p_journey->>'schema_version', '')::integer, 1),
    'active',
    1,
    greatest(coalesce(p_source_sequence, 0), 0),
    pg_catalog.btrim(p_journey->>'place'),
    p_journey->'hierarchy',
    pg_catalog.lower(pg_catalog.btrim(p_journey->>'granularity')),
    case when p_journey ? 'latitude' then (p_journey->>'latitude')::double precision else null end,
    case when p_journey ? 'longitude' then (p_journey->>'longitude')::double precision else null end,
    coalesce(nullif(p_journey->>'duration_ms', '')::integer, 5200),
    pg_catalog.clock_timestamp(),
    pg_catalog.clock_timestamp()
  )
  on conflict (user_id) do update set
    schema_version = excluded.schema_version,
    status = excluded.status,
    revision = case when excluded.source_sequence >= public.user_place_journey.source_sequence
      then public.user_place_journey.revision + 1 else public.user_place_journey.revision end,
    source_sequence = greatest(public.user_place_journey.source_sequence, excluded.source_sequence),
    place = case when excluded.source_sequence >= public.user_place_journey.source_sequence
      then excluded.place else public.user_place_journey.place end,
    hierarchy = case when excluded.source_sequence >= public.user_place_journey.source_sequence
      then excluded.hierarchy else public.user_place_journey.hierarchy end,
    granularity = case when excluded.source_sequence >= public.user_place_journey.source_sequence
      then excluded.granularity else public.user_place_journey.granularity end,
    latitude = case when excluded.source_sequence >= public.user_place_journey.source_sequence
      then excluded.latitude else public.user_place_journey.latitude end,
    longitude = case when excluded.source_sequence >= public.user_place_journey.source_sequence
      then excluded.longitude else public.user_place_journey.longitude end,
    duration_ms = case when excluded.source_sequence >= public.user_place_journey.source_sequence
      then excluded.duration_ms else public.user_place_journey.duration_ms end,
    updated_at = case when excluded.source_sequence >= public.user_place_journey.source_sequence
      then pg_catalog.clock_timestamp() else public.user_place_journey.updated_at end
  returning * into saved;

  return pg_catalog.to_jsonb(saved);
end;
$$;

revoke all on function public.upsert_user_place_journey(uuid, jsonb, bigint) from public, anon;
grant execute on function public.upsert_user_place_journey(uuid, jsonb, bigint) to authenticated;

drop function if exists public.commit_user_agent_turn(uuid, text, text, text[]);

create or replace function public.commit_user_agent_turn(
  p_lease_token uuid,
  p_thread_id text,
  p_content text,
  p_source_paths text[] default '{}',
  p_source_sequence bigint default null
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  owner_id uuid := auth.uid();
  held public.user_agent_turn_lease%rowtype;
  saved public.user_memory%rowtype;
  next_sequence bigint;
begin
  if owner_id is null then
    raise exception 'authenticated user required' using errcode = '42501';
  end if;
  select * into held from public.user_agent_turn_lease
    where user_id = owner_id for update;
  if not found or held.lease_token is distinct from p_lease_token
      or held.expires_at <= pg_catalog.clock_timestamp() then
    raise exception 'Codex turn lease lost' using errcode = '42501';
  end if;
  if p_thread_id is null or pg_catalog.btrim(p_thread_id) = '' or p_content is null then
    raise exception 'thread and content required' using errcode = '22023';
  end if;
  if exists (
    select 1 from pg_catalog.unnest(p_source_paths) as source(path)
    where path is null or path !~
      ('^(sessions|archived_sessions|memories)/turns/' || p_lease_token::text || '/[^.].*')
      or path ~ '(^|/)\.'
  ) then
    raise exception 'invalid turn artifact path' using errcode = '22023';
  end if;

  insert into public.user_agent_session(user_id, codex_thread_id, status, turn_sequence, updated_at)
    values (owner_id, p_thread_id, 'active', 1, pg_catalog.clock_timestamp())
    on conflict (user_id) do update set
      codex_thread_id = excluded.codex_thread_id,
      status = excluded.status,
      turn_sequence = public.user_agent_session.turn_sequence + 1,
      updated_at = excluded.updated_at
    returning turn_sequence into next_sequence;

  insert into public.user_memory(user_id, kind, content, source_paths, source_sequence)
    values (owner_id, 'agent', p_content, coalesce(p_source_paths, '{}'), next_sequence)
    returning * into saved;
  return pg_catalog.jsonb_build_array(pg_catalog.to_jsonb(saved));
end;
$$;

revoke all on function public.commit_user_agent_turn(uuid, text, text, text[], bigint) from public, anon;
grant execute on function public.commit_user_agent_turn(uuid, text, text, text[], bigint) to authenticated;

commit;
