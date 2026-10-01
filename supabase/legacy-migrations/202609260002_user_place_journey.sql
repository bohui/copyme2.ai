begin;

create table if not exists public.user_place_journey (
  user_id uuid primary key references auth.users(id) on delete cascade,
  schema_version integer not null default 1 check (schema_version = 1),
  status text not null default 'active' check (status = 'active'),
  revision bigint not null default 1 check (revision > 0),
  place text not null check (char_length(btrim(place)) between 1 and 120),
  hierarchy jsonb not null check (
    jsonb_typeof(hierarchy) = 'array'
    and jsonb_array_length(hierarchy) between 1 and 6
    and hierarchy->>0 = 'Earth'
  ),
  granularity text not null check (granularity in ('country', 'region', 'city', 'suburb', 'landmark')),
  latitude double precision,
  longitude double precision,
  duration_ms integer not null default 5200 check (duration_ms between 2800 and 9000),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check ((latitude is null and longitude is null) or (latitude is not null and longitude is not null)),
  check (latitude is null or latitude between -90 and 90),
  check (longitude is null or longitude between -180 and 180)
);

alter table public.user_place_journey enable row level security;
drop policy if exists place_journey_owner on public.user_place_journey;
create policy place_journey_owner on public.user_place_journey for select to authenticated
  using (user_id = (select auth.uid()));
revoke all on public.user_place_journey from anon;
grant select on public.user_place_journey to authenticated;

-- The lease protects this write from concurrent Codex turns. The API validates
-- the marker before calling the function; table constraints remain the final
-- database boundary for malformed or over-precise output.
create or replace function public.upsert_user_place_journey(
  p_lease_token uuid,
  p_journey jsonb
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
    user_id, schema_version, status, revision, place, hierarchy, granularity,
    latitude, longitude, duration_ms, created_at, updated_at
  ) values (
    owner_id,
    coalesce(nullif(p_journey->>'schema_version', '')::integer, 1),
    'active',
    1,
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
    revision = public.user_place_journey.revision + 1,
    place = excluded.place,
    hierarchy = excluded.hierarchy,
    granularity = excluded.granularity,
    latitude = excluded.latitude,
    longitude = excluded.longitude,
    duration_ms = excluded.duration_ms,
    updated_at = pg_catalog.clock_timestamp()
  returning * into saved;

  return pg_catalog.to_jsonb(saved);
end;
$$;

revoke all on function public.upsert_user_place_journey(uuid, jsonb) from public, anon;
grant execute on function public.upsert_user_place_journey(uuid, jsonb) to authenticated;

commit;
