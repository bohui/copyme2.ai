-- Issue 41: private photo bytes, accepted cue snapshots and one private plan.
-- Apply only through the normal migration process, never from an API worker.
begin;

alter table public.user_memoir_project add column if not exists interview_sequence bigint not null default 0;

create table public.user_interview_photo (
  id uuid not null default gen_random_uuid(), user_id uuid not null, project_id text not null,
  upload_key uuid, content_sha256 text, unique(user_id,project_id,upload_key),
  object_path text not null unique, content_type text not null check(content_type in ('image/jpeg','image/png','image/webp')),
  byte_size bigint not null check(byte_size between 1 and 10485760), width integer not null, height integer not null,
  status text not null default 'pending' check(status in ('pending','ready','deleted')),
  created_at timestamptz not null default clock_timestamp(),
  primary key(user_id,project_id,id),
  check(width>0 and height>0 and width::bigint*height<=36000000),
  foreign key(user_id,project_id) references public.user_memoir_project on delete cascade
);
create table public.user_interview_turn (
  user_id uuid not null, project_id text not null, client_turn_id uuid not null,
  sequence bigint not null, source_id uuid, source_version bigint, source_sequence bigint not null,
  input_hash text not null, kind text not null, collector jsonb, photo_context jsonb not null default '[]',
  consumed_photo_key text, consumed_photo_revision text, policy_epoch bigint not null,
  created_at timestamptz not null default clock_timestamp(),
  primary key(user_id,project_id,client_turn_id), unique(user_id,project_id,sequence),
  foreign key(user_id,project_id) references public.user_memoir_project on delete cascade,
  foreign key(user_id,project_id,source_id) references public.user_narrator_source on delete cascade
);
create table public.user_interview_photo_link (
  id uuid not null default gen_random_uuid(), user_id uuid not null, project_id text not null,
  photo_id text not null, event_id text, intended_event_id text,
  source_id uuid not null, source_version bigint not null, quote text not null check(length(quote) between 1 and 2000),
  description text not null check(length(description) between 1 and 2000),
  provenance text not null check(provenance in ('narrator','narrator_metadata','visual_derived')),
  status text not null default 'pending' check(status in ('pending','confirmed','invalidated','unlinked')),
  retired_through_sequence bigint,
  primary key(user_id,project_id,id), unique(user_id,project_id,photo_id,source_id,source_version,quote),
  foreign key(user_id,project_id,source_id,source_version) references public.user_narrator_source_version on delete cascade,
  foreign key(user_id,project_id,event_id) references public.user_memory_event on delete cascade,
  foreign key(user_id,project_id,intended_event_id) references public.user_memory_event on delete cascade
);
create table public.user_interview_plan (
  user_id uuid not null, project_id text not null, client_turn_id uuid not null,
  sequence bigint not null, revision bigint not null default 1, plan jsonb not null,
  primary key(user_id,project_id),
  foreign key(user_id,project_id,client_turn_id) references public.user_interview_turn on delete cascade
);

-- No shared-project or family-member policy is applicable to this domain.
alter table public.user_interview_photo enable row level security;
alter table public.user_interview_turn enable row level security;
alter table public.user_interview_photo_link enable row level security;
alter table public.user_interview_plan enable row level security;
revoke all on public.user_interview_photo,public.user_interview_turn,public.user_interview_photo_link,public.user_interview_plan from public,anon,authenticated;
grant select on public.user_interview_photo,public.user_interview_turn,public.user_interview_photo_link,public.user_interview_plan to authenticated;
create policy interview_photo_owner on public.user_interview_photo for select to authenticated using(user_id=auth.uid());
create policy interview_turn_owner on public.user_interview_turn for select to authenticated using(user_id=auth.uid());
create policy interview_photo_link_owner on public.user_interview_photo_link for select to authenticated using(user_id=auth.uid() and status in ('pending','confirmed'));
create policy interview_plan_owner on public.user_interview_plan for select to authenticated using(user_id=auth.uid());

insert into storage.buckets(id,name,public,file_size_limit)
  values('memoir-private-photos','memoir-private-photos',false,10485760)
  on conflict(id) do update set public=false,file_size_limit=10485760;
-- Object paths are identities, not authority. Ownership follows the private
-- record, including after an authorised guest transfer. No storage SQL writes.
-- Requires Supabase Storage's documented operation-aware authorization helper.
-- Missing helper/operation fails closed, including for owners. Do not replace
-- with a path-only policy: it would allow reusable signed download URLs.
create function public.interview_storage_operation_allowed(p_operations text[]) returns boolean
language plpgsql stable set search_path='' as $$
declare allowed boolean;
begin
  if to_regprocedure('storage.allow_any_operation(text[])') is null then return false; end if;
  execute 'select storage.allow_any_operation($1)' into allowed using p_operations;
  return coalesce(allowed,false);
end $$;
revoke all on function public.interview_storage_operation_allowed(text[]) from public,anon;
grant execute on function public.interview_storage_operation_allowed(text[]) to authenticated;
create policy interview_photo_bytes_read on storage.objects for select to authenticated
  using(bucket_id='memoir-private-photos' and exists(select 1 from public.user_interview_photo p
    where p.user_id=auth.uid() and p.object_path=name and (
      p.status='ready' and public.interview_storage_operation_allowed(array['object.get_authenticated','object.get_authenticated_info','object.head_authenticated_info']) or
      p.status in ('pending','deleted') and public.interview_storage_operation_allowed(array['object.delete','object.delete_many']))));
