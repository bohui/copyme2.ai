-- Issue 59: additive authoritative phase state. No historical identity merge.
begin;
create table if not exists public.user_conversation_phase (
 user_id uuid not null, project_id text not null,
 phase text not null check(phase in ('comfort','explore','shape')),
 selection text not null default 'automatic' check(selection in ('automatic','explicit')),
 preferred_phase text check(preferred_phase in ('comfort','explore','shape')),
 paused boolean not null default false,
 revision bigint not null default 0 check(revision>=0),
 reason text not null check(reason in ('new_journey','saved_narration','narrator_choice','narration','pause','resume','skip','correction')),
 source_turn_id uuid,
 primary key(user_id,project_id),
 foreign key(user_id,project_id) references public.user_memoir_project on delete cascade,
 check((selection='explicit')=(preferred_phase is not null))
);
alter table public.user_conversation_phase enable row level security;
revoke all on public.user_conversation_phase from public,anon,authenticated;
grant select on public.user_conversation_phase to authenticated;
drop policy if exists phase_owner on public.user_conversation_phase;
create policy phase_owner on public.user_conversation_phase for select to authenticated using(user_id=auth.uid());

create or replace function public.conversation_phase_record(s public.user_conversation_phase) returns jsonb
language sql immutable set search_path='' as $$
 select (to_jsonb(s)-'user_id'-'project_id') || jsonb_build_object('schema_version',1)
$$;

create or replace function public.conversation_has_narration(p_owner uuid,p_project text) returns boolean
language sql stable security definer set search_path='' as $$
 select exists(select 1 from public.user_narrator_source n where n.user_id=p_owner
   and n.project_id=p_project and n.status='active' and not exists(select 1 from public.user_interview_turn t
     where t.user_id=n.user_id and t.project_id=n.project_id and t.source_id=n.id
     and (t.collector is null or t.collector->'plan'->'work'->>'mode'='reply_only')))
 or exists(select 1 from public.user_memory m where m.user_id=p_owner and m.project_id=p_project
   and m.kind='agent' and m.content like 'Storyteller: %' and position(E'\nMemory Spark: ' in m.content)>0
   and not exists(select 1 from public.user_interview_turn t where t.user_id=m.user_id
     and t.project_id=m.project_id and t.client_turn_id=m.client_turn_id));
$$;
revoke all on function public.conversation_has_narration(uuid,text) from public,anon,authenticated;

