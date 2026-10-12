-- Selected-source collection work. Durable references and bounded windows only.
-- No historical mapping, backfill, deployment or feature activation.
begin;
create table public.user_lifetime_collection (
 user_id uuid not null, project_id text not null, revision bigint not null default 0,
 periods jsonb not null default '{}', ready boolean not null default false,
 source_revision bigint not null default 0, policy_epoch bigint not null,
 preference_revision bigint not null, source_fingerprint text,
 primary key(user_id,project_id),
 foreign key(user_id,project_id) references public.user_lifetime_conversation(user_id,project_id) on delete cascade
);
create table public.user_lifetime_collection_selection (
 user_id uuid not null,project_id text not null,source_id uuid not null,source_version bigint not null,
 source_hash text not null,ordinal integer not null,
 primary key(user_id,project_id,source_id),
 foreign key(user_id,project_id) references public.user_lifetime_collection(user_id,project_id) on delete cascade
);
create table public.user_lifetime_collection_job (
 id uuid primary key default gen_random_uuid(),snapshot_id uuid not null default gen_random_uuid(),
 user_id uuid not null,project_id text not null,conversation_id uuid not null,
 kind text not null check(kind in ('BuildFreePreview','BuildSourceExport','BuildOutline')),
 title text not null check(length(title) between 1 and 200),locale text not null,
 policy_epoch bigint not null,preference_revision bigint not null,collection_revision bigint not null,
 source_count integer not null,source_pages integer not null,next_page integer not null default 0,
 manifest_digest text not null,root_digest text not null,dedup_key text not null,
 state text not null default 'QUEUED' check(state in ('QUEUED','RUNNING','SUCCEEDED','FAILED','STALE')),
 token uuid,lease_until timestamptz,attempts integer not null default 0,error text,
 created_at timestamptz not null default clock_timestamp(),
 unique(user_id,project_id,dedup_key),
 foreign key(user_id,conversation_id) references public.user_lifetime_conversation(user_id,conversation_id) on delete cascade
);
create index lifetime_collection_owner_history on public.user_lifetime_collection_job(user_id,project_id,created_at desc,id desc);
create index lifetime_collection_pending on public.user_lifetime_collection_job(state,created_at);
create table public.user_lifetime_collection_job_source (
 job_id uuid not null references public.user_lifetime_collection_job(id) on delete cascade,
 ordinal integer not null,source_id uuid not null,source_version bigint not null,source_hash text not null,
 original_length integer not null,first_page integer not null,page_count integer not null,
 primary key(job_id,ordinal),unique(job_id,source_id)
);
create table public.user_lifetime_collection_job_page (
 job_id uuid not null references public.user_lifetime_collection_job(id) on delete cascade,
 page_number integer not null,source_id uuid not null,source_version bigint not null,
 char_start integer not null,char_end integer not null,page_digest text not null,result jsonb,
 primary key(job_id,page_number)
);
create table public.user_lifetime_collection_job_node (
 id uuid primary key default gen_random_uuid(),job_id uuid not null references public.user_lifetime_collection_job(id) on delete cascade,
 ordinal integer not null,level integer not null,parent_id uuid references public.user_lifetime_collection_job_node(id),
 metadata jsonb not null,result jsonb not null,digest text not null,children uuid[] not null default '{}',
 unique(job_id,ordinal)
);
create index lifetime_collection_node_frontier on public.user_lifetime_collection_job_node(job_id,level,ordinal) where parent_id is null;
create table public.user_lifetime_collection_job_edge (
 job_id uuid not null references public.user_lifetime_collection_job(id) on delete cascade,
 parent_node uuid not null references public.user_lifetime_collection_job_node(id) on delete cascade,
 parent_section integer not null,child_node uuid not null references public.user_lifetime_collection_job_node(id),child_section integer not null,
 primary key(job_id,child_node,child_section)
);
alter table public.user_lifetime_collection_job_node enable row level security;
alter table public.user_lifetime_collection_job_edge enable row level security;
revoke all on public.user_lifetime_collection_job_node,public.user_lifetime_collection_job_edge from public,anon,authenticated;
create table public.user_lifetime_collection_job_cursor (
 id uuid primary key default gen_random_uuid(),job_id uuid not null references public.user_lifetime_collection_job(id) on delete cascade,
 user_id uuid not null,root_digest text not null,next_page integer not null,
 expires_at timestamptz not null default clock_timestamp()+interval '1 hour',
 unique(job_id,root_digest,next_page)
);
alter table public.user_lifetime_collection enable row level security;
alter table public.user_lifetime_collection_selection enable row level security;
alter table public.user_lifetime_collection_job enable row level security;
alter table public.user_lifetime_collection_job_source enable row level security;
alter table public.user_lifetime_collection_job_page enable row level security;
alter table public.user_lifetime_collection_job_cursor enable row level security;
revoke all on public.user_lifetime_collection,public.user_lifetime_collection_selection,
 public.user_lifetime_collection_job,public.user_lifetime_collection_job_source,
 public.user_lifetime_collection_job_page,public.user_lifetime_collection_job_cursor from public,anon,authenticated;

-- Disposable editorial output is purged in the same transaction that revokes
-- its authority. Original narrator storage and non-sensitive scope audit remain.
create function public.invalidate_lifetime_collection_scope(p_owner uuid,p_project text,p_outline_only boolean default false) returns void
language plpgsql security definer set search_path=public,auth as $$
begin
 update public.user_lifetime_collection_job set state='STALE',token=null,lease_until=null,error='SOURCE_OR_COLLECTION_CHANGED'
  where user_id=p_owner and (p_project is null or project_id=p_project) and (not p_outline_only or kind='BuildOutline');
 delete from public.user_lifetime_collection_job_edge where job_id in (select id from public.user_lifetime_collection_job
  where user_id=p_owner and (p_project is null or project_id=p_project) and (not p_outline_only or kind='BuildOutline'));
 delete from public.user_lifetime_collection_job_node where job_id in (select id from public.user_lifetime_collection_job
  where user_id=p_owner and (p_project is null or project_id=p_project) and (not p_outline_only or kind='BuildOutline'));
 delete from public.user_lifetime_collection_job_cursor where job_id in (select id from public.user_lifetime_collection_job
  where user_id=p_owner and (p_project is null or project_id=p_project) and (not p_outline_only or kind='BuildOutline'));
