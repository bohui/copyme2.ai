-- Three-strategy expansion. All new controls default OFF; shadow state is private.
begin;

-- Reconcile unsaved accepted turns through the same path even after flag rollback.
alter function public.accept_user_interview_turn(text,uuid,text,text,text,jsonb,jsonb) rename to accept_user_interview_turn_before_pending_guard;
revoke all on function public.accept_user_interview_turn_before_pending_guard(text,uuid,text,text,text,jsonb,jsonb) from public,anon,authenticated,service_role;
create function public.accept_user_interview_turn(p_project_id text,p_client_turn_id uuid,p_text text,
 p_kind text default 'narrator_chat',p_language text default 'en-AU',p_uploaded_photo_ids jsonb default '[]',p_photo_selection jsonb default null)
returns jsonb language plpgsql security definer set search_path=public,auth as $$
declare identity public.user_lifetime_conversation%rowtype;
begin
 select * into identity from public.user_lifetime_conversation where user_id=auth.uid() and project_id=p_project_id;
 if found then
   perform 1 from public.user_memoir_project where user_id=auth.uid() and project_id=p_project_id for update;
   if exists(select 1 from public.user_interview_turn t join public.user_narrator_source s
     on s.user_id=t.user_id and s.project_id=t.project_id and s.id=t.source_id and s.status='active'
     where t.user_id=auth.uid() and t.project_id=p_project_id and t.client_turn_id<>p_client_turn_id
       and not exists(select 1 from public.user_lifetime_reply r where r.user_id=t.user_id
         and r.conversation_id=identity.conversation_id and r.client_turn_id=t.client_turn_id)) then
     raise exception 'saved source has a pending reply; retry its original turn' using errcode='PT409';
   end if;
 end if;
 return public.accept_user_interview_turn_before_pending_guard(p_project_id,p_client_turn_id,p_text,p_kind,p_language,p_uploaded_photo_ids,p_photo_selection);
end $$;
revoke all on function public.accept_user_interview_turn(text,uuid,text,text,text,jsonb,jsonb) from public,anon;
grant execute on function public.accept_user_interview_turn(text,uuid,text,text,text,jsonb,jsonb) to authenticated;

create function public.read_lifetime_two_lane_checkpoint(p_conversation_id uuid,p_policy_epoch bigint,p_model text,p_prompt_version text)
returns jsonb language plpgsql security definer set search_path=public,auth as $$
declare result jsonb;
begin
 result:=public.read_lifetime_checkpoint(p_conversation_id,p_policy_epoch,p_model,p_prompt_version);
 if result is not null and not exists(select 1 from public.user_lifetime_checkpoint where user_id=auth.uid()
   and id=(result->>'checkpoint_id')::uuid and lossless) then return null;end if;
 return result;
end $$;
create function public.read_lifetime_two_lane_tail(p_conversation_id uuid,p_policy_epoch bigint,p_after_sequence bigint,p_through_sequence bigint)
returns jsonb language plpgsql security definer set search_path=public,auth as $$
declare result jsonb; page jsonb; cursor_seq bigint:=p_after_sequence; hi bigint;
begin
 -- Use canonical policy/access guards for every page; only exact originals and
 -- tombstones are joined. Never silently truncate an oversized required tail.
 result:=jsonb_build_object('records','[]'::jsonb,'tombstones','[]'::jsonb,'complete',true,
   'after_sequence',p_after_sequence,'through_sequence',p_through_sequence);
 if p_through_sequence-p_after_sequence>256 then
   perform public.read_lifetime_tail(p_conversation_id,p_policy_epoch,p_after_sequence,p_after_sequence);
   return result||jsonb_build_object('complete',false);
 end if;
 loop
   hi:=least(cursor_seq+16,p_through_sequence);
   page:=public.read_lifetime_tail(p_conversation_id,p_policy_epoch,cursor_seq,hi);
   if page->'complete' is distinct from 'true'::jsonb then return result||jsonb_build_object('complete',false);end if;
   result:=jsonb_set(jsonb_set(result,'{records}',(result->'records')||(page->'records')),'{tombstones}',(result->'tombstones')||(page->'tombstones'));
   if octet_length(result::text)>32768 then return result||jsonb_build_object('complete',false);end if;
   cursor_seq:=hi;
   exit when cursor_seq>=p_through_sequence;
 end loop;
 return result;
