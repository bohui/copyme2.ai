-- Supabase Storage defines owner_id, which shadowed the PL/pgSQL variable.
-- Use a distinct variable name without changing ownership or grants.
begin;

create or replace function public.prepare_guest_conversation_transfer(
  p_token text, p_project_id text, p_messages jsonb,
  p_workspace_profile jsonb default '{}'::jsonb, p_ui_locale text default null
) returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  v_authenticated_user_id uuid := auth.uid(); key_hash text; snapshot jsonb; context jsonb;
  source_profile jsonb; browser_profile jsonb; locale text;
begin
  if v_authenticated_user_id is null or not exists(select 1 from auth.users where id = v_authenticated_user_id and is_anonymous is true) then
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
  if exists(select 1 from public.user_agent_turn_lease where user_id = v_authenticated_user_id and expires_at > clock_timestamp()) then
    raise exception 'conversation reply in progress' using errcode = '55000';
  end if;
  select coalesce(jsonb_agg(to_jsonb(m) - 'user_id' order by created_at, id), '[]'::jsonb)
    into snapshot from public.user_memory m where user_id = v_authenticated_user_id;
  if jsonb_array_length(snapshot) > 1000 then
    raise exception 'conversation exceeds transfer limit' using errcode = '22023';
  end if;
  select profile into source_profile from public.user_profile where user_id = v_authenticated_user_id;
  -- The browser keeps some generated place/photo data in its project adapter.
  -- Accept only product context, never client-supplied auth or payment claims.
  select coalesce(jsonb_object_agg(key, value), '{}'::jsonb) into browser_profile
    from jsonb_each(p_workspace_profile) where key in ('name', 'preferred_language', 'birth_year',
      'birth_date_expression', 'birth_place', 'childhood_place', 'story_focus',
      'dialect_preference', 'memory_places', 'avatar_style');
  source_profile := public.merge_memoir_context(coalesce(source_profile, '{}'::jsonb), browser_profile, true);
  if exists(select 1 from public.user_place_journey where user_id = v_authenticated_user_id) then
    source_profile := jsonb_set(source_profile, '{memory_places}', public.merge_memoir_context(
      coalesce(source_profile->'memory_places', '[]'::jsonb),
      (select jsonb_build_array(to_jsonb(j) - 'user_id') from public.user_place_journey j where user_id = v_authenticated_user_id), false));
  end if;
  select coalesce(p_ui_locale, raw_user_meta_data->>'ui_locale') into locale from auth.users where id = v_authenticated_user_id;
  if locale not in ('en-AU', 'zh-CN') then locale := null; end if;
  context := jsonb_build_object('profile', source_profile, 'ui_locale', locale,
    'place_journey', (select to_jsonb(j) - 'user_id' from public.user_place_journey j where user_id = v_authenticated_user_id),
    'family_context', (select coalesce(jsonb_agg(to_jsonb(f) - 'user_id'), '[]'::jsonb) from public.user_family_context f where user_id = v_authenticated_user_id),
    'agent_session', (select to_jsonb(s) - 'user_id' from public.user_agent_session s where user_id = v_authenticated_user_id),
    'storage_objects', (select coalesce(jsonb_agg(jsonb_build_object('name', name, 'metadata', metadata)), '[]'::jsonb)
      from storage.objects where bucket_id = 'memory-spark'
        and split_part(name, '/', 1) = v_authenticated_user_id::text));
  key_hash := encode(sha256(convert_to(p_token, 'UTF8')), 'hex');
  delete from public.guest_conversation_transfer where guest_user_id = v_authenticated_user_id and target_user_id is null and expires_at <= clock_timestamp();
  insert into public.guest_conversation_transfer(token_hash, guest_user_id, project_id, messages, memories, workspace)
    values(key_hash, v_authenticated_user_id, p_project_id, p_messages, snapshot, context)
    on conflict(token_hash) do update set project_id = excluded.project_id, messages = excluded.messages,
      memories = excluded.memories, workspace = excluded.workspace, expires_at = clock_timestamp() + interval '1 hour'
    where public.guest_conversation_transfer.guest_user_id = v_authenticated_user_id and public.guest_conversation_transfer.target_user_id is null;
  if not found then raise exception 'transfer already claimed' using errcode = '42501'; end if;
  return jsonb_build_object('prepared', true);
end;
$$;

commit;
