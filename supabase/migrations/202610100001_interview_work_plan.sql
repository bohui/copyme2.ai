-- Keep the model-selected work plan with the saved reply for idempotent retries.
-- Existing plans without work retain normal extraction; RPC identity and grants stay the same.
begin;

create or replace function public.save_user_interview_plan(p_project_id text,p_client_turn_id uuid,p_plan jsonb,p_associations jsonb,p_lease_token uuid,
  p_reply text default null,p_response_photo_ids jsonb default '[]',p_thread_id text default null)
returns jsonb language plpgsql security definer set search_path='' as $$
declare v_owner uuid:=auth.uid(); project public.user_memoir_project%rowtype; turn public.user_interview_turn%rowtype;
  candidate jsonb; context jsonb; proposal jsonb; evidence jsonb; current_source public.user_narrator_source%rowtype;
  inserted integer; changed boolean:=false; response_cards jsonb:='[]'; photo_identifier text;
begin
  if v_owner is null then raise exception 'authenticated user required' using errcode='42501'; end if;
  select * into project from public.user_memoir_project where user_id=v_owner and project_id=p_project_id for update;
  perform 1 from public.user_agent_turn_lease where user_id=v_owner and lease_token=p_lease_token and expires_at>clock_timestamp() for update;
  if not found then raise exception 'agent turn lease lost' using errcode='40001'; end if;
  select * into turn from public.user_interview_turn where user_id=v_owner and project_id=p_project_id and client_turn_id=p_client_turn_id;
  if not found or turn.sequence is distinct from project.interview_sequence or turn.source_sequence is distinct from project.source_sequence or
    turn.policy_epoch is distinct from project.policy_epoch then raise exception 'stale interview turn' using errcode='40001'; end if;
  if turn.source_id is not null and not exists(select 1 from public.user_narrator_source where user_id=v_owner and project_id=p_project_id
      and id=turn.source_id and version=turn.source_version and status='active') then raise exception 'stale interview turn' using errcode='40001'; end if;
  if turn.collector is not null then
    return public.interview_turn_record(turn) || public.read_user_interview_context(p_project_id);
  end if;
  if p_reply is not null and (length(btrim(p_reply)) not between 1 and 100000 or length(coalesce(p_thread_id,'')) not between 1 and 1000) then
    raise exception 'invalid saved collector reply' using errcode='22023'; end if;
  if jsonb_typeof(p_response_photo_ids) is distinct from 'array' or jsonb_array_length(p_response_photo_ids)>5 then
    raise exception 'invalid response photo selection' using errcode='22023'; end if;
  for photo_identifier in select distinct value from jsonb_array_elements_text(p_response_photo_ids) loop
    if not public.interview_photo_available(v_owner,p_project_id,photo_identifier) then
      raise exception 'response photo unavailable' using errcode='42501'; end if;
    response_cards:=response_cards || (select jsonb_build_array(p) from public.user_interview_turn t,
      jsonb_array_elements(t.photo_context) p where t.user_id=v_owner and t.project_id=p_project_id and p->>'photo_id'=photo_identifier
      order by t.sequence desc limit 1);
  end loop;
  if jsonb_typeof(p_plan) is distinct from 'object' or octet_length(p_plan::text)>32000 or
    jsonb_typeof(p_plan->'candidates') is distinct from 'array' or jsonb_array_length(p_plan->'candidates')>5 or
    exists(select 1 from jsonb_object_keys(p_plan) k where k not in ('candidates','chosen_id','active_event_id','work')) or
    jsonb_typeof(p_associations) is distinct from 'array' or jsonb_array_length(p_associations)>20 or
    octet_length(p_associations::text)>32000 then raise exception 'invalid interview plan' using errcode='22023'; end if;
  if p_plan ? 'work' then
    if jsonb_typeof(p_plan->'work') is distinct from 'object' or
      (p_plan->'work'->>'mode') is null or (p_plan->'work'->>'mode') not in ('reply_only','extract') or
      exists(select 1 from jsonb_object_keys(p_plan->'work') k where k not in ('mode','name')) or
      not (p_plan->'work' ? 'name') or jsonb_typeof(p_plan->'work'->'name') not in ('string','null') or
      length(coalesce(p_plan->'work'->>'name',''))>120 then
      raise exception 'invalid interview work plan' using errcode='22023'; end if;
    if p_plan->'work'->>'mode'='reply_only' then
      -- Prior narrator history determines opening_turn in collector validation.
      -- A project's first turn can belong to a returning storyteller.
      if jsonb_array_length(p_associations)>0 or jsonb_array_length(p_response_photo_ids)>0 or
        jsonb_array_length(turn.photo_context)>0 then
        raise exception 'reply-only work cannot discard accepted photo context' using errcode='22023'; end if;
      if p_plan->'work'->>'name' is not null then
        select * into current_source from public.user_narrator_source where user_id=v_owner and project_id=p_project_id
          and id=turn.source_id and version=turn.source_version and status='active';
        if not found or length(btrim(p_plan->'work'->>'name'))=0 or
          position((p_plan->'work'->>'name') in current_source.text)=0 then
          raise exception 'opening name requires exact narrator wording' using errcode='22023'; end if;
      end if;
    elsif p_plan->'work'->>'name' is not null then
      raise exception 'story profile clues belong to normal extraction' using errcode='22023'; end if;
  end if;

  if (select count(*)<>count(distinct c->>'id') from jsonb_array_elements(p_plan->'candidates') c) or
    (jsonb_array_length(p_plan->'candidates')>0 and not exists(select 1 from jsonb_array_elements(p_plan->'candidates') c where c->>'id'=p_plan->>'chosen_id')) or
    (jsonb_array_length(p_plan->'candidates')=0 and p_plan->>'chosen_id' is not null) then
    raise exception 'invalid interview plan selection' using errcode='22023'; end if;
  if p_plan->>'active_event_id' is not null and not exists(select 1 from public.user_memory_event
    where user_id=v_owner and project_id=p_project_id and id=p_plan->>'active_event_id' and status='active') then
    raise exception 'active event unavailable' using errcode='42501'; end if;
  for candidate in select value from jsonb_array_elements(p_plan->'candidates') loop
    context:=coalesce(candidate->'context','{}');
    if jsonb_typeof(candidate) is distinct from 'object' or
      jsonb_typeof(candidate->'order') is distinct from 'number' or
      jsonb_typeof(candidate->'question') is distinct from 'string' or
      exists(select 1 from jsonb_object_keys(candidate) k where k not in ('id','question','context','order','bridge')) or length(coalesce(candidate->>'id','')) not between 1 and 128 or
      length(btrim(coalesce(candidate->>'question',''))) not between 1 and 2000 or jsonb_typeof(context) is distinct from 'object' or
      length(coalesce(candidate->>'bridge',''))>2000 or
      exists(select 1 from jsonb_object_keys(context) k where k not in ('event_id','photo_id','life_stage','year')) or (candidate->>'order')::integer not between 0 and 100 then
      raise exception 'invalid interview plan candidate' using errcode='22023'; end if;
    if context->>'event_id' is not null and not exists(select 1 from public.user_memory_event
      where user_id=v_owner and project_id=p_project_id and id=context->>'event_id' and status='active') then
      raise exception 'candidate event unavailable' using errcode='42501'; end if;
    if context->>'life_stage' is not null and not exists(select 1 from public.user_memory_event e where
      e.user_id=v_owner and e.project_id=p_project_id and e.status='active' and e.life_stage=context->>'life_stage') then
      raise exception 'unsupported candidate life stage' using errcode='22023'; end if;
    if context->>'year' is not null and not (
      exists(select 1 from public.user_memory_event e where e.user_id=v_owner and e.project_id=p_project_id and e.status='active'
        and (e.data->'temporal'->>'year_start'=context->>'year' or e.data->'temporal'->>'year_end'=context->>'year'))) then
      raise exception 'unsupported candidate year' using errcode='22023'; end if;
    if context->>'photo_id' is not null and not public.interview_photo_available(v_owner,p_project_id,context->>'photo_id') then
      raise exception 'candidate photo unavailable' using errcode='42501'; end if;
  end loop;
  for proposal in select value from jsonb_array_elements(p_associations) loop
    if turn.source_id is null or proposal->>'source_id' is distinct from turn.source_id::text or
      (proposal->>'source_version')::bigint is distinct from turn.source_version then
      raise exception 'photo evidence must belong to this accepted source' using errcode='42501'; end if;
    if not public.interview_photo_available(v_owner,p_project_id,proposal->>'photo_id') then
      raise exception 'photo unavailable' using errcode='42501'; end if;
    -- A deferred cue may gain its FIRST link from a later accepted source.
    -- Cue authority is scoped, lifecycle-current and fenced by any explicit
    -- unlink. Uploading alone or retaining a withdrawn snapshot is not enough.
    if not public.interview_photo_available(v_owner,p_project_id,proposal->>'photo_id',true) and
      not exists(select 1 from public.user_interview_photo_link l join public.user_narrator_source original
        on original.user_id=l.user_id and original.project_id=l.project_id and original.id=l.source_id
        where l.user_id=v_owner and l.project_id=p_project_id and l.photo_id=proposal->>'photo_id'
          and l.status='confirmed' and l.event_id=proposal->>'event_id'
          and original.status='active' and original.version=l.source_version) then
      raise exception 'photo is not accepted or supported active event context' using errcode='42501'; end if;
    evidence:=jsonb_build_object('source_id',proposal->>'source_id','version',proposal->'source_version','quote',proposal->>'quote');
    perform public.validate_memory_evidence(v_owner,p_project_id,evidence);
    if proposal->>'event_id' is not null and not exists(select 1 from public.user_memory_event where user_id=v_owner and project_id=p_project_id
      and id=proposal->>'event_id' and status='active') then raise exception 'photo event unavailable' using errcode='42501'; end if;
    -- visual_derived requires a future verified image-inspection path. Current
    -- collector sees metadata, never pixels: fail closed on claimed sight.
    if proposal->>'provenance' is null or proposal->>'provenance' not in ('narrator','narrator_metadata') then
      raise exception 'unsupported photo description provenance' using errcode='22023'; end if;
    insert into public.user_interview_photo_link(user_id,project_id,photo_id,intended_event_id,source_id,source_version,quote,description,provenance)
      values(v_owner,p_project_id,proposal->>'photo_id',proposal->>'event_id',turn.source_id,turn.source_version,
        proposal->>'quote',proposal->>'description',proposal->>'provenance') on conflict do nothing;
    get diagnostics inserted=row_count; changed:=changed or inserted>0;
  end loop;
  if changed then perform public.invalidate_interview_photo_projection(v_owner,p_project_id,false); end if;
  perform public.reconcile_interview_photo_links(v_owner,p_project_id);
  insert into public.user_interview_plan(user_id,project_id,client_turn_id,sequence,plan)
    values(v_owner,p_project_id,p_client_turn_id,turn.sequence,p_plan)
    on conflict(user_id,project_id) do update set client_turn_id=excluded.client_turn_id,sequence=excluded.sequence,
      revision=public.user_interview_plan.revision+1,plan=excluded.plan;
  update public.user_interview_turn set collector=case when p_reply is null then null else jsonb_build_object(
    'plan',p_plan,'reply',p_reply,'thread_id',p_thread_id,'response_photos',response_cards) end, policy_epoch=(select policy_epoch from public.user_memoir_project where user_id=v_owner and project_id=p_project_id)
    where user_id=v_owner and project_id=p_project_id and client_turn_id=p_client_turn_id;
  if not exists(select 1 from public.user_agent_turn_lease where user_id=v_owner and lease_token=p_lease_token and expires_at>clock_timestamp()) then
    raise exception 'agent turn lease lost' using errcode='40001'; end if;
  return public.read_user_interview_turn(p_project_id,p_client_turn_id) || public.read_user_interview_context(p_project_id);
end $$;

commit;
