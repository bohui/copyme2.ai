-- W5: transactional, metadata-only required projections; raw artifacts remain
-- optional. No deployment, historical backfill, object deletion or retention
-- change. Existing source/reply receipts and commercial counters are untouched.
begin;

create table public.user_lifetime_memory_obligation (
  id uuid primary key default gen_random_uuid(), user_id uuid not null,
  conversation_id uuid not null, project_id text not null,
  kind text not null check(kind in ('source_projection','reply_projection')),
  dedup_key text not null check(length(dedup_key) between 1 and 200),
  origin_id uuid not null, origin_hash text, source_id uuid, source_version bigint,
  policy_epoch bigint not null, source_revision bigint not null, execution_generation bigint not null,
  status text not null default 'pending' check(status in ('pending','running','retryable','succeeded','failed','cancelled','superseded')),
  attempts integer not null default 0 check(attempts between 0 and 5),
  next_attempt_at timestamptz not null default clock_timestamp(),
  claim_token uuid, claim_expires_at timestamptz, fence jsonb,
  error_code text check(error_code in ('projection_failed','storage_unavailable','manifest_incomplete','retry_exhausted','stale_origin')),
  projection jsonb, created_at timestamptz not null default clock_timestamp(),
  updated_at timestamptz not null default clock_timestamp(),
  unique(user_id,conversation_id,dedup_key),
  foreign key(user_id,conversation_id) references public.user_lifetime_conversation(user_id,conversation_id) on delete cascade,
  foreign key(user_id,project_id) references public.user_memoir_project(user_id,project_id) on delete cascade
);
create index lifetime_obligation_ready on public.user_lifetime_memory_obligation(user_id,conversation_id,status,next_attempt_at,created_at,id);
alter table public.user_lifetime_memory_obligation enable row level security;
revoke all on public.user_lifetime_memory_obligation from public,anon,authenticated;

create table public.user_lifetime_optional_artifact (
  user_id uuid not null, conversation_id uuid not null, manifest_id text not null check(manifest_id ~ '^[a-f0-9]{64}$'),
  fence jsonb not null, manifest_wire text, complete boolean not null, linked boolean not null default true,
  created_at timestamptz not null default clock_timestamp(),
  primary key(user_id,conversation_id,manifest_id),
  foreign key(user_id,conversation_id) references public.user_lifetime_conversation(user_id,conversation_id) on delete cascade
);
alter table public.user_lifetime_optional_artifact enable row level security;
revoke all on public.user_lifetime_optional_artifact from public,anon,authenticated;

-- Keep one normalized effective state, not one full-state copy per delta.
-- These are logical projection references only; deleting them never deletes
-- content-addressed storage objects or changes the object's retention policy.
create table public.user_lifetime_artifact_head (
  user_id uuid not null, conversation_id uuid not null, manifest_id text not null,
  primary key(user_id,conversation_id),
  foreign key(user_id,conversation_id) references public.user_lifetime_conversation(user_id,conversation_id) on delete cascade
);
create table public.user_lifetime_artifact_file (
  user_id uuid not null, conversation_id uuid not null, path text not null,
  byte_count bigint not null check(byte_count between 0 and 134217728),
  primary key(user_id,conversation_id,path),
  foreign key(user_id,conversation_id) references public.user_lifetime_artifact_head(user_id,conversation_id) on delete cascade
);
create table public.user_lifetime_artifact_chunk (
  user_id uuid not null, conversation_id uuid not null, path text not null,
  chunk_offset bigint not null check(chunk_offset>=0), byte_count bigint not null check(byte_count between 1 and 1048576),
  object_key text not null, content_sha256 text not null,
  primary key(user_id,conversation_id,path,chunk_offset),
  foreign key(user_id,conversation_id,path) references public.user_lifetime_artifact_file(user_id,conversation_id,path) on delete cascade
);
alter table public.user_lifetime_artifact_head enable row level security;
alter table public.user_lifetime_artifact_file enable row level security;
alter table public.user_lifetime_artifact_chunk enable row level security;
revoke all on public.user_lifetime_artifact_head,public.user_lifetime_artifact_file,public.user_lifetime_artifact_chunk from public,anon,authenticated;

