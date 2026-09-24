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
  values ('memory-spark', 'memory-spark', false, 52428800);
create policy memory_spark_owner on storage.objects for all to authenticated
  using (bucket_id = 'memory-spark' and (storage.foldername(name))[1] = (select auth.uid())::text)
  with check (bucket_id = 'memory-spark' and (storage.foldername(name))[1] = (select auth.uid())::text
    and (storage.foldername(name))[2] in ('attachment', 'agent'));

commit;
