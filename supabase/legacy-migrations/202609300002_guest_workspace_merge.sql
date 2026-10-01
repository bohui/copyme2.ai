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
