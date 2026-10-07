-- Preserve event and section revisions when extraction repeats unchanged facts.
-- Additive replacement; existing installations keep their canonical records.
begin;

create or replace function public.apply_user_memory_events(p_project_id text,p_sources jsonb,p_events jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare owner_id uuid:=auth.uid(); item jsonb; saved public.user_narrator_source%rowtype; updated integer;
  proposal jsonb; ref jsonb; relation jsonb; evidence public.user_narrator_source%rowtype;
  current_event public.user_memory_event%rowtype; event_id text; event_data jsonb; event_refs jsonb; event_stage text; next_change bigint;
begin
  if owner_id is null then raise exception 'authenticated user required' using errcode='42501'; end if;
  if pg_catalog.jsonb_typeof(p_sources) is distinct from 'array' or pg_catalog.jsonb_array_length(p_sources) not between 1 and 1000 or
     pg_catalog.jsonb_typeof(p_events) is distinct from 'array' or pg_catalog.jsonb_array_length(p_events)>100 then
    raise exception 'invalid extraction result' using errcode='22023';
  end if;
  perform 1 from public.user_memoir_project where user_id=owner_id and project_id=p_project_id for update;
  if not found then raise exception 'project unavailable' using errcode='42501'; end if;
  for item in select value from pg_catalog.jsonb_array_elements(p_sources) loop
    select * into saved from public.user_narrator_source where user_id=owner_id and project_id=p_project_id and id=(item->>'id')::uuid;
    if not found then raise exception 'source unavailable' using errcode='42501'; end if;
    if saved.version is distinct from (item->>'version')::bigint or saved.status<>'active' then
      raise exception 'source revision conflict' using errcode='40001';
    end if;
  end loop;
  -- Replayed successful inputs cannot create a second set of identities.
  if not exists(select 1 from public.user_narrator_source where user_id=owner_id and project_id=p_project_id
    and processing_status<>'succeeded' and id in(select (value->>'id')::uuid from pg_catalog.jsonb_array_elements(p_sources))) then
    return public.read_user_memory_events(p_project_id);
  end if;
  for proposal in select value from pg_catalog.jsonb_array_elements(p_events) loop
    if pg_catalog.jsonb_typeof(proposal) is distinct from 'object' or
       exists(select 1 from pg_catalog.jsonb_object_keys(proposal) k where k not in
         ('id','existing_id','expected_revision','kind','title','life_stage','temporal','stage_evidence','source_refs','uncertainty','person_ids','visibility','include_in_print','attribution','candidate_ids','relations','correction')) or
       proposal->>'kind' not in ('event','period') or
       length(pg_catalog.btrim(coalesce(proposal->>'title',''))) not between 1 and 300 or
       pg_catalog.jsonb_typeof(proposal->'source_refs') is distinct from 'array' or
       pg_catalog.jsonb_array_length(proposal->'source_refs') not between 1 and 100 then
      raise exception 'invalid event proposal' using errcode='22023';
    end if;
    current_event:=null;
    if coalesce(pg_catalog.jsonb_array_length(proposal->'candidate_ids'),0)>0 and ((proposal ? 'existing_id') or exists(select 1 from pg_catalog.jsonb_array_elements_text(proposal->'candidate_ids') candidate
        where not exists(select 1 from public.user_memory_event where user_id=owner_id and project_id=p_project_id and id=candidate))) then
      raise exception 'ambiguous candidates must remain scoped and unresolved' using errcode='42501'; end if;
    if proposal ? 'person_ids' and exists(select 1 from pg_catalog.jsonb_array_elements_text(proposal->'person_ids') person_id
        where not exists(select 1 from public.user_family_context f,
          pg_catalog.jsonb_array_elements(coalesce(f.document->'people','[]')) person
          where f.user_id=owner_id and f.project_id=p_project_id and person->>'id'=person_id)) then
      raise exception 'person identity unavailable in this project' using errcode='42501'; end if;
    for relation in select value from pg_catalog.jsonb_array_elements(coalesce(proposal->'relations','[]')) loop
      if relation->>'kind' is null or relation->>'kind' not in ('before','after') or
         pg_catalog.jsonb_typeof(relation->'source_refs') is distinct from 'array' or pg_catalog.jsonb_array_length(relation->'source_refs')=0 or
         not exists(select 1 from public.user_memory_event where user_id=owner_id and project_id=p_project_id and id=relation->>'event_id') then
        raise exception 'chronology target unavailable in this project' using errcode='42501'; end if;
      for ref in select value from pg_catalog.jsonb_array_elements(relation->'source_refs') loop
        perform public.validate_memory_evidence(owner_id,p_project_id,ref);
      end loop;
    end loop;
    if proposal ? 'existing_id' then
      select * into current_event from public.user_memory_event
        where user_id=owner_id and project_id=p_project_id and id=proposal->>'existing_id' for update;
      if not found then raise exception 'event unavailable' using errcode='42501'; end if;
      if current_event.revision is distinct from (proposal->>'expected_revision')::bigint then
        raise exception 'event revision conflict' using errcode='40001';
      end if;
      if current_event.kind is distinct from proposal->>'kind' then
        raise exception 'event kind cannot change' using errcode='22023';
      end if;
      event_id:=current_event.id;
    else event_id:=pg_catalog.gen_random_uuid()::text;
    end if;
    if proposal ? 'correction' then
      ref:=proposal->'correction';
      perform public.validate_memory_evidence(owner_id,p_project_id,ref);
      select * into evidence from public.user_narrator_source where user_id=owner_id and project_id=p_project_id and id=(ref->>'source_id')::uuid;
      if current_event.id is null or evidence.text is distinct from ref->>'quote' or
         not exists(select 1 from pg_catalog.jsonb_array_elements(p_sources) s where s->>'id'=ref->>'source_id' and s->>'version'=ref->>'version') or
         evidence.text !~* '(correct|actually|year was|i meant|should be|更正|纠正|应该|其实|不是)' then
        raise exception 'chat correction requires explicit current original testimony' using errcode='22023'; end if;
      select coalesce(pg_catalog.jsonb_object_agg(key,value),'{}') into event_data from pg_catalog.jsonb_each(proposal)
        where key in ('life_stage','temporal');
      perform public.correct_user_memory_event(p_project_id,event_id,current_event.revision,event_data,evidence.text,'chat',evidence.id);
      continue;
    end if;
    event_stage:=coalesce(proposal->>'life_stage',current_event.life_stage,'unplaced');
    if event_stage not in ('baby','toddler','childhood','adolescence','young_adulthood','midlife','later_life','unplaced') then
      raise exception 'invalid life stage' using errcode='22023';
    end if;
    event_data:=(coalesce(current_event.data,'{"temporal":{"expression":"unknown","precision":"unknown"},"visibility":"private","include_in_print":false}'::jsonb)-'reconciliation_source_ids') ||
      (proposal - array['id','existing_id','expected_revision','source_refs','kind','life_stage']);
    if proposal ? 'temporal' and not (coalesce(current_event.data->'user_overrides','{}') ? 'temporal') and
       (coalesce((current_event.data->>'timing_conflict')::boolean,false) or
        (current_event.data->'temporal'->>'year_start' is not null and proposal->'temporal'->>'year_start' is not null and
         (current_event.data->'temporal'->>'year_start' is distinct from proposal->'temporal'->>'year_start' or
          current_event.data->'temporal'->>'year_end' is distinct from proposal->'temporal'->>'year_end'))) then
      event_data:=event_data || pg_catalog.jsonb_build_object('timing_conflict',true,
        'temporal_accounts',coalesce(current_event.data->'temporal_accounts',pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object('temporal',current_event.data->'temporal'))) ||
          pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object('temporal',proposal->'temporal')),
        'temporal',pg_catalog.jsonb_build_object('expression','unknown','precision','unknown',
          'basis',coalesce(current_event.data->'temporal'->'basis','[]') || coalesce(proposal->'temporal'->'basis','[]')));
    end if;
    if current_event.data->'user_overrides' ? 'life_stage' then event_stage:=current_event.life_stage; end if;
    if current_event.data->'user_overrides' ? 'temporal' then
      event_data:=pg_catalog.jsonb_set(event_data,'{temporal}',current_event.data->'temporal');
    end if;
    if coalesce(proposal->>'visibility','private')<>coalesce(current_event.data->>'visibility','private') or
       coalesce((proposal->>'include_in_print')::boolean,false)<>coalesce((current_event.data->>'include_in_print')::boolean,false) then
      if proposal ? 'visibility' or proposal ? 'include_in_print' then raise exception 'extraction cannot grant visibility or print rights' using errcode='42501'; end if;
    end if;
    event_data:=event_data || pg_catalog.jsonb_build_object('visibility',coalesce(current_event.data->>'visibility','private'),
      'include_in_print',coalesce((current_event.data->>'include_in_print')::boolean,false));
    perform public.validate_memory_temporal(owner_id,p_project_id,event_data->'temporal');
    for ref in select value from pg_catalog.jsonb_array_elements(coalesce(event_data->'stage_evidence','[]')) loop
      perform public.validate_memory_evidence(owner_id,p_project_id,ref);
    end loop;
    if pg_catalog.jsonb_typeof(event_data->'temporal') is distinct from 'object' or
       event_data->'temporal'->>'precision' not in ('unknown','day','month','year','range','approximate','age','season') or
       length(coalesce(event_data->'temporal'->>'expression','')) not between 1 and 500 then
      raise exception 'invalid temporal placement' using errcode='22023';
    end if;
    if event_stage<>'unplaced' and (pg_catalog.jsonb_typeof(event_data->'stage_evidence') is distinct from 'array' or pg_catalog.jsonb_array_length(event_data->'stage_evidence')=0) then
      raise exception 'life stage requires evidence' using errcode='22023';
    end if;
    -- Every retained fact is a dependency, even when a birth/stage/chronology
    -- statement is separate from the event's principal narrator statement.
    select coalesce(pg_catalog.jsonb_agg(value),'[]') into event_refs from (
      select value from pg_catalog.jsonb_array_elements(proposal->'source_refs')
      union select value from pg_catalog.jsonb_array_elements(coalesce(event_data->'temporal'->'basis','[]'))
      union select value from pg_catalog.jsonb_array_elements(coalesce(event_data->'stage_evidence','[]'))
      union select r.value from pg_catalog.jsonb_array_elements(coalesce(event_data->'relations','[]')) relation_ref,
        pg_catalog.jsonb_array_elements(relation_ref.value->'source_refs') r
      union select r.value from pg_catalog.jsonb_array_elements(coalesce(event_data->'temporal_accounts','[]')) account,
        pg_catalog.jsonb_array_elements(coalesce(account->'temporal'->'basis','[]')) r
    ) dependencies;
    for ref in select value from pg_catalog.jsonb_array_elements(event_refs) loop
      if exists(select 1 from public.user_memory_event_source_exclusion x where x.user_id=owner_id and x.project_id=p_project_id
        and x.event_id=current_event.id and x.source_id::text=ref->>'source_id') then
        raise exception 'removed source link requires an explicit author decision' using errcode='42501'; end if;
      perform public.validate_memory_evidence(owner_id,p_project_id,ref);
      select * into evidence from public.user_narrator_source where user_id=owner_id and project_id=p_project_id and id=(ref->>'source_id')::uuid;
      if not found then raise exception 'event source unavailable' using errcode='42501'; end if;
      if evidence.status<>'active' or evidence.version is distinct from (ref->>'version')::bigint then
        raise exception 'evidence revision conflict' using errcode='40001';
      end if;
      if length(coalesce(ref->>'quote','')) not between 1 and 2000 or pg_catalog.strpos(evidence.text,ref->>'quote')=0 then
        raise exception 'evidence quote must match original testimony' using errcode='22023';
      end if;
    end loop;
    -- A validated echo of saved facts acknowledges the input without dirtying
    -- the event. New evidence links, placement or lifecycle still revise it.
    if current_event.id is not null and current_event.data = event_data and
       current_event.life_stage = event_stage and current_event.status =
         (case when coalesce(pg_catalog.jsonb_array_length(proposal->'candidate_ids'),0)>0 then 'unresolved' else 'active' end) and
       not exists(select 1 from pg_catalog.jsonb_array_elements(event_refs) proposed_ref where not exists(
         select 1 from public.user_memory_event_source s where s.user_id=owner_id and s.project_id=p_project_id
           and s.event_id=current_event.id and s.evidence=proposed_ref.value)) then
      continue;
    end if;
    update public.user_memoir_project set event_sequence=event_sequence+1
      where user_id=owner_id and project_id=p_project_id returning event_sequence into next_change;
    insert into public.user_memory_event(user_id,project_id,id,revision,kind,life_stage,status,data,change_sequence)
      values(owner_id,p_project_id,event_id,coalesce(current_event.revision,0)+1,proposal->>'kind',event_stage,
        case when coalesce(pg_catalog.jsonb_array_length(proposal->'candidate_ids'),0)>0 then 'unresolved' else 'active' end,event_data,next_change)
      on conflict(user_id,project_id,id) do update set revision=excluded.revision,life_stage=excluded.life_stage,
        data=excluded.data,status=excluded.status,change_sequence=excluded.change_sequence;
    for ref in select value from pg_catalog.jsonb_array_elements(event_refs) loop
      insert into public.user_memory_event_source(user_id,project_id,event_id,source_id,source_version,evidence_hash,evidence)
        values(owner_id,p_project_id,event_id,(ref->>'source_id')::uuid,(ref->>'version')::bigint,pg_catalog.md5(ref::text),ref)
        on conflict do nothing;
    end loop;
    select * into current_event from public.user_memory_event where user_id=owner_id and project_id=p_project_id and id=event_id;
    insert into public.user_memory_event_revision(user_id,project_id,event_id,revision,record,actor,origin)
      values(owner_id,p_project_id,event_id,current_event.revision,public.memory_event_record(current_event),'model','author_timeline');
  end loop;
  update public.user_narrator_source set processing_status='succeeded'
    where user_id=owner_id and project_id=p_project_id and processing_status<>'succeeded'
      and id in (select (value->>'id')::uuid from pg_catalog.jsonb_array_elements(p_sources));
  get diagnostics updated=ROW_COUNT;
  update public.user_memoir_project set extraction_cursor=coalesce(
      (select min(sequence)-1 from public.user_narrator_source where user_id=owner_id and project_id=p_project_id and processing_status<>'succeeded'),source_sequence)
    where user_id=owner_id and project_id=p_project_id;
  if updated>0 then
    insert into public.user_private_draft_outbox(user_id,project_id,change_kind) values(owner_id,p_project_id,'events');
  end if;
  return public.read_user_memory_events(p_project_id);
end $$;
revoke all on function public.apply_user_memory_events(text,jsonb,jsonb) from public,anon;
grant execute on function public.apply_user_memory_events(text,jsonb,jsonb) to authenticated;

commit;
