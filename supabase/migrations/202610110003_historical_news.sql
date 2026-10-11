-- Optional external context; never a narrator source or canonical MemoryEvent.
begin;
create table public.user_historical_news_state (
  user_id uuid not null, project_id text not null, enabled boolean not null default true,
  revision bigint not null default 1,
  primary key(user_id,project_id),
  foreign key(user_id,project_id) references public.user_memoir_project on delete cascade
);
create table public.user_historical_news_job (
  user_id uuid not null, project_id text not null, id uuid not null default gen_random_uuid(),
  context_revision text not null, source_sequence bigint not null,
  status text not null check(status in ('running','ready','empty','unavailable','cancelled')),
  expires_at timestamptz not null, hypothesis jsonb not null,
  accounting jsonb not null default '{"cost":null,"cost_status":"unavailable"}',
  primary key(user_id,project_id,id),
  foreign key(user_id,project_id) references public.user_memoir_project on delete cascade
);
create unique index historical_news_one_running on public.user_historical_news_job(user_id,project_id,context_revision) where status='running';
create table public.user_historical_news_clue (
  user_id uuid not null, project_id text not null, id text not null,
  context_revision text not null, status text not null check(status in ('ready','rejected','used')),
  evidence jsonb not null, relevance jsonb not null,
  primary key(user_id,project_id,id),
  foreign key(user_id,project_id) references public.user_memoir_project on delete cascade
);
alter table public.user_historical_news_state enable row level security;
alter table public.user_historical_news_job enable row level security;
alter table public.user_historical_news_clue enable row level security;
revoke all on public.user_historical_news_state,public.user_historical_news_job,public.user_historical_news_clue from public,anon,authenticated;
grant select on public.user_historical_news_state,public.user_historical_news_job,public.user_historical_news_clue to authenticated;
create policy news_state_owner on public.user_historical_news_state for select to authenticated using(user_id=auth.uid());
create policy news_job_owner on public.user_historical_news_job for select to authenticated using(user_id=auth.uid());
create policy news_clue_owner on public.user_historical_news_clue for select to authenticated using(user_id=auth.uid());

create function public.historical_news_public(p_evidence jsonb) returns jsonb
language sql immutable set search_path='' as $$
 select jsonb_object_agg(key,value) from jsonb_each(p_evidence) where key in
 ('id','title','summary','event_start','event_end','precision','place','source_url','source_title','publisher','publication_date')
$$;
create function public.historical_news_revision(p_owner uuid,p_project text) returns text
language sql stable security definer set search_path='' as $$
 select p.policy_epoch::text || ':' || p.event_sequence::text || ':' || coalesce(s.revision,1)::text
 from public.user_memoir_project p left join public.user_historical_news_state s using(user_id,project_id)
 where p.user_id=p_owner and p.project_id=p_project
$$;
create function public.read_user_historical_news(p_project_id text) returns jsonb
language plpgsql stable security definer set search_path='' as $$
declare rev text; enabled boolean;
begin
 if auth.uid() is null then raise exception 'authenticated user required' using errcode='42501'; end if;
 rev:=public.historical_news_revision(auth.uid(),p_project_id);
 enabled:=coalesce((select s.enabled from public.user_historical_news_state s where user_id=auth.uid() and project_id=p_project_id),true);
 return jsonb_build_object('enabled',enabled,'project_id',p_project_id,'context_revision',rev,
 'clues',coalesce((select jsonb_agg(evidence || jsonb_build_object('id',id,'status',status,'project_id',project_id,
   'context_revision',context_revision,'relevance',relevance)) from public.user_historical_news_clue
   where user_id=auth.uid() and project_id=p_project_id and status='ready' and context_revision=rev and enabled),'[]'));
end $$;
create function public.set_user_historical_news(p_project_id text,p_enabled boolean,p_reject_id text default null) returns jsonb
language plpgsql security definer set search_path='' as $$
begin
 if auth.uid() is null or (p_enabled is null and p_reject_id is null) then raise exception 'authenticated preference required' using errcode='42501'; end if;
 perform 1 from public.user_memoir_project where user_id=auth.uid() and project_id=p_project_id for update;
 if not found then raise exception 'project unavailable' using errcode='42501'; end if;
 insert into public.user_historical_news_state(user_id,project_id,enabled) values(auth.uid(),p_project_id,coalesce(p_enabled,(select enabled from public.user_historical_news_state where user_id=auth.uid() and project_id=p_project_id),true))
 on conflict(user_id,project_id) do update set enabled=excluded.enabled,revision=public.user_historical_news_state.revision+1;
 if p_reject_id is not null then
   update public.user_historical_news_clue set status='rejected' where user_id=auth.uid() and project_id=p_project_id and id=p_reject_id;
 end if;
 update public.user_historical_news_job set status='cancelled' where user_id=auth.uid() and project_id=p_project_id and status='running';
 -- Preference/exclusion changes fence work without modifying narrator evidence.
 update public.user_interview_plan set plan=jsonb_set(jsonb_set(plan,'{candidates}',
   coalesce((select jsonb_agg(c) from jsonb_array_elements(plan->'candidates') c where c->'context'->>'historical_clue_id' is null),'[]')),
   '{chosen_id}',case when exists(select 1 from jsonb_array_elements(plan->'candidates') c
      where c->>'id'=plan->>'chosen_id' and c->'context'->>'historical_clue_id' is null) then plan->'chosen_id' else coalesce((select c->'id' from jsonb_array_elements(plan->'candidates') c
        where c->'context'->>'historical_clue_id' is null limit 1),'null') end)
   where user_id=auth.uid() and project_id=p_project_id;
 return public.read_user_historical_news(p_project_id);