create function public.enqueue_lifetime_source_obligation() returns trigger
language plpgsql security definer set search_path='' as $$
declare identity public.user_lifetime_conversation%rowtype; epoch bigint;
begin
  select * into identity from public.user_lifetime_conversation where user_id=new.user_id and project_id=new.project_id;
  if not found then return new; end if;
  if tg_op='UPDATE' and old.version=new.version and old.status=new.status then return new; end if;
  select policy_epoch into epoch from public.user_memoir_project where user_id=new.user_id and project_id=new.project_id;
  insert into public.user_lifetime_memory_obligation(user_id,conversation_id,project_id,kind,dedup_key,origin_id,
    source_id,source_version,policy_epoch,source_revision,execution_generation)
  values(new.user_id,identity.conversation_id,new.project_id,'source_projection','source:'||new.id||':'||new.version||':'||new.status,
    new.id,new.id,new.version,epoch,new.sequence,identity.execution_generation) on conflict do nothing;
  return new;
end $$;
create trigger lifetime_source_obligation after insert or update of version,status on public.user_narrator_source
 for each row execute function public.enqueue_lifetime_source_obligation();

create function public.enqueue_lifetime_reply_obligation() returns trigger
language plpgsql security definer set search_path='' as $$
declare identity public.user_lifetime_conversation%rowtype; project public.user_memoir_project%rowtype;
  source public.user_narrator_source%rowtype; fingerprint text;
begin
  if new.project_id is null or new.client_turn_id is null or new.kind not in ('agent','agent_greeting') then return new; end if;
  if tg_op='UPDATE' and old.project_id is not distinct from new.project_id and old.client_turn_id is not distinct from new.client_turn_id
    and old.content is not distinct from new.content then return new; end if;
  select * into identity from public.user_lifetime_conversation where user_id=new.user_id and project_id=new.project_id;
  if not found then return new; end if;
  select * into project from public.user_memoir_project where user_id=new.user_id and project_id=new.project_id;
  select * into source from public.user_narrator_source where user_id=new.user_id and project_id=new.project_id and client_turn_id=new.client_turn_id;
  fingerprint:=encode(sha256(convert_to(new.content,'UTF8')),'hex');
  update public.user_lifetime_memory_obligation set status='superseded',projection=null,claim_token=null,claim_expires_at=null,
    updated_at=clock_timestamp() where user_id=new.user_id and conversation_id=identity.conversation_id
    and kind='reply_projection' and origin_id=new.id and origin_hash is distinct from fingerprint;
  insert into public.user_lifetime_memory_obligation(user_id,conversation_id,project_id,kind,dedup_key,origin_id,origin_hash,
    source_id,source_version,policy_epoch,source_revision,execution_generation)
  values(new.user_id,identity.conversation_id,new.project_id,'reply_projection','reply:'||new.id||':'||fingerprint,new.id,fingerprint,
    source.id,source.version,project.policy_epoch,project.source_sequence,identity.execution_generation) on conflict do nothing;
  return new;
end $$;
create trigger lifetime_reply_obligation after insert or update of project_id,client_turn_id,content on public.user_memory
 for each row execute function public.enqueue_lifetime_reply_obligation();

create function public.invalidate_lifetime_obligations() returns trigger
language plpgsql security definer set search_path='' as $$
begin
  if old.policy_epoch is distinct from new.policy_epoch then
    update public.user_lifetime_memory_obligation set status='superseded',projection=null,claim_token=null,claim_expires_at=null,
      updated_at=clock_timestamp() where user_id=new.user_id and project_id=new.project_id and policy_epoch<>new.policy_epoch;
    delete from public.user_lifetime_artifact_head h using public.user_lifetime_conversation l
      where h.user_id=l.user_id and h.conversation_id=l.conversation_id and l.user_id=new.user_id and l.project_id=new.project_id;
    update public.user_lifetime_optional_artifact a set linked=false,manifest_wire=null from public.user_lifetime_conversation l
      where a.user_id=l.user_id and a.conversation_id=l.conversation_id and l.user_id=new.user_id and l.project_id=new.project_id;
  end if;
  return new;
