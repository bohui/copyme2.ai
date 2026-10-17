-- Reconstruct only completed embedded evaluations that predate progress capture.
begin;

insert into public.user_background_skill_work (
  user_id,project_id,id,lane_id,snapshot_id,page_digest,phase,skill,execution,
  source_id,source_version,client_turn_id,coverage_start,coverage_end,
  status,model_invoked,model_attempts,reason,updated_at)
select t.user_id,t.project_id,md5(t.id||':place'),t.lane_id,t.snapshot_id,
  t.page_digest,'place','memoir-place-journey','embedded',t.source_id,
  t.source_version,t.client_turn_id,t.coverage_start,t.coverage_end,
  case when p.source_id is null then 'skipped' else 'saved' end,
  false,0,case when p.source_id is null then 'no_place_cue' end,t.updated_at
from public.user_background_skill_work t
join public.user_lifetime_two_lane_source s on s.user_id=t.user_id
  and s.project_id=t.project_id and s.source_id=t.source_id
left join public.user_lifetime_place_journey p on p.user_id=t.user_id
  and p.project_id=t.project_id and p.source_id=t.source_id
  and p.source_version=t.source_version
  and jsonb_array_length(p.journeys)>0
where t.skill='memoir-author-timeline' and t.phase='extract'
  and t.status='saved' and t.source_id is not null
  and not exists (
    select 1 from public.user_background_skill_work prior
    where prior.user_id=t.user_id and prior.project_id=t.project_id
      and prior.skill='memoir-place-journey' and prior.source_id=t.source_id
      and prior.source_version=t.source_version)
on conflict(user_id,project_id,id) do nothing;

commit;