end $$;
create function public.read_user_historical_news_basis(p_project_id text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare p public.user_memoir_project%rowtype;
begin
 if auth.uid() is null then raise exception 'authenticated user required' using errcode='42501'; end if;
 select * into p from public.user_memoir_project where user_id=auth.uid() and project_id=p_project_id for share;
 if not found then return null; end if;
 return public.read_user_memory_events(p_project_id) || jsonb_build_object('news_snapshot',jsonb_build_object(
 'source_sequence',p.source_sequence,'context_revision',public.historical_news_revision(auth.uid(),p_project_id)));
end $$;
create function public.begin_user_historical_news(p_project_id text,p_hypothesis jsonb,p_snapshot jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare project public.user_memoir_project%rowtype; rev text; job public.user_historical_news_job%rowtype;
begin
 if auth.uid() is null then raise exception 'authenticated user required' using errcode='42501'; end if;
 select * into project from public.user_memoir_project where user_id=auth.uid() and project_id=p_project_id for update;
 if not found then raise exception 'project unavailable' using errcode='42501'; end if;
 if exists(select 1 from public.user_historical_news_state where user_id=auth.uid() and project_id=p_project_id and not enabled) then return null; end if;
 if jsonb_typeof(p_hypothesis) is distinct from 'object' or octet_length(p_hypothesis::text)>2000 or
   jsonb_typeof(p_hypothesis->'start') is distinct from 'number' or jsonb_typeof(p_hypothesis->'end') is distinct from 'number' or
   jsonb_typeof(p_hypothesis->'place') is distinct from 'string' or jsonb_typeof(p_hypothesis->'country') is distinct from 'string' or
   jsonb_typeof(p_hypothesis->'tentative') is distinct from 'boolean' or
   exists(select 1 from jsonb_object_keys(p_hypothesis) k where k not in ('start','end','place','country','granularity','tentative','time_basis','age_interval')) or
   not exists(select 1 from (values ('New York, USA','USA'),('New York City, USA','USA'),('New York State, USA','USA'),('Boston, USA','USA'),
     ('Sydney, Australia','Australia'),('Perth, Australia','Australia'),('Melbourne, Australia','Australia'),('Chengdu, China','China'),
     ('Kunming, China','China'),('Beijing, China','China'),('成都, 中国','中国'),('昆明, 中国','中国'),('北京, 中国','中国'),
     ('纽约, 美国','美国'),('悉尼, 澳大利亚','澳大利亚')) public_place(place,country)
     where place=p_hypothesis->>'place' and country=p_hypothesis->>'country') or
   (p_hypothesis->>'end')::integer>extract(year from current_date)::integer or
   (p_hypothesis->>'start')::integer not between 1 and extract(year from current_date)::integer or
   (p_hypothesis->>'end')::integer < (p_hypothesis->>'start')::integer or
   (p_hypothesis->>'end')::integer-(p_hypothesis->>'start')::integer>15 then raise exception 'invalid news hypothesis'; end if;
 rev:=public.historical_news_revision(auth.uid(),p_project_id);
 if p_snapshot->>'context_revision' is distinct from rev or (p_snapshot->>'source_sequence')::bigint is distinct from project.source_sequence then return null; end if;
 update public.user_historical_news_job set status=case when context_revision=rev then 'unavailable' else 'cancelled' end where user_id=auth.uid() and project_id=p_project_id and status='running'
   and (expires_at<=clock_timestamp() or context_revision<>rev);
 if exists(select 1 from public.user_historical_news_job where user_id=auth.uid() and project_id=p_project_id
   and context_revision=rev and (status='running' or status in ('ready','empty','unavailable') and expires_at>clock_timestamp()-interval '24 hours')) then return null; end if;
 insert into public.user_historical_news_job(user_id,project_id,context_revision,source_sequence,status,expires_at,hypothesis)
 values(auth.uid(),p_project_id,rev,project.source_sequence,'running',clock_timestamp()+interval '45 seconds',p_hypothesis) returning * into job;
 return to_jsonb(job)-'user_id';
end $$;
create function public.finish_user_historical_news(p_project_id text,p_job_id uuid,p_result jsonb) returns boolean
language plpgsql security definer set search_path='' as $$
declare project public.user_memoir_project%rowtype; job public.user_historical_news_job%rowtype; c jsonb;
begin
 if auth.uid() is null then raise exception 'authenticated user required' using errcode='42501'; end if;
 select * into project from public.user_memoir_project where user_id=auth.uid() and project_id=p_project_id for update;
 select * into job from public.user_historical_news_job where user_id=auth.uid() and project_id=p_project_id and id=p_job_id for update;
 if not found or job.status<>'running' or job.expires_at<=clock_timestamp() or job.source_sequence<>project.source_sequence
   or job.context_revision is distinct from public.historical_news_revision(auth.uid(),p_project_id)
   or exists(select 1 from public.user_historical_news_state where user_id=auth.uid() and project_id=p_project_id and not enabled) then return false; end if;
 if p_result->>'status' not in ('ready','empty','unavailable') or jsonb_typeof(p_result->'clues') is distinct from 'array'
   or jsonb_array_length(p_result->'clues')>5 or octet_length(p_result::text)>50000 then raise exception 'invalid historical result'; end if;
 for c in select value from jsonb_array_elements(p_result->'clues') loop
   if jsonb_typeof(c) is distinct from 'object' or exists(select 1 from unnest(array[
      'id','title','summary','precision','place','category','source_url','source_title','publisher','excerpt','locator','retrieved_at','evidence_status']) k
      where jsonb_typeof(c->k) is distinct from 'string' or length(btrim(c->>k))=0)
      or jsonb_typeof(c->'event_start') is distinct from 'number' or jsonb_typeof(c->'event_end') is distinct from 'number'
      or jsonb_typeof(c->'receipt') is distinct from 'object' or jsonb_typeof(c->'receipt'->'urls') is distinct from 'array'
      or exists(select 1 from unnest(array['provider','response_id','tool_call_id','status']) k
         where jsonb_typeof(c->'receipt'->k) is distinct from 'string' or length(btrim(c->'receipt'->>k))=0)
      or c->>'source_url' !~ '^https?://[A-Za-z][A-Za-z0-9.-]*[.][A-Za-z]{2,}(/|$)'
      or c->>'source_url' ~* '(^https?://localhost[./]|[.]local/|[.]internal/|[.]localhost/|[?&](token|key|secret|password)=)'
      then raise exception 'malformed historical evidence' using errcode='22023'; end if;
   if c->>'id' !~ '^news-[a-f0-9]{24}$' or c->>'evidence_status' is distinct from 'inspected'
     or c->'receipt'->>'status' is distinct from 'completed' or length(coalesce(c->'receipt'->>'response_id',''))=0
     or length(coalesce(c->'receipt'->>'tool_call_id',''))=0 or not (c->'receipt'->'urls' ? (c->>'source_url'))
     or length(c->>'title')>200 or length(c->>'locator')>200 or length(c->>'retrieved_at')>40 or length(c->>'source_url')>8192
     or c->>'retrieved_at' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]+)?(Z|[+-][0-9]{2}:[0-9]{2})$'
     or (c->>'retrieved_at')::timestamptz is null
     or (c->'publication_date' is not null and c->'publication_date'<>'null'::jsonb and
       (jsonb_typeof(c->'publication_date') is distinct from 'string' or c->>'publication_date' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
        or (c->>'publication_date')::date is null))
     or c->>'source_url' !~ '^https?://[^ /]+/' or length(coalesce(c->>'excerpt','')) not between 1 and 800
     or length(coalesce(c->>'source_title','')) not between 1 and 300 or length(coalesce(c->>'publisher','')) not between 1 and 200
     or length(coalesce(c->>'summary','')) not between 1 and 500 or position(c->>'summary' in c->>'excerpt')=0
     or concat_ws(' ',c->>'title',c->>'summary',c->>'excerpt') ~* '\m(war|battle|attack|massacre|kill(ed|ing)?|murder|assassin[[:alpha:]]*|terror[[:alpha:]]*|bomb[[:alpha:]]*|shoot[[:alpha:]]*|riot[[:alpha:]]*|violence|rape|abuse|discrimination|racis[[:alpha:]]*|slavery|genocide|election|campaign|politic[[:alpha:]]*|protest|coup|revolution|communis[[:alpha:]]*|nazi|holocaust|famine|disaster)\M|灾|战争|屠杀|杀害|袭击|枪击|炸弹|骚乱|暴力|强奸|虐待|歧视|种族|奴隶|选举|政治|抗议|政变|革命|文革|饥荒|死亡'
     or c->>'category' not in ('civic','culture','sport') or c->>'precision' not in ('year','range')
     or (c->>'event_start')::integer<(job.hypothesis->>'start')::integer or (c->>'event_end')::integer>(job.hypothesis->>'end')::integer
     or (c->>'event_start')::integer>(c->>'event_end')::integer
     or c->>'place' not in (job.hypothesis->>'place',job.hypothesis->>'country')
     then raise exception 'unsupported historical evidence' using errcode='22023'; end if;
   insert into public.user_historical_news_clue(user_id,project_id,id,context_revision,status,evidence,relevance)
   values(auth.uid(),p_project_id,c->>'id',job.context_revision,'ready',c,job.hypothesis)
   on conflict(user_id,project_id,id) do update set context_revision=excluded.context_revision,evidence=excluded.evidence,relevance=excluded.relevance
     where public.user_historical_news_clue.status='ready';
 end loop;
 update public.user_historical_news_job set status=p_result->>'status',accounting=jsonb_build_object(
 'discovery_requests',p_result->'accounting'->'discovery_requests','source_reads',p_result->'accounting'->'source_reads',
 'cache',p_result->'accounting'->'cache','cost',null,'cost_status','unavailable') where user_id=auth.uid() and project_id=p_project_id and id=p_job_id;
 return true;
