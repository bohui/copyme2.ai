-- Issue 6: authoritative project/skill ownership and coalesced catch-up work.
-- Only opaque lane IDs/tokens and safe cursors enter Temporal history.
begin;

create table if not exists public.user_memoir_lane (
  id uuid not null default gen_random_uuid(), user_id uuid not null, project_id text not null,
  skill text not null check(skill in ('timeline','composer')),
  pending boolean not null default true, target_source bigint not null default 0,
  target_event bigint not null default 0, target_milestone bigint not null default 0,
  successful_source bigint not null default 0, successful_event bigint not null default 0,
  successful_round bigint not null default 0, token uuid, lease_until timestamptz, run_deadline timestamptz,
  active_manifest jsonb not null default '[]', active_through bigint, active_event bigint, active_round bigint,
  active_policy bigint, active_events jsonb not null default '[]',
  active_milestone bigint, active_locale text,
  active_manuscript_revision bigint not null default 0,
  attempts integer not null default 0, available_at timestamptz not null default clock_timestamp(),
  error text, locale text not null default 'en-AU',
  primary key(id), unique(user_id,project_id,skill),
  foreign key(user_id,project_id) references public.user_memoir_project on delete cascade
);
alter table public.user_memoir_lane enable row level security;
revoke all on public.user_memoir_lane from public,anon,authenticated;
grant select on public.user_memoir_lane to authenticated;
drop policy if exists memoir_lane_owner on public.user_memoir_lane;
create policy memoir_lane_owner on public.user_memoir_lane for select to authenticated using(user_id=auth.uid());

create or replace function public.memoir_lane_progress(p_lane public.user_memoir_lane) returns jsonb
language sql stable set search_path='' as $$
  select pg_catalog.jsonb_build_object('state',case
    when p_lane.token is not null and p_lane.lease_until>clock_timestamp() and p_lane.run_deadline>clock_timestamp() then 'running'
    when p_lane.attempts>=3 then 'retry_required'
    when p_lane.pending or p_lane.token is not null then 'pending' else 'finished' end,
    'pending',coalesce((p_lane.pending or p_lane.token is not null) and p_lane.attempts<3,false),
    'successful_source',coalesce(p_lane.successful_source,0),'successful_event',coalesce(p_lane.successful_event,0),
    'covered_round',coalesce(p_lane.successful_round,0),'target_milestone',coalesce(p_lane.target_milestone,0),'error',p_lane.error)
$$;
revoke all on function public.memoir_lane_progress(public.user_memoir_lane) from public,anon,authenticated;

create or replace function public.read_memoir_lane_state(p_lane_id uuid) returns jsonb
language sql security definer set search_path='' as $$
  select public.memoir_lane_progress(l) from public.user_memoir_lane l where id=p_lane_id
$$;
revoke all on function public.read_memoir_lane_state(uuid) from public,anon,authenticated;
grant execute on function public.read_memoir_lane_state(uuid) to service_role;

create table if not exists public.user_memoir_manuscript (
  user_id uuid not null, project_id text not null, locale text not null,
  revision bigint not null default 0, covered_round bigint not null default 0,
  source_sequence bigint not null default 0, event_sequence bigint not null default 0,
  completed_milestone bigint not null default 0, bundle jsonb, proposal jsonb,
  human_locked boolean not null default false, eligible boolean not null default true, reuse jsonb,
  primary key(user_id,project_id,locale),
  foreign key(user_id,project_id) references public.user_memoir_project on delete cascade
);
create table if not exists public.user_memoir_section_revision (
  user_id uuid not null, project_id text not null, locale text not null,
  section_id text not null, revision bigint not null, fingerprint text not null,
  data jsonb not null, event_manifest jsonb not null,
  primary key(user_id,project_id,locale,section_id,revision),
  foreign key(user_id,project_id) references public.user_memoir_project on delete cascade
);
alter table public.user_memoir_manuscript enable row level security;
alter table public.user_memoir_section_revision enable row level security;
revoke all on public.user_memoir_manuscript,public.user_memoir_section_revision from public,anon,authenticated;
grant select on public.user_memoir_manuscript,public.user_memoir_section_revision to authenticated;
drop policy if exists memoir_manuscript_owner on public.user_memoir_manuscript;
create policy memoir_manuscript_owner on public.user_memoir_manuscript for select to authenticated using(user_id=auth.uid() and eligible);
drop policy if exists memoir_section_owner on public.user_memoir_section_revision;
create policy memoir_section_owner on public.user_memoir_section_revision for select to authenticated using(user_id=auth.uid() and
  exists(select 1 from public.user_memoir_manuscript m where m.user_id=user_memoir_section_revision.user_id
    and m.project_id=user_memoir_section_revision.project_id and m.locale=user_memoir_section_revision.locale and m.eligible));

create table if not exists public.user_memoir_milestone (
  user_id uuid not null, project_id text not null, locale text not null,
  milestone bigint not null check(milestone>0), state text not null default 'pending' check(state in ('pending','completed','proposed')),
  covered_round bigint, manuscript_revision bigint,
  primary key(user_id,project_id,locale,milestone),
  foreign key(user_id,project_id) references public.user_memoir_project on delete cascade
);
alter table public.user_memoir_milestone enable row level security;
revoke all on public.user_memoir_milestone from public,anon,authenticated;
grant select on public.user_memoir_milestone to authenticated;
drop policy if exists memoir_milestone_owner on public.user_memoir_milestone;
create policy memoir_milestone_owner on public.user_memoir_milestone for select to authenticated using(user_id=auth.uid());

create or replace function public.safe_memoir_reuse(p_bundle jsonb,p_event_ids text[],p_source_id uuid default null) returns jsonb
language sql immutable set search_path='' as $$
  with safe_sections as (select value s from pg_catalog.jsonb_array_elements(coalesce(p_bundle->'sections','[]'))
    where not exists(select 1 from pg_catalog.jsonb_array_elements_text(value->'event_ids') id where id=any(p_event_ids))
      and not exists(select 1 from pg_catalog.jsonb_array_elements(value->'source_refs') ref where ref->>'source_id'=p_source_id::text))
  select pg_catalog.jsonb_build_object('content_config',p_bundle->'content_config',
    'kind',coalesce(p_bundle->'manuscript'->>'kind',p_bundle->>'kind','sample_chapter'),
    'sections',coalesce((select pg_catalog.jsonb_agg(s) from safe_sections),'[]'),
    'event_manifest',coalesce((select pg_catalog.jsonb_agg(e) from pg_catalog.jsonb_array_elements(coalesce(p_bundle->'event_manifest','[]')) e
      where e->>'id' in(select pg_catalog.jsonb_array_elements_text(s->'event_ids') from safe_sections)),'[]'))
$$;
revoke all on function public.safe_memoir_reuse(jsonb,text[],uuid) from public,anon,authenticated;

create or replace function public.pending_memoir_receipts(p_limit integer default 50) returns jsonb
language sql security definer set search_path='' as $$
  select coalesce(pg_catalog.jsonb_agg(id),'[]'::jsonb) from
    (select id from public.user_private_draft_outbox where not delivered order by created_at,id limit least(greatest(p_limit,1),100)) r
$$;
revoke all on function public.pending_memoir_receipts(integer) from public,anon,authenticated;
grant execute on function public.pending_memoir_receipts(integer) to service_role;

create or replace function public.read_memoir_receipt_scope(p_receipt_id uuid) returns jsonb
language sql security definer set search_path='' as $$
  select pg_catalog.jsonb_build_object('user_id',user_id,'project_id',project_id,'change_kind',change_kind)
    from public.user_private_draft_outbox where id=p_receipt_id and not delivered
$$;
revoke all on function public.read_memoir_receipt_scope(uuid) from public,anon,authenticated;
grant execute on function public.read_memoir_receipt_scope(uuid) to service_role;

create or replace function public.pending_memoir_lanes(p_limit integer default 50) returns jsonb
language sql security definer set search_path='' as $$
  select coalesce(pg_catalog.jsonb_agg(id),'[]'::jsonb) from
    (select id from public.user_memoir_lane where attempts<3 and available_at<=clock_timestamp() and
      (pending or (token is not null and (lease_until<=clock_timestamp() or run_deadline<=clock_timestamp())))
      order by available_at,id limit least(greatest(p_limit,1),100)) r
$$;
revoke all on function public.pending_memoir_lanes(integer) from public,anon,authenticated;
grant execute on function public.pending_memoir_lanes(integer) to service_role;

create or replace function public.queue_memoir_receipt(p_receipt_id uuid,p_cadence integer default 5)
returns jsonb language plpgsql security definer set search_path='' as $$
declare receipt public.user_private_draft_outbox%rowtype; project public.user_memoir_project%rowtype; lane_id uuid; composer_id uuid;
  completed_round bigint; milestone bigint; output_locale text;
