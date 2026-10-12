-- Policy completeness is a metadata wait, never a failed selected-source run.
begin;
create function public.defer_lifetime_collection_job_policy(p_job_id uuid,p_token uuid,p_user_id uuid)
returns boolean language plpgsql security definer set search_path='' as $$
declare job public.user_lifetime_collection_job%rowtype; conversation uuid;
begin
 if p_user_id is null or p_token is null then
  raise exception 'collection claim required' using errcode='42501';end if;
 -- Keep account/project/identity/job order, but do not read source content or
 -- invoke the policy-ready guard that intentionally blocked this worker.
 perform 1 from auth.users where id=p_user_id for share;
 if not found then raise exception 'collection owner unavailable' using errcode='42501';end if;
 select * into job from public.user_lifetime_collection_job where id=p_job_id and user_id=p_user_id;
 if not found then raise exception 'collection claim unavailable' using errcode='42501';end if;
 perform 1 from public.user_memoir_project where user_id=job.user_id and project_id=job.project_id for share;
 if not found then raise exception 'collection project unavailable' using errcode='42501';end if;
 select conversation_id into conversation from public.user_lifetime_conversation
  where user_id=job.user_id and project_id=job.project_id for share;
 if not found then raise exception 'collection identity unavailable' using errcode='42501';end if;
 select * into job from public.user_lifetime_collection_job where id=p_job_id and user_id=p_user_id for update;
 if not found or job.conversation_id is distinct from conversation or job.state<>'RUNNING'
  or job.token is distinct from p_token or job.lease_until is null or job.lease_until<=clock_timestamp() then
  raise exception 'stale collection claim' using errcode='40001';end if;
 update public.user_lifetime_collection_job set state='QUEUED',token=null,lease_until=null,
  attempts=0,error='LIFETIME_POLICY_PENDING' where id=job.id;
 return true;
end $$;
revoke all on function public.defer_lifetime_collection_job_policy(uuid,uuid,uuid) from public,anon,authenticated;
grant execute on function public.defer_lifetime_collection_job_policy(uuid,uuid,uuid) to service_role;

-- Eligibility must be applied before LIMIT: filtering the old bounded result
-- would let pending owners occupy every slot and starve unrelated ready work.
-- Preserve SQL020 state/order/limit and SQL026 positive clearance semantics.
create or replace function public.pending_lifetime_collection_jobs(p_limit integer default 8,p_include_outline boolean default true)
returns jsonb language plpgsql security definer set search_path='' as $$
begin
 if p_limit is null or p_limit not between 1 and 32 then raise exception 'invalid job limit';end if;
 return coalesce((select jsonb_agg(id order by created_at) from (
  select j.id,j.created_at from public.user_lifetime_collection_job j
  where (j.state='QUEUED' or j.state='RUNNING' and j.lease_until<=clock_timestamp())
   and (j.kind<>'BuildOutline' or p_include_outline is true and exists(
    select 1 from public.lifetime_realtime_clearance where singleton and stage='canonical_ready'))
   and not exists(select 1 from public.user_lifetime_pending_policy p where p.user_id=j.user_id and p.project_id=j.project_id)
   and not exists(select 1 from public.user_lifetime_policy_inventory_pending p where p.user_id=j.user_id and p.project_id=j.project_id)
  order by j.created_at limit p_limit) ready),'[]'::jsonb);
end $$;
revoke all on function public.pending_lifetime_collection_jobs(integer,boolean) from public,anon,authenticated;
grant execute on function public.pending_lifetime_collection_jobs(integer,boolean) to service_role;
commit;
