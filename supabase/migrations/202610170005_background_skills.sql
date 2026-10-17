-- Safe operation metadata: no private source text, prompts, plans or candidates.
begin;
create table public.user_background_skill_work (
 user_id uuid not null,project_id text not null,id text not null,
 lane_id uuid references public.user_memoir_lane on delete cascade,
 snapshot_id uuid,page_digest text,phase text not null,
 skill text not null,execution text not null check(execution in ('model','embedded','deterministic','provider','cache')),
 source_id uuid,source_version bigint,client_turn_id uuid,
 coverage_start bigint not null,coverage_end bigint not null,
 status text not null check(status in ('queued','running','completed','saved','failed','skipped','cached')),
 model_invoked boolean default false,model_attempts integer default 0,
 invocation_id uuid,lease_token uuid,reason text,updated_at timestamptz not null default clock_timestamp(),
 primary key(user_id,project_id,id),
 foreign key(user_id,project_id) references public.user_memoir_project(user_id,project_id) on delete cascade
);
alter table public.user_background_skill_work enable row level security;
revoke all on public.user_background_skill_work from public,anon,authenticated,service_role;
create index background_skill_recent on public.user_background_skill_work(user_id,project_id,updated_at desc);

create function public.background_skill_id(p_page jsonb,p_phase text) returns text
language sql immutable set search_path='' as $$
 select md5(concat_ws(':',p_page->>'snapshot_id',p_page->>'page_number',p_phase,
   p_page->'source'->>'id',p_page->'source'->>'version',p_page->'source'->>'char_start',
   p_page->'profile_context'->>'target_round',p_page->'profile_context'->>'work_mode'))
$$;
revoke all on function public.background_skill_id(jsonb,text) from public,anon,authenticated,service_role;

-- Only canonical commit wrappers call this helper. Eligibility is not execution.
create function public.background_skill_receipt(p_page jsonb,p_phase text,p_skill text,p_execution text,p_status text,p_reason text default null)
returns void language plpgsql set search_path='' as $$
declare source public.user_narrator_source%rowtype; first_source bigint;last_source bigint;
begin
 first_source:=coalesce((p_page->'source'->>'sequence')::bigint,(p_page->'profile_context'->>'source_frontier')::bigint,0);
 last_source:=first_source;
 if p_page ? 'batch' then
   select min((s->>'sequence')::bigint),max((s->>'sequence')::bigint) into first_source,last_source
   from jsonb_array_elements(coalesce(p_page->'batch'->'sources','[]')||coalesce(p_page->'batch'->'new_messages','[]')) s;
 end if;
 select * into source from public.user_narrator_source where user_id=(p_page->>'user_id')::uuid
   and project_id=p_page->>'project_id' and sequence=last_source and status='active';
 insert into public.user_background_skill_work(user_id,project_id,id,lane_id,snapshot_id,page_digest,phase,skill,execution,
   source_id,source_version,client_turn_id,coverage_start,coverage_end,status,reason,model_invoked,model_attempts,lease_token)
 values((p_page->>'user_id')::uuid,p_page->>'project_id',public.background_skill_id(p_page,p_phase),
   (p_page->>'lane_id')::uuid,(p_page->>'snapshot_id')::uuid,p_page->>'page_digest',p_phase,p_skill,p_execution,
   source.id,source.version,source.client_turn_id,coalesce(first_source,0),coalesce(last_source,0),p_status,p_reason,
   case when p_execution='model' and p_status='saved' then null else false end,
   case when p_execution='model' and p_status='saved' then null else 0 end,(p_page->>'token')::uuid)
 on conflict(user_id,project_id,id) do update set status=excluded.status,reason=excluded.reason,
   page_digest=excluded.page_digest,lease_token=excluded.lease_token,updated_at=clock_timestamp();
end $$;
revoke all on function public.background_skill_receipt(jsonb,text,text,text,text,text) from public,anon,authenticated,service_role;