create or replace function public.read_user_conversation_phase(p_project_id text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare narrated boolean; s public.user_conversation_phase%rowtype;
begin
 if auth.uid() is null then raise exception 'authenticated user required' using errcode='42501'; end if;
 perform 1 from public.user_memoir_project where user_id=auth.uid() and project_id=p_project_id for update;
 if not found then raise exception 'project unavailable' using errcode='42501'; end if;
 select * into s from public.user_conversation_phase where user_id=auth.uid() and project_id=p_project_id;
 if not found then
   -- Current unsaved intake is not prior accepted narration. No text-length,
   -- account allowance, life-stage or browser-message heuristic is used.
   narrated:=public.conversation_has_narration(auth.uid(),p_project_id);
   insert into public.user_conversation_phase(user_id,project_id,phase,reason)
   values(auth.uid(),p_project_id,case when narrated then 'explore' else 'comfort' end,
     case when narrated then 'saved_narration' else 'new_journey' end)
   on conflict do nothing;
   select * into s from public.user_conversation_phase where user_id=auth.uid() and project_id=p_project_id;
 end if;
 return public.conversation_phase_record(s);
end $$;

create or replace function public.change_user_conversation_phase(p_project_id text,p_action text,p_expected_revision bigint) returns jsonb
language plpgsql security definer set search_path='' as $$
declare current jsonb; s public.user_conversation_phase%rowtype; automatic_phase text;
begin
 current:=public.read_user_conversation_phase(p_project_id);
 if p_expected_revision is null or p_expected_revision<>(current->>'revision')::bigint then
   raise exception 'conversation choice changed; reload' using errcode='40001'; end if;
 if p_action is null or p_action not in ('comfort','explore','shape','automatic','pause','resume','skip') then
   raise exception 'unknown conversation control' using errcode='22023'; end if;
 select case when public.conversation_has_narration(auth.uid(),p_project_id) then 'explore' else 'comfort' end into automatic_phase;
 if (p_action in ('comfort','explore','shape') and current->>'phase'=p_action and current->>'preferred_phase'=p_action)
   or (p_action='pause' and (current->>'paused')::boolean)
   or (p_action='resume' and not (current->>'paused')::boolean)
   or (p_action='automatic' and current->>'selection'='automatic' and current->>'phase'=automatic_phase) then
   return current;
 end if;
 update public.user_conversation_phase set
   phase=case when p_action in ('comfort','explore','shape') then p_action when p_action='automatic' then automatic_phase else phase end,
   selection=case when p_action in ('comfort','explore','shape') then 'explicit' when p_action='automatic' then 'automatic' else selection end,
   preferred_phase=case when p_action in ('comfort','explore','shape') then p_action when p_action='automatic' then null else preferred_phase end,
   paused=case when p_action='pause' then true when p_action='resume' then false else paused end,
   revision=revision+1, source_turn_id=null,
   reason=case when p_action in ('pause','resume','skip') then p_action else 'narrator_choice' end
 where user_id=auth.uid() and project_id=p_project_id returning * into s;
 return public.conversation_phase_record(s);
end $$;

do $$ begin
 if to_regprocedure('public.read_user_interview_context_before_phase(text)') is null then
  alter function public.read_user_interview_context(text) rename to read_user_interview_context_before_phase;
 end if;
end $$;
create or replace function public.read_user_interview_context(p_project_id text) returns jsonb
language plpgsql security definer set search_path='' as $$
begin
 return public.read_user_interview_context_before_phase(p_project_id) ||
   jsonb_build_object('conversation_phase',public.read_user_conversation_phase(p_project_id),
     'has_accepted_narration',public.conversation_has_narration(auth.uid(),p_project_id));
end $$;

create or replace function public.conversation_phase_action(p_text text) returns text
language plpgsql immutable set search_path='' as $$
declare sentence text; candidate text; candidates text[]; part text; selected text;
begin
 if coalesce(p_text,'') ~* '["“”「」『』`]|\m(?:said|says|told|asked)\M|(?:说|說|告诉|告訴)[：:]?' then return null; end if;
 foreach sentence in array regexp_split_to_array(coalesce(p_text,''),'[.!?。！？\n]') loop
 candidates:=array[btrim(sentence)];
 if sentence !~* '["“”‘’「」『』]|(?:he|she|they) said|[他她]说' then
   foreach part in array (regexp_split_to_array(sentence,'[,，]'))[2:] loop
     if part ~* '^\s*(?:I want to |I would like to |我想)' then candidates:=array_append(candidates,btrim(part)); end if;
   end loop;
 end if;
 foreach candidate in array candidates loop
 if candidate ~* '^((?:please |I want to |I would like to |let''s |can we )?(?:pause|stop)(?: (?:the interview|for now))?(?: please)?|(?:请|我想|我们先)?(?:暂停|停止)(?:采访|一下)?|不想继续了|先不聊了|不要再问(?:我)?(?:了)?|今天就到这里|(?:please )?(?:stop asking(?: me)? questions|don''t ask(?: me)? (?:any )?more questions|do not ask(?: me)? (?:any )?more questions))$' then selected:='pause'; end if;
 if candidate ~* '^((?:please |I want to |let''s |can we )?(?:resume|continue the interview)(?: please)?|(?:请|我想)?(?:恢复采访|继续采访))$' then selected:='resume'; end if;
 if candidate ~* '^((?:please )?(?:keep talking|keep it gentle|let''s take it slowly)|(?:请)?(?:轻松聊聊|慢慢聊|随便聊聊))$' then selected:='comfort'; end if;
 if candidate ~* '^((?:please )?(?:explore my memories|let''s explore|let''s get straight into it)|(?:请)?(?:深入回忆|直接开始回忆|探索回忆))$' then selected:='explore'; end if;
 if candidate ~* '^((?:please |I want to |can we )?(?:shape my story|organize my story|organise my story|help me (?:shape|organize|organise|review) my story)|(?:请|我想)?(?:整理我的故事|帮我整理故事|回顾我的故事))$' then selected:='shape'; end if;
 if candidate ~* '^((?:please )?(?:use automatic guidance|return to automatic guidance)|(?:请)?(?:恢复自动引导|自动引导))$' then selected:='automatic'; end if;
 if candidate ~* '^((?:please |can we )?(?:skip(?: this question)?|try another topic|change (?:the )?topic)|(?:请)?(?:跳过(?:这个问题)?|换个话题))$' then selected:='skip'; end if;
 end loop;
 end loop;
 return selected;
end $$;
revoke all on function public.conversation_phase_action(text) from public,anon,authenticated;

-- Capture intent ordering at admission, never at a later context read/retry.
alter table public.user_interview_turn add column if not exists phase_revision bigint check(phase_revision>=0);
do $$ begin
 if to_regprocedure('public.accept_user_interview_turn_before_phase(text,uuid,text,text,text,jsonb,jsonb)') is null then
   alter function public.accept_user_interview_turn(text,uuid,text,text,text,jsonb,jsonb) rename to accept_user_interview_turn_before_phase;
 end if;
end $$;
create or replace function public.accept_user_interview_turn(p_project_id text,p_client_turn_id uuid,p_text text,
 p_kind text default 'narrator_chat',p_language text default 'en-AU',p_uploaded_photo_ids jsonb default '[]',p_photo_selection jsonb default null)
returns jsonb language plpgsql security definer set search_path='' as $$
declare existed boolean; result jsonb; current jsonb; baseline bigint;
begin
 select exists(select 1 from public.user_interview_turn where user_id=auth.uid() and project_id=p_project_id
   and client_turn_id=p_client_turn_id) into existed;
 result:=public.accept_user_interview_turn_before_phase(p_project_id,p_client_turn_id,p_text,p_kind,p_language,p_uploaded_photo_ids,p_photo_selection);
 current:=public.read_user_conversation_phase(p_project_id);
 if not existed then
   update public.user_interview_turn set phase_revision=(current->>'revision')::bigint
   where user_id=auth.uid() and project_id=p_project_id and client_turn_id=p_client_turn_id and phase_revision is null;
 end if;
 select phase_revision into baseline from public.user_interview_turn where user_id=auth.uid()
   and project_id=p_project_id and client_turn_id=p_client_turn_id;
 return result || jsonb_build_object('phase_revision',baseline);
end $$;
revoke all on function public.accept_user_interview_turn_before_phase(text,uuid,text,text,text,jsonb,jsonb),
 public.accept_user_interview_turn(text,uuid,text,text,text,jsonb,jsonb) from public,anon,authenticated;
grant execute on function public.accept_user_interview_turn(text,uuid,text,text,text,jsonb,jsonb) to authenticated;

-- Keep the latest news/work/photo validator intact. Phase is a separate typed
-- boundary, never an extra unvalidated key in the saved interview plan.
do $$ begin
 if to_regprocedure('public.save_user_interview_plan_before_phase(text,uuid,jsonb,jsonb,uuid,text,jsonb,text)') is null then
  alter function public.save_user_interview_plan(text,uuid,jsonb,jsonb,uuid,text,jsonb,text) rename to save_user_interview_plan_before_phase;
 end if;
end $$;
create or replace function public.save_user_interview_plan(p_project_id text,p_client_turn_id uuid,p_plan jsonb,p_associations jsonb,p_lease_token uuid,
 p_reply text default null,p_response_photo_ids jsonb default '[]',p_thread_id text default null)
returns jsonb language plpgsql security definer set search_path='' as $$
declare current jsonb; result jsonb; update_phase jsonb:=p_plan->'phase_update'; action text; source_text text;
 old public.user_interview_turn%rowtype; desired text;
begin
 current:=public.read_user_conversation_phase(p_project_id);
 select * into old from public.user_interview_turn where user_id=auth.uid() and project_id=p_project_id and client_turn_id=p_client_turn_id;
 -- The delegated validator still checks owner/lease/source/policy before replay.
 if old.collector is not null then
   return public.save_user_interview_plan_before_phase(p_project_id,p_client_turn_id,p_plan-'phase_update',p_associations,p_lease_token,p_reply,p_response_photo_ids,p_thread_id);
 end if;
 if update_phase is not null then
   if jsonb_typeof(update_phase) is distinct from 'object' or
     (select count(*) from jsonb_object_keys(update_phase))<>2 or
     not (update_phase ?& array['phase','expected_revision']) or
     jsonb_typeof(update_phase->'expected_revision') is distinct from 'number' or
     update_phase->>'expected_revision' !~ '^[0-9]+$' or
     (update_phase->'phase'<>'null'::jsonb and update_phase->>'phase' not in ('comfort','explore')) then
     raise exception 'invalid phase proposal' using errcode='22023'; end if;
   if (update_phase->>'expected_revision')::bigint<>(current->>'revision')::bigint then
     raise exception 'conversation choice changed; retry accepted turn' using errcode='40001'; end if;
 end if;
 select text into source_text from public.user_narrator_source where user_id=auth.uid() and project_id=p_project_id and id=old.source_id and version=old.source_version and status='active';
 action:=public.conversation_phase_action(source_text);
 -- A later explicit choice supersedes intent in an earlier admitted source.
 -- Its narration may still finish against the new state; retries never refresh
 -- the admission baseline. Legacy rows with no baseline are conservative.
 if old.phase_revision is distinct from (current->>'revision')::bigint then action:=null; end if;
 if ((current->>'paused')::boolean and action is distinct from 'resume') or action='pause' then
   if jsonb_array_length(p_plan->'candidates')<>0 or p_plan->>'chosen_id' is not null then
     raise exception 'paused conversation cannot ask a question' using errcode='22023'; end if;
 end if;
 result:=public.save_user_interview_plan_before_phase(p_project_id,p_client_turn_id,p_plan-'phase_update',p_associations,p_lease_token,p_reply,p_response_photo_ids,p_thread_id);
 if action is not null then
   current:=public.change_user_conversation_phase(p_project_id,action,(current->>'revision')::bigint);
   update public.user_conversation_phase set source_turn_id=p_client_turn_id where user_id=auth.uid() and project_id=p_project_id;
 elsif update_phase->>'phase' is not null and current->>'selection'='automatic' and not (current->>'paused')::boolean then
   desired:=update_phase->>'phase';
   update public.user_conversation_phase set phase=desired,revision=revision+1,reason='narration',source_turn_id=p_client_turn_id
   where user_id=auth.uid() and project_id=p_project_id and phase<>desired;
 end if;
 return result || jsonb_build_object('conversation_phase',public.read_user_conversation_phase(p_project_id));
end $$;

do $$ begin
 if to_regprocedure('public.read_user_interview_turn_before_phase(text,uuid)') is null then
  alter function public.read_user_interview_turn(text,uuid) rename to read_user_interview_turn_before_phase;
 end if;
end $$;
create or replace function public.read_user_interview_turn(p_project_id text,p_client_turn_id uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare result jsonb;
begin
 result:=public.read_user_interview_turn_before_phase(p_project_id,p_client_turn_id);
 if result is null then return null; end if;
 return result || jsonb_build_object('conversation_phase',public.read_user_conversation_phase(p_project_id),
   'phase_revision',(select phase_revision from public.user_interview_turn where user_id=auth.uid() and project_id=p_project_id and client_turn_id=p_client_turn_id));
end $$;

create or replace function public.correct_conversation_phase() returns trigger
language plpgsql security definer set search_path='' as $$
begin
 if new.version is distinct from old.version or new.status is distinct from old.status then
   update public.user_conversation_phase set phase='explore',revision=revision+1,reason='correction',source_turn_id=new.client_turn_id
   where user_id=new.user_id and project_id=new.project_id and phase='shape';
 end if;
 return new;
end $$;
drop trigger if exists conversation_phase_source_correction on public.user_narrator_source;
create trigger conversation_phase_source_correction after update of version,status on public.user_narrator_source
 for each row execute function public.correct_conversation_phase();

-- A workspace correction is current explicit user action. A delayed chat
-- correction may reopen exploration only if its admission preference is current.
do $$ begin
 if to_regprocedure('public.correct_user_memory_event_before_phase(text,text,bigint,jsonb,text,text,uuid)') is null then
   alter function public.correct_user_memory_event(text,text,bigint,jsonb,text,text,uuid) rename to correct_user_memory_event_before_phase;
 end if;
end $$;
create or replace function public.correct_user_memory_event(p_project_id text,p_event_id text,p_expected_revision bigint,
 p_patch jsonb,p_statement text,p_origin text default 'workspace',p_source_id uuid default null) returns jsonb
language plpgsql security definer set search_path='' as $$
declare result jsonb; baseline bigint; source_turn uuid;
begin
 result:=public.correct_user_memory_event_before_phase(p_project_id,p_event_id,p_expected_revision,p_patch,p_statement,p_origin,p_source_id);
 select t.phase_revision,s.client_turn_id into baseline,source_turn from public.user_narrator_source s
   left join public.user_interview_turn t on t.user_id=s.user_id and t.project_id=s.project_id and t.client_turn_id=s.client_turn_id
   where s.user_id=auth.uid() and s.project_id=p_project_id
     and s.id=coalesce(p_source_id,(select (value->>'source_id')::uuid from pg_catalog.jsonb_each(result->'user_overrides')
       where key in (select pg_catalog.jsonb_object_keys(p_patch)) limit 1));
 update public.user_conversation_phase set phase='explore',revision=revision+1,reason='correction',source_turn_id=source_turn
 where user_id=auth.uid() and project_id=p_project_id and phase='shape'
   and (p_origin='workspace' or baseline=revision);
 return result;
end $$;
revoke all on function public.correct_user_memory_event_before_phase(text,text,bigint,jsonb,text,text,uuid),
 public.correct_user_memory_event(text,text,bigint,jsonb,text,text,uuid) from public,anon,authenticated;
grant execute on function public.correct_user_memory_event(text,text,bigint,jsonb,text,text,uuid) to authenticated;

do $$ begin
 if to_regprocedure('public.attach_guest_conversation_before_phase(text,boolean)') is null then
  alter function public.attach_guest_conversation(text,boolean) rename to attach_guest_conversation_before_phase;
 end if;
end $$;
create or replace function public.attach_guest_conversation(p_token text,p_guest_wins boolean default false) returns jsonb
language plpgsql security definer set search_path='' as $$
declare result jsonb; guest uuid; project text; target uuid:=auth.uid();
begin
 result:=public.attach_guest_conversation_before_phase(p_token,p_guest_wins);
 guest:=(result->>'guest_user_id')::uuid;
 select project_id into project from public.user_conversation_attachment where user_id=target and id=(result->>'conversation_id')::uuid;
 if guest is null or project is null or guest=target then return result; end if;
 insert into public.user_conversation_phase(user_id,project_id,phase,selection,preferred_phase,paused,revision,reason,source_turn_id)
 select target,project,phase,selection,preferred_phase,paused,revision,reason,source_turn_id
 from public.user_conversation_phase where user_id=guest and project_id=project on conflict do nothing;
 return result;
end $$;

revoke all on function public.read_user_interview_turn_before_phase(text,uuid),public.read_user_interview_turn(text,uuid),
 public.correct_conversation_phase() from public,anon,authenticated;
grant execute on function public.read_user_interview_turn(text,uuid) to authenticated;
revoke all on function public.conversation_phase_record(public.user_conversation_phase),public.read_user_conversation_phase(text),
 public.change_user_conversation_phase(text,text,bigint),public.read_user_interview_context_before_phase(text),
 public.read_user_interview_context(text),public.save_user_interview_plan_before_phase(text,uuid,jsonb,jsonb,uuid,text,jsonb,text),
 public.save_user_interview_plan(text,uuid,jsonb,jsonb,uuid,text,jsonb,text),public.attach_guest_conversation_before_phase(text,boolean),
 public.attach_guest_conversation(text,boolean) from public,anon,authenticated;
grant execute on function public.read_user_conversation_phase(text),public.change_user_conversation_phase(text,text,bigint),
 public.read_user_interview_context(text),public.save_user_interview_plan(text,uuid,jsonb,jsonb,uuid,text,jsonb,text),
 public.attach_guest_conversation(text,boolean) to authenticated;
commit;