create policy interview_photo_bytes_insert on storage.objects for insert to authenticated
  with check(bucket_id='memoir-private-photos' and public.interview_storage_operation_allowed(array['object.upload']) and
    exists(select 1 from public.user_interview_photo p where p.user_id=auth.uid() and p.object_path=name and p.status='pending'));
create policy interview_photo_bytes_delete on storage.objects for delete to authenticated
  using(bucket_id='memoir-private-photos' and public.interview_storage_operation_allowed(array['object.delete','object.delete_many']) and
    exists(select 1 from public.user_interview_photo p where p.user_id=auth.uid() and p.object_path=name and p.status in ('pending','deleted')));

create function public.begin_user_interview_photo(p_project_id text,p_metadata jsonb,p_upload_key uuid default null) returns jsonb
language plpgsql security definer set search_path='' as $$
declare v_owner uuid:=auth.uid(); v_id uuid:=gen_random_uuid(); saved public.user_interview_photo%rowtype; suffix text;
begin
  if v_owner is null then raise exception 'authenticated user required' using errcode='42501'; end if;
  if p_project_id is null or p_project_id !~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$' or
    jsonb_typeof(p_metadata) is distinct from 'object' or
    p_metadata->>'content_type' not in ('image/jpeg','image/png','image/webp') then
    raise exception 'invalid private photo' using errcode='22023'; end if;
  insert into public.user_memoir_project(user_id,project_id) values(v_owner,p_project_id) on conflict do nothing;
  perform 1 from public.user_memoir_project where user_id=v_owner and project_id=p_project_id for update;
  if p_upload_key is not null then
    select * into saved from public.user_interview_photo where user_id=v_owner and project_id=p_project_id and upload_key=p_upload_key;
    if found then
      if saved.status='deleted' or saved.content_sha256 is distinct from p_metadata->>'content_sha256' or
        saved.content_type is distinct from p_metadata->>'content_type' or saved.byte_size is distinct from (p_metadata->>'byte_size')::bigint then
        raise exception 'upload retry identity conflict' using errcode='40001'; end if;
      if saved.status='pending' and exists(select 1 from storage.objects where bucket_id='memoir-private-photos' and name=saved.object_path) then
        update public.user_interview_photo set status='ready' where user_id=v_owner and project_id=p_project_id and id=saved.id returning * into saved;
      end if;
      return to_jsonb(saved)-'user_id';
    end if;
  end if;
  if (select count(*) from public.user_interview_photo where user_id=v_owner and project_id=p_project_id and status<>'deleted')>=200 then
    raise exception 'photo collection exceeds supported bound' using errcode='22023'; end if;
  suffix:=case p_metadata->>'content_type' when 'image/jpeg' then 'jpg' when 'image/png' then 'png' else 'webp' end;
  insert into public.user_interview_photo(id,user_id,project_id,object_path,content_type,byte_size,width,height,upload_key,content_sha256)
    values(v_id,v_owner,p_project_id,v_owner::text || '/private-photo/' || v_id::text || '.' || suffix,
      p_metadata->>'content_type',(p_metadata->>'byte_size')::bigint,(p_metadata->>'width')::integer,(p_metadata->>'height')::integer,p_upload_key,p_metadata->>'content_sha256')
    returning * into saved;
  return to_jsonb(saved)-'user_id';
end $$;

