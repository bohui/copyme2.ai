-- Revision work may run between cadence checkpoints. Its source cursor must
-- not consume the next five completed exchanges' message summary.
begin;
alter table public.user_lifetime_lane_snapshot add column summary_source bigint not null default 0,
  add column summary_offset integer not null default 0;
create or replace function public.read_lifetime_memoir_lane_page(p_lane_id uuid,p_token uuid) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare page jsonb; snap public.user_lifetime_lane_snapshot%rowtype;
  predecessor public.user_lifetime_lane_snapshot%rowtype; summary_after bigint;
  starting_source bigint; messages jsonb:='[]'; source public.user_narrator_source%rowtype;
  lo integer; hi integer;
begin
  page:=public.read_lifetime_memoir_lane_page_before_summary_windows(p_lane_id,p_token);
  if not (page ? 'batch') then return page;end if;
  select * into snap from public.user_lifetime_lane_snapshot where id=(page->>'snapshot_id')::uuid;
  select * into predecessor from public.user_lifetime_lane_snapshot where id=snap.predecessor;
  summary_after:=greatest(coalesce(predecessor.milestone,0),snap.milestone-5);
  select coalesce(max(s.sequence),0) into starting_source from public.user_completed_round r
    join public.user_narrator_source s on s.user_id=r.user_id and s.project_id=r.project_id and s.client_turn_id=r.turn_id
    where r.user_id=snap.user_id and r.project_id=snap.project_id and r.ordinal<=summary_after;
  if snap.summary_source=0 and snap.summary_offset=0 then
    update public.user_lifetime_lane_snapshot set summary_source=starting_source,summary_offset=100000
      where id=snap.id returning * into snap;
  end if;
  if snap.milestone>summary_after then
    for source in select s.* from public.user_completed_round r join public.user_narrator_source s
      on s.user_id=r.user_id and s.project_id=r.project_id and s.client_turn_id=r.turn_id
      where r.user_id=snap.user_id and r.project_id=snap.project_id and r.ordinal>summary_after
        and r.ordinal<=snap.milestone and s.sequence<=snap.source_high_water and s.status='active'
        and (s.sequence>snap.summary_source or s.sequence=snap.summary_source and snap.summary_offset<length(s.text))
      order by r.ordinal limit 5 loop
      lo:=case when source.sequence=snap.summary_source then snap.summary_offset else 0 end;
      hi:=least(lo+2000,length(source.text));
      if hi>lo then
        messages:=messages||jsonb_build_array(public.lifetime_composer_source(snap.user_id,snap.project_id,
          source.id,source.version,lo,hi));
      end if;
      if hi<length(source.text) then exit;end if;
    end loop;
  end if;
  -- Writing revisions and message summaries advance independently.
  page:=jsonb_set(jsonb_set(page,'{batch,new_messages}',messages),'{batch,starting_after}',to_jsonb(starting_source));
  page:=jsonb_set(page,'{complete}',to_jsonb((page->>'complete')::boolean and jsonb_array_length(messages)=0));
  if page->'source'='null'::jsonb and jsonb_array_length(messages)>0 then
    page:=jsonb_set(page,'{source}',messages->0);
  end if;
  if octet_length((page->'batch')::text)>45000 then
    raise exception 'progressive batch resource budget exceeded' using errcode='22023';
  end if;
  page:=page-'input_digest'-'page_digest';
  page:=page||jsonb_build_object('input_digest',encode(sha256(convert_to((page-'token')::text,'UTF8')),'hex'));
  return page||jsonb_build_object('page_digest',encode(sha256(convert_to(page::text,'UTF8')),'hex'));
end $$;
revoke all on function public.read_lifetime_memoir_lane_page(uuid,uuid) from public,anon,authenticated;
grant execute on function public.read_lifetime_memoir_lane_page(uuid,uuid) to service_role;

alter function public.commit_lifetime_memoir_lane_page(uuid,uuid,bigint,jsonb,text)
  rename to commit_lifetime_memoir_lane_page_before_summary_windows;
revoke all on function public.commit_lifetime_memoir_lane_page_before_summary_windows(uuid,uuid,bigint,jsonb,text)
  from public,anon,authenticated,service_role;
create function public.commit_lifetime_memoir_lane_page(p_lane_id uuid,p_token uuid,p_page_number bigint,p_result jsonb,p_page_digest text)
returns jsonb language plpgsql security definer set search_path=public,auth as $$
declare snap public.user_lifetime_lane_snapshot%rowtype; page jsonb; result jsonb; last_message jsonb;
begin
  snap:=public.lock_lifetime_memoir_lane(p_lane_id,p_token);
  page:=public.read_lifetime_memoir_lane_page(p_lane_id,p_token);
  result:=public.commit_lifetime_memoir_lane_page_before_summary_windows(p_lane_id,p_token,p_page_number,p_result,p_page_digest);
  if p_page_number=snap.page_number and jsonb_array_length(page->'batch'->'new_messages')>0 then
    last_message:=page->'batch'->'new_messages'->-1;
    update public.user_lifetime_lane_snapshot set summary_source=(last_message->>'sequence')::bigint,
      summary_offset=case when last_message->>'char_end'=last_message->>'original_length' then 100000
        else (last_message->>'char_end')::integer end where id=snap.id;
  end if;
  return result;
end $$;
revoke all on function public.commit_lifetime_memoir_lane_page(uuid,uuid,bigint,jsonb,text) from public,anon,authenticated;
grant execute on function public.commit_lifetime_memoir_lane_page(uuid,uuid,bigint,jsonb,text) to service_role;
notify pgrst,'reload schema';
commit;
