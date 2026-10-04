-- Issue 6: canonical, owner-scoped original evidence. Additive to PR 3.
begin;

create table if not exists public.user_memoir_project (
  user_id uuid not null references auth.users(id) on delete cascade,
  project_id text not null check(project_id ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$'),
  source_sequence bigint not null default 0,
  event_sequence bigint not null default 0,
  extraction_cursor bigint not null default 0,
  policy_epoch bigint not null default 1,
  primary key(user_id,project_id)
);

create table if not exists public.user_narrator_source (
  id uuid not null default gen_random_uuid(),
  user_id uuid not null,
  project_id text not null,
  client_turn_id uuid not null,
  sequence bigint not null,
  version bigint not null default 1,
  text text not null check(length(text) between 1 and 100000),
  kind text not null check(kind in ('narrator_chat','narrator_transcript')),
  language text not null check(language in ('en-AU','zh-CN')),
  status text not null default 'active' check(status in ('active','withdrawn')),
  processing_status text not null default 'pending' check(processing_status in ('pending','succeeded','retry')),
  created_at timestamptz not null default clock_timestamp(),
  primary key(user_id,project_id,id),
  unique(user_id,project_id,client_turn_id),
  unique(user_id,project_id,sequence),
  foreign key(user_id,project_id) references public.user_memoir_project on delete cascade
);

alter table public.user_memoir_project enable row level security;
alter table public.user_narrator_source enable row level security;
revoke all on public.user_memoir_project,public.user_narrator_source from public,anon,authenticated;
grant select on public.user_memoir_project,public.user_narrator_source to authenticated;
drop policy if exists memoir_project_owner on public.user_memoir_project;
create policy memoir_project_owner on public.user_memoir_project for select to authenticated using(user_id=auth.uid());
drop policy if exists narrator_source_owner on public.user_narrator_source;
create policy narrator_source_owner on public.user_narrator_source for select to authenticated using(user_id=auth.uid());

create table if not exists public.user_narrator_source_version (
  user_id uuid not null, project_id text not null, source_id uuid not null,
  version bigint not null, text text not null, language text not null, attribution jsonb not null default '{"role":"storyteller"}',
  primary key(user_id,project_id,source_id,version),
  foreign key(user_id,project_id,source_id) references public.user_narrator_source on delete cascade
);
create table if not exists public.user_memory_event (
  user_id uuid not null, project_id text not null, id text not null default gen_random_uuid()::text,
  revision bigint not null default 1, kind text not null check(kind in ('event','period')),
  life_stage text not null default 'unplaced' check(life_stage in ('baby','toddler','childhood','adolescence','young_adulthood','midlife','later_life','unplaced')),
  status text not null default 'active' check(status in ('active','unresolved','withdrawn')),
  data jsonb not null, change_sequence bigint not null,
  primary key(user_id,project_id,id),
  foreign key(user_id,project_id) references public.user_memoir_project on delete cascade
);
create index if not exists memory_event_group on public.user_memory_event(user_id,project_id,life_stage,(data->'temporal'->>'year_start'),id);
create table if not exists public.user_memory_event_source (
  user_id uuid not null, project_id text not null, event_id text not null,
  source_id uuid not null, source_version bigint not null, evidence_hash text not null, evidence jsonb not null,
  primary key(user_id,project_id,event_id,source_id,source_version,evidence_hash),
  foreign key(user_id,project_id,event_id) references public.user_memory_event on delete cascade,
  foreign key(user_id,project_id,source_id,source_version) references public.user_narrator_source_version on delete cascade
);
create table if not exists public.user_memory_event_revision (
  user_id uuid not null, project_id text not null, event_id text not null, revision bigint not null,
  record jsonb not null, actor text not null, origin text not null,
  primary key(user_id,project_id,event_id,revision),
  foreign key(user_id,project_id,event_id) references public.user_memory_event on delete cascade
);
alter table public.user_narrator_source_version enable row level security;
alter table public.user_memory_event enable row level security;
alter table public.user_memory_event_source enable row level security;
alter table public.user_memory_event_revision enable row level security;
revoke all on public.user_narrator_source_version,public.user_memory_event,public.user_memory_event_source,public.user_memory_event_revision from public,anon,authenticated;
grant select on public.user_narrator_source_version,public.user_memory_event,public.user_memory_event_source,public.user_memory_event_revision to authenticated;
drop policy if exists source_version_owner on public.user_narrator_source_version;
create policy source_version_owner on public.user_narrator_source_version for select to authenticated using(user_id=auth.uid());
drop policy if exists memory_event_owner on public.user_memory_event;
create policy memory_event_owner on public.user_memory_event for select to authenticated using(user_id=auth.uid());
drop policy if exists event_source_owner on public.user_memory_event_source;
create policy event_source_owner on public.user_memory_event_source for select to authenticated using(user_id=auth.uid());
drop policy if exists event_revision_owner on public.user_memory_event_revision;
create policy event_revision_owner on public.user_memory_event_revision for select to authenticated using(user_id=auth.uid());

alter table public.user_private_draft_outbox drop constraint if exists user_private_draft_outbox_change_kind_check;
alter table public.user_private_draft_outbox add constraint user_private_draft_outbox_change_kind_check
  check(change_kind in ('round','edit','delete','assignment','accepted','events','correction','revocation'));

create or replace function public.narrator_source_record(s public.user_narrator_source) returns jsonb
language sql immutable set search_path='' as $$
  select pg_catalog.jsonb_build_object('id',s.id,'project_id',s.project_id,
    'client_turn_id',s.client_turn_id,'sequence',s.sequence,'version',s.version,
    'text',s.text,'kind',s.kind,'language',s.language,'status',s.status,
    'author_role','storyteller','created_at',s.created_at)
$$;
revoke all on function public.narrator_source_record(public.user_narrator_source) from public,anon,authenticated;

create or replace function public.accept_user_narrator_source(
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
  if (select count(*) from public.user_narrator_source where user_id=owner_id and project_id=p_project_id)>=1000 or
     (select coalesce(sum(length(text)),0) from public.user_narrator_source where user_id=owner_id and project_id=p_project_id)+length(p_text)>120000 then
    raise exception 'memoir evidence exceeds supported bounds' using errcode='22023';
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
revoke all on function public.accept_user_narrator_source(text,uuid,text,text,text) from public,anon;
grant execute on function public.accept_user_narrator_source(text,uuid,text,text,text) to authenticated;

create or replace function public.memory_event_record(e public.user_memory_event) returns jsonb
language sql stable set search_path='' as $$
  select e.data || pg_catalog.jsonb_build_object('id',e.id,'revision',e.revision,'kind',e.kind,
    'life_stage',e.life_stage,'status',e.status,'change_sequence',e.change_sequence,
    'source_refs',coalesce((select pg_catalog.jsonb_agg(s.evidence order by n.sequence,s.source_version,s.evidence_hash)
      from public.user_memory_event_source s join public.user_narrator_source n
        on n.user_id=s.user_id and n.project_id=s.project_id and n.id=s.source_id
      where s.user_id=e.user_id and s.project_id=e.project_id and s.event_id=e.id
        and n.status='active' and n.version=s.source_version),'[]'::jsonb))
$$;
revoke all on function public.memory_event_record(public.user_memory_event) from public,anon,authenticated;

create or replace function public.read_user_memory_events(p_project_id text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare owner_id uuid:=auth.uid(); project public.user_memoir_project%rowtype;
begin
  if owner_id is null then raise exception 'authenticated user required' using errcode='42501'; end if;
  select * into project from public.user_memoir_project where user_id=owner_id and project_id=p_project_id;
  return pg_catalog.jsonb_build_object('schema_version',1,'project_id',p_project_id,
    'events',coalesce((select pg_catalog.jsonb_agg(public.memory_event_record(e) order by change_sequence,id)
      from public.user_memory_event e where user_id=owner_id and project_id=p_project_id and status<>'withdrawn'),'[]'::jsonb),
    'sources',coalesce((select pg_catalog.jsonb_agg(public.narrator_source_record(s) order by sequence)
      from public.user_narrator_source s where user_id=owner_id and project_id=p_project_id),'[]'::jsonb),
    'completed_rounds',(select count(*) from public.user_completed_round where user_id=owner_id and project_id=p_project_id),
    'processing',pg_catalog.jsonb_build_object('extracted_through',coalesce(project.extraction_cursor,0),
      'pending_inputs',(select count(*) from public.user_narrator_source where user_id=owner_id and project_id=p_project_id and processing_status<>'succeeded')));
end $$;
revoke all on function public.read_user_memory_events(text) from public,anon;
grant execute on function public.read_user_memory_events(text) to authenticated;

create or replace function public.validate_memory_evidence(p_owner uuid,p_project_id text,p_ref jsonb) returns void
language plpgsql security definer set search_path='' as $$
declare original public.user_narrator_source%rowtype; start_offset integer; end_offset integer;
begin
  select * into original from public.user_narrator_source where user_id=p_owner and project_id=p_project_id and id=(p_ref->>'source_id')::uuid;
  if not found then raise exception 'evidence source unavailable' using errcode='42501'; end if;
  if original.status<>'active' or original.version is distinct from (p_ref->>'version')::bigint then
    raise exception 'evidence revision conflict' using errcode='40001'; end if;
  if length(coalesce(p_ref->>'quote','')) not between 1 and 2000 or pg_catalog.strpos(original.text,p_ref->>'quote')=0 then
    raise exception 'evidence quote must match original testimony' using errcode='22023'; end if;
  start_offset:=(p_ref->>'char_start')::integer; end_offset:=(p_ref->>'char_end')::integer;
  if (start_offset is null)<>(end_offset is null) or (start_offset is not null and
    (start_offset<0 or end_offset<=start_offset or pg_catalog.substr(original.text,start_offset+1,end_offset-start_offset) is distinct from p_ref->>'quote')) then
    raise exception 'evidence span must match original testimony' using errcode='22023'; end if;
end $$;
revoke all on function public.validate_memory_evidence(uuid,text,jsonb) from public,anon,authenticated;

create or replace function public.memory_age_number(p_text text) returns integer
language plpgsql immutable set search_path='' as $$
declare matches text[]; word text; number integer; unit integer; tens integer;
  small text[]:=array['zero','one','two','three','four','five','six','seven','eight','nine','ten','eleven','twelve','thirteen','fourteen','fifteen','sixteen','seventeen','eighteen','nineteen'];
begin
  matches:=pg_catalog.regexp_match(p_text,'(?:at age |aged |age |when I was )([0-9]{1,3})','i');
  if matches is null then matches:=pg_catalog.regexp_match(p_text,'([0-9]{1,3})\s*(?:years old|岁)'); end if;
  if matches is not null then return matches[1]::integer; end if;
  matches:=pg_catalog.regexp_match(p_text,'(?:at age|aged|age|at|when I was)\s+([a-z]+)(?:[-\s]+([a-z]+))?','i');
  if matches is not null then
    number:=pg_catalog.array_position(small,pg_catalog.lower(matches[1]))-1;
    if number is not null then return number; end if;
    tens:=(pg_catalog.array_position(array['twenty','thirty','forty','fifty','sixty','seventy','eighty','ninety'],pg_catalog.lower(matches[1]))+1)*10;
    if tens is not null then
      unit:=pg_catalog.array_position(small,pg_catalog.lower(matches[2]))-1;
      return tens+case when unit between 1 and 9 then unit else 0 end;
    end if;
  end if;
  matches:=pg_catalog.regexp_match(p_text,'([一二三四五六七八九十两]{1,3})岁');
  if matches is not null then
    word:=pg_catalog.replace(matches[1],'两','二');
    if pg_catalog.strpos(word,'十')>0 then
      tens:=case when pg_catalog.left(word,1)='十' then 1 else pg_catalog.strpos('一二三四五六七八九',pg_catalog.left(word,1)) end;
      unit:=case when pg_catalog.right(word,1)='十' then 0 else pg_catalog.strpos('一二三四五六七八九',pg_catalog.right(word,1)) end;
      if tens>0 then return tens*10+unit; end if;
    elsif length(word)=1 then return nullif(pg_catalog.strpos('一二三四五六七八九',word),0); end if;
  end if;
  return null;
end $$;
revoke all on function public.memory_age_number(text) from public,anon,authenticated;

create or replace function public.validate_memory_temporal(p_owner uuid,p_project_id text,p_temporal jsonb) returns void
language plpgsql security definer set search_path='' as $$
declare basis jsonb; birth_basis jsonb; target_year integer; age_number integer; birth_match text[]; supported boolean;
begin
  if pg_catalog.jsonb_typeof(p_temporal) is distinct from 'object' or
     p_temporal->>'precision' is null or p_temporal->>'precision' not in ('unknown','day','month','year','range','approximate','age','season') or
     length(coalesce(p_temporal->>'expression','')) not between 1 and 500 then
    raise exception 'invalid temporal placement' using errcode='22023'; end if;
  if (p_temporal->>'year_start')::integer>(p_temporal->>'year_end')::integer then
    raise exception 'invalid temporal range' using errcode='22023'; end if;
  for basis in select value from pg_catalog.jsonb_array_elements(coalesce(p_temporal->'basis','[]')) loop
    perform public.validate_memory_evidence(p_owner,p_project_id,basis);
  end loop;
  for target_year in select (p_temporal->>'year_start')::integer union select (p_temporal->>'year_end')::integer loop
    if target_year is null then continue; end if;
    if target_year not between 1 and 9999 or p_temporal->>'precision'='unknown' then
      raise exception 'unsupported numeric date' using errcode='22023'; end if;
    supported:=false;
    if p_temporal->>'precision'='age' then
      for basis in select value from pg_catalog.jsonb_array_elements(coalesce(p_temporal->'basis','[]')) loop
        age_number:=public.memory_age_number(basis->>'quote');
        if age_number is not null then
          for birth_basis in select value from pg_catalog.jsonb_array_elements(p_temporal->'basis') loop
            if birth_basis->>'quote' ~* '(born|birth|出生)' then
              birth_match:=pg_catalog.regexp_match(birth_basis->>'quote','([0-9]{4})');
              if birth_match is not null and birth_match[1]::integer+age_number=target_year then supported:=true; end if;
            end if;
          end loop;
        end if;
      end loop;
    else
      select exists(select 1 from pg_catalog.jsonb_array_elements(coalesce(p_temporal->'basis','[]')) b
        where b->>'quote' ~ ('(^|[^0-9])'||target_year::text||'([^0-9]|$)')) into supported;
    end if;
    if not supported then raise exception 'numeric date requires supported original evidence' using errcode='22023'; end if;
  end loop;
  if p_temporal->>'expression'<>'unknown' and not exists
      (select 1 from pg_catalog.jsonb_array_elements(coalesce(p_temporal->'basis','[]')) b where pg_catalog.strpos(b->>'quote',p_temporal->>'expression')>0) then
    raise exception 'date expression requires its original evidence' using errcode='22023'; end if;
end $$;
revoke all on function public.validate_memory_temporal(uuid,text,jsonb) from public,anon,authenticated;

create or replace function public.apply_user_memory_events(p_project_id text,p_sources jsonb,p_events jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare owner_id uuid:=auth.uid(); item jsonb; saved public.user_narrator_source%rowtype; updated integer;
  proposal jsonb; ref jsonb; relation jsonb; evidence public.user_narrator_source%rowtype;
  current_event public.user_memory_event%rowtype; event_id text; event_data jsonb; event_stage text; next_change bigint;
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
    if proposal ? 'candidate_ids' and ((proposal ? 'existing_id') or exists(select 1 from pg_catalog.jsonb_array_elements_text(proposal->'candidate_ids') candidate
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
    event_data:=coalesce(current_event.data,'{"temporal":{"expression":"unknown","precision":"unknown"},"visibility":"private","include_in_print":false}'::jsonb) ||
      (proposal - array['id','existing_id','expected_revision','source_refs','kind','life_stage']);
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
    for ref in select value from pg_catalog.jsonb_array_elements(proposal->'source_refs') loop
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
    update public.user_memoir_project set event_sequence=event_sequence+1
      where user_id=owner_id and project_id=p_project_id returning event_sequence into next_change;
    insert into public.user_memory_event(user_id,project_id,id,revision,kind,life_stage,status,data,change_sequence)
      values(owner_id,p_project_id,event_id,coalesce(current_event.revision,0)+1,proposal->>'kind',event_stage,
        case when proposal ? 'candidate_ids' then 'unresolved' else 'active' end,event_data,next_change)
      on conflict(user_id,project_id,id) do update set revision=excluded.revision,life_stage=excluded.life_stage,
        data=excluded.data,status=excluded.status,change_sequence=excluded.change_sequence;
    for ref in select value from pg_catalog.jsonb_array_elements(proposal->'source_refs') loop
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

create or replace function public.correct_user_memory_event(
  p_project_id text,p_event_id text,p_expected_revision bigint,p_patch jsonb,p_statement text,
  p_origin text default 'workspace',p_source_id uuid default null
) returns jsonb language plpgsql security definer set search_path='' as $$
declare owner_id uuid:=auth.uid(); saved public.user_memory_event%rowtype; patch_key text; overrides jsonb; next_change bigint;
  correction_source jsonb; correction_ref jsonb;
begin
  if owner_id is null then raise exception 'authenticated user required' using errcode='42501'; end if;
  if p_origin not in ('workspace','chat') or (p_origin='workspace' and p_source_id is not null) then
    raise exception 'invalid correction origin' using errcode='22023'; end if;
  if pg_catalog.jsonb_typeof(p_patch) is distinct from 'object' or p_patch='{}'::jsonb or
     exists(select 1 from pg_catalog.jsonb_object_keys(p_patch) k where k not in ('life_stage','temporal','visibility','include_in_print')) or
     length(pg_catalog.btrim(coalesce(p_statement,''))) not between 1 and 2000 then
    raise exception 'invalid explicit correction' using errcode='22023';
  end if;
  perform 1 from public.user_memoir_project where user_id=owner_id and project_id=p_project_id for update;
  select * into saved from public.user_memory_event where user_id=owner_id and project_id=p_project_id and id=p_event_id for update;
  if not found then raise exception 'event unavailable' using errcode='42501'; end if;
  if saved.revision is distinct from p_expected_revision then
    raise exception 'event revision conflict; reload the event' using errcode='40001';
  end if;
  if p_patch ? 'life_stage' and (p_patch->>'life_stage' is null or p_patch->>'life_stage' not in
    ('baby','toddler','childhood','adolescence','young_adulthood','midlife','later_life','unplaced')) then
    raise exception 'invalid life stage' using errcode='22023';
  end if;
  if p_patch ? 'temporal' and (pg_catalog.jsonb_typeof(p_patch->'temporal') is distinct from 'object' or
    p_patch->'temporal'->>'precision' is null or p_patch->'temporal'->>'precision' not in ('unknown','day','month','year','range','approximate','age','season') or
    length(coalesce(p_patch->'temporal'->>'expression','')) not between 1 and 500) then
    raise exception 'invalid temporal correction' using errcode='22023';
  end if;
  overrides:=coalesce(saved.data->'user_overrides','{}'::jsonb);
  if p_origin='chat' then
    select public.narrator_source_record(s) into correction_source from public.user_narrator_source s
      where user_id=owner_id and project_id=p_project_id and id=p_source_id and status='active' and text=p_statement;
    if correction_source is null or p_statement !~* '(correct|actually|year was|i meant|should be|更正|纠正|应该|其实|不是)' then
      raise exception 'explicit chat correction source unavailable' using errcode='42501'; end if;
  else
    correction_source:=public.accept_user_narrator_source(p_project_id,pg_catalog.gen_random_uuid(),p_statement,'narrator_chat',
      case when p_statement ~ '[一-鿿]' then 'zh-CN' else 'en-AU' end);
  end if;
  update public.user_narrator_source set processing_status='succeeded' where user_id=owner_id and project_id=p_project_id and id=(correction_source->>'id')::uuid;
  correction_ref:=pg_catalog.jsonb_build_object('source_id',correction_source->>'id','version',correction_source->'version','quote',p_statement,'attribution',owner_id::text);
  if p_patch ? 'temporal' then p_patch:=pg_catalog.jsonb_set(p_patch,'{temporal,basis}',pg_catalog.jsonb_build_array(correction_ref)); end if;
  if p_patch ? 'temporal' then perform public.validate_memory_temporal(owner_id,p_project_id,p_patch->'temporal'); end if;
  if p_patch ? 'life_stage' then
    p_patch:=p_patch || pg_catalog.jsonb_build_object('stage_evidence',pg_catalog.jsonb_build_array(correction_ref));
  end if;
  insert into public.user_memory_event_source(user_id,project_id,event_id,source_id,source_version,evidence_hash,evidence)
    values(owner_id,p_project_id,p_event_id,(correction_source->>'id')::uuid,(correction_source->>'version')::bigint,pg_catalog.md5(correction_ref::text),correction_ref) on conflict do nothing;
  for patch_key in select pg_catalog.jsonb_object_keys(p_patch) loop
    overrides:=overrides || pg_catalog.jsonb_build_object(patch_key,pg_catalog.jsonb_build_object(
      'actor',owner_id,'origin',p_origin,'statement',p_statement,'expected_revision',p_expected_revision));
  end loop;
  update public.user_memoir_project set event_sequence=event_sequence+1,policy_epoch=policy_epoch+1
    where user_id=owner_id and project_id=p_project_id returning event_sequence into next_change;
  update public.user_memory_event set data=(data || (p_patch-'life_stage')) || pg_catalog.jsonb_build_object('user_overrides',overrides),
    life_stage=coalesce(p_patch->>'life_stage',life_stage),revision=revision+1,change_sequence=next_change
    where user_id=owner_id and project_id=p_project_id and id=p_event_id returning * into saved;
  insert into public.user_memory_event_revision(user_id,project_id,event_id,revision,record,actor,origin)
    values(owner_id,p_project_id,p_event_id,saved.revision,public.memory_event_record(saved),owner_id::text,p_origin);
  insert into public.user_private_draft_outbox(user_id,project_id,change_kind) values(owner_id,p_project_id,'correction');
  update public.user_memoir_project set extraction_cursor=coalesce((select min(sequence)-1 from public.user_narrator_source
    where user_id=owner_id and project_id=p_project_id and status='active' and processing_status<>'succeeded'),source_sequence)
    where user_id=owner_id and project_id=p_project_id;
  return public.memory_event_record(saved);
end $$;
revoke all on function public.correct_user_memory_event(text,text,bigint,jsonb,text,text,uuid) from public,anon;
grant execute on function public.correct_user_memory_event(text,text,bigint,jsonb,text,text,uuid) to authenticated;

commit;