end $$;

alter function public.read_user_interview_context(text) rename to read_user_interview_context_before_news;
create function public.read_user_interview_context(p_project_id text) returns jsonb
language sql stable security definer set search_path='' as $$
 select public.read_user_interview_context_before_news(p_project_id) || jsonb_build_object('historical_news',public.read_user_historical_news(p_project_id))
$$;

create or replace function public.save_user_interview_plan(p_project_id text,p_client_turn_id uuid,p_plan jsonb,p_associations jsonb,p_lease_token uuid,
  p_reply text default null,p_response_photo_ids jsonb default '[]',p_thread_id text default null)
returns jsonb language plpgsql security definer set search_path='' as $$
declare v_owner uuid:=auth.uid(); project public.user_memoir_project%rowtype; turn public.user_interview_turn%rowtype;
  candidate jsonb; context jsonb; proposal jsonb; evidence jsonb; current_source public.user_narrator_source%rowtype;
  inserted integer; changed boolean:=false; response_cards jsonb:='[]'; photo_identifier text;
begin
  if v_owner is null then raise exception 'authenticated user required' using errcode='42501'; end if;
  select * into project from public.user_memoir_project where user_id=v_owner and project_id=p_project_id for update;
  perform 1 from public.user_agent_turn_lease where user_id=v_owner and lease_token=p_lease_token and expires_at>clock_timestamp() for update;
  if not found then raise exception 'agent turn lease lost' using errcode='40001'; end if;
  select * into turn from public.user_interview_turn where user_id=v_owner and project_id=p_project_id and client_turn_id=p_client_turn_id;
  if not found or turn.sequence is distinct from project.interview_sequence or turn.source_sequence is distinct from project.source_sequence or
    turn.policy_epoch is distinct from project.policy_epoch then raise exception 'stale interview turn' using errcode='40001'; end if;
  if turn.source_id is not null and not exists(select 1 from public.user_narrator_source where user_id=v_owner and project_id=p_project_id
      and id=turn.source_id and version=turn.source_version and status='active') then raise exception 'stale interview turn' using errcode='40001'; end if;
  if turn.collector is not null then
    return public.interview_turn_record(turn) || public.read_user_interview_context(p_project_id);
  end if;
  if p_reply is not null and (length(btrim(p_reply)) not between 1 and 100000 or length(coalesce(p_thread_id,'')) not between 1 and 1000) then
    raise exception 'invalid saved collector reply' using errcode='22023'; end if;
  if jsonb_typeof(p_response_photo_ids) is distinct from 'array' or jsonb_array_length(p_response_photo_ids)>5 then
    raise exception 'invalid response photo selection' using errcode='22023'; end if;
  for photo_identifier in select distinct value from jsonb_array_elements_text(p_response_photo_ids) loop
    if not public.interview_photo_available(v_owner,p_project_id,photo_identifier) then
      raise exception 'response photo unavailable' using errcode='42501'; end if;
    response_cards:=response_cards || (select jsonb_build_array(p) from public.user_interview_turn t,
      jsonb_array_elements(t.photo_context) p where t.user_id=v_owner and t.project_id=p_project_id and p->>'photo_id'=photo_identifier
      order by t.sequence desc limit 1);
  end loop;
  if jsonb_typeof(p_plan) is distinct from 'object' or octet_length(p_plan::text)>32000 or
    jsonb_typeof(p_plan->'candidates') is distinct from 'array' or jsonb_array_length(p_plan->'candidates')>5 or
    exists(select 1 from jsonb_object_keys(p_plan) k where k not in ('candidates','chosen_id','active_event_id','work')) or
    jsonb_typeof(p_associations) is distinct from 'array' or jsonb_array_length(p_associations)>20 or
    octet_length(p_associations::text)>32000 then raise exception 'invalid interview plan' using errcode='22023'; end if;
  if p_plan ? 'work' then
    if jsonb_typeof(p_plan->'work') is distinct from 'object' or
      (p_plan->'work'->>'mode') is null or (p_plan->'work'->>'mode') not in ('reply_only','extract') or
      exists(select 1 from jsonb_object_keys(p_plan->'work') k where k not in ('mode','name')) or
      not (p_plan->'work' ? 'name') or jsonb_typeof(p_plan->'work'->'name') not in ('string','null') or
      length(coalesce(p_plan->'work'->>'name',''))>120 then
      raise exception 'invalid interview work plan' using errcode='22023'; end if;
    if p_plan->'work'->>'mode'='reply_only' then
      -- Prior narrator history determines opening_turn in collector validation.
      -- A project's first turn can belong to a returning storyteller.
      if jsonb_array_length(p_associations)>0 or jsonb_array_length(p_response_photo_ids)>0 or
        jsonb_array_length(turn.photo_context)>0 then
        raise exception 'reply-only work cannot discard accepted photo context' using errcode='22023'; end if;
      if p_plan->'work'->>'name' is not null then
        select * into current_source from public.user_narrator_source where user_id=v_owner and project_id=p_project_id
          and id=turn.source_id and version=turn.source_version and status='active';
        if not found or length(btrim(p_plan->'work'->>'name'))=0 or
          position((p_plan->'work'->>'name') in current_source.text)=0 then
          raise exception 'opening name requires exact narrator wording' using errcode='22023'; end if;
      end if;
    elsif p_plan->'work'->>'name' is not null then
      raise exception 'story profile clues belong to normal extraction' using errcode='22023'; end if;
  end if;

  if (select count(*)<>count(distinct c->>'id') from jsonb_array_elements(p_plan->'candidates') c) or
    (jsonb_array_length(p_plan->'candidates')>0 and not exists(select 1 from jsonb_array_elements(p_plan->'candidates') c where c->>'id'=p_plan->>'chosen_id')) or
    (jsonb_array_length(p_plan->'candidates')=0 and p_plan->>'chosen_id' is not null) then
    raise exception 'invalid interview plan selection' using errcode='22023'; end if;
  if p_plan->>'active_event_id' is not null and not exists(select 1 from public.user_memory_event
    where user_id=v_owner and project_id=p_project_id and id=p_plan->>'active_event_id' and status='active') then
    raise exception 'active event unavailable' using errcode='42501'; end if;
  for candidate in select value from jsonb_array_elements(p_plan->'candidates') loop
    context:=coalesce(candidate->'context','{}');
    if jsonb_typeof(candidate) is distinct from 'object' or
      jsonb_typeof(candidate->'order') is distinct from 'number' or
      jsonb_typeof(candidate->'question') is distinct from 'string' or
      exists(select 1 from jsonb_object_keys(candidate) k where k not in ('id','question','context','order','bridge')) or length(coalesce(candidate->>'id','')) not between 1 and 128 or
      length(btrim(coalesce(candidate->>'question',''))) not between 1 and 2000 or jsonb_typeof(context) is distinct from 'object' or
      length(coalesce(candidate->>'bridge',''))>2000 or
      exists(select 1 from jsonb_object_keys(context) k where k not in ('event_id','photo_id','life_stage','year','historical_clue_id')) or (candidate->>'order')::integer not between 0 and 100 then
      raise exception 'invalid interview plan candidate' using errcode='22023'; end if;
    if context->>'historical_clue_id' is not null then
      if context->>'year' is not null or context->>'life_stage' is not null or context->>'event_id' is not null or context->>'photo_id' is not null
        or (select count(*) from jsonb_array_elements(p_plan->'candidates') c where c->'context'->>'historical_clue_id' is not null)>1
        or (candidate->>'id'=p_plan->>'chosen_id' and p_plan->>'active_event_id' is not null)
        or not exists(select 1 from jsonb_array_elements(public.read_user_historical_news(p_project_id)->'clues') c
          where c->>'id'=context->>'historical_clue_id') then
        raise exception 'historical clue unavailable' using errcode='42501'; end if;
    end if;
    if context->>'event_id' is not null and not exists(select 1 from public.user_memory_event
      where user_id=v_owner and project_id=p_project_id and id=context->>'event_id' and status='active') then
      raise exception 'candidate event unavailable' using errcode='42501'; end if;
    if context->>'life_stage' is not null and not exists(select 1 from public.user_memory_event e where
      e.user_id=v_owner and e.project_id=p_project_id and e.status='active' and e.life_stage=context->>'life_stage') then
      raise exception 'unsupported candidate life stage' using errcode='22023'; end if;
    if context->>'year' is not null and not (
      exists(select 1 from public.user_memory_event e where e.user_id=v_owner and e.project_id=p_project_id and e.status='active'
        and (e.data->'temporal'->>'year_start'=context->>'year' or e.data->'temporal'->>'year_end'=context->>'year'))) then
      raise exception 'unsupported candidate year' using errcode='22023'; end if;
    if context->>'photo_id' is not null and not public.interview_photo_available(v_owner,p_project_id,context->>'photo_id') then
      raise exception 'candidate photo unavailable' using errcode='42501'; end if;
  end loop;
  for proposal in select value from jsonb_array_elements(p_associations) loop
    if turn.source_id is null or proposal->>'source_id' is distinct from turn.source_id::text or
      (proposal->>'source_version')::bigint is distinct from turn.source_version then
      raise exception 'photo evidence must belong to this accepted source' using errcode='42501'; end if;
    if not public.interview_photo_available(v_owner,p_project_id,proposal->>'photo_id') then
      raise exception 'photo unavailable' using errcode='42501'; end if;
    -- A deferred cue may gain its FIRST link from a later accepted source.
    -- Cue authority is scoped, lifecycle-current and fenced by any explicit
    -- unlink. Uploading alone or retaining a withdrawn snapshot is not enough.
    if not public.interview_photo_available(v_owner,p_project_id,proposal->>'photo_id',true) and
      not exists(select 1 from public.user_interview_photo_link l join public.user_narrator_source original
        on original.user_id=l.user_id and original.project_id=l.project_id and original.id=l.source_id
        where l.user_id=v_owner and l.project_id=p_project_id and l.photo_id=proposal->>'photo_id'
          and l.status='confirmed' and l.event_id=proposal->>'event_id'
          and original.status='active' and original.version=l.source_version) then
      raise exception 'photo is not accepted or supported active event context' using errcode='42501'; end if;
    evidence:=jsonb_build_object('source_id',proposal->>'source_id','version',proposal->'source_version','quote',proposal->>'quote');
    perform public.validate_memory_evidence(v_owner,p_project_id,evidence);
    if proposal->>'event_id' is not null and not exists(select 1 from public.user_memory_event where user_id=v_owner and project_id=p_project_id
      and id=proposal->>'event_id' and status='active') then raise exception 'photo event unavailable' using errcode='42501'; end if;
    -- visual_derived requires a future verified image-inspection path. Current
    -- collector sees metadata, never pixels: fail closed on claimed sight.
    if proposal->>'provenance' is null or proposal->>'provenance' not in ('narrator','narrator_metadata') then
      raise exception 'unsupported photo description provenance' using errcode='22023'; end if;
    insert into public.user_interview_photo_link(user_id,project_id,photo_id,intended_event_id,source_id,source_version,quote,description,provenance)
      values(v_owner,p_project_id,proposal->>'photo_id',proposal->>'event_id',turn.source_id,turn.source_version,
        proposal->>'quote',proposal->>'description',proposal->>'provenance') on conflict do nothing;
    get diagnostics inserted=row_count; changed:=changed or inserted>0;
  end loop;
  if changed then perform public.invalidate_interview_photo_projection(v_owner,p_project_id,false); end if;
  perform public.reconcile_interview_photo_links(v_owner,p_project_id);
  insert into public.user_interview_plan(user_id,project_id,client_turn_id,sequence,plan)
    values(v_owner,p_project_id,p_client_turn_id,turn.sequence,p_plan)
    on conflict(user_id,project_id) do update set client_turn_id=excluded.client_turn_id,sequence=excluded.sequence,
      revision=public.user_interview_plan.revision+1,plan=excluded.plan;
  update public.user_interview_turn set collector=case when p_reply is null then null else jsonb_build_object(
    'plan',p_plan,'reply',p_reply,'thread_id',p_thread_id,'response_photos',response_cards,
    'historical_context',(select public.historical_news_public(c.evidence)
       from public.user_historical_news_clue c, jsonb_array_elements(p_plan->'candidates') q
       where c.user_id=v_owner and c.project_id=p_project_id and c.id=q->'context'->>'historical_clue_id' and q->>'id'=p_plan->>'chosen_id')) end, policy_epoch=(select policy_epoch from public.user_memoir_project where user_id=v_owner and project_id=p_project_id)
    where user_id=v_owner and project_id=p_project_id and client_turn_id=p_client_turn_id;
  -- Once presented, do not ask this cue again. Its immutable cited reply
  -- remains replayable; later narration stays exact original testimony.
  update public.user_historical_news_clue set status='used' where user_id=v_owner and project_id=p_project_id and id=(
    select c->'context'->>'historical_clue_id' from jsonb_array_elements(p_plan->'candidates') c where c->>'id'=p_plan->>'chosen_id');
  if not exists(select 1 from public.user_agent_turn_lease where user_id=v_owner and lease_token=p_lease_token and expires_at>clock_timestamp()) then
    raise exception 'agent turn lease lost' using errcode='40001'; end if;
  return public.read_user_interview_turn(p_project_id,p_client_turn_id) || public.read_user_interview_context(p_project_id);