end $$;
revoke all on function public.read_lifetime_two_lane_checkpoint(uuid,bigint,text,text),public.read_lifetime_two_lane_tail(uuid,bigint,bigint,bigint) from public,anon;
grant execute on function public.read_lifetime_two_lane_checkpoint(uuid,bigint,text,text),public.read_lifetime_two_lane_tail(uuid,bigint,bigint,bigint) to authenticated;

alter table public.lifetime_two_lane_rollout add column strategy_enabled boolean not null default false,
 add column strategy_shadow boolean not null default true;
create table public.user_lifetime_strategy_frontier (
 user_id uuid not null,project_id text not null,revision bigint not null default 0,
 active_strategy text,shadow_strategy text,
 primary key(user_id,project_id),foreign key(user_id,project_id) references public.user_memoir_project on delete cascade
);
create table public.user_lifetime_interview_strategy (
 user_id uuid not null,project_id text not null,plan_revision bigint not null,shadow boolean not null,
 source_id uuid not null,source_version bigint not null,based_on_sequence bigint not null,
 policy_epoch bigint not null,preference_revision bigint not null,execution_generation bigint not null,phase_revision bigint not null,
 event_manifest jsonb not null,data jsonb not null,created_at timestamptz not null default clock_timestamp(),
 primary key(user_id,project_id,plan_revision),foreign key(user_id,project_id) references public.user_memoir_project on delete cascade
);
create table public.user_lifetime_strategy_outcome (
 user_id uuid not null,project_id text not null,client_turn_id uuid not null,reply_id uuid not null,source_id uuid not null,
 source_sequence bigint not null,plan_revision_seen bigint,selected_candidate_id text,selection_reason text not null,
 used_strategy text not null,question_delivered text,work_hint text not null,delivered boolean not null default false,
 created_at timestamptz not null default clock_timestamp(),
 primary key(user_id,project_id,client_turn_id),foreign key(user_id,project_id) references public.user_memoir_project on delete cascade
);
alter table public.user_lifetime_strategy_frontier enable row level security;
alter table public.user_lifetime_interview_strategy enable row level security;
alter table public.user_lifetime_strategy_outcome enable row level security;
revoke all on public.user_lifetime_strategy_frontier,public.user_lifetime_interview_strategy,public.user_lifetime_strategy_outcome from public,anon,authenticated;

-- Planning control/revision is part of the exact canonical page digest.
alter function public.read_lifetime_memoir_lane_page(uuid,uuid) rename to read_lifetime_memoir_lane_page_before_strategy;
revoke all on function public.read_lifetime_memoir_lane_page_before_strategy(uuid,uuid) from public,anon,authenticated,service_role;
create function public.read_lifetime_memoir_lane_page(p_lane_id uuid,p_token uuid) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare page jsonb; planning text; revision bigint;
begin
 page:=public.read_lifetime_memoir_lane_page_before_strategy(p_lane_id,p_token);
 if page ? 'two_lane' then
   select case when enabled and strategy_enabled then case when strategy_shadow then 'shadow' else 'active' end else 'disabled' end
     into planning from public.lifetime_two_lane_rollout where singleton;
   select f.revision into revision from public.user_lifetime_strategy_frontier f
     where f.user_id=(page->>'user_id')::uuid and f.project_id=page->>'project_id';
   if planning<>'disabled' then
     page:=jsonb_set(page,'{two_lane}',page->'two_lane'||jsonb_build_object('strategy_mode',planning,'strategy_revision',coalesce(revision,0)));
     page:=page-'input_digest'-'page_digest';
     page:=page||jsonb_build_object('input_digest',encode(sha256(convert_to((page-'token')::text,'UTF8')),'hex'));
     page:=page||jsonb_build_object('page_digest',encode(sha256(convert_to(page::text,'UTF8')),'hex'));
   end if;
 end if;
 return page;
end $$;
revoke all on function public.read_lifetime_memoir_lane_page(uuid,uuid) from public,anon,authenticated;
grant execute on function public.read_lifetime_memoir_lane_page(uuid,uuid) to service_role;

create function public.read_lifetime_strategy_context(p_conversation_id uuid) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare pins jsonb; identity public.user_lifetime_conversation%rowtype; planned public.user_lifetime_interview_strategy%rowtype;
 rollout text; data jsonb; candidates jsonb; hint text; delivery jsonb;
