-- Retire user-selected interview modes. AI plans/outcomes remain independently persisted.
-- Keep zero-valued phase_revision transport/columns for historical receipt compatibility.
begin;

CREATE OR REPLACE FUNCTION public.read_lifetime_pinned(p_conversation_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'auth'
AS $function$
declare owner uuid:=auth.uid(); identity public.user_lifetime_conversation%rowtype; profile jsonb;
  question text; plan jsonb; continuity jsonb; epoch bigint; record jsonb; selected_bytes integer:=0; omitted boolean:=false; policy_record record; policy_bytes integer:=0; privacy_complete boolean:=true; paused jsonb; excluded jsonb; unresolved jsonb;
begin
  select * into identity from public.user_lifetime_conversation where user_id=owner and conversation_id=p_conversation_id;
  if not found then raise exception 'conversation unavailable'; end if;
  select policy_epoch into epoch from public.user_memoir_project where user_id=owner and project_id=identity.project_id for share;
  select p.profile into profile from public.user_profile p where p.user_id=owner for share;
  select * into identity from public.user_lifetime_conversation where user_id=owner and conversation_id=p_conversation_id;
  select p.plan into plan from public.user_interview_plan p where user_id=owner and project_id=identity.project_id;
  select c->>'question' into question from jsonb_array_elements(coalesce(plan->'candidates','[]')) c where c->>'id'=plan->>'chosen_id';
  -- Only a bounded recent working set belongs in the prompt. Historical typed
  -- records remain available via the explicit paginated retrieval RPC. Privacy,
  -- language, exclusions and active question below are authoritative pins
  -- and are never selected by lexical relevance.
  continuity:='[]'::jsonb;
  for record in select to_jsonb(c)-'user_id'-'conversation_id'-'last_source_sequence' from public.user_lifetime_continuity c
    where c.user_id=owner and c.conversation_id=p_conversation_id and c.policy_epoch=epoch
      and not exists(select 1 from jsonb_array_elements(c.data->'source_refs') ref where not exists(
        select 1 from public.user_narrator_source s where s.user_id=owner and s.project_id=identity.project_id
          and s.id=(ref->>'source_id')::uuid and s.version=(ref->>'version')::bigint and s.status='active'))
    order by case c.kind when 'unresolved_reference' then 0 when 'commitment' then 1 else 2 end,
      c.last_source_sequence desc,c.record_id
    limit 9
  loop
    if jsonb_array_length(continuity)>=8 or selected_bytes+octet_length(record::text)>8000 then omitted:=true;
    else continuity:=continuity||jsonb_build_array(record);selected_bytes:=selected_bytes+octet_length(record::text); end if;
  end loop;
  paused:=coalesce(profile->'memory_preferences'->'paused_topics','[]');
  excluded:=coalesce(profile->'memory_preferences'->'excluded_topics','[]');
  unresolved:=coalesce(profile->'memory_preferences'->'unresolved_references','[]');
  policy_bytes:=octet_length(paused::text)+octet_length(excluded::text)+octet_length(unresolved::text);
  privacy_complete:=policy_bytes<=16384;
  if privacy_complete then
    for policy_record in select kind,data->>'text' as text from public.user_lifetime_continuity
      where user_id=owner and conversation_id=p_conversation_id and policy_epoch=epoch and kind in ('paused_topic','excluded_topic')
      order by record_id limit 16385 loop
      policy_bytes:=policy_bytes+octet_length(to_jsonb(policy_record.text)::text)+1;
      if policy_bytes>16384 then privacy_complete:=false;exit;end if;
      if policy_record.kind='paused_topic' then paused:=paused||to_jsonb(policy_record.text);
      else excluded:=excluded||to_jsonb(policy_record.text);end if;
    end loop;
  end if;
  -- Never send a partial policy to a model. The coordinator returns an accepted
  -- maintenance receipt when this active configuration exceeds one request.
  if not privacy_complete then paused:='[]';excluded:='[]';unresolved:='[]';end if;
  return jsonb_build_object('schema_version',1,'known_continuity',continuity,'known_continuity_complete',not omitted,
    'continuity_retrieval','read_lifetime_continuity','preference_revision',identity.preference_revision,
    'chosen_name',profile->>'name','language',case when profile->>'preferred_language' in ('en-AU','zh-CN') then profile->>'preferred_language' else 'en-AU' end,
    'active_question',question,'privacy_complete',privacy_complete,'unresolved_references',unresolved,
    'paused_topics',paused,'excluded_topics',excluded);
end $function$;

CREATE OR REPLACE FUNCTION public.read_lifetime_reply(p_conversation_id uuid, p_client_turn_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'auth'
AS $function$
declare owner uuid:=auth.uid(); identity public.user_lifetime_conversation%rowtype; saved public.user_lifetime_reply%rowtype;
 epoch bigint; source public.user_narrator_source%rowtype; interview jsonb; valid boolean;
begin
 select * into identity from public.user_lifetime_conversation where user_id=owner and conversation_id=p_conversation_id;
 if not found then raise exception 'conversation unavailable'; end if;
 select policy_epoch into epoch from public.user_memoir_project where user_id=owner and project_id=identity.project_id for share;
 select * into saved from public.user_lifetime_reply where user_id=owner and conversation_id=p_conversation_id and client_turn_id=p_client_turn_id;
 if not found then return null; end if;
 select * into source from public.user_narrator_source where user_id=owner and project_id=identity.project_id and client_turn_id=p_client_turn_id;
 interview:=public.read_user_interview_turn(identity.project_id,p_client_turn_id);
 valid:=source.status='active' and saved.policy_epoch=epoch and saved.execution_generation=identity.execution_generation
   and saved.preference_revision=identity.preference_revision;
 return jsonb_build_object('conversation_saved',true,'accepted_source_id',source.id,'project_id',identity.project_id,
   'client_turn_id',p_client_turn_id,'reply',case when valid then interview->>'reply' else null end,
   'context_rebuild_required',not coalesce(valid,false));
end $function$;

CREATE OR REPLACE FUNCTION public.capture_lifetime_fence(p_conversation_id uuid, p_lease_token uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'auth'
AS $function$
declare owner uuid:=auth.uid(); identity public.user_lifetime_conversation%rowtype;
  project public.user_memoir_project%rowtype; phase_revision bigint:=0;
begin
  select * into identity from public.user_lifetime_conversation where user_id=owner and conversation_id=p_conversation_id;
  if not found then raise exception 'conversation unavailable'; end if;
  -- Shared project lock conflicts with every correction/preference writer.
  select * into project from public.user_memoir_project where user_id=owner and project_id=identity.project_id for share;
  -- Ensure there is a lockable preference authority even for a new account.
  insert into public.user_profile(user_id,profile) values(owner,'{}') on conflict do nothing;
  perform 1 from public.user_profile where user_id=owner for share;
  -- Refresh after obtaining ordering locks; the first identity read is not a fence.
  select * into identity from public.user_lifetime_conversation where user_id=owner and conversation_id=p_conversation_id;
  perform 1 from public.user_agent_turn_lease where user_id=owner and lease_token=p_lease_token
    and expires_at>clock_timestamp() for share;
  if not found then raise exception 'valid turn lease required' using errcode='PT409'; end if;
  return jsonb_build_object('schema_version',1,'identity',jsonb_build_object('schema_version',1,
    'owner_id',owner,'conversation_id',identity.conversation_id,'product','memoir','project_id',identity.project_id),
    'policy_epoch',project.policy_epoch,'source_revision',project.source_sequence,
    'execution_generation',identity.execution_generation,'phase_revision',phase_revision,
    'preference_revision',identity.preference_revision,'lease_token',p_lease_token);
end $function$;

CREATE OR REPLACE FUNCTION public.read_user_interview_context(p_project_id text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
begin
 if auth.uid() is null then raise exception 'authenticated owner required' using errcode='42501';end if;
 perform 1 from public.user_memoir_project where user_id=auth.uid() and project_id=p_project_id for share;
 if not found then raise exception 'project unavailable' using errcode='42501';end if;
 return public.read_user_interview_context_before_phase(p_project_id) ||
   jsonb_build_object('has_accepted_narration',public.conversation_has_narration(auth.uid(),p_project_id));
end $function$;

CREATE OR REPLACE FUNCTION public.invalidate_formal_memoir_authority()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare changed boolean:=false; owner uuid; project text;
begin
 owner:=coalesce(new.user_id,old.user_id);project:=coalesce(new.project_id,old.project_id);
 if tg_table_name='user_memoir_project' then
   changed:=old.policy_epoch is distinct from new.policy_epoch or old.source_sequence is distinct from new.source_sequence
     or old.event_sequence is distinct from new.event_sequence;
 elsif tg_table_name='user_lifetime_conversation' then
   changed:=old.preference_revision is distinct from new.preference_revision;
 elsif tg_table_name='user_narrator_source' then
   changed:=tg_op='DELETE' or old.version is distinct from new.version or old.status is distinct from new.status or old.text is distinct from new.text;
 end if;
 if changed then
   if tg_table_name<>'user_lifetime_conversation' then
     -- Do not lock formal rows before profile/identity: a preference writer
     -- could otherwise hold profile while waiting for those formal rows.
     perform 1 from public.user_memoir_project where user_id=owner and project_id=project for update;
     perform 1 from public.user_profile where user_id=owner for share;
     perform 1 from public.user_lifetime_conversation where user_id=owner and project_id=project for share;
   end if;
   perform public.invalidate_formal_memoir(owner,project);
 end if;
 return coalesce(new,old);
end $function$;

CREATE OR REPLACE FUNCTION public.lock_formal_memoir_context(p_owner uuid, p_project text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare project public.user_memoir_project%rowtype; identity public.user_lifetime_conversation%rowtype;
 pins jsonb; old_owner text;
begin
 select * into project from public.user_memoir_project where user_id=p_owner and project_id=p_project for update;
 if not found then raise exception 'FORMAL_PROJECT_UNAVAILABLE' using errcode='42501';end if;
 perform 1 from public.user_profile where user_id=p_owner for share;
 select * into identity from public.user_lifetime_conversation where user_id=p_owner and project_id=p_project for share;
 if not found or exists(select 1 from auth.users where id=p_owner and is_anonymous) then
   raise exception 'FORMAL_OWNER_REQUIRED' using errcode='42501';end if;
 perform public.require_lifetime_policy_ready(p_owner,p_project);
 old_owner:=current_setting('request.jwt.claim.sub',true);
 perform set_config('request.jwt.claim.sub',p_owner::text,true);
 pins:=public.read_lifetime_pinned(identity.conversation_id);
 perform set_config('request.jwt.claim.sub',coalesce(old_owner,''),true);
 if (pins->>'privacy_complete')::boolean is distinct from true
   or jsonb_array_length(pins->'excluded_topics')>0 or jsonb_array_length(pins->'paused_topics')>0 then
   raise exception 'FORMAL_PRIVACY_REVIEW_REQUIRED' using errcode='55000';end if;
 return jsonb_build_object('conversation_id',identity.conversation_id,'locale',pins->>'language',
   'phase_revision',0,'policy_epoch',project.policy_epoch,'preference_revision',identity.preference_revision,
   'source_revision',project.source_sequence,'event_revision',project.event_sequence);
end $function$;

CREATE OR REPLACE FUNCTION public.read_lifetime_interview_context(p_conversation_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'auth'
AS $function$
declare owner uuid:=auth.uid(); project text; plan jsonb; events jsonb;
begin
 select project_id into project from public.user_lifetime_conversation where user_id=owner and conversation_id=p_conversation_id;
 if not found then raise exception 'conversation unavailable'; end if;
 perform 1 from public.user_memoir_project where user_id=owner and project_id=project for share;
 select p.plan into plan from public.user_interview_plan p where user_id=owner and project_id=project;
 select coalesce(jsonb_agg(public.bounded_lifetime_event_record(e)),'[]') into events from (select e.* from public.user_memory_event e
 where e.user_id=owner and e.project_id=project and e.status='active'
 and e.id in (select c->'context'->>'event_id' from jsonb_array_elements(coalesce(plan->'candidates','[]')) c)
 and not exists(select 1 from public.user_memory_event_source r where r.user_id=owner and r.project_id=project and r.event_id=e.id
   and not exists(select 1 from public.user_narrator_source s where s.user_id=owner and s.project_id=project and s.id=r.source_id
     and s.version=r.source_version and s.status='active')) order by e.change_sequence desc,e.id limit 8) e;
 return jsonb_build_object('plan',plan,'events',events,'photos','[]'::jsonb,'photo_associations','[]'::jsonb,
   'historical_context_complete',false,'historical_news',public.read_user_historical_news(project),
   'has_accepted_narration',public.conversation_has_narration(owner,project));
end $function$;

CREATE OR REPLACE FUNCTION public.read_lifetime_profile_page(p_lane_id uuid, p_token uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
#variable_conflict use_column
declare snap public.user_lifetime_lane_snapshot%rowtype; job public.user_lifetime_profile_progress%rowtype;
 authority public.user_lifetime_profile_authority%rowtype; source public.user_narrator_source%rowtype;
 page jsonb; profile jsonb; facts jsonb; targets jsonb; mode text; core integer; lo integer; hi integer; due bigint; frontier bigint;
begin
 if not exists(select 1 from public.lifetime_two_lane_rollout where singleton and enabled) then return null;end if;
 snap:=public.lock_lifetime_memoir_lane(p_lane_id,p_token);
 if not exists(select 1 from public.user_memoir_lane where id=p_lane_id and skill='timeline') then return null;end if;
 perform 1 from public.user_agent_turn_lease where user_id=snap.user_id for share;
 if exists(select 1 from public.user_agent_turn_lease where user_id=snap.user_id and expires_at>clock_timestamp()) then return null;end if;
 perform public.ensure_lifetime_profile_authority(snap.user_id);
 select * into authority from public.user_lifetime_profile_authority where user_id=snap.user_id;
 -- Older sessions coalesce to their newest milestone; no historical job replay.
 select public.lifetime_profile_due_round(coalesce(max(ordinal),0)) into due from public.user_completed_round
 where user_id=snap.user_id and project_id=snap.project_id;
 select coalesce(max(pos.sequence),0) into frontier from public.user_completed_round r
 join public.user_narrator_source s on s.user_id=r.user_id and s.project_id=r.project_id and s.client_turn_id=r.turn_id
 join public.user_lifetime_source_position pos on pos.user_id=s.user_id and pos.project_id=s.project_id and pos.source_id=s.id
 where r.user_id=snap.user_id and r.project_id=snap.project_id and r.ordinal<=due;
 insert into public.user_lifetime_profile_progress(user_id,project_id,requested_round,requested_frontier)
 values(snap.user_id,snap.project_id,due,frontier) on conflict(user_id,project_id) do update set
   requested_round=excluded.requested_round,requested_frontier=excluded.requested_frontier
   where excluded.requested_round>user_lifetime_profile_progress.requested_round;
 select * into job from public.user_lifetime_profile_progress where user_id=snap.user_id and project_id=snap.project_id for update;
 if job.active_round=0 and job.requested_round<=greatest(job.covered_round,job.skipped_round) then return null;end if;
 if job.active_round=0 then
   update public.user_lifetime_profile_progress set active_round=requested_round,source_frontier=requested_frontier
   where user_id=snap.user_id and project_id=snap.project_id returning * into job;
 end if;
 select p.profile into profile from public.user_profile p where p.user_id=snap.user_id;
 select coalesce(jsonb_agg(f),'[]') into targets
 from unnest(array['name','birth_year','birth_date_expression','birth_place','childhood_place','avatar_style']) f
 where not(authority.field_locks ? f);
 -- Reference includes protected values, without leaking unrelated application state.
 select coalesce(jsonb_object_agg(f,jsonb_build_object('value',case when length(profile->>f)<=160
   and jsonb_typeof(profile->f) in ('string','number','null') then profile->f else null end,'authority',coalesce(authority.field_locks->>f,
   case when f='name' then (select n.authority from public.user_lifetime_chosen_name n where n.user_id=snap.user_id) end,'automatic'))),'{}')
 into facts from unnest(array['name','birth_year','birth_date_expression','birth_place','childhood_place','avatar_style']) f;
 mode:='extract';
 if not authority.auto_enabled or authority.manual_complete or jsonb_array_length(targets)=0 then mode:='skip';end if;
 select s.* into source from public.user_narrator_source s left join public.user_lifetime_profile_coverage c
 on c.user_id=s.user_id and c.project_id=s.project_id and c.source_id=s.id and c.source_version=s.version
 where s.user_id=snap.user_id and s.project_id=snap.project_id and s.status='active' and s.sequence<=job.source_frontier
   and coalesce(c.next_offset,0)<length(s.text) order by s.sequence limit 1;
 if source.id is null and mode<>'skip' then mode:='reply_only';end if;
 if source.id is not null then
   select coalesce((select next_offset from public.user_lifetime_profile_coverage where user_id=snap.user_id
     and project_id=snap.project_id and source_id=source.id and source_version=source.version),0) into core;
   hi:=least(core+2048,length(source.text));
   lo:=greatest(core-256,0);
   if mode='extract' and exists(select 1 from public.user_interview_turn t where t.user_id=snap.user_id
     and t.project_id=snap.project_id and t.source_id=source.id and t.source_version=source.version
     and t.collector->'plan'->'work'->>'mode'='reply_only') then mode:='reply_only';end if;
 end if;
 -- Read the base without recursively calling the profile-aware wrapper below.
 page:=public.read_lifetime_memoir_lane_page_before_background_profile(p_lane_id,p_token);
 page:=(page-array['input_digest','page_digest','memory_summary','batch'])||jsonb_build_object('complete',false,
   'two_lane',null,'base_revision',coalesce((page->>'base_revision')::bigint,0),
   'events','[]'::jsonb,'partition',null,'source',case when source.id is null or mode='skip' then null else
     jsonb_build_object('id',source.id,'project_id',source.project_id,'version',source.version,'sequence',source.sequence,
       'text',substring(source.text from lo+1 for hi-lo),'char_start',lo,'char_end',hi,'original_length',length(source.text),
       'kind',source.kind,'language',source.language,'status',source.status,'author_role','storyteller') end,
   'profile_context',jsonb_build_object('schema_version',1,'revision',authority.revision,'target_round',job.active_round,
     'covered_round',job.covered_round,'source_frontier',job.source_frontier,'targets',targets,'reference',facts,'work_mode',mode,
     'execution_generation',(select execution_generation from public.user_lifetime_conversation where user_id=snap.user_id
       and conversation_id=snap.conversation_id),'phase_revision',0,
     'cursor',jsonb_build_object('source_id',source.id,'version',source.version,
         'char_start',core,'char_end',hi)));
 page:=page||jsonb_build_object('input_digest',encode(sha256(convert_to((page-'token')::text,'UTF8')),'hex'));
 return page||jsonb_build_object('page_digest',encode(sha256(convert_to(page::text,'UTF8')),'hex'));
end $function$;

CREATE OR REPLACE FUNCTION public.read_lifetime_prepared_questions(p_conversation_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'auth'
AS $function$
declare identity public.user_lifetime_conversation%rowtype; pins jsonb; result jsonb;
begin
 -- Reuse the existing content access/policy guard before selecting any bytes.
 pins:=public.read_lifetime_pinned(p_conversation_id);
 if not exists(select 1 from public.lifetime_two_lane_rollout where singleton and enabled) then return '[]'::jsonb;end if;
 select * into identity from public.user_lifetime_conversation where user_id=auth.uid() and conversation_id=p_conversation_id;
 select coalesce(jsonb_agg(item),'[]') into result from (
   select q||jsonb_build_object('id','bq-'||encode(sha256(convert_to(d.source_id::text||':'||d.source_version||':'||(q->>'question'),'UTF8')),'hex'),
     'source_id',d.source_id,'source_version',d.source_version,'creation_revision',d.source_revision,
     'snapshot_id',d.snapshot_id,'policy_epoch',d.policy_epoch,'task_version','two-lane-v1',
     'invalidation','source/policy/preference/generation/recent coverage/delivered question') item
   from public.user_lifetime_prepared_question d join public.user_narrator_source s on s.user_id=d.user_id and s.project_id=d.project_id
     and s.id=d.source_id and s.version=d.source_version and s.status='active'
   join public.user_memoir_project p on p.user_id=d.user_id and p.project_id=d.project_id
   cross join lateral jsonb_array_elements(d.questions) q
   where d.user_id=auth.uid() and d.project_id=identity.project_id and d.policy_epoch=p.policy_epoch
     and d.preference_revision=identity.preference_revision and d.execution_generation=identity.execution_generation
     and d.source_revision>=p.source_sequence-1
     and not exists(select 1 from public.user_interview_turn t where t.user_id=d.user_id and t.project_id=d.project_id
       and t.collector->'plan'->>'chosen_id'='bq-'||encode(sha256(convert_to(d.source_id::text||':'||d.source_version||':'||(q->>'question'),'UTF8')),'hex'))
   order by s.sequence desc,d.source_id,q->>'question' limit 3
 ) hints;
 return result;
end $function$;

CREATE OR REPLACE FUNCTION public.read_lifetime_strategy_context_at(p_conversation_id uuid, p_plan_revision bigint)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'auth'
AS $function$
declare pins jsonb; identity public.user_lifetime_conversation%rowtype; planned public.user_lifetime_interview_strategy%rowtype;
 rollout text; data jsonb; candidates jsonb; hint text; delivery jsonb;
begin
 pins:=public.read_lifetime_pinned(p_conversation_id);
 select * into identity from public.user_lifetime_conversation where user_id=auth.uid() and conversation_id=p_conversation_id;
 select case when enabled and strategy_enabled then case when strategy_shadow then 'shadow' else 'active' end else 'disabled' end into rollout
   from public.lifetime_two_lane_rollout where singleton;
 if rollout<>'active' then return jsonb_build_object('mode',rollout,'plan',null);end if;
 select jsonb_build_object('prior_delivered_question',o.question_delivered,'prior_delivered_sequence',o.source_sequence) into delivery
   from public.user_lifetime_strategy_outcome o join public.user_interview_turn t
     on t.user_id=o.user_id and t.project_id=o.project_id and t.client_turn_id=o.client_turn_id
   join public.user_narrator_source s on s.user_id=t.user_id and s.project_id=t.project_id and s.id=t.source_id
     and s.version=t.source_version and s.status='active'
   join public.user_lifetime_reply r on r.user_id=o.user_id and r.conversation_id=p_conversation_id and r.client_turn_id=o.client_turn_id
   where o.user_id=auth.uid() and o.project_id=identity.project_id and o.delivered and o.question_delivered is not null
     and r.policy_epoch=(select p.policy_epoch from public.user_memoir_project p where p.user_id=auth.uid() and p.project_id=identity.project_id) and r.execution_generation=identity.execution_generation
     and r.preference_revision=identity.preference_revision order by o.source_sequence desc limit 1;
 delivery:=coalesce(delivery,jsonb_build_object('prior_delivered_question',null,'prior_delivered_sequence',null));
 select active_strategy into hint from public.user_lifetime_strategy_frontier where user_id=auth.uid() and project_id=identity.project_id;
 select * into planned from public.user_lifetime_interview_strategy where user_id=auth.uid() and project_id=identity.project_id and not shadow
   and (p_plan_revision is null or plan_revision=p_plan_revision) order by plan_revision desc limit 1;
 data:=planned.data;
 if planned.plan_revision is null or not exists(select 1 from public.user_memoir_project p join public.user_narrator_source s
   on s.user_id=p.user_id and s.project_id=p.project_id and s.id=planned.source_id and s.version=planned.source_version and s.status='active'
   where p.user_id=auth.uid() and p.project_id=identity.project_id and p.policy_epoch=planned.policy_epoch
     and planned.preference_revision=identity.preference_revision and planned.execution_generation=identity.execution_generation
     and planned.based_on_sequence between p.source_sequence-3 and p.source_sequence)
   or exists(select 1 from jsonb_array_elements(planned.event_manifest) e where not exists(select 1 from public.user_memory_event m
     where m.user_id=auth.uid() and m.project_id=identity.project_id and m.id=e->>'id' and m.revision::text=e->>'revision' and m.status='active')) then
   return jsonb_build_object('mode',rollout,'plan',null,'planned_strategy_hint',hint,'invalid_plan_revision',planned.plan_revision)||delivery;
 end if;
 select coalesce(jsonb_agg(q),'[]') into candidates from jsonb_array_elements(data->'candidates') q
   where not exists(select 1 from public.user_lifetime_strategy_outcome o where o.user_id=auth.uid() and o.project_id=identity.project_id
     and o.delivered and (o.selected_candidate_id=q->>'id' or lower(btrim(o.question_delivered))=lower(btrim(q->>'question'))))
   and not exists(select 1 from public.user_interview_turn t cross join lateral jsonb_array_elements(coalesce(t.collector->'plan'->'candidates','[]')) c
     where t.user_id=auth.uid() and t.project_id=identity.project_id and c->>'id'=t.collector->'plan'->>'chosen_id'
       and not exists(select 1 from public.user_lifetime_strategy_outcome o where o.user_id=t.user_id
         and o.project_id=t.project_id and o.client_turn_id=t.client_turn_id)
       and (c->>'id'=q->>'id' or lower(btrim(c->>'question'))=lower(btrim(q->>'question'))));
 data:=jsonb_set(data,'{candidates}',candidates);
 return jsonb_build_object('mode',rollout,'plan',data,'planned_strategy_hint',hint)||delivery;
end $function$;

CREATE OR REPLACE FUNCTION public.capture_lifetime_read_fence_before_drafts(p_project_id text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
 SET lock_timeout TO '2s'
AS $function$
declare owner uuid:=auth.uid(); identity public.user_lifetime_conversation%rowtype;
  project public.user_memoir_project%rowtype; phase_revision bigint:=0;
begin
  if owner is null then raise exception 'authenticated owner required' using errcode='42501'; end if;
  select * into identity from public.user_lifetime_conversation
    where user_id=owner and project_id=p_project_id and product='memoir';
  if not found then raise exception 'lifetime conversation unavailable' using errcode='42501'; end if;
  -- Same ordering as generation publication, but never lock or claim its lease.
  select * into project from public.user_memoir_project
    where user_id=owner and project_id=p_project_id for share;
  if not found then raise exception 'project unavailable' using errcode='42501'; end if;
  perform 1 from public.user_profile where user_id=owner for share;
  if not found then
    -- A missing row cannot be row-locked. Block only this owner's first INSERT
    -- without creating data from a GET or blocking other tenants' profile writes.
    perform pg_catalog.pg_advisory_xact_lock_shared(pg_catalog.hashtextextended('memoir-profile:'||owner::text,0));
    perform 1 from public.user_profile where user_id=owner for share;
  end if;
  select * into identity from public.user_lifetime_conversation
    where user_id=owner and project_id=p_project_id and product='memoir';
  if not found then raise exception 'lifetime conversation unavailable' using errcode='42501'; end if;
  return jsonb_build_object('schema_version',1,'identity',jsonb_build_object('schema_version',1,
    'owner_id',owner,'conversation_id',identity.conversation_id,'product','memoir','project_id',p_project_id),
    'policy_epoch',project.policy_epoch,'source_revision',project.source_sequence,
    'execution_generation',identity.execution_generation,'phase_revision',phase_revision,
    'preference_revision',identity.preference_revision,
    'captured_at_ms',floor(extract(epoch from clock_timestamp())*1000)::bigint);
end $function$;

CREATE OR REPLACE FUNCTION public.advance_two_lane_checkpoint(p_lane_id uuid, p_token uuid, p_steps integer DEFAULT 1, p_model text DEFAULT 'gpt-5.6-luna-pooled'::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'auth'
AS $function$
declare snap public.user_lifetime_lane_snapshot%rowtype; identity public.user_lifetime_conversation%rowtype;
 project public.user_memoir_project%rowtype; saved public.user_lifetime_compaction%rowtype;
 predecessor uuid; start_sequence bigint:=0; end_sequence bigint; owner uuid; pins jsonb; checkpoint_fence jsonb;
 previous_owner text; candidate uuid; evidence jsonb:='[]'; manifest_sources jsonb:='[]'; item record;
 processed integer; fingerprint text; count_items bigint; chain text; last_seq bigint; last_start integer;
begin
 if p_steps is null or p_steps not between 1 and 4 or p_model not in
   ('gpt-5.6-luna-pooled','gpt-5.6-luna-memoir-low','memoir-luna-low','legal2ai-luna-low','synthetic-byte-bpe') then raise exception 'bounded checkpoint configuration required';end if;
 snap:=public.lock_lifetime_memoir_lane(p_lane_id,p_token);
 owner:=snap.user_id;
 if not exists(select 1 from public.user_memoir_lane where id=p_lane_id and skill='timeline') then
   raise exception 'timeline checkpoint owner required' using errcode='42501';end if;
 if not exists(select 1 from public.lifetime_two_lane_rollout where singleton and enabled)
   or not exists(select 1 from public.user_lifetime_two_lane_source where user_id=owner and project_id=snap.project_id) then
   return jsonb_build_object('complete',true,'coverage_end',0);
 end if;
 select * into project from public.user_memoir_project where user_id=owner and project_id=snap.project_id;
 select * into identity from public.user_lifetime_conversation where user_id=owner and conversation_id=snap.conversation_id;
 previous_owner:=current_setting('request.jwt.claim.sub',true);
 perform set_config('request.jwt.claim.sub',owner::text,true);
 pins:=public.read_lifetime_pinned(snap.conversation_id);
 if pins->'privacy_complete' is distinct from 'true'::jsonb then raise exception 'complete current privacy required' using errcode='PT409';end if;
 predecessor:=identity.checkpoint_id;
 select coverage_end into start_sequence from public.user_lifetime_checkpoint where id=predecessor and published and (lossless or memory_summary is not null);
 start_sequence:=coalesce(start_sequence,0);
 -- Never cover an in-flight current source. The next A consumes this accepted
 -- checkpoint plus every remaining canonical position, including tombstones.
 end_sequence:=snap.source_high_water-1;
 -- A newer canonical frontier belongs to a newer snapshot. Finish this old
 -- quantum without replacing it with a lower checkpoint, even across rollback.
 if exists(select 1 from public.user_lifetime_checkpoint c where c.id=predecessor and c.published and c.coverage_end>end_sequence) then
   perform set_config('request.jwt.claim.sub',coalesce(previous_owner,''),true);
   return jsonb_build_object('complete',true,'coverage_end',(select c.coverage_end from public.user_lifetime_checkpoint c where c.id=predecessor));
 end if;
 if end_sequence<=start_sequence then
   perform set_config('request.jwt.claim.sub',coalesce(previous_owner,''),true);
   return jsonb_build_object('complete',true,'coverage_end',start_sequence);
 end if;
 if not exists(select 1 from public.user_lifetime_source_inventory where user_id=owner and project_id=snap.project_id
   and record_count=project.source_sequence and max_sequence=project.source_sequence) then
   raise exception 'complete canonical source inventory required' using errcode='PT409';end if;
 checkpoint_fence:=jsonb_build_object('schema_version',1,'identity',jsonb_build_object('schema_version',1,'owner_id',owner,
   'conversation_id',snap.conversation_id,'project_id',snap.project_id,'product','memoir'),
   'policy_epoch',project.policy_epoch,'source_revision',project.source_sequence,'execution_generation',identity.execution_generation,
   'phase_revision',0,'preference_revision',identity.preference_revision,'lease_token',p_token);
 select c.* into saved from public.user_lifetime_compaction c where c.user_id=owner and c.conversation_id=snap.conversation_id
   and c.fence-'lease_token'=checkpoint_fence-'lease_token'
   and c.predecessor_id is not distinct from predecessor and c.starting_after=start_sequence and c.through_sequence=end_sequence
   and c.pinned=pins order by id limit 1;
 if not found then
   insert into public.user_lifetime_compaction(user_id,conversation_id,fence,predecessor_id,starting_after,through_sequence,last_sequence,pinned)
     values(owner,snap.conversation_id,checkpoint_fence,predecessor,start_sequence,end_sequence,start_sequence,pins) returning * into saved;
 end if;
 update public.user_lifetime_compaction set fence=checkpoint_fence where id=saved.id returning * into saved;
 for iteration in 1..p_steps loop
   exit when saved.complete;
  processed:=0;
  chain:=saved.digest;count_items:=saved.item_count;last_seq:=saved.last_sequence;last_start:=saved.last_offset;
  for item in
    select pos.sequence,pos.source_id,pos.version,chunk_start,
      case when src.version=pos.version and src.status='active' then least(chunk_start+2000,length(src.text)) else 0 end as chunk_end,
      case when src.id is null then 'withdrawn' when src.version<>pos.version then 'superseded' else src.status end as status,
      case when src.version=pos.version and src.status='active' then substring(src.text from chunk_start+1 for 2000) else null end as content
    from public.user_lifetime_source_position pos left join public.user_narrator_source src
      on src.user_id=pos.user_id and src.project_id=pos.project_id and src.id=pos.source_id
    cross join lateral generate_series(0,case when src.version=pos.version and src.status='active' then greatest(length(src.text)-1,0) else 0 end,2000) chunk_start
    where pos.user_id=owner and pos.project_id=snap.project_id and pos.sequence>saved.starting_after and pos.sequence<=saved.through_sequence
      and (pos.sequence>saved.last_sequence or (pos.sequence=saved.last_sequence and chunk_start>saved.last_offset))
    order by pos.sequence,chunk_start limit 32
  loop
    fingerprint:=case when item.content is not null then encode(sha256(convert_to(item.content,'UTF8')),'hex') else null end;
    insert into public.user_lifetime_covered_evidence(maintenance_id,sequence,source_id,version,char_start,char_end,status,content_sha256)
      values(saved.id,item.sequence,item.source_id,item.version,item.chunk_start,item.chunk_end,item.status,fingerprint);
    chain:=encode(sha256(convert_to(chain||':'||item.sequence||':'||item.source_id||':'||item.version||':'||item.chunk_start||':'||item.chunk_end||':'||item.status||':'||coalesce(fingerprint,''),'UTF8')),'hex');
    processed:=processed+1;count_items:=count_items+1;last_seq:=item.sequence;last_start:=item.chunk_start;
  end loop;
  update public.user_lifetime_compaction set revision=revision+1,item_count=count_items,digest=chain,last_sequence=last_seq,last_offset=last_start,
    complete=processed<32 where id=saved.id returning * into saved;

 end loop;
 if saved.complete then
   -- Publish only a complete lossless replacement. A raw inventory/hash is not
   -- a summary. Larger intervals retain mandatory raw context and fail closed
   -- on A budget overflow until an accepted bounded summary is available.
   if exists(select 1 from public.user_lifetime_checkpoint c where c.id=predecessor and c.memory_summary is not null)
     or (select coalesce(sum(octet_length(substring(s.text from e.char_start+1 for e.char_end-e.char_start))),0)
       from public.user_lifetime_covered_evidence e join public.user_narrator_source s on s.user_id=owner and s.project_id=snap.project_id
         and s.id=e.source_id and s.version=e.version where e.maintenance_id=saved.id and e.status='active')
       +coalesce((select octet_length(c.evidence::text) from public.user_lifetime_checkpoint c where c.id=predecessor),0)>12000
     or (select count(*) from public.user_lifetime_covered_evidence where maintenance_id=saved.id and status='active')
       + coalesce((select jsonb_array_length(c.evidence) from public.user_lifetime_checkpoint c where c.id=predecessor and c.lossless),0)>16 then
     update public.user_lifetime_compaction set summary_required=true,summary_model=p_model where id=saved.id;
     perform set_config('request.jwt.claim.sub',coalesce(previous_owner,''),true);
     return jsonb_build_object('complete',true,'coverage_end',start_sequence,'summary_pending',true,'checkpoint_published',false,'maintenance_id',saved.id);
   end if;
   select coalesce(c.evidence,'[]'),coalesce(c.manifest->'sources','[]') into evidence,manifest_sources
     from public.user_lifetime_checkpoint c where c.id=predecessor and c.lossless;
   evidence:=coalesce(evidence,'[]');manifest_sources:=coalesce(manifest_sources,'[]');
   -- The project lock and timeline admission remain held through predecessor
   -- CAS and every derived write. All exact windows/tombstones were scanned.
   if identity.checkpoint_id is distinct from saved.predecessor_id or
     saved.item_count<>(select count(*) from public.user_lifetime_covered_evidence where maintenance_id=saved.id) then
     raise exception 'checkpoint predecessor or coverage changed' using errcode='PT409';end if;
   for item in select c.*,s.language,substring(s.text from c.char_start+1 for c.char_end-c.char_start) original
     from public.user_lifetime_covered_evidence c join public.user_narrator_source s
       on s.user_id=owner and s.project_id=snap.project_id and s.id=c.source_id and s.version=c.version and s.status='active'
     where c.maintenance_id=saved.id and c.status='active' order by c.sequence,c.char_start loop
     evidence:=evidence||jsonb_build_array(jsonb_build_object('schema_version',1,'source_id',item.source_id,'version',item.version,
       'char_start',item.char_start,'char_end',item.char_end,'original',item.original,'language',item.language,
       'role','storyteller','assertion','asserted','allowed_use',jsonb_build_array('conversation'),'policy_epoch',project.policy_epoch));
     if not manifest_sources @> jsonb_build_array(jsonb_build_object('schema_version',1,'source_id',item.source_id,'version',item.version)) then
       manifest_sources:=manifest_sources||jsonb_build_array(jsonb_build_object('schema_version',1,'source_id',item.source_id,'version',item.version));
     end if;
   end loop;
   insert into public.user_lifetime_checkpoint(user_id,conversation_id,predecessor_id,fence,coverage_end,model,prompt_version,pinned,
     manifest,evidence,published,coverage_proof_id,lossless) values(owner,snap.conversation_id,predecessor,checkpoint_fence,end_sequence,p_model,'lifetime-v1',pins,
       jsonb_build_object('schema_version',1,'identity',checkpoint_fence->'identity','policy_epoch',project.policy_epoch,
         'source_revision',project.source_sequence,'sources',manifest_sources),evidence,true,saved.id,true) returning id into candidate;
   update public.user_lifetime_conversation set checkpoint_id=candidate where user_id=owner and conversation_id=snap.conversation_id
     and checkpoint_id is not distinct from predecessor;
   if not found then raise exception 'checkpoint CAS failed' using errcode='PT409';end if;
 end if;
 perform set_config('request.jwt.claim.sub',coalesce(previous_owner,''),true);
 return jsonb_build_object('complete',saved.complete,'coverage_end',case when saved.complete then end_sequence else start_sequence end,
   'proof_revision',saved.revision);
end $function$;

CREATE OR REPLACE FUNCTION public.read_user_interview_turn_before_recordings(p_project_id text, p_client_turn_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
begin
 return public.read_user_interview_turn_before_phase(p_project_id,p_client_turn_id);
end
$function$;

CREATE OR REPLACE FUNCTION public.attach_guest_conversation_before_lifetime(p_token text, p_guest_wins boolean DEFAULT false)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
begin
 return public.attach_guest_conversation_before_phase(p_token,p_guest_wins);
end
$function$;

CREATE OR REPLACE FUNCTION public.read_lifetime_memoir_lane_page_before_strategy(p_lane_id uuid, p_token uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'auth'
AS $function$
declare page jsonb; descriptor jsonb;
begin
 page:=public.read_lifetime_memoir_lane_page_before_two_lanes(p_lane_id,p_token);
 if exists(select 1 from public.lifetime_two_lane_rollout where singleton and enabled)
   and exists(select 1 from public.user_lifetime_two_lane_source where user_id=(page->>'user_id')::uuid and project_id=page->>'project_id') then
   page:=page||jsonb_build_object('two_lane_maintenance_required',true);
 end if;
 if page->>'skill'='timeline' and exists(select 1 from public.lifetime_two_lane_rollout where singleton and enabled) and exists(select 1 from public.user_lifetime_two_lane_source m
   where m.user_id=(page->>'user_id')::uuid and m.project_id=page->>'project_id' and m.source_id=(page->'source'->>'id')::uuid) then
   select jsonb_build_object('schema_version',1,'task_version','two-lane-v1','execution_generation',c.execution_generation,
     'phase_revision',0,'work_mode',case when t.collector is null and exists(select 1 from public.user_agent_turn_lease a
       where a.user_id=c.user_id and a.expires_at>clock_timestamp()) then 'pending'
       when t.source_version=(page->'source'->>'version')::bigint
       and t.collector->'plan'->'work'->>'mode'='reply_only' then 'reply_only' else 'extract' end) into descriptor
   from public.user_lifetime_conversation c
   left join public.user_interview_turn t on t.user_id=c.user_id and t.project_id=c.project_id and t.source_id=(page->'source'->>'id')::uuid
   where c.user_id=(page->>'user_id')::uuid and c.conversation_id=(page->>'conversation_id')::uuid;
   page:=(page-'input_digest'-'page_digest')||jsonb_build_object('two_lane',descriptor);
   page:=page||jsonb_build_object('input_digest',encode(sha256(convert_to((page-'token')::text,'UTF8')),'hex'));
   page:=page||jsonb_build_object('page_digest',encode(sha256(convert_to(page::text,'UTF8')),'hex'));
 end if;
 if page ? 'two_lane_maintenance_required' then
   page:=page-'input_digest'-'page_digest';
   page:=page||jsonb_build_object('input_digest',encode(sha256(convert_to((page-'token')::text,'UTF8')),'hex'));
   page:=page||jsonb_build_object('page_digest',encode(sha256(convert_to(page::text,'UTF8')),'hex'));
 end if;
 return page;
end $function$;

CREATE OR REPLACE FUNCTION public.save_lifetime_interview_plan(p_snapshot_fence jsonb, p_project_id text, p_client_turn_id uuid, p_plan jsonb, p_associations jsonb, p_lease_token uuid, p_reply text DEFAULT NULL::text, p_response_photo_ids jsonb DEFAULT '[]'::jsonb, p_thread_id text DEFAULT NULL::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
begin
 return public.save_lifetime_interview_plan_core(p_snapshot_fence,p_project_id,p_client_turn_id,p_plan,
   p_associations,p_lease_token,p_reply,p_response_photo_ids,p_thread_id);
end
$function$;

CREATE OR REPLACE FUNCTION public.accept_user_interview_turn_before_pending_guard(p_project_id text, p_client_turn_id uuid, p_text text, p_kind text DEFAULT 'narrator_chat'::text, p_language text DEFAULT 'en-AU'::text, p_uploaded_photo_ids jsonb DEFAULT '[]'::jsonb, p_photo_selection jsonb DEFAULT NULL::jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
begin
 return public.accept_user_interview_turn_before_phase(p_project_id,p_client_turn_id,p_text,p_kind,p_language,
   p_uploaded_photo_ids,p_photo_selection);
end
$function$;

-- Preserve the retired preferences for recovery; no application role can read or change them.
drop trigger formal_phase_invalidation on public.user_conversation_phase;
drop function public.change_user_conversation_phase(text,text,bigint);
drop function public.read_user_conversation_phase(text);
drop function public.conversation_phase_action(text);
drop function public.conversation_phase_record(public.user_conversation_phase);
revoke all on public.user_conversation_phase from public,anon,authenticated,service_role;
alter table public.user_conversation_phase rename to user_conversation_phase_archive;

notify pgrst,'reload schema';
commit;
