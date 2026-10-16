-- Repair the strategy layer while preserving the outer semantic-page guard.
begin;
create or replace function public.commit_lifetime_memoir_lane_page_before_semantic(p_lane_id uuid,p_token uuid,p_page_number bigint,p_result jsonb,p_page_digest text)
returns jsonb language plpgsql security definer set search_path=public,auth as $$
declare snap public.user_lifetime_lane_snapshot%rowtype; page jsonb; result jsonb; proposal jsonb; shadow_mode boolean;
 current_revision bigint; prior_sequence bigint; next_revision bigint; candidates jsonb; manifest jsonb; checkpoint uuid; lag bigint;
begin
 -- Disabled planning adds no repeated canonical page read/lock to ordinary
 -- composer work. Strategy receipts still take the full guarded replay path.
 if not (p_result ? 'strategy_proposal') and not exists(select 1 from public.lifetime_two_lane_rollout
   where singleton and enabled and strategy_enabled) then
   return public.commit_lifetime_memoir_lane_page_before_strategy(p_lane_id,p_token,p_page_number,p_result,p_page_digest);
 end if;
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
 -- A correction in this same transaction purges old-policy plans and advances
 -- their frontier. Keep the correction, but never publish its stale proposal.
 if exists(select 1 from public.user_memoir_project where user_id=snap.user_id and project_id=snap.project_id
   and policy_epoch is distinct from snap.policy_epoch) then
   insert into public.user_lifetime_strategy_page_receipt values(snap.id,p_page_number,p_page_digest,
     encode(sha256(convert_to(p_result::text,'UTF8')),'hex'));
   return result||jsonb_build_object('policy_changed',true);
 end if;
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
revoke all on function public.commit_lifetime_memoir_lane_page_before_semantic(uuid,uuid,bigint,jsonb,text) from public,anon,authenticated,service_role;
-- Lease release is metadata-only even after the correction invalidates its body.
create function public.yield_lifetime_memoir_lane_metadata(p_lane_id uuid,p_token uuid,
 p_user_id uuid,p_project_id text,p_conversation_id uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare lane public.user_memoir_lane%rowtype;
begin
 select * into lane from public.user_memoir_lane
   where id=p_lane_id and user_id=p_user_id and project_id=p_project_id;
 if not found then raise exception 'canonical lane metadata authority unavailable' using errcode='42501';end if;
 perform 1 from public.user_memoir_project where user_id=p_user_id and project_id=p_project_id for update;
 if not found then raise exception 'canonical lane metadata authority unavailable' using errcode='42501';end if;
 perform 1 from public.user_profile where user_id=p_user_id for share;
 perform 1 from public.user_lifetime_conversation where user_id=p_user_id and project_id=p_project_id
   and conversation_id=p_conversation_id for share;
 if not found then raise exception 'canonical lane metadata authority unavailable' using errcode='42501';end if;
 select * into lane from public.user_memoir_lane where id=p_lane_id for update;
 if lane.id is null or lane.user_id is distinct from p_user_id or lane.project_id is distinct from p_project_id
   or lane.token is null or lane.token is distinct from p_token or lane.lease_until is null or lane.run_deadline is null
   or lane.lease_until<=clock_timestamp() or lane.run_deadline<=clock_timestamp() then
   raise exception 'stale canonical lane metadata lease' using errcode='40001';end if;
 -- The page may already be stale and its contents remain inaccessible. This
 -- current owner/token can only relinquish its own lease and request a retry.
 update public.user_memoir_lane set token=null,lease_until=null,run_deadline=null,pending=true,attempts=0,
   error=null,available_at=clock_timestamp() where id=p_lane_id;
 return jsonb_build_object('status','pending','retrieval_complete',false);
end $$;
revoke all on function public.yield_lifetime_memoir_lane_metadata(uuid,uuid,uuid,text,uuid) from public,anon,authenticated;
grant execute on function public.yield_lifetime_memoir_lane_metadata(uuid,uuid,uuid,text,uuid) to service_role;

-- Exclude blocked owners BEFORE the bounded selection. Required work remains
-- pending; one unreviewed historical inventory cannot starve another tenant.
create or replace function public.pending_memoir_lanes(p_limit integer default 50) returns jsonb
language sql security definer set search_path='' as $$
 select coalesce(jsonb_agg(id),'[]'::jsonb) from (
   select l.id from public.user_memoir_lane l where l.attempts<3 and l.available_at<=clock_timestamp()
     and (l.pending or (l.token is not null and (l.lease_until<=clock_timestamp() or l.run_deadline<=clock_timestamp())))
     and not exists(select 1 from public.user_lifetime_pending_policy p where p.user_id=l.user_id and p.project_id=l.project_id)
     and not exists(select 1 from public.user_lifetime_policy_inventory_pending p where p.user_id=l.user_id and p.project_id=l.project_id)
   order by l.available_at,l.id limit least(greatest(p_limit,1),100)) ready;
$$;
revoke all on function public.pending_memoir_lanes(integer) from public,anon,authenticated;
grant execute on function public.pending_memoir_lanes(integer) to service_role;

create or replace function public.pending_memoir_receipts(p_limit integer default 50) returns jsonb
language sql security definer set search_path='' as $$
 select coalesce(jsonb_agg(id),'[]'::jsonb) from (
   select r.id from public.user_private_draft_outbox r where not r.delivered
     and not exists(select 1 from public.user_lifetime_pending_policy p where p.user_id=r.user_id and p.project_id=r.project_id)
     and not exists(select 1 from public.user_lifetime_policy_inventory_pending p where p.user_id=r.user_id and p.project_id=r.project_id)
   order by r.created_at,r.id limit least(greatest(p_limit,1),100)) ready;
$$;
revoke all on function public.pending_memoir_receipts(integer) from public,anon,authenticated;
grant execute on function public.pending_memoir_receipts(integer) to service_role;
commit;