begin
  if p_cadence not between 1 and 1000000 then raise exception 'invalid cadence' using errcode='22023'; end if;
  select * into receipt from public.user_private_draft_outbox where id=p_receipt_id for update;
  if not found then return null; end if;
  select * into project from public.user_memoir_project where user_id=receipt.user_id and project_id=receipt.project_id for update;
  if not found then return null; end if;
  insert into public.user_memoir_lane(user_id,project_id,skill,pending,target_source,target_event)
    values(receipt.user_id,receipt.project_id,'timeline',true,project.source_sequence,project.event_sequence)
    on conflict(user_id,project_id,skill) do update set
      pending=public.user_memoir_lane.pending or exists(select 1 from public.user_narrator_source
        where user_id=receipt.user_id and project_id=receipt.project_id and processing_status<>'succeeded' and status='active'),
      attempts=case when excluded.target_source>public.user_memoir_lane.target_source then 0 else public.user_memoir_lane.attempts end,
      error=case when excluded.target_source>public.user_memoir_lane.target_source then null else public.user_memoir_lane.error end,
      target_source=greatest(public.user_memoir_lane.target_source,excluded.target_source),target_event=excluded.target_event
    returning id into lane_id;
  select coalesce(max(ordinal),0) into completed_round from public.user_completed_round where user_id=receipt.user_id and project_id=receipt.project_id;
  milestone:=(completed_round/p_cadence)*p_cadence;
  select coalesce(profile->>'preferred_language','en-AU') into output_locale from public.user_profile where user_id=receipt.user_id;
  output_locale:=case when output_locale='zh-CN' then 'zh-CN' else 'en-AU' end;
  if milestone>0 then
    insert into public.user_memoir_milestone(user_id,project_id,locale,milestone)
      select receipt.user_id,receipt.project_id,output_locale,checkpoint
        from pg_catalog.generate_series(p_cadence::bigint,milestone,p_cadence::bigint) checkpoint
      on conflict do nothing;
    insert into public.user_memoir_lane(user_id,project_id,skill,pending,target_source,target_event,target_milestone,locale)
      values(receipt.user_id,receipt.project_id,'composer',true,project.source_sequence,project.event_sequence,milestone,output_locale)
      on conflict(user_id,project_id,skill) do update set
        pending=public.user_memoir_lane.pending or excluded.locale<>public.user_memoir_lane.locale or excluded.target_milestone>public.user_memoir_lane.target_milestone or
          (receipt.change_kind in ('correction','revocation','edit','delete') and
            (excluded.target_event>public.user_memoir_lane.successful_event or excluded.target_source>public.user_memoir_lane.successful_source)),
        attempts=case when excluded.target_milestone>public.user_memoir_lane.target_milestone or excluded.target_event>public.user_memoir_lane.target_event then 0 else public.user_memoir_lane.attempts end,
        error=case when excluded.target_milestone>public.user_memoir_lane.target_milestone or excluded.target_event>public.user_memoir_lane.target_event then null else public.user_memoir_lane.error end,
        target_source=excluded.target_source,target_event=excluded.target_event,target_milestone=excluded.target_milestone,locale=excluded.locale
      returning id into composer_id;
  end if;
  update public.user_private_draft_outbox set delivered=true where id=p_receipt_id;
  return pg_catalog.jsonb_build_object('timeline_lane_id',lane_id,'composer_lane_id',composer_id);
end $$;
revoke all on function public.queue_memoir_receipt(uuid,integer) from public,anon,authenticated;
grant execute on function public.queue_memoir_receipt(uuid,integer) to service_role;

create or replace function public.claim_memoir_lane(p_lane_id uuid,p_run_seconds integer default 300)
returns jsonb language plpgsql security definer set search_path='' as $$
declare lane public.user_memoir_lane%rowtype; project public.user_memoir_project%rowtype; now_at timestamptz:=clock_timestamp();
  run_token uuid:=gen_random_uuid(); manifest jsonb; sources jsonb; first_sequence bigint; last_sequence bigint;
  completed_round bigint; event_manifest jsonb;
begin
  if p_run_seconds not between 1 and 1800 then raise exception 'invalid run duration' using errcode='22023'; end if;
  select * into lane from public.user_memoir_lane where id=p_lane_id;
  if not found then return null; end if;
  select * into project from public.user_memoir_project where user_id=lane.user_id and project_id=lane.project_id for update;
  select * into lane from public.user_memoir_lane where id=p_lane_id for update;
  now_at:=clock_timestamp();
  if lane.token is not null then
    if lane.lease_until>now_at and lane.run_deadline>now_at then return null; end if;
    -- Timeout/crash never advances a successful cursor or discards its range.
    update public.user_memoir_lane set token=null,pending=true,error='MEMOIR_INTERRUPTED' where id=p_lane_id;
    lane.pending:=true;
  end if;
  if not lane.pending or lane.available_at>now_at then return null; end if;
  if lane.attempts>=3 then
    update public.user_memoir_lane set token=null,error='MEMOIR_RETRY_REQUIRED' where id=p_lane_id;
    return null;
  end if;
  if lane.skill='composer' then
    if exists(select 1 from public.user_narrator_source where user_id=lane.user_id and project_id=lane.project_id
      and processing_status<>'succeeded' and status='active') then return null; end if;
    select coalesce(max(ordinal),0) into completed_round from public.user_completed_round where user_id=lane.user_id and project_id=lane.project_id;
    if completed_round<lane.target_milestone then return null; end if;
  end if;
  select coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('id',s.id,'version',s.version) order by sequence),'[]'::jsonb),
    coalesce(pg_catalog.jsonb_agg(public.narrator_source_record(s) order by sequence),'[]'::jsonb),min(sequence),max(sequence)
    into manifest,sources,first_sequence,last_sequence from public.user_narrator_source s
    where user_id=lane.user_id and project_id=lane.project_id and status='active'
      and (lane.skill='composer' or processing_status<>'succeeded');
  if manifest='[]'::jsonb and lane.skill='timeline' then
    update public.user_memoir_lane set pending=false,token=null where id=p_lane_id;
    return null;
  end if;
  select coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('id',e.id,'revision',e.revision) order by id),'[]'::jsonb)
    into event_manifest from public.user_memory_event e where user_id=lane.user_id and project_id=lane.project_id and status<>'withdrawn';
  update public.user_memoir_lane set token=run_token,lease_until=now_at+pg_catalog.make_interval(secs=>least(60,p_run_seconds)),
    run_deadline=now_at+pg_catalog.make_interval(secs=>p_run_seconds),pending=false,active_manifest=manifest,
    active_through=coalesce(last_sequence,project.source_sequence),active_event=project.event_sequence,active_round=coalesce(completed_round,0),
    active_policy=project.policy_epoch,active_events=event_manifest,active_milestone=lane.target_milestone,active_locale=lane.locale,
    active_manuscript_revision=coalesce((select revision from public.user_memoir_manuscript where user_id=lane.user_id and project_id=lane.project_id and locale=lane.locale),0),
    attempts=attempts+1,error=null
    where id=p_lane_id;
  return pg_catalog.jsonb_build_object('lane_id',p_lane_id,'token',run_token,'skill',lane.skill,
    'user_id',lane.user_id,'project_id',lane.project_id,'locale',lane.locale,
    'from_sequence',case when lane.skill='composer' then lane.successful_source+1 else first_sequence end,
    'through_sequence',coalesce(last_sequence,project.source_sequence),'coverage_round',coalesce(completed_round,0),
    'milestone',lane.target_milestone,'source_manifest',manifest,'event_manifest',event_manifest,
    'event_sequence',project.event_sequence,'policy_epoch',project.policy_epoch,'sources',sources,
    'context_sources',coalesce((select pg_catalog.jsonb_agg(public.narrator_source_record(s) order by sequence)
      from public.user_narrator_source s where user_id=lane.user_id and project_id=lane.project_id and status='active'),'[]'::jsonb),
    'previous', (select coalesce(bundle,reuse) from public.user_memoir_manuscript where user_id=lane.user_id and project_id=lane.project_id and locale=lane.locale),
    'base_revision',coalesce((select revision from public.user_memoir_manuscript where user_id=lane.user_id and project_id=lane.project_id and locale=lane.locale),0),
    'human_locked',coalesce((select human_locked from public.user_memoir_manuscript where user_id=lane.user_id and project_id=lane.project_id and locale=lane.locale),false),
    'events',coalesce((select pg_catalog.jsonb_agg(public.memory_event_record(e) order by change_sequence,id)
      from public.user_memory_event e where user_id=lane.user_id and project_id=lane.project_id and status<>'withdrawn'),'[]'::jsonb));
end $$;
revoke all on function public.claim_memoir_lane(uuid,integer) from public,anon,authenticated;
grant execute on function public.claim_memoir_lane(uuid,integer) to service_role;

