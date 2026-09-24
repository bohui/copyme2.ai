begin;

-- Memory Spark's server-side domain state lives in the same Supabase Postgres
-- database as the authenticated Codex tables. The API connects with
-- SUPABASE_DB_URL and remains the authorization boundary for these records.
create table if not exists public.memory_spark_state (
  id smallint primary key check (id = 1),
  schema_version integer not null,
  revision bigint not null,
  snapshot jsonb not null,
  updated_at timestamptz not null default now()
);

create table if not exists public.memory_spark_outbox (
  event_id text primary key,
  job_id text not null,
  project_id text not null,
  event_type text not null,
  status text not null,
  attempts integer not null default 0,
  lease_owner text,
  lease_until timestamptz,
  occurred_at timestamptz not null,
  acknowledged_at timestamptz,
  payload jsonb not null,
  event jsonb not null
);

create index if not exists memory_spark_outbox_pending_idx
  on public.memory_spark_outbox (status, occurred_at)
  where status in ('PENDING', 'LEASED');

create index if not exists memory_spark_outbox_job_idx
  on public.memory_spark_outbox (job_id, occurred_at);

commit;
