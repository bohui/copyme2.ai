-- Completed conversation rounds and a transactional private-draft outbox.
-- No browser tokens, broad executor grants or composition permissions live here.
begin;

alter table public.user_memory drop constraint user_memory_kind_check;
alter table public.user_memory add constraint user_memory_kind_check check(kind in ('agent','memoir','agent_greeting'));

alter table public.user_memory add column if not exists project_id text;
alter table public.user_memory add column if not exists client_turn_id uuid;
alter table public.user_memory add column if not exists life_stage text
  check (life_stage in ('baby','toddler','childhood','adolescence','young_adulthood','midlife','later_life'));
create unique index user_memory_client_turn on public.user_memory(user_id,client_turn_id)
  where client_turn_id is not null;

create table public.user_completed_round (
  user_id uuid not null references auth.users(id) on delete cascade,
  project_id text not null,
  memory_id uuid references public.user_memory(id) on delete set null,
  turn_id uuid not null,
  ordinal bigint not null,
  created_at timestamptz not null default clock_timestamp(),
  primary key(user_id,project_id,turn_id),
  unique(user_id,project_id,ordinal), unique(memory_id)
);
create table public.user_private_draft_outbox (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  project_id text not null,
  memory_id uuid,
  change_kind text not null check(change_kind in ('round','edit','delete','assignment')),
  delivered boolean not null default false,
  created_at timestamptz not null default clock_timestamp()
);
alter table public.user_completed_round enable row level security;
alter table public.user_private_draft_outbox enable row level security;
revoke all on public.user_completed_round,public.user_private_draft_outbox from public,anon,authenticated;
grant select on public.user_completed_round,public.user_private_draft_outbox to authenticated;
create policy completed_round_owner on public.user_completed_round for select to authenticated using(user_id=auth.uid());
create policy draft_outbox_owner on public.user_private_draft_outbox for select to authenticated using(user_id=auth.uid());

create function public.record_private_draft_change() returns trigger
language plpgsql security definer set search_path='' as $$
declare m public.user_memory%rowtype; next_round bigint; inserted integer;
begin
  if TG_OP='DELETE' then m:=old; else m:=new; end if;
  if m.kind <> 'agent' or m.project_id is null then return null; end if;
  if TG_OP='INSERT' or (TG_OP='UPDATE' and old.project_id is null) then
    -- A durable assistant-only greeting or incomplete exchange is not a round.
    if m.content !~ '^Storyteller: [[:space:][:print:]]+' or
       pg_catalog.strpos(m.content,E'\nMemory Spark: ')=0 or
       pg_catalog.btrim(pg_catalog.regexp_replace(pg_catalog.split_part(m.content,E'\nMemory Spark: ',1),'^Storyteller: ',''))='' or
       pg_catalog.btrim(pg_catalog.split_part(m.content,E'\nMemory Spark: ',2))='' then return null; end if;
    perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(m.user_id::text||':'||m.project_id,0));
    select coalesce(max(ordinal),0)+1 into next_round from public.user_completed_round
      where user_id=m.user_id and project_id=m.project_id;
    insert into public.user_completed_round(user_id,project_id,memory_id,turn_id,ordinal)
      values(m.user_id,m.project_id,m.id,coalesce(m.client_turn_id,m.id),next_round)
      on conflict do nothing;
    get diagnostics inserted=ROW_COUNT;
    if inserted=0 then return null; end if;
    insert into public.user_private_draft_outbox(user_id,project_id,memory_id,change_kind)
      values(m.user_id,m.project_id,m.id,'round');
  elsif TG_OP='DELETE' then
    insert into public.user_private_draft_outbox(user_id,project_id,memory_id,change_kind)
      values(m.user_id,m.project_id,m.id,'delete');
  elsif old.content is distinct from new.content or old.life_stage is distinct from new.life_stage or
        old.project_id is distinct from new.project_id then
    insert into public.user_private_draft_outbox(user_id,project_id,memory_id,change_kind)
      values(m.user_id,m.project_id,m.id,case when old.content is distinct from new.content then 'edit' else 'assignment' end);
  end if;
  return null;
end $$;
create trigger private_draft_round_event after insert or update or delete on public.user_memory
  for each row execute function public.record_private_draft_change();

alter function public.commit_user_agent_turn(uuid,text,text,text[],bigint)
  rename to commit_user_agent_turn_legacy;
revoke all on function public.commit_user_agent_turn_legacy(uuid,text,text,text[],bigint) from public,anon,authenticated;