create or replace function public.finish_memoir_timeline(p_lane_id uuid,p_token uuid,p_events jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare lane public.user_memoir_lane%rowtype; saved jsonb;
begin
  select * into lane from public.user_memoir_lane where id=p_lane_id;
  if not found then return pg_catalog.jsonb_build_object('status','stale'); end if;
  perform 1 from public.user_memoir_project where user_id=lane.user_id and project_id=lane.project_id for update;
  select * into lane from public.user_memoir_lane where id=p_lane_id for update;
  if lane.skill<>'timeline' or lane.token is distinct from p_token or lane.token is null or
     lane.lease_until<=clock_timestamp() or lane.run_deadline<=clock_timestamp() or
     lane.active_policy is distinct from (select policy_epoch from public.user_memoir_project
       where user_id=lane.user_id and project_id=lane.project_id) then
    return pg_catalog.jsonb_build_object('status','stale');
  end if;
  perform pg_catalog.set_config('request.jwt.claim.sub',lane.user_id::text,true);
  saved:=public.apply_user_memory_events(lane.project_id,lane.active_manifest,p_events);
  if lane.run_deadline<=clock_timestamp() or lane.lease_until<=clock_timestamp() then
    raise exception 'memoir run expired before commit' using errcode='40001';
  end if;
  update public.user_memoir_lane set token=null,lease_until=null,run_deadline=null,active_manifest='[]',
    successful_source=(saved->'processing'->>'extracted_through')::bigint,attempts=0,error=null,
    pending=pending or exists(select 1 from public.user_narrator_source where user_id=lane.user_id and project_id=lane.project_id
      and processing_status<>'succeeded' and status='active') where id=p_lane_id;
  return pg_catalog.jsonb_build_object('status','saved','extracted_through',saved->'processing'->'extracted_through');
end $$;
revoke all on function public.finish_memoir_timeline(uuid,uuid,jsonb) from public,anon,authenticated;
grant execute on function public.finish_memoir_timeline(uuid,uuid,jsonb) to service_role;

create or replace function public.heartbeat_memoir_lane(p_lane_id uuid,p_token uuid) returns boolean
language plpgsql security definer set search_path='' as $$
begin
  update public.user_memoir_lane set lease_until=least(run_deadline,clock_timestamp()+interval '60 seconds')
    where id=p_lane_id and token=p_token and lease_until>clock_timestamp() and run_deadline>clock_timestamp();
  return found;
end $$;
revoke all on function public.heartbeat_memoir_lane(uuid,uuid) from public,anon,authenticated;
grant execute on function public.heartbeat_memoir_lane(uuid,uuid) to service_role;

create or replace function public.fail_memoir_lane(p_lane_id uuid,p_token uuid,p_error text,p_retryable boolean default true)
returns jsonb language plpgsql security definer set search_path='' as $$
declare lane public.user_memoir_lane%rowtype; retryable boolean;
begin
  if p_error not in ('MEMOIR_PROVIDER_UNAVAILABLE','MEMOIR_UNAVAILABLE','MEMOIR_CONFLICT','MEMOIR_REVIEW_FAILED') then
    raise exception 'invalid recoverable error code' using errcode='22023';
  end if;
  select * into lane from public.user_memoir_lane where id=p_lane_id for update;
  if not found or lane.token is null or lane.token is distinct from p_token or
      lane.run_deadline<=clock_timestamp() or lane.lease_until<=clock_timestamp() then
    return pg_catalog.jsonb_build_object('status','stale');
  end if;
  retryable:=p_retryable and lane.attempts<3;
  update public.user_memoir_lane set token=null,lease_until=null,run_deadline=null,pending=true,
    attempts=case when retryable then attempts else 3 end,error=p_error,
    available_at=clock_timestamp()+pg_catalog.make_interval(secs=>case when retryable then power(2,lane.attempts)::integer else 0 end)
    where id=p_lane_id;
  update public.user_narrator_source set processing_status='retry' where user_id=lane.user_id and project_id=lane.project_id
    and processing_status<>'succeeded' and id in(select (value->>'id')::uuid from pg_catalog.jsonb_array_elements(lane.active_manifest));
  return pg_catalog.jsonb_build_object('status',case when retryable then 'retry' else 'retry_required' end);
end $$;
revoke all on function public.fail_memoir_lane(uuid,uuid,text,boolean) from public,anon,authenticated;
grant execute on function public.fail_memoir_lane(uuid,uuid,text,boolean) to service_role;

create or replace function public.retry_user_memoir_lane(p_project_id text,p_skill text) returns jsonb
language plpgsql security definer set search_path='' as $$
begin
  if auth.uid() is null then raise exception 'authenticated user required' using errcode='42501'; end if;
  update public.user_memoir_lane set attempts=0,error=null,available_at=clock_timestamp(),pending=true,token=null,lease_until=null,run_deadline=null
    where user_id=auth.uid() and project_id=p_project_id and skill=p_skill and
      (token is null or lease_until<=clock_timestamp() or run_deadline<=clock_timestamp());
  return pg_catalog.jsonb_build_object('queued',found);
end $$;
revoke all on function public.retry_user_memoir_lane(text,text) from public,anon;
grant execute on function public.retry_user_memoir_lane(text,text) to authenticated;

create or replace function public.finish_memoir_composer(p_lane_id uuid,p_token uuid,p_expected_revision bigint,p_bundle jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare lane public.user_memoir_lane%rowtype; manuscript public.user_memoir_manuscript%rowtype;
  section jsonb; previous public.user_memoir_section_revision%rowtype; sections jsonb:='[]'; manifest jsonb; next_revision bigint;
begin
  select * into lane from public.user_memoir_lane where id=p_lane_id;
  if not found then return pg_catalog.jsonb_build_object('status','stale'); end if;
  perform 1 from public.user_memoir_project where user_id=lane.user_id and project_id=lane.project_id for update;
  select * into lane from public.user_memoir_lane where id=p_lane_id for update;
  if lane.skill<>'composer' or lane.token is null or lane.token is distinct from p_token or
    lane.lease_until<=clock_timestamp() or lane.run_deadline<=clock_timestamp() or
    lane.active_policy is distinct from (select policy_epoch from public.user_memoir_project
      where user_id=lane.user_id and project_id=lane.project_id) then
    return pg_catalog.jsonb_build_object('status','stale');
  end if;
  if (p_bundle->'validation'->>'ok')::boolean is distinct from true or
     (p_bundle->'review'->>'ready_for_user_review')::boolean is distinct from true or
     (p_bundle->'review'->>'publication_approved')::boolean is distinct from false or
     exists(select 1 from pg_catalog.jsonb_array_elements(p_bundle->'review'->'findings') f where f->>'severity'='blocking') or
     pg_catalog.jsonb_typeof(p_bundle->'sections') is distinct from 'array' then
    return pg_catalog.jsonb_build_object('status','rejected');
  end if;
  -- Unrelated new testimony may leave this frozen snapshot eligible. Relevant
  -- event/source edits or withdrawals refuse the obsolete candidate.
  if exists(select 1 from pg_catalog.jsonb_array_elements(lane.active_events) ref
      left join public.user_memory_event e on e.user_id=lane.user_id and e.project_id=lane.project_id and e.id=ref->>'id'
      where e.id is null or e.status='withdrawn' or e.revision is distinct from (ref->>'revision')::bigint) or
     exists(select 1 from pg_catalog.jsonb_array_elements(lane.active_manifest) ref
      left join public.user_narrator_source s on s.user_id=lane.user_id and s.project_id=lane.project_id and s.id=(ref->>'id')::uuid
      where s.id is null or s.status<>'active' or s.version is distinct from (ref->>'version')::bigint) then
    return pg_catalog.jsonb_build_object('status','stale');
  end if;
  for section in select value from pg_catalog.jsonb_array_elements(p_bundle->'sections') loop
    if pg_catalog.jsonb_typeof(section->'source_refs') is distinct from 'array' or exists(
      select 1 from pg_catalog.jsonb_array_elements(section->'source_refs') ref
      left join public.user_narrator_source s on s.user_id=lane.user_id and s.project_id=lane.project_id and s.id::text=ref->>'source_id'
      where s.id is null or s.status<>'active' or s.version::text is distinct from ref->>'version' or
        not exists(select 1 from pg_catalog.jsonb_array_elements(lane.active_manifest) m
          where m->>'id'=ref->>'source_id' and m->>'version'=ref->>'version') or
        ref->>'char_start' is null or ref->>'char_end' is null or (ref->>'char_start')::integer<0 or
        (ref->>'char_end')::integer<=(ref->>'char_start')::integer or (ref->>'char_end')::integer>length(s.text)) then
      raise exception 'section references an unavailable source' using errcode='42501';
    end if;
  end loop;
  insert into public.user_memoir_manuscript(user_id,project_id,locale) values(lane.user_id,lane.project_id,lane.active_locale) on conflict do nothing;
  select * into manuscript from public.user_memoir_manuscript where user_id=lane.user_id and project_id=lane.project_id and locale=lane.active_locale for update;
  if manuscript.revision is distinct from p_expected_revision or p_expected_revision is distinct from lane.active_manuscript_revision then
    return pg_catalog.jsonb_build_object('status','stale');
  end if;
  if coalesce((p_bundle->>'unchanged')::boolean,false) then
    if manuscript.bundle is null or manuscript.bundle->'sections' is distinct from p_bundle->'sections' or
       manuscript.bundle->'preview' is distinct from p_bundle->'preview' or
       manuscript.bundle->'event_manifest' is distinct from lane.active_events then
      raise exception 'unchanged completion has changed dependencies' using errcode='40001';
    end if;
    update public.user_memoir_manuscript set covered_round=lane.active_round,source_sequence=lane.active_through,
      event_sequence=lane.active_event,completed_milestone=lane.active_milestone
      where user_id=lane.user_id and project_id=lane.project_id and locale=lane.active_locale;
  elsif manuscript.human_locked then
    update public.user_memoir_manuscript set proposal=pg_catalog.jsonb_build_object('base_revision',manuscript.revision,'bundle',p_bundle)
      where user_id=lane.user_id and project_id=lane.project_id and locale=lane.active_locale;
  else
    for section in select value from pg_catalog.jsonb_array_elements(p_bundle->'sections') loop
      if length(coalesce(section->>'id','')) not between 1 and 100 or length(coalesce(section->>'fingerprint',''))=0 or
        pg_catalog.jsonb_typeof(section->'event_ids') is distinct from 'array' then
        raise exception 'invalid section dependency manifest' using errcode='22023';
      end if;
      if exists(select 1 from pg_catalog.jsonb_array_elements_text(section->'event_ids') id where not exists
          (select 1 from pg_catalog.jsonb_array_elements(lane.active_events) e where e->>'id'=id)) then
        raise exception 'section references an unavailable event' using errcode='42501';
      end if;
      select * into previous from public.user_memoir_section_revision where user_id=lane.user_id and project_id=lane.project_id
        and locale=lane.active_locale and section_id=section->>'id' order by revision desc limit 1;
      if found and previous.fingerprint=section->>'fingerprint' then
        -- Never accept provider rewriting of an unchanged stored section.
        section:=previous.data;
      else
        next_revision:=coalesce(previous.revision,0)+1;
        section:=section || pg_catalog.jsonb_build_object('revision',next_revision);
        select coalesce(pg_catalog.jsonb_agg(e),'[]'::jsonb) into manifest from pg_catalog.jsonb_array_elements(lane.active_events) e
          where e->>'id' in(select pg_catalog.jsonb_array_elements_text(section->'event_ids'));
        insert into public.user_memoir_section_revision(user_id,project_id,locale,section_id,revision,fingerprint,data,event_manifest)
          values(lane.user_id,lane.project_id,lane.active_locale,section->>'id',next_revision,section->>'fingerprint',section,manifest);
      end if;
      sections:=sections || pg_catalog.jsonb_build_array(section);
    end loop;
    p_bundle:=pg_catalog.jsonb_set(p_bundle,'{sections}',sections);
    update public.user_memoir_manuscript set revision=revision+1,bundle=p_bundle,reuse=null,proposal=null,eligible=true,
      covered_round=lane.active_round,source_sequence=lane.active_through,event_sequence=lane.active_event,completed_milestone=lane.active_milestone
      where user_id=lane.user_id and project_id=lane.project_id and locale=lane.active_locale;
  end if;
  if lane.run_deadline<=clock_timestamp() or lane.lease_until<=clock_timestamp() then
    raise exception 'memoir run expired before commit' using errcode='40001';
  end if;
  update public.user_memoir_milestone set state=case when manuscript.human_locked then 'proposed' else 'completed' end,
    covered_round=lane.active_round,manuscript_revision=manuscript.revision+
      case when manuscript.human_locked or coalesce((p_bundle->>'unchanged')::boolean,false) then 0 else 1 end
    where user_id=lane.user_id and project_id=lane.project_id and locale=lane.active_locale and
      milestone<=lane.active_milestone and state='pending';
  update public.user_memoir_lane set token=null,lease_until=null,run_deadline=null,active_manifest='[]',active_events='[]',
    successful_source=active_through,successful_event=active_event,successful_round=active_round,attempts=0,error=null
    where id=p_lane_id;
  return pg_catalog.jsonb_build_object('status',case when manuscript.human_locked then 'proposed' else 'saved' end);
end $$;
revoke all on function public.finish_memoir_composer(uuid,uuid,bigint,jsonb) from public,anon,authenticated;
grant execute on function public.finish_memoir_composer(uuid,uuid,bigint,jsonb) to service_role;

create or replace function public.read_user_memoir_draft(p_project_id text,p_locale text default 'en-AU') returns jsonb
language plpgsql security definer set search_path='' as $$
declare saved public.user_memoir_manuscript%rowtype; lane public.user_memoir_lane%rowtype; timeline public.user_memoir_lane%rowtype;
begin
  if auth.uid() is null then raise exception 'authenticated user required' using errcode='42501'; end if;
  select * into saved from public.user_memoir_manuscript where user_id=auth.uid() and project_id=p_project_id and locale=p_locale;
  select * into lane from public.user_memoir_lane where user_id=auth.uid() and project_id=p_project_id and skill='composer';
  select * into timeline from public.user_memoir_lane where user_id=auth.uid() and project_id=p_project_id and skill='timeline';
  return pg_catalog.jsonb_build_object('status',case when saved.bundle is not null and saved.eligible then 'ready' when not saved.eligible then 'stale' else 'collecting' end,
    'preview',case when saved.eligible then saved.bundle->'preview' else null end,
    'covered_round',coalesce(saved.covered_round,0),'milestone',coalesce(saved.completed_milestone,0),'revision',coalesce(saved.revision,0),
    'milestones',coalesce((select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('milestone',milestone,'state',state,
      'covered_round',covered_round,'manuscript_revision',manuscript_revision) order by milestone)
      from public.user_memoir_milestone where user_id=auth.uid() and project_id=p_project_id and locale=p_locale),'[]'),
    'sections',case when saved.eligible then coalesce(saved.bundle->'sections','[]'::jsonb) else '[]'::jsonb end,
    'updating',(public.memoir_lane_progress(lane)->>'state') in ('running','pending') or
      ((public.memoir_lane_progress(timeline)->>'state') in ('running','pending') and exists(select 1 from public.user_narrator_source
        where user_id=auth.uid() and project_id=p_project_id and status='active' and processing_status<>'succeeded')),
    'progress',pg_catalog.jsonb_build_object('composition',public.memoir_lane_progress(lane),
      'extraction',public.memoir_lane_progress(timeline) || pg_catalog.jsonb_build_object('extracted_through',coalesce((select extraction_cursor from public.user_memoir_project where user_id=auth.uid() and project_id=p_project_id),0),
        'pending_inputs',(select count(*) from public.user_narrator_source where user_id=auth.uid() and project_id=p_project_id and status='active' and processing_status<>'succeeded'))),
    'error',coalesce(lane.error,timeline.error),'proposal_pending',saved.proposal is not null);
end $$;
revoke all on function public.read_user_memoir_draft(text,text) from public,anon;
grant execute on function public.read_user_memoir_draft(text,text) to authenticated;

create or replace function public.protect_user_memoir_draft(p_project_id text,p_locale text,p_expected_revision bigint,p_locked boolean) returns jsonb
language plpgsql security definer set search_path='' as $$
declare saved public.user_memoir_manuscript%rowtype;
begin
  if auth.uid() is null then raise exception 'authenticated user required' using errcode='42501'; end if;
  perform 1 from public.user_memoir_project where user_id=auth.uid() and project_id=p_project_id for update;
  select * into saved from public.user_memoir_manuscript where user_id=auth.uid() and project_id=p_project_id and locale=p_locale for update;
  if not found or saved.revision is distinct from p_expected_revision then raise exception 'manuscript revision conflict; reload the draft' using errcode='40001'; end if;
  update public.user_memoir_manuscript set human_locked=p_locked where user_id=auth.uid() and project_id=p_project_id and locale=p_locale;
  return pg_catalog.jsonb_build_object('revision',saved.revision,'protected',p_locked);
end $$;
revoke all on function public.protect_user_memoir_draft(text,text,bigint,boolean) from public,anon;
grant execute on function public.protect_user_memoir_draft(text,text,bigint,boolean) to authenticated;

create or replace function public.read_user_memoir_proposal(p_project_id text,p_locale text) returns jsonb
language sql security definer set search_path='' as $$
  select pg_catalog.jsonb_build_object('base_revision',proposal->'base_revision','preview',proposal->'bundle'->'preview')
    from public.user_memoir_manuscript where user_id=auth.uid() and project_id=p_project_id and locale=p_locale and proposal is not null
$$;
revoke all on function public.read_user_memoir_proposal(text,text) from public,anon;
grant execute on function public.read_user_memoir_proposal(text,text) to authenticated;

create table if not exists public.user_memory_event_change (
  user_id uuid not null, project_id text not null, sequence bigint not null, event_id text not null,
  old_group jsonb, new_group jsonb not null, revision bigint not null,
  primary key(user_id,project_id,sequence),
  foreign key(user_id,project_id) references public.user_memoir_project on delete cascade
);
alter table public.user_memory_event_change enable row level security;
revoke all on public.user_memory_event_change from public,anon,authenticated;
grant select on public.user_memory_event_change to authenticated;
drop policy if exists memory_event_change_owner on public.user_memory_event_change;
create policy memory_event_change_owner on public.user_memory_event_change for select to authenticated using(user_id=auth.uid());

create or replace function public.memory_event_group(e public.user_memory_event) returns jsonb
language sql immutable set search_path='' as $$
  select pg_catalog.jsonb_build_object('event_id',e.id,'life_stage',e.life_stage,
    'year_start',e.data->'temporal'->'year_start','year_end',e.data->'temporal'->'year_end',
    'precision',coalesce(e.data->'temporal'->>'precision','unknown'),'kind',e.kind)
$$;
revoke all on function public.memory_event_group(public.user_memory_event) from public,anon,authenticated;

create or replace function public.record_memory_event_change() returns trigger
language plpgsql security definer set search_path='' as $$
begin
  if TG_OP='UPDATE' and new.revision=old.revision then return new; end if;
  insert into public.user_memory_event_change(user_id,project_id,sequence,event_id,old_group,new_group,revision)
    values(new.user_id,new.project_id,new.change_sequence,new.id,
      case when TG_OP='UPDATE' then public.memory_event_group(old) else null end,public.memory_event_group(new),new.revision)
    on conflict(user_id,project_id,sequence) do nothing;
  if TG_OP='UPDATE' and (new.data->'user_overrides' is distinct from old.data->'user_overrides' or new.status='withdrawn') then
    update public.user_memoir_manuscript m set eligible=false,proposal=null where user_id=new.user_id and project_id=new.project_id
      and exists(select 1 from pg_catalog.jsonb_array_elements(coalesce(m.bundle->'event_manifest','[]')) ref where ref->>'id'=new.id);
  end if;
  return new;
end $$;
revoke all on function public.record_memory_event_change() from public,anon,authenticated;
drop trigger if exists record_memory_event_change on public.user_memory_event;
create trigger record_memory_event_change after insert or update on public.user_memory_event
  for each row execute function public.record_memory_event_change();

create or replace function public.read_user_memory_event_changes(p_project_id text,p_after_sequence bigint default 0) returns jsonb
language sql security definer set search_path='' as $$
  select coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('sequence',sequence,'event_id',event_id,
    'revision',revision,'old_group',old_group,'new_group',new_group) order by sequence),'[]'::jsonb)
  from public.user_memory_event_change where user_id=auth.uid() and project_id=p_project_id and sequence>p_after_sequence
