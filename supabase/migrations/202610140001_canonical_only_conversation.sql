-- Development decision: the canonical engine is the sole conversation path.
-- This retires the old rollout interlock; it does not attest provider call termination.
-- Direct realtime and ungoverned worker admission remain permanently denied.
begin;

create or replace function public.lock_lifetime_realtime_admission() returns void
language plpgsql security definer set search_path='' as $$
begin
 raise exception 'direct realtime conversation has been retired' using errcode='42501';
end $$;
revoke all on function public.lock_lifetime_realtime_admission() from public,anon,authenticated,service_role;

create or replace function public.lock_lifetime_legacy_worker_admission() returns boolean
language plpgsql security definer set search_path='' as $$
begin
 raise exception 'canonical execution required' using errcode='42501';
end $$;
revoke all on function public.lock_lifetime_legacy_worker_admission() from public,anon,authenticated,service_role;

create or replace function public.lock_lifetime_provider_activation() returns void
language plpgsql security definer set search_path='' as $$
begin
 if auth.uid() is null or not exists(select 1 from auth.users where id=auth.uid()) then
   raise exception 'authenticated owner required' using errcode='42501';
 end if;
end $$;
revoke all on function public.lock_lifetime_provider_activation() from public,anon,service_role;
grant execute on function public.lock_lifetime_provider_activation() to authenticated;

create or replace function public.read_lifetime_admission(p_project_id text default null)
returns text language plpgsql stable security definer set search_path='' as $$
begin
 if auth.uid() is null or not exists(select 1 from auth.users where id=auth.uid()) then
   raise exception 'authenticated owner required' using errcode='42501';
 end if;
 return 'governed';
end $$;

create or replace function public.pending_lifetime_collection_jobs(p_limit integer default 8,p_include_outline boolean default true)
returns jsonb language plpgsql security definer set search_path='' as $$
begin
 if p_limit is null or p_limit not between 1 and 32 then raise exception 'invalid job limit';end if;
 return coalesce((select jsonb_agg(id order by created_at) from (
  select j.id,j.created_at from public.user_lifetime_collection_job j
  where (j.state='QUEUED' or j.state='RUNNING' and j.lease_until<=clock_timestamp())
   and (j.kind<>'BuildOutline' or p_include_outline is true)
   and not exists(select 1 from public.user_lifetime_pending_policy p where p.user_id=j.user_id and p.project_id=j.project_id)
   and not exists(select 1 from public.user_lifetime_policy_inventory_pending p where p.user_id=j.user_id and p.project_id=j.project_id)
  order by j.created_at limit p_limit) ready),'[]'::jsonb);
end $$;
revoke all on function public.pending_lifetime_collection_jobs(integer,boolean) from public,anon,authenticated;
grant execute on function public.pending_lifetime_collection_jobs(integer,boolean) to service_role;

drop trigger lifetime_identity_requires_realtime_clearance on public.user_lifetime_conversation;
drop function public.guard_lifetime_identity_adoption();
drop function public.require_lifetime_canonical_clearance();
drop function public.pending_lifetime_collection_jobs_before_clearance(integer,boolean);
drop function public.begin_lifetime_realtime_drain(bigint);
drop function public.attest_lifetime_realtime_clearance(bigint,text);
drop table public.lifetime_realtime_clearance;
drop function public.enforce_lifetime_realtime_clearance_transition();

notify pgrst, 'reload schema';
commit;
