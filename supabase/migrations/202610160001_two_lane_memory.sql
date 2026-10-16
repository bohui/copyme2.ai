-- Issue 70, additive local schema only. The server flag remains OFF by default.
-- Reuse the unique timeline lane, source positions, outbox and page receipts.
begin;
-- A client JWT cannot activate the experiment by calling its RPC directly.
-- Only a separately approved database-owner rollout may change this row.
create table public.lifetime_two_lane_rollout (
 singleton boolean primary key default true check(singleton),
 enabled boolean not null default false
);
alter table public.lifetime_two_lane_rollout enable row level security;
revoke all on public.lifetime_two_lane_rollout from public,anon,authenticated,service_role;
insert into public.lifetime_two_lane_rollout default values;
alter table public.user_lifetime_place_journey add column derived_fence jsonb;
alter table public.user_lifetime_checkpoint add column lossless boolean not null default false;
create table public.user_lifetime_two_lane_source (
 user_id uuid not null,project_id text not null,source_id uuid not null,
 primary key(user_id,project_id,source_id),
 foreign key(user_id,project_id,source_id) references public.user_narrator_source(user_id,project_id,id) on delete cascade
);
create table public.user_lifetime_prepared_question (
 user_id uuid not null,project_id text not null,source_id uuid not null,source_version bigint not null,
 source_revision bigint not null,policy_epoch bigint not null,preference_revision bigint not null,
 execution_generation bigint not null,phase_revision bigint not null,snapshot_id uuid not null,
 page_digest text not null,questions jsonb not null,
 primary key(user_id,project_id,source_id),
 foreign key(user_id,project_id,source_id) references public.user_narrator_source(user_id,project_id,id) on delete cascade
);
alter table public.user_lifetime_two_lane_source enable row level security;
alter table public.user_lifetime_prepared_question enable row level security;
revoke all on public.user_lifetime_two_lane_source,public.user_lifetime_prepared_question from public,anon,authenticated;

create function public.accept_two_lane_interview_turn(p_project_id text,p_client_turn_id uuid,p_text text,
 p_kind text default 'narrator_chat',p_language text default 'en-AU',p_uploaded_photo_ids jsonb default '[]',p_photo_selection jsonb default null)
returns jsonb language plpgsql security definer set search_path=public,auth as $$
declare result jsonb; identity public.user_lifetime_conversation%rowtype;
begin
 perform 1 from public.lifetime_two_lane_rollout where singleton and enabled for share;
 if not found then raise exception 'two lane rollout is disabled' using errcode='55000';end if;
 select * into identity from public.user_lifetime_conversation where user_id=auth.uid() and project_id=p_project_id;
 if not found then raise exception 'canonical conversation required' using errcode='42501';end if;
 perform 1 from public.user_memoir_project where user_id=auth.uid() and project_id=p_project_id for update;
 -- A saved source is not a saved reply. Require reconciliation of an unfinished
 -- active turn; neither a disconnect nor a failed save permits a competing turn.
 if exists(select 1 from public.user_interview_turn t join public.user_narrator_source s
   on s.user_id=t.user_id and s.project_id=t.project_id and s.id=t.source_id and s.status='active'
   where t.user_id=auth.uid() and t.project_id=p_project_id and t.client_turn_id<>p_client_turn_id
   and not exists(select 1 from public.user_lifetime_reply r where r.user_id=t.user_id
     and r.conversation_id=identity.conversation_id and r.client_turn_id=t.client_turn_id)) then
   raise exception 'saved source has a pending reply; retry its original turn' using errcode='PT409';
 end if;
 result:=public.accept_user_interview_turn(p_project_id,p_client_turn_id,p_text,p_kind,p_language,p_uploaded_photo_ids,p_photo_selection);
 insert into public.user_lifetime_two_lane_source values(auth.uid(),p_project_id,(result->'source'->>'id')::uuid) on conflict do nothing;
 -- Intent is durable before any collector call. Existing receipt dispatch also
 -- schedules composition; this target only wakes the existing memory owner.
 insert into public.user_memoir_lane(user_id,project_id,skill,pending,target_source,target_event)
 select auth.uid(),p_project_id,'timeline',true,source_sequence,event_sequence from public.user_memoir_project
 where user_id=auth.uid() and project_id=p_project_id
 on conflict(user_id,project_id,skill) do update set pending=true,
   target_source=greatest(user_memoir_lane.target_source,excluded.target_source),
   target_event=greatest(user_memoir_lane.target_event,excluded.target_event),
   attempts=case when excluded.target_source>user_memoir_lane.target_source then 0 else user_memoir_lane.attempts end;
 return result;