$$;
revoke all on function public.read_user_memory_event_changes(text,bigint) from public,anon;
grant execute on function public.read_user_memory_event_changes(text,bigint) to authenticated;

create or replace function public.change_user_narrator_source(p_project_id text,p_source_id uuid,
  p_expected_version bigint,p_action text,p_text text default null) returns jsonb
language plpgsql security definer set search_path='' as $$
declare owner_id uuid:=auth.uid(); saved public.user_narrator_source%rowtype; affected text[]; affected_event_id text;
  next_sequence bigint; next_change bigint; previous_sync text;
begin
  if owner_id is null then raise exception 'authenticated user required' using errcode='42501'; end if;
  if p_action not in ('edit','withdraw') or (p_action='edit' and length(pg_catalog.btrim(coalesce(p_text,''))) not between 1 and 100000) then
    raise exception 'invalid source change' using errcode='22023';
  end if;
  perform 1 from public.user_memoir_project where user_id=owner_id and project_id=p_project_id for update;
  select * into saved from public.user_narrator_source where user_id=owner_id and project_id=p_project_id and id=p_source_id for update;
  if not found then raise exception 'source unavailable' using errcode='42501'; end if;
  if saved.version is distinct from p_expected_version or saved.status<>'active' then
    raise exception 'source revision conflict; reload the source' using errcode='40001';
  end if;
  if p_action='edit' and (select coalesce(sum(length(text)),0) from public.user_narrator_source
     where user_id=owner_id and project_id=p_project_id and id<>p_source_id)+length(p_text)>120000 then
    raise exception 'memoir evidence exceeds supported bounds' using errcode='22023';
  end if;
  select array_agg(distinct s.event_id) into affected from public.user_memory_event_source s
    where user_id=owner_id and project_id=p_project_id and source_id=p_source_id;
  -- Eligibility changes in the same transaction as the source change.
  update public.user_memoir_manuscript m set eligible=false,proposal=null,
    reuse=case when p_action='withdraw' then public.safe_memoir_reuse(coalesce(m.bundle,m.reuse),affected,p_source_id) else reuse end,
    bundle=case when p_action='withdraw' then null else bundle end
    where user_id=owner_id and project_id=p_project_id and
      ((p_action='withdraw' and exists(select 1 from pg_catalog.jsonb_array_elements(coalesce(m.bundle->'source_manifest','[]')) r where r->>'id'=p_source_id::text)) or
       exists(select 1 from pg_catalog.jsonb_array_elements(coalesce(m.bundle->'sections','[]')) section,
         pg_catalog.jsonb_array_elements(section->'source_refs') r where r->>'source_id'=p_source_id::text));
  if p_action='withdraw' then
    delete from public.user_memoir_section_revision r where user_id=owner_id and project_id=p_project_id and exists
      (select 1 from pg_catalog.jsonb_array_elements(r.data->'source_refs') ref where ref->>'source_id'=p_source_id::text);
    -- Existing deletion policy removes restricted original and derived bytes.
    update public.user_narrator_source_version set text='[withdrawn]' where user_id=owner_id and project_id=p_project_id and source_id=p_source_id;
    delete from public.user_memory_event_revision where user_id=owner_id and project_id=p_project_id and event_id=any(affected);
    -- Retired views can contain the original in their saved request as well as
    -- generated prose. Scope their removal to this owner's affected project.
    update public.user_memory set content='[Evidence withdrawn; rebuild from surviving originals.]'
      where user_id=owner_id and kind='memoir' and
        (project_id=p_project_id or ('memoir-preview:' || p_project_id)=any(source_paths));
    update public.user_family_context f set document=pg_catalog.jsonb_set(f.document,'{timeline}',
      coalesce((select pg_catalog.jsonb_agg(item) from pg_catalog.jsonb_array_elements(coalesce(f.document->'timeline','[]')) item
        where not (item->>'id'=any(coalesce(affected,array[]::text[])) or
          exists(select 1 from public.user_memory_event_alias a where a.user_id=owner_id and a.project_id=p_project_id
            and a.event_id=any(affected) and a.legacy_id=item->>'id') or
          exists(select 1 from pg_catalog.jsonb_array_elements(coalesce(item->'source_refs','[]')) ref
            where ref->>'source_id'=p_source_id::text or ref->>'source_id' in
              (select legacy_id from public.user_narrator_source_alias where user_id=owner_id and project_id=p_project_id and source_id=p_source_id)))),'[]')),
      revision=f.revision+1 where f.user_id=owner_id and f.project_id=p_project_id;
  end if;
  delete from public.user_memory_event_source where user_id=owner_id and project_id=p_project_id and source_id=p_source_id;
  foreach affected_event_id in array coalesce(affected,array[]::text[]) loop
    update public.user_memoir_project set event_sequence=event_sequence+1 where user_id=owner_id and project_id=p_project_id returning event_sequence into next_change;
    update public.user_memory_event e set revision=revision+1,change_sequence=next_change,
      status=case when p_action='edit' or exists(select 1 from public.user_memory_event_source s where s.user_id=owner_id and s.project_id=p_project_id and s.event_id=e.id) then 'unresolved' else 'withdrawn' end,
      life_stage=case when data->'user_overrides' ? 'life_stage' and data->'user_overrides'->'life_stage'->>'source_id' is distinct from p_source_id::text then life_stage else 'unplaced' end,
      data=pg_catalog.jsonb_build_object('title','Evidence changed; awaiting extraction','temporal',
        case when data->'user_overrides' ? 'temporal' and data->'user_overrides'->'temporal'->>'source_id' is distinct from p_source_id::text
          then data->'temporal' else pg_catalog.jsonb_build_object('expression','unknown','precision','unknown') end,
        'stage_evidence',case when data->'user_overrides' ? 'life_stage' and data->'user_overrides'->'life_stage'->>'source_id' is distinct from p_source_id::text
          then coalesce(data->'stage_evidence','[]') else '[]'::jsonb end,
        'user_overrides',coalesce((select pg_catalog.jsonb_object_agg(key,value) from pg_catalog.jsonb_each(coalesce(data->'user_overrides','{}'))
          where value->>'source_id' is distinct from p_source_id::text),'{}'),
        'visibility',coalesce(data->>'visibility','private'),'include_in_print',coalesce((data->>'include_in_print')::boolean,false),
        'reconciliation_source_ids',case when p_action='edit' then pg_catalog.jsonb_build_array(p_source_id) else '[]'::jsonb end)
      where user_id=owner_id and project_id=p_project_id and id=affected_event_id;
  end loop;
  -- Surviving testimony needs reconciliation too: a withdrawal is not a
  -- successful extraction of the facts formerly supported by that source.
  update public.user_narrator_source original set processing_status='pending'
    where user_id=owner_id and project_id=p_project_id and status='active' and id<>p_source_id
      and exists(select 1 from public.user_memory_event_source link where link.user_id=owner_id
        and link.project_id=p_project_id and link.event_id=any(affected) and link.source_id=original.id);
  update public.user_memoir_project set source_sequence=source_sequence+1,policy_epoch=policy_epoch+1
    where user_id=owner_id and project_id=p_project_id returning source_sequence into next_sequence;
  update public.user_narrator_source set version=version+1,sequence=next_sequence,
    text=case when p_action='withdraw' then '[withdrawn]' else p_text end,
    status=case when p_action='withdraw' then 'withdrawn' else 'active' end,
    processing_status=case when p_action='withdraw' then 'succeeded' else 'pending' end
    where user_id=owner_id and project_id=p_project_id and id=p_source_id returning * into saved;
  insert into public.user_narrator_source_version(user_id,project_id,source_id,version,text,language)
    values(owner_id,p_project_id,p_source_id,saved.version,saved.text,saved.language);
  -- Conversation memory is a disposable context view. Withdrawn originals and
  -- assistant-derived repetitions cannot remain available through that view.
  previous_sync:=pg_catalog.current_setting('memoir.sync_source',true);
  perform pg_catalog.set_config('memoir.sync_source','true',true);
  update public.user_memory set content='Storyteller: ' || saved.text || E'\nMemory Spark: [source changed]'
    where user_id=owner_id and project_id=p_project_id and kind='agent' and
      (client_turn_id=saved.client_turn_id or id::text in(select legacy_id from public.user_narrator_source_alias
        where user_id=owner_id and project_id=p_project_id and source_id=p_source_id));
  perform pg_catalog.set_config('memoir.sync_source',coalesce(previous_sync,''),true);
  update public.user_memoir_project set extraction_cursor=coalesce((select min(sequence)-1 from public.user_narrator_source
      where user_id=owner_id and project_id=p_project_id and status='active' and processing_status<>'succeeded'),source_sequence)
    where user_id=owner_id and project_id=p_project_id;
  insert into public.user_private_draft_outbox(user_id,project_id,memory_id,change_kind)
    values(owner_id,p_project_id,p_source_id,case when p_action='withdraw' then 'revocation' else 'edit' end);
  return public.narrator_source_record(saved);
