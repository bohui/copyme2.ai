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
