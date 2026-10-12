-- Governed reply, phase plan, usage receipt and execution pointer share one commit.
begin;
create table public.user_lifetime_reply (
 user_id uuid not null, conversation_id uuid not null, client_turn_id uuid not null,
 memory_id uuid not null references public.user_memory(id),
 policy_epoch bigint not null, source_revision bigint not null,
 execution_generation bigint not null, phase_revision bigint not null,
 preference_revision bigint not null, model text not null, prompt_version text not null,
 primary key(user_id,conversation_id,client_turn_id),
 foreign key(user_id,conversation_id) references public.user_lifetime_conversation(user_id,conversation_id)
);
alter table public.user_lifetime_reply enable row level security;
revoke all on public.user_lifetime_reply from public,anon,authenticated;
create function public.commit_lifetime_turn(p_fence jsonb,p_client_turn_id uuid,p_plan jsonb,p_associations jsonb,
 p_reply text,p_response_photo_ids jsonb,p_thread_id text,p_prompt_version text,p_model text,p_continuity_updates jsonb default '[]') returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare owner uuid:=auth.uid(); conversation uuid:=(p_fence->'identity'->>'conversation_id')::uuid;
 project text; accepted public.user_interview_turn%rowtype; source public.user_narrator_source%rowtype;
 interview jsonb; memory jsonb; next_fence jsonb; prior public.user_lifetime_reply%rowtype;
begin
 select project_id into project from public.user_lifetime_conversation where user_id=owner and conversation_id=conversation;
 if not found then raise exception 'conversation unavailable'; end if;
 perform 1 from public.user_memoir_project where user_id=owner and project_id=project for update;
 perform public.lock_lifetime_publication(p_fence);
 if length(coalesce(p_model,'')) not between 1 and 200 or length(coalesce(p_prompt_version,'')) not between 1 and 100 then raise exception 'execution compatibility required'; end if;
 select * into accepted from public.user_interview_turn where user_id=owner and project_id=project and client_turn_id=p_client_turn_id;
 if not found then raise exception 'accepted narrator turn required'; end if;
 select * into prior from public.user_lifetime_reply where user_id=owner and conversation_id=conversation and client_turn_id=p_client_turn_id;
 if found then
   if accepted.collector->>'thread_id' is distinct from p_thread_id or accepted.collector->>'reply' is distinct from p_reply
     or prior.model is distinct from p_model or prior.prompt_version is distinct from p_prompt_version then
     raise exception 'saved execution identity conflict'; end if;
   select jsonb_build_array(to_jsonb(m)) into memory from public.user_memory m where m.user_id=owner and m.id=prior.memory_id;
   return jsonb_build_object('memory',memory,'interview',public.read_user_interview_turn(project,p_client_turn_id),'fence',p_fence);
 end if;
 select * into source from public.user_narrator_source where user_id=owner and project_id=project and id=accepted.source_id
   and version=accepted.source_version and status='active';
 if not found then raise exception 'active exact narrator source required'; end if;
 interview:=public.save_user_interview_plan(project,p_client_turn_id,p_plan,p_associations,(p_fence->>'lease_token')::uuid,
   p_reply,p_response_photo_ids,p_thread_id);
 if p_plan->'work'->>'mode'='reply_only' and p_plan->'work'->>'name' is not null then
   -- Retain exact source/version authority and preserve independent settings.
   perform public.persist_lifetime_chosen_name(conversation,source.id,source.version,p_plan->'work'->>'name');
 end if;
 next_fence:=public.capture_lifetime_fence(conversation,(p_fence->>'lease_token')::uuid);
 next_fence:=public.persist_lifetime_continuity_updates(next_fence,p_continuity_updates,false);
 -- Only this accepted plan's validated phase/name/continuity changes can advance the fence.
 -- All locks stay held, so no external correction/preference/source can intervene.
 next_fence:=public.capture_lifetime_fence(conversation,(p_fence->>'lease_token')::uuid);
 if next_fence-'phase_revision'-'preference_revision' is distinct from p_fence-'phase_revision'-'preference_revision' then raise exception 'unexpected execution mutation'; end if;
 memory:=public.commit_user_agent_turn_before_lifetime_adoption((p_fence->>'lease_token')::uuid,p_thread_id,
   'Storyteller: '||source.text||E'\nMemory Spark: '||p_reply,'{}'::text[],null,project,p_client_turn_id,true,'unplaced');
 insert into public.user_lifetime_reply values(owner,conversation,p_client_turn_id,(memory->0->>'id')::uuid,
   (next_fence->>'policy_epoch')::bigint,(next_fence->>'source_revision')::bigint,(next_fence->>'execution_generation')::bigint,
   (next_fence->>'phase_revision')::bigint,(next_fence->>'preference_revision')::bigint,p_model,p_prompt_version)
   on conflict do nothing;
 update public.user_lifetime_conversation set thread_schema_version=1,thread_id=p_thread_id,thread_model=p_model,thread_prompt_version=p_prompt_version,
   thread_policy_epoch=(next_fence->>'policy_epoch')::bigint where user_id=owner and conversation_id=conversation;
 return jsonb_build_object('memory',memory,'interview',interview,'fence',next_fence);
