-- Explicit private formal assembly, separate from cadence-driven draft roots.
-- V1 is extractive: every block is an exact canonical original evidence span.
begin;

create table public.user_formal_memoir_head (
 user_id uuid not null, project_id text not null, revision bigint not null default 0,
 edition_id uuid, consent_revision bigint not null default 0,
 primary key(user_id,project_id),
 foreign key(user_id,project_id) references public.user_memoir_project on delete cascade
);
create table public.user_formal_memoir_run (
 id uuid primary key default gen_random_uuid(), user_id uuid not null, project_id text not null,
 conversation_id uuid not null, request_id uuid not null, locale text not null,
 base_revision bigint not null, phase_revision bigint not null, policy_epoch bigint not null,
 preference_revision bigint not null, source_revision bigint not null, event_revision bigint not null,
 plan_digest text not null default '', chapter_count integer not null default 0,
 state text not null default 'pending' check(state in ('pending','running','completed','stale')),
 token uuid, fence bigint not null default 0, lease_until timestamptz,
 created_at timestamptz not null default clock_timestamp(),
 unique(user_id,project_id,request_id),
 foreign key(user_id,project_id) references public.user_memoir_project on delete cascade,
 foreign key(user_id,conversation_id) references public.user_lifetime_conversation(user_id,conversation_id) on delete cascade
);
create table public.user_formal_memoir_plan (
 run_id uuid not null references public.user_formal_memoir_run on delete cascade,
 ordinal integer not null, chapter_id uuid not null default gen_random_uuid(),
 event_id text not null, event_revision bigint not null, title text not null,
 evidence jsonb not null, digest text not null,
 primary key(run_id,ordinal), unique(run_id,chapter_id), unique(run_id,event_id)
);
alter table public.user_formal_memoir_head enable row level security;
alter table public.user_formal_memoir_run enable row level security;
alter table public.user_formal_memoir_plan enable row level security;
revoke all on public.user_formal_memoir_head,public.user_formal_memoir_run,public.user_formal_memoir_plan from public,anon,authenticated,service_role;

create function public.formal_memoir_digest(p_value jsonb) returns text
language sql immutable set search_path='' as $$
 select encode(sha256(convert_to(p_value::text,'UTF8')),'hex')
$$;
revoke all on function public.formal_memoir_digest(jsonb) from public,anon,authenticated,service_role;