end $$;
create function public.invalidate_lifetime_collection_authority() returns trigger
language plpgsql security definer set search_path=public,auth as $$
begin
 if tg_table_name='user_memoir_project' then
  if old.policy_epoch is distinct from new.policy_epoch then perform public.invalidate_lifetime_collection_scope(new.user_id,new.project_id);end if;
 elsif tg_table_name='user_lifetime_conversation' then
  if old.preference_revision is distinct from new.preference_revision then perform public.invalidate_lifetime_collection_scope(new.user_id,new.project_id);end if;
 elsif tg_table_name='user_lifetime_collection' then
  if old.revision is distinct from new.revision then perform public.invalidate_lifetime_collection_scope(new.user_id,new.project_id,true);end if;
 elsif tg_table_name='story_entitlements' then
  if tg_op='DELETE' or new.status is distinct from 'paid' then perform public.invalidate_lifetime_collection_scope(old.user_id,null,true);end if;
 elsif tg_table_name='users' then
  if old.is_anonymous is distinct from new.is_anonymous and new.is_anonymous then perform public.invalidate_lifetime_collection_scope(new.id,null,true);end if;
 end if;
 return coalesce(new,old);
end $$;
create trigger lifetime_collection_policy_invalidation after update on public.user_memoir_project
 for each row execute function public.invalidate_lifetime_collection_authority();
create trigger lifetime_collection_preference_invalidation after update on public.user_lifetime_conversation
 for each row execute function public.invalidate_lifetime_collection_authority();
create trigger lifetime_collection_selection_invalidation after update on public.user_lifetime_collection
 for each row execute function public.invalidate_lifetime_collection_authority();
create trigger lifetime_collection_account_invalidation after update on auth.users
 for each row execute function public.invalidate_lifetime_collection_authority();
-- Production's existing commercial migration owns this table. Isolated core
-- fixture schemas may omit that independent subsystem; its calls fail closed.
do $$ begin if to_regclass('public.story_entitlements') is not null then
 execute 'create trigger lifetime_collection_entitlement_invalidation after update or delete on public.story_entitlements for each row execute function public.invalidate_lifetime_collection_authority()';
end if;end $$;
revoke all on function public.invalidate_lifetime_collection_scope(uuid,text,boolean),public.invalidate_lifetime_collection_authority()
 from public,anon,authenticated,service_role;

create function public.read_lifetime_collection_selection(p_project_id text,p_after uuid default null,p_limit integer default 8) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare owner uuid:=auth.uid(); doc public.user_lifetime_collection%rowtype; tasks jsonb;
 anchor public.user_lifetime_collection_job%rowtype; more boolean; next_cursor uuid;
begin
 if owner is null or not exists(select 1 from public.user_lifetime_conversation where user_id=owner and project_id=p_project_id) then
  raise exception 'collection unavailable' using errcode='42501';end if;
 if p_limit is null or p_limit<1 or p_limit>8 then raise exception 'invalid page bound' using errcode='22023';end if;
 if p_after is not null then
  select * into anchor from public.user_lifetime_collection_job where id=p_after and user_id=owner and project_id=p_project_id;
  if not found then raise exception 'task cursor unavailable' using errcode='42501';end if;
 end if;
 select * into doc from public.user_lifetime_collection where user_id=owner and project_id=p_project_id;
 with bounded as materialized (
  select id,created_at,jsonb_build_object('id',id,'project_id',project_id,'kind',kind,'status',state,'attempts',attempts,
   'result',null,'error',error,'created_at',created_at) item from public.user_lifetime_collection_job
  where user_id=owner and project_id=p_project_id and (p_after is null or (created_at,id)<(anchor.created_at,anchor.id))
  order by created_at desc,id desc limit p_limit+1
 ), visible as (select * from bounded order by created_at desc,id desc limit p_limit)
 select coalesce((select jsonb_agg(item order by created_at desc,id desc) from visible),'[]'),
  (select count(*)>p_limit from bounded),(select id from visible order by created_at,id limit 1)
 into tasks,more,next_cursor;
 return jsonb_build_object('revision',coalesce(doc.revision,0),'periods',coalesce(doc.periods,'{}'),'ready',
  coalesce(doc.ready,false) and exists(select 1 from public.user_memoir_project p join public.user_lifetime_conversation i using(user_id,project_id)
   where p.user_id=owner and p.project_id=p_project_id and p.source_sequence=doc.source_revision
    and p.policy_epoch=doc.policy_epoch and i.preference_revision=doc.preference_revision),
  'source_fingerprint',doc.source_fingerprint,'tasks',tasks,'tasks_complete',not more,
  'tasks_next_cursor',case when more then next_cursor else null end,
  'workflow','canonical_selected_jobs','legacy_jobs_supported',false);
end $$;

create function public.set_lifetime_collection(p_project_id text,p_expected_revision bigint,p_periods jsonb,p_ready boolean) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare owner uuid:=auth.uid(); project public.user_memoir_project%rowtype; identity public.user_lifetime_conversation%rowtype;
 doc public.user_lifetime_collection%rowtype; item record; ids uuid[]; manifest jsonb; fingerprint text;