end $$;
create function public.read_lifetime_reply(p_conversation_id uuid,p_client_turn_id uuid) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
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
   'context_rebuild_required',not coalesce(valid,false),'conversation_phase',public.read_user_conversation_phase(identity.project_id));
end $$;
revoke all on function public.commit_lifetime_turn(jsonb,uuid,jsonb,jsonb,text,jsonb,text,text,text,jsonb),public.read_lifetime_reply(uuid,uuid) from public,anon;
grant execute on function public.commit_lifetime_turn(jsonb,uuid,jsonb,jsonb,text,jsonb,text,text,text,jsonb),public.read_lifetime_reply(uuid,uuid) to authenticated;
-- Bounded event identity/context for interview prompts. The canonical evidence
-- and relationship history remain behind explicit, owner-scoped page retrieval.
-- Never call memory_event_record here: one event can have lifetime-sized links.
create function public.bounded_lifetime_event_record(e public.user_memory_event) returns jsonb
language plpgsql stable security definer set search_path='' as $$
declare refs jsonb; more boolean; result jsonb;
begin
 select coalesce(jsonb_agg(item order by key),'[]') into refs from (
   select s.source_id::text||':'||s.source_version::text||':'||s.evidence_hash key,
     jsonb_build_object('source_id',s.source_id,'version',s.source_version,
       'char_start',s.evidence->'char_start','char_end',s.evidence->'char_end') item
   from public.user_memory_event_source s join public.user_narrator_source n
     on n.user_id=s.user_id and n.project_id=s.project_id and n.id=s.source_id and n.version=s.source_version and n.status='active'
   where s.user_id=e.user_id and s.project_id=e.project_id and s.event_id=e.id
   order by key limit 9) bounded;
 more:=jsonb_array_length(refs)>8;
 if more then refs:=refs-8;end if;
 result:=jsonb_build_object('id',e.id,'revision',e.revision,'kind',e.kind,'status',e.status,'life_stage',e.life_stage,
   'change_sequence',e.change_sequence,'title',left(e.data->>'title',300),
   'title_complete',length(coalesce(e.data->>'title',''))<=300,
   'temporal',jsonb_build_object('expression',left(e.data->'temporal'->>'expression',500),
     'precision',left(e.data->'temporal'->>'precision',20),
     'year_start',case when e.data->'temporal'->>'year_start'~'^[0-9]{1,4}$' then e.data->'temporal'->'year_start' else null end,
     'year_end',case when e.data->'temporal'->>'year_end'~'^[0-9]{1,4}$' then e.data->'temporal'->'year_end' else null end),
   'temporal_complete',length(coalesce(e.data->'temporal'->>'expression',''))<=500,
   'uncertainty',left(e.data->>'uncertainty',1000),'uncertainty_complete',length(coalesce(e.data->>'uncertainty',''))<=1000,
   'assertion',case when e.data->>'assertion' in ('asserted','inferred') then e.data->>'assertion' else 'unspecified' end,
   'timing_conflict',e.data->'timing_conflict'='true'::jsonb,
   'source_refs',refs,'reference_identity_complete',not more,'evidence_complete',jsonb_array_length(refs)=0,
   'evidence_retrieval','read_lifetime_collection_page:event_sources',
   'details_complete',not exists(select 1 from unnest(array['temporal_accounts','relations','candidate_ids','supersedes','contradicts']) k
     where jsonb_typeof(e.data->k)='array' and jsonb_array_length(e.data->k)>0),
   'details_retrieval','read_lifetime_collection_page:event_details');
 return result;
end $$;
revoke all on function public.bounded_lifetime_event_record(public.user_memory_event) from public,anon,authenticated;
create function public.read_lifetime_interview_context(p_conversation_id uuid) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
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
   'conversation_phase',public.read_user_conversation_phase(project),
   'has_accepted_narration',public.conversation_has_narration(owner,project));
end $$;
create function public.read_lifetime_tail(p_conversation_id uuid,p_policy_epoch bigint,p_after_sequence bigint,p_through_sequence bigint)
returns jsonb language plpgsql security definer set search_path=public,auth as $$
declare owner uuid:=auth.uid(); project text; epoch bigint; high_water bigint; row record;
 records jsonb:='[]'; tombstones jsonb:='[]'; item jsonb; reply_row record; bytes integer:=0; seen bigint:=0; complete boolean:=true;