end $$;


revoke all on function public.historical_news_public(jsonb),public.historical_news_revision(uuid,text),public.read_user_historical_news(text),
 public.set_user_historical_news(text,boolean,text),public.read_user_historical_news_basis(text),public.begin_user_historical_news(text,jsonb,jsonb),public.finish_user_historical_news(text,uuid,jsonb),
 public.read_user_interview_context(text),public.read_user_interview_context_before_news(text) from public,anon,authenticated;
grant execute on function public.read_user_historical_news(text),public.set_user_historical_news(text,boolean,text),
 public.read_user_historical_news_basis(text),public.begin_user_historical_news(text,jsonb,jsonb),public.finish_user_historical_news(text,uuid,jsonb),public.read_user_interview_context(text) to authenticated;
create or replace function public.interview_turn_record(t public.user_interview_turn) returns jsonb
language sql stable set search_path='' as $$
  select jsonb_build_object('client_turn_id',t.client_turn_id,'sequence',t.sequence,
    'source',(select public.narrator_source_record(s) from public.user_narrator_source s
      where s.user_id=t.user_id and s.project_id=t.project_id and s.id=t.source_id),
    'source_version',t.source_version,'photo_context',case when t.source_id is null or exists(select 1 from public.user_narrator_source s
      where s.user_id=t.user_id and s.project_id=t.project_id and s.id=t.source_id and s.version=t.source_version and s.status='active')
      then coalesce((select jsonb_agg(p) from jsonb_array_elements(t.photo_context) p where p->>'kind'<>'private_upload' or
        exists(select 1 from public.user_interview_photo owned where owned.user_id=t.user_id and owned.project_id=t.project_id
          and 'upload:' || owned.id::text=p->>'photo_id' and owned.status='ready')),'[]') else '[]'::jsonb end,
    'plan',t.collector->'plan','reply',t.collector->>'reply','thread_id',t.collector->>'thread_id',
    'response_photos',coalesce(t.collector->'response_photos','[]'),
    'historical_context',t.collector->'historical_context',
    'consumed_photo_key',t.consumed_photo_key,'consumed_photo_revision',t.consumed_photo_revision,
    'photo_cue',jsonb_build_object('consumed',t.consumed_photo_key is not null or jsonb_array_length(t.photo_context)>0,
      'key',t.consumed_photo_key,'revision',t.consumed_photo_revision))