end $$;
create trigger lifetime_obligation_invalidation after update of policy_epoch on public.user_memoir_project
 for each row execute function public.invalidate_lifetime_obligations();

create function public.lifetime_obligation_record(o public.user_lifetime_memory_obligation) returns jsonb
language sql stable set search_path='' as $$
 select pg_catalog.to_jsonb(o)-'user_id'-'origin_hash' || pg_catalog.jsonb_build_object('schema_version',1,'required',true,'backup_complete',false)
$$;

create function public.lifetime_obligation_origin_current(o public.user_lifetime_memory_obligation) returns boolean
language sql stable security definer set search_path='' as $$
 select (o.source_id is null or exists(select 1 from public.user_narrator_source s where s.user_id=o.user_id
   and s.project_id=o.project_id and s.id=o.source_id and s.version=o.source_version
   and (o.kind='source_projection' or s.status='active')))
 and (o.kind='source_projection' or exists(select 1 from public.user_memory m where m.user_id=o.user_id
   and m.project_id=o.project_id and m.id=o.origin_id and pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(m.content,'UTF8')),'hex')=o.origin_hash))
$$;

create function public.claim_lifetime_memory_obligation(p_fence jsonb) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare owner uuid:=auth.uid(); conversation uuid:=(p_fence->'identity'->>'conversation_id')::uuid;
  project text; saved public.user_lifetime_memory_obligation%rowtype;
begin
  select project_id into project from public.user_lifetime_conversation where user_id=owner and conversation_id=conversation;
  if not found then raise exception 'conversation unavailable'; end if;
  perform 1 from public.user_memoir_project where user_id=owner and project_id=project for update;
  perform public.lock_lifetime_publication(p_fence);
  -- Inspect/retire at most 32 obsolete or exhausted entries per bounded claim.
  for saved in select * from public.user_lifetime_memory_obligation where user_id=owner and conversation_id=conversation
    and (status in ('pending','retryable') and next_attempt_at<=clock_timestamp()
      or status='running' and claim_expires_at<=clock_timestamp()) order by created_at,id limit 32 for update skip locked
  loop
    if saved.policy_epoch<>(p_fence->>'policy_epoch')::bigint or saved.execution_generation<>(p_fence->>'execution_generation')::bigint
      or not public.lifetime_obligation_origin_current(saved) then
      update public.user_lifetime_memory_obligation set status='superseded',projection=null,claim_token=null,claim_expires_at=null,
        error_code='stale_origin',updated_at=clock_timestamp() where id=saved.id;
      continue;
    end if;
    if saved.attempts>=5 then
      update public.user_lifetime_memory_obligation set status='failed',error_code='retry_exhausted',claim_token=null,claim_expires_at=null,
        updated_at=clock_timestamp() where id=saved.id;
      continue;
    end if;
    update public.user_lifetime_memory_obligation set status='running',attempts=attempts+1,claim_token=gen_random_uuid(),
      claim_expires_at=least(clock_timestamp()+interval '60 seconds',(select expires_at from public.user_agent_turn_lease where user_id=owner)),
      fence=p_fence,error_code=null,updated_at=clock_timestamp() where id=saved.id returning * into saved;
    return public.lifetime_obligation_record(saved);
  end loop;
  if exists(select 1 from public.user_lifetime_memory_obligation where user_id=owner and conversation_id=conversation
    and status in ('pending','running','retryable','failed')) then
    return jsonb_build_object('status','not_ready','backup_complete',false);
  end if;
  return null;