begin
 pins:=public.read_lifetime_pinned(p_conversation_id);
 select * into identity from public.user_lifetime_conversation where user_id=auth.uid() and conversation_id=p_conversation_id;
 select case when enabled and strategy_enabled then case when strategy_shadow then 'shadow' else 'active' end else 'disabled' end into rollout
   from public.lifetime_two_lane_rollout where singleton;
 if rollout<>'active' then return jsonb_build_object('mode',rollout,'plan',null);end if;
 select jsonb_build_object('prior_delivered_question',o.question_delivered,'prior_delivered_sequence',o.source_sequence) into delivery
   from public.user_lifetime_strategy_outcome o join public.user_interview_turn t
     on t.user_id=o.user_id and t.project_id=o.project_id and t.client_turn_id=o.client_turn_id
   join public.user_narrator_source s on s.user_id=t.user_id and s.project_id=t.project_id and s.id=t.source_id
     and s.version=t.source_version and s.status='active'
   join public.user_lifetime_reply r on r.user_id=o.user_id and r.conversation_id=p_conversation_id and r.client_turn_id=o.client_turn_id
   where o.user_id=auth.uid() and o.project_id=identity.project_id and o.delivered and o.question_delivered is not null
     and r.policy_epoch=(select p.policy_epoch from public.user_memoir_project p where p.user_id=auth.uid() and p.project_id=identity.project_id) and r.execution_generation=identity.execution_generation
     and r.preference_revision=identity.preference_revision order by o.source_sequence desc limit 1;
 delivery:=coalesce(delivery,jsonb_build_object('prior_delivered_question',null,'prior_delivered_sequence',null));
 select active_strategy into hint from public.user_lifetime_strategy_frontier where user_id=auth.uid() and project_id=identity.project_id;
 select * into planned from public.user_lifetime_interview_strategy where user_id=auth.uid() and project_id=identity.project_id and not shadow
   order by plan_revision desc limit 1;
 data:=planned.data;
 if planned.plan_revision is null or not exists(select 1 from public.user_memoir_project p join public.user_narrator_source s
   on s.user_id=p.user_id and s.project_id=p.project_id and s.id=planned.source_id and s.version=planned.source_version and s.status='active'
   where p.user_id=auth.uid() and p.project_id=identity.project_id and p.policy_epoch=planned.policy_epoch
     and planned.preference_revision=identity.preference_revision and planned.execution_generation=identity.execution_generation
     and planned.phase_revision=(pins->'conversation_phase'->>'revision')::bigint
     and planned.based_on_sequence between p.source_sequence-3 and p.source_sequence)
   or exists(select 1 from jsonb_array_elements(planned.event_manifest) e where not exists(select 1 from public.user_memory_event m
     where m.user_id=auth.uid() and m.project_id=identity.project_id and m.id=e->>'id' and m.revision::text=e->>'revision' and m.status='active')) then
   return jsonb_build_object('mode',rollout,'plan',null,'planned_strategy_hint',hint,'invalid_plan_revision',planned.plan_revision)||delivery;
 end if;
 select coalesce(jsonb_agg(q),'[]') into candidates from jsonb_array_elements(data->'candidates') q
   where not exists(select 1 from public.user_lifetime_strategy_outcome o where o.user_id=auth.uid() and o.project_id=identity.project_id
     and o.delivered and (o.selected_candidate_id=q->>'id' or lower(btrim(o.question_delivered))=lower(btrim(q->>'question'))))
   and not exists(select 1 from public.user_interview_turn t cross join lateral jsonb_array_elements(coalesce(t.collector->'plan'->'candidates','[]')) c
     where t.user_id=auth.uid() and t.project_id=identity.project_id and c->>'id'=t.collector->'plan'->>'chosen_id'
       and not exists(select 1 from public.user_lifetime_strategy_outcome o where o.user_id=t.user_id
         and o.project_id=t.project_id and o.client_turn_id=t.client_turn_id)
       and (c->>'id'=q->>'id' or lower(btrim(c->>'question'))=lower(btrim(q->>'question'))));
 data:=jsonb_set(data,'{candidates}',candidates);
 return jsonb_build_object('mode',rollout,'plan',data,'planned_strategy_hint',hint)||delivery;
