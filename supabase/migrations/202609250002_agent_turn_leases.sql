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
