-- Guest transfer preserves stage evidence but deliberately leaves lifetime
-- identity unmapped. Count its capability-imported replies without adopting it.
begin;

create or replace function public.read_lifetime_stage_readiness(p_project_id text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare result jsonb;
begin
 if auth.uid() is null or not (
   exists(select 1 from public.user_memoir_project where user_id=auth.uid() and project_id=p_project_id)
   or exists(select 1 from public.user_memory where user_id=auth.uid() and project_id=p_project_id)
   or exists(select 1 from public.user_conversation_attachment where user_id=auth.uid() and project_id=p_project_id))
   then raise exception 'owned conversation unavailable' using errcode='42501';end if;
 with transferred_memories as materialized (
   select m.id from public.user_shared_memoir_transfer t
   join public.user_conversation_attachment a on a.id=t.conversation_id and a.user_id=t.user_id and a.project_id=t.project_id
   cross join lateral jsonb_each_text(a.workspace->'memory_id_map') imported
   join public.user_memory m on m.id::text=imported.value and m.user_id=t.user_id and m.project_id=t.project_id
   where t.user_id=auth.uid() and t.project_id=p_project_id
     and public.lifetime_narrator_word_equivalents(m.kind,m.content)>0
 ), saved_sources as materialized (
   select n.* from public.user_narrator_source n
   where n.user_id=auth.uid() and n.project_id=p_project_id and n.status='active'
     and exists(select 1 from public.user_memory m
       where m.user_id=n.user_id and m.project_id=n.project_id and m.client_turn_id=n.client_turn_id
         and (exists(select 1 from public.user_lifetime_reply r where r.user_id=m.user_id and r.memory_id=m.id)
           or exists(select 1 from transferred_memories t where t.id=m.id)))
 ), spans as (
   select n.id,n.text,e.life_stage,s.evidence->>'quote' quote,
     coalesce((s.evidence->>'char_start')::integer,strpos(n.text,s.evidence->>'quote')-1) lo,
     coalesce((s.evidence->>'char_end')::integer,
       coalesce((s.evidence->>'char_start')::integer,strpos(n.text,s.evidence->>'quote')-1)+length(s.evidence->>'quote')) hi,
     s.evidence ? 'char_start' explicit_span
   from saved_sources n join public.user_memory_event_source s
     on s.user_id=n.user_id and s.project_id=n.project_id and s.source_id=n.id and s.source_version=n.version
   join public.user_memory_event e on e.user_id=s.user_id and e.project_id=s.project_id and e.id=s.event_id
   where e.status='active' and e.life_stage<>'unplaced'
     and s.stage_progress_role in ('primary','stage','legacy_primary','legacy_stage')
     and not exists(select 1 from public.user_memory_event_source_exclusion x
       where x.user_id=s.user_id and x.project_id=s.project_id and x.event_id=s.event_id and x.source_id=s.source_id)
 ), merged as (
   select id,life_stage,range_agg(int4range(lo,hi)) ranges from spans
   where lo>=0 and hi>lo and hi<=length(text) and substring(text from lo+1 for hi-lo)=quote
     and (explicit_span or strpos(substring(text from lo+2),quote)=0)
   group by id,life_stage
 ), volumes as (
   select m.life_stage,sum(public.lifetime_narrator_word_equivalents('agent',
     'Storyteller: '||substring(n.text from lower(piece)+1 for upper(piece)-lower(piece))||E'\nMemory Spark: saved')) words
   from merged m join saved_sources n on n.id=m.id cross join lateral unnest(m.ranges) piece group by m.life_stage
   union all
   select v.life_stage,sum(v.word_equivalents) from public.user_lifetime_stage_volume v
   where v.user_id=auth.uid() and v.project_id=p_project_id
     and not exists(select 1 from public.user_lifetime_reply r where r.user_id=v.user_id and r.memory_id=v.memory_id)
     and not exists(select 1 from saved_sources n join spans s on s.id=n.id where n.client_turn_id=v.client_turn_id)
     and not exists(select 1 from public.user_narrator_source n where n.user_id=v.user_id and n.project_id=v.project_id
       and n.client_turn_id=v.client_turn_id and n.status='withdrawn') group by v.life_stage
 ), counts as (
   select stage,coalesce(sum(v.words),0) words
   from unnest(array['baby','toddler','childhood','adolescence','young_adulthood','midlife','later_life']) stage
   left join volumes v on v.life_stage=stage group by stage
 )
 select jsonb_build_object('stages',jsonb_object_agg(stage,jsonb_build_object('word_equivalents',words,
   'percent',round(least(case when words<=300 then words::numeric/10 else 30+least(words-300,700)::numeric*20/700 end,50),1),
   'color',case when words<300 then 'red' when words<1000 then 'amber' else 'green' end)),
   'pending',exists(select 1 from saved_sources where processing_status<>'succeeded')) into result from counts;
 return result || jsonb_build_object('project_id',p_project_id,'heuristic','narrator_context_volume_v1',
   'maximum_percent',50,'complete',true);
end $$;
revoke all on function public.read_lifetime_stage_readiness(text) from public,anon;
grant execute on function public.read_lifetime_stage_readiness(text) to authenticated;

notify pgrst, 'reload schema';
commit;