end $$;
revoke all on function public.read_lifetime_strategy_context(uuid) from public,anon;
grant execute on function public.read_lifetime_strategy_context(uuid) to authenticated;

alter function public.commit_lifetime_memoir_lane_page(uuid,uuid,bigint,jsonb,text) rename to commit_lifetime_memoir_lane_page_before_strategy;
revoke all on function public.commit_lifetime_memoir_lane_page_before_strategy(uuid,uuid,bigint,jsonb,text) from public,anon,authenticated,service_role;
create function public.commit_lifetime_memoir_lane_page(p_lane_id uuid,p_token uuid,p_page_number bigint,p_result jsonb,p_page_digest text)
returns jsonb language plpgsql security definer set search_path=public,auth as $$
declare snap public.user_lifetime_lane_snapshot%rowtype; page jsonb; result jsonb; proposal jsonb; shadow_mode boolean;
 current_revision bigint; prior_sequence bigint; next_revision bigint; candidates jsonb; manifest jsonb; checkpoint uuid; lag bigint;
begin
 snap:=public.lock_lifetime_memoir_lane(p_lane_id,p_token);
 -- Canonical receipts own retries including the complete proposal digest. Store
 -- the proposal inside the existing events envelope's result digest separately
 -- below; never let a replay mutate an already accepted strategy.
 if p_page_number<snap.page_number and exists(select 1 from public.user_lifetime_strategy_page_receipt r
   where r.snapshot_id=snap.id and r.page_number=p_page_number) then
   if exists(select 1 from public.user_lifetime_strategy_page_receipt r where r.snapshot_id=snap.id and r.page_number=p_page_number
     and r.page_digest=p_page_digest and r.result_digest=encode(sha256(convert_to(p_result::text,'UTF8')),'hex')) then
     return jsonb_build_object('status','page_saved','replayed',true);
   end if;
   raise exception 'strategy replay conflict' using errcode='PT409';
 end if;
 page:=public.read_lifetime_memoir_lane_page(p_lane_id,p_token);
 if (page->'two_lane'->>'strategy_mode') is null then
   return public.commit_lifetime_memoir_lane_page_before_strategy(p_lane_id,p_token,p_page_number,p_result,p_page_digest);
 end if;
 if p_page_digest is distinct from page->>'page_digest' then raise exception 'stale strategy plan input' using errcode='PT409';end if;
 proposal:=p_result->'strategy_proposal';
 if page->'two_lane'->>'work_mode'='reply_only' and proposal='null'::jsonb then
   result:=public.commit_lifetime_memoir_lane_page_before_strategy(p_lane_id,p_token,p_page_number,p_result-'strategy_proposal',p_page_digest);
   insert into public.user_lifetime_strategy_page_receipt values(snap.id,p_page_number,p_page_digest,encode(sha256(convert_to(p_result::text,'UTF8')),'hex'));
   return result;
 end if;
 if jsonb_typeof(proposal) is distinct from 'object' or exists(select 1 from jsonb_object_keys(proposal) k where k not in ('strategy','objective','focus_event_ids'))
   or coalesce(proposal->>'strategy','') not in ('comfort','explore','shape')
   or coalesce(proposal->>'objective','') not in ('gentle_entry','follow_story','clarify_order','clarify_identity','link_stories')
   or jsonb_typeof(proposal->'focus_event_ids') is distinct from 'array' or jsonb_array_length(proposal->'focus_event_ids')>8
   or (proposal->>'strategy'='shape' and proposal->>'objective' not in ('clarify_order','clarify_identity','link_stories'))
   or exists(select 1 from jsonb_array_elements(proposal->'focus_event_ids') e where not exists(select 1 from jsonb_array_elements(page->'events') v
     where v->>'id'=e#>>'{}' and v->>'status'='active')) then raise exception 'invalid bounded strategy proposal' using errcode='22023';end if;
 insert into public.user_lifetime_strategy_frontier(user_id,project_id) values(snap.user_id,snap.project_id) on conflict do nothing;
 select revision into current_revision from public.user_lifetime_strategy_frontier where user_id=snap.user_id and project_id=snap.project_id for update;
 if current_revision is distinct from (page->'two_lane'->>'strategy_revision')::bigint then raise exception 'strategy revision changed' using errcode='PT409';end if;
 shadow_mode:=page->'two_lane'->>'strategy_mode'='shadow';
 select max(based_on_sequence) into prior_sequence from public.user_lifetime_interview_strategy where user_id=snap.user_id and project_id=snap.project_id and shadow=shadow_mode;
 if coalesce(prior_sequence,0)>(page->'source'->>'sequence')::bigint then raise exception 'older strategy source' using errcode='PT409';end if;
 result:=public.commit_lifetime_memoir_lane_page_before_strategy(p_lane_id,p_token,p_page_number,p_result-'strategy_proposal',p_page_digest);
 next_revision:=current_revision+1;
 select coalesce(jsonb_agg(q||jsonb_build_object('id','bq-'||encode(sha256(convert_to((page->'source'->>'id')||':'||
   (page->'source'->>'version')||':'||(q->>'question'),'UTF8')),'hex'))),'[]') into candidates from jsonb_array_elements(p_result->'prepared_questions') q;
 select coalesce(jsonb_agg(jsonb_build_object('id',e.id,'revision',e.revision)),'[]') into manifest from public.user_memory_event e
   where e.user_id=snap.user_id and e.project_id=snap.project_id and proposal->'focus_event_ids' @> to_jsonb(e.id);
 select checkpoint_id into checkpoint from public.user_lifetime_conversation where user_id=snap.user_id and conversation_id=snap.conversation_id;
 select greatest(0,floor(extract(epoch from clock_timestamp()-created_at)*1000))::bigint into lag from public.user_narrator_source
   where user_id=snap.user_id and project_id=snap.project_id and id=(page->'source'->>'id')::uuid;
 insert into public.user_lifetime_interview_strategy(user_id,project_id,plan_revision,shadow,source_id,source_version,based_on_sequence,
   policy_epoch,preference_revision,execution_generation,phase_revision,event_manifest,data)
 values(snap.user_id,snap.project_id,next_revision,shadow_mode,(page->'source'->>'id')::uuid,(page->'source'->>'version')::bigint,
   (page->'source'->>'sequence')::bigint,snap.policy_epoch,snap.preference_revision,(page->'two_lane'->>'execution_generation')::bigint,
   (page->'two_lane'->>'phase_revision')::bigint,manifest,jsonb_build_object('schema_version',1,'project_id',snap.project_id,
     'plan_revision',next_revision,'based_on_sequence',(page->'source'->>'sequence')::bigint,'source_id',page->'source'->>'id',
     'source_version',(page->'source'->>'version')::bigint,'source_revision',snap.source_high_water,'policy_epoch',snap.policy_epoch,
     'preference_revision',snap.preference_revision,'execution_generation',(page->'two_lane'->>'execution_generation')::bigint,
     'phase_revision',(page->'two_lane'->>'phase_revision')::bigint,'snapshot_id',snap.id,'checkpoint_id',checkpoint,
     'strategy',proposal->>'strategy','objective',proposal->>'objective','focus_event_ids',proposal->'focus_event_ids',
     'candidates',candidates,'background_lag_ms',lag));
 update public.user_lifetime_strategy_frontier set revision=next_revision,
   active_strategy=case when shadow_mode then active_strategy else proposal->>'strategy' end,
   shadow_strategy=case when shadow_mode then proposal->>'strategy' else shadow_strategy end
   where user_id=snap.user_id and project_id=snap.project_id and revision=current_revision;
 if not found then raise exception 'strategy CAS failed' using errcode='PT409';end if;
 insert into public.user_lifetime_strategy_page_receipt values(snap.id,p_page_number,p_page_digest,encode(sha256(convert_to(p_result::text,'UTF8')),'hex'));
 return result;
end $$;
-- The table is resolved when the function executes, after this migration commits.
create table public.user_lifetime_strategy_page_receipt (
 snapshot_id uuid not null references public.user_lifetime_lane_snapshot(id) on delete cascade,page_number bigint not null,
 page_digest text not null,result_digest text not null,primary key(snapshot_id,page_number)
);
alter table public.user_lifetime_strategy_page_receipt enable row level security;
revoke all on public.user_lifetime_strategy_page_receipt from public,anon,authenticated;
revoke all on function public.commit_lifetime_memoir_lane_page(uuid,uuid,bigint,jsonb,text) from public,anon,authenticated;
grant execute on function public.commit_lifetime_memoir_lane_page(uuid,uuid,bigint,jsonb,text) to service_role;

-- The selector's outcome is committed with the canonical reply, never in B.
create function public.commit_lifetime_strategy_turn(p_fence jsonb,p_client_turn_id uuid,p_plan jsonb,p_associations jsonb,
 p_reply text,p_response_photo_ids jsonb,p_thread_id text,p_prompt_version text,p_model text,p_continuity_updates jsonb,p_outcome jsonb)
returns jsonb language plpgsql security definer set search_path=public,auth as $$
declare result jsonb; context jsonb; candidate jsonb; chosen jsonb; accepted public.user_interview_turn%rowtype;
 project text; question text; prior public.user_lifetime_strategy_outcome%rowtype;
begin
 perform public.lock_lifetime_publication(p_fence);
 project:=p_fence->'identity'->>'project_id';
 select * into accepted from public.user_interview_turn where user_id=auth.uid() and project_id=project and client_turn_id=p_client_turn_id;
 if not found then raise exception 'accepted exact source required' using errcode='PT409';end if;
 if jsonb_typeof(p_outcome) is distinct from 'object' or not(p_outcome ?& array['schema_version','plan_revision_seen','selected_candidate_id',
   'selection_reason','used_strategy','question_delivered','work_hint']) or exists(select 1 from jsonb_object_keys(p_outcome) k
     where k not in ('schema_version','plan_revision_seen','selected_candidate_id','selection_reason','used_strategy','question_delivered','work_hint'))
   or p_outcome->>'schema_version'<>'1' or coalesce(p_outcome->>'used_strategy','') not in ('comfort','explore','shape')
   or coalesce(p_outcome->>'selection_reason','') not in ('prepared_candidate','adapted_candidate','latest_story','user_redirect','current_correction',
     'pacing','pause','direct_answer','safe_fallback','stale_plan','no_plan','return_context')
   or p_outcome->>'work_hint' is distinct from p_plan->'work'->>'mode'
   or jsonb_typeof(p_outcome->'question_delivered') not in ('string','null') then raise exception 'invalid immediate outcome' using errcode='22023';end if;
 select q into chosen from jsonb_array_elements(p_plan->'candidates') q where q->>'id'=p_plan->>'chosen_id';
 question:=chosen->>'question';
 if question is distinct from p_outcome->>'question_delivered' or (question is null and p_outcome->>'selection_reason' not in ('pause','direct_answer'))
   or (question is not null and (length(question)>800 or strpos(p_reply,question)=0))
   or jsonb_array_length(p_plan->'candidates')>1 then raise exception 'outcome must match the saved immediate question' using errcode='22023';end if;
 select * into prior from public.user_lifetime_strategy_outcome where user_id=auth.uid() and project_id=project and client_turn_id=p_client_turn_id;
 if found then
   if prior.plan_revision_seen is distinct from (p_outcome->>'plan_revision_seen')::bigint
     or prior.selected_candidate_id is distinct from p_outcome->>'selected_candidate_id'
     or prior.selection_reason is distinct from p_outcome->>'selection_reason' or prior.used_strategy is distinct from p_outcome->>'used_strategy'
     or prior.question_delivered is distinct from question or prior.work_hint is distinct from p_outcome->>'work_hint' then
     raise exception 'saved outcome identity conflict' using errcode='PT409';end if;
 else
   context:=public.read_lifetime_strategy_context((p_fence->'identity'->>'conversation_id')::uuid);
   if context->>'mode'<>'active' then raise exception 'strategy is disabled' using errcode='PT409';end if;
   if coalesce(context->'plan'->>'plan_revision',context->>'invalid_plan_revision') is distinct from p_outcome->>'plan_revision_seen' then
     raise exception 'strategy plan changed' using errcode='PT409';end if;
   if p_outcome->>'selected_candidate_id' is not null then
     select q into candidate from jsonb_array_elements(context->'plan'->'candidates') q where q->>'id'=p_outcome->>'selected_candidate_id';
     if candidate is null or p_outcome->>'selection_reason' not in ('prepared_candidate','adapted_candidate') then
       raise exception 'candidate unavailable' using errcode='PT409';end if;
     if p_outcome->>'selection_reason'='prepared_candidate' and candidate->>'question' is distinct from question then
       raise exception 'prepared candidate text changed' using errcode='22023';end if;
   elsif p_outcome->>'selection_reason' in ('prepared_candidate','adapted_candidate') then raise exception 'candidate identity required' using errcode='22023';end if;
 end if;
 result:=public.commit_lifetime_turn(p_fence,p_client_turn_id,p_plan,p_associations,p_reply,p_response_photo_ids,p_thread_id,p_prompt_version,p_model,p_continuity_updates);
 insert into public.user_lifetime_strategy_outcome(user_id,project_id,client_turn_id,reply_id,source_id,source_sequence,
   plan_revision_seen,selected_candidate_id,selection_reason,used_strategy,question_delivered,work_hint)
 values(auth.uid(),project,p_client_turn_id,(result->'memory'->0->>'id')::uuid,accepted.source_id,
   (select sequence from public.user_narrator_source where user_id=auth.uid() and project_id=project and id=accepted.source_id),
   (p_outcome->>'plan_revision_seen')::bigint,p_outcome->>'selected_candidate_id',p_outcome->>'selection_reason',p_outcome->>'used_strategy',question,p_outcome->>'work_hint')
 on conflict do nothing;
 return result||jsonb_build_object('strategy_metrics',jsonb_build_object('repeated_question_count',
   (select count(*) from public.user_lifetime_strategy_outcome o where o.user_id=auth.uid() and o.project_id=project
     and o.delivered and o.client_turn_id<>p_client_turn_id and lower(btrim(o.question_delivered))=lower(btrim(question))),
   'previous_delivered_question_count',(select count(*) from public.user_lifetime_strategy_outcome o
     where o.user_id=auth.uid() and o.project_id=project and o.delivered and o.client_turn_id<>p_client_turn_id and o.question_delivered is not null)));
end $$;
create function public.commit_lifetime_strategy_delivery(p_fence jsonb,p_client_turn_id uuid,p_reply_id uuid) returns boolean
language plpgsql security definer set search_path=public,auth as $$
begin
 perform public.lock_lifetime_publication(p_fence);
 update public.user_lifetime_strategy_outcome o set delivered=true where o.user_id=auth.uid()
   and o.project_id=p_fence->'identity'->>'project_id' and o.client_turn_id=p_client_turn_id and o.reply_id=p_reply_id
   and exists(select 1 from public.user_lifetime_reply r where r.user_id=o.user_id and r.client_turn_id=o.client_turn_id
     and r.memory_id=o.reply_id and r.conversation_id=(p_fence->'identity'->>'conversation_id')::uuid
     and r.policy_epoch=(p_fence->>'policy_epoch')::bigint and r.execution_generation=(p_fence->>'execution_generation')::bigint);
 return found;
end $$;
revoke all on function public.commit_lifetime_strategy_turn(jsonb,uuid,jsonb,jsonb,text,jsonb,text,text,text,jsonb,jsonb),
 public.commit_lifetime_strategy_delivery(jsonb,uuid,uuid) from public,anon;
grant execute on function public.commit_lifetime_strategy_turn(jsonb,uuid,jsonb,jsonb,text,jsonb,text,text,text,jsonb,jsonb),
 public.commit_lifetime_strategy_delivery(jsonb,uuid,uuid) to authenticated;

-- Private derived bytes follow the canonical policy/source invalidation. Keep
-- only the safe enum hint so a correction does not restart the journey.
create function public.purge_lifetime_strategy_projections() returns trigger
language plpgsql security definer set search_path=public,auth as $$
begin
 if old.policy_epoch is distinct from new.policy_epoch then
   delete from public.user_lifetime_interview_strategy where user_id=new.user_id and project_id=new.project_id;
   update public.user_lifetime_strategy_outcome set question_delivered=null,selected_candidate_id=null
     where user_id=new.user_id and project_id=new.project_id;
   update public.user_lifetime_strategy_frontier set revision=revision+1 where user_id=new.user_id and project_id=new.project_id;
 end if;
 return new;
end $$;
create trigger lifetime_strategy_invalidation after update of policy_epoch on public.user_memoir_project
 for each row execute function public.purge_lifetime_strategy_projections();
revoke all on function public.purge_lifetime_strategy_projections() from public,anon,authenticated,service_role;
notify pgrst,'reload schema';
commit;