begin
 select project_id into project from public.user_lifetime_conversation where user_id=owner and conversation_id=p_conversation_id;
 if not found then raise exception 'conversation unavailable'; end if;
 select policy_epoch,source_sequence into epoch,high_water from public.user_memoir_project where user_id=owner and project_id=project for share;
 if p_policy_epoch is distinct from epoch then raise exception 'stale tail epoch'; end if;
 if p_after_sequence<0 or p_through_sequence<p_after_sequence or p_through_sequence>high_water then raise exception 'invalid tail range'; end if;
 for row in select p.sequence as position_sequence,p.version as position_version,s as source from public.user_lifetime_source_position p
 join public.user_narrator_source s on s.user_id=p.user_id and s.project_id=p.project_id and s.id=p.source_id
 where p.user_id=owner and p.project_id=project and p.sequence>p_after_sequence and p.sequence<=p_through_sequence
 order by p.sequence limit 17 loop
   seen:=seen+1;
   if seen>16 or bytes+octet_length((row.source).text)>32768 then complete:=false;exit;end if;
   if (row.source).status<>'active' or row.position_version<>(row.source).version then
     tombstones:=tombstones||to_jsonb(row.position_sequence);
   else
     item:=public.narrator_source_record(row.source);
     select r.policy_epoch,r.preference_revision,r.execution_generation,t.collector->>'reply' as reply into reply_row
       from public.user_lifetime_reply r join public.user_interview_turn t on t.user_id=r.user_id and t.project_id=project and t.client_turn_id=r.client_turn_id
       join public.user_lifetime_conversation l on l.user_id=r.user_id and l.conversation_id=r.conversation_id
       where r.user_id=owner and r.conversation_id=p_conversation_id and r.client_turn_id=(row.source).client_turn_id
         and r.policy_epoch=epoch and r.preference_revision=l.preference_revision and r.execution_generation=l.execution_generation;
     if found then item:=item||jsonb_build_object('conversation_saved',true,'assistant_reply',reply_row.reply,'reply_policy_epoch',epoch); end if;
     bytes:=bytes+octet_length(item::text);
     if bytes>32768 then complete:=false;exit;end if;
     records:=records||jsonb_build_array(item);
   end if;
 end loop;
 complete:=complete and seen=p_through_sequence-p_after_sequence;
 return jsonb_build_object('records',records,'tombstones',tombstones,'complete',complete,
   'after_sequence',p_after_sequence,'through_sequence',p_through_sequence);
end $$;
revoke all on function public.read_lifetime_interview_context(uuid),public.read_lifetime_tail(uuid,bigint,bigint,bigint) from public,anon;
grant execute on function public.read_lifetime_interview_context(uuid),public.read_lifetime_tail(uuid,bigint,bigint,bigint) to authenticated;
create function public.validate_lifetime_replay_input(p_conversation_id uuid,p_client_turn_id uuid,p_text text,p_kind text)
returns boolean language plpgsql security definer set search_path=public,auth as $$
declare project text; accepted public.user_interview_turn%rowtype; kind text;
begin
 select project_id into project from public.user_lifetime_conversation where user_id=auth.uid() and conversation_id=p_conversation_id;
 if not found then raise exception 'conversation unavailable'; end if;
 select * into accepted from public.user_interview_turn where user_id=auth.uid() and project_id=project and client_turn_id=p_client_turn_id;
 if not found then return false; end if;
 select s.kind into kind from public.user_narrator_source s where s.user_id=auth.uid() and s.project_id=project and s.id=accepted.source_id;
 if accepted.input_hash is distinct from md5(p_text) or kind is distinct from p_kind then
   raise exception 'input revision conflict; retry the original accepted input' using errcode='40001'; end if;
 return true;
end $$;
create function public.set_lifetime_language(p_fence jsonb,p_language text,p_explicit boolean default false)
returns text language plpgsql security definer set search_path=public,auth as $$
declare owner uuid:=auth.uid(); project text; selected text;
begin
 select project_id into project from public.user_lifetime_conversation where user_id=owner and conversation_id=(p_fence->'identity'->>'conversation_id')::uuid;
 if not found then raise exception 'conversation unavailable'; end if;
 perform 1 from public.user_memoir_project where user_id=owner and project_id=project for update;
 perform public.lock_lifetime_publication(p_fence);
 if p_language not in ('en-AU','zh-CN') or p_explicit is null then raise exception 'invalid language selection'; end if;
 select profile->>'preferred_language' into selected from public.user_profile where user_id=owner for update;
 if p_explicit or selected is null or selected not in ('en-AU','zh-CN') then
   update public.user_profile set profile=jsonb_set(profile,'{preferred_language}',to_jsonb(p_language)) where user_id=owner;
   selected:=p_language;
 end if;
 return selected;
end $$;
revoke all on function public.validate_lifetime_replay_input(uuid,uuid,text,text),public.set_lifetime_language(jsonb,text,boolean) from public,anon;
grant execute on function public.validate_lifetime_replay_input(uuid,uuid,text,text),public.set_lifetime_language(jsonb,text,boolean) to authenticated;

commit;
