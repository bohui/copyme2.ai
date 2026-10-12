-- Only resolved lifetime identities bypass legacy cumulative admission limits.
-- Original per-request, evidence, privacy, receipt and commercial checks remain.
begin;
create or replace function public.accept_user_narrator_source_before_news(
  p_project_id text,p_client_turn_id uuid,p_text text,
  p_kind text default 'narrator_chat',p_language text default 'en-AU'
) returns jsonb language plpgsql security definer set search_path='' as $$
declare owner_id uuid:=auth.uid(); saved public.user_narrator_source%rowtype; next_sequence bigint;
begin
  if owner_id is null then raise exception 'authenticated user required' using errcode='42501'; end if;
  if p_project_id is null or p_project_id !~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$' or
     p_client_turn_id is null or p_text is null or length(pg_catalog.btrim(p_text))=0 or length(p_text)>100000 or
     p_kind not in ('narrator_chat','narrator_transcript') or p_language not in ('en-AU','zh-CN') then
    raise exception 'invalid narrator source' using errcode='22023';
  end if;
  insert into public.user_memoir_project(user_id,project_id) values(owner_id,p_project_id) on conflict do nothing;
  perform 1 from public.user_memoir_project where user_id=owner_id and project_id=p_project_id for update;
  select * into saved from public.user_narrator_source
    where user_id=owner_id and project_id=p_project_id and client_turn_id=p_client_turn_id;
  if found then
    if saved.text is distinct from p_text or saved.kind is distinct from p_kind then
      raise exception 'input revision conflict; retry with the original input' using errcode='40001';
    end if;
    return public.narrator_source_record(saved);
  end if;
  if not exists(select 1 from public.user_lifetime_conversation where user_id=owner_id and project_id=p_project_id) then
  if (select count(*) from public.user_narrator_source where user_id=owner_id and project_id=p_project_id)>=1000 or
     (select coalesce(sum(length(text)),0) from public.user_narrator_source where user_id=owner_id and project_id=p_project_id)+length(p_text)>120000 then
    raise exception 'memoir evidence exceeds supported bounds' using errcode='22023';
  end if;
  end if;
  update public.user_memoir_project set source_sequence=source_sequence+1
    where user_id=owner_id and project_id=p_project_id returning source_sequence into next_sequence;
  insert into public.user_narrator_source(user_id,project_id,client_turn_id,sequence,text,kind,language)
    values(owner_id,p_project_id,p_client_turn_id,next_sequence,p_text,p_kind,p_language) returning * into saved;
  insert into public.user_narrator_source_version(user_id,project_id,source_id,version,text,language)
    values(owner_id,p_project_id,saved.id,saved.version,saved.text,saved.language);
  -- Acceptance and intent commit together, before optional assistant delivery.
  insert into public.user_private_draft_outbox(user_id,project_id,memory_id,change_kind)
    values(owner_id,p_project_id,saved.id,'accepted');
  return public.narrator_source_record(saved);
end $$;

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
  if not exists(select 1 from public.user_lifetime_conversation where user_id=owner_id and project_id=p_project_id) then
  if p_action='edit' and (select coalesce(sum(length(text)),0) from public.user_narrator_source
     where user_id=owner_id and project_id=p_project_id and id<>p_source_id)+length(p_text)>120000 then
    raise exception 'memoir evidence exceeds supported bounds' using errcode='22023';
  end if;
  end if;
  select array_agg(distinct s.event_id) into affected from public.user_memory_event_source s
    where user_id=owner_id and project_id=p_project_id and source_id=p_source_id;
  update public.user_memoir_manuscript m set proposal=null where user_id=owner_id and project_id=p_project_id
    and exists(select 1 from pg_catalog.jsonb_array_elements(coalesce(m.proposal->'bundle'->'source_manifest','[]')) ref where ref->>'id'=p_source_id::text);
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
revoke all on function public.accept_user_narrator_source_before_news(text,uuid,text,text,text) from public,anon,authenticated;
commit;
