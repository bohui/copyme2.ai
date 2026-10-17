-- Show the embedded place evaluation alongside its shared timeline model pass.
begin;

alter function public.record_lifetime_skill_phase(jsonb,text,text,uuid)
  rename to record_lifetime_skill_phase_before_place_progress;
revoke all on function public.record_lifetime_skill_phase_before_place_progress(jsonb,text,text,uuid)
  from public,anon,authenticated,service_role;

create function public.record_lifetime_skill_phase(
  p_fence jsonb,p_phase text,p_status text,p_invocation_id uuid) returns void
language plpgsql security definer set search_path='' as $$
declare page jsonb;
begin
  perform public.record_lifetime_skill_phase_before_place_progress(
    p_fence,p_phase,p_status,p_invocation_id);
  if p_phase='extract' and p_status='running' then
    page:=public.read_lifetime_memoir_lane_page(
      (p_fence->>'lane_id')::uuid,(p_fence->>'token')::uuid);
    if page ? 'two_lane' and page->'two_lane'->>'work_mode'='extract' then
      perform public.background_skill_receipt(
        page,'place','memoir-place-journey','embedded','running');
    end if;
  end if;
end $$;
revoke all on function public.record_lifetime_skill_phase(jsonb,text,text,uuid)
  from public,anon,authenticated;
grant execute on function public.record_lifetime_skill_phase(jsonb,text,text,uuid)
  to service_role;

alter function public.commit_lifetime_memoir_lane_page(uuid,uuid,bigint,jsonb,text)
  rename to commit_lifetime_memoir_lane_page_before_place_progress;
revoke all on function public.commit_lifetime_memoir_lane_page_before_place_progress(uuid,uuid,bigint,jsonb,text)
  from public,anon,authenticated,service_role;

create function public.commit_lifetime_memoir_lane_page(
  p_lane_id uuid,p_token uuid,p_page_number bigint,p_result jsonb,p_page_digest text)
returns jsonb language plpgsql security definer set search_path='' as $$
declare page jsonb; result jsonb;
begin
  page:=public.read_lifetime_memoir_lane_page(p_lane_id,p_token);
  result:=public.commit_lifetime_memoir_lane_page_before_place_progress(
    p_lane_id,p_token,p_page_number,p_result,p_page_digest);
  if result->>'status'='page_saved' and result->>'replayed' is distinct from 'true'
      and page->>'skill'='timeline' and page ? 'two_lane'
      and page->'two_lane'->>'work_mode'='extract'
      and jsonb_array_length(coalesce(p_result->'place_journeys','[]'::jsonb))=0 then
    perform public.background_skill_receipt(
      page,'place','memoir-place-journey','embedded','skipped','no_place_cue');
  end if;
  return result;
end $$;
revoke all on function public.commit_lifetime_memoir_lane_page(uuid,uuid,bigint,jsonb,text)
  from public,anon,authenticated;
grant execute on function public.commit_lifetime_memoir_lane_page(uuid,uuid,bigint,jsonb,text)
  to service_role;

notify pgrst,'reload schema';
commit;