begin
 if owner is null then raise exception 'authenticated owner required' using errcode='42501';end if;
 select * into project from public.user_memoir_project where user_id=owner and project_id=p_project_id for update;
 perform 1 from public.user_profile where user_id=owner for share;
 select * into identity from public.user_lifetime_conversation where user_id=owner and project_id=p_project_id for share;
 if not found then raise exception 'collection unavailable' using errcode='42501';end if;
 select * into doc from public.user_lifetime_collection where user_id=owner and project_id=p_project_id for update;
 if p_expected_revision is null or coalesce(doc.revision,0)<>p_expected_revision then raise exception 'collection revision conflict' using errcode='40001';end if;
 if p_ready is null or jsonb_typeof(p_periods) is distinct from 'object' or octet_length(p_periods::text)>200000 then raise exception 'invalid collection periods';end if;
 for item in select key,value from jsonb_each(p_periods) loop
  if item.key not in ('baby','toddler','childhood','adolescence','young_adulthood','midlife','later_life')
   or jsonb_typeof(item.value) is distinct from 'object' or item.value- array['status','memory_ids','note']<>'{}'::jsonb
   or jsonb_typeof(item.value->'status') is distinct from 'string' or item.value->>'status' not in ('recorded','skipped','not_applicable')
   or jsonb_typeof(item.value->'memory_ids') is distinct from 'array' or jsonb_array_length(item.value->'memory_ids')>1000
   or jsonb_typeof(item.value->'note') is distinct from 'string' or length(item.value->>'note')>500
   or (item.value->>'status'='recorded' and jsonb_array_length(item.value->'memory_ids')=0)
   or (item.value->>'status'<>'recorded' and (length(trim(item.value->>'note'))=0 or jsonb_array_length(item.value->'memory_ids')<>0)) then
   raise exception 'invalid collection period';end if;
 end loop;
 select coalesce(array_agg(selected order by first_position),'{}') into ids from (
  select v.value::uuid selected,min(array_position(array['baby','toddler','childhood','adolescence','young_adulthood','midlife','later_life'],p.key)*1001+v.n) first_position
  from jsonb_each(p_periods)p cross join lateral jsonb_array_elements_text(p.value->'memory_ids') with ordinality v(value,n)
  group by v.value::uuid) ordered_selection;
 if cardinality(ids)>1000 or (p_ready and ((select count(*) from jsonb_each(p_periods))<>7 or cardinality(ids)=0)) then
  raise exception 'collection selection limit or readiness incomplete';end if;
 if exists(select 1 from unnest(ids) selected where not exists(select 1 from public.user_narrator_source s
   where s.user_id=owner and s.project_id=p_project_id and s.id=selected and s.status='active' and s.kind in ('narrator_chat','narrator_transcript'))) then
  raise exception 'collection references unavailable narrator evidence' using errcode='40001';end if;
 select coalesce(jsonb_agg(jsonb_build_object('id',s.id,'version',s.version,'hash',encode(sha256(convert_to(s.text,'UTF8')),'hex')) order by n),'[]')
  into manifest from unnest(ids) with ordinality a(id,n) join public.user_narrator_source s on s.id=a.id and s.user_id=owner and s.project_id=p_project_id;
 fingerprint:=encode(sha256(convert_to(jsonb_build_object('sources',manifest,'source_revision',project.source_sequence)::text,'UTF8')),'hex');
 insert into public.user_lifetime_collection(user_id,project_id,revision,periods,ready,source_revision,policy_epoch,preference_revision,source_fingerprint)
 values(owner,p_project_id,p_expected_revision+1,p_periods,p_ready,project.source_sequence,project.policy_epoch,identity.preference_revision,fingerprint)
 on conflict(user_id,project_id) do update set revision=excluded.revision,periods=excluded.periods,ready=excluded.ready,
 source_revision=excluded.source_revision,policy_epoch=excluded.policy_epoch,preference_revision=excluded.preference_revision,source_fingerprint=excluded.source_fingerprint;
 delete from public.user_lifetime_collection_selection where user_id=owner and project_id=p_project_id;
 insert into public.user_lifetime_collection_selection(user_id,project_id,source_id,source_version,source_hash,ordinal)
 select owner,p_project_id,(v->>'id')::uuid,(v->>'version')::bigint,v->>'hash',n::integer
 from jsonb_array_elements(manifest) with ordinality m(v,n);
 return public.read_lifetime_collection_selection(p_project_id);
end $$;

-- Consistent lock graph: auth-user, project, profile/identity, collection, entitlement, job.
-- Callers must not hold a weaker project lock before requesting this helper.
create function public.lock_lifetime_collection_job(p_job_id uuid,p_token uuid default null) returns public.user_lifetime_collection_job
language plpgsql security definer set search_path=public,auth as $$
declare job public.user_lifetime_collection_job%rowtype; project public.user_memoir_project%rowtype;
 identity public.user_lifetime_conversation%rowtype; doc public.user_lifetime_collection%rowtype;
begin
 select * into job from public.user_lifetime_collection_job where id=p_job_id;
 if not found then raise exception 'collection job unavailable' using errcode='42501';end if;
 if job.kind='BuildOutline' then
  perform 1 from auth.users where id=job.user_id and not is_anonymous for share;
  if not found then raise exception 'paid memoir entitlement required' using errcode='42501';end if;
 end if;
 select * into project from public.user_memoir_project where user_id=job.user_id and project_id=job.project_id for share;
 perform 1 from public.user_profile where user_id=job.user_id for share;
 if not found then perform pg_advisory_xact_lock_shared(hashtextextended('memoir-profile:'||job.user_id::text,0));end if;
 select * into identity from public.user_lifetime_conversation where user_id=job.user_id and project_id=job.project_id for share;
 select * into doc from public.user_lifetime_collection where user_id=job.user_id and project_id=job.project_id for share;
 if job.kind='BuildOutline' then
  perform 1 from public.story_entitlements where user_id=job.user_id and status='paid' for share;
  if not found then raise exception 'paid memoir entitlement required' using errcode='42501';end if;
 end if;
 select * into job from public.user_lifetime_collection_job where id=p_job_id for update;
 if identity.conversation_id is distinct from job.conversation_id or project.policy_epoch is distinct from job.policy_epoch
  or identity.preference_revision is distinct from job.preference_revision or (job.kind='BuildOutline' and coalesce(doc.revision,0)<>job.collection_revision)
  or job.state='STALE' or (p_token is not null and (job.token is distinct from p_token or job.lease_until<=clock_timestamp() or job.state<>'RUNNING')) then
  raise exception 'stale collection job' using errcode='40001';end if;
 if exists(select 1 from public.user_lifetime_collection_job_source j left join public.user_narrator_source s
  on s.id=j.source_id and s.user_id=job.user_id and s.project_id=job.project_id
  where j.job_id=job.id and (s.id is null or s.version<>j.source_version or s.status<>'active'
   or s.kind not in ('narrator_chat','narrator_transcript') or length(s.text)<>j.original_length)) then
  raise exception 'stale collection source manifest' using errcode='40001';end if;
 if job.kind='BuildOutline' then
  if not coalesce(doc.ready,false) or doc.policy_epoch<>job.policy_epoch or doc.preference_revision<>job.preference_revision then
   raise exception 'collection confirmation changed' using errcode='40001';end if;
 end if;
 return job;
