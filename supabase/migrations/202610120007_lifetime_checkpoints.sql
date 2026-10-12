-- Bounded, disposable checkpoint candidates; publishing is a separate CAS.
begin;
create table public.user_lifetime_checkpoint (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  conversation_id uuid not null,
  predecessor_id uuid,
  fence jsonb not null,
  coverage_end bigint not null check(coverage_end>0),
  model text not null check(length(model) between 1 and 200),
  prompt_version text not null check(length(prompt_version) between 1 and 100),
  pinned jsonb not null,
  manifest jsonb not null,
  evidence jsonb not null,
  published boolean not null default false,
  created_at timestamptz not null default clock_timestamp(),
  foreign key(user_id,conversation_id) references public.user_lifetime_conversation(user_id,conversation_id) on delete cascade
);
alter table public.user_lifetime_conversation add column checkpoint_id uuid;
alter table public.user_lifetime_checkpoint enable row level security;
revoke all on public.user_lifetime_checkpoint from public,anon,authenticated;

create function public.read_lifetime_pinned(p_conversation_id uuid) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare owner uuid:=auth.uid(); identity public.user_lifetime_conversation%rowtype; profile jsonb;
  phase jsonb; question text; plan jsonb; continuity jsonb; epoch bigint; record jsonb; selected_bytes integer:=0; omitted boolean:=false;
begin
  select * into identity from public.user_lifetime_conversation where user_id=owner and conversation_id=p_conversation_id;
  if not found then raise exception 'conversation unavailable'; end if;
  select policy_epoch into epoch from public.user_memoir_project where user_id=owner and project_id=identity.project_id for share;
  select p.profile into profile from public.user_profile p where p.user_id=owner for share;
  select * into identity from public.user_lifetime_conversation where user_id=owner and conversation_id=p_conversation_id;
  select public.conversation_phase_record(s) into phase from public.user_conversation_phase s where user_id=owner and project_id=identity.project_id;
  select p.plan into plan from public.user_interview_plan p where user_id=owner and project_id=identity.project_id;
  select c->>'question' into question from jsonb_array_elements(coalesce(plan->'candidates','[]')) c where c->>'id'=plan->>'chosen_id';
  -- Only a bounded recent working set belongs in the prompt. Historical typed
  -- records remain available via the explicit paginated retrieval RPC. Privacy,
  -- language, exclusions, phase and active question below are authoritative pins
  -- and are never selected by lexical relevance.
  continuity:='[]'::jsonb;
  for record in select to_jsonb(c)-'user_id'-'conversation_id' from public.user_lifetime_continuity c
    where c.user_id=owner and c.conversation_id=p_conversation_id and c.policy_epoch=epoch
      and not exists(select 1 from jsonb_array_elements(c.data->'source_refs') ref where not exists(
        select 1 from public.user_narrator_source s where s.user_id=owner and s.project_id=identity.project_id
          and s.id=(ref->>'source_id')::uuid and s.version=(ref->>'version')::bigint and s.status='active'))
    order by case c.kind when 'unresolved_reference' then 0 when 'commitment' then 1 else 2 end,
      (select max(s.sequence) from jsonb_array_elements(c.data->'source_refs') ref
        join public.user_narrator_source s on s.id=(ref->>'source_id')::uuid and s.user_id=owner) desc,c.record_id
    limit 9
  loop
    if jsonb_array_length(continuity)>=8 or selected_bytes+octet_length(record::text)>8000 then omitted:=true;
    else continuity:=continuity||jsonb_build_array(record);selected_bytes:=selected_bytes+octet_length(record::text); end if;
  end loop;
  return jsonb_build_object('schema_version',1,'known_continuity',continuity,'known_continuity_complete',not omitted,
    'continuity_retrieval','read_lifetime_continuity','preference_revision',identity.preference_revision,'conversation_phase',phase,
    'chosen_name',profile->>'name','language',case when profile->>'preferred_language' in ('en-AU','zh-CN') then profile->>'preferred_language' else 'en-AU' end,
    'active_question',question,'unresolved_references',coalesce(profile->'memory_preferences'->'unresolved_references','[]'),
    'paused_topics',coalesce(profile->'memory_preferences'->'paused_topics','[]'),
    'excluded_topics',coalesce(profile->'memory_preferences'->'excluded_topics','[]'));
end $$;

create function public.create_lifetime_checkpoint(p_fence jsonb,p_coverage_end bigint,p_model text,
  p_prompt_version text,p_evidence jsonb default '[]') returns uuid
language plpgsql security definer set search_path=public,auth as $$
declare owner uuid:=auth.uid(); conversation uuid:=(p_fence->'identity'->>'conversation_id')::uuid;
  project text; predecessor uuid; prior_end bigint:=0; claim jsonb; source public.user_narrator_source%rowtype;
  manifest_sources jsonb:='[]'; candidate uuid; pins jsonb;
