-- Required metadata remains processable after the last visit/token expiration.
-- Existing service-role worker only; no model, new credentials or deployment.
begin;
create function public.drain_lifetime_memory_obligations(p_limit integer default 4)
returns jsonb language plpgsql security definer set search_path=public,auth as $$
declare candidate record; token uuid; fence jsonb; claimed jsonb;
 processed integer:=0; failed integer:=0; busy integer:=0;
 previous_owner text:=current_setting('request.jwt.claim.sub',true);
 previous_timeout text:=current_setting('lock_timeout');
begin
 if p_limit is null or p_limit not between 1 and 32 then raise exception 'invalid maintenance limit';end if;
 perform set_config('lock_timeout','250ms',true);
 for candidate in select o.user_id,o.conversation_id,o.project_id from public.user_lifetime_memory_obligation o
   join public.user_lifetime_conversation l on l.user_id=o.user_id and l.conversation_id=o.conversation_id and l.project_id=o.project_id
   where (o.status in ('pending','retryable') and o.next_attempt_at<=clock_timestamp())
      or (o.status='running' and o.claim_expires_at<=clock_timestamp())
   order by o.created_at,o.id limit p_limit
 loop
  begin
   -- Match foreground lock order before acquiring its short exclusive lease.
   perform 1 from public.user_memoir_project where user_id=candidate.user_id and project_id=candidate.project_id for update nowait;
   if not found then continue;end if;
   perform set_config('request.jwt.claim.sub',candidate.user_id::text,true);
   insert into public.user_profile(user_id,profile) values(candidate.user_id,'{}') on conflict do nothing;
   perform 1 from public.user_profile where user_id=candidate.user_id for update nowait;
   token:=gen_random_uuid();
   if not public.acquire_user_agent_turn_lease(token,30) then
    raise exception 'foreground lease busy' using errcode='55P03';
   end if;
   fence:=public.capture_lifetime_fence(candidate.conversation_id,token);
   claimed:=public.claim_lifetime_memory_obligation(fence);
   if claimed->>'status'='running' then
    begin
     perform public.complete_lifetime_memory_obligation(fence,(claimed->>'id')::uuid,(claimed->>'claim_token')::uuid);
     processed:=processed+1;
    exception when others then
     perform public.fail_lifetime_memory_obligation(fence,(claimed->>'id')::uuid,(claimed->>'claim_token')::uuid,'projection_failed');
     failed:=failed+1;
    end;
   end if;
   perform public.release_user_agent_turn_lease(token);
  exception when lock_not_available then
   busy:=busy+1;
  end;
 end loop;
 perform set_config('request.jwt.claim.sub',coalesce(previous_owner,''),true);
 perform set_config('lock_timeout',previous_timeout,true);
 return jsonb_build_object('processed',processed,'failed',failed,'busy',busy);
exception when others then
 perform set_config('request.jwt.claim.sub',coalesce(previous_owner,''),true);
 perform set_config('lock_timeout',previous_timeout,true);
 raise;
end $$;
revoke all on function public.drain_lifetime_memory_obligations(integer) from public,anon,authenticated;
grant execute on function public.drain_lifetime_memory_obligations(integer) to service_role;
commit;