end $$;

create function public.create_lifetime_collection_job(p_project_id text,p_kind text,p_title text,p_source_ids jsonb,
 p_expected_revision bigint default null,p_locale text default 'en-AU',p_paused boolean default false) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare owner uuid:=auth.uid(); project public.user_memoir_project%rowtype; identity public.user_lifetime_conversation%rowtype;
 doc public.user_lifetime_collection%rowtype; job public.user_lifetime_collection_job%rowtype; manifest jsonb; ids uuid[];
 digest text; dedup text; count_sources integer; count_pages integer;
begin
 if owner is null then raise exception 'authenticated owner required' using errcode='42501';end if;
 if p_kind='BuildOutline' then
  perform 1 from auth.users where id=owner and not is_anonymous for share;
  if not found then raise exception 'paid memoir entitlement required' using errcode='42501';end if;
 end if;
 if p_kind is null or p_kind not in ('BuildFreePreview','BuildSourceExport','BuildOutline') or p_locale is null or p_locale not in ('en-AU','zh-CN')
  or p_title is null or length(p_title) not between 1 and 200 then raise exception 'invalid collection job';end if;
 select * into project from public.user_memoir_project where user_id=owner and project_id=p_project_id for share;
 perform 1 from public.user_profile where user_id=owner for share;
 if not found then perform pg_advisory_xact_lock_shared(hashtextextended('memoir-profile:'||owner::text,0));end if;
 select * into identity from public.user_lifetime_conversation where user_id=owner and project_id=p_project_id for share;
 if not found then raise exception 'collection unavailable' using errcode='42501';end if;
 select * into doc from public.user_lifetime_collection where user_id=owner and project_id=p_project_id for share;
 if p_kind='BuildOutline' then
  if p_expected_revision is null or doc.revision is distinct from p_expected_revision or not coalesce(doc.ready,false)
   or doc.source_revision<>project.source_sequence or doc.policy_epoch<>project.policy_epoch or doc.preference_revision<>identity.preference_revision then
   raise exception 'confirm current collection before organising' using errcode='40001';end if;
  perform 1 from public.story_entitlements where user_id=owner and status='paid' for share;
  if not found or exists(select 1 from auth.users where id=owner and is_anonymous) then raise exception 'paid memoir entitlement required' using errcode='42501';end if;
  select array_agg(source_id order by ordinal) into ids from public.user_lifetime_collection_selection where user_id=owner and project_id=p_project_id;
  if exists(select 1 from public.user_lifetime_collection_selection c left join public.user_narrator_source s on s.user_id=c.user_id and s.project_id=c.project_id and s.id=c.source_id
    where c.user_id=owner and c.project_id=p_project_id and (s.id is null or s.version<>c.source_version or s.status<>'active'
     or encode(sha256(convert_to(s.text,'UTF8')),'hex')<>c.source_hash)) then raise exception 'collection sources changed' using errcode='40001';end if;
 else
  if jsonb_typeof(p_source_ids) is distinct from 'array' or jsonb_array_length(p_source_ids) not between 1 and 1000 then raise exception 'select 1 to 1000 sources';end if;
  select array_agg(value::uuid order by n) into ids from jsonb_array_elements_text(p_source_ids) with ordinality a(value,n);
  if cardinality(ids)<>(select count(distinct x) from unnest(ids)x) then raise exception 'duplicate source selection';end if;
 end if;
 if coalesce(cardinality(ids),0) not between 1 and 1000 then raise exception 'select 1 to 1000 sources';end if;
 if exists(select 1 from unnest(ids) selected where not exists(select 1 from public.user_narrator_source s
  where s.user_id=owner and s.project_id=p_project_id and s.id=selected and s.status='active' and s.kind in ('narrator_chat','narrator_transcript'))) then
  raise exception 'selected narrator source unavailable' using errcode='40001';end if;
 select jsonb_agg(jsonb_build_object('id',s.id,'version',s.version,'hash',encode(sha256(convert_to(s.text,'UTF8')),'hex'),
  'length',length(s.text),'pages',(length(s.text)+2047)/2048) order by n),count(*),sum((length(s.text)+2047)/2048)
  into manifest,count_sources,count_pages from unnest(ids) with ordinality a(id,n) join public.user_narrator_source s
   on s.id=a.id and s.user_id=owner and s.project_id=p_project_id;
 digest:=encode(sha256(convert_to(manifest::text,'UTF8')),'hex');
 dedup:=encode(sha256(convert_to(jsonb_build_object('manifest',digest,'kind',p_kind,'title',p_title,'locale',p_locale,
  'policy',project.policy_epoch,'preferences',identity.preference_revision,'collection',case when p_kind='BuildOutline' then coalesce(doc.revision,0) else 0 end)::text,'UTF8')),'hex');
 if p_paused is distinct from false and not exists(select 1 from public.user_lifetime_collection_job where user_id=owner and project_id=p_project_id and dedup_key=dedup) then
  raise exception 'lifetime generation paused' using errcode='55000';end if;
 insert into public.user_lifetime_collection_job(user_id,project_id,conversation_id,kind,title,locale,policy_epoch,preference_revision,
  collection_revision,source_count,source_pages,manifest_digest,root_digest,dedup_key)
 values(owner,p_project_id,identity.conversation_id,p_kind,p_title,p_locale,project.policy_epoch,identity.preference_revision,
  case when p_kind='BuildOutline' then coalesce(doc.revision,0) else 0 end,count_sources,count_pages,digest,digest,dedup)
 on conflict(user_id,project_id,dedup_key) do nothing returning * into job;
 if job.id is null then select * into job from public.user_lifetime_collection_job where user_id=owner and project_id=p_project_id and dedup_key=dedup;
 else
  insert into public.user_lifetime_collection_job_source(job_id,ordinal,source_id,source_version,source_hash,original_length,first_page,page_count)
  select job.id,n::integer,(v->>'id')::uuid,(v->>'version')::bigint,v->>'hash',(v->>'length')::integer,
   (sum((v->>'pages')::integer) over(order by n)-(v->>'pages')::integer)::integer,(v->>'pages')::integer
  from jsonb_array_elements(manifest) with ordinality m(v,n);
 end if;
 return jsonb_build_object('id',job.id,'project_id',job.project_id,'kind',job.kind,'status',job.state,'attempts',job.attempts,
  'created_at',job.created_at,'result',null,'error',job.error,'source_count',job.source_count,'source_pages',job.source_pages);
