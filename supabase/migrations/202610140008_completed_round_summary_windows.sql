-- Revision work may run between cadence checkpoints. Its source cursor must
-- not consume the next five completed exchanges' message summary.
begin;
alter function public.read_lifetime_memoir_lane_page(uuid,uuid)
  rename to read_lifetime_memoir_lane_page_before_summary_windows;
revoke all on function public.read_lifetime_memoir_lane_page_before_summary_windows(uuid,uuid)
  from public,anon,authenticated,service_role;
create function public.read_lifetime_memoir_lane_page(p_lane_id uuid,p_token uuid) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare page jsonb; snap public.user_lifetime_lane_snapshot%rowtype;
  predecessor public.user_lifetime_lane_snapshot%rowtype; summary_after bigint;
  starting_source bigint; messages jsonb:='[]'; source public.user_narrator_source%rowtype;
begin
  page:=public.read_lifetime_memoir_lane_page_before_summary_windows(p_lane_id,p_token);
  if not (page ? 'batch') then return page;end if;
  select * into snap from public.user_lifetime_lane_snapshot where id=(page->>'snapshot_id')::uuid;
  select * into predecessor from public.user_lifetime_lane_snapshot where id=snap.predecessor;
  summary_after:=greatest(coalesce(predecessor.milestone,0),snap.milestone-5);
  select coalesce(max(s.sequence),0) into starting_source from public.user_completed_round r
    join public.user_narrator_source s on s.user_id=r.user_id and s.project_id=r.project_id and s.client_turn_id=r.turn_id
    where r.user_id=snap.user_id and r.project_id=snap.project_id and r.ordinal<=summary_after;
  if snap.page_number=0 and snap.milestone>summary_after then
    for source in select s.* from public.user_completed_round r join public.user_narrator_source s
      on s.user_id=r.user_id and s.project_id=r.project_id and s.client_turn_id=r.turn_id
      where r.user_id=snap.user_id and r.project_id=snap.project_id and r.ordinal>summary_after
        and r.ordinal<=snap.milestone and s.sequence<=snap.source_high_water and s.status='active'
      order by r.ordinal limit 5 loop
      messages:=messages||jsonb_build_array(public.lifetime_composer_source(snap.user_id,snap.project_id,
        source.id,source.version,0,least(2000,length(source.text))));
    end loop;
  end if;
  -- Keep the original writing/event cursor and completion decision.
  page:=jsonb_set(jsonb_set(page,'{batch,new_messages}',messages),'{batch,starting_after}',to_jsonb(starting_source));
  if octet_length((page->'batch')::text)>45000 then
    raise exception 'progressive batch resource budget exceeded' using errcode='22023';
  end if;
  page:=page-'input_digest'-'page_digest';
  page:=page||jsonb_build_object('input_digest',encode(sha256(convert_to((page-'token')::text,'UTF8')),'hex'));
  return page||jsonb_build_object('page_digest',encode(sha256(convert_to(page::text,'UTF8')),'hex'));
end $$;
revoke all on function public.read_lifetime_memoir_lane_page(uuid,uuid) from public,anon,authenticated;
grant execute on function public.read_lifetime_memoir_lane_page(uuid,uuid) to service_role;
notify pgrst,'reload schema';
commit;