end $$;

create function public.complete_lifetime_memory_obligation(p_fence jsonb,p_id uuid,p_claim_token uuid) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare saved public.user_lifetime_memory_obligation%rowtype; refs jsonb; source public.user_narrator_source%rowtype;
begin
  select * into saved from public.user_lifetime_memory_obligation where id=p_id and user_id=auth.uid();
  if not found then raise exception 'obligation unavailable'; end if;
  perform 1 from public.user_memoir_project where user_id=auth.uid() and project_id=saved.project_id for update;
  perform public.lock_lifetime_publication(p_fence);
  select * into saved from public.user_lifetime_memory_obligation where id=p_id and user_id=auth.uid() for update;
  if saved.fence is distinct from p_fence or saved.claim_token is distinct from p_claim_token or p_claim_token is null
    or saved.status not in ('running','succeeded') or saved.claim_expires_at<=clock_timestamp()
    or not public.lifetime_obligation_origin_current(saved) then raise exception 'stale obligation claim' using errcode='40001'; end if;
  if saved.status='succeeded' then return public.lifetime_obligation_record(saved); end if;
  select * into source from public.user_narrator_source where user_id=saved.user_id and project_id=saved.project_id
    and id=saved.source_id and version=saved.source_version and status='active';
  refs:='[]';
  if found then
    select jsonb_agg(jsonb_build_object('source_id',source.id,'version',source.version,'char_start',offset_value,
      'char_end',least(offset_value+2048,length(source.text))) order by offset_value) into refs
      from generate_series(0,length(source.text)-1,2048) offset_value;
  end if;
  update public.user_lifetime_memory_obligation set status='succeeded',error_code=null,updated_at=clock_timestamp(),
    projection=jsonb_build_object('schema_version',1,'kind','canonical_references','origin_id',saved.origin_id,
      'policy_epoch',saved.policy_epoch,'sources',coalesce(refs,'[]'),'canonical_recovery_required',false)
    where id=p_id returning * into saved;
  return public.lifetime_obligation_record(saved);
end $$;

create function public.fail_lifetime_memory_obligation(p_fence jsonb,p_id uuid,p_claim_token uuid,p_error_code text) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare saved public.user_lifetime_memory_obligation%rowtype;
begin
  if p_error_code is null or p_error_code not in ('projection_failed','storage_unavailable','manifest_incomplete') then raise exception 'bounded error code required'; end if;
  select * into saved from public.user_lifetime_memory_obligation where id=p_id and user_id=auth.uid();
  if not found then raise exception 'obligation unavailable'; end if;
  perform 1 from public.user_memoir_project where user_id=auth.uid() and project_id=saved.project_id for update;
  perform public.lock_lifetime_publication(p_fence);
  select * into saved from public.user_lifetime_memory_obligation where id=p_id and user_id=auth.uid() for update;
  if saved.fence is distinct from p_fence or saved.claim_token is distinct from p_claim_token or p_claim_token is null
    or saved.status<>'running' or saved.claim_expires_at<=clock_timestamp() then raise exception 'stale obligation claim' using errcode='40001'; end if;
  update public.user_lifetime_memory_obligation set status=case when attempts>=5 then 'failed' else 'retryable' end,
    next_attempt_at=clock_timestamp()+make_interval(secs=>least(3600,(5*power(2,attempts-1))::integer)),
    error_code=p_error_code,claim_token=null,claim_expires_at=null,updated_at=clock_timestamp() where id=p_id returning * into saved;
  return public.lifetime_obligation_record(saved);
end $$;

