-- Literal policy is atomic with new narrator acceptance and explicit edits.
-- No model/client completeness flags; unknown historical provenance stays pending.
begin;
create table public.user_lifetime_source_policy_receipt (
 user_id uuid not null, project_id text not null, conversation_id uuid not null,
 source_id uuid not null, source_version bigint not null check(source_version>0),
 parser_version text not null check(parser_version='literal-v1'),
 primary key(user_id,project_id,source_id),
 foreign key(user_id,project_id,source_id) references public.user_narrator_source(user_id,project_id,id) on delete cascade,
 foreign key(user_id,conversation_id) references public.user_lifetime_conversation(user_id,conversation_id) on delete cascade
);
create table public.user_lifetime_pending_policy (
 user_id uuid not null, project_id text not null, conversation_id uuid not null,
 source_id uuid not null, source_version bigint not null check(source_version>0),
 client_turn_id uuid not null, parser_version text not null check(parser_version='literal-v1'),
 primary key(user_id,project_id,source_id),
 foreign key(user_id,project_id,source_id) references public.user_narrator_source(user_id,project_id,id) on delete cascade,
 foreign key(user_id,conversation_id) references public.user_lifetime_conversation(user_id,conversation_id) on delete cascade
);
-- Mapping inventory is a durable conversation-level blocker. A single source
-- edit/withdrawal cannot prove that all other historical sources were reviewed.
create table public.user_lifetime_policy_inventory_pending (
 user_id uuid not null, project_id text not null, conversation_id uuid not null,
 parser_version text not null check(parser_version='literal-v1'),
 primary key(user_id,project_id),
 foreign key(user_id,conversation_id) references public.user_lifetime_conversation(user_id,conversation_id) on delete cascade
);
alter table public.user_lifetime_policy_inventory_pending enable row level security;
revoke all on public.user_lifetime_policy_inventory_pending from public,anon,authenticated,service_role;
create index lifetime_pending_policy_conversation on public.user_lifetime_pending_policy(user_id,conversation_id,source_id);
alter table public.user_lifetime_source_policy_receipt enable row level security;
alter table public.user_lifetime_pending_policy enable row level security;
revoke all on public.user_lifetime_source_policy_receipt,public.user_lifetime_pending_policy from public,anon,authenticated,service_role;

-- Existing identity upgrade boundary. Header-only inventory; no history scan
-- or automatic replay of completed/raw/edited historic preferences. Reconciliation
-- requires a separate, source-reviewed operator approval, never an owner flag.
insert into public.user_lifetime_policy_inventory_pending
 select c.user_id,c.project_id,c.conversation_id,'literal-v1'
 from public.user_lifetime_conversation c join public.user_memoir_project p using(user_id,project_id)
 where p.source_sequence>0 or exists(select 1 from public.user_narrator_source s
   where s.user_id=c.user_id and s.project_id=c.project_id) on conflict do nothing;
-- End upgrade inventory.

-- Exact-evidence compatibility lookups must not scan lifetime continuity rows.
create index lifetime_literal_policy_evidence on public.user_lifetime_continuity
 (user_id,conversation_id,kind,(data->'source_refs'->0->>'source_id'),
  (data->'source_refs'->0->>'version'),(data->'source_refs'->0->>'char_start'),(data->'source_refs'->0->>'char_end'))
 where kind in ('excluded_topic','paused_topic');

-- Same versioned literal forms as lifetime_memory_continuity.py. The parser
-- preserves complete original Unicode spans, never truncates explicit controls.
create function public.parse_lifetime_literal_policy(p_text text) returns jsonb
language plpgsql immutable set search_path='' as $body$
declare segment text; phrase text; kind text; cursor_at integer:=0; raw_start integer; quote_start integer;
 result jsonb:='[]';