create function public.finish_user_interview_photo(p_project_id text,p_photo_id uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare saved public.user_interview_photo%rowtype;
begin
  select * into saved from public.user_interview_photo where user_id=auth.uid() and project_id=p_project_id and id=p_photo_id for update;
  if not found or saved.status='deleted' then raise exception 'photo unavailable' using errcode='42501'; end if;
  if not exists(select 1 from storage.objects where bucket_id='memoir-private-photos' and name=saved.object_path) then
    raise exception 'photo upload incomplete' using errcode='55000'; end if;
  update public.user_interview_photo set status='ready' where user_id=auth.uid() and project_id=p_project_id and id=p_photo_id returning * into saved;
  return to_jsonb(saved)-'user_id';
end $$;

create function public.read_user_interview_photo(p_project_id text,p_photo_id uuid) returns jsonb
language sql security definer set search_path='' as $$
  select to_jsonb(p)-'user_id' from public.user_interview_photo p
    where user_id=auth.uid() and project_id=p_project_id and id=p_photo_id and status='ready'
$$;

create function public.interview_photo_card(p public.user_interview_photo) returns jsonb
language sql immutable set search_path='' as $$
  select jsonb_build_object('id',p.id,'photo_id','upload:' || p.id::text,'kind','private_upload',
    'title','Your private photo','content_type',p.content_type,'byte_size',p.byte_size,
    'content_url','/v1/agent/projects/' || p.project_id || '/photos/' || p.id::text || '/content')
$$;

create function public.interview_turn_record(t public.user_interview_turn) returns jsonb
language sql stable set search_path='' as $$
  select jsonb_build_object('client_turn_id',t.client_turn_id,'sequence',t.sequence,
    'source',(select public.narrator_source_record(s) from public.user_narrator_source s
      where s.user_id=t.user_id and s.project_id=t.project_id and s.id=t.source_id),
    'source_version',t.source_version,'photo_context',case when t.source_id is null or exists(select 1 from public.user_narrator_source s
      where s.user_id=t.user_id and s.project_id=t.project_id and s.id=t.source_id and s.version=t.source_version and s.status='active')
      then coalesce((select jsonb_agg(p) from jsonb_array_elements(t.photo_context) p where p->>'kind'<>'private_upload' or
        exists(select 1 from public.user_interview_photo owned where owned.user_id=t.user_id and owned.project_id=t.project_id
          and 'upload:' || owned.id::text=p->>'photo_id' and owned.status='ready')),'[]') else '[]'::jsonb end,
    'plan',t.collector->'plan','reply',t.collector->>'reply','thread_id',t.collector->>'thread_id',
    'response_photos',coalesce(t.collector->'response_photos','[]'),
    'consumed_photo_key',t.consumed_photo_key,'consumed_photo_revision',t.consumed_photo_revision,
    'photo_cue',jsonb_build_object('consumed',t.consumed_photo_key is not null or jsonb_array_length(t.photo_context)>0,
      'key',t.consumed_photo_key,'revision',t.consumed_photo_revision))
$$;

create function public.read_user_interview_turn(p_project_id text,p_client_turn_id uuid) returns jsonb
language sql stable security definer set search_path='' as $$
  select public.interview_turn_record(t) from public.user_interview_turn t
    where user_id=auth.uid() and project_id=p_project_id and client_turn_id=p_client_turn_id
$$;

create function public.accept_user_interview_turn(p_project_id text,p_client_turn_id uuid,p_text text,
  p_kind text default 'narrator_chat',p_language text default 'en-AU',p_uploaded_photo_ids jsonb default '[]',
  p_photo_selection jsonb default null) returns jsonb
language plpgsql security definer set search_path='' as $$
declare v_owner uuid:=auth.uid(); project public.user_memoir_project%rowtype; saved public.user_interview_turn%rowtype;
  source jsonb; v_profile jsonb; state jsonb; selected jsonb; context jsonb:='[]'; photo public.user_interview_photo%rowtype;
  identifier text; selected_key text; selected_revision text; next_sequence bigint;
begin
  if v_owner is null then raise exception 'authenticated user required' using errcode='42501'; end if;
  if p_project_id is null or p_project_id !~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$' or p_client_turn_id is null or
    p_text is null or length(p_text)>100000 or p_kind not in ('narrator_chat','narrator_transcript') or
    p_language not in ('en-AU','zh-CN') or jsonb_typeof(p_uploaded_photo_ids) is distinct from 'array' or
    jsonb_array_length(p_uploaded_photo_ids)>5 then raise exception 'invalid interview input' using errcode='22023'; end if;
  insert into public.user_memoir_project(user_id,project_id) values(v_owner,p_project_id) on conflict do nothing;
  select * into project from public.user_memoir_project where user_id=v_owner and project_id=p_project_id for update;
  select * into saved from public.user_interview_turn where user_id=v_owner and project_id=p_project_id and client_turn_id=p_client_turn_id;
  if found then
    if saved.input_hash is distinct from md5(p_text) or saved.kind is distinct from p_kind then
      raise exception 'input revision conflict; retry with the original input' using errcode='40001'; end if;
    return public.interview_turn_record(saved);
  end if;
  select p.profile into v_profile from public.user_profile p where user_id=v_owner for update;
  state:=coalesce(v_profile->'photo_memories'->p_project_id,'{}');
  selected_key:=state->>'selected'; selected_revision:=state->>'selection_revision';
  -- Explicit null means no public cue. Never silently consume another tab's
  -- selection. A legacy missing revision is accepted only with matching null.
  if p_photo_selection is not null and p_photo_selection<>'null'::jsonb then
    if jsonb_typeof(p_photo_selection) is distinct from 'object' or
      p_photo_selection->>'key' is distinct from selected_key or
      p_photo_selection->>'revision' is distinct from selected_revision or selected_key is null then
      raise exception 'photo selection changed; reload the cue' using errcode='40001'; end if;
    select value into selected from jsonb_array_elements(coalesce(state->'favorites','[]')) where value->>'key'=selected_key;
    if selected is null then raise exception 'photo selection changed; reload the cue' using errcode='40001'; end if;
    context:=jsonb_build_array(selected || jsonb_build_object('kind','public_reference','photo_id','reference:' || md5(selected_key)));
    state:=jsonb_set(state,'{selected}','null');
    v_profile:=jsonb_set(v_profile,array['photo_memories',p_project_id],state);
    update public.user_profile p set profile=v_profile where p.user_id=v_owner;
  else selected_key:=null; selected_revision:=null;
  end if;
  for identifier in select distinct value from jsonb_array_elements_text(p_uploaded_photo_ids) loop
    select * into photo from public.user_interview_photo where user_id=v_owner and project_id=p_project_id and id=identifier::uuid and status='ready';
    if not found then raise exception 'photo unavailable' using errcode='42501'; end if;
    context:=context || jsonb_build_array(public.interview_photo_card(photo));
  end loop;
  if length(btrim(p_text))=0 and context='[]'::jsonb then raise exception 'a narrative or photo cue is required' using errcode='22023'; end if;
  if length(btrim(p_text))>0 then
    source:=public.accept_user_narrator_source(p_project_id,p_client_turn_id,p_text,p_kind,p_language);
  end if;
  update public.user_memoir_project set interview_sequence=interview_sequence+1
    where user_id=v_owner and project_id=p_project_id returning * into project;
  insert into public.user_interview_turn(user_id,project_id,client_turn_id,sequence,source_id,source_version,source_sequence,
    input_hash,kind,photo_context,consumed_photo_key,consumed_photo_revision,policy_epoch)
    values(v_owner,p_project_id,p_client_turn_id,project.interview_sequence,(source->>'id')::uuid,(source->>'version')::bigint,
      project.source_sequence,md5(p_text),p_kind,context,selected_key,selected_revision,project.policy_epoch) returning * into saved;
  return public.interview_turn_record(saved);
end $$;

create function public.interview_photo_available(p_owner uuid,p_project_id text,p_photo_id text,p_for_cue boolean default false) returns boolean
language sql stable security definer set search_path='' as $$
  select exists(select 1 from public.user_interview_turn t, jsonb_array_elements(t.photo_context) p
    where t.user_id=p_owner and t.project_id=p_project_id and p->>'photo_id'=p_photo_id
      and (not p_for_cue or not exists(select 1 from public.user_interview_photo_link retired
        where retired.user_id=p_owner and retired.project_id=p_project_id and retired.photo_id=p_photo_id
          and retired.status='unlinked' and t.sequence<=coalesce(retired.retired_through_sequence,9223372036854775807)))
      and (t.source_id is null or exists(select 1 from public.user_narrator_source s where s.user_id=t.user_id
        and s.project_id=t.project_id and s.id=t.source_id and s.version=t.source_version and s.status='active')))
    and (p_photo_id not like 'upload:%' or exists(select 1 from public.user_interview_photo p
      where p.user_id=p_owner and p.project_id=p_project_id and 'upload:' || p.id::text=p_photo_id and p.status='ready'))
$$;

create function public.interview_photo_links(p_owner uuid,p_project_id text,p_event_id text default null) returns jsonb
language sql stable security definer set search_path='' as $$
  select coalesce(jsonb_agg(to_jsonb(l)-'user_id' order by l.id),'[]') from public.user_interview_photo_link l
    join public.user_narrator_source s on s.user_id=l.user_id and s.project_id=l.project_id and s.id=l.source_id
    where l.user_id=p_owner and l.project_id=p_project_id and l.status in ('pending','confirmed')
      and s.status='active' and s.version=l.source_version
      and (p_event_id is null or l.event_id=p_event_id and l.status='confirmed')
      and public.interview_photo_available(p_owner,p_project_id,l.photo_id)
$$;

create function public.read_user_interview_context(p_project_id text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare result jsonb;
begin
  if auth.uid() is null then raise exception 'authenticated user required' using errcode='42501'; end if;
  return jsonb_build_object('plan',(select plan from public.user_interview_plan where user_id=auth.uid() and project_id=p_project_id),
    'photo_associations',public.interview_photo_links(auth.uid(),p_project_id),
    'photos',coalesce((select jsonb_agg(p) from (select distinct p from public.user_interview_turn t,
      jsonb_array_elements(t.photo_context) p where t.user_id=auth.uid() and t.project_id=p_project_id
        and public.interview_photo_available(auth.uid(),p_project_id,p->>'photo_id')
        and (public.interview_photo_available(auth.uid(),p_project_id,p->>'photo_id',true) or exists(
          select 1 from public.user_interview_photo_link l join public.user_narrator_source original
            on original.user_id=l.user_id and original.project_id=l.project_id and original.id=l.source_id
          where l.user_id=auth.uid() and l.project_id=p_project_id and l.photo_id=p->>'photo_id'
            and l.status='confirmed' and original.status='active' and original.version=l.source_version))) photos),'[]'));
end $$;

-- Invalidates frozen worker snapshots as well as the current manuscript and
-- planner. No derived quote remains reusable through a checkpoint/reuse bundle.
create function public.invalidate_interview_photo_projection(p_owner uuid,p_project_id text,p_retire boolean default true) returns void
language plpgsql security definer set search_path='' as $$
begin
  update public.user_memoir_project set policy_epoch=policy_epoch+1 where user_id=p_owner and project_id=p_project_id;
  update public.user_memoir_manuscript set eligible=false,proposal=null,reuse=null where user_id=p_owner and project_id=p_project_id;
  delete from public.user_memoir_section_revision where user_id=p_owner and project_id=p_project_id;
  delete from public.user_memoir_checkpoint c using public.user_memoir_lane l where c.lane_id=l.id and l.user_id=p_owner and l.project_id=p_project_id;
  if not p_retire then
    update public.user_interview_turn t set policy_epoch=p.policy_epoch from public.user_memoir_project p
      where p.user_id=p_owner and p.project_id=p_project_id and t.user_id=p.user_id and t.project_id=p.project_id
        and t.sequence=p.interview_sequence and t.source_sequence=p.source_sequence;
  end if;
  if p_retire then
    delete from public.user_interview_plan where user_id=p_owner and project_id=p_project_id;
    update public.user_interview_turn set collector=null where user_id=p_owner and project_id=p_project_id;
  end if;
  insert into public.user_private_draft_outbox(user_id,project_id,change_kind) values(p_owner,p_project_id,'correction');
end $$;

create function public.reconcile_interview_photo_links(p_owner uuid,p_project_id text) returns void
language plpgsql security definer set search_path='' as $$
declare link public.user_interview_photo_link%rowtype; matches text[]; resolved text; changed boolean:=false;
begin
  for link in select * from public.user_interview_photo_link where user_id=p_owner and project_id=p_project_id and status in ('pending','confirmed') loop
    select array_agg(distinct e.event_id) into matches from public.user_memory_event_source e
      join public.user_memory_event event on event.user_id=e.user_id and event.project_id=e.project_id and event.id=e.event_id
      join public.user_narrator_source s on s.user_id=e.user_id and s.project_id=e.project_id and s.id=e.source_id
      where e.user_id=p_owner and e.project_id=p_project_id and e.source_id=link.source_id and e.source_version=link.source_version
        and s.status='active' and s.version=link.source_version and event.status='active'
        and strpos(e.evidence->>'quote',link.quote)>0
        and strpos(substr(s.text,strpos(s.text,link.quote)+1),link.quote)=0
        and (link.intended_event_id is null or e.event_id=link.intended_event_id)
        and not exists(select 1 from public.user_memory_event_source_exclusion x where x.user_id=p_owner and x.project_id=p_project_id
          and x.event_id=e.event_id and x.source_id=link.source_id);
    resolved:=case when array_length(matches,1)=1 then matches[1] else null end;
    if link.event_id is distinct from resolved then
      update public.user_interview_photo_link set event_id=resolved,status=case when resolved is null then 'pending' else 'confirmed' end
        where user_id=p_owner and project_id=p_project_id and id=link.id;
      changed:=true;
    end if;
  end loop;
  if changed then perform public.invalidate_interview_photo_projection(p_owner,p_project_id,false); end if;
end $$;

create function public.save_user_interview_plan(p_project_id text,p_client_turn_id uuid,p_plan jsonb,p_associations jsonb,p_lease_token uuid,
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
    exists(select 1 from jsonb_object_keys(p_plan) k where k not in ('candidates','chosen_id','active_event_id')) or
    jsonb_typeof(p_associations) is distinct from 'array' or jsonb_array_length(p_associations)>20 or
    octet_length(p_associations::text)>32000 then raise exception 'invalid interview plan' using errcode='22023'; end if;
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

create function public.delete_user_interview_photo(p_project_id text,p_photo_id uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare saved public.user_interview_photo%rowtype; v_owner uuid:=auth.uid();
begin
  perform 1 from public.user_memoir_project where user_id=v_owner and project_id=p_project_id for update;
  select * into saved from public.user_interview_photo where user_id=v_owner and project_id=p_project_id and id=p_photo_id for update;
  if not found then return null; end if;
  if saved.status<>'deleted' then
    update public.user_interview_photo set status='deleted' where user_id=v_owner and project_id=p_project_id and id=p_photo_id;
    update public.user_interview_photo_link set status='invalidated',description='[photo deleted]',quote='[photo deleted:' || id::text || ']'
      where user_id=v_owner and project_id=p_project_id and photo_id='upload:' || p_photo_id::text;
    update public.user_interview_turn t set photo_context=coalesce((select jsonb_agg(p) from jsonb_array_elements(t.photo_context) p
      where p->>'photo_id'<>'upload:' || p_photo_id::text),'[]') where user_id=v_owner and project_id=p_project_id;
    perform public.invalidate_interview_photo_projection(v_owner,p_project_id);
  end if;
  return to_jsonb(saved)-'user_id';
end $$;

create function public.unlink_user_interview_photo(p_project_id text,p_association_id uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare link public.user_interview_photo_link%rowtype; latest_sequence bigint;
begin
  select interview_sequence into latest_sequence from public.user_memoir_project
    where user_id=auth.uid() and project_id=p_project_id for update;
  select * into link from public.user_interview_photo_link where user_id=auth.uid() and project_id=p_project_id and id=p_association_id for update;
  if not found then raise exception 'photo association unavailable' using errcode='42501'; end if;
  -- Uncertain retries cannot move the fence past an explicitly reselected cue.
  if link.status='unlinked' then return jsonb_build_object('unlinked',true); end if;
  update public.user_interview_photo_link set status='unlinked',retired_through_sequence=latest_sequence
    where user_id=auth.uid() and project_id=p_project_id and id=p_association_id;
  perform public.invalidate_interview_photo_projection(auth.uid(),p_project_id);
  return jsonb_build_object('unlinked',true);
end $$;

create function public.invalidate_changed_interview_evidence() returns trigger
language plpgsql security definer set search_path='' as $$
declare changed integer;
begin
  if old.version is distinct from new.version or old.status is distinct from new.status then
    -- An event correction trigger may already have invalidated a link before
    -- this source trigger runs. Scrub those retired records too, so a later
    -- guest-transfer snapshot cannot carry the withdrawn original quote.
    update public.user_interview_photo_link set status=case when status='unlinked' then 'unlinked' else 'invalidated' end,
      description='[evidence changed]',quote='[evidence changed:' || id::text || ']'
      where user_id=new.user_id and project_id=new.project_id and source_id=new.id;
    get diagnostics changed=row_count;
    delete from public.user_interview_plan where user_id=new.user_id and project_id=new.project_id;
    if changed>0 then perform public.invalidate_interview_photo_projection(new.user_id,new.project_id); end if;
  end if;
  return new;
end $$;
create trigger invalidate_changed_interview_evidence after update on public.user_narrator_source
  for each row execute function public.invalidate_changed_interview_evidence();

create function public.invalidate_corrected_interview_event() returns trigger
language plpgsql security definer set search_path='' as $$
declare changed integer;
begin
  if new.status<>'active' or new.data->'user_overrides' is distinct from old.data->'user_overrides' then
    update public.user_interview_photo_link set status='invalidated',description='[event changed]'
      where user_id=new.user_id and project_id=new.project_id and (event_id=new.id or intended_event_id=new.id) and status in ('pending','confirmed');
    get diagnostics changed=row_count;
    delete from public.user_interview_plan where user_id=new.user_id and project_id=new.project_id;
    if changed>0 then perform public.invalidate_interview_photo_projection(new.user_id,new.project_id); end if;
  end if;
  return new;
end $$;
create trigger invalidate_corrected_interview_event after update on public.user_memory_event
  for each row execute function public.invalidate_corrected_interview_event();

-- Reconciliation occurs after ALL event proposals commit, so two supported
-- events sharing an ambiguous quote remain unresolved, rather than first wins.
alter function public.apply_user_memory_events(text,jsonb,jsonb) rename to apply_user_memory_events_before_photos;
revoke all on function public.apply_user_memory_events_before_photos(text,jsonb,jsonb) from public,anon,authenticated;
create function public.apply_user_memory_events(p_project_id text,p_sources jsonb,p_events jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
begin
  perform public.apply_user_memory_events_before_photos(p_project_id,p_sources,p_events);
  perform public.reconcile_interview_photo_links(auth.uid(),p_project_id);
  return public.read_user_memory_events(p_project_id);
end $$;

alter function public.memory_event_record(public.user_memory_event) rename to memory_event_record_before_photos;
revoke all on function public.memory_event_record_before_photos(public.user_memory_event) from public,anon,authenticated;
create function public.memory_event_record(e public.user_memory_event) returns jsonb
language sql stable set search_path='' as $$
  select public.memory_event_record_before_photos(e) || jsonb_build_object('photo_associations',public.interview_photo_links(e.user_id,e.project_id,e.id))
$$;

-- Photo context is a current authorized projection, not historical evidence.
-- Do not fossilize it in canonical revision blobs, which otherwise outlive a
-- guest transfer, deletion or unlink and could expose stale private metadata.
create function public.strip_historical_interview_photo_context() returns trigger
language plpgsql security definer set search_path='' as $$
begin
  new.record:=new.record-'photo_associations';
  return new;
end $$;
revoke all on function public.strip_historical_interview_photo_context() from public,anon,authenticated;
create trigger strip_historical_interview_photo_context before insert or update on public.user_memory_event_revision
  for each row execute function public.strip_historical_interview_photo_context();

-- Carry the same canonical photo context into both fenced worker lanes.
alter function public.claim_memoir_lane(uuid,integer) rename to claim_memoir_lane_before_photos;
revoke all on function public.claim_memoir_lane_before_photos(uuid,integer) from public,anon,authenticated,service_role;
create function public.claim_memoir_lane(p_lane_id uuid,p_run_seconds integer default 300) returns jsonb
language plpgsql security definer set search_path='' as $$
declare result jsonb; v_owner uuid; v_project_id text;
begin
  result:=public.claim_memoir_lane_before_photos(p_lane_id,p_run_seconds);
  if result is null then return null; end if;
  v_owner:=(result->>'user_id')::uuid; v_project_id:=result->>'project_id';
  return result || jsonb_build_object('interview_context',jsonb_build_object(
    'plan',(select p.plan from public.user_interview_plan p where p.user_id=v_owner and p.project_id=v_project_id),
    'photo_associations',public.interview_photo_links(v_owner,v_project_id)));
end $$;

create table public.user_interview_photo_transfer (
  conversation_id uuid primary key references public.user_conversation_attachment on delete cascade,
  user_id uuid not null references auth.users on delete cascade
);
alter table public.user_interview_photo_transfer enable row level security;
revoke all on public.user_interview_photo_transfer from public,anon,authenticated;

create function public.interview_transfer_snapshot(p_owner uuid,p_project_id text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare snapshot jsonb:='{}'; table_name text; rows jsonb;
begin
  foreach table_name in array array['user_interview_photo','user_interview_turn','user_interview_photo_link','user_interview_plan'] loop
    execute format('select coalesce(jsonb_agg(to_jsonb(t) order by to_jsonb(t)::text),''[]''::jsonb) from public.%I t where user_id=$1 and project_id=$2',table_name)
      into rows using p_owner,p_project_id;
    snapshot:=snapshot || jsonb_build_object(table_name,rows);
  end loop;
  return snapshot;
end $$;

alter function public.prepare_guest_conversation_transfer(text,text,jsonb,jsonb,text) rename to prepare_guest_conversation_before_photos;
revoke all on function public.prepare_guest_conversation_before_photos(text,text,jsonb,jsonb,text) from public,anon,authenticated;
create function public.prepare_guest_conversation_transfer(p_token text,p_project_id text,p_messages jsonb,
  p_workspace_profile jsonb default '{}',p_ui_locale text default null) returns jsonb
language plpgsql security definer set search_path='' as $$
declare result jsonb;
begin
  result:=public.prepare_guest_conversation_before_photos(p_token,p_project_id,p_messages,p_workspace_profile,p_ui_locale);
  update public.guest_conversation_transfer set workspace=workspace || jsonb_build_object('interview_photos',public.interview_transfer_snapshot(auth.uid(),p_project_id))
    where token_hash=encode(sha256(convert_to(p_token,'UTF8')),'hex') and guest_user_id=auth.uid() and target_user_id is null;
  return result;
end $$;

alter function public.attach_guest_conversation(text,boolean) rename to attach_guest_conversation_before_photos;
revoke all on function public.attach_guest_conversation_before_photos(text,boolean) from public,anon,authenticated;
create function public.attach_guest_conversation(p_token text,p_guest_wins boolean default false) returns jsonb
language plpgsql security definer set search_path='' as $$
declare result jsonb; attachment public.user_conversation_attachment%rowtype; snapshot jsonb; original jsonb;
  v_owner uuid:=auth.uid(); guest uuid; table_name text;
begin
  result:=public.attach_guest_conversation_before_photos(p_token,p_guest_wins);
  select * into attachment from public.user_conversation_attachment where user_id=v_owner and id=(result->>'conversation_id')::uuid;
  if exists(select 1 from public.user_interview_photo_transfer where conversation_id=attachment.id and user_id=v_owner) then return result; end if;
  snapshot:=attachment.workspace->'interview_photos';
  if snapshot is null then return result; end if;
  guest:=(result->>'guest_user_id')::uuid;
  if snapshot is distinct from public.interview_transfer_snapshot(guest,attachment.project_id) then
    raise exception 'guest photo context changed; prepare a new transfer' using errcode='40001'; end if;
  -- The existing canonical transfer has created the destination project and
  -- preserved canonical source/event identities. Private byte paths stay put;
  -- authoritative owner records are rebound, revoking the old guest at once.
  update public.user_interview_photo set user_id=v_owner where user_id=guest and project_id=attachment.project_id;
  foreach table_name in array array['user_interview_turn','user_interview_photo_link','user_interview_plan'] loop
    for original in select value from jsonb_array_elements(coalesce(snapshot->table_name,'[]')) loop
      if original->>'user_id' is distinct from guest::text or original->>'project_id' is distinct from attachment.project_id then
        raise exception 'invalid photo transfer scope' using errcode='42501'; end if;
      original:=original || jsonb_build_object('user_id',v_owner);
      execute format('insert into public.%I select (jsonb_populate_record(null::public.%I,$1)).*',table_name,table_name) using original;
    end loop;
  end loop;
  delete from public.user_interview_plan where user_id=guest and project_id=attachment.project_id;
  delete from public.user_interview_photo_link where user_id=guest and project_id=attachment.project_id;
  delete from public.user_interview_turn where user_id=guest and project_id=attachment.project_id;
  perform public.invalidate_interview_photo_projection(guest,attachment.project_id);
  insert into public.user_interview_photo_transfer values(attachment.id,v_owner);
  return result;
end $$;

-- The last durable publication boundary rechecks lifecycle/ordering under the
-- SAME project lock as source edits and photo deletion, before the old atomic
-- conversation+allowance commit. Legacy turns without this context are intact.
alter function public.commit_user_agent_turn(uuid,text,text,text[],bigint,text,uuid,boolean,text)
  rename to commit_user_agent_turn_before_photos;
revoke all on function public.commit_user_agent_turn_before_photos(uuid,text,text,text[],bigint,text,uuid,boolean,text) from public,anon,authenticated;
create function public.commit_user_agent_turn(
  p_lease_token uuid,p_thread_id text,p_content text,p_source_paths text[] default '{}',
  p_source_sequence bigint default null,p_project_id text default null,p_client_turn_id uuid default null,
  p_user_response boolean default true,p_life_stage text default 'unplaced') returns jsonb
language plpgsql security definer set search_path='' as $$
declare v_owner uuid:=auth.uid(); turn public.user_interview_turn%rowtype; project public.user_memoir_project%rowtype;
  suffix text; prefix text:='Storyteller: ';
begin
  if v_owner is null then raise exception 'authenticated user required' using errcode='42501'; end if;
  select * into project from public.user_memoir_project where user_id=v_owner and project_id=p_project_id for update;
  select * into turn from public.user_interview_turn where user_id=v_owner and project_id=p_project_id and client_turn_id=p_client_turn_id;
  if found and not exists(select 1 from public.user_memory where user_id=v_owner and project_id=p_project_id and client_turn_id=p_client_turn_id) then
    if turn.sequence is distinct from project.interview_sequence or turn.source_sequence is distinct from project.source_sequence or
      turn.policy_epoch is distinct from project.policy_epoch or turn.collector is null or
      (turn.source_id is not null and not exists(select 1 from public.user_narrator_source where user_id=v_owner and project_id=p_project_id
        and id=turn.source_id and version=turn.source_version and status='active')) then
      raise exception 'stale interview publication' using errcode='40001'; end if;
    suffix:=E'\nMemory Spark: ' || (turn.collector->>'reply');
    if p_content is null or length(p_content)<length(prefix)+length(suffix) or left(p_content,length(prefix))<>prefix or
      right(p_content,length(suffix))<>suffix or
      md5(substr(p_content,length(prefix)+1,length(p_content)-length(prefix)-length(suffix))) is distinct from turn.input_hash or
      p_thread_id is distinct from turn.collector->>'thread_id' or p_user_response is distinct from (turn.source_id is not null) then
      raise exception 'interview publication does not match accepted collector' using errcode='22023'; end if;
  end if;
  return public.commit_user_agent_turn_before_photos(p_lease_token,p_thread_id,p_content,p_source_paths,
    p_source_sequence,p_project_id,p_client_turn_id,p_user_response,p_life_stage);
end $$;
revoke all on function public.commit_user_agent_turn(uuid,text,text,text[],bigint,text,uuid,boolean,text) from public,anon;
grant execute on function public.commit_user_agent_turn(uuid,text,text,text[],bigint,text,uuid,boolean,text) to authenticated;

-- Grant only public owner-scoped entry points. Helper functions are never RPCs.
revoke all on function public.begin_user_interview_photo(text,jsonb,uuid),public.finish_user_interview_photo(text,uuid),
  public.read_user_interview_photo(text,uuid),public.interview_photo_card(public.user_interview_photo),
  public.interview_turn_record(public.user_interview_turn),public.read_user_interview_turn(text,uuid),
  public.accept_user_interview_turn(text,uuid,text,text,text,jsonb,jsonb),public.interview_photo_available(uuid,text,text,boolean),
  public.interview_photo_links(uuid,text,text),public.read_user_interview_context(text),
  public.invalidate_interview_photo_projection(uuid,text,boolean),public.reconcile_interview_photo_links(uuid,text),
  public.save_user_interview_plan(text,uuid,jsonb,jsonb,uuid,text,jsonb,text),public.delete_user_interview_photo(text,uuid),
  public.unlink_user_interview_photo(text,uuid),public.invalidate_changed_interview_evidence(),
  public.invalidate_corrected_interview_event(),public.apply_user_memory_events(text,jsonb,jsonb),
  public.memory_event_record(public.user_memory_event),public.claim_memoir_lane(uuid,integer),
  public.interview_transfer_snapshot(uuid,text),public.prepare_guest_conversation_transfer(text,text,jsonb,jsonb,text),
  public.attach_guest_conversation(text,boolean) from public,anon,authenticated;
grant execute on function public.begin_user_interview_photo(text,jsonb,uuid),public.finish_user_interview_photo(text,uuid),
  public.read_user_interview_photo(text,uuid),public.read_user_interview_turn(text,uuid),
  public.accept_user_interview_turn(text,uuid,text,text,text,jsonb,jsonb),public.read_user_interview_context(text),
  public.save_user_interview_plan(text,uuid,jsonb,jsonb,uuid,text,jsonb,text),public.delete_user_interview_photo(text,uuid),
  public.unlink_user_interview_photo(text,uuid),public.apply_user_memory_events(text,jsonb,jsonb),
  public.prepare_guest_conversation_transfer(text,text,jsonb,jsonb,text),public.attach_guest_conversation(text,boolean) to authenticated;
grant execute on function public.claim_memoir_lane(uuid,integer) to service_role;

-- Canonical source/event revocation may reduce a bundle to independently safe
-- sections. Keep each surviving event's photo dependency digest through that
-- restriction, including repeated restrictions of an already-reuse bundle.
-- A removed photo must not appear unchanged merely because metadata was lost.
create or replace function public.safe_memoir_reuse(p_bundle jsonb,p_event_ids text[],p_source_id uuid default null) returns jsonb
language sql immutable set search_path='' as $$
  with safe_sections as (select value s from pg_catalog.jsonb_array_elements(coalesce(p_bundle->'sections','[]'))
    where not exists(select 1 from pg_catalog.jsonb_array_elements_text(value->'event_ids') id where id=any(p_event_ids))
      and not exists(select 1 from pg_catalog.jsonb_array_elements(value->'source_refs') ref where ref->>'source_id'=p_source_id::text)),
  safe_events as (select distinct pg_catalog.jsonb_array_elements_text(s->'event_ids') id from safe_sections)
  select pg_catalog.jsonb_build_object('content_config',p_bundle->'content_config',
    'kind',coalesce(p_bundle->'manuscript'->>'kind',p_bundle->>'kind','sample_chapter'),
    'sections',coalesce((select pg_catalog.jsonb_agg(s) from safe_sections),'[]'),
    'event_manifest',coalesce((select pg_catalog.jsonb_agg(e) from pg_catalog.jsonb_array_elements(coalesce(p_bundle->'event_manifest','[]')) e
      where e->>'id' in(select id from safe_events)),'[]')) ||
    case when p_bundle ? 'photo_association_manifest' then pg_catalog.jsonb_build_object('photo_association_manifest',
      coalesce((select pg_catalog.jsonb_object_agg(key,value) from pg_catalog.jsonb_each(p_bundle->'photo_association_manifest')
        where key in(select id from safe_events)),'{}')) else '{}'::jsonb end
$$;
revoke all on function public.safe_memoir_reuse(jsonb,text[],uuid) from public,anon,authenticated;

commit;