create function public.record_lifetime_skill_phase(p_fence jsonb,p_phase text,p_status text,p_invocation_id uuid) returns void
language plpgsql security definer set search_path='' as $$
declare page jsonb; source public.user_narrator_source%rowtype; skill text; first_source bigint;last_source bigint;
begin
 if p_phase not in ('extract','profile','summarize','prepare','draft','review','index') or p_status not in ('running','completed','failed')
   or p_invocation_id is null then raise exception 'bounded skill phase required' using errcode='22023';end if;
 perform public.lock_lifetime_memoir_lane_publication(p_fence);
 if p_phase='profile' then
   page:=public.read_lifetime_profile_page((p_fence->>'lane_id')::uuid,(p_fence->>'token')::uuid);
   if page->'profile_context'->>'work_mode'<>'extract' then raise exception 'profile model not admitted' using errcode='42501';end if;
   skill:='memoir-memory-context';
 else
   page:=public.read_lifetime_memoir_lane_page((p_fence->>'lane_id')::uuid,(p_fence->>'token')::uuid);
   skill:=case when page->>'skill'='composer' then 'memoir-composer' else 'memoir-author-timeline' end;
   if (page->>'skill'='timeline' and p_phase not in ('extract','summarize'))
     or (page->>'skill'='composer' and p_phase not in ('prepare','draft','review','index')) then
     raise exception 'skill phase mismatch' using errcode='42501';end if;
   if p_phase='extract' and page->'two_lane'->>'work_mode'<>'extract' then raise exception 'timeline model not admitted' using errcode='42501';end if;
 end if;
 if page->>'page_digest' is distinct from p_fence->>'page_digest' then raise exception 'skill page changed' using errcode='40001';end if;
 first_source:=coalesce((page->'source'->>'sequence')::bigint,0);last_source:=first_source;
 if page ? 'batch' then
   select min((s->>'sequence')::bigint),max((s->>'sequence')::bigint) into first_source,last_source
     from jsonb_array_elements(coalesce(page->'batch'->'sources','[]')||coalesce(page->'batch'->'new_messages','[]')) s;
 end if;
 select * into source from public.user_narrator_source where user_id=(page->>'user_id')::uuid
   and project_id=page->>'project_id' and sequence=last_source and status='active';
 insert into public.user_background_skill_work(user_id,project_id,id,lane_id,snapshot_id,page_digest,phase,skill,execution,
   source_id,source_version,client_turn_id,coverage_start,coverage_end,status,model_invoked,model_attempts,invocation_id,lease_token)
 values((page->>'user_id')::uuid,page->>'project_id',public.background_skill_id(page,p_phase),
   (page->>'lane_id')::uuid,(page->>'snapshot_id')::uuid,page->>'page_digest',p_phase,skill,'model',
   source.id,source.version,source.client_turn_id,coalesce(first_source,0),coalesce(last_source,0),p_status,p_status='completed',1,p_invocation_id,(page->>'token')::uuid)
 on conflict(user_id,project_id,id) do update set status=excluded.status,
   page_digest=excluded.page_digest,lease_token=excluded.lease_token,
   model_attempts=public.user_background_skill_work.model_attempts+case when public.user_background_skill_work.invocation_id<>p_invocation_id then 1 else 0 end,
   model_invoked=public.user_background_skill_work.model_invoked or excluded.model_invoked,
   invocation_id=p_invocation_id,updated_at=clock_timestamp()
 where public.user_background_skill_work.status<>'saved';
end $$;
revoke all on function public.record_lifetime_skill_phase(jsonb,text,text,uuid) from public,anon,authenticated;
grant execute on function public.record_lifetime_skill_phase(jsonb,text,text,uuid) to service_role;