end $$;

create function public.pending_lifetime_collection_jobs(p_limit integer default 8,p_include_outline boolean default true) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
begin
 if p_limit is null or p_limit not between 1 and 32 then raise exception 'invalid job limit';end if;
 return coalesce((select jsonb_agg(id order by created_at) from (select id,created_at from public.user_lifetime_collection_job
  where (state='QUEUED' or state='RUNNING' and lease_until<=clock_timestamp()) and (p_include_outline or kind<>'BuildOutline') order by created_at limit p_limit) j),'[]');
end $$;
create function public.claim_lifetime_collection_job(p_job_id uuid,p_run_seconds integer default 300) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare job public.user_lifetime_collection_job%rowtype; claim_token uuid:=gen_random_uuid();
begin
 if p_run_seconds is null or p_run_seconds not between 1 and 600 then raise exception 'invalid job duration';end if;
 begin
  job:=public.lock_lifetime_collection_job(p_job_id);
 exception when serialization_failure then
  update public.user_lifetime_collection_job set state='STALE',token=null,lease_until=null,error='SOURCE_OR_COLLECTION_CHANGED' where id=p_job_id;
  return null;
 end;
 if job.state='SUCCEEDED' or job.token is not null and job.lease_until>clock_timestamp() then return null;end if;
 if job.attempts>=3 then
  update public.user_lifetime_collection_job set state='FAILED',token=null,lease_until=null,error='BOUNDED_JOB_RETRY' where id=p_job_id;
  return null;
 end if;
 update public.user_lifetime_collection_job set state='RUNNING',token=claim_token,lease_until=clock_timestamp()+make_interval(secs=>p_run_seconds),attempts=attempts+1,error=null
  where id=p_job_id returning * into job;
 return jsonb_build_object('id',job.id,'token',job.token,'user_id',job.user_id,'project_id',job.project_id,'kind',job.kind);
end $$;

create function public.read_lifetime_collection_job_page(p_job_id uuid,p_token uuid) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare job public.user_lifetime_collection_job%rowtype; selected public.user_lifetime_collection_job_source%rowtype;
 source public.user_narrator_source%rowtype; lo integer; hi integer; preferences jsonb; payload jsonb; previous_owner text;
 children jsonb:='[]'; child record; source_items jsonb:='[]'; phase text:='leaf';
begin
 -- Successful final page is a stable completion receipt; it contains no source bytes.
 select * into job from public.user_lifetime_collection_job where id=p_job_id;
 if job.state='SUCCEEDED' and job.token=p_token then
  perform public.lock_lifetime_collection_job(p_job_id);return jsonb_build_object('complete',true,'job_id',job.id,'root_digest',job.root_digest);end if;
 job:=public.lock_lifetime_collection_job(p_job_id,p_token);
 if job.next_page<job.source_pages then
 select * into selected from public.user_lifetime_collection_job_source where job_id=job.id and job.next_page>=first_page and job.next_page<first_page+page_count;
 select * into source from public.user_narrator_source where user_id=job.user_id and project_id=job.project_id and id=selected.source_id;
 lo:=(job.next_page-selected.first_page)*2048;hi:=least(lo+2048,selected.original_length);
 source_items:=jsonb_build_array(jsonb_build_object('id',source.id,'project_id',source.project_id,'version',source.version,'sequence',source.sequence,
   'text',substring(source.text from lo+1 for hi-lo),'char_start',lo,'char_end',hi,'original_length',selected.original_length,
   'kind',source.kind,'language',source.language,'status',source.status,'author_role','storyteller'));
 else
  phase:='merge';
  for child in select metadata from public.user_lifetime_collection_job_node where job_id=job.id and parent_id is null order by level,ordinal limit 2 loop
   children:=children||jsonb_build_array(child.metadata);
  end loop;
  if jsonb_array_length(children)<2 then raise exception 'outline merge budget requires maintenance' using errcode='54000';end if;
 end if;
 previous_owner:=current_setting('request.jwt.claim.sub',true);perform set_config('request.jwt.claim.sub',job.user_id::text,true);
 preferences:=public.read_lifetime_pinned(job.conversation_id);
 preferences:=jsonb_set(preferences,'{known_continuity}',coalesce((select jsonb_agg(jsonb_build_object('schema_version',1)||record||jsonb_build_object('data',
  jsonb_build_object('schema_version',1,'uncertainty',null)||(record->'data')||jsonb_build_object('source_refs',
   (select jsonb_agg(jsonb_build_object('schema_version',1)||ref) from jsonb_array_elements(record->'data'->'source_refs')ref))))
  from jsonb_array_elements(preferences->'known_continuity')record),'[]'));
 perform set_config('request.jwt.claim.sub',coalesce(previous_owner,''),true);
 payload:=jsonb_build_object('schema_version',1,'protocol','lifetime_collection_jobs','job_id',job.id,'token',job.token,
  'snapshot_id',job.snapshot_id,'user_id',job.user_id,'project_id',job.project_id,'conversation_id',job.conversation_id,
  'kind',job.kind,'locale',job.locale,'policy_epoch',job.policy_epoch,'preference_revision',job.preference_revision,
  'collection_revision',job.collection_revision,'root_digest',job.root_digest,'page_number',job.next_page,'preferences',preferences,
  'phase',phase,'sources',source_items,'child_groups',children);
 return payload||jsonb_build_object('page_digest',encode(sha256(convert_to(payload::text,'UTF8')),'hex'),'complete',false);