begin
  -- UPDATE lock first so candidates/publication use the same project-first order.
  select project_id into project from public.user_lifetime_conversation where user_id=owner and conversation_id=conversation;
  if not found then raise exception 'conversation unavailable'; end if;
  perform 1 from public.user_memoir_project where user_id=owner and project_id=project for update;
  perform public.lock_lifetime_publication(p_fence);
  if p_coverage_end is null or p_coverage_end<1 or p_coverage_end>(p_fence->>'source_revision')::bigint then raise exception 'invalid checkpoint coverage'; end if;
  select checkpoint_id into predecessor from public.user_lifetime_conversation where user_id=owner and conversation_id=conversation;
  if predecessor is not null then select coverage_end into prior_end from public.user_lifetime_checkpoint where id=predecessor and published; end if;
  if p_coverage_end<=coalesce(prior_end,0) then raise exception 'checkpoint must advance coverage'; end if;
  if jsonb_typeof(p_evidence) is distinct from 'array' or jsonb_array_length(p_evidence)>16 then raise exception 'bounded checkpoint evidence required'; end if;
  for claim in select value from jsonb_array_elements(p_evidence) loop
    if jsonb_typeof(claim) is distinct from 'object' then raise exception 'evidence object required'; end if;
    if exists(select 1 from jsonb_object_keys(claim) k where k not in
      ('schema_version','source_id','version','char_start','char_end','original','language','role','assertion','uncertainty',
       'time_meaning','translation','translation_attribution','supersedes','contradicts','allowed_use','policy_epoch'))
      or jsonb_typeof(claim->'schema_version') is distinct from 'number'
      or jsonb_typeof(claim->'policy_epoch') is distinct from 'number'
      or jsonb_typeof(claim->'allowed_use') is distinct from 'array' then raise exception 'typed checkpoint envelope required'; end if;
    if jsonb_array_length(claim->'allowed_use') not between 1 and 3 or exists(
      select 1 from jsonb_array_elements(claim->'allowed_use') u where jsonb_typeof(u)<>'string' or u#>>'{}' not in ('conversation','extraction','composition'))
      then raise exception 'invalid checkpoint uses'; end if;
    if exists(select 1 from (values('uncertainty',2000),('time_meaning',500),('translation',2000),('translation_attribution',200)) bounds(k,n)
      where claim->k is not null and claim->k<>'null'::jsonb and (jsonb_typeof(claim->k)<>'string' or length(claim->>k)>n))
      or ((claim->>'translation') is null)<>((claim->>'translation_attribution') is null) then raise exception 'invalid attributed checkpoint metadata'; end if;
    if exists(select 1 from (values('supersedes'),('contradicts')) fields(k)
      where claim->k is not null and jsonb_typeof(claim->k)<>'array') then raise exception 'invalid checkpoint relations'; end if;
    if jsonb_array_length(coalesce(claim->'supersedes','[]'))>100 or jsonb_array_length(coalesce(claim->'contradicts','[]'))>100
      or exists(select 1 from jsonb_array_elements(coalesce(claim->'supersedes','[]')||coalesce(claim->'contradicts','[]')) relation
        where jsonb_typeof(relation)<>'string' or length(relation#>>'{}') not between 1 and 128) then raise exception 'unbounded checkpoint relations'; end if;
    if not (claim ?& array['source_id','version','char_start','char_end','original','policy_epoch','allowed_use'])
      or jsonb_typeof(claim->'source_id') is distinct from 'string'
      or jsonb_typeof(claim->'version') is distinct from 'number' or coalesce(claim->>'version','')!~'^[1-9][0-9]*$'
      or jsonb_typeof(claim->'char_start') is distinct from 'number' or coalesce(claim->>'char_start','')!~'^[0-9]+$'
      or jsonb_typeof(claim->'char_end') is distinct from 'number' or coalesce(claim->>'char_end','')!~'^[1-9][0-9]*$'
      or jsonb_typeof(claim->'original') is distinct from 'string' or length(claim->>'original') not between 1 and 2000
      or claim->>'policy_epoch' is distinct from p_fence->>'policy_epoch'
      or not coalesce(claim->'allowed_use' @> '["conversation"]',false)
      or coalesce(claim->>'role','')<>'storyteller' or claim->>'schema_version' is distinct from '1'
      or coalesce(claim->>'assertion','') not in ('asserted','inferred') then raise exception 'invalid checkpoint evidence'; end if;
    select * into source from public.user_narrator_source where user_id=owner and project_id=project
      and id=(claim->>'source_id')::uuid and version=(claim->>'version')::bigint and status='active' and sequence<=p_coverage_end;
    if not found or claim->>'language' is distinct from source.language or (claim->>'char_end')::integer<=(claim->>'char_start')::integer
      or (claim->>'char_end')::integer>length(source.text)
      or substring(source.text from (claim->>'char_start')::integer+1 for (claim->>'char_end')::integer-(claim->>'char_start')::integer)
        is distinct from claim->>'original' then raise exception 'unsupported checkpoint quote'; end if;
    if not manifest_sources @> jsonb_build_array(jsonb_build_object('schema_version',1,'source_id',source.id,'version',source.version)) then
      manifest_sources:=manifest_sources || jsonb_build_array(jsonb_build_object('schema_version',1,'source_id',source.id,'version',source.version));
    end if;
  end loop;
  pins:=public.read_lifetime_pinned(conversation);
  insert into public.user_lifetime_checkpoint(user_id,conversation_id,predecessor_id,fence,coverage_end,model,prompt_version,pinned,manifest,evidence)
    values(owner,conversation,predecessor,p_fence,p_coverage_end,p_model,p_prompt_version,pins,
      jsonb_build_object('schema_version',1,'identity',p_fence->'identity','policy_epoch',(p_fence->>'policy_epoch')::bigint,
        'source_revision',(p_fence->>'source_revision')::bigint,'sources',manifest_sources),p_evidence) returning id into candidate;
  return candidate;
end $$;

create function public.publish_lifetime_checkpoint(p_id uuid,p_fence jsonb) returns boolean
language plpgsql security definer set search_path=public,auth as $$
declare owner uuid:=auth.uid(); saved public.user_lifetime_checkpoint%rowtype; project text; head uuid;
begin
  select * into saved from public.user_lifetime_checkpoint where id=p_id and user_id=owner;
  if not found then raise exception 'checkpoint unavailable'; end if;
  select project_id into project from public.user_lifetime_conversation where user_id=owner and conversation_id=saved.conversation_id;
  perform 1 from public.user_memoir_project where user_id=owner and project_id=project for update;
  perform public.lock_lifetime_publication(p_fence);
  if saved.fence is distinct from p_fence or saved.pinned is distinct from public.read_lifetime_pinned(saved.conversation_id) then raise exception 'stale checkpoint' using errcode='40001'; end if;
  select checkpoint_id into head from public.user_lifetime_conversation where user_id=owner and conversation_id=saved.conversation_id;
  if head=p_id and saved.published then return true; end if;
  if head is distinct from saved.predecessor_id then raise exception 'checkpoint predecessor changed' using errcode='40001'; end if;
  update public.user_lifetime_checkpoint set published=true where id=p_id;
  update public.user_lifetime_conversation set checkpoint_id=p_id where user_id=owner and conversation_id=saved.conversation_id;
  return true;
end $$;

create function public.read_lifetime_checkpoint(p_conversation_id uuid,p_policy_epoch bigint,p_model text,p_prompt_version text) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare identity public.user_lifetime_conversation%rowtype; saved public.user_lifetime_checkpoint%rowtype; epoch bigint;
begin
  select * into identity from public.user_lifetime_conversation where user_id=auth.uid() and conversation_id=p_conversation_id;
  if not found then raise exception 'conversation unavailable'; end if;
  select policy_epoch into epoch from public.user_memoir_project where user_id=auth.uid() and project_id=identity.project_id for share;
  if epoch is distinct from p_policy_epoch then raise exception 'stale checkpoint policy' using errcode='40001'; end if;
  select * into identity from public.user_lifetime_conversation where user_id=auth.uid() and conversation_id=p_conversation_id;
  select * into saved from public.user_lifetime_checkpoint where id=identity.checkpoint_id and published
    and fence->>'policy_epoch'=epoch::text and model=p_model and prompt_version=p_prompt_version;
  if not found then return null; end if;
  return jsonb_build_object('schema_version',1,'checkpoint_id',saved.id,'predecessor_id',saved.predecessor_id,
    'identity',saved.fence->'identity','policy_epoch',epoch,'coverage_end',saved.coverage_end,
    'model',saved.model,'prompt_version',saved.prompt_version,'pinned',public.read_lifetime_pinned(p_conversation_id),
    'manifest',saved.manifest,'evidence',saved.evidence);
end $$;
revoke all on function public.read_lifetime_pinned(uuid),public.create_lifetime_checkpoint(jsonb,bigint,text,text,jsonb),
 public.publish_lifetime_checkpoint(uuid,jsonb),public.read_lifetime_checkpoint(uuid,bigint,text,text) from public,anon;
grant execute on function public.read_lifetime_pinned(uuid),public.create_lifetime_checkpoint(jsonb,bigint,text,text,jsonb),
 public.publish_lifetime_checkpoint(uuid,jsonb),public.read_lifetime_checkpoint(uuid,bigint,text,text) to authenticated;
create function public.purge_lifetime_checkpoint_projections() returns trigger
language plpgsql security definer set search_path='' as $$
begin
  if old.policy_epoch is distinct from new.policy_epoch then
    update public.user_lifetime_conversation set checkpoint_id=null where user_id=new.user_id and project_id=new.project_id;
    delete from public.user_lifetime_checkpoint c using public.user_lifetime_conversation l
      where c.user_id=l.user_id and c.conversation_id=l.conversation_id and l.user_id=new.user_id and l.project_id=new.project_id;
  end if;
  return new;
end $$;
create trigger lifetime_checkpoint_invalidation after update of policy_epoch on public.user_memoir_project
 for each row execute function public.purge_lifetime_checkpoint_projections();
revoke all on function public.purge_lifetime_checkpoint_projections() from public,anon,authenticated;
commit;