end $$;
revoke all on function public.accept_two_lane_interview_turn(text,uuid,text,text,text,jsonb,jsonb) from public,anon;
grant execute on function public.accept_two_lane_interview_turn(text,uuid,text,text,text,jsonb,jsonb) to authenticated;

-- Bind additional hints to the same authoritative page and digest. A later
-- execution/phase revision changes that digest, rejecting already-running work.
alter function public.read_lifetime_memoir_lane_page(uuid,uuid) rename to read_lifetime_memoir_lane_page_before_two_lanes;
revoke all on function public.read_lifetime_memoir_lane_page_before_two_lanes(uuid,uuid) from public,anon,authenticated,service_role;
create function public.read_lifetime_memoir_lane_page(p_lane_id uuid,p_token uuid) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare page jsonb; descriptor jsonb;
begin
 page:=public.read_lifetime_memoir_lane_page_before_two_lanes(p_lane_id,p_token);
 if exists(select 1 from public.lifetime_two_lane_rollout where singleton and enabled)
   and exists(select 1 from public.user_lifetime_two_lane_source where user_id=(page->>'user_id')::uuid and project_id=page->>'project_id') then
   page:=page||jsonb_build_object('two_lane_maintenance_required',true);
 end if;
 if page->>'skill'='timeline' and exists(select 1 from public.lifetime_two_lane_rollout where singleton and enabled) and exists(select 1 from public.user_lifetime_two_lane_source m
   where m.user_id=(page->>'user_id')::uuid and m.project_id=page->>'project_id' and m.source_id=(page->'source'->>'id')::uuid) then
   select jsonb_build_object('schema_version',1,'task_version','two-lane-v1','execution_generation',c.execution_generation,
     'phase_revision',coalesce(p.revision,0),'work_mode',case when t.collector is null and exists(select 1 from public.user_agent_turn_lease a
       where a.user_id=c.user_id and a.expires_at>clock_timestamp()) then 'pending'
       when t.source_version=(page->'source'->>'version')::bigint
       and t.collector->'plan'->'work'->>'mode'='reply_only' then 'reply_only' else 'extract' end) into descriptor
   from public.user_lifetime_conversation c left join public.user_conversation_phase p on p.user_id=c.user_id and p.project_id=c.project_id
   left join public.user_interview_turn t on t.user_id=c.user_id and t.project_id=c.project_id and t.source_id=(page->'source'->>'id')::uuid
   where c.user_id=(page->>'user_id')::uuid and c.conversation_id=(page->>'conversation_id')::uuid;
   page:=(page-'input_digest'-'page_digest')||jsonb_build_object('two_lane',descriptor);
   page:=page||jsonb_build_object('input_digest',encode(sha256(convert_to((page-'token')::text,'UTF8')),'hex'));
   page:=page||jsonb_build_object('page_digest',encode(sha256(convert_to(page::text,'UTF8')),'hex'));
 end if;
 if page ? 'two_lane_maintenance_required' then
   page:=page-'input_digest'-'page_digest';
   page:=page||jsonb_build_object('input_digest',encode(sha256(convert_to((page-'token')::text,'UTF8')),'hex'));
   page:=page||jsonb_build_object('page_digest',encode(sha256(convert_to(page::text,'UTF8')),'hex'));
 end if;
 return page;
end $$;
revoke all on function public.read_lifetime_memoir_lane_page(uuid,uuid) from public,anon,authenticated;
grant execute on function public.read_lifetime_memoir_lane_page(uuid,uuid) to service_role;