$$;


-- Cue context is attribution about the prompt, never a claim of witnessing.
create function public.attribute_historical_news_answer() returns trigger
language plpgsql security definer set search_path='' as $$
declare cue jsonb;
begin
 if new.version=1 and current_setting('memoir.news_source_accept',true)='1' then
   select t.collector->'historical_context' into cue from public.user_interview_turn t
    where t.user_id=new.user_id and t.project_id=new.project_id order by sequence desc limit 1;
   if btrim(new.text) ~* '^(please )?(stop historical clues|disable historical clues|pause|pause for now|先暂停|暂停|关闭历史线索|不要历史线索)[.!。！ ]*$' or btrim(new.text) ~* '^(I don.t want to discuss|do not discuss|我不想.*谈)' then
     perform public.set_user_historical_news(new.project_id,false,case when cue is not null then cue->>'id' else null end);
   elsif new.text ~* '(don.t remember|cannot remember|can.t remember|skip this clue|想不起来|不记得|跳过)' then
     if cue is not null then perform public.set_user_historical_news(new.project_id,
       coalesce((select enabled from public.user_historical_news_state where user_id=new.user_id and project_id=new.project_id),true),cue->>'id'); end if;
   elsif lower(btrim(new.text)) in ('let''s return to that historical clue.','let''s return to that historical clue','回到刚才那条历史线索。','回到刚才那条历史线索') then
     if cue is null or cue='null'::jsonb then
       select t.collector->'historical_context' into cue from public.user_interview_turn t where
         t.user_id=new.user_id and t.project_id=new.project_id and t.collector->'historical_context' is not null
         and t.collector->'historical_context'<>'null'::jsonb order by sequence desc limit 1;
     end if;
     perform public.set_user_historical_news(new.project_id,true);
     update public.user_historical_news_clue set status='ready',context_revision=public.historical_news_revision(new.user_id,new.project_id)
       where user_id=new.user_id and project_id=new.project_id and id=cue->>'id';
   end if;
   if cue is not null and cue<>'null'::jsonb then
     new.attribution:=new.attribution || jsonb_build_object('cue_context',jsonb_build_object(
       'kind','historical_context_presented','clue_id',cue->>'id'));
   end if;
 elsif new.version>1 then
   select v.attribution->'cue_context' into cue from public.user_narrator_source_version v
    where v.user_id=new.user_id and v.project_id=new.project_id and v.source_id=new.source_id and v.version<new.version
    order by v.version desc limit 1;
   if cue is not null then new.attribution:=new.attribution || jsonb_build_object('cue_context',cue); end if;
 end if;
 return new;
