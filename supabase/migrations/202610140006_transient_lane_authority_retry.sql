-- A brief foreground/publication lock must not postpone background work five minutes.
begin;
create or replace function public.defer_lifetime_memoir_lane(p_lane_id uuid,p_token uuid,p_reason text) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
begin
 perform public.lock_lifetime_memoir_lane(p_lane_id,p_token);
 if p_reason not in ('LIFETIME_PRIVACY_MAINTENANCE_REQUIRED','LIFETIME_MODEL_BUDGET_REQUIRED',
   'LIFETIME_GENERATION_PAUSED','LIFETIME_PROVIDER_AUTHORITY_UNAVAILABLE') then
   raise exception 'invalid lane maintenance reason';end if;
 update public.user_memoir_lane set token=null,lease_until=null,run_deadline=null,pending=true,attempts=0,error=p_reason,
   available_at=clock_timestamp()+case when p_reason='LIFETIME_PROVIDER_AUTHORITY_UNAVAILABLE'
     then interval '15 seconds' else interval '5 minutes' end where id=p_lane_id;
 return jsonb_build_object('status','pending','error',p_reason,'retrieval_complete',false);
end $$;
revoke all on function public.defer_lifetime_memoir_lane(uuid,uuid,text) from public,anon,authenticated;
grant execute on function public.defer_lifetime_memoir_lane(uuid,uuid,text) to service_role;
update public.user_memoir_lane set available_at=least(available_at,clock_timestamp()+interval '15 seconds')
 where pending and token is null and error='LIFETIME_PROVIDER_AUTHORITY_UNAVAILABLE';
notify pgrst,'reload schema';
commit;