end $$;

create function public.lock_lifetime_collection_job_publication(p_fence jsonb) returns double precision
language plpgsql security definer set search_path=public,auth as $$
declare current_page jsonb; remaining double precision;
begin
 if jsonb_typeof(p_fence) is distinct from 'object' or (p_fence->>'user_id')::uuid is distinct from auth.uid() then
  raise exception 'collection publication owner mismatch' using errcode='42501';end if;
 current_page:=public.read_lifetime_collection_job_page((p_fence->>'job_id')::uuid,(p_fence->>'token')::uuid);
 if current_page-'complete' is distinct from p_fence or current_page->>'complete'<>'false' then
  raise exception 'stale collection publication' using errcode='40001';end if;
 select extract(epoch from lease_until-clock_timestamp()) into remaining from public.user_lifetime_collection_job where id=(p_fence->>'job_id')::uuid;
 return remaining;
end $$;

create function public.commit_lifetime_collection_job_page(p_fence jsonb,p_result jsonb default null) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare job public.user_lifetime_collection_job%rowtype; current_page jsonb; evidence jsonb; output_digest text;
 node_id uuid:=gen_random_uuid(); node_meta jsonb; section record; child record; refs text[]; expected text[];
 child_ids uuid[]:='{}'; node_level integer:=0; finished boolean; new_digest text; sections jsonb:='[]';
begin
 job:=public.lock_lifetime_collection_job((p_fence->>'job_id')::uuid,(p_fence->>'token')::uuid);
 current_page:=public.read_lifetime_collection_job_page(job.id,job.token);
 if current_page-'complete' is distinct from p_fence-'complete' then raise exception 'stale collection page commit' using errcode='40001';end if;
 if job.kind='BuildOutline' then
  if jsonb_typeof(p_result) is distinct from 'object' or p_result-array['title','sections']<>'{}'::jsonb
   or jsonb_typeof(p_result->'title') is distinct from 'string' or length(p_result->>'title') not between 1 and 200
   or jsonb_typeof(p_result->'sections') is distinct from 'array' or jsonb_array_length(p_result->'sections') not between 1 and 100
   or octet_length(p_result::text)>65536 then raise exception 'invalid outline result';end if;
  for section in select v,n from jsonb_array_elements(p_result->'sections') with ordinality a(v,n) loop
   if jsonb_typeof(section.v) is distinct from 'object' or jsonb_typeof(section.v->'title') is distinct from 'string'
    or length(section.v->>'title') not between 1 and 200 then raise exception 'invalid outline section';end if;
   if current_page->>'phase'='leaf' then
    if section.v-array['title','memory_ids']<>'{}'::jsonb or jsonb_typeof(section.v->'memory_ids') is distinct from 'array'
     or jsonb_array_length(section.v->'memory_ids')<>1 then raise exception 'invalid leaf coverage';end if;
    refs:=array_append(refs,section.v->'memory_ids'->>0);
   else
    if section.v-array['title','section_ids']<>'{}'::jsonb or jsonb_typeof(section.v->'section_ids') is distinct from 'array'
     or jsonb_array_length(section.v->'section_ids')<1 then raise exception 'invalid merge coverage';end if;
    refs:=refs||array(select jsonb_array_elements_text(section.v->'section_ids'));
   end if;
   sections:=sections||jsonb_build_array(jsonb_build_object('id',node_id::text||':'||section.n::text,'title',section.v->>'title'));
  end loop;
  if current_page->>'phase'='leaf' then
   expected:=array[current_page->'sources'->0->>'id'];
  else
   select array_agg(s->>'id' order by s->>'id') into expected from jsonb_array_elements(current_page->'child_groups')c
    cross join lateral jsonb_array_elements(c->'sections')s;
   select array_agg((v->>'id')::uuid) into child_ids from jsonb_array_elements(current_page->'child_groups')v;
   select max(level)+1 into node_level from public.user_lifetime_collection_job_node where id=any(child_ids) and job_id=job.id;
  end if;
  if (select array_agg(x order by x) from unnest(refs)x) is distinct from expected
   or cardinality(refs)<>(select count(distinct x) from unnest(refs)x) then raise exception 'outline omitted duplicated or invented coverage';end if;
  new_digest:=encode(sha256(convert_to(jsonb_build_object('job',job.id,'owner',job.user_id,'snapshot',job.snapshot_id,
   'policy',job.policy_epoch,'preferences',job.preference_revision,'page',current_page->>'page_digest','output',p_result)::text,'UTF8')),'hex');
  node_meta:=jsonb_build_object('id',node_id,'digest',new_digest,'title',p_result->>'title','sections',sections);
  if octet_length(node_meta::text)>12000 then raise exception 'outline title metadata budget exceeded' using errcode='54000';end if;
  insert into public.user_lifetime_collection_job_node(id,job_id,ordinal,level,metadata,result,digest,children)
   values(node_id,job.id,job.next_page,node_level,node_meta,p_result,new_digest,child_ids);
  if current_page->>'phase'='merge' then
   for section in select v,n from jsonb_array_elements(p_result->'sections') with ordinality a(v,n) loop
    for child in select value from jsonb_array_elements_text(section.v->'section_ids') loop
     insert into public.user_lifetime_collection_job_edge(job_id,parent_node,parent_section,child_node,child_section)
      values(job.id,node_id,section.n,(split_part(child.value,':',1))::uuid,(split_part(child.value,':',2))::integer);
    end loop;
   end loop;
   update public.user_lifetime_collection_job_node set parent_id=node_id where job_id=job.id and id=any(child_ids) and parent_id is null;
  end if;
 else
  if p_result is not null then raise exception 'deterministic task cannot accept generated content';end if;
 end if;
 if current_page->>'phase'='leaf' then
  evidence:=current_page->'sources'->0;
  insert into public.user_lifetime_collection_job_page(job_id,page_number,source_id,source_version,char_start,char_end,page_digest)
  values(job.id,job.next_page,(evidence->>'id')::uuid,(evidence->>'version')::bigint,(evidence->>'char_start')::integer,
   (evidence->>'char_end')::integer,current_page->>'page_digest');
 end if;
 output_digest:=encode(sha256(convert_to(job.root_digest||':'||(current_page->>'page_digest')||':'||coalesce(new_digest,''),'UTF8')),'hex');
 finished:=job.next_page+1>=job.source_pages and (job.kind<>'BuildOutline' or
  (select count(*)=1 from public.user_lifetime_collection_job_node where job_id=job.id and parent_id is null));
 update public.user_lifetime_collection_job set next_page=next_page+1,root_digest=output_digest,
  state=case when finished then 'SUCCEEDED' else 'RUNNING' end where id=job.id;
 return jsonb_build_object('complete',finished,'next_page',job.next_page+1,'root_digest',output_digest);