end $$;
create trigger historical_news_answer_attribution before insert on public.user_narrator_source_version
 for each row execute function public.attribute_historical_news_answer();
-- Mark only live narrator acceptance. Bulk guest transfer must preserve the
-- original source attribution rather than attaching a target-account cue.
alter function public.accept_user_narrator_source(text,uuid,text,text,text) rename to accept_user_narrator_source_before_news;
revoke all on function public.accept_user_narrator_source_before_news(text,uuid,text,text,text) from public,anon,authenticated;
create function public.accept_user_narrator_source(p_project_id text,p_client_turn_id uuid,p_text text,
 p_kind text default 'narrator_chat',p_language text default 'en-AU') returns jsonb
language plpgsql security definer set search_path='' as $$
declare result jsonb; prior text:=current_setting('memoir.news_source_accept',true);
begin
 perform set_config('memoir.news_source_accept','1',true);
 result:=public.accept_user_narrator_source_before_news(p_project_id,p_client_turn_id,p_text,p_kind,p_language);
 perform set_config('memoir.news_source_accept',coalesce(prior,''),true);
 return result;
exception when others then
 perform set_config('memoir.news_source_accept',coalesce(prior,''),true);
 raise;
end $$;
revoke all on function public.accept_user_narrator_source(text,uuid,text,text,text) from public,anon,authenticated;
grant execute on function public.accept_user_narrator_source(text,uuid,text,text,text) to authenticated;