create function public.lock_formal_memoir_context(p_owner uuid,p_project text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare project public.user_memoir_project%rowtype; identity public.user_lifetime_conversation%rowtype;
 phase public.user_conversation_phase%rowtype; pins jsonb; old_owner text;
begin
 select * into project from public.user_memoir_project where user_id=p_owner and project_id=p_project for update;
 if not found then raise exception 'FORMAL_PROJECT_UNAVAILABLE' using errcode='42501';end if;
 perform 1 from public.user_profile where user_id=p_owner for share;
 select * into identity from public.user_lifetime_conversation where user_id=p_owner and project_id=p_project for share;
 if not found or exists(select 1 from auth.users where id=p_owner and is_anonymous) then
   raise exception 'FORMAL_OWNER_REQUIRED' using errcode='42501';end if;
 select * into phase from public.user_conversation_phase where user_id=p_owner and project_id=p_project;
 if not found or phase.phase<>'shape' then raise exception 'FORMAL_SHAPE_REQUIRED' using errcode='40001';end if;
 perform public.require_lifetime_policy_ready(p_owner,p_project);
 old_owner:=current_setting('request.jwt.claim.sub',true);
 perform set_config('request.jwt.claim.sub',p_owner::text,true);
 pins:=public.read_lifetime_pinned(identity.conversation_id);
 perform set_config('request.jwt.claim.sub',coalesce(old_owner,''),true);
 if (pins->>'privacy_complete')::boolean is distinct from true
   or jsonb_array_length(pins->'excluded_topics')>0 or jsonb_array_length(pins->'paused_topics')>0 then
   raise exception 'FORMAL_PRIVACY_REVIEW_REQUIRED' using errcode='55000';end if;
 return jsonb_build_object('conversation_id',identity.conversation_id,'locale',pins->>'language',
   'phase_revision',phase.revision,'policy_epoch',project.policy_epoch,'preference_revision',identity.preference_revision,
   'source_revision',project.source_sequence,'event_revision',project.event_sequence);
end $$;
revoke all on function public.lock_formal_memoir_context(uuid,text) from public,anon,authenticated,service_role;

create function public.formal_memoir_run_record(p_run public.user_formal_memoir_run) returns jsonb
language sql stable set search_path='' as $$
 select jsonb_build_object('schema_version',1,'run_id',p_run.id,'status',p_run.state,'project_id',p_run.project_id,
  'locale',p_run.locale,'base_revision',p_run.base_revision,'phase_revision',p_run.phase_revision,
  'policy_epoch',p_run.policy_epoch,'preference_revision',p_run.preference_revision,'source_revision',p_run.source_revision,
  'event_revision',p_run.event_revision,'plan_digest',p_run.plan_digest,'chapter_count',p_run.chapter_count)
$$;
revoke all on function public.formal_memoir_run_record(public.user_formal_memoir_run) from public,anon,authenticated,service_role;

create function public.begin_formal_memoir(p_project_id text,p_expected_phase_revision bigint,p_expected_revision bigint,p_request_id uuid)
returns jsonb language plpgsql security definer set search_path='' as $$
declare owner uuid:=auth.uid(); context jsonb; run public.user_formal_memoir_run%rowtype; event record;
 ref record; refs jsonb; span jsonb; lo integer; hi integer; ordinal integer:=0; plan jsonb; current_revision bigint;
begin
 if owner is null then raise exception 'FORMAL_OWNER_REQUIRED' using errcode='42501';end if;
 context:=public.lock_formal_memoir_context(owner,p_project_id);
 if p_request_id is null or p_expected_phase_revision is distinct from (context->>'phase_revision')::bigint then
   raise exception 'FORMAL_PHASE_CHANGED' using errcode='40001';end if;
 select * into run from public.user_formal_memoir_run where user_id=owner and project_id=p_project_id and request_id=p_request_id;
 if found then
   if run.base_revision is distinct from p_expected_revision or run.phase_revision is distinct from p_expected_phase_revision then
     raise exception 'FORMAL_REQUEST_CONFLICT' using errcode='40001';end if;
   return public.formal_memoir_run_record(run);
 end if;
 insert into public.user_formal_memoir_head(user_id,project_id) values(owner,p_project_id) on conflict do nothing;
 select revision into current_revision from public.user_formal_memoir_head where user_id=owner and project_id=p_project_id for update;
 if current_revision is distinct from p_expected_revision then raise exception 'FORMAL_REVISION_CHANGED' using errcode='40001';end if;
 if exists(select 1 from public.user_formal_memoir_run where user_id=owner and project_id=p_project_id and state in ('pending','running')) then
   raise exception 'FORMAL_RUN_PENDING' using errcode='40001';end if;
 if exists(select 1 from public.user_narrator_source where user_id=owner and project_id=p_project_id and status='active' and processing_status<>'succeeded') then
   raise exception 'FORMAL_EXTRACTION_INCOMPLETE' using errcode='55000';end if;
 insert into public.user_formal_memoir_run(user_id,project_id,conversation_id,request_id,locale,base_revision,phase_revision,
   policy_epoch,preference_revision,source_revision,event_revision)
 values(owner,p_project_id,(context->>'conversation_id')::uuid,p_request_id,context->>'locale',p_expected_revision,p_expected_phase_revision,
   (context->>'policy_epoch')::bigint,(context->>'preference_revision')::bigint,(context->>'source_revision')::bigint,(context->>'event_revision')::bigint)
 returning * into run;
 for event in select * from public.user_memory_event where user_id=owner and project_id=p_project_id and status='active'
   order by change_sequence,id loop
   ordinal:=ordinal+1;
   if ordinal>128 then raise exception 'FORMAL_PLAN_CAPACITY_REQUIRED' using errcode='55000';end if;
   refs:='[]';
   for ref in select r.source_id,r.source_version,r.evidence,s.text,s.status,s.version from public.user_memory_event_source r
     left join public.user_narrator_source s on s.user_id=r.user_id and s.project_id=r.project_id and s.id=r.source_id
     where r.user_id=owner and r.project_id=p_project_id and r.event_id=event.id order by r.source_id,r.source_version,r.evidence_hash loop
     if ref.status is distinct from 'active' or ref.version is distinct from ref.source_version then
       raise exception 'FORMAL_EVIDENCE_UNAVAILABLE' using errcode='40001';end if;
     lo:=coalesce((ref.evidence->>'char_start')::integer,strpos(ref.text,ref.evidence->>'quote')-1);
     hi:=coalesce((ref.evidence->>'char_end')::integer,lo+length(ref.evidence->>'quote'));
     if lo is null or hi is null or lo<0 or hi<=lo or hi>length(ref.text) or hi-lo>2000
       or substring(ref.text from lo+1 for hi-lo) is distinct from ref.evidence->>'quote'
       or ((ref.evidence->>'char_start' is null) <> (ref.evidence->>'char_end' is null))
       or (ref.evidence->>'char_start' is null and strpos(substring(ref.text from lo+2),ref.evidence->>'quote')>0) then
       raise exception 'FORMAL_EXACT_EVIDENCE_REQUIRED' using errcode='22023';end if;
     span:=jsonb_build_object('source_id',ref.source_id,'version',ref.source_version,'char_start',lo,'char_end',hi,'quote',ref.evidence->>'quote');
     refs:=refs||jsonb_build_array(span);
   end loop;
   if jsonb_array_length(refs) not between 1 and 8 then raise exception 'FORMAL_CHAPTER_CAPACITY_REQUIRED' using errcode='55000';end if;
   plan:=jsonb_build_object('ordinal',ordinal,'event_id',event.id,'event_revision',event.revision,'title','Chapter '||ordinal,'evidence',refs);
   insert into public.user_formal_memoir_plan(run_id,ordinal,event_id,event_revision,title,evidence,digest)
    values(run.id,ordinal,event.id,event.revision,'Chapter '||ordinal,refs,public.formal_memoir_digest(plan));
 end loop;
 if ordinal=0 then raise exception 'FORMAL_EVIDENCE_REQUIRED' using errcode='55000';end if;
 update public.user_formal_memoir_run set chapter_count=ordinal,plan_digest=public.formal_memoir_digest(
   (select jsonb_agg(jsonb_build_object('ordinal',p.ordinal,'chapter_id',p.chapter_id,'digest',p.digest) order by p.ordinal)
    from public.user_formal_memoir_plan p where p.run_id=run.id)) where id=run.id returning * into run;
 return public.formal_memoir_run_record(run);
end $$;
revoke all on function public.begin_formal_memoir(text,bigint,bigint,uuid) from public,anon;
grant execute on function public.begin_formal_memoir(text,bigint,bigint,uuid) to authenticated;

create function public.read_formal_memoir_status(p_project_id text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare owner uuid:=auth.uid(); run public.user_formal_memoir_run%rowtype;
begin
 if owner is null or not exists(select 1 from public.user_lifetime_conversation where user_id=owner and project_id=p_project_id) then
   raise exception 'FORMAL_OWNER_REQUIRED' using errcode='42501';end if;
 perform 1 from public.user_memoir_project where user_id=owner and project_id=p_project_id for share;
 select * into run from public.user_formal_memoir_run where user_id=owner and project_id=p_project_id order by created_at desc,id desc limit 1;
 return jsonb_build_object('schema_version',1,'run',case when run.id is not null then public.formal_memoir_run_record(run) end,'edition',null);
end $$;
revoke all on function public.read_formal_memoir_status(text) from public,anon;
grant execute on function public.read_formal_memoir_status(text) to authenticated;

create table public.user_formal_memoir_chapter (
 run_id uuid not null, ordinal integer not null, chapter jsonb not null, digest text not null,
 validation jsonb not null, validation_digest text not null,
 primary key(run_id,ordinal),
 foreign key(run_id,ordinal) references public.user_formal_memoir_plan on delete cascade
);
create table public.user_formal_memoir_edition (
 id uuid primary key, run_id uuid not null unique references public.user_formal_memoir_run on delete cascade,
 user_id uuid not null, project_id text not null, revision bigint not null, digest text not null,
 active boolean not null default true, result jsonb not null,
 unique(user_id,project_id,revision),
 foreign key(user_id,project_id) references public.user_memoir_project on delete cascade
);
alter table public.user_formal_memoir_chapter enable row level security;
alter table public.user_formal_memoir_edition enable row level security;
revoke all on public.user_formal_memoir_chapter,public.user_formal_memoir_edition from public,anon,authenticated,service_role;

create function public.lock_formal_memoir_run(p_run_id uuid,p_token uuid default null,p_require_token boolean default true)
returns public.user_formal_memoir_run language plpgsql security definer set search_path='' as $$
declare run public.user_formal_memoir_run%rowtype; context jsonb; key text;
begin
 select * into run from public.user_formal_memoir_run where id=p_run_id;
 if not found then raise exception 'FORMAL_RUN_UNAVAILABLE' using errcode='42501';end if;
 context:=public.lock_formal_memoir_context(run.user_id,run.project_id);
 select * into run from public.user_formal_memoir_run where id=p_run_id for update;
 if run.state='stale' then raise exception 'FORMAL_AUTHORITY_STALE' using errcode='40001';end if;
 foreach key in array array['conversation_id','locale','phase_revision','policy_epoch','preference_revision','source_revision','event_revision'] loop
   if to_jsonb(run)->key is distinct from context->key then raise exception 'FORMAL_AUTHORITY_STALE' using errcode='40001';end if;
 end loop;
 if run.state='completed' and not exists(select 1 from public.user_formal_memoir_edition e
   join public.user_formal_memoir_head h on h.user_id=e.user_id and h.project_id=e.project_id and h.edition_id=e.id
   where e.run_id=run.id and e.active) then
   raise exception 'FORMAL_EDITION_STALE' using errcode='40001';end if;
 if p_require_token and (p_token is null or run.token is distinct from p_token or run.state<>'running' or run.lease_until<=clock_timestamp()) then
   raise exception 'FORMAL_LEASE_STALE' using errcode='40001';end if;
 return run;
end $$;
revoke all on function public.lock_formal_memoir_run(uuid,uuid,boolean) from public,anon,authenticated,service_role;

create function public.claim_formal_memoir(p_run_id uuid,p_lease_seconds integer default 300) returns jsonb
language plpgsql security definer set search_path='' as $$
declare run public.user_formal_memoir_run%rowtype; next_ordinal integer;
begin
 if p_lease_seconds is null or p_lease_seconds not between 1 and 900 then raise exception 'FORMAL_LEASE_BOUNDS' using errcode='22023';end if;
 run:=public.lock_formal_memoir_run(p_run_id,null,false);
 if run.state='completed' then return (select result from public.user_formal_memoir_edition where run_id=run.id and active);end if;
 if run.token is not null and run.lease_until>clock_timestamp() then return jsonb_build_object('status','busy','run_id',run.id);end if;
 update public.user_formal_memoir_run set state='running',token=gen_random_uuid(),fence=fence+1,
   lease_until=clock_timestamp()+make_interval(secs=>p_lease_seconds) where id=run.id returning * into run;
 select coalesce(min(p.ordinal),run.chapter_count+1) into next_ordinal from public.user_formal_memoir_plan p
   where p.run_id=run.id and not exists(select 1 from public.user_formal_memoir_chapter c where c.run_id=p.run_id and c.ordinal=p.ordinal);
 return public.formal_memoir_run_record(run)||jsonb_build_object('token',run.token,'fence',run.fence,'lease_until',run.lease_until,'next_ordinal',next_ordinal);
end $$;
revoke all on function public.claim_formal_memoir(uuid,integer) from public,anon,authenticated;
grant execute on function public.claim_formal_memoir(uuid,integer) to service_role;

create function public.release_formal_memoir(p_run_id uuid,p_token uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare run public.user_formal_memoir_run%rowtype; next_ordinal integer;
begin
 run:=public.lock_formal_memoir_run(p_run_id,p_token);
 update public.user_formal_memoir_run set state='pending',token=null,lease_until=null,fence=fence+1 where id=run.id;
 select coalesce(min(p.ordinal),run.chapter_count+1) into next_ordinal from public.user_formal_memoir_plan p
 where p.run_id=run.id and not exists(select 1 from public.user_formal_memoir_chapter c where c.run_id=p.run_id and c.ordinal=p.ordinal);
 return jsonb_build_object('status','pending','run_id',run.id,'next_ordinal',next_ordinal);
end $$;
revoke all on function public.release_formal_memoir(uuid,uuid) from public,anon,authenticated;
grant execute on function public.release_formal_memoir(uuid,uuid) to service_role;

create function public.read_formal_memoir_chapter(p_run_id uuid,p_token uuid,p_ordinal integer) returns jsonb
language plpgsql security definer set search_path='' as $$
declare run public.user_formal_memoir_run%rowtype; plan public.user_formal_memoir_plan%rowtype;
begin
 run:=public.lock_formal_memoir_run(p_run_id,p_token);
 select * into plan from public.user_formal_memoir_plan where run_id=run.id and ordinal=p_ordinal;
 if not found then raise exception 'FORMAL_CHAPTER_UNAVAILABLE' using errcode='22023';end if;
 return jsonb_build_object('run_id',run.id,'token',run.token,'fence',run.fence,'plan_digest',run.plan_digest,
   'ordinal',plan.ordinal,'chapter_id',plan.chapter_id,'title',plan.title,'event_id',plan.event_id,
   'event_revision',plan.event_revision,'evidence',plan.evidence,'chapter_plan_digest',plan.digest);
end $$;
revoke all on function public.read_formal_memoir_chapter(uuid,uuid,integer) from public,anon,authenticated;
grant execute on function public.read_formal_memoir_chapter(uuid,uuid,integer) to service_role;

create function public.stage_formal_memoir_chapter(p_run_id uuid,p_token uuid,p_ordinal integer,p_chapter jsonb,p_validation jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare run public.user_formal_memoir_run%rowtype; plan public.user_formal_memoir_plan%rowtype; expected jsonb; validation jsonb;
 saved public.user_formal_memoir_chapter%rowtype; chapter_digest text;
begin
 run:=public.lock_formal_memoir_run(p_run_id,p_token);
 select * into plan from public.user_formal_memoir_plan where run_id=run.id and ordinal=p_ordinal;
 if not found then raise exception 'FORMAL_CHAPTER_UNAVAILABLE' using errcode='22023';end if;
 expected:=jsonb_build_object('schema_version',1,'chapter_id',plan.chapter_id,'title',plan.title,'blocks',
   (select jsonb_agg((e-'quote')||jsonb_build_object('text',e->>'quote') order by n) from jsonb_array_elements(plan.evidence) with ordinality a(e,n)));
 validation:=jsonb_build_object('schema_version',1,'validator','formal-extractive-v1','chapter_plan_digest',plan.digest,
   'provenance','deterministic-extractive','blocking_count',0);
 if p_chapter is distinct from expected or p_validation is distinct from validation then
   raise exception 'FORMAL_CHAPTER_VALIDATION_FAILED' using errcode='22023';end if;
 chapter_digest:=public.formal_memoir_digest(expected);
 select * into saved from public.user_formal_memoir_chapter where run_id=run.id and ordinal=p_ordinal;
 if found and (saved.digest<>chapter_digest or saved.validation is distinct from validation) then
   raise exception 'FORMAL_CHAPTER_REPLAY_CONFLICT' using errcode='40001';end if;
 insert into public.user_formal_memoir_chapter(run_id,ordinal,chapter,digest,validation,validation_digest)
 values(run.id,p_ordinal,expected,chapter_digest,validation,public.formal_memoir_digest(validation)) on conflict do nothing;
 return jsonb_build_object('status','staged','chapter_id',plan.chapter_id,'digest',chapter_digest);
end $$;
revoke all on function public.stage_formal_memoir_chapter(uuid,uuid,integer,jsonb,jsonb) from public,anon,authenticated;
grant execute on function public.stage_formal_memoir_chapter(uuid,uuid,integer,jsonb,jsonb) to service_role;

create function public.complete_formal_memoir(p_run_id uuid,p_token uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare run public.user_formal_memoir_run%rowtype; current_revision bigint; coverage jsonb; edition uuid:=gen_random_uuid();
 manuscript_digest text; receipt jsonb; result jsonb;
begin
 run:=public.lock_formal_memoir_run(p_run_id,null,false);
 if run.state='completed' then
   if p_token is distinct from run.token then raise exception 'FORMAL_LEASE_STALE' using errcode='40001';end if;
   return (select e.result from public.user_formal_memoir_edition e where e.run_id=run.id and e.active);
 end if;
 run:=public.lock_formal_memoir_run(p_run_id,p_token);
 select revision into current_revision from public.user_formal_memoir_head where user_id=run.user_id and project_id=run.project_id for update;
 if current_revision is distinct from run.base_revision then raise exception 'FORMAL_REVISION_CHANGED' using errcode='40001';end if;
 if (select count(*) from public.user_formal_memoir_chapter where run_id=run.id)<>run.chapter_count
   or (select count(*) from public.user_formal_memoir_plan where run_id=run.id)<>run.chapter_count then
   raise exception 'FORMAL_COVERAGE_INCOMPLETE' using errcode='40001';end if;
 select jsonb_agg(jsonb_build_object('chapter_id',p.chapter_id,'revision',1,'digest',c.digest) order by p.ordinal)
 into coverage from public.user_formal_memoir_plan p join public.user_formal_memoir_chapter c using(run_id,ordinal) where p.run_id=run.id;
 manuscript_digest:=public.formal_memoir_digest(coverage);
 receipt:=jsonb_build_object('schema_version',1,'receipt_id',gen_random_uuid(),'run_id',run.id,'edition_id',edition,
   'owner_id',run.user_id,'project_id',run.project_id,'conversation_id',run.conversation_id,'locale',run.locale,
   'revision',current_revision+1,'manuscript_digest',manuscript_digest,'chapter_coverage',coverage,'plan_digest',run.plan_digest,
   'policy_epoch',run.policy_epoch,'preference_revision',run.preference_revision,'phase_revision',run.phase_revision,
   'source_revision',run.source_revision,'event_revision',run.event_revision,'pending_count',0,'blocking_count',0,
   'scope','all_active_canonical_events_at_initiation','assembly','extractive-v1','manuscript_kind','formal_memoir','manuscript_status','draft','publication_approved',false,
   'source_manifest_digest',public.formal_memoir_digest((select jsonb_agg(p.evidence order by p.ordinal) from public.user_formal_memoir_plan p where p.run_id=run.id)),
   'validation_digest',public.formal_memoir_digest((select jsonb_agg(c.validation_digest order by c.ordinal) from public.user_formal_memoir_chapter c where c.run_id=run.id)));
 result:=jsonb_build_object('status','completed','edition_id',edition,'revision',current_revision+1,'manuscript_digest',manuscript_digest,'receipt',receipt);
 update public.user_formal_memoir_edition set active=false where user_id=run.user_id and project_id=run.project_id;
 insert into public.user_formal_memoir_edition(id,run_id,user_id,project_id,revision,digest,result)
 values(edition,run.id,run.user_id,run.project_id,current_revision+1,manuscript_digest,result);
 update public.user_formal_memoir_head set revision=current_revision+1,edition_id=edition,consent_revision=consent_revision+1
 where user_id=run.user_id and project_id=run.project_id;
 update public.user_formal_memoir_run set state='completed',lease_until=null where id=run.id;
 return result;
end $$;
revoke all on function public.complete_formal_memoir(uuid,uuid) from public,anon,authenticated;
grant execute on function public.complete_formal_memoir(uuid,uuid) to service_role;

create or replace function public.read_formal_memoir_status(p_project_id text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare owner uuid:=auth.uid(); run public.user_formal_memoir_run%rowtype; edition jsonb;
begin
 if owner is null or not exists(select 1 from public.user_lifetime_conversation where user_id=owner and project_id=p_project_id) then
   raise exception 'FORMAL_OWNER_REQUIRED' using errcode='42501';end if;
 perform 1 from public.user_memoir_project where user_id=owner and project_id=p_project_id for share;
 -- Preference invalidation owns identity without requesting project. Wait for
 -- that whole transaction before reading run and edition metadata together.
 perform 1 from public.user_lifetime_conversation where user_id=owner and project_id=p_project_id for share;
 select * into run from public.user_formal_memoir_run where user_id=owner and project_id=p_project_id order by created_at desc,id desc limit 1;
 select result into edition from public.user_formal_memoir_edition where user_id=owner and project_id=p_project_id and active;
 return jsonb_build_object('schema_version',1,'run',case when run.id is not null then public.formal_memoir_run_record(run) end,'edition',edition);
end $$;

-- Worker persistence read only. No direct owner/browser prose RPC: actual-send
-- guarded owner delivery is a separate future feature, not implemented here.
create function public.read_formal_memoir_edition_chapter(p_project_id text,p_edition_id uuid,p_ordinal integer) returns jsonb
language plpgsql security definer set search_path='' as $$
declare edition public.user_formal_memoir_edition%rowtype; run public.user_formal_memoir_run%rowtype; chapter public.user_formal_memoir_chapter%rowtype;
begin
 select * into edition from public.user_formal_memoir_edition where id=p_edition_id and project_id=p_project_id and active;
 if not found then raise exception 'FORMAL_EDITION_UNAVAILABLE' using errcode='42501';end if;
 run:=public.lock_formal_memoir_run(edition.run_id,null,false);
 select * into chapter from public.user_formal_memoir_chapter where run_id=run.id and ordinal=p_ordinal;
 if not found then raise exception 'FORMAL_CHAPTER_UNAVAILABLE' using errcode='22023';end if;
 return jsonb_build_object('edition_id',edition.id,'revision',edition.revision,'ordinal',p_ordinal,'chapter',chapter.chapter,'digest',chapter.digest);
end $$;
revoke all on function public.read_formal_memoir_edition_chapter(text,uuid,integer) from public,anon,authenticated;
grant execute on function public.read_formal_memoir_edition_chapter(text,uuid,integer) to service_role;

-- Consent revision is a conservative project-global fence. Any consent change,
-- including revoking an older edition, requires a fresh grant for the current
-- edition before adaptation is eligible; a grant never transfers editions.
create table public.user_story_game_consent (
 edition_id uuid primary key references public.user_formal_memoir_edition on delete cascade,
 user_id uuid not null, project_id text not null, revision bigint not null,
 status text not null check(status in ('active','revoked')), policy_epoch bigint not null,
 purpose text not null default 'game_adaptation' check(purpose='game_adaptation'),
 audience text not null default 'private' check(audience='private'),
 foreign key(user_id,project_id) references public.user_memoir_project on delete cascade
);
alter table public.user_story_game_consent enable row level security;
revoke all on public.user_story_game_consent from public,anon,authenticated,service_role;

create function public.set_story_game_consent(p_project_id text,p_edition_id uuid,p_expected_digest text,p_expected_revision bigint,p_action text)
returns jsonb language plpgsql security definer set search_path='' as $$
declare owner uuid:=auth.uid(); edition public.user_formal_memoir_edition%rowtype; head public.user_formal_memoir_head%rowtype;
 epoch bigint; result_status text;
begin
 if owner is null then raise exception 'FORMAL_OWNER_REQUIRED' using errcode='42501';end if;
 select policy_epoch into epoch from public.user_memoir_project where user_id=owner and project_id=p_project_id for update;
 if not found then raise exception 'FORMAL_OWNER_REQUIRED' using errcode='42501';end if;
 if p_action is null or p_action not in ('grant','revoke') then raise exception 'ADAPTATION_ACTION_INVALID' using errcode='22023';end if;
 select * into edition from public.user_formal_memoir_edition where id=p_edition_id and user_id=owner and project_id=p_project_id;
 if not found or edition.digest is distinct from p_expected_digest then
   raise exception 'ADAPTATION_EDITION_MISMATCH' using errcode='40001';end if;
 select * into head from public.user_formal_memoir_head where user_id=owner and project_id=p_project_id for update;
 if head.consent_revision is distinct from p_expected_revision then raise exception 'ADAPTATION_CONSENT_CHANGED' using errcode='40001';end if;
 if p_action='grant' then
   if not edition.active or head.edition_id is distinct from edition.id then raise exception 'ADAPTATION_EDITION_STALE' using errcode='40001';end if;
   perform public.lock_formal_memoir_run(edition.run_id,null,false);
 end if;
 -- Withdrawal is always possible, including after a phase exit or invalidation.
 result_status:=case when p_action='grant' then 'active' else 'revoked' end;
 update public.user_formal_memoir_head set consent_revision=consent_revision+1 where user_id=owner and project_id=p_project_id returning * into head;
 insert into public.user_story_game_consent(edition_id,user_id,project_id,revision,status,policy_epoch)
 values(edition.id,owner,p_project_id,head.consent_revision,result_status,epoch)
 on conflict(edition_id) do update set revision=excluded.revision,status=excluded.status,policy_epoch=excluded.policy_epoch;
 return jsonb_build_object('revision',head.consent_revision,'status',result_status,'edition_id',edition.id);
end $$;
revoke all on function public.set_story_game_consent(text,uuid,text,bigint,text) from public,anon;
grant execute on function public.set_story_game_consent(text,uuid,text,bigint,text) to authenticated;

create function public.read_story_game_eligibility(p_project_id text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare owner uuid:=auth.uid(); edition public.user_formal_memoir_edition%rowtype; head public.user_formal_memoir_head%rowtype;
 reasons jsonb:='[]'; context jsonb; authority boolean; code text;
begin
 if owner is null or not exists(select 1 from public.user_lifetime_conversation where user_id=owner and project_id=p_project_id) then
   raise exception 'FORMAL_OWNER_REQUIRED' using errcode='42501';end if;
 perform 1 from public.user_memoir_project where user_id=owner and project_id=p_project_id for update;
 select * into head from public.user_formal_memoir_head where user_id=owner and project_id=p_project_id;
 select * into edition from public.user_formal_memoir_edition where id=head.edition_id;
 begin
   context:=public.lock_formal_memoir_context(owner,p_project_id);
   if edition.id is null then reasons:=reasons||'"completion_required"'::jsonb;
   elsif not edition.active then reasons:=reasons||'"completion_stale"'::jsonb;
   else perform public.lock_formal_memoir_run(edition.run_id,null,false);
   end if;
 exception when sqlstate '40001' or sqlstate '55000' then
   code:=case SQLERRM when 'FORMAL_SHAPE_REQUIRED' then 'shape_required'
     when 'FORMAL_PRIVACY_REVIEW_REQUIRED' then 'privacy_review_required'
     when 'LIFETIME_POLICY_PENDING' then 'policy_pending' else 'completion_stale' end;
   reasons:=reasons||to_jsonb(code);
 end;
 if not exists(select 1 from public.user_story_game_consent c where c.edition_id=edition.id and c.user_id=owner
   and c.project_id=p_project_id and c.status='active' and c.revision=head.consent_revision
   and c.policy_epoch=(select policy_epoch from public.user_memoir_project where user_id=owner and project_id=p_project_id)) then
   reasons:=reasons||'"adaptation_consent_required"'::jsonb;
 end if;
 authority:=jsonb_array_length(reasons)=0;
 -- Persisted authority is not executable availability. Model binding, grounding
 -- review, game jobs and guarded private browser delivery remain unimplemented.
 return jsonb_build_object('schema_version',1,'authority_eligible',authority,'available',false,
   'reasons',reasons||'"runtime_unavailable"'::jsonb,'edition_id',edition.id,'revision',edition.revision,
   'manuscript_digest',edition.digest,'consent_revision',coalesce(head.consent_revision,0));
end $$;
revoke all on function public.read_story_game_eligibility(text) from public,anon;
grant execute on function public.read_story_game_eligibility(text) to authenticated;

create function public.invalidate_formal_memoir(p_owner uuid,p_project text) returns void
language plpgsql security definer set search_path='' as $$
begin
 -- The trigger owns the lifetime identity row before touching formal rows.
 -- Preference writers already hold profile -> identity and must never request
 -- project here. Other invalidators take project -> profile -> identity first.
 -- Retain metadata hashes, never stale prose; purge stays in the writer's txn.
 delete from public.user_formal_memoir_chapter c using public.user_formal_memoir_run r
   where c.run_id=r.id and r.user_id=p_owner and r.project_id=p_project;
 update public.user_formal_memoir_plan p set evidence='[]' from public.user_formal_memoir_run r
   where p.run_id=r.id and r.user_id=p_owner and r.project_id=p_project and p.evidence<>'[]'::jsonb;
 update public.user_formal_memoir_run set state='stale',token=null,lease_until=null,fence=fence+1
   where user_id=p_owner and project_id=p_project and state<>'stale';
 update public.user_formal_memoir_edition set active=false where user_id=p_owner and project_id=p_project and active;
end $$;
revoke all on function public.invalidate_formal_memoir(uuid,text) from public,anon,authenticated,service_role;

create function public.invalidate_formal_memoir_authority() returns trigger
language plpgsql security definer set search_path='' as $$
declare changed boolean:=false; owner uuid; project text;
begin
 owner:=coalesce(new.user_id,old.user_id);project:=coalesce(new.project_id,old.project_id);
 if tg_table_name='user_memoir_project' then
   changed:=old.policy_epoch is distinct from new.policy_epoch or old.source_sequence is distinct from new.source_sequence
     or old.event_sequence is distinct from new.event_sequence;
 elsif tg_table_name='user_lifetime_conversation' then
   changed:=old.preference_revision is distinct from new.preference_revision;
 elsif tg_table_name='user_conversation_phase' then
   changed:=tg_op='DELETE' or old.revision is distinct from new.revision;
 elsif tg_table_name='user_narrator_source' then
   changed:=tg_op='DELETE' or old.version is distinct from new.version or old.status is distinct from new.status or old.text is distinct from new.text;
 end if;
 if changed then
   if tg_table_name<>'user_lifetime_conversation' then
     -- Do not lock formal rows before profile/identity: a preference writer
     -- could otherwise hold profile while waiting for those formal rows.
     perform 1 from public.user_memoir_project where user_id=owner and project_id=project for update;
     perform 1 from public.user_profile where user_id=owner for share;
     perform 1 from public.user_lifetime_conversation where user_id=owner and project_id=project for share;
   end if;
   perform public.invalidate_formal_memoir(owner,project);
 end if;
 return coalesce(new,old);
end $$;
revoke all on function public.invalidate_formal_memoir_authority() from public,anon,authenticated,service_role;
create trigger formal_project_invalidation after update on public.user_memoir_project
 for each row execute function public.invalidate_formal_memoir_authority();
create trigger formal_preference_invalidation after update on public.user_lifetime_conversation
 for each row execute function public.invalidate_formal_memoir_authority();
create trigger formal_phase_invalidation after update or delete on public.user_conversation_phase
 for each row execute function public.invalidate_formal_memoir_authority();
create trigger formal_original_invalidation after update or delete on public.user_narrator_source
 for each row execute function public.invalidate_formal_memoir_authority();
commit;