begin
 if p_text is null or length(p_text)>100000 then raise exception 'invalid narrator text' using errcode='22023';end if;
 if p_text collate pg_catalog."C" ~* $reported$["“”‘「」『』`：:]|(?<!\w)['’]|['’](?!\w)|\y(?:said|says|told|asked|replied|wrote|written|whispered|shouted|reported|quoted|quote|caption|script|example|hypothetical|suppose|imagine)\y|(?:说|說|告诉|告訴|写道|寫道|写着|寫著|例如|假如|如果)$reported$ then return result;end if;
 for segment in select item[1] from regexp_matches(p_text collate pg_catalog."C",$segments$[^.!?。！？\r\n\u2028\u2029]+[.!?。！？]?$segments$,'g') item loop
   raw_start:=cursor_at+strpos(substring(p_text from cursor_at+1),segment)-1;
   cursor_at:=raw_start+length(segment);
   quote_start:=raw_start+length(segment)-length(regexp_replace(segment,'^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+',''));
   phrase:=regexp_replace(regexp_replace(segment,'^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+',''),'[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$','');
   if right(phrase,1) in ('?','？') then continue;end if;
   phrase:=regexp_replace(regexp_replace(phrase,'[.!。！]+$',''),'[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$','');
   if phrase='' or phrase collate pg_catalog."C" ~* $conditional$\y(?:if|unless|until|when|because|but|except|maybe|perhaps|whether)\y|(?:除非|如果|假如|也许|也許|可能|但是|不过|不過)$conditional$ then continue;end if;
   kind:=null;
    if phrase collate pg_catalog."C" ~* $pattern$^(?:(?:please[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+)?(?:do[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+not|don't|don’t|never)[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+(?:discuss|mention|ask[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+(?:me[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+)?about|bring[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+up)[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+.+)$$pattern$ then kind:='excluded_topic';
    elsif phrase collate pg_catalog."C" ~* $pattern$^(?:I[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+(?:do[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+not|don't|don’t)[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+want[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+to[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+(?:discuss|talk[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+about)[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+.+)$$pattern$ then kind:='excluded_topic';
    elsif phrase collate pg_catalog."C" ~* $pattern$^(?:(?:请|我)?(?:不要|别|不想)(?:再)?(?:讨论|谈|聊|提)(?:到|起)?[^，,：:；;]+)$$pattern$ then kind:='excluded_topic';
    elsif phrase collate pg_catalog."C" ~* $pattern$^(?:(?:(?:please|let's|let’s)[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+)?(?:set[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+aside|pause[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+discussing|pause[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+talking[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+about)[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+.+?(?:[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+for[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+now)?)$$pattern$ then kind:='paused_topic';
    elsif phrase collate pg_catalog."C" ~* $pattern$^(?:(?:我们|咱们)?先(?:不聊|不谈|暂停讨论)[^，,：:；;]+)$$pattern$ then kind:='paused_topic';
    end if;
   if kind is not null then
     if length(phrase)>500 then raise exception 'LIFETIME_POLICY_INPUT_LIMIT' using errcode='22023';end if;
     result:=result||jsonb_build_array(jsonb_build_object('kind',kind,'text',phrase,'char_start',quote_start,'char_end',quote_start+length(phrase)));
     if jsonb_array_length(result)>8 then raise exception 'LIFETIME_POLICY_INPUT_LIMIT' using errcode='22023';end if;
   end if;
 end loop;
 return result;
end $body$;
revoke all on function public.parse_lifetime_literal_policy(text) from public,anon,authenticated,service_role;

create function public.mark_lifetime_source_policy_pending() returns trigger
language plpgsql security definer set search_path='' as $$
declare conversation uuid;
begin
 select conversation_id into conversation from public.user_lifetime_conversation where user_id=new.user_id and project_id=new.project_id;
 if not found then return new;end if;
 -- Source mutators own project first; raw owner imports must obey the same order.
 perform 1 from public.user_memoir_project where user_id=new.user_id and project_id=new.project_id for update;
 if new.status<>'active' then
   delete from public.user_lifetime_pending_policy where user_id=new.user_id and project_id=new.project_id and source_id=new.id;
   delete from public.user_lifetime_source_policy_receipt where user_id=new.user_id and project_id=new.project_id and source_id=new.id;
 else
   insert into public.user_lifetime_pending_policy values(new.user_id,new.project_id,conversation,new.id,new.version,new.client_turn_id,'literal-v1')
   on conflict(user_id,project_id,source_id) do update set source_version=excluded.source_version,parser_version=excluded.parser_version;
 end if;
 return new;
end $$;
create trigger lifetime_source_policy_pending after insert or update of version,status on public.user_narrator_source
 for each row execute function public.mark_lifetime_source_policy_pending();
revoke all on function public.mark_lifetime_source_policy_pending() from public,anon,authenticated,service_role;

create function public.apply_lifetime_literal_policy(p_owner uuid,p_project text,p_source uuid,p_version bigint) returns void
language plpgsql security definer set search_path='' as $$
declare source public.user_narrator_source%rowtype; identity public.user_lifetime_conversation%rowtype;
 epoch bigint; item jsonb; v_data jsonb; identifier text; controls jsonb;
begin
 -- Only authoritative private acceptance/edit wrappers may call this function.
 if not exists(select 1 from public.user_lifetime_conversation where user_id=p_owner and project_id=p_project) then return;end if;
 select policy_epoch into epoch from public.user_memoir_project where user_id=p_owner and project_id=p_project for update;
 insert into public.user_profile(user_id,profile) values(p_owner,'{}') on conflict do nothing;
 perform 1 from public.user_profile where user_id=p_owner for update;
 select * into identity from public.user_lifetime_conversation where user_id=p_owner and project_id=p_project for update;
 if not found then return;end if;
 select * into source from public.user_narrator_source where user_id=p_owner and project_id=p_project and id=p_source and version=p_version and status='active';
 if not found then raise exception 'current source policy required' using errcode='40001';end if;
 controls:=public.parse_lifetime_literal_policy(source.text);
 for item in select value from jsonb_array_elements(controls) loop
   v_data:=jsonb_build_object('text',item->>'text','assertion','asserted',
    'uncertainty','Literal current-source request; scope is limited to the quoted wording.',
    'source_refs',jsonb_build_array(jsonb_build_object('source_id',source.id,'version',source.version,
      'char_start',item->'char_start','char_end',item->'char_end','quote',item->>'text')));
   identifier:='literal-v1:'||encode(sha256(convert_to('memoir:continuity:'||source.id::text||':'||source.version::text||':'||
      (item->>'kind')||':'||(item->>'char_start')||':'||(item->>'char_end'),'UTF8')),'hex');
   -- Recognize earlier UUID5 identity only by the complete, exact evidence/data.
   -- Never rewrite or replay an older preference from a partial identity match.
   if not exists(select 1 from public.user_lifetime_continuity c where c.user_id=p_owner and c.conversation_id=identity.conversation_id
       and c.kind=item->>'kind' and c.kind in ('excluded_topic','paused_topic')
       and c.data->'source_refs'->0->>'source_id'=source.id::text
       and c.data->'source_refs'->0->>'version'=source.version::text
       and c.data->'source_refs'->0->>'char_start'=item->>'char_start'
       and c.data->'source_refs'->0->>'char_end'=item->>'char_end'
       and c.data=v_data and c.policy_epoch=epoch) then
     insert into public.user_lifetime_continuity(user_id,conversation_id,record_id,kind,revision,policy_epoch,data)
       values(p_owner,identity.conversation_id,identifier,item->>'kind',1,epoch,v_data);
   end if;
 end loop;
 insert into public.user_lifetime_source_policy_receipt values(p_owner,p_project,identity.conversation_id,p_source,p_version,'literal-v1')
 on conflict(user_id,project_id,source_id) do update set source_version=excluded.source_version,parser_version=excluded.parser_version;
 delete from public.user_lifetime_pending_policy where user_id=p_owner and project_id=p_project and source_id=p_source and source_version=p_version;
end $$;
revoke all on function public.apply_lifetime_literal_policy(uuid,text,uuid,bigint) from public,anon,authenticated,service_role;

-- Existing historical-news/photo/interview wrappers still call this exact seam.
-- Quote helper names containing "atomic" for older Supabase CLI SQL splitters.
alter function public.accept_user_narrator_source_before_news(text,uuid,text,text,text) rename to "accept_user_narrator_source_before_atomic_policy";
revoke all on function public."accept_user_narrator_source_before_atomic_policy"(text,uuid,text,text,text) from public,anon,authenticated,service_role;
create function public.accept_user_narrator_source_before_news(p_project_id text,p_client_turn_id uuid,p_text text,
 p_kind text default 'narrator_chat',p_language text default 'en-AU') returns jsonb
language plpgsql security definer set search_path='' as $$
declare source jsonb; existed boolean; owner uuid:=auth.uid();
begin
 -- Existing acceptance owns the project lock. Acquire it first when present,
 -- then profile before the policy writer can advance the identity revision.
 if exists(select 1 from public.user_lifetime_conversation where user_id=owner and project_id=p_project_id) then
   perform 1 from public.user_memoir_project where user_id=owner and project_id=p_project_id for update;
   insert into public.user_profile(user_id,profile) values(owner,'{}') on conflict do nothing;
   perform 1 from public.user_profile where user_id=owner for update;
 end if;
 select exists(select 1 from public.user_narrator_source where user_id=owner and project_id=p_project_id and client_turn_id=p_client_turn_id) into existed;
 source:=public.accept_user_narrator_source_before_atomic_policy(p_project_id,p_client_turn_id,p_text,p_kind,p_language);
 if not existed then perform public.apply_lifetime_literal_policy(owner,p_project_id,(source->>'id')::uuid,(source->>'version')::bigint);end if;
 return source;
end $$;
revoke all on function public.accept_user_narrator_source_before_news(text,uuid,text,text,text) from public,anon,authenticated,service_role;

alter function public.change_user_narrator_source(text,uuid,bigint,text,text) rename to "change_user_narrator_source_before_atomic_policy";
revoke all on function public."change_user_narrator_source_before_atomic_policy"(text,uuid,bigint,text,text) from public,anon,authenticated,service_role;
create function public.change_user_narrator_source(p_project_id text,p_source_id uuid,p_expected_version bigint,p_action text,p_text text default null) returns jsonb
language plpgsql security definer set search_path='' as $$
declare result jsonb; owner uuid:=auth.uid();
begin
 if exists(select 1 from public.user_lifetime_conversation where user_id=owner and project_id=p_project_id) then
   perform 1 from public.user_memoir_project where user_id=owner and project_id=p_project_id for update;
   insert into public.user_profile(user_id,profile) values(owner,'{}') on conflict do nothing;
   perform 1 from public.user_profile where user_id=owner for update;
 end if;
 result:=public.change_user_narrator_source_before_atomic_policy(p_project_id,p_source_id,p_expected_version,p_action,p_text);
 if p_action='edit' then perform public.apply_lifetime_literal_policy(owner,p_project_id,p_source_id,(result->>'version')::bigint);end if;
 return result;
end $$;
revoke all on function public.change_user_narrator_source(text,uuid,bigint,text,text) from public,anon,service_role;
grant execute on function public.change_user_narrator_source(text,uuid,bigint,text,text) to authenticated;

-- One-time inventory of unfinished accepted turns, using the unfinished partial
-- index. This records uncertainty only, never replays historical preferences.
create index lifetime_unfinished_policy_inventory on public.user_interview_turn(user_id,project_id,source_id,source_version)
 where collector is null and source_id is not null;
insert into public.user_lifetime_pending_policy
 select t.user_id,t.project_id,c.conversation_id,s.id,s.version,s.client_turn_id,'literal-v1'
 from public.user_interview_turn t join public.user_lifetime_conversation c using(user_id,project_id)
 join public.user_narrator_source s on s.user_id=t.user_id and s.project_id=t.project_id and s.id=t.source_id and s.version=t.source_version
 where t.collector is null and t.source_id is not null and s.status='active'
 and not exists(select 1 from public.user_lifetime_reply r where r.user_id=t.user_id and r.conversation_id=c.conversation_id and r.client_turn_id=t.client_turn_id)
 on conflict do nothing;

create function public.mark_lifetime_mapping_policy_pending() returns trigger
language plpgsql security definer set search_path='' as $$
begin
 -- An explicitly mapped/transferred historical source has no parser receipt.
 -- Inventory remains incomplete until a separate, reviewed migration resolves
 -- it. Merely editing the first source cannot clear unknown remaining history.
 if exists(select 1 from public.user_narrator_source where user_id=new.user_id and project_id=new.project_id) then
   insert into public.user_lifetime_policy_inventory_pending values(new.user_id,new.project_id,new.conversation_id,'literal-v1') on conflict do nothing;
 end if;
 insert into public.user_lifetime_pending_policy
 select s.user_id,s.project_id,new.conversation_id,s.id,s.version,s.client_turn_id,'literal-v1'
 from public.user_narrator_source s where s.user_id=new.user_id and s.project_id=new.project_id and s.status='active'
 order by s.sequence limit 1 on conflict do nothing;
 return new;
end $$;
create trigger lifetime_mapping_policy_pending after insert on public.user_lifetime_conversation
 for each row execute function public.mark_lifetime_mapping_policy_pending();
revoke all on function public.mark_lifetime_mapping_policy_pending() from public,anon,authenticated,service_role;

create function public.require_lifetime_policy_ready(p_owner uuid,p_project text) returns void
language plpgsql security definer set search_path='' as $$
begin
 if exists(select 1 from public.user_lifetime_pending_policy where user_id=p_owner and project_id=p_project)
   or exists(select 1 from public.user_lifetime_policy_inventory_pending where user_id=p_owner and project_id=p_project) then
   raise exception 'LIFETIME_POLICY_PENDING' using errcode='55000';end if;
end $$;
revoke all on function public.require_lifetime_policy_ready(uuid,text) from public,anon,authenticated,service_role;

create function public.read_lifetime_policy_status(p_conversation_id uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare owner uuid:=auth.uid(); project text; pending public.user_lifetime_pending_policy%rowtype;
begin
 select project_id into project from public.user_lifetime_conversation where user_id=owner and conversation_id=p_conversation_id;
 if not found then raise exception 'conversation unavailable' using errcode='42501';end if;
 perform 1 from public.user_memoir_project where user_id=owner and project_id=project for share;
 select * into pending from public.user_lifetime_pending_policy where user_id=owner and conversation_id=p_conversation_id order by source_id limit 1;
 return jsonb_build_object('pending',found or exists(select 1 from public.user_lifetime_policy_inventory_pending where user_id=owner and project_id=project),'pending_source_id',pending.source_id,'pending_source_version',pending.source_version,
   'pending_client_turn_id',pending.client_turn_id,'parser_version','literal-v1');
end $$;
revoke all on function public.read_lifetime_policy_status(uuid) from public,anon,service_role;
grant execute on function public.read_lifetime_policy_status(uuid) to authenticated;

-- Capture/receipt metadata remains available for truthful recovery. Actual body
-- publication, model admission, commits and background lane/job authority do not.
alter function public.lock_lifetime_publication(jsonb) rename to "lock_lifetime_publication_before_atomic_policy";
revoke all on function public."lock_lifetime_publication_before_atomic_policy"(jsonb) from public,anon,authenticated,service_role;
create function public.lock_lifetime_publication(p_fence jsonb) returns double precision
language plpgsql security definer set search_path='' as $$
declare remaining double precision;
begin
 remaining:=public.lock_lifetime_publication_before_atomic_policy(p_fence);
 perform public.require_lifetime_policy_ready(auth.uid(),p_fence->'identity'->>'project_id');
 return remaining;
end $$;
revoke all on function public.lock_lifetime_publication(jsonb) from public,anon,service_role;
grant execute on function public.lock_lifetime_publication(jsonb) to authenticated;

alter function public.lock_lifetime_read_publication(jsonb) rename to "lock_lifetime_read_publication_before_atomic_policy";
revoke all on function public."lock_lifetime_read_publication_before_atomic_policy"(jsonb) from public,anon,authenticated,service_role;
create function public.lock_lifetime_read_publication(p_fence jsonb) returns double precision
language plpgsql security definer set search_path='' as $$
declare remaining double precision;
begin
 remaining:=public.lock_lifetime_read_publication_before_atomic_policy(p_fence);
 perform public.require_lifetime_policy_ready(auth.uid(),p_fence->'identity'->>'project_id');
 return remaining;
end $$;
revoke all on function public.lock_lifetime_read_publication(jsonb) from public,anon,service_role;
grant execute on function public.lock_lifetime_read_publication(jsonb) to authenticated;

alter function public.lock_lifetime_memoir_lane(uuid,uuid) rename to "lock_lifetime_memoir_lane_before_atomic_policy";
revoke all on function public."lock_lifetime_memoir_lane_before_atomic_policy"(uuid,uuid) from public,anon,authenticated,service_role;
create function public.lock_lifetime_memoir_lane(p_lane_id uuid,p_token uuid) returns public.user_lifetime_lane_snapshot
language plpgsql security definer set search_path='' as $$
declare snapshot public.user_lifetime_lane_snapshot%rowtype;
begin
 snapshot:=public.lock_lifetime_memoir_lane_before_atomic_policy(p_lane_id,p_token);
 perform public.require_lifetime_policy_ready(snapshot.user_id,snapshot.project_id);
 return snapshot;
end $$;
revoke all on function public.lock_lifetime_memoir_lane(uuid,uuid) from public,anon,authenticated,service_role;

alter function public.lock_lifetime_collection_job(uuid,uuid) rename to "lock_lifetime_collection_job_before_atomic_policy";
revoke all on function public."lock_lifetime_collection_job_before_atomic_policy"(uuid,uuid) from public,anon,authenticated,service_role;
create function public.lock_lifetime_collection_job(p_job_id uuid,p_token uuid default null) returns public.user_lifetime_collection_job
language plpgsql security definer set search_path='' as $$
declare job public.user_lifetime_collection_job%rowtype;
begin
 job:=public.lock_lifetime_collection_job_before_atomic_policy(p_job_id,p_token);
 perform public.require_lifetime_policy_ready(job.user_id,job.project_id);
 return job;
end $$;
revoke all on function public.lock_lifetime_collection_job(uuid,uuid) from public,anon,authenticated,service_role;
-- Reuse the identical frozen parser at final collector persistence too, so
-- Unicode controls and legacy opaque IDs cannot drift after atomic acceptance.
create or replace function public.persist_lifetime_continuity_updates(p_fence jsonb,p_updates jsonb,p_literal_only boolean default false)
returns jsonb language plpgsql security definer set search_path=public,auth as $$
declare owner uuid:=auth.uid(); conversation uuid:=(p_fence->'identity'->>'conversation_id')::uuid; project text;
 item jsonb; v_data jsonb; ref jsonb; existing public.user_lifetime_continuity%rowtype; source public.user_narrator_source%rowtype;
begin
 select project_id into project from public.user_lifetime_conversation where user_id=owner and conversation_id=conversation;
 if not found then raise exception 'conversation unavailable'; end if;
 perform 1 from public.user_memoir_project where user_id=owner and project_id=project for update;
 perform public.lock_lifetime_publication(p_fence);
 if jsonb_typeof(p_updates) is distinct from 'array' or jsonb_array_length(p_updates)>8 then raise exception 'bounded continuity updates required'; end if;
 for item in select value from jsonb_array_elements(p_updates) loop
   if jsonb_typeof(item)<>'object' or exists(select 1 from jsonb_object_keys(item) k where k not in ('record_id','kind','data'))
     or not (item ?& array['record_id','kind','data']) or item->>'kind' not in ('person','unresolved_reference','commitment','excluded_topic','paused_topic')
     then raise exception 'invalid continuity update'; end if;
   v_data:=item->'data';ref:=v_data->'source_refs'->0;
   if jsonb_typeof(v_data->'source_refs') is distinct from 'array' or jsonb_array_length(v_data->'source_refs')<>1
      or v_data->>'text' is distinct from ref->>'quote' then raise exception 'verbatim current continuity required'; end if;
   select * into source from public.user_narrator_source where user_id=owner and project_id=project and id=(ref->>'source_id')::uuid
     and version=(ref->>'version')::bigint and sequence=(p_fence->>'source_revision')::bigint and status='active';
   if not found then raise exception 'current source continuity required';end if;
   if p_literal_only and item->>'kind' not in ('excluded_topic','paused_topic') then raise exception 'only current literal privacy controls allowed'; end if;
   if item->>'kind' in ('excluded_topic','paused_topic') and
     (v_data->>'assertion'<>'asserted' or not exists(select 1 from jsonb_array_elements(public.parse_lifetime_literal_policy(source.text)) literal
       where literal->>'kind'=item->>'kind' and literal->>'text'=v_data->>'text'
         and literal->'char_start'=ref->'char_start' and literal->'char_end'=ref->'char_end')) then
     raise exception 'direct literal privacy instruction required';end if;
   select * into existing from public.user_lifetime_continuity where user_id=owner and conversation_id=conversation and record_id=item->>'record_id';
   if not found and item->>'kind' in ('excluded_topic','paused_topic') then
     -- Earlier UUID5 policy records remain opaque stable identities. Reuse an
     -- exact current-source record; do not duplicate it during final commit.
     select * into existing from public.user_lifetime_continuity c where c.user_id=owner and c.conversation_id=conversation
       and c.kind=item->>'kind' and c.kind in ('excluded_topic','paused_topic')
       and c.data->'source_refs'->0->>'source_id'=ref->>'source_id'
       and c.data->'source_refs'->0->>'version'=ref->>'version'
       and c.data->'source_refs'->0->>'char_start'=ref->>'char_start'
       and c.data->'source_refs'->0->>'char_end'=ref->>'char_end'
       and c.data=v_data and c.policy_epoch=(p_fence->>'policy_epoch')::bigint order by c.record_id limit 1;
   end if;
   if found then
     if existing.data is distinct from v_data or existing.kind is distinct from item->>'kind' then raise exception 'continuity identity conflict'; end if;
   else
     perform public.save_lifetime_continuity(conversation,item->>'record_id',item->>'kind',0,(p_fence->>'policy_epoch')::bigint,(p_fence->>'lease_token')::uuid,v_data);
   end if;
 end loop;
 return public.capture_lifetime_fence(conversation,(p_fence->>'lease_token')::uuid);
end $$;
commit;
