-- Incomplete source policy blocks content authority, not metadata-only release.
-- No policy receipt, checkpoint, source, manuscript or outbox ACK is changed.
begin;
create function public.defer_lifetime_memoir_lane_policy(p_lane_id uuid,p_token uuid,
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
   error='LIFETIME_POLICY_PENDING',available_at=clock_timestamp()+interval '5 minutes' where id=p_lane_id;
 return jsonb_build_object('status','pending','error','LIFETIME_POLICY_PENDING','retrieval_complete',false);
end $$;
revoke all on function public.defer_lifetime_memoir_lane_policy(uuid,uuid,uuid,text,uuid) from public,anon,authenticated;
grant execute on function public.defer_lifetime_memoir_lane_policy(uuid,uuid,uuid,text,uuid) to service_role;

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
