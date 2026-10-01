-- Memoir development schema: consolidated from the original migration sequence.
-- Apply this file through Supabase migration tracking; do not apply archive files directly.


-- -----------------------------------------------------------------------------
-- Source: 202609230001_user_agent_storage.sql
-- -----------------------------------------------------------------------------

begin;

create table public.user_profile (
  user_id uuid primary key references auth.users(id) on delete cascade,
  profile jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create table public.user_memory (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  kind text not null check (kind in ('memoir', 'agent')),
  content text not null,
  source_paths text[] not null default '{}',
  created_at timestamptz not null default now()
);
create index user_memory_owner_created on public.user_memory(user_id, created_at desc);

alter table public.user_profile enable row level security;
alter table public.user_memory enable row level security;
create policy profile_owner on public.user_profile for all to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
create policy memory_owner on public.user_memory for all to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
revoke all on public.user_profile, public.user_memory from anon;
grant select, insert, update, delete on public.user_profile, public.user_memory to authenticated;

insert into storage.buckets(id, name, public, file_size_limit)
  values ('memory-spark', 'memory-spark', false, 52428800)
  on conflict (id) do update set name = excluded.name, public = excluded.public,
    file_size_limit = excluded.file_size_limit;
create policy memory_spark_owner on storage.objects for all to authenticated
  using (bucket_id = 'memory-spark' and (storage.foldername(name))[1] = (select auth.uid())::text)
  with check (bucket_id = 'memory-spark' and (storage.foldername(name))[1] = (select auth.uid())::text
    and (storage.foldername(name))[2] in ('attachment', 'agent'));

commit;


-- -----------------------------------------------------------------------------
-- Source: 202609230002_agent_sessions.sql
-- -----------------------------------------------------------------------------

begin;

create table public.user_agent_session (
  user_id uuid primary key references auth.users(id) on delete cascade,
  codex_thread_id text not null,
  status text not null default 'active' check (status in ('active', 'paused', 'failed')),
  updated_at timestamptz not null default now()
);

alter table public.user_agent_session enable row level security;
create policy agent_session_owner on public.user_agent_session for all to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
revoke all on public.user_agent_session from anon;
grant select, insert, update, delete on public.user_agent_session to authenticated;

commit;


-- -----------------------------------------------------------------------------
-- Source: 202609240001_memory_spark_state.sql
-- -----------------------------------------------------------------------------

-- Retired. Memory Spark's product journey now uses the RLS-protected
-- user_profile and user_memory tables. Existing installations are cleaned up
-- by 202609250001_remove_memory_spark_state.sql.


-- -----------------------------------------------------------------------------
-- Source: 202609250001_remove_memory_spark_state.sql
-- -----------------------------------------------------------------------------

begin;

-- These tables belonged to the retired singleton JSONB store and its durable
-- outbox. They are intentionally not replaced: user-owned story data lives in
-- user_profile/user_memory and Codex artifacts live in Storage.
drop table if exists public.memory_spark_outbox;
drop table if exists public.memory_spark_state;

commit;


-- -----------------------------------------------------------------------------
-- Source: 202609250002_agent_turn_leases.sql
-- -----------------------------------------------------------------------------

begin;

-- A lease is the cross-replica serialization point for Codex thread turns.
-- The row is owned by the authenticated user, but direct table access is not
-- granted; callers use the narrowly-scoped RPC functions below.
create table public.user_agent_turn_lease (
  user_id uuid primary key references auth.users(id) on delete cascade,
  lease_token uuid not null,
  expires_at timestamptz not null,
  updated_at timestamptz not null default now()
);

alter table public.user_agent_turn_lease enable row level security;
create policy agent_turn_lease_owner on public.user_agent_turn_lease
  for all to authenticated
  using (user_id = (select auth.uid()))
  with check (user_id = (select auth.uid()));

revoke all on public.user_agent_turn_lease from public, anon, authenticated;

create or replace function public.acquire_user_agent_turn_lease(
  p_lease_token uuid,
  p_lease_seconds integer default 300
)
returns boolean
language plpgsql
security definer
set search_path = public, auth
as $$
declare
  current_user_id uuid := auth.uid();
  acquired boolean := false;
  duration_seconds integer := greatest(30, least(coalesce(p_lease_seconds, 300), 900));
begin
  if current_user_id is null then
    raise exception 'authenticated user required';
  end if;
  if p_lease_token is null then
    raise exception 'lease token required';
  end if;

  insert into public.user_agent_turn_lease(user_id, lease_token, expires_at)
    values (current_user_id, p_lease_token, now() + make_interval(secs => duration_seconds))
  on conflict (user_id) do update
    set lease_token = excluded.lease_token,
        expires_at = excluded.expires_at,
        updated_at = now()
    where public.user_agent_turn_lease.expires_at <= now()
  returning true into acquired;

  return coalesce(acquired, false);
end;
$$;

create or replace function public.renew_user_agent_turn_lease(
  p_lease_token uuid,
  p_lease_seconds integer default 300
)
returns boolean
language plpgsql
security definer
set search_path = public, auth
as $$
declare
  current_user_id uuid := auth.uid();
  renewed boolean := false;
  duration_seconds integer := greatest(30, least(coalesce(p_lease_seconds, 300), 900));
begin
  if current_user_id is null then
    raise exception 'authenticated user required';
  end if;

  update public.user_agent_turn_lease
     set expires_at = now() + make_interval(secs => duration_seconds),
         updated_at = now()
   where user_id = current_user_id
     and lease_token = p_lease_token
     and expires_at > now()
  returning true into renewed;

  return coalesce(renewed, false);
end;
$$;

create or replace function public.release_user_agent_turn_lease(p_lease_token uuid)
returns boolean
language plpgsql
security definer
set search_path = public, auth
as $$
declare
  current_user_id uuid := auth.uid();
  released boolean := false;
begin
  if current_user_id is null then
    raise exception 'authenticated user required';
  end if;

  delete from public.user_agent_turn_lease
   where user_id = current_user_id
     and lease_token = p_lease_token;
  released := found;
  return released;
end;
$$;

revoke all on function public.acquire_user_agent_turn_lease(uuid, integer) from public, anon;
revoke all on function public.renew_user_agent_turn_lease(uuid, integer) from public, anon;
revoke all on function public.release_user_agent_turn_lease(uuid) from public, anon;
grant execute on function public.acquire_user_agent_turn_lease(uuid, integer) to authenticated;
grant execute on function public.renew_user_agent_turn_lease(uuid, integer) to authenticated;
grant execute on function public.release_user_agent_turn_lease(uuid) to authenticated;

commit;


-- -----------------------------------------------------------------------------
-- Source: 202609250003_story_entitlements.sql
-- -----------------------------------------------------------------------------

begin;

-- Payment state is server-controlled. Storytellers can read their own
-- entitlement, but cannot insert or update it through the browser token.
create table if not exists public.story_entitlements (
  user_id uuid primary key references auth.users(id) on delete cascade,
  status text not null check (status in ('paid', 'revoked')),
  plan_key text not null,
  book_count integer not null check (book_count >= 0),
  amount_minor integer not null check (amount_minor >= 0),
  currency text not null,
  electronic_only boolean not null default false,
  family_tree boolean not null default false,
  timeline boolean not null default false,
  expanded_details boolean not null default false,
  stripe_session_id text not null unique,
  stripe_payment_intent_id text,
  paid_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.story_entitlements enable row level security;

drop policy if exists story_entitlement_owner_select on public.story_entitlements;
create policy story_entitlement_owner_select on public.story_entitlements
  for select to authenticated
  using (user_id = (select auth.uid()));

revoke all on public.story_entitlements from anon;
grant select on public.story_entitlements to authenticated;
grant all on public.story_entitlements to service_role;

commit;


-- -----------------------------------------------------------------------------
-- Source: 202609250004_fenced_agent_turn_commit.sql
-- -----------------------------------------------------------------------------

begin;

-- The lease row lock serializes this commit against acquisition, renewal and
-- release. RLS alone establishes ownership, not which replica owns the turn.
create or replace function public.commit_user_agent_turn(
  p_lease_token uuid,
  p_thread_id text,
  p_content text,
  p_source_paths text[] default '{}'
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
begin
  if owner_id is null then
    raise exception 'authenticated user required' using errcode = '42501';
  end if;
  select * into held from public.user_agent_turn_lease
    where user_id = owner_id for update;
  -- clock_timestamp, not transaction-start now(): the SELECT may have waited.
  if not found or held.lease_token is distinct from p_lease_token
      or held.expires_at <= pg_catalog.clock_timestamp() then
    raise exception 'Codex turn lease lost' using errcode = '42501';
  end if;
  if p_thread_id is null or pg_catalog.btrim(p_thread_id) = '' or p_content is null then
    raise exception 'thread and content required' using errcode = '22023';
  end if;
  -- Only immutable uploads belonging to this attempt may be published.
  if exists (
    select 1 from pg_catalog.unnest(p_source_paths) as source(path)
    where path is null or path !~
      ('^(sessions|archived_sessions|memories)/turns/' || p_lease_token::text || '/[^.].*')
      or path ~ '(^|/)\.'
  ) then
    raise exception 'invalid turn artifact path' using errcode = '22023';
  end if;

  insert into public.user_agent_session(user_id, codex_thread_id, status, updated_at)
    values (owner_id, p_thread_id, 'active', pg_catalog.clock_timestamp())
    on conflict (user_id) do update set
      codex_thread_id = excluded.codex_thread_id,
      status = excluded.status, updated_at = excluded.updated_at;
  insert into public.user_memory(user_id, kind, content, source_paths)
    values (owner_id, 'agent', p_content, coalesce(p_source_paths, '{}'))
    returning * into saved;
  return pg_catalog.jsonb_build_array(pg_catalog.to_jsonb(saved));
end;
$$;

revoke all on function public.commit_user_agent_turn(uuid, text, text, text[]) from public, anon;
grant execute on function public.commit_user_agent_turn(uuid, text, text, text[]) to authenticated;

commit;


-- -----------------------------------------------------------------------------
-- Source: 202609250005_family_price_provenance.sql
-- -----------------------------------------------------------------------------

begin;

-- Keep the server-side entitlement tied to the configured Stripe price when
-- the Family feature is enabled. Existing rows remain readable and require
-- the normal plan fallback until they are reconciled or repurchased.
alter table public.story_entitlements
  add column if not exists stripe_price_id text;

commit;


-- -----------------------------------------------------------------------------
-- Source: 202609260001_user_family_context.sql
-- -----------------------------------------------------------------------------

begin;

-- One versioned, renderable Family/Timeline document per authenticated user
-- and legacy Memoir project. The project id is only a correlation key; RLS
-- keeps the document scoped to the Supabase user who owns it.
create table if not exists public.user_family_context (
  user_id uuid not null references auth.users(id) on delete cascade,
  project_id text not null check (char_length(project_id) between 1 and 128),
  document jsonb not null check (jsonb_typeof(document) = 'object'),
  revision bigint not null default 0 check (revision >= 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (user_id, project_id)
);

alter table public.user_family_context enable row level security;

drop policy if exists user_family_context_select_own on public.user_family_context;
create policy user_family_context_select_own
  on public.user_family_context for select
  to authenticated
  using (user_id = auth.uid());

drop policy if exists user_family_context_insert_own on public.user_family_context;
create policy user_family_context_insert_own
  on public.user_family_context for insert
  to authenticated
  with check (user_id = auth.uid());

drop policy if exists user_family_context_update_own on public.user_family_context;
create policy user_family_context_update_own
  on public.user_family_context for update
  to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

revoke all on table public.user_family_context from anon;
grant select, insert, update on table public.user_family_context to authenticated;
grant all on table public.user_family_context to service_role;

create or replace function public.upsert_user_family_context(
  p_project_id text,
  p_document jsonb,
  p_expected_revision bigint default null
)
returns jsonb
language plpgsql
security invoker
set search_path = public
as $$
declare
  current_row public.user_family_context%rowtype;
  next_revision bigint;
  next_document jsonb;
begin
  if auth.uid() is null then
    raise exception 'authenticated user required';
  end if;
  if p_project_id is null or char_length(p_project_id) < 1 or char_length(p_project_id) > 128 then
    raise exception 'invalid project id';
  end if;
  if p_document is null or jsonb_typeof(p_document) <> 'object' then
    raise exception 'family document must be a JSON object';
  end if;

  select * into current_row
    from public.user_family_context
   where user_id = auth.uid() and project_id = p_project_id
   for update;

  if found then
    if p_expected_revision is not null and current_row.revision <> p_expected_revision then
      raise exception 'family context revision conflict';
    end if;

    -- Ignore transport metadata when deciding whether a retry changed the
    -- canonical records. This makes a retried Codex turn idempotent.
    if (current_row.document - 'revision' - 'updated_at') = (p_document - 'revision' - 'updated_at') then
      return jsonb_build_object(
        'changed', false,
        'document', current_row.document,
        'revision', current_row.revision,
        'updated_at', current_row.updated_at
      );
    end if;

    next_revision := current_row.revision + 1;
    next_document := p_document || jsonb_build_object('revision', next_revision, 'updated_at', now());
    update public.user_family_context
       set document = next_document,
           revision = next_revision,
           updated_at = now()
     where user_id = auth.uid() and project_id = p_project_id;
  else
    if p_expected_revision is not null and p_expected_revision <> 0 then
      raise exception 'family context revision conflict';
    end if;
    next_revision := 1;
    next_document := p_document || jsonb_build_object('revision', next_revision, 'updated_at', now());
    insert into public.user_family_context(user_id, project_id, document, revision)
    values (auth.uid(), p_project_id, next_document, next_revision);
  end if;

  return jsonb_build_object(
    'changed', true,
    'document', next_document,
    'revision', next_revision,
    'updated_at', now()
  );
end;
$$;

revoke all on function public.upsert_user_family_context(text, jsonb, bigint) from public;
grant execute on function public.upsert_user_family_context(text, jsonb, bigint) to authenticated;
grant execute on function public.upsert_user_family_context(text, jsonb, bigint) to service_role;

commit;


-- -----------------------------------------------------------------------------
-- Source: 202609260002_user_place_journey.sql
-- -----------------------------------------------------------------------------

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


-- -----------------------------------------------------------------------------
-- Source: 202609280001_agent_workspace_ordering.sql
-- -----------------------------------------------------------------------------

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


-- -----------------------------------------------------------------------------
-- Source: 202609300001_guest_conversation_attachments.sql
-- -----------------------------------------------------------------------------

begin;

-- A short-lived capability is prepared under the guest session, then redeemed
-- under the permanent session. Store only its hash, never a Supabase token.
create table public.guest_conversation_transfer (
  token_hash text primary key,
  guest_user_id uuid not null references auth.users(id) on delete cascade,
  project_id text not null,
  messages jsonb not null,
  memories jsonb not null,
  expires_at timestamptz not null default (now() + interval '1 hour'),
  target_user_id uuid references auth.users(id) on delete cascade,
  conversation_id uuid
);
alter table public.guest_conversation_transfer enable row level security;
revoke all on public.guest_conversation_transfer from public, anon, authenticated;

create table public.user_conversation_attachment (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  project_id text not null,
  messages jsonb not null,
  created_at timestamptz not null default now()
);
alter table public.user_conversation_attachment enable row level security;
create policy conversation_attachment_owner on public.user_conversation_attachment
  for select to authenticated using (user_id = (select auth.uid()));
revoke all on public.user_conversation_attachment from public, anon, authenticated;
grant select on public.user_conversation_attachment to authenticated;

create function public.prepare_guest_conversation_transfer(
  p_token text, p_project_id text, p_messages jsonb
) returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  owner_id uuid := auth.uid();
  key_hash text;
  snapshot jsonb;
begin
  if owner_id is null or not exists (
    select 1 from auth.users where id = owner_id and is_anonymous is true
  ) then
    raise exception 'guest session required' using errcode = '42501';
  end if;
  if p_token is null or p_token !~ '^[a-f0-9]{64}$'
      or p_project_id is null or char_length(p_project_id) not between 1 and 128
      or p_messages is null or jsonb_typeof(p_messages) <> 'array'
      or jsonb_array_length(p_messages) > 1000
      or octet_length(p_messages::text) > 2000000 then
    raise exception 'invalid conversation transfer' using errcode = '22023';
  end if;
  if exists (select 1 from jsonb_array_elements(p_messages) m
    where jsonb_typeof(m) <> 'object' or coalesce(m->>'role', '') not in ('user', 'assistant')
      or jsonb_typeof(m->'text') is distinct from 'string') then
    raise exception 'invalid conversation messages' using errcode = '22023';
  end if;
  -- The browser also blocks merging while a reply is running. The server
  -- checks the durable lease before taking a snapshot.
  if exists (select 1 from public.user_agent_turn_lease
      where user_id = owner_id and expires_at > clock_timestamp()) then
    raise exception 'conversation reply in progress' using errcode = '55000';
  end if;
  select coalesce(jsonb_agg(jsonb_build_object(
    'kind', kind, 'content', content, 'created_at', created_at
  ) order by created_at, id), '[]'::jsonb) into snapshot
    from public.user_memory where user_id = owner_id;
  if jsonb_array_length(snapshot) > 1000 then
    raise exception 'conversation exceeds transfer limit' using errcode = '22023';
  end if;
  key_hash := encode(sha256(convert_to(p_token, 'UTF8')), 'hex');
  delete from public.guest_conversation_transfer
    where guest_user_id = owner_id and target_user_id is null and expires_at <= clock_timestamp();
  insert into public.guest_conversation_transfer(token_hash, guest_user_id, project_id, messages, memories)
    values (key_hash, owner_id, p_project_id, p_messages, snapshot)
    on conflict (token_hash) do update set
      project_id = excluded.project_id, messages = excluded.messages, memories = excluded.memories,
      expires_at = clock_timestamp() + interval '1 hour'
    where public.guest_conversation_transfer.guest_user_id = owner_id
      and public.guest_conversation_transfer.target_user_id is null;
  if not found then
    raise exception 'transfer already claimed' using errcode = '42501';
  end if;
  return jsonb_build_object('prepared', true);
end;
$$;

create function public.attach_guest_conversation(p_token text)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  owner_id uuid := auth.uid();
  held public.guest_conversation_transfer%rowtype;
  saved_id uuid;
begin
  if owner_id is null or not exists (
    select 1 from auth.users where id = owner_id and is_anonymous is false
  ) then
    raise exception 'permanent session required' using errcode = '42501';
  end if;
  if p_token is null or p_token !~ '^[a-f0-9]{64}$' then
    raise exception 'invalid transfer capability' using errcode = '22023';
  end if;
  select * into held from public.guest_conversation_transfer
    where token_hash = encode(sha256(convert_to(p_token, 'UTF8')), 'hex') for update;
  if not found then
    raise exception 'transfer unavailable' using errcode = '42501';
  end if;
  if held.target_user_id is not null then
    if held.target_user_id <> owner_id then
      raise exception 'transfer already claimed' using errcode = '42501';
    end if;
    return jsonb_build_object('conversation_id', held.conversation_id, 'attached', true);
  end if;
  if held.expires_at <= clock_timestamp() or held.guest_user_id = owner_id then
    raise exception 'transfer expired or invalid' using errcode = '42501';
  end if;
  insert into public.user_conversation_attachment(user_id, project_id, messages)
    values (owner_id, held.project_id, held.messages) returning id into saved_id;
  -- Append textual conversation memories. Existing profile, live Codex thread,
  -- entitlements and stored files are preserved. Guest files stay with the guest.
  insert into public.user_memory(user_id, kind, content, created_at)
    select owner_id, m.kind, m.content, m.created_at
    from jsonb_to_recordset(held.memories) as m(kind text, content text, created_at timestamptz);
  update public.guest_conversation_transfer
    set target_user_id = owner_id, conversation_id = saved_id,
        messages = '[]'::jsonb, memories = '[]'::jsonb
    where token_hash = held.token_hash;
  return jsonb_build_object('conversation_id', saved_id, 'attached', true);
end;
$$;

revoke all on function public.prepare_guest_conversation_transfer(text, text, jsonb) from public, anon;
revoke all on function public.attach_guest_conversation(text) from public, anon;
grant execute on function public.prepare_guest_conversation_transfer(text, text, jsonb) to authenticated;
grant execute on function public.attach_guest_conversation(text) to authenticated;
commit;


-- -----------------------------------------------------------------------------
-- Source: 202609300002_guest_workspace_merge.sql
-- -----------------------------------------------------------------------------

begin;

alter table public.guest_conversation_transfer add column workspace jsonb not null default '{}'::jsonb;
alter table public.guest_conversation_transfer add column memory_id_map jsonb not null default '{}'::jsonb;
alter table public.user_conversation_attachment add column workspace jsonb not null default '{}'::jsonb;

-- Fill missing scalar values; merge nested records and collections without
-- dropping either account's photos, places, or timeline records.
create function public.merge_memoir_context(a jsonb, b jsonb, guest_wins boolean default false)
returns jsonb language plpgsql immutable set search_path = '' as $$
declare
  result jsonb := a;
  item record;
  incoming jsonb;
  identity text;
  position integer;
begin
  if a is null or a in ('null'::jsonb, '""'::jsonb, '{}'::jsonb, '[]'::jsonb) then return b; end if;
  if b is null or b in ('null'::jsonb, '""'::jsonb, '{}'::jsonb, '[]'::jsonb) then return a; end if;
  if jsonb_typeof(a) = 'object' and jsonb_typeof(b) = 'object' then
    for item in select key, value from jsonb_each(b) loop
      result := jsonb_set(result, array[item.key], public.merge_memoir_context(result->item.key, item.value, guest_wins), true);
    end loop;
    return result;
  end if;
  if jsonb_typeof(a) = 'array' and jsonb_typeof(b) = 'array' then
    for incoming in select value from jsonb_array_elements(b) loop
      identity := case when incoming ? 'place' then
        'place:' || lower(coalesce((incoming->'hierarchy')::text, '') || ':' || (incoming->>'place'))
        else coalesce(incoming->>'asset_id', incoming->>'id', incoming->>'source_url', incoming->>'image_url') end;
      select (ordinality - 1)::integer into position from jsonb_array_elements(result) with ordinality e(value, ordinality)
        where value = incoming or (identity is not null and identity = case when value ? 'place' then
          'place:' || lower(coalesce((value->'hierarchy')::text, '') || ':' || (value->>'place'))
          else coalesce(value->>'asset_id', value->>'id', value->>'source_url', value->>'image_url') end)
        limit 1;
      if position is null then result := result || jsonb_build_array(incoming);
      else result := jsonb_set(result, array[position::text], public.merge_memoir_context(result->position, incoming, guest_wins)); end if;
    end loop;
    return result;
  end if;
  return case when guest_wins then b else a end;
end;
$$;

create table public.guest_merge_asset_access (
  user_id uuid not null references auth.users(id) on delete cascade,
  source_name text not null,
  primary key(user_id, source_name)
);
alter table public.guest_merge_asset_access enable row level security;
revoke all on public.guest_merge_asset_access from public, anon, authenticated;
grant select on public.guest_merge_asset_access to authenticated;
create policy merged_asset_access_owner on public.guest_merge_asset_access for select to authenticated
  using(user_id = (select auth.uid()));
-- Only files captured by an explicitly redeemed guest capability can be read.
-- Copying the bytes uses the Storage API; SQL never mutates Storage metadata.
create policy merged_guest_asset_read on storage.objects for select to authenticated
  using(bucket_id = 'memory-spark' and exists(select 1 from public.guest_merge_asset_access g
    where g.user_id = (select auth.uid()) and g.source_name = storage.objects.name));

create function public.import_memoir_path(path text, guest_id uuid, owner_id uuid, relative_agent boolean default false)
returns text language plpgsql immutable set search_path = '' as $$
declare tail text; root text;
begin
  if starts_with(path, guest_id::text || '/agent/') then
    tail := substr(path, length(guest_id::text || '/agent/') + 1);
    return owner_id::text || '/agent/' || public.import_memoir_path(tail, guest_id, owner_id, true);
  elsif starts_with(path, guest_id::text || '/attachment/') then
    return owner_id::text || '/attachment/imports/' || guest_id::text || '/' || substr(path, length(guest_id::text || '/attachment/') + 1);
  elsif relative_agent and split_part(path, '/', 1) in ('sessions', 'archived_sessions', 'memories') then
    root := split_part(path, '/', 1);
    return root || '/imports/' || guest_id::text || '/' || substr(path, length(root) + 2);
  end if;
  return path;
end;
$$;

create function public.rewrite_merged_context(p_value jsonb, guest_id uuid, owner_id uuid, id_map jsonb default '{}'::jsonb)
returns jsonb language plpgsql immutable set search_path = '' as $$
declare result jsonb; item record; text_value text;
begin
  if jsonb_typeof(p_value) = 'string' then
    text_value := p_value #>> '{}';
    return to_jsonb(coalesce(id_map->>text_value, public.import_memoir_path(text_value, guest_id, owner_id)));
  elsif jsonb_typeof(p_value) = 'object' then
    result := '{}'::jsonb;
    for item in select key, value as content from jsonb_each(p_value) loop
      result := result || jsonb_build_object(item.key, public.rewrite_merged_context(item.content, guest_id, owner_id, id_map));
    end loop;
    return result;
  elsif jsonb_typeof(p_value) = 'array' then
    select coalesce(jsonb_agg(public.rewrite_merged_context(content, guest_id, owner_id, id_map) order by position), '[]'::jsonb)
      into result from jsonb_array_elements(p_value) with ordinality e(content, position);
    return result;
  end if;
  return p_value;
end;
$$;

drop function public.prepare_guest_conversation_transfer(text, text, jsonb);
create function public.prepare_guest_conversation_transfer(
  p_token text, p_project_id text, p_messages jsonb,
  p_workspace_profile jsonb default '{}'::jsonb, p_ui_locale text default null
) returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  owner_id uuid := auth.uid(); key_hash text; snapshot jsonb; context jsonb;
  source_profile jsonb; browser_profile jsonb; locale text;
begin
  if owner_id is null or not exists(select 1 from auth.users where id = owner_id and is_anonymous is true) then
    raise exception 'guest session required' using errcode = '42501';
  end if;
  if p_token is null or p_token !~ '^[a-f0-9]{64}$' or p_project_id is null
    or char_length(p_project_id) not between 1 and 128 or p_messages is null
    or jsonb_typeof(p_messages) <> 'array' or jsonb_array_length(p_messages) > 1000
    or octet_length(p_messages::text) > 2000000 or jsonb_typeof(p_workspace_profile) <> 'object'
    or octet_length(p_workspace_profile::text) > 2000000 then
    raise exception 'invalid conversation transfer' using errcode = '22023';
  end if;
  if exists(select 1 from jsonb_array_elements(p_messages) m where jsonb_typeof(m) <> 'object'
      or coalesce(m->>'role', '') not in ('user', 'assistant') or jsonb_typeof(m->'text') is distinct from 'string') then
    raise exception 'invalid conversation messages' using errcode = '22023';
  end if;
  if exists(select 1 from public.user_agent_turn_lease where user_id = owner_id and expires_at > clock_timestamp()) then
    raise exception 'conversation reply in progress' using errcode = '55000';
  end if;
  select coalesce(jsonb_agg(to_jsonb(m) - 'user_id' order by created_at, id), '[]'::jsonb)
    into snapshot from public.user_memory m where user_id = owner_id;
  if jsonb_array_length(snapshot) > 1000 then
    raise exception 'conversation exceeds transfer limit' using errcode = '22023';
  end if;
  select profile into source_profile from public.user_profile where user_id = owner_id;
  -- The browser keeps some generated place/photo data in its project adapter.
  -- Accept only product context, never client-supplied auth or payment claims.
  select coalesce(jsonb_object_agg(key, value), '{}'::jsonb) into browser_profile
    from jsonb_each(p_workspace_profile) where key in ('name', 'preferred_language', 'birth_year',
      'birth_date_expression', 'birth_place', 'childhood_place', 'story_focus',
      'dialect_preference', 'memory_places', 'avatar_style');
  source_profile := public.merge_memoir_context(coalesce(source_profile, '{}'::jsonb), browser_profile, true);
  if exists(select 1 from public.user_place_journey where user_id = owner_id) then
    source_profile := jsonb_set(source_profile, '{memory_places}', public.merge_memoir_context(
      coalesce(source_profile->'memory_places', '[]'::jsonb),
      (select jsonb_build_array(to_jsonb(j) - 'user_id') from public.user_place_journey j where user_id = owner_id), false));
  end if;
  select coalesce(p_ui_locale, raw_user_meta_data->>'ui_locale') into locale from auth.users where id = owner_id;
  if locale not in ('en-AU', 'zh-CN') then locale := null; end if;
  context := jsonb_build_object('profile', source_profile, 'ui_locale', locale,
    'place_journey', (select to_jsonb(j) - 'user_id' from public.user_place_journey j where user_id = owner_id),
    'family_context', (select coalesce(jsonb_agg(to_jsonb(f) - 'user_id'), '[]'::jsonb) from public.user_family_context f where user_id = owner_id),
    'agent_session', (select to_jsonb(s) - 'user_id' from public.user_agent_session s where user_id = owner_id),
    'storage_objects', (select coalesce(jsonb_agg(jsonb_build_object('name', name, 'metadata', metadata)), '[]'::jsonb)
      from storage.objects where bucket_id = 'memory-spark' and split_part(name, '/', 1) = owner_id::text));
  key_hash := encode(sha256(convert_to(p_token, 'UTF8')), 'hex');
  delete from public.guest_conversation_transfer where guest_user_id = owner_id and target_user_id is null and expires_at <= clock_timestamp();
  insert into public.guest_conversation_transfer(token_hash, guest_user_id, project_id, messages, memories, workspace)
    values(key_hash, owner_id, p_project_id, p_messages, snapshot, context)
    on conflict(token_hash) do update set project_id = excluded.project_id, messages = excluded.messages,
      memories = excluded.memories, workspace = excluded.workspace, expires_at = clock_timestamp() + interval '1 hour'
    where public.guest_conversation_transfer.guest_user_id = owner_id and public.guest_conversation_transfer.target_user_id is null;
  if not found then raise exception 'transfer already claimed' using errcode = '42501'; end if;
  return jsonb_build_object('prepared', true);
end;
$$;

drop function public.attach_guest_conversation(text);
create function public.attach_guest_conversation(p_token text, p_guest_wins boolean default false)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  owner_id uuid := auth.uid(); held public.guest_conversation_transfer%rowtype;
  saved_id uuid; existing_profile jsonb; merged_profile jsonb; locale text;
  m jsonb; f jsonb; file jsonb; new_memory_id uuid; paths text[];
  id_map jsonb := '{}'::jsonb; watermark bigint; context jsonb; response jsonb;
begin
  if owner_id is null or not exists(select 1 from auth.users where id = owner_id and is_anonymous is false) then
    raise exception 'permanent session required' using errcode = '42501';
  end if;
  if p_token is null or p_token !~ '^[a-f0-9]{64}$' then raise exception 'invalid transfer capability' using errcode = '22023'; end if;
  select * into held from public.guest_conversation_transfer
    where token_hash = encode(sha256(convert_to(p_token, 'UTF8')), 'hex') for update;
  if not found then raise exception 'transfer unavailable' using errcode = '42501'; end if;
  if held.target_user_id is not null and held.target_user_id <> owner_id then
    raise exception 'transfer already claimed' using errcode = '42501';
  end if;
  if held.target_user_id is null then
    if held.expires_at <= clock_timestamp() or held.guest_user_id = owner_id then
      raise exception 'transfer expired or invalid' using errcode = '42501';
    end if;
    -- Fence existing workspace enrichment as well as new agent turns.
    insert into public.user_agent_turn_lease(user_id, lease_token, expires_at)
      values(owner_id, gen_random_uuid(), clock_timestamp()) on conflict(user_id) do nothing;
    perform 1 from public.user_agent_turn_lease where user_id = owner_id for update;
    if exists(select 1 from public.user_agent_turn_lease where user_id = owner_id and expires_at > clock_timestamp()) then
      raise exception 'account reply in progress' using errcode = '55000';
    end if;
    select profile into existing_profile from public.user_profile where user_id = owner_id for update;
    existing_profile := coalesce(existing_profile, '{}'::jsonb);
    if exists(select 1 from public.user_place_journey where user_id = owner_id) then
      existing_profile := jsonb_set(existing_profile, '{memory_places}', public.merge_memoir_context(
        coalesce(existing_profile->'memory_places', '[]'::jsonb),
        (select jsonb_build_array(to_jsonb(j) - 'user_id') from public.user_place_journey j where user_id = owner_id), false));
    end if;
    for m in select value from jsonb_array_elements(held.memories) loop
      if m ? 'id' then id_map := id_map || jsonb_build_object(m->>'id', md5(owner_id::text || ':' || (m->>'id'))::uuid); end if;
    end loop;
    merged_profile := public.merge_memoir_context(existing_profile,
      public.rewrite_merged_context(held.workspace->'profile', held.guest_user_id, owner_id, id_map), p_guest_wins);
    merged_profile := coalesce(merged_profile, existing_profile);
    select coalesce(turn_sequence, 0) + 1 into watermark from public.user_agent_session where user_id = owner_id;
    watermark := coalesce(watermark, 1) + jsonb_array_length(held.memories);
    insert into public.user_profile(user_id, profile, agent_source_sequences)
      values(owner_id, merged_profile, (select coalesce(jsonb_object_agg(key, to_jsonb(watermark)), '{}'::jsonb) from jsonb_each(merged_profile)))
      on conflict(user_id) do update set profile = excluded.profile, agent_source_sequences = excluded.agent_source_sequences;
    update public.user_agent_session set turn_sequence = watermark where user_id = owner_id;
    select raw_user_meta_data->>'ui_locale' into locale from auth.users where id = owner_id;
    if p_guest_wins or locale is null then locale := coalesce(held.workspace->>'ui_locale', locale); end if;
    if locale in ('en-AU', 'zh-CN') then
      update auth.users set raw_user_meta_data = coalesce(raw_user_meta_data, '{}'::jsonb) || jsonb_build_object('ui_locale', locale) where id = owner_id;
    end if;
    for m in select value from jsonb_array_elements(held.memories) loop
      new_memory_id := case when m ? 'id' then md5(owner_id::text || ':' || (m->>'id'))::uuid else gen_random_uuid() end;
      if m ? 'id' then id_map := id_map || jsonb_build_object(m->>'id', new_memory_id); end if;
      select coalesce(array_agg(public.import_memoir_path(value, held.guest_user_id, owner_id, true)), '{}'::text[]) into paths
        from jsonb_array_elements_text(coalesce(m->'source_paths', '[]'::jsonb));
      insert into public.user_memory(id, user_id, kind, content, created_at, source_paths, source_sequence)
        values(new_memory_id, owner_id, m->>'kind', m->>'content', (m->>'created_at')::timestamptz, paths, watermark)
        on conflict(id) do nothing;
    end loop;
    for f in select value from jsonb_array_elements(coalesce(held.workspace->'family_context', '[]'::jsonb)) loop
      insert into public.user_family_context(user_id, project_id, document, revision)
        values(owner_id, f->>'project_id', public.rewrite_merged_context(f->'document', held.guest_user_id, owner_id, id_map)
          || jsonb_build_object('revision', coalesce((f->>'revision')::bigint, 0), 'source_sequence', watermark), coalesce((f->>'revision')::bigint, 0))
        on conflict(user_id, project_id) do update set
          document = public.merge_memoir_context(public.user_family_context.document, excluded.document, p_guest_wins)
            || jsonb_build_object('revision', public.user_family_context.revision + 1, 'source_sequence', watermark, 'updated_at', clock_timestamp()),
          revision = public.user_family_context.revision + 1;
    end loop;
    if jsonb_typeof(held.workspace->'place_journey') = 'object' then
      f := held.workspace->'place_journey';
      insert into public.user_place_journey(user_id, schema_version, status, revision, source_sequence, place, hierarchy,
        granularity, latitude, longitude, duration_ms)
      values(owner_id, 1, 'active', 1, watermark, f->>'place', f->'hierarchy', f->>'granularity',
        (f->>'latitude')::double precision, (f->>'longitude')::double precision, (f->>'duration_ms')::integer)
      on conflict(user_id) do nothing;
    end if;
    for file in select value from jsonb_array_elements(coalesce(held.workspace->'storage_objects', '[]'::jsonb)) loop
      insert into public.guest_merge_asset_access(user_id, source_name) values(owner_id, file->>'name') on conflict do nothing;
    end loop;
    context := held.workspace || jsonb_build_object('existing_profile', existing_profile, 'merged_profile', merged_profile,
      'memory_id_map', id_map, 'guest_user_id', held.guest_user_id, 'memories', held.memories);
    insert into public.user_conversation_attachment(user_id, project_id, messages, workspace)
      values(owner_id, held.project_id, held.messages, context) returning id into saved_id;
    update public.guest_conversation_transfer set target_user_id = owner_id, conversation_id = saved_id,
      memory_id_map = id_map, messages = '[]'::jsonb, memories = '[]'::jsonb
      where token_hash = held.token_hash;
  else saved_id := held.conversation_id; id_map := held.memory_id_map;
  end if;
  select profile into merged_profile from public.user_profile where user_id = owner_id;
  select raw_user_meta_data->>'ui_locale' into locale from auth.users where id = owner_id;
  return jsonb_build_object('conversation_id', saved_id, 'attached', true, 'guest_user_id', held.guest_user_id,
    'project_id', held.project_id, 'memory_id_map', id_map, 'profile', merged_profile, 'ui_locale', locale,
    'storage_objects', coalesce(held.workspace->'storage_objects', '[]'::jsonb));
end;
$$;

revoke all on function public.merge_memoir_context(jsonb, jsonb, boolean) from public, anon, authenticated;
revoke all on function public.import_memoir_path(text, uuid, uuid, boolean) from public, anon, authenticated;
revoke all on function public.rewrite_merged_context(jsonb, uuid, uuid, jsonb) from public, anon, authenticated;
revoke all on function public.prepare_guest_conversation_transfer(text, text, jsonb, jsonb, text) from public, anon;
revoke all on function public.attach_guest_conversation(text, boolean) from public, anon;
grant execute on function public.prepare_guest_conversation_transfer(text, text, jsonb, jsonb, text) to authenticated;
grant execute on function public.attach_guest_conversation(text, boolean) to authenticated;
commit;


-- -----------------------------------------------------------------------------
-- Source: 202609300003_recall_usage.sql
-- -----------------------------------------------------------------------------

begin;

-- Usage survives refreshes, new projects, and deletion of conversation records.
-- Clients can read their usage but cannot reset or grant it through a profile.
create table public.user_recall_usage (
  user_id uuid primary key references auth.users(id) on delete cascade,
  rounds_completed bigint not null default 0 check (rounds_completed >= 0)
);
alter table public.user_recall_usage enable row level security;
revoke all on public.user_recall_usage from public, anon, authenticated;
grant select on public.user_recall_usage to authenticated;
create policy recall_usage_owner on public.user_recall_usage for select to authenticated
  using (user_id = (select auth.uid()));

insert into public.user_recall_usage(user_id, rounds_completed)
  select user_id, count(*) from public.user_memory where kind = 'agent' group by user_id;

-- The conversation commit and charge share one transaction. Failed replies
-- consume nothing; a crash after saving cannot lose the charge.
create function public.count_recall_reply() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  if new.kind = 'agent' then
    insert into public.user_recall_usage(user_id, rounds_completed) values(new.user_id, 1)
      on conflict(user_id) do update set rounds_completed = public.user_recall_usage.rounds_completed + 1;
  end if;
  return new;
end;
$$;
revoke all on function public.count_recall_reply() from public, anon, authenticated;
create trigger count_recall_reply after insert on public.user_memory
  for each row execute function public.count_recall_reply();

-- Imported replies are counted above. Preserve any additional consumed guest
-- rounds whose records were deleted, exactly once on redemption of a transfer.
create function public.transfer_recall_usage() returns trigger
language plpgsql security definer set search_path = '' as $$
declare guest_usage bigint; imported bigint;
begin
  if old.target_user_id is null and new.target_user_id is not null then
    select rounds_completed into guest_usage from public.user_recall_usage where user_id = old.guest_user_id;
    select count(*) into imported from jsonb_array_elements(old.memories) m where m->>'kind' = 'agent';
    insert into public.user_recall_usage(user_id, rounds_completed)
      values(new.target_user_id, greatest(0, coalesce(guest_usage, 0) - imported))
      on conflict(user_id) do update set rounds_completed = public.user_recall_usage.rounds_completed + excluded.rounds_completed;
  end if;
  return new;
end;
$$;
revoke all on function public.transfer_recall_usage() from public, anon, authenticated;
create trigger transfer_recall_usage after update of target_user_id on public.guest_conversation_transfer
  for each row execute function public.transfer_recall_usage();

commit;
