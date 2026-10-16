-- Accepted selective summaries reuse the canonical B owner and compaction proof.
begin;
alter table public.user_lifetime_checkpoint add column memory_summary jsonb;
alter table public.user_lifetime_compaction add column summary_required boolean not null default false,
 add column summary_initialized boolean not null default false,add column summary_data jsonb not null default '{"items":[]}',
 add column summary_sequence bigint not null default 0,add column summary_offset integer not null default -1,
 add column summary_revision bigint not null default 0,add column summary_windows bigint not null default 0,
 add column summary_complete boolean not null default false,add column summary_model text not null default 'gpt-5.6-luna-pooled';
create table public.user_lifetime_summary_receipt (
 maintenance_id uuid not null references public.user_lifetime_compaction(id) on delete cascade,
 revision bigint not null,page_digest text not null,result_digest text not null,
 primary key(maintenance_id,revision)
);
alter table public.user_lifetime_summary_receipt enable row level security;
revoke all on public.user_lifetime_summary_receipt from public,anon,authenticated;

alter function public.read_lifetime_checkpoint(uuid,bigint,text,text) rename to read_lifetime_checkpoint_before_semantic;
revoke all on function public.read_lifetime_checkpoint_before_semantic(uuid,bigint,text,text) from public,anon,authenticated,service_role;
create function public.read_lifetime_checkpoint(p_conversation_id uuid,p_policy_epoch bigint,p_model text,p_prompt_version text)
returns jsonb language plpgsql security definer set search_path=public,auth as $$
declare result jsonb; summary jsonb;
begin
 result:=public.read_lifetime_checkpoint_before_semantic(p_conversation_id,p_policy_epoch,p_model,p_prompt_version);
 if result is null then return null;end if;
 select c.memory_summary into summary from public.user_lifetime_checkpoint c where c.user_id=auth.uid() and c.id=(result->>'checkpoint_id')::uuid;
 if summary is not null then
   if not exists(select 1 from public.user_lifetime_compaction p where p.user_id=auth.uid()
     and p.id=(summary->>'maintenance_id')::uuid and p.complete and p.summary_complete
     and p.digest=summary->>'coverage_digest' and p.through_sequence=(result->>'coverage_end')::bigint)
     or exists(select 1 from jsonb_array_elements(summary->'items') i cross join lateral jsonb_array_elements(i->'source_refs') r
       where not exists(select 1 from public.user_narrator_source s join public.user_lifetime_conversation l
         on l.user_id=s.user_id and l.project_id=s.project_id and l.conversation_id=p_conversation_id
         where s.user_id=auth.uid() and s.id=(r->>'source_id')::uuid and s.version=(r->>'version')::bigint and s.status='active')) then return null;end if;
   result:=result||jsonb_build_object('memory_summary',summary);
 end if;
 return result;
end $$;
create or replace function public.read_lifetime_two_lane_checkpoint(p_conversation_id uuid,p_policy_epoch bigint,p_model text,p_prompt_version text)
returns jsonb language plpgsql security definer set search_path=public,auth as $$
declare result jsonb;
begin
 result:=public.read_lifetime_checkpoint(p_conversation_id,p_policy_epoch,p_model,p_prompt_version);
 if result is not null and not exists(select 1 from public.user_lifetime_checkpoint c where c.user_id=auth.uid()
   and c.id=(result->>'checkpoint_id')::uuid and (c.lossless or c.memory_summary is not null)) then return null;end if;
 return result;
end $$;
revoke all on function public.read_lifetime_checkpoint(uuid,bigint,text,text),public.read_lifetime_two_lane_checkpoint(uuid,bigint,text,text) from public,anon;
grant execute on function public.read_lifetime_checkpoint(uuid,bigint,text,text),public.read_lifetime_two_lane_checkpoint(uuid,bigint,text,text) to authenticated;