create function public.commit_user_agent_turn(
  p_lease_token uuid,p_thread_id text,p_content text,p_source_paths text[] default '{}',
  p_source_sequence bigint default null,p_project_id text default null,
  p_client_turn_id uuid default null,p_user_response boolean default true
) returns jsonb language plpgsql security definer set search_path='' as $$
declare owner_id uuid:=auth.uid(); saved public.user_memory%rowtype; result jsonb;
begin
  if owner_id is null then raise exception 'authenticated user required' using errcode='42501'; end if;
  if p_project_id is not null and p_project_id !~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$' then
    raise exception 'invalid project' using errcode='22023'; end if;
  -- Retries return the original commit without advancing either counter.
  if p_client_turn_id is not null then
    select * into saved from public.user_memory where user_id=owner_id and client_turn_id=p_client_turn_id
      and project_id is not distinct from p_project_id;
    if found then return pg_catalog.jsonb_build_array(pg_catalog.to_jsonb(saved)); end if;
  end if;
  result:=public.commit_user_agent_turn_legacy(p_lease_token,p_thread_id,p_content,p_source_paths,p_source_sequence);
  update public.user_memory set project_id=p_project_id,client_turn_id=p_client_turn_id,
      kind=case when p_user_response then 'agent' else 'agent_greeting' end
    where id=(result->0->>'id')::uuid and user_id=owner_id returning * into saved;
  if not p_user_response then
    update public.user_recall_usage set rounds_completed=greatest(rounds_completed-1,0) where user_id=owner_id;
  end if;
  return pg_catalog.jsonb_build_array(pg_catalog.to_jsonb(saved));
end $$;
revoke all on function public.commit_user_agent_turn(uuid,text,text,text[],bigint,text,uuid,boolean) from public,anon;
grant execute on function public.commit_user_agent_turn(uuid,text,text,text[],bigint,text,uuid,boolean) to authenticated;

-- Only the trusted API broker can drain events. A job-specific receipt selects
-- its owner/project; neither callers nor model workers can choose an owner.
create function public.private_draft_event_snapshot(p_event_id uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare event public.user_private_draft_outbox%rowtype; result jsonb;
begin
  select * into event from public.user_private_draft_outbox where id=p_event_id;
  if not found then return null; end if;
  if (select count(*) from public.user_memory where user_id=event.user_id and project_id=event.project_id and kind='agent')>1000 then
    raise exception 'private draft collection exceeds bounds' using errcode='22023'; end if;
  select pg_catalog.jsonb_build_object('event_id',event.id,'user_id',event.user_id,'project_id',event.project_id,
      'rounds',coalesce((select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(r) order by ordinal)
        from public.user_completed_round r where user_id=event.user_id and project_id=event.project_id),'[]'::jsonb),
      'memories',coalesce((select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(m) order by created_at,id)
        from public.user_memory m where user_id=event.user_id and project_id=event.project_id and kind='agent'),'[]'::jsonb),
      'completed',coalesce((select rounds_completed from public.user_recall_usage where user_id=event.user_id),0),
      'locale',coalesce((select profile->>'preferred_language' from public.user_profile where user_id=event.user_id),'en-AU'))
      into result;
  return result;
end $$;
revoke all on function public.private_draft_event_snapshot(uuid) from public,anon,authenticated;
grant execute on function public.private_draft_event_snapshot(uuid) to service_role;
grant select on public.user_private_draft_outbox to service_role;
grant update(delivered) on public.user_private_draft_outbox to service_role;

-- Preserve project/turn/stage identity after the existing capability-checked
-- guest transfer. Its immutable attachment snapshot is the import authority.
alter function public.attach_guest_conversation(text,boolean) rename to attach_guest_conversation_legacy;
revoke all on function public.attach_guest_conversation_legacy(text,boolean) from public,anon,authenticated;
create function public.attach_guest_conversation(p_token text,p_guest_wins boolean default false)
returns jsonb language plpgsql security definer set search_path='' as $$
declare result jsonb; attachment public.user_conversation_attachment%rowtype; original jsonb;
begin
  result:=public.attach_guest_conversation_legacy(p_token,p_guest_wins);
  select * into attachment from public.user_conversation_attachment
    where id=(result->>'conversation_id')::uuid and user_id=auth.uid();
  for original in select value from pg_catalog.jsonb_array_elements(coalesce(attachment.workspace->'memories','[]'::jsonb)) loop
    update public.user_memory set project_id=coalesce(original->>'project_id',attachment.project_id),
      client_turn_id=coalesce((original->>'client_turn_id')::uuid,(original->>'id')::uuid),
      life_stage=original->>'life_stage'
      where user_id=auth.uid() and id=(result->'memory_id_map'->>(original->>'id'))::uuid
        and project_id is null and kind='agent';
  end loop;
  return result;
end $$;
revoke all on function public.attach_guest_conversation(text,boolean) from public,anon;
grant execute on function public.attach_guest_conversation(text,boolean) to authenticated;

commit;