end $$;

create function public.lifetime_collection_root_section(p_job_id uuid,p_page integer) returns text
language sql stable security definer set search_path=public,auth as $$
 with recursive ancestry(node_id,section_number,depth) as (
  select id,1,0 from public.user_lifetime_collection_job_node where job_id=p_job_id and ordinal=p_page
  union all
  select e.parent_node,e.parent_section,a.depth+1 from ancestry a join public.user_lifetime_collection_job_edge e
   on e.job_id=p_job_id and e.child_node=a.node_id and e.child_section=a.section_number where a.depth<64
 ) select node_id::text||':'||section_number::text from ancestry order by depth desc limit 1;
$$;
revoke all on function public.lifetime_collection_root_section(uuid,integer) from public,anon,authenticated,service_role;

create function public.read_lifetime_collection_job(p_job_id uuid,p_cursor uuid default null,p_limit integer default 8) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare job public.user_lifetime_collection_job%rowtype; cursor_row public.user_lifetime_collection_job_cursor%rowtype;
 after_page integer:=0; result_after integer; items jsonb; result jsonb; next_cursor uuid; complete boolean;
begin
 if p_limit is null or p_limit not between 1 and 8 then raise exception 'invalid result page limit';end if;
 select * into job from public.user_lifetime_collection_job where id=p_job_id and user_id=auth.uid();
 if not found then raise exception 'collection job unavailable' using errcode='42501';end if;
 job:=public.lock_lifetime_collection_job(p_job_id);
 if p_cursor is not null then
  select * into cursor_row from public.user_lifetime_collection_job_cursor where id=p_cursor and job_id=job.id and user_id=auth.uid();
  if not found or cursor_row.expires_at<=clock_timestamp() or cursor_row.root_digest<>job.root_digest then raise exception 'stale result cursor' using errcode='40001';end if;
  after_page:=cursor_row.next_page;
 end if;
 if job.state='SUCCEEDED' then
  select coalesce(jsonb_agg(item order by page_number),'[]'),coalesce(max(page_number)+1,after_page) into items,result_after from (
   select p.page_number,jsonb_build_object('id',s.id,'version',s.version,'content',substring(s.text from p.char_start+1 for p.char_end-p.char_start),
    'char_start',p.char_start,'char_end',p.char_end,'original_length',length(s.text),'source_kind',s.kind,'language',s.language,'root_section_id',case when job.kind='BuildOutline' then public.lifetime_collection_root_section(job.id,p.page_number) else null end) item
   from public.user_lifetime_collection_job_page p join public.user_narrator_source s on s.id=p.source_id
    and s.user_id=job.user_id and s.project_id=job.project_id and s.version=p.source_version
   where p.job_id=job.id and p.page_number>=after_page order by p.page_number limit p_limit) bounded;
  complete:=result_after>=job.source_pages;
  if not complete then
   insert into public.user_lifetime_collection_job_cursor(job_id,user_id,root_digest,next_page) values(job.id,job.user_id,job.root_digest,result_after)
    on conflict(job_id,root_digest,next_page) do update set expires_at=clock_timestamp()+interval '1 hour' returning id into next_cursor;
  end if;
  result:=jsonb_build_object('schema_version',1,'kind',job.kind,'title',job.title,'sources',items,
   'coverage',jsonb_build_object('complete',true,'scope','selected_sources','source_count',job.source_count,'source_pages',job.source_pages,
    'manifest_digest',job.manifest_digest,'root_digest',job.root_digest),'proposed',job.kind='BuildOutline');
  if job.kind='BuildOutline' then
   result:=result||jsonb_build_object('sections',(select metadata->'sections' from public.user_lifetime_collection_job_node where job_id=job.id and parent_id is null),
    'suggested_title',(select metadata->>'title' from public.user_lifetime_collection_job_node where job_id=job.id and parent_id is null),
    'source_references_paginated',true,'provenance','derived_proposal','publication_approved',false);
  end if;
  if job.kind='BuildFreePreview' then result:=result||jsonb_build_object('blocks',coalesce((select jsonb_agg(jsonb_build_object(
   'type','narrative','text',v->>'content','source_memory_ids',jsonb_build_array(v->>'id'),'char_start',v->'char_start','char_end',v->'char_end')) from jsonb_array_elements(items)v),'[]'));end if;
 else complete:=false;end if;
 return jsonb_build_object('id',job.id,'project_id',job.project_id,'kind',job.kind,'status',job.state,'attempts',job.attempts,
  'created_at',job.created_at,'result',result,'error',job.error,'root_digest',job.root_digest,'complete',complete,'next_cursor',next_cursor,
  'progress',jsonb_build_object('completed_pages',job.next_page,'source_pages',job.source_pages));