create or replace function public.advance_two_lane_checkpoint(p_lane_id uuid,p_token uuid,p_steps integer default 1,
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
 select coverage_end into start_sequence from public.user_lifetime_checkpoint where id=predecessor and published and (lossless or memory_summary is not null);
 start_sequence:=coalesce(start_sequence,0);
 -- Never cover an in-flight current source. The next A consumes this accepted
 -- checkpoint plus every remaining canonical position, including tombstones.
 end_sequence:=snap.source_high_water-1;
 -- A newer canonical frontier belongs to a newer snapshot. Finish this old
 -- quantum without replacing it with a lower checkpoint, even across rollback.
 if exists(select 1 from public.user_lifetime_checkpoint c where c.id=predecessor and c.published and c.coverage_end>end_sequence) then
   perform set_config('request.jwt.claim.sub',coalesce(previous_owner,''),true);
   return jsonb_build_object('complete',true,'coverage_end',(select c.coverage_end from public.user_lifetime_checkpoint c where c.id=predecessor));
 end if;
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
   if exists(select 1 from public.user_lifetime_checkpoint c where c.id=predecessor and c.memory_summary is not null)
     or (select coalesce(sum(octet_length(substring(s.text from e.char_start+1 for e.char_end-e.char_start))),0)
       from public.user_lifetime_covered_evidence e join public.user_narrator_source s on s.user_id=owner and s.project_id=snap.project_id
         and s.id=e.source_id and s.version=e.version where e.maintenance_id=saved.id and e.status='active')
       +coalesce((select octet_length(c.evidence::text) from public.user_lifetime_checkpoint c where c.id=predecessor),0)>12000
     or (select count(*) from public.user_lifetime_covered_evidence where maintenance_id=saved.id and status='active')
       + coalesce((select jsonb_array_length(c.evidence) from public.user_lifetime_checkpoint c where c.id=predecessor and c.lossless),0)>16 then
     update public.user_lifetime_compaction set summary_required=true,summary_model=p_model where id=saved.id;
     perform set_config('request.jwt.claim.sub',coalesce(previous_owner,''),true);
     return jsonb_build_object('complete',true,'coverage_end',start_sequence,'summary_pending',true,'checkpoint_published',false,'maintenance_id',saved.id);
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

-- Publication runs under the same project/lane owner after every original
-- window has a durable accepted summary receipt (including explicit no-ops).
create function public.publish_lifetime_semantic_checkpoint(p_lane_id uuid,p_token uuid,p_maintenance_id uuid)
returns void language plpgsql security definer set search_path=public,auth as $$
declare snap public.user_lifetime_lane_snapshot%rowtype; proof public.user_lifetime_compaction%rowtype;
 identity public.user_lifetime_conversation%rowtype; project public.user_memoir_project%rowtype; head public.user_lifetime_checkpoint%rowtype;
 manifest jsonb; data jsonb; candidate uuid; fence jsonb; page jsonb;
begin
 snap:=public.lock_lifetime_memoir_lane(p_lane_id,p_token);
 page:=public.read_lifetime_memoir_lane_page_before_semantic(p_lane_id,p_token);
 select * into proof from public.user_lifetime_compaction where id=p_maintenance_id and user_id=snap.user_id and conversation_id=snap.conversation_id for update;
 select * into identity from public.user_lifetime_conversation where user_id=snap.user_id and conversation_id=snap.conversation_id;
 select * into project from public.user_memoir_project where user_id=snap.user_id and project_id=snap.project_id;
 if not found or not proof.complete or not proof.summary_complete or not proof.summary_required
   or proof.predecessor_id is distinct from identity.checkpoint_id or proof.pinned-'active_question'-'known_continuity'-'known_continuity_complete' is distinct from (page->'preferences')-'active_question'-'known_continuity'-'known_continuity_complete'
   or proof.fence->>'policy_epoch' is distinct from project.policy_epoch::text
   or proof.fence->>'execution_generation' is distinct from identity.execution_generation::text
   or proof.through_sequence<>snap.source_high_water-1
   or exists(select 1 from public.user_lifetime_checkpoint c where c.id=identity.checkpoint_id and c.coverage_end>proof.through_sequence) then raise exception 'stale semantic checkpoint' using errcode='PT409';end if;
 select * into head from public.user_lifetime_checkpoint where id=proof.predecessor_id;
 if proof.summary_revision<>(select count(*) from public.user_lifetime_summary_receipt r where r.maintenance_id=proof.id)
   or proof.summary_windows<>proof.summary_revision+coalesce((head.memory_summary->>'processed_windows')::bigint,0) then
   raise exception 'incomplete accepted summary receipts' using errcode='PT409';end if;
 select coalesce(jsonb_agg(distinct jsonb_build_object('schema_version',1,'source_id',r->>'source_id','version',(r->>'version')::bigint)),'[]') into manifest
   from jsonb_array_elements(proof.summary_data->'items') i cross join lateral jsonb_array_elements(i->'source_refs') r;
 data:=jsonb_build_object('schema_version',1,'kind','selective_derived_context','maintenance_id',proof.id,
   'coverage_digest',proof.digest,'processed_windows',proof.summary_windows,'processed_through',proof.through_sequence,'items',proof.summary_data->'items');
 fence:=proof.fence||jsonb_build_object('source_revision',project.source_sequence,'lease_token',p_token);
 insert into public.user_lifetime_checkpoint(user_id,conversation_id,predecessor_id,fence,coverage_end,model,prompt_version,pinned,
   manifest,evidence,published,coverage_proof_id,lossless,memory_summary)
 values(snap.user_id,snap.conversation_id,proof.predecessor_id,fence,proof.through_sequence,
   proof.summary_model,'lifetime-v1',page->'preferences',
   jsonb_build_object('schema_version',1,'identity',fence->'identity','policy_epoch',project.policy_epoch,'source_revision',project.source_sequence,'sources',manifest),
   '[]',true,proof.id,false,data) returning id into candidate;
 update public.user_lifetime_conversation set checkpoint_id=candidate where user_id=snap.user_id and conversation_id=snap.conversation_id
   and checkpoint_id is not distinct from proof.predecessor_id;
 if not found then raise exception 'semantic checkpoint CAS failed' using errcode='PT409';end if;
end $$;
revoke all on function public.publish_lifetime_semantic_checkpoint(uuid,uuid,uuid) from public,anon,authenticated,service_role;

alter function public.read_lifetime_memoir_lane_page(uuid,uuid) rename to read_lifetime_memoir_lane_page_before_semantic;
revoke all on function public.read_lifetime_memoir_lane_page_before_semantic(uuid,uuid) from public,anon,authenticated,service_role;
create function public.read_lifetime_memoir_lane_page(p_lane_id uuid,p_token uuid) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare page jsonb; snap public.user_lifetime_lane_snapshot%rowtype; proof public.user_lifetime_compaction%rowtype;
 prior public.user_lifetime_checkpoint%rowtype; identity public.user_lifetime_conversation%rowtype; next_item record; source jsonb; work text;
begin
 page:=public.read_lifetime_memoir_lane_page_before_semantic(p_lane_id,p_token);
 if page->>'skill'<>'timeline' or page->'complete' is distinct from 'true'::jsonb or not(page ? 'two_lane_maintenance_required') then return page;end if;
 snap:=public.lock_lifetime_memoir_lane(p_lane_id,p_token);
 select * into identity from public.user_lifetime_conversation where user_id=snap.user_id and conversation_id=snap.conversation_id;
 select * into proof from public.user_lifetime_compaction p where p.user_id=snap.user_id and p.conversation_id=snap.conversation_id
   and p.complete and p.summary_required and p.predecessor_id is not distinct from identity.checkpoint_id
   and p.through_sequence=snap.source_high_water-1
   and p.through_sequence>=coalesce((select c.coverage_end from public.user_lifetime_checkpoint c where c.id=identity.checkpoint_id),0)
   and p.pinned-'active_question'-'known_continuity'-'known_continuity_complete'
     =(page->'preferences')-'active_question'-'known_continuity'-'known_continuity_complete'
   and p.fence->>'policy_epoch'=page->>'policy_epoch' and p.fence->>'execution_generation'=identity.execution_generation::text
   order by p.summary_windows desc,p.id limit 1 for update;
 if not found then return page;end if;
 if not proof.summary_initialized then
   select * into prior from public.user_lifetime_checkpoint where id=proof.predecessor_id;
   update public.user_lifetime_compaction set summary_initialized=true,
     summary_data=case when prior.memory_summary is not null then jsonb_build_object('items',prior.memory_summary->'items') else '{"items":[]}' end,
     summary_sequence=case when prior.memory_summary is not null then prior.coverage_end else 0 end,
     summary_offset=case when prior.memory_summary is not null then 2147483647 else -1 end,
     summary_windows=case when prior.memory_summary is not null then (prior.memory_summary->>'processed_windows')::bigint else 0 end
     where id=proof.id returning * into proof;
 end if;
 select pos.sequence,pos.source_id,pos.version,part as char_start,
   case when src.version=pos.version and src.status='active' then least(part+2000,length(src.text)) else 0 end as char_end,
   src as original,case when src.version=pos.version and src.status='active' then 'active' else 'tombstone' end as status
 into next_item from public.user_lifetime_source_position pos left join public.user_narrator_source src
   on src.user_id=pos.user_id and src.project_id=pos.project_id and src.id=pos.source_id
 cross join lateral generate_series(0,case when src.version=pos.version and src.status='active' then greatest(length(src.text)-1,0) else 0 end,2000) part
 where pos.user_id=snap.user_id and pos.project_id=snap.project_id and pos.sequence<=proof.through_sequence
   and (pos.sequence>proof.summary_sequence or (pos.sequence=proof.summary_sequence and part>proof.summary_offset))
 order by pos.sequence,part limit 1;
 if not found then
   update public.user_lifetime_compaction set summary_complete=true where id=proof.id;
   perform public.publish_lifetime_semantic_checkpoint(p_lane_id,p_token,proof.id);
   return page;
 end if;
 source:=null;work:='reply_only';
 if next_item.status='active' then
   source:=public.narrator_source_record(next_item.original)||jsonb_build_object('text',substring((next_item.original).text from next_item.char_start+1 for next_item.char_end-next_item.char_start),
     'char_start',next_item.char_start,'char_end',next_item.char_end,'original_length',length((next_item.original).text));
   select coalesce((select case when t.collector->'plan'->'work'->>'mode'='reply_only' then 'reply_only' else 'extract' end
     from public.user_interview_turn t where t.user_id=snap.user_id and t.project_id=snap.project_id and t.source_id=next_item.source_id and t.source_version=next_item.version),'extract') into work;
 end if;
 page:=(page-'input_digest'-'page_digest')||jsonb_build_object('complete',false,'source',source,'partition',null,'events','[]'::jsonb,
   'two_lane',jsonb_build_object('schema_version',1,'task_version','two-lane-v1','execution_generation',identity.execution_generation,
     'phase_revision',proof.fence->'phase_revision','work_mode',work,'strategy_mode',null,'strategy_revision',0),
   'memory_summary',jsonb_build_object('schema_version',1,'maintenance_id',proof.id,'revision',proof.summary_revision,
     'through_sequence',proof.through_sequence,'sequence',next_item.sequence,'char_start',next_item.char_start,'char_end',next_item.char_end,
     'status',next_item.status,'work_mode',work,'prior',proof.summary_data));
 page:=page||jsonb_build_object('input_digest',encode(sha256(convert_to((page-'token')::text,'UTF8')),'hex'));
 page:=page||jsonb_build_object('page_digest',encode(sha256(convert_to(page::text,'UTF8')),'hex'));
 return page;
end $$;
revoke all on function public.read_lifetime_memoir_lane_page(uuid,uuid) from public,anon,authenticated;
grant execute on function public.read_lifetime_memoir_lane_page(uuid,uuid) to service_role;

create function public.commit_lifetime_memory_summary_page(p_lane_id uuid,p_token uuid,p_revision bigint,p_result jsonb,p_page_digest text)
returns jsonb language plpgsql security definer set search_path=public,auth as $$
declare snap public.user_lifetime_lane_snapshot%rowtype; proof public.user_lifetime_compaction%rowtype; page jsonb;
 item jsonb; ref jsonb; original public.user_narrator_source%rowtype; fingerprint text;
begin
 snap:=public.lock_lifetime_memoir_lane(p_lane_id,p_token);
 fingerprint:=encode(sha256(convert_to(p_result::text,'UTF8')),'hex');
 select p.* into proof from public.user_lifetime_compaction p join public.user_lifetime_summary_receipt r on r.maintenance_id=p.id
   where p.user_id=snap.user_id and p.conversation_id=snap.conversation_id and r.revision=p_revision and r.page_digest=p_page_digest;
 if found then
   if not exists(select 1 from public.user_lifetime_summary_receipt r where r.maintenance_id=proof.id and r.revision=p_revision and r.result_digest=fingerprint) then
     raise exception 'summary replay conflict' using errcode='PT409';end if;
   return jsonb_build_object('status','page_saved','replayed',true);
 end if;
 page:=public.read_lifetime_memoir_lane_page(p_lane_id,p_token);
 if page->'memory_summary' is null or p_page_digest is distinct from page->>'page_digest'
   or p_revision is distinct from (page->'memory_summary'->>'revision')::bigint then raise exception 'stale summary page' using errcode='PT409';end if;
 select * into proof from public.user_lifetime_compaction where id=(page->'memory_summary'->>'maintenance_id')::uuid for update;
 if jsonb_typeof(p_result) is distinct from 'object' or exists(select 1 from jsonb_object_keys(p_result) k where k<>'items')
   or jsonb_typeof(p_result->'items') is distinct from 'array' or jsonb_array_length(p_result->'items')>16
   or octet_length(p_result::text)>8192 then raise exception 'bounded semantic summary required' using errcode='22023';end if;
 if page->'memory_summary'->>'work_mode'='reply_only' and p_result is distinct from proof.summary_data then
   raise exception 'fact-free summary step must preserve prior context' using errcode='22023';end if;
 for item in select value from jsonb_array_elements(p_result->'items') loop
   if jsonb_typeof(item) is distinct from 'object' or exists(select 1 from jsonb_object_keys(item) k where k not in ('text','uncertainty','source_refs'))
     or jsonb_typeof(item->'text') is distinct from 'string' or length(item->>'text') not between 1 and 500
     or jsonb_typeof(item->'uncertainty') is distinct from 'string' or length(item->>'uncertainty') not between 1 and 500
     or jsonb_typeof(item->'source_refs') is distinct from 'array' or jsonb_array_length(item->'source_refs') not between 1 and 4 then
     raise exception 'typed derived summary item required' using errcode='22023';end if;
   for ref in select value from jsonb_array_elements(item->'source_refs') loop
     if jsonb_typeof(ref) is distinct from 'object' or exists(select 1 from jsonb_object_keys(ref) k where k not in ('source_id','version','quote','char_start','char_end'))
       or not(ref ?& array['source_id','version','quote','char_start','char_end']) or jsonb_typeof(ref->'quote') is distinct from 'string'
       or length(ref->>'quote') not between 1 and 500 or coalesce(ref->>'version','')!~'^[1-9][0-9]*$'
       or coalesce(ref->>'char_start','')!~'^[0-9]+$' or coalesce(ref->>'char_end','')!~'^[1-9][0-9]*$' then
       raise exception 'exact summary evidence required' using errcode='22023';end if;
     select * into original from public.user_narrator_source where user_id=snap.user_id and project_id=snap.project_id
       and id=(ref->>'source_id')::uuid and version=(ref->>'version')::bigint and status='active';
     if not found or (ref->>'char_end')::integer-(ref->>'char_start')::integer<>length(ref->>'quote')
       or substring(original.text from (ref->>'char_start')::integer+1 for length(ref->>'quote')) is distinct from ref->>'quote'
       or not ((page->'source'->>'id'=ref->>'source_id' and page->'source'->>'version'=ref->>'version'
         and (ref->>'char_start')::integer>=(page->'source'->>'char_start')::integer
         and (ref->>'char_end')::integer<=(page->'source'->>'char_end')::integer)
         or exists(select 1 from jsonb_array_elements(proof.summary_data->'items') old
           cross join lateral jsonb_array_elements(old->'source_refs') r where r=ref)) then
       raise exception 'summary evidence outside accepted inputs' using errcode='22023';end if;
   end loop;
 end loop;
 update public.user_lifetime_compaction set summary_data=p_result,summary_sequence=(page->'memory_summary'->>'sequence')::bigint,
   summary_offset=(page->'memory_summary'->>'char_start')::integer,summary_revision=summary_revision+1,summary_windows=summary_windows+1
   where id=proof.id and summary_revision=p_revision;
 if not found then raise exception 'summary CAS failed' using errcode='PT409';end if;
 insert into public.user_lifetime_summary_receipt values(proof.id,p_revision,p_page_digest,fingerprint);
 return jsonb_build_object('status','page_saved');
end $$;
revoke all on function public.commit_lifetime_memory_summary_page(uuid,uuid,bigint,jsonb,text) from public,anon,authenticated;
grant execute on function public.commit_lifetime_memory_summary_page(uuid,uuid,bigint,jsonb,text) to service_role;

-- Bind the new model-visible prior summary at actual provider admission. The
-- disabled path retains the original cost/locking behavior.
alter function public.lock_lifetime_memoir_lane_publication(jsonb) rename to lock_lifetime_memoir_lane_publication_before_semantic;
revoke all on function public.lock_lifetime_memoir_lane_publication_before_semantic(jsonb) from public,anon,authenticated,service_role;
create function public.lock_lifetime_memoir_lane_publication(p_fence jsonb) returns double precision
language plpgsql security definer set search_path=public,auth as $$
declare remaining double precision; page jsonb;
begin
 remaining:=public.lock_lifetime_memoir_lane_publication_before_semantic(p_fence);
 if exists(select 1 from public.lifetime_two_lane_rollout where singleton and enabled) then
   page:=public.read_lifetime_memoir_lane_page((p_fence->>'lane_id')::uuid,(p_fence->>'token')::uuid);
   if coalesce(p_fence->'memory_summary','null') is distinct from coalesce(page->'memory_summary','null') then
     raise exception 'summary admission differs from canonical page' using errcode='PT409';end if;
 end if;
 return remaining;
end $$;
revoke all on function public.lock_lifetime_memoir_lane_publication(jsonb) from public,anon;
grant execute on function public.lock_lifetime_memoir_lane_publication(jsonb) to authenticated,service_role;

alter function public.commit_lifetime_memoir_lane_page(uuid,uuid,bigint,jsonb,text) rename to commit_lifetime_memoir_lane_page_before_semantic;
revoke all on function public.commit_lifetime_memoir_lane_page_before_semantic(uuid,uuid,bigint,jsonb,text) from public,anon,authenticated,service_role;
create function public.commit_lifetime_memoir_lane_page(p_lane_id uuid,p_token uuid,p_page_number bigint,p_result jsonb,p_page_digest text)
returns jsonb language plpgsql security definer set search_path=public,auth as $$
begin
 if not (p_result ? 'strategy_proposal') and not exists(select 1 from public.lifetime_two_lane_rollout where singleton and enabled) then
   return public.commit_lifetime_memoir_lane_page_before_two_lanes(p_lane_id,p_token,p_page_number,p_result,p_page_digest);
 end if;
 if exists(select 1 from public.lifetime_two_lane_rollout where singleton and enabled)
   and public.read_lifetime_memoir_lane_page(p_lane_id,p_token) ? 'memory_summary' then
   raise exception 'semantic page requires its canonical writer' using errcode='PT409';end if;
 return public.commit_lifetime_memoir_lane_page_before_semantic(p_lane_id,p_token,p_page_number,p_result,p_page_digest);
end $$;
revoke all on function public.commit_lifetime_memoir_lane_page(uuid,uuid,bigint,jsonb,text) from public,anon,authenticated;
grant execute on function public.commit_lifetime_memoir_lane_page(uuid,uuid,bigint,jsonb,text) to service_role;

-- A feature rollback may consume an accepted semantic checkpoint. It must not
-- replace that checkpoint with the legacy two-excerpt compactor's raw inventory.
alter function public.create_lifetime_checkpoint(jsonb,bigint,text,text,jsonb,uuid) rename to create_lifetime_checkpoint_before_semantic;
revoke all on function public.create_lifetime_checkpoint_before_semantic(jsonb,bigint,text,text,jsonb,uuid) from public,anon,authenticated,service_role;
create function public.create_lifetime_checkpoint(p_fence jsonb,p_coverage_end bigint,p_model text,p_prompt_version text,
 p_evidence jsonb default '[]',p_coverage_proof uuid default null) returns uuid
language plpgsql security definer set search_path=public,auth as $$
begin
 perform public.lock_lifetime_publication(p_fence);
 if exists(select 1 from public.user_lifetime_conversation l join public.user_lifetime_checkpoint c on c.id=l.checkpoint_id
   where l.user_id=auth.uid() and l.conversation_id=(p_fence->'identity'->>'conversation_id')::uuid and c.memory_summary is not null) then
   raise exception 'LIFETIME_SEMANTIC_MAINTENANCE_REQUIRED: accepted summary requires bounded B maintenance' using errcode='PT409';
 end if;
 return public.create_lifetime_checkpoint_before_semantic(p_fence,p_coverage_end,p_model,p_prompt_version,p_evidence,p_coverage_proof);
end $$;
revoke all on function public.create_lifetime_checkpoint(jsonb,bigint,text,text,jsonb,uuid) from public,anon;
grant execute on function public.create_lifetime_checkpoint(jsonb,bigint,text,text,jsonb,uuid) to authenticated;

-- A technical retry can be older than the newest background checkpoint. Choose
-- a compatible accepted predecessor without moving the canonical head backwards.
create index lifetime_checkpoint_before_current on public.user_lifetime_checkpoint
 (user_id,conversation_id,model,prompt_version,coverage_end desc,created_at desc) where published;
create function public.read_lifetime_checkpoint_before(p_conversation_id uuid,p_policy_epoch bigint,p_model text,p_prompt_version text,
 p_before_sequence bigint,p_require_accepted boolean default true) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare saved public.user_lifetime_checkpoint%rowtype; result jsonb; summary jsonb;
begin
 -- Reuse canonical owner, current-policy and pending-policy admission guards.
 result:=public.read_lifetime_checkpoint(p_conversation_id,p_policy_epoch,p_model,p_prompt_version);
 if p_before_sequence is null or p_before_sequence<1 then raise exception 'current source position required';end if;
 if result is not null and (result->>'coverage_end')::bigint<p_before_sequence and
   (not p_require_accepted or exists(select 1 from public.user_lifetime_checkpoint c where c.id=(result->>'checkpoint_id')::uuid
     and (c.lossless or c.memory_summary is not null))) then return result;end if;
 select * into saved from public.user_lifetime_checkpoint c where c.user_id=auth.uid() and c.conversation_id=p_conversation_id
   and c.published and c.fence->>'policy_epoch'=p_policy_epoch::text and c.model=p_model and c.prompt_version=p_prompt_version
   and c.coverage_end<p_before_sequence and (not p_require_accepted or c.lossless or c.memory_summary is not null)
   order by c.coverage_end desc,c.created_at desc limit 1;
 if not found then return null;end if;
 summary:=saved.memory_summary;
 if summary is not null then
   if not exists(select 1 from public.user_lifetime_compaction p where p.user_id=auth.uid() and p.id=(summary->>'maintenance_id')::uuid
      and p.complete and p.summary_complete and p.digest=summary->>'coverage_digest' and p.through_sequence=saved.coverage_end)
      or exists(select 1 from jsonb_array_elements(summary->'items') i cross join lateral jsonb_array_elements(i->'source_refs') r
        where not exists(select 1 from public.user_narrator_source n join public.user_lifetime_conversation l
          on l.user_id=n.user_id and l.project_id=n.project_id and l.conversation_id=p_conversation_id
          where n.user_id=auth.uid() and n.id=(r->>'source_id')::uuid and n.version=(r->>'version')::bigint and n.status='active')) then return null;end if;
 end if;
 result:=jsonb_build_object('schema_version',1,'checkpoint_id',saved.id,'predecessor_id',saved.predecessor_id,
   'identity',saved.fence->'identity','policy_epoch',p_policy_epoch,'coverage_end',saved.coverage_end,'model',saved.model,
   'prompt_version',saved.prompt_version,'pinned',public.read_lifetime_pinned(p_conversation_id),'manifest',saved.manifest,'evidence',saved.evidence);
 if summary is not null then result:=result||jsonb_build_object('memory_summary',summary);end if;
 return result;
end $$;
revoke all on function public.read_lifetime_checkpoint_before(uuid,bigint,text,text,bigint,boolean) from public,anon;
grant execute on function public.read_lifetime_checkpoint_before(uuid,bigint,text,text,bigint,boolean) to authenticated;

-- Share the installed legacy validators rather than fork their photo/news/work
-- rules. Only the canonical commit supplies an explicit current execution fence;
-- legacy direct saves retain their original source-revision staleness check.
do $migration$
declare core text; phase text; memory_body text; commit_body text;
 source_guard text:='turn.source_sequence is distinct from project.source_sequence';
 policy_guard text:='turn.policy_epoch is distinct from project.policy_epoch';
 project_lock text:='  select * into project from public.user_memoir_project where user_id=v_owner and project_id=p_project_id for update;';
 fresh_check text:=$check$
  if p_snapshot_fence is not null then
    if p_snapshot_fence->'identity'->>'project_id' is distinct from p_project_id
      or p_snapshot_fence->'identity'->>'owner_id' is distinct from v_owner::text
      or p_snapshot_fence->>'lease_token' is distinct from p_lease_token::text then
      raise exception 'canonical reply scope mismatch' using errcode='42501';end if;
    perform public.lock_lifetime_publication(p_snapshot_fence);
  end if;
$check$;
begin
 core:=pg_get_functiondef('public.save_user_interview_plan_before_phase(text,uuid,jsonb,jsonb,uuid,text,jsonb,text)'::regprocedure);
 if position(source_guard in core)=0 or position(policy_guard in core)=0 or position(project_lock in core)=0 then
   raise exception 'canonical plan validator shape changed; review snapshot adaptation';end if;
 core:=replace(core,'public.save_user_interview_plan_before_phase(',
   'public.save_lifetime_interview_plan_core(p_snapshot_fence jsonb, ');
 core:=replace(core,source_guard,'(p_snapshot_fence is null and '||source_guard||')');
 core:=replace(core,policy_guard,'(p_snapshot_fence is null and '||policy_guard||')');
 core:=replace(core,project_lock,project_lock||fresh_check);
 execute core;
 phase:=pg_get_functiondef('public.save_user_interview_plan(text,uuid,jsonb,jsonb,uuid,text,jsonb,text)'::regprocedure);
 if position('public.save_user_interview_plan_before_phase(' in phase)=0 then
   raise exception 'canonical phase validator shape changed; review snapshot adaptation';end if;
 phase:=replace(phase,'public.save_user_interview_plan(',
   'public.save_lifetime_interview_plan(p_snapshot_fence jsonb, ');
 phase:=replace(phase,'public.save_user_interview_plan_before_phase(',
   'public.save_lifetime_interview_plan_core(p_snapshot_fence,');
 execute phase;
 memory_body:=pg_get_functiondef('public.commit_user_agent_turn_before_lifetime_adoption(uuid,text,text,text[],bigint,text,uuid,boolean,text)'::regprocedure);
 if position(source_guard in memory_body)=0 or position(policy_guard in memory_body)=0 or position(project_lock in memory_body)=0 then
   raise exception 'canonical memory validator shape changed; review snapshot adaptation';end if;
 memory_body:=replace(memory_body,'public.commit_user_agent_turn_before_lifetime_adoption(',
   'public.commit_lifetime_interview_memory(p_snapshot_fence jsonb, ');
 memory_body:=replace(memory_body,source_guard,'(p_snapshot_fence is null and '||source_guard||')');
 memory_body:=replace(memory_body,policy_guard,'(p_snapshot_fence is null and '||policy_guard||')');
 memory_body:=replace(memory_body,project_lock,project_lock||fresh_check);
 execute memory_body;
 commit_body:=pg_get_functiondef('public.commit_lifetime_turn(jsonb,uuid,jsonb,jsonb,text,jsonb,text,text,text,jsonb)'::regprocedure);
 if position('public.save_user_interview_plan(project,' in commit_body)=0 then
   raise exception 'canonical turn commit shape changed; review snapshot adaptation';end if;
 commit_body:=replace(commit_body,'public.save_user_interview_plan(project,','public.save_lifetime_interview_plan(p_fence,project,');
 if position('public.commit_user_agent_turn_before_lifetime_adoption(' in commit_body)=0 then
   raise exception 'canonical memory commit shape changed; review snapshot adaptation';end if;
 commit_body:=replace(commit_body,'public.commit_user_agent_turn_before_lifetime_adoption(',
   'public.commit_lifetime_interview_memory(next_fence,');
 execute commit_body;
end $migration$;
revoke all on function public.save_lifetime_interview_plan_core(jsonb,text,uuid,jsonb,jsonb,uuid,text,jsonb,text),
 public.save_lifetime_interview_plan(jsonb,text,uuid,jsonb,jsonb,uuid,text,jsonb,text),
 public.commit_lifetime_interview_memory(jsonb,uuid,text,text,text[],bigint,text,uuid,boolean,text) from public,anon,authenticated,service_role;
create or replace function public.save_user_interview_plan_before_phase(p_project_id text,p_client_turn_id uuid,p_plan jsonb,p_associations jsonb,p_lease_token uuid,
 p_reply text default null,p_response_photo_ids jsonb default '[]',p_thread_id text default null) returns jsonb
language sql security definer set search_path='' as $$
 select public.save_lifetime_interview_plan_core(null,p_project_id,p_client_turn_id,p_plan,p_associations,p_lease_token,p_reply,p_response_photo_ids,p_thread_id);
$$;
create or replace function public.save_user_interview_plan(p_project_id text,p_client_turn_id uuid,p_plan jsonb,p_associations jsonb,p_lease_token uuid,
 p_reply text default null,p_response_photo_ids jsonb default '[]',p_thread_id text default null) returns jsonb
language sql security definer set search_path='' as $$
 select public.save_lifetime_interview_plan(null,p_project_id,p_client_turn_id,p_plan,p_associations,p_lease_token,p_reply,p_response_photo_ids,p_thread_id);
$$;
create or replace function public.commit_user_agent_turn_before_lifetime_adoption(
 p_lease_token uuid,p_thread_id text,p_content text,p_source_paths text[] default '{}',
 p_source_sequence bigint default null,p_project_id text default null,p_client_turn_id uuid default null,
 p_user_response boolean default true,p_life_stage text default 'unplaced') returns jsonb
language sql security definer set search_path='' as $$
 select public.commit_lifetime_interview_memory(null,p_lease_token,p_thread_id,p_content,p_source_paths,p_source_sequence,
   p_project_id,p_client_turn_id,p_user_response,p_life_stage);
$$;
notify pgrst,'reload schema';
commit;
