-- Narration changes the research generation even before event extraction finishes.
begin;
create or replace function public.historical_news_revision(p_owner uuid,p_project text) returns text
language sql stable security definer set search_path='' as $$
 select p.policy_epoch::text || ':' || p.event_sequence::text || ':' || coalesce(s.revision,1)::text || ':' || p.source_sequence::text
 from public.user_memoir_project p left join public.user_historical_news_state s using(user_id,project_id)
 where p.user_id=p_owner and p.project_id=p_project
$$;

create or replace function public.read_user_historical_news(p_project_id text) returns jsonb
language plpgsql stable security definer set search_path='' as $$
declare rev text; enabled boolean;
begin
 if auth.uid() is null then raise exception 'authenticated user required' using errcode='42501'; end if;
 rev:=public.historical_news_revision(auth.uid(),p_project_id);
 enabled:=coalesce((select s.enabled from public.user_historical_news_state s where user_id=auth.uid() and project_id=p_project_id),true);
 return jsonb_build_object('enabled',enabled,'project_id',p_project_id,'context_revision',rev,
 'needs_revalidation',enabled and exists(select 1 from public.user_historical_news_clue
   where user_id=auth.uid() and project_id=p_project_id and status='ready' and context_revision<>rev
   and regexp_replace(context_revision,':[^:]+$','')=regexp_replace(rev,':[^:]+$','')),
 'clues',coalesce((select jsonb_agg(evidence || jsonb_build_object('id',id,'status',status,'project_id',project_id,
   'context_revision',context_revision,'relevance',relevance)) from public.user_historical_news_clue
   where user_id=auth.uid() and project_id=p_project_id and status='ready' and context_revision=rev and enabled),'[]'));
end $$;

-- A new ordinary answer need not discard useful public evidence. Rebinding it
-- requires the same locally derived hypothesis and an exact current snapshot.
create function public.revalidate_user_historical_news(p_project_id text,p_hypothesis jsonb,p_snapshot jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare project public.user_memoir_project%rowtype; rev text;
begin
 if auth.uid() is null then raise exception 'authenticated user required' using errcode='42501'; end if;
 select * into project from public.user_memoir_project where user_id=auth.uid() and project_id=p_project_id for update;
 if not found then return null; end if;
 rev:=public.historical_news_revision(auth.uid(),p_project_id);
 if p_snapshot->>'context_revision' is distinct from rev or (p_snapshot->>'source_sequence')::bigint is distinct from project.source_sequence
   or jsonb_typeof(p_hypothesis) is distinct from 'object' or octet_length(p_hypothesis::text)>2000 then return null; end if;
 update public.user_historical_news_clue set context_revision=rev
   where user_id=auth.uid() and project_id=p_project_id and status='ready' and relevance=p_hypothesis
   and regexp_replace(context_revision,':[^:]+$','')=regexp_replace(rev,':[^:]+$','');
 return public.read_user_historical_news(p_project_id);
end $$;
revoke all on function public.revalidate_user_historical_news(text,jsonb,jsonb) from public,anon,authenticated;
grant execute on function public.revalidate_user_historical_news(text,jsonb,jsonb) to authenticated;
commit;