create function public.read_lifetime_prepared_questions(p_conversation_id uuid) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare identity public.user_lifetime_conversation%rowtype; pins jsonb; result jsonb;
begin
 -- Reuse the existing content access/policy guard before selecting any bytes.
 pins:=public.read_lifetime_pinned(p_conversation_id);
 if not exists(select 1 from public.lifetime_two_lane_rollout where singleton and enabled) then return '[]'::jsonb;end if;
 select * into identity from public.user_lifetime_conversation where user_id=auth.uid() and conversation_id=p_conversation_id;
 select coalesce(jsonb_agg(item),'[]') into result from (
   select q||jsonb_build_object('id','bq-'||encode(sha256(convert_to(d.source_id::text||':'||d.source_version||':'||(q->>'question'),'UTF8')),'hex'),
     'source_id',d.source_id,'source_version',d.source_version,'creation_revision',d.source_revision,
     'snapshot_id',d.snapshot_id,'policy_epoch',d.policy_epoch,'task_version','two-lane-v1',
     'invalidation','source/policy/preference/phase/generation/recent coverage/delivered question') item
   from public.user_lifetime_prepared_question d join public.user_narrator_source s on s.user_id=d.user_id and s.project_id=d.project_id
     and s.id=d.source_id and s.version=d.source_version and s.status='active'
   join public.user_memoir_project p on p.user_id=d.user_id and p.project_id=d.project_id
   cross join lateral jsonb_array_elements(d.questions) q
   where d.user_id=auth.uid() and d.project_id=identity.project_id and d.policy_epoch=p.policy_epoch
     and d.preference_revision=identity.preference_revision and d.execution_generation=identity.execution_generation
     and d.phase_revision=(pins->'conversation_phase'->>'revision')::bigint
     and d.source_revision>=p.source_sequence-1
     and not exists(select 1 from public.user_interview_turn t where t.user_id=d.user_id and t.project_id=d.project_id
       and t.collector->'plan'->>'chosen_id'='bq-'||encode(sha256(convert_to(d.source_id::text||':'||d.source_version||':'||(q->>'question'),'UTF8')),'hex'))
   order by s.sequence desc,d.source_id,q->>'question' limit 3
 ) hints;
 return result;
end $$;
revoke all on function public.read_lifetime_prepared_questions(uuid) from public,anon;
grant execute on function public.read_lifetime_prepared_questions(uuid) to authenticated;

