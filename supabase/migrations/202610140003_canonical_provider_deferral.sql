-- A temporary provider-authority outage preserves canonical lane checkpoints.
begin;
create or replace function public.defer_lifetime_memoir_lane(p_lane_id uuid,p_token uuid,p_reason text) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
begin
 perform public.lock_lifetime_memoir_lane(p_lane_id,p_token);
 if p_reason not in ('LIFETIME_PRIVACY_MAINTENANCE_REQUIRED','LIFETIME_MODEL_BUDGET_REQUIRED',
   'LIFETIME_GENERATION_PAUSED','LIFETIME_PROVIDER_AUTHORITY_UNAVAILABLE') then
   raise exception 'invalid lane maintenance reason';end if;
 update public.user_memoir_lane set token=null,lease_until=null,run_deadline=null,pending=true,attempts=0,error=p_reason,
   available_at=clock_timestamp()+interval '5 minutes' where id=p_lane_id;
 return jsonb_build_object('status','pending','error',p_reason,'retrieval_complete',false);
end $$;
revoke all on function public.defer_lifetime_memoir_lane(uuid,uuid,text) from public,anon,authenticated;
grant execute on function public.defer_lifetime_memoir_lane(uuid,uuid,text) to service_role;
notify pgrst, 'reload schema';
commit;
