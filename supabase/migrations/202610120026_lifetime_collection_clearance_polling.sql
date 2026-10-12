-- Keep deterministic selected exports schedulable while model work waits for
-- explicit operator clearance. Actual provider admission still checks its lock.
begin;
alter function public.pending_lifetime_collection_jobs(integer,boolean)
 rename to pending_lifetime_collection_jobs_before_clearance;
revoke all on function public.pending_lifetime_collection_jobs_before_clearance(integer,boolean)
 from public,anon,authenticated,service_role;

create function public.pending_lifetime_collection_jobs(p_limit integer default 8,p_include_outline boolean default true)
returns jsonb language sql security definer set search_path='' as $$
 select public.pending_lifetime_collection_jobs_before_clearance(p_limit,
  p_include_outline is true and exists(select 1 from public.lifetime_realtime_clearance
   where singleton and stage='canonical_ready'));
$$;
revoke all on function public.pending_lifetime_collection_jobs(integer,boolean)
 from public,anon,authenticated;
grant execute on function public.pending_lifetime_collection_jobs(integer,boolean) to service_role;
commit;