alter function public.commit_lifetime_memoir_lane_page(uuid,uuid,bigint,jsonb,text) rename to commit_lifetime_memoir_lane_page_before_skills;
revoke all on function public.commit_lifetime_memoir_lane_page_before_skills(uuid,uuid,bigint,jsonb,text) from public,anon,authenticated,service_role;
create function public.commit_lifetime_memoir_lane_page(p_lane_id uuid,p_token uuid,p_page_number bigint,p_result jsonb,p_page_digest text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare result jsonb; page jsonb;
begin
 page:=public.read_lifetime_memoir_lane_page(p_lane_id,p_token);
 result:=public.commit_lifetime_memoir_lane_page_before_skills(p_lane_id,p_token,p_page_number,p_result,p_page_digest);
 if result->>'status'='page_saved' and result->>'replayed' is distinct from 'true' then
   update public.user_background_skill_work set status='saved',reason=null,page_digest=p_page_digest,
     lease_token=(page->>'token')::uuid,updated_at=clock_timestamp()
   where lane_id=p_lane_id and snapshot_id=(page->>'snapshot_id')::uuid
     and id=public.background_skill_id(page,phase) and status in ('completed','failed') and model_invoked;
   if not exists(select 1 from public.user_background_skill_work where lane_id=p_lane_id and page_digest=p_page_digest and status='saved')
     and page->'two_lane'->>'work_mode' is distinct from 'reply_only' then
     perform public.background_skill_receipt(page,case when page->>'skill'='composer' then 'commit' else 'extract' end,
       case when page->>'skill'='composer' then 'memoir-composer' else 'memoir-author-timeline' end,
       'model','saved','invocation_receipt_unavailable');
   end if;
   if page->'two_lane'->>'work_mode'='reply_only' then
     perform public.background_skill_receipt(page,'extract','memoir-author-timeline','model','skipped','reply_only');
   end if;
   if page->>'skill'='timeline' and page ? 'two_lane' and jsonb_array_length(coalesce(p_result->'place_journeys','[]'))>0 then
     perform public.background_skill_receipt(page,'place','memoir-place-journey','embedded','saved');
   end if;
 end if;
 return result;
end $$;
revoke all on function public.commit_lifetime_memoir_lane_page(uuid,uuid,bigint,jsonb,text) from public,anon,authenticated;
grant execute on function public.commit_lifetime_memoir_lane_page(uuid,uuid,bigint,jsonb,text) to service_role;

alter function public.commit_lifetime_profile_page(uuid,uuid,text,jsonb) rename to commit_lifetime_profile_page_before_skills;
revoke all on function public.commit_lifetime_profile_page_before_skills(uuid,uuid,text,jsonb) from public,anon,authenticated,service_role;
create function public.commit_lifetime_profile_page(p_lane_id uuid,p_token uuid,p_page_digest text,p_result jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare result jsonb; page jsonb; reason text;
begin
 page:=public.read_lifetime_profile_page(p_lane_id,p_token);
 result:=public.commit_lifetime_profile_page_before_skills(p_lane_id,p_token,p_page_digest,p_result);
 if result->>'status'='page_saved' and result->>'replayed' is distinct from 'true' then
   update public.user_background_skill_work set status='saved',updated_at=clock_timestamp()
   where lane_id=p_lane_id and page_digest=p_page_digest and status in ('completed','failed') and model_invoked;
   if page->'profile_context'->>'work_mode'='extract' and not exists(select 1 from public.user_background_skill_work
     where lane_id=p_lane_id and page_digest=p_page_digest and status='saved') then
     perform public.background_skill_receipt(page,'profile','memoir-memory-context','model','saved','invocation_receipt_unavailable');
   end if;
   if page->'profile_context'->>'work_mode' in ('skip','reply_only') then
     select case when not a.auto_enabled then 'automatic_stopped' when a.manual_complete then 'manually_confirmed' else 'no_targets' end into reason
       from public.user_lifetime_profile_authority a where a.user_id=(page->>'user_id')::uuid;
     perform public.background_skill_receipt(page,'profile','memoir-memory-context','model','skipped',
       case when page->'profile_context'->>'work_mode'='skip' then reason
         when page->'source'='null'::jsonb then 'no_evidence' else 'reply_only' end);
   end if;
 end if;
 return result;
end $$;
revoke all on function public.commit_lifetime_profile_page(uuid,uuid,text,jsonb) from public,anon,authenticated;
grant execute on function public.commit_lifetime_profile_page(uuid,uuid,text,jsonb) to service_role;

alter function public.commit_lifetime_memory_summary_page(uuid,uuid,bigint,jsonb,text) rename to commit_lifetime_memory_summary_page_before_skills;
revoke all on function public.commit_lifetime_memory_summary_page_before_skills(uuid,uuid,bigint,jsonb,text) from public,anon,authenticated,service_role;
create function public.commit_lifetime_memory_summary_page(p_lane_id uuid,p_token uuid,p_revision bigint,p_result jsonb,p_page_digest text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare result jsonb;
begin
 result:=public.commit_lifetime_memory_summary_page_before_skills(p_lane_id,p_token,p_revision,p_result,p_page_digest);
 if result->>'status'='page_saved' and result->>'replayed' is distinct from 'true' then
   update public.user_background_skill_work set status='saved',updated_at=clock_timestamp()
   where lane_id=p_lane_id and page_digest=p_page_digest and phase='summarize' and status in ('completed','failed') and model_invoked;
 end if;
 return result;
end $$;
revoke all on function public.commit_lifetime_memory_summary_page(uuid,uuid,bigint,jsonb,text) from public,anon,authenticated;
grant execute on function public.commit_lifetime_memory_summary_page(uuid,uuid,bigint,jsonb,text) to service_role;

alter function public.fail_memoir_lane(uuid,uuid,text,boolean) rename to fail_memoir_lane_before_skills;
revoke all on function public.fail_memoir_lane_before_skills(uuid,uuid,text,boolean) from public,anon,authenticated,service_role;
create function public.fail_memoir_lane(p_lane_id uuid,p_token uuid,p_error text,p_retryable boolean default true) returns jsonb
language plpgsql security definer set search_path='' as $$
declare result jsonb;
begin
 result:=public.fail_memoir_lane_before_skills(p_lane_id,p_token,p_error,p_retryable);
 if result->>'status' in ('retry','retry_required') then
   update public.user_background_skill_work set status='failed',reason='retry_required',updated_at=clock_timestamp()
   where lane_id=p_lane_id and status in ('running','completed');
 end if;
 return result;
end $$;
revoke all on function public.fail_memoir_lane(uuid,uuid,text,boolean) from public,anon,authenticated;
grant execute on function public.fail_memoir_lane(uuid,uuid,text,boolean) to service_role;

-- Reading a validated existing checkpoint is cache use, not another model call.
alter function public.read_memoir_checkpoint(uuid,uuid,text) rename to read_memoir_checkpoint_before_skills;
revoke all on function public.read_memoir_checkpoint_before_skills(uuid,uuid,text) from public,anon,authenticated,service_role;
create function public.read_memoir_checkpoint(p_lane_id uuid,p_token uuid,p_key text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare result jsonb; page jsonb;
begin
 result:=public.read_memoir_checkpoint_before_skills(p_lane_id,p_token,p_key);
 if result is not null and exists(select 1 from public.user_memoir_lane l join public.user_lifetime_conversation c
   on c.user_id=l.user_id and c.project_id=l.project_id where l.id=p_lane_id and l.skill='composer') then
   page:=public.read_lifetime_memoir_lane_page(p_lane_id,p_token);
   perform public.background_skill_receipt(page,'checkpoint','memoir-composer','cache','cached');
 end if;
 return result;
end $$;
revoke all on function public.read_memoir_checkpoint(uuid,uuid,text) from public,anon,authenticated;
grant execute on function public.read_memoir_checkpoint(uuid,uuid,text) to service_role;

-- Server-only optional-operation receipts. No source text/query or provider result
-- enters this table; public photo caches and research claims remain separate.
create function public.record_background_service_work(p_user_id uuid,p_project_id text,p_step jsonb) returns void
language plpgsql security definer set search_path='' as $$
declare source public.user_narrator_source%rowtype;
begin
 if p_step->>'skill' not in ('memoir-place-groups','place-photo-research','historical-news-research')
   or p_step->>'status' not in ('running','completed','saved','failed','cached')
   or p_step->>'execution' not in ('deterministic','provider','cache')
   or p_step->>'id' !~ '^[a-f0-9]{64}$' then raise exception 'invalid service receipt' using errcode='22023';end if;
 if p_step->>'skill'='historical-news-research' then
   select s.* into source from public.user_historical_news_job j join public.user_narrator_source s
     on s.user_id=j.user_id and s.project_id=j.project_id and s.sequence=j.source_sequence
   where j.user_id=p_user_id and j.project_id=p_project_id and j.id=(p_step->>'research_job_id')::uuid and s.status='active';
   if not found then raise exception 'owned research claim required' using errcode='42501';end if;
 elsif p_step->>'client_turn_id' is not null then
   select * into source from public.user_narrator_source where user_id=p_user_id and project_id=p_project_id
     and client_turn_id=(p_step->>'client_turn_id')::uuid and status='active';
   if not found then raise exception 'owned turn reference required' using errcode='42501';end if;
 end if;
 insert into public.user_background_skill_work(user_id,project_id,id,phase,skill,execution,coverage_start,coverage_end,status,
   client_turn_id,source_id,source_version,model_invoked,model_attempts)
 values(p_user_id,p_project_id,p_step->>'id',p_step->>'phase',p_step->>'skill',p_step->>'execution',coalesce(source.sequence,0),coalesce(source.sequence,0),p_step->>'status',
   source.client_turn_id,source.id,source.version,(p_step->>'model_invoked')::boolean,
   case when p_step->>'model_invoked'='false' then 0 else null end)
 on conflict(user_id,project_id,id) do update set status=excluded.status,execution=excluded.execution,
   model_invoked=excluded.model_invoked,model_attempts=excluded.model_attempts,updated_at=clock_timestamp();
end $$;
revoke all on function public.record_background_service_work(uuid,text,jsonb) from public,anon,authenticated;
grant execute on function public.record_background_service_work(uuid,text,jsonb) to service_role;

create function public.read_lifetime_current_mode(p_project_id text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare outcome public.user_lifetime_strategy_outcome%rowtype; result jsonb;
begin
 perform 1 from public.user_memoir_project where user_id=auth.uid() and project_id=p_project_id for share;
 if not found then raise exception 'owned project required' using errcode='42501';end if;
 if not exists(select 1 from public.lifetime_two_lane_rollout where singleton and enabled and strategy_enabled and not strategy_shadow)
   then return null;end if;
 select * into outcome from public.user_lifetime_strategy_outcome where user_id=auth.uid() and project_id=p_project_id
   and delivered order by source_sequence desc limit 1;
 select jsonb_build_object('project_id',p_project_id,'mode',outcome.used_strategy,'client_turn_id',outcome.client_turn_id,'reply_id',outcome.reply_id,
   'source_id',outcome.source_id,'source_sequence',outcome.source_sequence,'plan_revision_seen',outcome.plan_revision_seen,
   'policy_epoch',r.policy_epoch,'preference_revision',r.preference_revision,'execution_generation',r.execution_generation)
 into result from public.user_lifetime_reply r
 join public.user_lifetime_conversation c on c.user_id=r.user_id and c.conversation_id=r.conversation_id
 join public.user_memoir_project p on p.user_id=c.user_id and p.project_id=c.project_id
 join public.user_narrator_source s on s.user_id=p.user_id and s.project_id=p.project_id and s.id=outcome.source_id
 where r.user_id=auth.uid() and r.memory_id=outcome.reply_id and c.project_id=p_project_id
   and outcome.used_strategy in ('comfort','explore','shape') and s.status='active' and s.sequence=outcome.source_sequence
   and s.sequence=p.source_sequence and r.policy_epoch=p.policy_epoch and r.preference_revision=c.preference_revision
   and r.execution_generation=c.execution_generation;
 return result;
end $$;
revoke all on function public.read_lifetime_current_mode(text) from public,anon,service_role;
grant execute on function public.read_lifetime_current_mode(text) to authenticated;

alter function public.read_story_game_eligibility(text) rename to read_story_game_eligibility_before_skills;
revoke all on function public.read_story_game_eligibility_before_skills(text) from public,anon,authenticated,service_role;
create function public.read_story_game_eligibility(p_project_id text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare result jsonb; mode jsonb; reason text;
begin
 result:=public.read_story_game_eligibility_before_skills(p_project_id);
 mode:=public.read_lifetime_current_mode(p_project_id);
 reason:=case when mode is null then 'current_decision_required' when mode->>'mode'<>'shape' then 'shape_required' end;
 return result||jsonb_build_object('authority_eligible',(result->>'authority_eligible')::boolean and reason is null,
   'available',false,'reasons',result->'reasons'||case when reason is null then '[]'::jsonb else jsonb_build_array(reason) end);
end $$;
revoke all on function public.read_story_game_eligibility(text) from public,anon,service_role;
grant execute on function public.read_story_game_eligibility(text) to authenticated;

create function public.read_lifetime_skill_progress(p_project_id text,p_cursor text default null) returns jsonb
language plpgsql security definer set search_path='' as $$
declare records jsonb; queued jsonb; cursor jsonb; next_cursor text; more boolean;
begin
 perform 1 from public.user_memoir_project where user_id=auth.uid() and project_id=p_project_id for share;
 if not found then raise exception 'owned project required' using errcode='42501';end if;
 if p_cursor is not null then
   begin cursor:=convert_from(decode(p_cursor,'base64'),'UTF8')::jsonb;
   exception when others then raise exception 'invalid progress cursor' using errcode='22023';end;
   if cursor->>'owner' is distinct from auth.uid()::text or cursor->>'project' is distinct from p_project_id then
     raise exception 'progress cursor scope changed' using errcode='42501';end if;
 end if;
 select coalesce(jsonb_agg(to_jsonb(w)-array['user_id','lane_id','snapshot_id','page_digest','invocation_id','lease_token']||'{"lane":"B"}'::jsonb
   ||case when w.status in ('running','completed') and ((w.lane_id is null and w.status='running' and w.updated_at<clock_timestamp()-interval '5 minutes')
     or (w.lane_id is not null and not exists(select 1 from public.user_memoir_lane l
     where l.id=w.lane_id and l.token=w.lease_token and l.lease_until>clock_timestamp() and l.run_deadline>clock_timestamp()
       and exists(select 1 from public.user_lifetime_lane_snapshot s where s.id=w.snapshot_id and s.state='pending'))))
     then '{"status":"failed","reason":"interrupted"}'::jsonb else '{}'::jsonb end
   order by w.updated_at,w.id),'[]') into records from (select * from public.user_background_skill_work
   where user_id=auth.uid() and project_id=p_project_id
     and (p_cursor is null or (updated_at,id)<((cursor->>'at')::timestamptz,cursor->>'id'))
   order by updated_at desc,id desc limit 32) w;
 select exists(select 1 from public.user_background_skill_work
   where user_id=auth.uid() and project_id=p_project_id
     and (p_cursor is null or (updated_at,id)<((cursor->>'at')::timestamptz,cursor->>'id')) offset 32 limit 1) into more;
 if more then
   next_cursor:=encode(convert_to(jsonb_build_object('owner',auth.uid(),'project',p_project_id,
     'at',records->0->>'updated_at','id',records->0->>'id')::text,'UTF8'),'base64');
 end if;
 -- A real pending lane is queued, not proof that any phase/model has run.
 select coalesce(jsonb_agg(jsonb_build_object('id','queue:'||id||':'||target_source,'skill',case when skill='composer' then 'memoir-composer' else 'memoir-author-timeline' end,
   'lane','B','phase','queue','execution','model','status','queued','model_invoked',false,
   'coverage_start',successful_source+1,'coverage_end',target_source,'project_id',project_id,
   'client_turn_id',(select s.client_turn_id from public.user_narrator_source s where s.user_id=auth.uid() and s.project_id=p_project_id
     and s.sequence=l.target_source and s.status='active'))),'[]') into queued
 from public.user_memoir_lane l where p_cursor is null and user_id=auth.uid() and project_id=p_project_id and pending
   and attempts<3 and (token is null or lease_until<=clock_timestamp() or run_deadline<=clock_timestamp());
 return jsonb_build_object('project_id',p_project_id,'items',queued||records,'recent_limit',32,
   'continuation',p_cursor is not null,'truncated',more,'next_cursor',next_cursor,
   'pending',exists(select 1 from public.user_memoir_lane where user_id=auth.uid() and project_id=p_project_id
     and attempts<3 and (pending or (token is not null and lease_until>clock_timestamp() and run_deadline>clock_timestamp()))));
end $$;
revoke all on function public.read_lifetime_skill_progress(text,text) from public,anon;
grant execute on function public.read_lifetime_skill_progress(text,text) to authenticated;
notify pgrst,'reload schema';
commit;