end $$;
revoke all on function public.change_user_narrator_source(text,uuid,bigint,text,text) from public,anon;
grant execute on function public.change_user_narrator_source(text,uuid,bigint,text,text) to authenticated;

create or replace function public.unlink_user_memory_event_source(p_project_id text,p_event_id text,p_expected_revision bigint,
  p_source_id uuid,p_statement text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare owner_id uuid:=auth.uid(); saved public.user_memory_event%rowtype; next_change bigint;
begin
  if owner_id is null then raise exception 'authenticated user required' using errcode='42501'; end if;
  if length(pg_catalog.btrim(coalesce(p_statement,''))) not between 1 and 2000 then raise exception 'source removal requires a statement' using errcode='22023'; end if;
  perform 1 from public.user_memoir_project where user_id=owner_id and project_id=p_project_id for update;
  select * into saved from public.user_memory_event where user_id=owner_id and project_id=p_project_id and id=p_event_id for update;
  if not found then raise exception 'event unavailable' using errcode='42501'; end if;
  if saved.revision is distinct from p_expected_revision then raise exception 'event revision conflict; reload the event' using errcode='40001'; end if;
  if not exists(select 1 from public.user_memory_event_source where user_id=owner_id and project_id=p_project_id and event_id=p_event_id and source_id=p_source_id) then
    raise exception 'source link unavailable' using errcode='42501'; end if;
  insert into public.user_memory_event_source_exclusion values(owner_id,p_project_id,p_event_id,p_source_id,owner_id,p_statement,p_expected_revision) on conflict do nothing;
  delete from public.user_memory_event_source where user_id=owner_id and project_id=p_project_id and event_id=p_event_id and source_id=p_source_id;
  update public.user_memoir_manuscript m set eligible=false,reuse=public.safe_memoir_reuse(coalesce(m.bundle,m.reuse),array[p_event_id]),bundle=null,proposal=null where user_id=owner_id and project_id=p_project_id and
    exists(select 1 from pg_catalog.jsonb_array_elements(coalesce(m.bundle->'event_manifest','[]')) e where e->>'id'=p_event_id);
  delete from public.user_memoir_checkpoint c using public.user_memoir_lane l where c.lane_id=l.id and l.user_id=owner_id and l.project_id=p_project_id and
    exists(select 1 from pg_catalog.jsonb_array_elements(c.event_manifest) e where e->>'id'=p_event_id);
  update public.user_memoir_project set event_sequence=event_sequence+1,policy_epoch=policy_epoch+1 where user_id=owner_id and project_id=p_project_id returning event_sequence into next_change;
  update public.user_memory_event e set revision=revision+1,change_sequence=next_change,
    life_stage=case when saved.data->'user_overrides' ? 'life_stage' and saved.data->'user_overrides'->'life_stage'->>'source_id' is distinct from p_source_id::text then saved.life_stage else 'unplaced' end,
    status=case when exists(select 1 from public.user_memory_event_source where user_id=owner_id and project_id=p_project_id and event_id=p_event_id) then 'unresolved' else 'withdrawn' end,
    data=pg_catalog.jsonb_build_object('title','Evidence changed; awaiting extraction','temporal',
      case when saved.data->'user_overrides' ? 'temporal' and saved.data->'user_overrides'->'temporal'->>'source_id' is distinct from p_source_id::text
        then saved.data->'temporal' else pg_catalog.jsonb_build_object('expression','unknown','precision','unknown') end,
      'stage_evidence',case when saved.data->'user_overrides' ? 'life_stage' and saved.data->'user_overrides'->'life_stage'->>'source_id' is distinct from p_source_id::text
        then coalesce(saved.data->'stage_evidence','[]') else '[]'::jsonb end,
      'user_overrides',coalesce((select pg_catalog.jsonb_object_agg(key,value) from pg_catalog.jsonb_each(coalesce(saved.data->'user_overrides','{}'))
        where value->>'source_id' is distinct from p_source_id::text),'{}'),
      'visibility',saved.data->'visibility','include_in_print',saved.data->'include_in_print')
    where user_id=owner_id and project_id=p_project_id and id=p_event_id returning * into saved;
  update public.user_narrator_source set processing_status='pending' where user_id=owner_id and project_id=p_project_id and status='active' and id in
    (select source_id from public.user_memory_event_source where user_id=owner_id and project_id=p_project_id and event_id=p_event_id);
  update public.user_memoir_project set extraction_cursor=coalesce((select min(sequence)-1 from public.user_narrator_source where user_id=owner_id and project_id=p_project_id and status='active' and processing_status<>'succeeded'),source_sequence)
    where user_id=owner_id and project_id=p_project_id;
  insert into public.user_private_draft_outbox(user_id,project_id,change_kind) values(owner_id,p_project_id,'edit');
  return public.memory_event_record(saved);
end $$;
revoke all on function public.unlink_user_memory_event_source(text,text,bigint,uuid,text) from public,anon;
grant execute on function public.unlink_user_memory_event_source(text,text,bigint,uuid,text) to authenticated;

create table if not exists public.user_memoir_checkpoint (
  lane_id uuid not null references public.user_memoir_lane(id) on delete cascade,
  key text not null, kind text not null check(kind in ('prepare','compose')),
  value jsonb not null, source_manifest jsonb not null, event_manifest jsonb not null,
  created_at timestamptz not null default clock_timestamp(), primary key(lane_id,key)
);
alter table public.user_memoir_checkpoint enable row level security;
revoke all on public.user_memoir_checkpoint from public,anon,authenticated;

create or replace function public.read_memoir_checkpoint(p_lane_id uuid,p_token uuid,p_key text) returns jsonb
language sql security definer set search_path='' as $$
  select c.value from public.user_memoir_checkpoint c join public.user_memoir_lane l on l.id=c.lane_id
    join public.user_memoir_project p on p.user_id=l.user_id and p.project_id=l.project_id
    where l.id=p_lane_id and l.token=p_token and l.lease_until>clock_timestamp() and l.run_deadline>clock_timestamp()
      and l.active_policy=p.policy_epoch and c.key=p_key and c.created_at>clock_timestamp()-interval '7 days'
$$;
revoke all on function public.read_memoir_checkpoint(uuid,uuid,text) from public,anon,authenticated;
grant execute on function public.read_memoir_checkpoint(uuid,uuid,text) to service_role;

create or replace function public.save_memoir_checkpoint(p_lane_id uuid,p_token uuid,p_key text,p_kind text,p_value jsonb) returns boolean
language plpgsql security definer set search_path='' as $$
declare lane public.user_memoir_lane%rowtype;
begin
  select * into lane from public.user_memoir_lane where id=p_lane_id for update;
  if not found or lane.token is null or lane.token is distinct from p_token or lane.lease_until<=clock_timestamp() or lane.run_deadline<=clock_timestamp()
     or lane.active_policy is distinct from (select policy_epoch from public.user_memoir_project where user_id=lane.user_id and project_id=lane.project_id) then return false; end if;
  if p_key !~ '^[a-f0-9]{64}$' or p_kind not in ('prepare','compose') or pg_catalog.jsonb_typeof(p_value) is distinct from 'object'
    or length(p_value::text)>500000 then raise exception 'invalid execution checkpoint' using errcode='22023'; end if;
  insert into public.user_memoir_checkpoint(lane_id,key,kind,value,source_manifest,event_manifest)
    values(p_lane_id,p_key,p_kind,p_value,lane.active_manifest,lane.active_events)
    on conflict(lane_id,key) do update set value=excluded.value,source_manifest=excluded.source_manifest,event_manifest=excluded.event_manifest,created_at=clock_timestamp();
  return true;
end $$;
revoke all on function public.save_memoir_checkpoint(uuid,uuid,text,text,jsonb) from public,anon,authenticated;
grant execute on function public.save_memoir_checkpoint(uuid,uuid,text,text,jsonb) to service_role;

create or replace function public.purge_memoir_source_checkpoints() returns trigger
language plpgsql security definer set search_path='' as $$
begin
  if old.version is distinct from new.version or old.status is distinct from new.status then
    delete from public.user_memoir_checkpoint c using public.user_memoir_lane l where c.lane_id=l.id
      and l.user_id=new.user_id and l.project_id=new.project_id and exists
        (select 1 from pg_catalog.jsonb_array_elements(c.source_manifest) ref where ref->>'id'=new.id::text);
  end if;
  return new;
end $$;
revoke all on function public.purge_memoir_source_checkpoints() from public,anon,authenticated;
drop trigger if exists purge_memoir_source_checkpoints on public.user_narrator_source;
create trigger purge_memoir_source_checkpoints after update on public.user_narrator_source
  for each row execute function public.purge_memoir_source_checkpoints();

-- Explicit legacy mappings are retained; titles/dates are never join keys.
create table if not exists public.user_memory_event_alias (
  user_id uuid not null, project_id text not null, namespace text not null,
  legacy_id text not null, event_id text not null,
  primary key(user_id,project_id,namespace,legacy_id),
  foreign key(user_id,project_id,event_id) references public.user_memory_event on delete cascade
);
create table if not exists public.user_narrator_source_alias (
  user_id uuid not null, project_id text not null, legacy_id text not null, source_id uuid not null,
  primary key(user_id,project_id,legacy_id),
  foreign key(user_id,project_id,source_id) references public.user_narrator_source on delete cascade
);
alter table public.user_memory_event_alias enable row level security;
alter table public.user_narrator_source_alias enable row level security;
revoke all on public.user_memory_event_alias,public.user_narrator_source_alias from public,anon,authenticated;
grant select on public.user_memory_event_alias,public.user_narrator_source_alias to authenticated;
drop policy if exists memory_event_alias_owner on public.user_memory_event_alias;
create policy memory_event_alias_owner on public.user_memory_event_alias for select to authenticated using(user_id=auth.uid());
drop policy if exists narrator_source_alias_owner on public.user_narrator_source_alias;
create policy narrator_source_alias_owner on public.user_narrator_source_alias for select to authenticated using(user_id=auth.uid());

create or replace function public.import_legacy_memory_events(p_project_id text,p_namespace text,p_items jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare owner_id uuid:=auth.uid(); item jsonb; old_ref jsonb; ref jsonb; refs jsonb; original public.user_narrator_source%rowtype;
  event_id text; next_change bigint; timing jsonb; expression text; precision text; years text[]; stage text; person_ids jsonb; missing_person_ids jsonb;
  result jsonb:='{}'; candidates jsonb;
begin
  if owner_id is null then raise exception 'authenticated user required' using errcode='42501'; end if;
  if p_namespace not in ('timeline','composer') or pg_catalog.jsonb_typeof(p_items) is distinct from 'array' or pg_catalog.jsonb_array_length(p_items)>1000 then
    raise exception 'invalid legacy event collection' using errcode='22023'; end if;
  perform 1 from public.user_memoir_project where user_id=owner_id and project_id=p_project_id for update;
  for item in select value from pg_catalog.jsonb_array_elements(p_items) loop
    if length(coalesce(item->>'id','')) not between 1 and 128 or length(coalesce(item->>'title',item->>'summary','')) not between 1 and 300 then continue; end if;
    select a.event_id into event_id from public.user_memory_event_alias a where user_id=owner_id and project_id=p_project_id and namespace=p_namespace and legacy_id=item->>'id';
    if found then result:=result || pg_catalog.jsonb_build_object(item->>'id',event_id); continue; end if;
    -- Only an explicit canonical mapping authorises cross-index reconciliation.
    if item ? 'canonical_event_id' and exists(select 1 from public.user_memory_event where user_id=owner_id and project_id=p_project_id and id=item->>'canonical_event_id') then
      event_id:=item->>'canonical_event_id';
      insert into public.user_memory_event_alias values(owner_id,p_project_id,p_namespace,item->>'id',event_id);
      result:=result || pg_catalog.jsonb_build_object(item->>'id',event_id); continue;
    end if;
    event_id:=item->>'id'; candidates:='[]';
    if exists(select 1 from public.user_memory_event where user_id=owner_id and project_id=p_project_id and id=event_id) then
      candidates:=pg_catalog.jsonb_build_array(event_id); event_id:=pg_catalog.gen_random_uuid()::text;
    end if;
    refs:='[]';
    for old_ref in select value from pg_catalog.jsonb_array_elements(coalesce(item->'source_refs','[]')) loop
      select s.* into original from public.user_narrator_source s join public.user_narrator_source_alias a
        on a.user_id=s.user_id and a.project_id=s.project_id and a.source_id=s.id
        where a.user_id=owner_id and a.project_id=p_project_id and a.legacy_id=old_ref->>'source_id' and s.status='active';
      if not found then
        select * into original from public.user_narrator_source where user_id=owner_id and project_id=p_project_id and id::text=old_ref->>'source_id' and status='active';
      end if;
      if not found then continue; end if;
      ref:=pg_catalog.jsonb_build_object('source_id',original.id,'version',original.version,'quote',coalesce(old_ref->>'quote',
        pg_catalog.substr(original.text,coalesce((old_ref->>'char_start')::integer,0)+1,(old_ref->>'char_end')::integer-coalesce((old_ref->>'char_start')::integer,0))));
      if length(coalesce(ref->>'quote','')) not between 1 and 2000 or pg_catalog.strpos(original.text,ref->>'quote')=0 then continue; end if;
      ref:=ref || case when old_ref ? 'attribution' then pg_catalog.jsonb_build_object('attribution',old_ref->'attribution') else '{}'::jsonb end;
      refs:=refs || pg_catalog.jsonb_build_array(ref);
    end loop;
    expression:=coalesce(item->'date'->>'original_expression',item->>'date_expression',
      nullif(pg_catalog.concat_ws(' – ',item->>'start_expression',item->>'end_expression'),''),'unknown');
    precision:=coalesce(item->>'precision',item->'date'->>'precision','unknown');
    if precision not in ('unknown','day','month','year','range','approximate','age','season') then precision:='approximate'; end if;
    timing:=pg_catalog.jsonb_build_object('expression',expression,'precision',precision,'basis',refs,
      'legacy_start_expression',item->'start_expression','legacy_end_expression',item->'end_expression');
    if refs<>'[]' and exists(select 1 from pg_catalog.jsonb_array_elements(refs) r where pg_catalog.strpos(r->>'quote',expression)>0) then
      years:=pg_catalog.regexp_match(expression,'(^|[^0-9])([0-9]{4})([^0-9]|$)');
      if years is not null and precision<>'unknown' and precision<>'age' then timing:=timing || pg_catalog.jsonb_build_object('year_start',years[2]::integer,'year_end',years[2]::integer); end if;
    end if;
    stage:='unplaced';
    select coalesce(pg_catalog.jsonb_agg(id),'[]') into person_ids from pg_catalog.jsonb_array_elements_text(coalesce(item->'person_ids','[]')) id
      where exists(select 1 from public.user_family_context f,pg_catalog.jsonb_array_elements(coalesce(f.document->'people','[]')) p
        where f.user_id=owner_id and f.project_id=p_project_id and p->>'id'=id);
    select coalesce(pg_catalog.jsonb_agg(id),'[]') into missing_person_ids from pg_catalog.jsonb_array_elements_text(coalesce(item->'person_ids','[]')) id
      where not exists(select 1 from pg_catalog.jsonb_array_elements_text(person_ids) p where p=id);
    update public.user_memoir_project set event_sequence=event_sequence+1 where user_id=owner_id and project_id=p_project_id returning event_sequence into next_change;
    insert into public.user_memory_event(user_id,project_id,id,revision,kind,life_stage,status,data,change_sequence)
      values(owner_id,p_project_id,event_id,greatest(coalesce((item->>'revision')::bigint,1),1),
        case when item->>'kind'='period' then 'period' else 'event' end,stage,
        case when refs='[]' or candidates<>'[]' then 'unresolved' else 'active' end,
        pg_catalog.jsonb_build_object('title',coalesce(item->>'title',item->>'summary'),'temporal',timing,
          'visibility',coalesce(item->>'visibility','private'),'include_in_print',coalesce((item->>'include_in_print')::boolean,false),
          'person_ids',person_ids,'unresolved_person_ids',missing_person_ids,'uncertainty',item->'uncertainty','candidate_ids',candidates,
          'provenance_status',case when candidates<>'[]' then 'legacy_identity_unresolved' when refs='[]' then 'legacy_evidence_unavailable' else 'legacy_original_recovered' end),next_change);
    insert into public.user_memory_event_alias values(owner_id,p_project_id,p_namespace,item->>'id',event_id);
    for ref in select value from pg_catalog.jsonb_array_elements(refs) loop
      insert into public.user_memory_event_source values(owner_id,p_project_id,event_id,(ref->>'source_id')::uuid,(ref->>'version')::bigint,pg_catalog.md5(ref::text),ref) on conflict do nothing;
    end loop;
    insert into public.user_memory_event_revision(user_id,project_id,event_id,revision,record,actor,origin)
      select owner_id,p_project_id,event_id,e.revision,public.memory_event_record(e),'migration',p_namespace from public.user_memory_event e
        where user_id=owner_id and project_id=p_project_id and id=event_id;
    result:=result || pg_catalog.jsonb_build_object(item->>'id',event_id);
  end loop;
  return result;
end $$;
revoke all on function public.import_legacy_memory_events(text,text,jsonb) from public,anon,authenticated;

create or replace function public.migrate_user_memory_events(p_project_id text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare owner_id uuid:=auth.uid(); memory public.user_memory%rowtype; original_text text; source jsonb; document jsonb; id_map jsonb;
begin
  if owner_id is null then raise exception 'authenticated user required' using errcode='42501'; end if;
  insert into public.user_memoir_project(user_id,project_id) values(owner_id,p_project_id) on conflict do nothing;
  perform 1 from public.user_memoir_project where user_id=owner_id and project_id=p_project_id for update;
  select f.document into document from public.user_family_context f where user_id=owner_id and project_id=p_project_id;
  for memory in select * from public.user_memory where user_id=owner_id and kind='agent' and
      (project_id=p_project_id or (project_id is null and id::text in(select pg_catalog.jsonb_array_elements_text(coalesce(document->'source_memory_ids','[]'))))) order by created_at,id loop
    if memory.content not like 'Storyteller: %' then continue; end if;
    original_text:=pg_catalog.regexp_replace(pg_catalog.substr(memory.content,14),E'\\nMemory Spark:[\\s\\S]*$','');
    if length(pg_catalog.btrim(original_text))=0 then continue; end if;
    select public.narrator_source_record(s) into source from public.user_narrator_source s where
      user_id=owner_id and project_id=p_project_id and client_turn_id=coalesce(memory.client_turn_id,memory.id);
    if not found then
      source:=public.accept_user_narrator_source(p_project_id,coalesce(memory.client_turn_id,memory.id),original_text,'narrator_chat',case when original_text ~ '[一-鿿]' then 'zh-CN' else 'en-AU' end);
    end if;
    insert into public.user_narrator_source_alias values(owner_id,p_project_id,memory.id::text,(source->>'id')::uuid) on conflict do nothing;
  end loop;
  id_map:=public.import_legacy_memory_events(p_project_id,'timeline',coalesce(document->'timeline','[]'));
  return pg_catalog.jsonb_build_object('event_id_map',id_map);
end $$;
revoke all on function public.migrate_user_memory_events(text) from public,anon;
grant execute on function public.migrate_user_memory_events(text) to authenticated;

-- Backfill existing authorised scopes once; replay follows stable aliases.
do $$
declare scope record;
begin
  for scope in select user_id,project_id from public.user_family_context where project_id ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$'
      union select user_id,project_id from public.user_memory where project_id is not null loop
    perform pg_catalog.set_config('request.jwt.claim.sub',scope.user_id::text,true);
    perform public.migrate_user_memory_events(scope.project_id);
  end loop;
  perform pg_catalog.set_config('request.jwt.claim.sub','',true);
end $$;

create or replace function public.migrate_user_memoir_index(p_project_id text,p_events jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare result jsonb; source_map jsonb; view jsonb;
begin
  perform public.migrate_user_memory_events(p_project_id);
  result:=public.import_legacy_memory_events(p_project_id,'composer',p_events);
  select coalesce(pg_catalog.jsonb_object_agg(legacy_id,source_id),'{}') into source_map
    from public.user_narrator_source_alias where user_id=auth.uid() and project_id=p_project_id;
  view:=public.read_user_memory_events(p_project_id);
  return view || pg_catalog.jsonb_build_object('event_id_map',result,'source_id_map',source_map);
end $$;
revoke all on function public.migrate_user_memoir_index(text,jsonb) from public,anon;
grant execute on function public.migrate_user_memoir_index(text,jsonb) to authenticated;

create or replace function public.import_user_legacy_memoir(p_project_id text,p_locale text,p_revision bigint,
  p_covered_round bigint,p_human_locked boolean,p_bundle jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare owner_id uuid:=auth.uid(); section jsonb; sections jsonb:='[]'; manifest jsonb;
begin
  if owner_id is null then raise exception 'authenticated user required' using errcode='42501'; end if;
  perform 1 from public.user_memoir_project where user_id=owner_id and project_id=p_project_id for update;
  if exists(select 1 from public.user_memoir_manuscript where user_id=owner_id and project_id=p_project_id) then
    return pg_catalog.jsonb_build_object('imported',false);
  end if;
  if p_locale not in ('en-AU','zh-CN') or p_revision<1 or p_covered_round<1 or
      p_covered_round>(select count(*) from public.user_completed_round where user_id=owner_id and project_id=p_project_id) or
      (p_bundle->'validation'->>'ok')::boolean is distinct from true or
      (p_bundle->'review'->>'ready_for_user_review')::boolean is distinct from true or
      (p_bundle->'review'->>'publication_approved')::boolean is distinct from false or
      p_bundle->'request'->>'project_id' is distinct from p_project_id or
      p_bundle->'preview'->>'locale' is distinct from p_locale or
      exists(select 1 from pg_catalog.jsonb_array_elements(p_bundle->'review'->'findings') f where f->>'severity'='blocking') then
    raise exception 'legacy manuscript requires review' using errcode='22023';
  end if;
  if exists(select 1 from pg_catalog.jsonb_array_elements(p_bundle->'source_manifest') ref left join public.user_narrator_source s
      on s.user_id=owner_id and s.project_id=p_project_id and s.id::text=ref->>'id'
      where s.id is null or s.status<>'active' or s.version is distinct from (ref->>'version')::bigint) or
     exists(select 1 from pg_catalog.jsonb_array_elements(p_bundle->'event_manifest') ref left join public.user_memory_event e
      on e.user_id=owner_id and e.project_id=p_project_id and e.id=ref->>'id'
      where e.id is null or e.status<>'active' or e.revision is distinct from (ref->>'revision')::bigint) then
    raise exception 'legacy manuscript references unavailable evidence' using errcode='42501';
  end if;
  for section in select value from pg_catalog.jsonb_array_elements(p_bundle->'sections') loop
    if exists(select 1 from pg_catalog.jsonb_array_elements_text(section->'event_ids') id
        where not exists(select 1 from pg_catalog.jsonb_array_elements(p_bundle->'event_manifest') e where e->>'id'=id)) then
      raise exception 'legacy section references unavailable event' using errcode='42501'; end if;
    section:=section || pg_catalog.jsonb_build_object('revision',coalesce((section->>'revision')::bigint,1));
    select coalesce(pg_catalog.jsonb_agg(e),'[]') into manifest from pg_catalog.jsonb_array_elements(p_bundle->'event_manifest') e
      where e->>'id' in(select pg_catalog.jsonb_array_elements_text(section->'event_ids'));
    insert into public.user_memoir_section_revision values(owner_id,p_project_id,p_locale,section->>'id',
      (section->>'revision')::bigint,section->>'fingerprint',section,manifest);
    sections:=sections || pg_catalog.jsonb_build_array(section);
  end loop;
  p_bundle:=pg_catalog.jsonb_set(p_bundle,'{sections}',sections);
  insert into public.user_memoir_manuscript(user_id,project_id,locale,revision,covered_round,completed_milestone,bundle,human_locked)
    values(owner_id,p_project_id,p_locale,p_revision,p_covered_round,p_covered_round,p_bundle,p_human_locked);
  insert into public.user_memoir_milestone(user_id,project_id,locale,milestone,state,covered_round,manuscript_revision)
    values(owner_id,p_project_id,p_locale,p_covered_round,'completed',p_covered_round,p_revision)
    on conflict(user_id,project_id,locale,milestone) do update set
      state='completed',covered_round=excluded.covered_round,manuscript_revision=excluded.manuscript_revision;
  return pg_catalog.jsonb_build_object('imported',true);
end $$;
revoke all on function public.import_user_legacy_memoir(text,text,bigint,bigint,boolean,jsonb) from public,anon;
grant execute on function public.import_user_legacy_memoir(text,text,bigint,bigint,boolean,jsonb) to authenticated;

-- Extend the established capability transfer, retaining its immutable snapshot
-- authority. Rename only once so replay never wraps the wrapper recursively.
do $$ begin
  if pg_catalog.to_regprocedure('public.prepare_guest_conversation_before_memory_events(text,text,jsonb,jsonb,text)') is null then
    alter function public.prepare_guest_conversation_transfer(text,text,jsonb,jsonb,text) rename to prepare_guest_conversation_before_memory_events;
  end if;
  if pg_catalog.to_regprocedure('public.attach_guest_conversation_before_memory_events(text,boolean)') is null then
    alter function public.attach_guest_conversation(text,boolean) rename to attach_guest_conversation_before_memory_events;
  end if;
end $$;
revoke all on function public.prepare_guest_conversation_before_memory_events(text,text,jsonb,jsonb,text) from public,anon,authenticated;
revoke all on function public.attach_guest_conversation_before_memory_events(text,boolean) from public,anon,authenticated;

create or replace function public.prepare_guest_conversation_transfer(p_token text,p_project_id text,p_messages jsonb,
  p_workspace_profile jsonb default '{}',p_ui_locale text default null) returns jsonb
language plpgsql security definer set search_path='' as $$
declare result jsonb; project public.user_memoir_project%rowtype; snapshot jsonb:='{}'; rows jsonb; table_name text;
begin
  result:=public.prepare_guest_conversation_before_memory_events(p_token,p_project_id,p_messages,p_workspace_profile,p_ui_locale);
  select * into project from public.user_memoir_project where user_id=auth.uid() and project_id=p_project_id for update;
  if found then
    snapshot:=pg_catalog.jsonb_build_object('project',pg_catalog.to_jsonb(project));
    foreach table_name in array array['user_narrator_source','user_narrator_source_version','user_memory_event','user_memory_event_source',
      'user_memory_event_source_exclusion','user_memory_event_revision','user_memory_event_change','user_memory_event_alias','user_narrator_source_alias',
      'user_memoir_manuscript','user_memoir_section_revision','user_memoir_milestone','user_memoir_lane'] loop
      execute pg_catalog.format('select coalesce(jsonb_agg(to_jsonb(t)),''[]''::jsonb) from public.%I t where user_id=$1 and project_id=$2',table_name)
        into rows using auth.uid(),p_project_id;
      snapshot:=snapshot || pg_catalog.jsonb_build_object(table_name,rows);
    end loop;
  end if;
  update public.guest_conversation_transfer set workspace=workspace || pg_catalog.jsonb_build_object('shared_memoir',snapshot)
    where token_hash=pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p_token,'UTF8')),'hex') and guest_user_id=auth.uid() and target_user_id is null;
  return result;
end $$;
revoke all on function public.prepare_guest_conversation_transfer(text,text,jsonb,jsonb,text) from public,anon;
grant execute on function public.prepare_guest_conversation_transfer(text,text,jsonb,jsonb,text) to authenticated;

create table if not exists public.user_shared_memoir_transfer (
  conversation_id uuid primary key references public.user_conversation_attachment(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade, project_id text not null,
  event_id_map jsonb not null, source_id_map jsonb not null
);
alter table public.user_shared_memoir_transfer enable row level security;
revoke all on public.user_shared_memoir_transfer from public,anon,authenticated;

create or replace function public.attach_guest_conversation(p_token text,p_guest_wins boolean default false) returns jsonb
language plpgsql security definer set search_path='' as $$
declare result jsonb; attachment public.user_conversation_attachment%rowtype; snapshot jsonb; original jsonb; table_name text;
  project public.user_memoir_project%rowtype; owner_id uuid:=auth.uid(); event_map jsonb; source_map jsonb;
begin
  result:=public.attach_guest_conversation_before_memory_events(p_token,p_guest_wins);
  select * into attachment from public.user_conversation_attachment where user_id=owner_id and id=(result->>'conversation_id')::uuid;
  if exists(select 1 from public.user_shared_memoir_transfer where conversation_id=attachment.id and user_id=owner_id) then return result; end if;
  snapshot:=attachment.workspace->'shared_memoir';
  if snapshot->'project' is null then return result; end if;
  select * into project from public.user_memoir_project where user_id=(result->>'guest_user_id')::uuid and project_id=attachment.project_id for update;
  if not found or project.source_sequence is distinct from (snapshot->'project'->>'source_sequence')::bigint or
    project.event_sequence is distinct from (snapshot->'project'->>'event_sequence')::bigint or project.policy_epoch is distinct from (snapshot->'project'->>'policy_epoch')::bigint then
    raise exception 'guest evidence changed; prepare a new transfer' using errcode='40001'; end if;
  if exists(select 1 from public.user_memoir_project where user_id=owner_id and project_id=attachment.project_id) then
    raise exception 'project transfer conflict; retain both authorised projects' using errcode='40001'; end if;
  insert into public.user_memoir_project select (pg_catalog.jsonb_populate_record(null::public.user_memoir_project,snapshot->'project' || pg_catalog.jsonb_build_object('user_id',owner_id))).*;
  foreach table_name in array array['user_narrator_source','user_narrator_source_version','user_memory_event','user_memory_event_source',
    'user_memory_event_source_exclusion','user_memory_event_revision','user_memory_event_change','user_memory_event_alias','user_narrator_source_alias',
    'user_memoir_manuscript','user_memoir_section_revision','user_memoir_milestone','user_memoir_lane'] loop
    for original in select value from pg_catalog.jsonb_array_elements(snapshot->table_name) loop
      if original->>'user_id' is distinct from result->>'guest_user_id' or original->>'project_id' is distinct from attachment.project_id then
        raise exception 'invalid transfer scope' using errcode='42501'; end if;
      original:=original || pg_catalog.jsonb_build_object('user_id',owner_id);
      if table_name='user_memoir_lane' then
        original:=original || pg_catalog.jsonb_build_object('id',pg_catalog.gen_random_uuid(),'token',null,'lease_until',null,'run_deadline',null,
          'active_manifest','[]'::jsonb,'active_events','[]'::jsonb,'pending',coalesce((original->>'pending')::boolean,false) or original->'token'<>'null'::jsonb);
      end if;
      execute pg_catalog.format('insert into public.%I select (jsonb_populate_record(null::public.%I,$1)).* on conflict do nothing',table_name,table_name) using original;
    end loop;
  end loop;
  select coalesce(pg_catalog.jsonb_object_agg(e->>'id',e->>'id'),'{}') into event_map from pg_catalog.jsonb_array_elements(snapshot->'user_memory_event') e;
  select coalesce(pg_catalog.jsonb_object_agg(s->>'id',s->>'id'),'{}') into source_map from pg_catalog.jsonb_array_elements(snapshot->'user_narrator_source') s;
  insert into public.user_shared_memoir_transfer values(attachment.id,owner_id,attachment.project_id,event_map,source_map);
  return result;
end $$;
revoke all on function public.attach_guest_conversation(text,boolean) from public,anon;
grant execute on function public.attach_guest_conversation(text,boolean) to authenticated;

create or replace function public.synchronize_narrator_memory_change() returns trigger
language plpgsql security definer set search_path='' as $$
declare source public.user_narrator_source%rowtype; original_text text; previous_owner text;
begin
  if pg_catalog.current_setting('memoir.sync_source',true)='true' or old.kind<>'agent' or old.project_id is null then return null; end if;
  if TG_OP='UPDATE' and old.content is not distinct from new.content then return null; end if;
  select * into source from public.user_narrator_source where user_id=old.user_id and project_id=old.project_id and
    (client_turn_id=coalesce(old.client_turn_id,old.id) or id in(select source_id from public.user_narrator_source_alias
      where user_id=old.user_id and project_id=old.project_id and legacy_id=old.id::text));
  if not found or source.status<>'active' then return null; end if;
  previous_owner:=pg_catalog.current_setting('request.jwt.claim.sub',true);
  perform pg_catalog.set_config('request.jwt.claim.sub',old.user_id::text,true);
  if TG_OP='DELETE' or new.content not like 'Storyteller: %' or
     (TG_OP='UPDATE' and new.project_id is distinct from old.project_id) then
    perform public.change_user_narrator_source(old.project_id,source.id,source.version,'withdraw');
  else
    original_text:=pg_catalog.regexp_replace(pg_catalog.substr(new.content,14),E'\\nMemory Spark:[\\s\\S]*$','');
    if pg_catalog.btrim(original_text)='' then
      perform public.change_user_narrator_source(old.project_id,source.id,source.version,'withdraw');
    elsif original_text is distinct from source.text then
      perform public.change_user_narrator_source(old.project_id,source.id,source.version,'edit',original_text);
    end if;
  end if;
  perform pg_catalog.set_config('request.jwt.claim.sub',coalesce(previous_owner,''),true);
  return null;
end $$;
revoke all on function public.synchronize_narrator_memory_change() from public,anon,authenticated;
drop trigger if exists synchronize_narrator_memory_change on public.user_memory;
create trigger synchronize_narrator_memory_change after update or delete on public.user_memory
  for each row execute function public.synchronize_narrator_memory_change();

commit;