create function public.cancel_lifetime_memory_obligation(p_fence jsonb,p_id uuid) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare saved public.user_lifetime_memory_obligation%rowtype;
begin
  select * into saved from public.user_lifetime_memory_obligation where id=p_id and user_id=auth.uid();
  if not found then raise exception 'obligation unavailable'; end if;
  perform 1 from public.user_memoir_project where user_id=auth.uid() and project_id=saved.project_id for update;
  perform public.lock_lifetime_publication(p_fence);
  if saved.conversation_id is distinct from (p_fence->'identity'->>'conversation_id')::uuid then raise exception 'obligation conversation mismatch'; end if;
  update public.user_lifetime_memory_obligation set status='cancelled',projection=null,claim_token=null,claim_expires_at=null,
    updated_at=clock_timestamp() where id=p_id returning * into saved;
  return public.lifetime_obligation_record(saved);
end $$;

create function public.read_lifetime_memory_obligations(p_conversation_id uuid,p_after uuid default null,p_limit integer default 32) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare records jsonb; more boolean; cursor_time timestamptz;
begin
  if not exists(select 1 from public.user_lifetime_conversation where user_id=auth.uid() and conversation_id=p_conversation_id) then raise exception 'conversation unavailable'; end if;
  if p_limit is null or p_limit not between 1 and 32 then raise exception 'invalid inspection bounds'; end if;
  if p_after is not null and not exists(select 1 from public.user_lifetime_memory_obligation where user_id=auth.uid()
    and conversation_id=p_conversation_id and id=p_after) then raise exception 'invalid inspection cursor'; end if;
  if p_after is not null then select created_at into cursor_time from public.user_lifetime_memory_obligation where id=p_after; end if;
  select coalesce(jsonb_agg(public.lifetime_obligation_record(o) order by o.created_at,o.id),'[]') into records from
    (select * from public.user_lifetime_memory_obligation where user_id=auth.uid() and conversation_id=p_conversation_id
      and (p_after is null or (created_at,id)>(cursor_time,p_after)) order by created_at,id limit p_limit+1) o;
  more:=jsonb_array_length(records)>p_limit;
  if more then records:=records-p_limit; end if;
  return jsonb_build_object('schema_version',1,'records',records,'complete',not more,'next_cursor',case when more then records->-1->>'id' else null end,'backup_complete',false);
end $$;

create function public.link_lifetime_optional_artifact(p_fence jsonb,p_manifest_id text,p_manifest text default null,p_authorized boolean default false) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare owner uuid:=auth.uid(); conversation uuid:=(p_fence->'identity'->>'conversation_id')::uuid; project text;
  manifest jsonb; file jsonb; chunk jsonb; artifact_path text; head text; covered_bytes bigint;
  saved public.user_lifetime_optional_artifact%rowtype;