-- Same deterministic place validator as the existing authenticated path.
create function public.validate_two_lane_places(p_source_text text,p_journeys jsonb) returns void
language plpgsql set search_path='' as $$
declare journey jsonb;
begin
 if jsonb_typeof(p_journeys) is distinct from 'array' or jsonb_array_length(p_journeys)>8
   or octet_length(p_journeys::text)>8192 then raise exception 'bounded place journeys required' using errcode='22023'; end if;
 for journey in select * from jsonb_array_elements(p_journeys) loop
   if jsonb_typeof(journey) is distinct from 'object'
     or exists(select 1 from jsonb_object_keys(journey) k where k not in ('schema_version','place','hierarchy','granularity','duration_ms','latitude','longitude'))
     or journey->'schema_version' is distinct from '1'::jsonb
     or jsonb_typeof(journey->'place') is distinct from 'string'
     or length(journey->>'place') not between 1 and 120
     or strpos(lower(p_source_text),lower(journey->>'place'))=0
     or jsonb_typeof(journey->'hierarchy') is distinct from 'array'
     or jsonb_array_length(journey->'hierarchy') not between 2 and 6
     or journey->'hierarchy'->>0 is distinct from 'Earth'
     or journey->'hierarchy'->>-1 is distinct from journey->>'place'
     or exists(select 1 from jsonb_array_elements(journey->'hierarchy') label
       where jsonb_typeof(label) is distinct from 'string' or length(label#>>'{}') not between 1 and 120)
     or coalesce(journey->>'granularity','') not in ('country','region','city','suburb')
     then raise exception 'grounded coarse place journey required' using errcode='22023'; end if;
   if (journey ? 'latitude') is distinct from (journey ? 'longitude')
     or (journey ? 'latitude' and (jsonb_typeof(journey->'latitude') is distinct from 'number'
       or jsonb_typeof(journey->'longitude') is distinct from 'number'
       or (journey->>'latitude')::numeric not between -90 and 90
       or (journey->>'longitude')::numeric not between -180 and 180))
     then raise exception 'valid public place centre required' using errcode='22023'; end if;
 end loop;
end $$;
revoke all on function public.validate_two_lane_places(text,jsonb) from public,anon,authenticated,service_role;

alter function public.commit_lifetime_memoir_lane_page(uuid,uuid,bigint,jsonb,text) rename to commit_lifetime_memoir_lane_page_before_two_lanes;
revoke all on function public.commit_lifetime_memoir_lane_page_before_two_lanes(uuid,uuid,bigint,jsonb,text) from public,anon,authenticated,service_role;
create function public.commit_lifetime_memoir_lane_page(p_lane_id uuid,p_token uuid,p_page_number bigint,p_result jsonb,p_page_digest text)
returns jsonb language plpgsql security definer set search_path=public,auth as $$
declare snap public.user_lifetime_lane_snapshot%rowtype; page jsonb; result jsonb; q jsonb;
begin
 snap:=public.lock_lifetime_memoir_lane(p_lane_id,p_token);
 -- The canonical receipt verifies identical retries before any repeated effect.
 if p_page_number<snap.page_number then
   return public.commit_lifetime_memoir_lane_page_before_two_lanes(p_lane_id,p_token,p_page_number,p_result,p_page_digest);
 end if;
 page:=public.read_lifetime_memoir_lane_page(p_lane_id,p_token);
 if page ? 'two_lane' then
   if p_page_digest is distinct from page->>'page_digest' then raise exception 'stale derived page' using errcode='PT409';end if;
   if jsonb_typeof(p_result->'prepared_questions') is distinct from 'array' or jsonb_array_length(p_result->'prepared_questions')>5
     or octet_length((p_result->'prepared_questions')::text)>6000
     or exists(select 1 from jsonb_object_keys(p_result) k where k not in ('events','place_journeys','prepared_questions')) then
     raise exception 'bounded derived hints required' using errcode='22023';end if;
   if (select count(*) from jsonb_array_elements(p_result->'prepared_questions')) is distinct from
     (select count(distinct lower(btrim(candidate.value->>'question'))) from jsonb_array_elements(p_result->'prepared_questions') candidate(value)) then
     raise exception 'prepared questions must be distinct' using errcode='22023';end if;
   perform public.validate_two_lane_places(page->'source'->>'text',p_result->'place_journeys');
   for q in select * from jsonb_array_elements(p_result->'prepared_questions') loop
     if jsonb_typeof(q)<>'object' or exists(select 1 from jsonb_object_keys(q) k where k not in ('question','topic','quote'))
       or jsonb_typeof(q->'question') is distinct from 'string' or length(q->>'question') not between 1 and 800
       or jsonb_typeof(q->'topic') is distinct from 'string' or length(q->>'topic') not between 1 and 120
       or jsonb_typeof(q->'quote') is distinct from 'string' or length(q->>'quote') not between 1 and 500
       or strpos(page->'source'->>'text',q->>'quote')=0
       or length(regexp_replace(q->>'question','[^?？]','','g'))>1 then raise exception 'grounded question hints required' using errcode='22023';end if;
   end loop;
   if page->'two_lane'->>'work_mode'='reply_only' and (jsonb_array_length(p_result->'events')>0
     or jsonb_array_length(p_result->'place_journeys')>0 or jsonb_array_length(p_result->'prepared_questions')>0) then
     raise exception 'reply only work cannot create derived facts' using errcode='22023';end if;
 end if;
 result:=public.commit_lifetime_memoir_lane_page_before_two_lanes(p_lane_id,p_token,p_page_number,p_result,p_page_digest);
 if page ? 'two_lane' and result->>'status'='page_saved' then
   -- Empty or failed B never erases a previously valid activated workspace.
   if jsonb_array_length(p_result->'place_journeys')>0 then
     insert into public.user_lifetime_place_journey(user_id,project_id,source_id,source_version,journeys,derived_fence) values(snap.user_id,snap.project_id,(page->'source'->>'id')::uuid,
       (page->'source'->>'version')::bigint,p_result->'place_journeys',jsonb_build_object('policy_epoch',snap.policy_epoch,
         'preference_revision',snap.preference_revision,'execution_generation',(page->'two_lane'->>'execution_generation')::bigint,'privacy_digest',snap.privacy_digest))
     on conflict(user_id,project_id,source_id) do update set source_version=excluded.source_version,derived_fence=excluded.derived_fence,
       journeys=(select coalesce(jsonb_agg(distinct j),'[]') from jsonb_array_elements(
         case when user_lifetime_place_journey.source_version=excluded.source_version then user_lifetime_place_journey.journeys else '[]' end||excluded.journeys) j);
   end if;
   if page->'two_lane'->>'strategy_mode' is null then
   insert into public.user_lifetime_prepared_question values(snap.user_id,snap.project_id,(page->'source'->>'id')::uuid,
     (page->'source'->>'version')::bigint,snap.source_high_water,snap.policy_epoch,snap.preference_revision,
     (page->'two_lane'->>'execution_generation')::bigint,(page->'two_lane'->>'phase_revision')::bigint,snap.id,p_page_digest,p_result->'prepared_questions')
   on conflict(user_id,project_id,source_id) do update set source_version=excluded.source_version,source_revision=excluded.source_revision,
     policy_epoch=excluded.policy_epoch,preference_revision=excluded.preference_revision,execution_generation=excluded.execution_generation,
     phase_revision=excluded.phase_revision,snapshot_id=excluded.snapshot_id,page_digest=excluded.page_digest,questions=excluded.questions;
   end if;
 end if;
 return result;
end $$;
revoke all on function public.commit_lifetime_memoir_lane_page(uuid,uuid,bigint,jsonb,text) from public,anon,authenticated;
grant execute on function public.commit_lifetime_memoir_lane_page(uuid,uuid,bigint,jsonb,text) to service_role;

-- Dialogue checkpoint maintenance reuses canonical proof/checkpoint tables.
-- Its owner is the existing timeline token, never the interactive turn lease.
-- These cursors have no relationship to composer summary_source/summary_offset.
create function public.advance_two_lane_checkpoint(p_lane_id uuid,p_token uuid,p_steps integer default 1,
 p_model text default 'gpt-5.6-luna-pooled') returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare snap public.user_lifetime_lane_snapshot%rowtype; identity public.user_lifetime_conversation%rowtype;
 project public.user_memoir_project%rowtype; saved public.user_lifetime_compaction%rowtype;
 predecessor uuid; start_sequence bigint:=0; end_sequence bigint; owner uuid; pins jsonb; checkpoint_fence jsonb;
 previous_owner text; candidate uuid; evidence jsonb:='[]'; manifest_sources jsonb:='[]'; item record;
 processed integer; fingerprint text; count_items bigint; chain text; last_seq bigint; last_start integer;
begin
 if p_steps is null or p_steps not between 1 and 4 or p_model not in
   ('gpt-5.6-luna-pooled','gpt-5.6-luna-memoir-low','memoir-luna-low','legal2ai-luna-low','synthetic-byte-bpe') then raise exception 'bounded checkpoint configuration required';end if;
 snap:=public.lock_lifetime_memoir_lane(p_lane_id,p_token);
 owner:=snap.user_id;
 if not exists(select 1 from public.user_memoir_lane where id=p_lane_id and skill='timeline') then
   raise exception 'timeline checkpoint owner required' using errcode='42501';end if;
 if not exists(select 1 from public.lifetime_two_lane_rollout where singleton and enabled)
   or not exists(select 1 from public.user_lifetime_two_lane_source where user_id=owner and project_id=snap.project_id) then
   return jsonb_build_object('complete',true,'coverage_end',0);
 end if;
 select * into project from public.user_memoir_project where user_id=owner and project_id=snap.project_id;
 select * into identity from public.user_lifetime_conversation where user_id=owner and conversation_id=snap.conversation_id;
 previous_owner:=current_setting('request.jwt.claim.sub',true);
 perform set_config('request.jwt.claim.sub',owner::text,true);
 pins:=public.read_lifetime_pinned(snap.conversation_id);
 if pins->'privacy_complete' is distinct from 'true'::jsonb then raise exception 'complete current privacy required' using errcode='PT409';end if;
 predecessor:=identity.checkpoint_id;
 select coverage_end into start_sequence from public.user_lifetime_checkpoint where id=predecessor and published and lossless;
 start_sequence:=coalesce(start_sequence,0);
 -- Never cover an in-flight current source. The next A consumes this accepted
 -- checkpoint plus every remaining canonical position, including tombstones.
 end_sequence:=snap.source_high_water-1;
 if end_sequence<=start_sequence then
   perform set_config('request.jwt.claim.sub',coalesce(previous_owner,''),true);
   return jsonb_build_object('complete',true,'coverage_end',start_sequence);
 end if;
 if not exists(select 1 from public.user_lifetime_source_inventory where user_id=owner and project_id=snap.project_id
   and record_count=project.source_sequence and max_sequence=project.source_sequence) then
   raise exception 'complete canonical source inventory required' using errcode='PT409';end if;
 checkpoint_fence:=jsonb_build_object('schema_version',1,'identity',jsonb_build_object('schema_version',1,'owner_id',owner,
   'conversation_id',snap.conversation_id,'project_id',snap.project_id,'product','memoir'),
   'policy_epoch',project.policy_epoch,'source_revision',project.source_sequence,'execution_generation',identity.execution_generation,
   'phase_revision',(pins->'conversation_phase'->>'revision')::bigint,'preference_revision',identity.preference_revision,'lease_token',p_token);
 select c.* into saved from public.user_lifetime_compaction c where c.user_id=owner and c.conversation_id=snap.conversation_id
   and c.fence-'lease_token'=checkpoint_fence-'lease_token'
   and c.predecessor_id is not distinct from predecessor and c.starting_after=start_sequence and c.through_sequence=end_sequence
   and c.pinned=pins order by id limit 1;
 if not found then
   insert into public.user_lifetime_compaction(user_id,conversation_id,fence,predecessor_id,starting_after,through_sequence,last_sequence,pinned)
     values(owner,snap.conversation_id,checkpoint_fence,predecessor,start_sequence,end_sequence,start_sequence,pins) returning * into saved;
 end if;
 update public.user_lifetime_compaction set fence=checkpoint_fence where id=saved.id returning * into saved;
 for iteration in 1..p_steps loop
   exit when saved.complete;
  processed:=0;
  chain:=saved.digest;count_items:=saved.item_count;last_seq:=saved.last_sequence;last_start:=saved.last_offset;
  for item in
    select pos.sequence,pos.source_id,pos.version,chunk_start,
      case when src.version=pos.version and src.status='active' then least(chunk_start+2000,length(src.text)) else 0 end as chunk_end,
      case when src.id is null then 'withdrawn' when src.version<>pos.version then 'superseded' else src.status end as status,
      case when src.version=pos.version and src.status='active' then substring(src.text from chunk_start+1 for 2000) else null end as content
    from public.user_lifetime_source_position pos left join public.user_narrator_source src
      on src.user_id=pos.user_id and src.project_id=pos.project_id and src.id=pos.source_id
    cross join lateral generate_series(0,case when src.version=pos.version and src.status='active' then greatest(length(src.text)-1,0) else 0 end,2000) chunk_start
    where pos.user_id=owner and pos.project_id=snap.project_id and pos.sequence>saved.starting_after and pos.sequence<=saved.through_sequence
      and (pos.sequence>saved.last_sequence or (pos.sequence=saved.last_sequence and chunk_start>saved.last_offset))
    order by pos.sequence,chunk_start limit 32
  loop
    fingerprint:=case when item.content is not null then encode(sha256(convert_to(item.content,'UTF8')),'hex') else null end;
    insert into public.user_lifetime_covered_evidence(maintenance_id,sequence,source_id,version,char_start,char_end,status,content_sha256)
      values(saved.id,item.sequence,item.source_id,item.version,item.chunk_start,item.chunk_end,item.status,fingerprint);
    chain:=encode(sha256(convert_to(chain||':'||item.sequence||':'||item.source_id||':'||item.version||':'||item.chunk_start||':'||item.chunk_end||':'||item.status||':'||coalesce(fingerprint,''),'UTF8')),'hex');
    processed:=processed+1;count_items:=count_items+1;last_seq:=item.sequence;last_start:=item.chunk_start;
  end loop;
  update public.user_lifetime_compaction set revision=revision+1,item_count=count_items,digest=chain,last_sequence=last_seq,last_offset=last_start,
    complete=processed<32 where id=saved.id returning * into saved;

 end loop;
 if saved.complete then
   -- Publish only a complete lossless replacement. A raw inventory/hash is not
   -- a summary. Larger intervals retain mandatory raw context and fail closed
   -- on A budget overflow until an accepted bounded summary is available.
   if (select count(*) from public.user_lifetime_covered_evidence where maintenance_id=saved.id and status='active')
       + coalesce((select jsonb_array_length(c.evidence) from public.user_lifetime_checkpoint c where c.id=predecessor and c.lossless),0)>16 then
     perform set_config('request.jwt.claim.sub',coalesce(previous_owner,''),true);
     return jsonb_build_object('complete',true,'coverage_end',start_sequence,'summary_pending',true,'checkpoint_published',false);
   end if;
   select coalesce(c.evidence,'[]'),coalesce(c.manifest->'sources','[]') into evidence,manifest_sources
     from public.user_lifetime_checkpoint c where c.id=predecessor and c.lossless;
   evidence:=coalesce(evidence,'[]');manifest_sources:=coalesce(manifest_sources,'[]');
   -- The project lock and timeline admission remain held through predecessor
   -- CAS and every derived write. All exact windows/tombstones were scanned.
   if identity.checkpoint_id is distinct from saved.predecessor_id or
     saved.item_count<>(select count(*) from public.user_lifetime_covered_evidence where maintenance_id=saved.id) then
     raise exception 'checkpoint predecessor or coverage changed' using errcode='PT409';end if;
   for item in select c.*,s.language,substring(s.text from c.char_start+1 for c.char_end-c.char_start) original
     from public.user_lifetime_covered_evidence c join public.user_narrator_source s
       on s.user_id=owner and s.project_id=snap.project_id and s.id=c.source_id and s.version=c.version and s.status='active'
     where c.maintenance_id=saved.id and c.status='active' order by c.sequence,c.char_start loop
     evidence:=evidence||jsonb_build_array(jsonb_build_object('schema_version',1,'source_id',item.source_id,'version',item.version,
       'char_start',item.char_start,'char_end',item.char_end,'original',item.original,'language',item.language,
       'role','storyteller','assertion','asserted','allowed_use',jsonb_build_array('conversation'),'policy_epoch',project.policy_epoch));
     if not manifest_sources @> jsonb_build_array(jsonb_build_object('schema_version',1,'source_id',item.source_id,'version',item.version)) then
       manifest_sources:=manifest_sources||jsonb_build_array(jsonb_build_object('schema_version',1,'source_id',item.source_id,'version',item.version));
     end if;
   end loop;
   insert into public.user_lifetime_checkpoint(user_id,conversation_id,predecessor_id,fence,coverage_end,model,prompt_version,pinned,
     manifest,evidence,published,coverage_proof_id,lossless) values(owner,snap.conversation_id,predecessor,checkpoint_fence,end_sequence,p_model,'lifetime-v1',pins,
       jsonb_build_object('schema_version',1,'identity',checkpoint_fence->'identity','policy_epoch',project.policy_epoch,
         'source_revision',project.source_sequence,'sources',manifest_sources),evidence,true,saved.id,true) returning id into candidate;
   update public.user_lifetime_conversation set checkpoint_id=candidate where user_id=owner and conversation_id=snap.conversation_id
     and checkpoint_id is not distinct from predecessor;
   if not found then raise exception 'checkpoint CAS failed' using errcode='PT409';end if;
 end if;
 perform set_config('request.jwt.claim.sub',coalesce(previous_owner,''),true);
 return jsonb_build_object('complete',saved.complete,'coverage_end',case when saved.complete then end_sequence else start_sequence end,
   'proof_revision',saved.revision);
end $$;
revoke all on function public.advance_two_lane_checkpoint(uuid,uuid,integer,text) from public,anon,authenticated;
grant execute on function public.advance_two_lane_checkpoint(uuid,uuid,integer,text) to service_role;
create or replace function public.persist_lifetime_place_journeys(p_fence jsonb,p_source_id uuid,p_source_version bigint,p_journeys jsonb)
returns void language plpgsql security definer set search_path='' as $$
declare owner uuid:=auth.uid(); project text:=p_fence->'identity'->>'project_id';
 source public.user_narrator_source%rowtype; journey jsonb;
begin
 perform public.lock_lifetime_publication(p_fence);
 select * into source from public.user_narrator_source
   where user_id=owner and project_id=project and id=p_source_id and version=p_source_version and status='active';
 if not found then raise exception 'current narrator source required' using errcode='PT409'; end if;
 if jsonb_typeof(p_journeys) is distinct from 'array' or jsonb_array_length(p_journeys)>8
   or octet_length(p_journeys::text)>8192 then raise exception 'bounded place journeys required' using errcode='22023'; end if;
 for journey in select * from jsonb_array_elements(p_journeys) loop
   if jsonb_typeof(journey) is distinct from 'object'
     or exists(select 1 from jsonb_object_keys(journey) k where k not in ('schema_version','place','hierarchy','granularity','duration_ms','latitude','longitude'))
     or journey->'schema_version' is distinct from '1'::jsonb
     or jsonb_typeof(journey->'place') is distinct from 'string'
     or length(journey->>'place') not between 1 and 120
     or strpos(lower(source.text),lower(journey->>'place'))=0
     or jsonb_typeof(journey->'hierarchy') is distinct from 'array'
     or jsonb_array_length(journey->'hierarchy') not between 2 and 6
     or journey->'hierarchy'->>0 is distinct from 'Earth'
     or journey->'hierarchy'->>-1 is distinct from journey->>'place'
     or exists(select 1 from jsonb_array_elements(journey->'hierarchy') label
       where jsonb_typeof(label) is distinct from 'string' or length(label#>>'{}') not between 1 and 120)
     or coalesce(journey->>'granularity','') not in ('country','region','city','suburb')
     then raise exception 'grounded coarse place journey required' using errcode='22023'; end if;
   if (journey ? 'latitude') is distinct from (journey ? 'longitude')
     or (journey ? 'latitude' and (jsonb_typeof(journey->'latitude') is distinct from 'number'
       or jsonb_typeof(journey->'longitude') is distinct from 'number'
       or (journey->>'latitude')::numeric not between -90 and 90
       or (journey->>'longitude')::numeric not between -180 and 180))
     then raise exception 'valid public place centre required' using errcode='22023'; end if;
 end loop;
 insert into public.user_lifetime_place_journey(user_id,project_id,source_id,source_version,journeys) values(owner,project,p_source_id,p_source_version,p_journeys)
 on conflict(user_id,project_id,source_id) do update set source_version=excluded.source_version,journeys=excluded.journeys,derived_fence=null;
end $$;

create or replace function public.read_lifetime_place_journeys(p_project_id text,p_source_id uuid default null)
returns jsonb language plpgsql security definer set search_path='' as $$
declare owner uuid:=auth.uid(); result jsonb; pins jsonb; privacy_hash text;
begin
 if not exists(select 1 from public.user_lifetime_conversation where user_id=owner and project_id=p_project_id)
   then raise exception 'canonical conversation required'; end if;
 perform 1 from public.user_memoir_project where user_id=owner and project_id=p_project_id for share;
 pins:=public.read_lifetime_pinned((select conversation_id from public.user_lifetime_conversation where user_id=owner and project_id=p_project_id));
 privacy_hash:=encode(sha256(convert_to(jsonb_build_object('excluded_topics',pins->'excluded_topics',
   'paused_topics',pins->'paused_topics','privacy_complete',pins->'privacy_complete')::text,'UTF8')),'hex');
 select coalesce(jsonb_agg(journey||jsonb_build_object('source_sequence',sequence,
   'status','active','revision',version,'updated_at',created_at) order by sequence,ordinal),'[]') into result
 from (
   select distinct on (journey->'hierarchy',journey->>'granularity') journey,s.sequence,s.version,s.created_at,ordinal
   from public.user_lifetime_place_journey p join public.user_narrator_source s
     on s.user_id=p.user_id and s.project_id=p.project_id and s.id=p.source_id
       and s.version=p.source_version and s.status='active'
   cross join lateral jsonb_array_elements(p.journeys) with ordinality as items(journey,ordinal)
   where p.user_id=owner and p.project_id=p_project_id
     and (p.derived_fence is null or exists(select 1 from public.user_lifetime_conversation c join public.user_memoir_project m
       on m.user_id=c.user_id and m.project_id=c.project_id where c.user_id=p.user_id and c.project_id=p.project_id
       and p.derived_fence->>'policy_epoch'=m.policy_epoch::text
       and p.derived_fence->>'privacy_digest'=privacy_hash
       and p.derived_fence->>'execution_generation'=c.execution_generation::text)) and (p_source_id is null or p.source_id=p_source_id)
   order by journey->'hierarchy',journey->>'granularity',s.sequence desc,ordinal
   limit 1000
 ) places;
 return result;
end $$;


create function public.read_lifetime_two_lane_reply(p_conversation_id uuid,p_client_turn_id uuid) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare result jsonb; reply uuid;
begin
 result:=public.read_lifetime_reply(p_conversation_id,p_client_turn_id);
 if result is null then return null;end if;
 select memory_id into reply from public.user_lifetime_reply where user_id=auth.uid()
   and conversation_id=p_conversation_id and client_turn_id=p_client_turn_id;
 return result||jsonb_build_object('reply_id',reply);
end $$;
revoke all on function public.read_lifetime_two_lane_reply(uuid,uuid) from public,anon;
grant execute on function public.read_lifetime_two_lane_reply(uuid,uuid) to authenticated;
notify pgrst,'reload schema';
commit;