create or replace function public.narrator_source_record(s public.user_narrator_source) returns jsonb
language sql stable set search_path='' as $$
 select jsonb_build_object('id',s.id,'project_id',s.project_id,'client_turn_id',s.client_turn_id,
 'sequence',s.sequence,'version',s.version,'text',s.text,'kind',s.kind,'language',s.language,
 'status',s.status,'author_role','storyteller','created_at',s.created_at) ||
 coalesce((select jsonb_build_object('cue_context',v.attribution->'cue_context')
   from public.user_narrator_source_version v where v.user_id=s.user_id and v.project_id=s.project_id
   and v.source_id=s.id and v.version=s.version and v.attribution ? 'cue_context'),'{}')
$$;

alter function public.attach_guest_conversation(text,boolean) rename to attach_guest_conversation_before_news;
revoke all on function public.attach_guest_conversation_before_news(text,boolean) from public,anon,authenticated;
create function public.attach_guest_conversation(p_token text,p_guest_wins boolean default false) returns jsonb
language plpgsql security definer set search_path='' as $$
declare result jsonb; guest uuid; project text; target uuid:=auth.uid();
begin
 result:=public.attach_guest_conversation_before_news(p_token,p_guest_wins);
 guest:=(result->>'guest_user_id')::uuid;
 select project_id into project from public.user_conversation_attachment where user_id=target and id=(result->>'conversation_id')::uuid;
 if guest is null or project is null or guest=target then return result; end if;
 -- Never transfer a running capability. Public citations already saved with
 -- replies remain intact; private relevance must be recomputed for the owner.
 update public.user_historical_news_job set status='cancelled' where user_id=guest and project_id=project and status='running';
 insert into public.user_historical_news_state(user_id,project_id,enabled,revision)
 select target,project,enabled,revision+1 from public.user_historical_news_state where user_id=guest and project_id=project
 on conflict(user_id,project_id) do nothing;
 insert into public.user_historical_news_clue(user_id,project_id,id,context_revision,status,evidence,relevance)
 select target,project,id,'transferred',case when status='rejected' then 'rejected' else 'used' end,evidence,relevance
 from public.user_historical_news_clue where user_id=guest and project_id=project
 on conflict(user_id,project_id,id) do nothing;
 delete from public.user_historical_news_clue where user_id=guest and project_id=project;
 -- Revoked guest execution remains disabled even if it still holds an old
 -- authenticated request. Repeated attachment cannot reset target choices.
 insert into public.user_historical_news_state(user_id,project_id,enabled)
 select guest,project,false where exists(select 1 from public.user_memoir_project where user_id=guest and project_id=project)
 on conflict(user_id,project_id) do update set enabled=false,revision=public.user_historical_news_state.revision+1;
 return result;
end $$;
revoke all on function public.attach_guest_conversation(text,boolean),public.attribute_historical_news_answer() from public,anon,authenticated;
grant execute on function public.attach_guest_conversation(text,boolean) to authenticated;

commit;