end $$;
create function public.lock_lifetime_collection_result_publication(p_fence jsonb,p_job_id uuid,p_root_digest text) returns double precision
language plpgsql security definer set search_path=public,auth as $$
declare remaining double precision; job public.user_lifetime_collection_job%rowtype;
begin
 -- One transaction: the account lock precedes generic project/profile reads,
 -- matching guest attachment's existing auth-user -> project/profile order.
 select * into job from public.user_lifetime_collection_job where id=p_job_id and user_id=auth.uid();
 if not found or job.project_id is distinct from p_fence->'identity'->>'project_id' then raise exception 'collection result owner mismatch' using errcode='42501';end if;
 if job.kind='BuildOutline' then perform 1 from auth.users where id=job.user_id for share;end if;
 remaining:=public.lock_lifetime_read_publication(p_fence);
 job:=public.lock_lifetime_collection_job(job.id);
 if job.root_digest is distinct from p_root_digest then raise exception 'collection result changed' using errcode='40001';end if;
 return remaining;
end $$;

create function public.set_lifetime_collection_job_retry(p_job_id uuid) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare job public.user_lifetime_collection_job%rowtype;
begin
 select * into job from public.user_lifetime_collection_job where id=p_job_id and user_id=auth.uid();
 if not found then raise exception 'collection job unavailable' using errcode='42501';end if;
 if job.kind='BuildOutline' then perform 1 from auth.users where id=job.user_id for share;end if;
 perform 1 from public.user_memoir_project where user_id=job.user_id and project_id=job.project_id for share;
 perform 1 from public.user_profile where user_id=job.user_id for share;
 if not found then perform pg_advisory_xact_lock_shared(hashtextextended('memoir-profile:'||job.user_id::text,0));end if;
 perform 1 from public.user_lifetime_conversation where user_id=job.user_id and project_id=job.project_id for share;
 perform 1 from public.user_lifetime_collection where user_id=job.user_id and project_id=job.project_id for share;
 if job.kind='BuildOutline' then
  perform 1 from public.story_entitlements where user_id=job.user_id for share;
 end if;
 select * into job from public.user_lifetime_collection_job where id=p_job_id for update;
 if job.state='FAILED' and job.error='BOUNDED_JOB_RETRY' then
  update public.user_lifetime_collection_job set state='QUEUED',attempts=0,error=null,token=null,lease_until=null where id=job.id;
 end if;
 -- Invalid source/privacy/payment authority rolls back the retry, too.
 perform public.lock_lifetime_collection_job(job.id);
 return public.read_lifetime_collection_job(job.id,null,8);
end $$;
revoke all on function public.set_lifetime_collection_job_retry(uuid) from public,anon;
grant execute on function public.set_lifetime_collection_job_retry(uuid) to authenticated;

create function public.read_lifetime_collection_job_scope(p_job_id uuid) returns jsonb
language sql security definer set search_path=public,auth as $$
 select jsonb_build_object('id',id,'project_id',project_id) from public.user_lifetime_collection_job where id=p_job_id and user_id=auth.uid();
$$;
create function public.release_lifetime_collection_job(p_job_id uuid,p_token uuid,p_error text default null) returns boolean
language plpgsql security definer set search_path=public,auth as $$
declare job public.user_lifetime_collection_job%rowtype;
begin
 if p_error is not null and p_error<>'BOUNDED_JOB_RETRY' then raise exception 'invalid collection error code';end if;
 job:=public.lock_lifetime_collection_job(p_job_id,p_token);
 update public.user_lifetime_collection_job set state=case when p_error is not null and attempts>=3 then 'FAILED' else 'QUEUED' end,
  token=null,lease_until=null,error=p_error,attempts=case when p_error is null then 0 else attempts end where id=job.id;
 return true;
end $$;
revoke all on function public.read_lifetime_collection_job_scope(uuid) from public,anon;
grant execute on function public.read_lifetime_collection_job_scope(uuid) to authenticated;
revoke all on function public.release_lifetime_collection_job(uuid,uuid,text) from public,anon,authenticated;
grant execute on function public.release_lifetime_collection_job(uuid,uuid,text) to service_role;

revoke all on function public.lock_lifetime_collection_job(uuid,uuid) from public,anon,authenticated,service_role;
revoke all on function public.read_lifetime_collection_selection(text,uuid,integer),public.set_lifetime_collection(text,bigint,jsonb,boolean),
 public.create_lifetime_collection_job(text,text,text,jsonb,bigint,text,boolean),public.read_lifetime_collection_job(uuid,uuid,integer),
 public.lock_lifetime_collection_job_publication(jsonb),public.lock_lifetime_collection_result_publication(jsonb,uuid,text) from public,anon;
grant execute on function public.read_lifetime_collection_selection(text,uuid,integer),public.set_lifetime_collection(text,bigint,jsonb,boolean),
 public.create_lifetime_collection_job(text,text,text,jsonb,bigint,text,boolean),public.read_lifetime_collection_job(uuid,uuid,integer),
 public.lock_lifetime_collection_job_publication(jsonb),public.lock_lifetime_collection_result_publication(jsonb,uuid,text) to authenticated;
revoke all on function public.pending_lifetime_collection_jobs(integer,boolean),public.claim_lifetime_collection_job(uuid,integer),
 public.read_lifetime_collection_job_page(uuid,uuid),public.commit_lifetime_collection_job_page(jsonb,jsonb) from public,anon,authenticated;
grant execute on function public.pending_lifetime_collection_jobs(integer,boolean),public.claim_lifetime_collection_job(uuid,integer),
 public.read_lifetime_collection_job_page(uuid,uuid),public.commit_lifetime_collection_job_page(jsonb,jsonb) to service_role;
commit;
