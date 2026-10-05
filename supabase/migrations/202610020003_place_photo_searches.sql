-- Shared public research metadata, never memoir text or user/project identities.
begin;
create table public.place_photo_searches (
  search_key text primary key check (search_key ~ '^[a-f0-9]{64}$'),
  place text not null,
  period text not null,
  result jsonb not null check (jsonb_typeof(result->'items') = 'array'),
  updated_at timestamptz not null default now()
);
alter table public.place_photo_searches enable row level security;
-- Only the trusted photo worker can populate or read the global cache.
-- End users retrieve paginated results through their authorized project route.
revoke all on public.place_photo_searches from anon, authenticated;
grant select, insert, update, delete on public.place_photo_searches to service_role;
commit;
