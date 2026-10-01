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