begin
  if p_authorized is distinct from true then raise exception 'explicit optional artifact authorization required'; end if;
  select project_id into project from public.user_lifetime_conversation where user_id=owner and conversation_id=conversation;
  if not found then raise exception 'conversation unavailable'; end if;
  perform 1 from public.user_memoir_project where user_id=owner and project_id=project for update;
  perform public.lock_lifetime_publication(p_fence);
  if p_manifest_id is null or p_manifest_id!~'^[a-f0-9]{64}$' then raise exception 'invalid manifest digest'; end if;
  select manifest_id into head from public.user_lifetime_artifact_head where user_id=owner and conversation_id=conversation;
  select * into saved from public.user_lifetime_optional_artifact where user_id=owner and conversation_id=conversation and manifest_id=p_manifest_id;
  if p_manifest is null then
    if not found or head is distinct from p_manifest_id or not saved.linked or saved.fence->'identity' is distinct from p_fence->'identity'
      or saved.fence->'policy_epoch' is distinct from p_fence->'policy_epoch'
      or saved.fence->'execution_generation' is distinct from p_fence->'execution_generation' then raise exception 'accepted authorized artifact predecessor required'; end if;
    update public.user_lifetime_optional_artifact set fence=p_fence where user_id=owner and conversation_id=conversation and manifest_id=p_manifest_id;
  else
    if octet_length(p_manifest)>1048576 or encode(sha256(convert_to(p_manifest,'UTF8')),'hex') is distinct from p_manifest_id then raise exception 'manifest size or digest mismatch'; end if;
    manifest:=p_manifest::jsonb;
    if jsonb_typeof(manifest) is distinct from 'object' or exists(select 1 from jsonb_object_keys(manifest) k where k not in
      ('schema_version','owner_id','conversation_id','policy_epoch','execution_generation','snapshot_semantics','files','removed_paths','omissions','complete','canonical_recovery_required','status','predecessor'))
      or not (manifest ?& array['schema_version','owner_id','conversation_id','policy_epoch','execution_generation','snapshot_semantics','files','removed_paths','omissions','complete','canonical_recovery_required','status','predecessor'])
      or manifest->'schema_version' is distinct from '3'::jsonb or manifest->>'owner_id' is distinct from owner::text
      or manifest->>'conversation_id' is distinct from conversation::text or manifest->'policy_epoch' is distinct from p_fence->'policy_epoch'
      or manifest->'execution_generation' is distinct from p_fence->'execution_generation'
      or manifest->>'snapshot_semantics' is distinct from 'full_authorized_snapshot'
      or manifest->>'status' is distinct from 'unlinked_candidate' or manifest->'canonical_recovery_required' is distinct from 'false'::jsonb
      or jsonb_typeof(manifest->'complete') is distinct from 'boolean' or jsonb_typeof(manifest->'files') is distinct from 'array'
      or jsonb_typeof(manifest->'removed_paths') is distinct from 'array' or jsonb_typeof(manifest->'omissions') is distinct from 'array' then raise exception 'invalid artifact envelope'; end if;
    if jsonb_array_length(manifest->'files')>256 or jsonb_array_length(manifest->'removed_paths')>256 or jsonb_array_length(manifest->'omissions')>257
      or (manifest->'complete'='true'::jsonb and jsonb_array_length(manifest->'omissions')>0) then raise exception 'bounded honest artifact manifest required'; end if;
    if manifest->>'predecessor' is not null and not exists(select 1 from public.user_lifetime_optional_artifact a
      where a.user_id=owner and a.conversation_id=conversation and a.manifest_id=manifest->>'predecessor' and a.linked
      and a.fence->'identity'=p_fence->'identity' and a.fence->'policy_epoch'=p_fence->'policy_epoch'
      and a.fence->'execution_generation'=p_fence->'execution_generation') then
      raise exception 'accepted current artifact predecessor required'; end if;
    if (select count(*)<>count(distinct value->>'path') from jsonb_array_elements(manifest->'files'))
      or (select count(*)<>count(distinct value) from jsonb_array_elements(manifest->'removed_paths'))
      or exists(select 1 from jsonb_array_elements(manifest->'files') f where manifest->'removed_paths' @> jsonb_build_array(f->>'path')) then
      raise exception 'duplicate or conflicting artifact paths';
    end if;
    for file in select value from jsonb_array_elements(manifest->'files') loop
      if jsonb_typeof(file) is distinct from 'object' or exists(select 1 from jsonb_object_keys(file) k where k not in ('path','bytes','chunks'))
        or jsonb_typeof(file->'path') is distinct from 'string' or jsonb_typeof(file->'bytes') is distinct from 'number'
        or coalesce(file->>'bytes','')!~'^[0-9]+$' or (file->>'bytes')::bigint>134217728
        or jsonb_typeof(file->'chunks') is distinct from 'array' then raise exception 'invalid artifact file'; end if;
      artifact_path:=file->>'path';
      if artifact_path !~ '^(sessions|archived_sessions)/[^/]' or artifact_path ~ '(^|/)\.' or length(artifact_path)>1024 or jsonb_array_length(file->'chunks')>131072 then raise exception 'unsafe or unbounded artifact file'; end if;
      if (select count(*)<>count(distinct value->'offset') from jsonb_array_elements(file->'chunks')) then raise exception 'duplicate artifact chunk offset'; end if;
      for chunk in select value from jsonb_array_elements(file->'chunks') loop
        if jsonb_typeof(chunk) is distinct from 'object' or exists(select 1 from jsonb_object_keys(chunk) k where k not in ('key','sha256','offset','bytes'))
          or jsonb_typeof(chunk->'key') is distinct from 'string' or coalesce(chunk->>'key','') !~ ('^'||owner::text||'/agent/chunks/v1/[a-f0-9]{64}$')
          or jsonb_typeof(chunk->'sha256') is distinct from 'string' or coalesce(chunk->>'sha256','')!~'^[a-f0-9]{64}$'
          or jsonb_typeof(chunk->'offset') is distinct from 'number' or coalesce(chunk->>'offset','')!~'^[0-9]+$'
          or jsonb_typeof(chunk->'bytes') is distinct from 'number' or coalesce(chunk->>'bytes','')!~'^[1-9][0-9]*$'
          or (chunk->>'bytes')::bigint>1048576 or (chunk->>'offset')::bigint+(chunk->>'bytes')::bigint>(file->>'bytes')::bigint then raise exception 'invalid tenant artifact chunk'; end if;
      end loop;
    end loop;
    for file in select value from jsonb_array_elements(manifest->'removed_paths') loop
      if jsonb_typeof(file) is distinct from 'string' or file#>>'{}' !~ '^(sessions|archived_sessions)/[^/]' or file#>>'{}' ~ '(^|/)\.' or length(file#>>'{}')>1024 then raise exception 'unsafe removed artifact path'; end if;
    end loop;
    for file in select value from jsonb_array_elements(manifest->'omissions') loop
      if jsonb_typeof(file) is distinct from 'object' or exists(select 1 from jsonb_object_keys(file) k where k not in ('index','reason'))
        or jsonb_typeof(file->'index') is distinct from 'number' or coalesce(file->>'index','')!~'^[0-9]+$'
        or (file->>'index')::bigint>256 or coalesce(file->>'reason','') not in ('job_file_limit','unprovenanced','unsafe_path','duplicate_path','file_resource_limit','job_resource_limit') then raise exception 'invalid omission'; end if;
    end loop;
    if saved.manifest_id is not null and (saved.fence->'identity' is distinct from p_fence->'identity'
      or saved.fence->'policy_epoch' is distinct from p_fence->'policy_epoch'
      or saved.fence->'execution_generation' is distinct from p_fence->'execution_generation'
      or saved.manifest_wire is distinct from p_manifest or not saved.linked) then raise exception 'artifact identity conflict'; end if;
    if saved.manifest_id is not null and head is distinct from p_manifest_id then
      raise exception 'historical artifact replay cannot replace current head';
    end if;
    -- An exact retry of the current head reuses its already validated state.
    -- A delta cannot branch from a historical snapshot into the mutable head.
    if head is distinct from p_manifest_id then
      if manifest->>'predecessor' is not null and head is distinct from manifest->>'predecessor' then
        raise exception 'artifact delta must extend current head';
      end if;
      if manifest->>'predecessor' is null then
        delete from public.user_lifetime_artifact_head where user_id=owner and conversation_id=conversation;
        insert into public.user_lifetime_artifact_head values(owner,conversation,p_manifest_id);
      end if;
      delete from public.user_lifetime_artifact_file f where f.user_id=owner and f.conversation_id=conversation
        and manifest->'removed_paths' @> jsonb_build_array(f.path);
      for file in select value from jsonb_array_elements(manifest->'files') loop
        artifact_path:=file->>'path';
        insert into public.user_lifetime_artifact_file(user_id,conversation_id,path,byte_count)
          values(owner,conversation,artifact_path,(file->>'bytes')::bigint)
          on conflict(user_id,conversation_id,path) do update set byte_count=excluded.byte_count;
        -- Drop a truncated suffix and replace only explicitly changed offsets.
        -- A retained partial chunk must be replaced; it may never be clipped
        -- silently because its hash names the original, longer content object.
        delete from public.user_lifetime_artifact_chunk c where c.user_id=owner and c.conversation_id=conversation and c.path=artifact_path
          and (c.chunk_offset>=(file->>'bytes')::bigint or exists(select 1 from jsonb_array_elements(file->'chunks') changed
            where (changed->>'offset')::bigint=c.chunk_offset));
        insert into public.user_lifetime_artifact_chunk(user_id,conversation_id,path,chunk_offset,byte_count,object_key,content_sha256)
          select owner,conversation,artifact_path,(value->>'offset')::bigint,(value->>'bytes')::bigint,value->>'key',value->>'sha256'
          from jsonb_array_elements(file->'chunks');
        select coalesce(sum(c.byte_count),0) into covered_bytes from public.user_lifetime_artifact_chunk c
          where c.user_id=owner and c.conversation_id=conversation and c.path=artifact_path;
        if covered_bytes<>(file->>'bytes')::bigint or exists(
          select 1 from (select chunk_offset,coalesce(sum(c.byte_count) over(order by chunk_offset rows between unbounded preceding and 1 preceding),0) expected_offset
            from public.user_lifetime_artifact_chunk c where c.user_id=owner and c.conversation_id=conversation and c.path=artifact_path) checked
          where chunk_offset<>expected_offset) then raise exception 'incomplete or overlapping effective artifact coverage'; end if;
      end loop;
      if (select count(*)>256 or coalesce(sum(byte_count),0)>268435456 from public.user_lifetime_artifact_file where user_id=owner and conversation_id=conversation)
        or (select count(*)>131072 from public.user_lifetime_artifact_chunk where user_id=owner and conversation_id=conversation) then
        raise exception 'effective artifact resource bound exceeded';
      end if;
      update public.user_lifetime_artifact_head set manifest_id=p_manifest_id where user_id=owner and conversation_id=conversation;
    end if;
    insert into public.user_lifetime_optional_artifact(user_id,conversation_id,manifest_id,fence,manifest_wire,complete)
      values(owner,conversation,p_manifest_id,p_fence,p_manifest,(manifest->>'complete')::boolean)
      on conflict(user_id,conversation_id,manifest_id) do update set fence=excluded.fence;
    select * into saved from public.user_lifetime_optional_artifact where user_id=owner and conversation_id=conversation and manifest_id=p_manifest_id;
  end if;
  return jsonb_build_object('schema_version',1,'manifest_id',saved.manifest_id,'optional',true,'manifest_complete',saved.complete,
    'backup_complete',false,'canonical_recovery_required',false,'status','linked');
