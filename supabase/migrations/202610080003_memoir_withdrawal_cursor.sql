-- Composer coverage includes source changes whose originals were withdrawn.
-- Active source manifests still contain only authorised surviving evidence.
begin;

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
    active_through=case when lane.skill='composer' then project.source_sequence else coalesce(last_sequence,project.source_sequence) end,active_event=project.event_sequence,active_round=coalesce(completed_round,0),
    active_policy=project.policy_epoch,active_events=event_manifest,active_milestone=lane.target_milestone,active_locale=lane.locale,
    active_manuscript_revision=coalesce((select revision from public.user_memoir_manuscript where user_id=lane.user_id and project_id=lane.project_id and locale=lane.locale),0),
    attempts=attempts+1,error=null
    where id=p_lane_id;
  return pg_catalog.jsonb_build_object('lane_id',p_lane_id,'token',run_token,'skill',lane.skill,
    'user_id',lane.user_id,'project_id',lane.project_id,'locale',lane.locale,
    'from_sequence',case when lane.skill='composer' then lane.successful_source+1 else first_sequence end,
    'through_sequence',case when lane.skill='composer' then project.source_sequence else coalesce(last_sequence,project.source_sequence) end,'coverage_round',coalesce(completed_round,0),
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

commit;
