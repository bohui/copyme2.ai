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