end $$;

revoke all on function public.enqueue_lifetime_source_obligation(),public.enqueue_lifetime_reply_obligation(),public.invalidate_lifetime_obligations(),
 public.lifetime_obligation_record(public.user_lifetime_memory_obligation),public.lifetime_obligation_origin_current(public.user_lifetime_memory_obligation)
 from public,anon,authenticated;
revoke all on function public.claim_lifetime_memory_obligation(jsonb),public.complete_lifetime_memory_obligation(jsonb,uuid,uuid),
 public.fail_lifetime_memory_obligation(jsonb,uuid,uuid,text),public.cancel_lifetime_memory_obligation(jsonb,uuid),
 public.read_lifetime_memory_obligations(uuid,uuid,integer),public.link_lifetime_optional_artifact(jsonb,text,text,boolean) from public,anon;
grant execute on function public.claim_lifetime_memory_obligation(jsonb),public.complete_lifetime_memory_obligation(jsonb,uuid,uuid),
 public.fail_lifetime_memory_obligation(jsonb,uuid,uuid,text),public.cancel_lifetime_memory_obligation(jsonb,uuid),
 public.read_lifetime_memory_obligations(uuid,uuid,integer),public.link_lifetime_optional_artifact(jsonb,text,text,boolean) to authenticated;
commit;
