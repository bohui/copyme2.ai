-- Canonicalise the two background skill identifiers that predate the memoir-
-- namespaced skill convention. Existing progress rows remain equivalent; only
-- their stable display identifier is updated.
begin;

update public.user_background_skill_work
set skill = case skill
  when 'historical-news-research' then 'memoir-historical-news-research'
  when 'place-photo-research' then 'memoir-place-photo-research'
  else skill
end
where skill in ('historical-news-research','place-photo-research');

create or replace function public.record_background_service_work(p_user_id uuid,p_project_id text,p_step jsonb) returns void
language plpgsql security definer set search_path='' as $$
declare source public.user_narrator_source%rowtype;
begin
 if p_step->>'skill' not in ('memoir-place-groups','memoir-place-photo-research','memoir-historical-news-research')
   or p_step->>'status' not in ('running','completed','saved','failed','cached')
   or p_step->>'execution' not in ('deterministic','provider','cache')
   or p_step->>'id' !~ '^[a-f0-9]{64}$' then raise exception 'invalid service receipt' using errcode='22023';end if;
 if p_step->>'skill'='memoir-historical-news-research' then
   select s.* into source from public.user_historical_news_job j join public.user_narrator_source s
     on s.user_id=j.user_id and s.project_id=j.project_id and s.sequence=j.source_sequence
   where j.user_id=p_user_id and j.project_id=p_project_id and j.id=(p_step->>'research_job_id')::uuid and s.status='active';
   if not found then raise exception 'owned research claim required' using errcode='42501';end if;
 elsif p_step->>'client_turn_id' is not null then
   select * into source from public.user_narrator_source where user_id=p_user_id and project_id=p_project_id
     and client_turn_id=(p_step->>'client_turn_id')::uuid and status='active';
   if not found then raise exception 'owned turn reference required' using errcode='42501';end if;
 end if;
 insert into public.user_background_skill_work(user_id,project_id,id,phase,skill,execution,coverage_start,coverage_end,status,
   client_turn_id,source_id,source_version,model_invoked,model_attempts)
 values(p_user_id,p_project_id,p_step->>'id',p_step->>'phase',p_step->>'skill',p_step->>'execution',coalesce(source.sequence,0),coalesce(source.sequence,0),p_step->>'status',
   source.client_turn_id,source.id,source.version,(p_step->>'model_invoked')::boolean,
   case when p_step->>'model_invoked'='false' then 0 else null end)
 on conflict(user_id,project_id,id) do update set status=excluded.status,execution=excluded.execution,
   model_invoked=excluded.model_invoked,model_attempts=excluded.model_attempts,updated_at=clock_timestamp();
end $$;
revoke all on function public.record_background_service_work(uuid,text,jsonb) from public,anon,authenticated;
grant execute on function public.record_background_service_work(uuid,text,jsonb) to service_role;

commit;
