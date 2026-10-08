-- Settle empty canonical checkpoints without generating prose or retrying.
begin;

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
  if p_bundle->>'status'='insufficient_context' then
    -- No supported canonical partition is a settled checkpoint, not a provider
    -- failure. Recheck that evidence has not appeared since the claim.
    if exists(select 1 from public.user_memory_event e where e.user_id=lane.user_id and e.project_id=lane.project_id
        and e.status='active' and exists(select 1 from public.user_memory_event_source r
          join public.user_narrator_source s on s.user_id=r.user_id and s.project_id=r.project_id and s.id=r.source_id
          where r.user_id=e.user_id and r.project_id=e.project_id and r.event_id=e.id
            and s.status='active' and s.version=r.source_version)) then
      return pg_catalog.jsonb_build_object('status','rejected');
    end if;
  elsif (p_bundle->'validation'->>'ok')::boolean is distinct from true or
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
  if p_bundle->>'status'='insufficient_context' then
    update public.user_memoir_manuscript set bundle=null,reuse=null,proposal=null,eligible=true,
      covered_round=lane.active_round,source_sequence=lane.active_through,
      event_sequence=lane.active_event,completed_milestone=lane.active_milestone
      where user_id=lane.user_id and project_id=lane.project_id and locale=lane.active_locale;
  elsif coalesce((p_bundle->>'unchanged')::boolean,false) then
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
  update public.user_memoir_milestone set state=case when manuscript.human_locked and p_bundle->>'status' is distinct from 'insufficient_context' then 'proposed' else 'completed' end,
    covered_round=lane.active_round,manuscript_revision=manuscript.revision+
      case when manuscript.human_locked or p_bundle->>'status'='insufficient_context' or coalesce((p_bundle->>'unchanged')::boolean,false) then 0 else 1 end
    where user_id=lane.user_id and project_id=lane.project_id and locale=lane.active_locale and
      milestone<=lane.active_milestone and state='pending';
  update public.user_memoir_lane set token=null,lease_until=null,run_deadline=null,active_manifest='[]',active_events='[]',
    successful_source=active_through,successful_event=active_event,successful_round=active_round,attempts=0,error=null
    where id=p_lane_id;
  return pg_catalog.jsonb_build_object('status',case when manuscript.human_locked and p_bundle->>'status' is distinct from 'insufficient_context' then 'proposed' else 'saved' end);
end $$;
revoke all on function public.finish_memoir_composer(uuid,uuid,bigint,jsonb) from public,anon,authenticated;
grant execute on function public.finish_memoir_composer(uuid,uuid,bigint,jsonb) to service_role;

commit;
