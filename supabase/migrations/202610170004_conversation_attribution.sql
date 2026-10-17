-- Passage accounting belongs to the existing timeline writer, not a new lane.
begin;
-- Numeric ages need narrator birth evidence, not a quoted relative or a saved
-- profile guess. Preserve the already-declared one-year uncertainty interval.
create function public.lifetime_narrator_birth_basis(p_owner uuid,p_project text,p_ref jsonb) returns boolean
language sql stable security definer set search_path='' as $$
 select coalesce((select lower(coalesce(p_ref->>'attribution','narrator')) in ('narrator','storyteller','self','我','本人')
   and p_ref->>'quote' ~* '^(actually[,[:space:]]+)?(I[[:space:]]+(was[[:space:]]+)?born|my[[:space:]]+(birth year|year of birth)|我(是|于|在)?[0-9]{4}年?(出生|生于)|我(是)?(出生|生于))'
   and btrim(regexp_replace(left(s.text,coalesce((p_ref->>'char_start')::integer,strpos(s.text,p_ref->>'quote')-1)),
     E'^.*[.!?。！？\n]','','s'))=''
 from public.user_narrator_source s where s.user_id=p_owner and s.project_id=p_project and s.id::text=p_ref->>'source_id'
   and s.version::text=p_ref->>'version' and s.status='active'),false)
$$;
revoke all on function public.lifetime_narrator_birth_basis(uuid,text,jsonb) from public,anon,authenticated,service_role;
alter function public.validate_memory_temporal(uuid,text,jsonb) rename to validate_memory_temporal_before_attribution;
revoke all on function public.validate_memory_temporal_before_attribution(uuid,text,jsonb) from public,anon,authenticated,service_role;
create function public.validate_memory_temporal(p_owner uuid,p_project_id text,p_temporal jsonb) returns void
language plpgsql security definer set search_path='' as $$
declare proof jsonb:=p_temporal; basis jsonb; filtered jsonb;
begin
 if auth.uid() is distinct from p_owner then raise exception 'owned temporal evidence required' using errcode='42501';end if;
 if p_temporal->>'precision'='age' and (p_temporal->>'year_start' is not null or p_temporal->>'year_end' is not null) then
   if (p_temporal->>'year_end')::integer>(p_temporal->>'year_start')::integer+1 then
     raise exception 'age interval exceeds supported precision' using errcode='22023';end if;
   for basis in select value from jsonb_array_elements(coalesce(p_temporal->'basis','[]')) loop
     perform public.validate_memory_evidence(p_owner,p_project_id,basis);
   end loop;
   select coalesce(jsonb_agg(b),'[]') into filtered from jsonb_array_elements(coalesce(p_temporal->'basis','[]')) b
   where lower(coalesce(b->>'attribution','narrator')) in ('narrator','storyteller','self','我','本人')
     and (b->>'quote' !~* '(born|birth|出生|生于)' or public.lifetime_narrator_birth_basis(p_owner,p_project_id,b));
   proof:=jsonb_set(proof,'{basis}',filtered);
   if p_temporal->>'year_start' is not null and (p_temporal->>'year_end')::integer=(p_temporal->>'year_start')::integer+1 then
     proof:=jsonb_set(proof,'{year_end}',p_temporal->'year_start');
   end if;
 end if;
 perform public.validate_memory_temporal_before_attribution(p_owner,p_project_id,proof);
end $$;
revoke all on function public.validate_memory_temporal(uuid,text,jsonb) from public,anon;
grant execute on function public.validate_memory_temporal(uuid,text,jsonb) to authenticated;

create table public.user_memory_attribution_window (
 user_id uuid not null, project_id text not null, source_id uuid not null, source_version bigint not null,
 char_start integer not null check(char_start>=0), char_end integer not null check(char_end>char_start),
 policy_epoch bigint not null, disposition text not null check(disposition in ('unresolved','non_story','withheld')),
 reason text not null, method text not null default 'model' check(method in ('model','rule')),
 primary key(user_id,project_id,source_id,source_version,char_start,char_end),
 foreign key(user_id,project_id,source_id) references public.user_narrator_source(user_id,project_id,id) on delete cascade
);
alter table public.user_memory_attribution_window enable row level security;
revoke all on public.user_memory_attribution_window from public,anon,authenticated,service_role;
alter table public.user_memoir_project add column attribution_revision bigint not null default 0;
alter table public.user_lifetime_read_cursor add column attribution_revision bigint not null default 0,
 add column source_id uuid;
create table public.user_memory_event_place (
 user_id uuid not null, project_id text not null, event_id text not null,
 source_id uuid not null, source_version bigint not null, char_start integer not null, char_end integer not null,
 role text not null check(role in ('setting','origin','destination')), place jsonb not null,
 place_key text generated always as (md5(place::text)) stored,
 primary key(user_id,project_id,event_id,source_id,source_version,char_start,char_end,role,place_key),
 foreign key(user_id,project_id,event_id) references public.user_memory_event(user_id,project_id,id) on delete cascade,
 foreign key(user_id,project_id,source_id) references public.user_narrator_source(user_id,project_id,id) on delete cascade
);
create table public.user_memory_attribution_receipt (
 snapshot_id uuid not null references public.user_lifetime_lane_snapshot on delete cascade,
 page_number bigint not null, page_digest text not null, result_digest text not null,
 primary key(snapshot_id,page_number)
);
alter table public.user_memory_event_place enable row level security;
alter table public.user_memory_attribution_receipt enable row level security;
revoke all on public.user_memory_event_place,public.user_memory_attribution_receipt from public,anon,authenticated,service_role;
create table public.user_memory_delivered_context (
 user_id uuid not null,project_id text not null,source_id uuid not null,source_version bigint not null,
 client_turn_id uuid not null,reply_id uuid not null,policy_epoch bigint not null,execution_generation bigint not null,
 preference_revision bigint not null,event_id text,event_revision bigint,
 primary key(user_id,project_id,source_id),
 foreign key(user_id,project_id,source_id) references public.user_narrator_source(user_id,project_id,id) on delete cascade
);
create table public.user_memory_reply_context (
 user_id uuid not null,project_id text not null,source_id uuid not null,source_version bigint not null,prior_source_id uuid not null,
 primary key(user_id,project_id,source_id),
 foreign key(user_id,project_id,source_id) references public.user_narrator_source(user_id,project_id,id) on delete cascade,
 foreign key(user_id,project_id,prior_source_id) references public.user_memory_delivered_context(user_id,project_id,source_id) on delete cascade
);
alter table public.user_memory_delivered_context enable row level security;
alter table public.user_memory_reply_context enable row level security;
revoke all on public.user_memory_delivered_context,public.user_memory_reply_context from public,anon,authenticated,service_role;

create function public.commit_lifetime_attribution_delivery(p_fence jsonb,p_client_turn_id uuid,p_reply_id uuid) returns boolean
language plpgsql security definer set search_path='' as $$
declare source public.user_narrator_source%rowtype; turn public.user_interview_turn%rowtype;
 question jsonb; event public.user_memory_event%rowtype; project text:=p_fence->'identity'->>'project_id';
begin
 perform public.lock_lifetime_publication(p_fence);
 select * into turn from public.user_interview_turn where user_id=auth.uid() and project_id=project and client_turn_id=p_client_turn_id;
 select * into source from public.user_narrator_source where user_id=auth.uid() and project_id=project
   and id=turn.source_id and version=turn.source_version and status='active';
 if not found or not exists(select 1 from public.user_lifetime_reply r where r.user_id=auth.uid()
   and r.conversation_id=(p_fence->'identity'->>'conversation_id')::uuid and r.client_turn_id=p_client_turn_id and r.memory_id=p_reply_id
   and r.policy_epoch=(p_fence->>'policy_epoch')::bigint and r.execution_generation=(p_fence->>'execution_generation')::bigint
   and r.preference_revision=(p_fence->>'preference_revision')::bigint) then return false;end if;
 select q into question from jsonb_array_elements(turn.collector->'plan'->'candidates') q
   where q->>'id'=turn.collector->'plan'->>'chosen_id';
 if question->'context'->>'event_id'=turn.collector->'plan'->>'active_event_id'
   and length(coalesce(question->>'question',''))>0 and strpos(turn.collector->>'reply',question->>'question')>0 then
   select * into event from public.user_memory_event where user_id=auth.uid() and project_id=project
     and id=question->'context'->>'event_id' and status='active';
 end if;
 insert into public.user_memory_delivered_context values(auth.uid(),project,source.id,source.version,p_client_turn_id,p_reply_id,
   (p_fence->>'policy_epoch')::bigint,(p_fence->>'execution_generation')::bigint,(p_fence->>'preference_revision')::bigint,event.id,event.revision)
 on conflict do nothing;
 return true;
end $$;
revoke all on function public.commit_lifetime_attribution_delivery(jsonb,uuid,uuid) from public,anon,service_role;
grant execute on function public.commit_lifetime_attribution_delivery(jsonb,uuid,uuid) to authenticated;

create function public.capture_memory_reply_context() returns trigger language plpgsql security definer set search_path='' as $$
declare prior uuid;
begin
 if not exists(select 1 from public.lifetime_two_lane_rollout where singleton and enabled) then return new;end if;
 select id into prior from public.user_narrator_source where user_id=new.user_id and project_id=new.project_id
   and sequence<new.sequence order by sequence desc limit 1;
 insert into public.user_memory_reply_context
 select new.user_id,new.project_id,new.id,new.version,d.source_id from public.user_memory_delivered_context d
 where d.user_id=new.user_id and d.project_id=new.project_id and d.source_id=prior and d.event_id is not null
 on conflict do nothing;
 return new;
end $$;
create trigger memory_reply_context after insert on public.user_narrator_source for each row execute function public.capture_memory_reply_context();
revoke all on function public.capture_memory_reply_context() from public,anon,authenticated,service_role;

create function public.lifetime_event_place_rows(p_owner uuid,p_project text,p_event text)
returns setof public.user_memory_event_place language sql stable security definer set search_path='' as $$
 select p.* from public.user_memory_event_place p join public.user_narrator_source s
   on s.user_id=p.user_id and s.project_id=p.project_id and s.id=p.source_id and s.version=p.source_version and s.status='active'
 join public.user_memory_event e on e.user_id=p.user_id and e.project_id=p.project_id and e.id=p.event_id and e.status='active'
 where p.user_id=p_owner and p.project_id=p_project and p.event_id=p_event
   and exists(select 1 from public.user_memory_event_source r where r.user_id=p.user_id and r.project_id=p.project_id
     and r.event_id=p.event_id and r.source_id=p.source_id and r.source_version=p.source_version and r.stage_progress_role='primary'
     and (r.evidence->>'char_start')::integer<=p.char_start and (r.evidence->>'char_end')::integer>=p.char_end)
   and not exists(select 1 from public.user_memory_event_source_exclusion x where x.user_id=p.user_id
     and x.project_id=p.project_id and x.event_id=p.event_id and x.source_id=p.source_id)
$$;
create function public.lifetime_attribution_event_context(p_owner uuid,p_project text,p_event text) returns jsonb
language sql stable security definer set search_path='' as $$
 select jsonb_build_object('id',e.id,'revision',e.revision,'life_stage',e.life_stage,
   'attribution',e.data->'attribution','uncertainty',e.data->'uncertainty',
   'temporal',jsonb_build_object('expression',e.data->'temporal'->'expression','precision',e.data->'temporal'->'precision',
     'year_start',e.data->'temporal'->'year_start','year_end',e.data->'temporal'->'year_end'),
   'places',coalesce((select jsonb_agg(to_jsonb(p)-array['user_id','project_id','event_id']) from
     (select * from public.lifetime_event_place_rows(p_owner,p_project,p_event) order by source_id,char_start,role,place_key limit 2) p),'[]'),
   'places_complete',(select count(*)<=2 from (select 1 from public.lifetime_event_place_rows(p_owner,p_project,p_event) limit 3) p),
   'places_retrieval','/v1/story/events/'||p_project||'/'||p_event||'/places')
 from public.user_memory_event e where e.user_id=p_owner and e.project_id=p_project and e.id=p_event and e.status='active'
$$;
revoke all on function public.lifetime_event_place_rows(uuid,text,text),public.lifetime_attribution_event_context(uuid,text,text)
 from public,anon,authenticated,service_role;

create function public.lifetime_source_context(p_owner uuid,p_project text,p_source uuid) returns jsonb
language sql stable security definer set search_path='' as $$
 select public.lifetime_attribution_event_context(p_owner,p_project,e.id)||jsonb_build_object('association','context_only',
   'reply_id',d.reply_id,'source_id',d.source_id,'source_version',d.source_version)
 from public.user_memory_reply_context c join public.user_narrator_source s
   on s.user_id=c.user_id and s.project_id=c.project_id and s.id=c.source_id and s.version=c.source_version and s.status='active'
 join public.user_memory_delivered_context d on d.user_id=c.user_id and d.project_id=c.project_id and d.source_id=c.prior_source_id
 join public.user_narrator_source prior on prior.user_id=d.user_id and prior.project_id=d.project_id
   and prior.id=d.source_id and prior.version=d.source_version and prior.status='active'
 join public.user_memory_event e on e.user_id=d.user_id and e.project_id=d.project_id and e.id=d.event_id and e.revision=d.event_revision and e.status='active'
 join public.user_memoir_project p on p.user_id=c.user_id and p.project_id=c.project_id and p.policy_epoch=d.policy_epoch
 join public.user_lifetime_conversation i on i.user_id=c.user_id and i.project_id=c.project_id
   and i.execution_generation=d.execution_generation and i.preference_revision=d.preference_revision
 where c.user_id=p_owner and c.project_id=p_project and c.source_id=p_source
$$;
revoke all on function public.lifetime_source_context(uuid,text,uuid) from public,anon,authenticated,service_role;

create function public.invalidate_memory_attribution_source() returns trigger
language plpgsql security definer set search_path='' as $$
begin
 if old.version=new.version and old.status=new.status then return new;end if;
 delete from public.user_memory_attribution_window where user_id=old.user_id and project_id=old.project_id and source_id=old.id;
 delete from public.user_memory_event_place where user_id=old.user_id and project_id=old.project_id and source_id=old.id;
 delete from public.user_memory_delivered_context where user_id=old.user_id and project_id=old.project_id and source_id=old.id;
 delete from public.user_memory_reply_context where user_id=old.user_id and project_id=old.project_id and source_id=old.id;
 update public.user_memoir_project set attribution_revision=attribution_revision+1 where user_id=old.user_id and project_id=old.project_id;
 return new;
end $$;
create trigger memory_attribution_source after update of version,status on public.user_narrator_source
 for each row execute function public.invalidate_memory_attribution_source();
revoke all on function public.invalidate_memory_attribution_source() from public,anon,authenticated,service_role;

create function public.lifetime_attribution_decision(p_text text,p_name text) returns jsonb
language plpgsql immutable set search_path='' as $$
declare words text:=lower(btrim(regexp_replace(p_text,'[[:space:].!?。！？]+$','','g')));
begin
 if words in ('do not record this','don''t record this','do not record this event','不要记录这件事','这件事不要记下来') then
   return jsonb_build_object('schema_version',1,'decision','withheld','reason','privacy_withheld');
 end if;
 if words in ('hello','hi','thank you','thanks','你好','您好','谢谢','多谢','please stop','stop','pause',
   'skip','next question','please continue','go on','暂停','停一下','跳过','继续','下一个问题','what can you do','你能做什么') then
   return jsonb_build_object('schema_version',1,'decision','non_story','reason','conversation_control');
 end if;
 if words in ('yes','no','okay','ok','是','是的','对','嗯','好','there','then','那里','那时') then
   return jsonb_build_object('schema_version',1,'decision','unresolved','reason','ambiguous_context');
 end if;
 if p_name is not null and p_name !~* '([0-9.,;!?。！？，；]|\m(and|but|when|was|born|lived|grew|moved|worked|remember|I)\M|出生|小时候|长大|住在|但是|然后)'
   and (words=lower('my name is '||p_name) or words=lower('i am '||p_name)
   or words='我叫'||lower(p_name) or words='我的名字是'||lower(p_name)) then
   return jsonb_build_object('schema_version',1,'decision','non_story','reason','profile_introduction');
 end if;
 return jsonb_build_object('schema_version',1,'decision','extract','reason','new_testimony');
end $$;
revoke all on function public.lifetime_attribution_decision(text,text) from public,anon,authenticated,service_role;

alter function public.read_lifetime_memoir_lane_page(uuid,uuid) rename to read_lifetime_memoir_lane_page_before_attribution;
revoke all on function public.read_lifetime_memoir_lane_page_before_attribution(uuid,uuid) from public,anon,authenticated,service_role;
create function public.read_lifetime_memoir_lane_page(p_lane_id uuid,p_token uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare page jsonb; source public.user_narrator_source%rowtype; name text; context jsonb; inputs jsonb; coverage jsonb; events jsonb;
begin
 page:=public.read_lifetime_memoir_lane_page_before_attribution(p_lane_id,p_token);
 if page->>'skill'='timeline' and page ? 'two_lane' and coalesce(page->'memory_summary','null')='null' then
   select * into source from public.user_narrator_source where user_id=(page->>'user_id')::uuid
     and project_id=page->>'project_id' and id=(page->'source'->>'id')::uuid;
   select t.collector->'plan'->'work'->>'name' into name from public.user_interview_turn t
     where t.user_id=source.user_id and t.project_id=source.project_id and t.source_id=source.id and t.source_version=source.version;
   context:=public.lifetime_attribution_decision(source.text,name)||jsonb_build_object('delivered_event',
     public.lifetime_source_context(source.user_id,source.project_id,source.id));
   page:=page||jsonb_build_object('attribution_context',context);
   page:=jsonb_set(page,'{events}',coalesce((select jsonb_agg(candidate||coalesce(ctx,'{}'))
     from jsonb_array_elements(page->'events') candidate cross join lateral (select public.lifetime_attribution_event_context(
       source.user_id,source.project_id,candidate->>'id') ctx) bounded),'[]'));
   if page->'two_lane'->>'work_mode'<>'pending' then
     page:=jsonb_set(page,'{two_lane,work_mode}',to_jsonb(case when context->>'decision'='extract' then 'extract' else 'reply_only' end));
   end if;
   page:=page-'input_digest'-'page_digest';
   page:=page||jsonb_build_object('input_digest',encode(sha256(convert_to((page-'token')::text,'UTF8')),'hex'));
   page:=page||jsonb_build_object('page_digest',encode(sha256(convert_to(page::text,'UTF8')),'hex'));
 elsif page->>'skill'='composer' and exists(select 1 from public.lifetime_two_lane_rollout where singleton and enabled) then
   inputs:=case when page ? 'batch' then coalesce(page->'batch'->'sources','[]')||coalesce(page->'batch'->'new_messages','[]')
     when page->'source'<>'null'::jsonb then jsonb_build_array(page->'source') else '[]' end;
   select coalesce(jsonb_agg(public.lifetime_source_attribution_summary((page->>'user_id')::uuid,page->>'project_id',id)),'[]')
     into coverage from (select distinct (s->>'id')::uuid id from jsonb_array_elements(inputs) s limit 21) bounded;
   select coalesce(jsonb_agg(public.lifetime_attribution_event_context((page->>'user_id')::uuid,page->>'project_id',e->>'id')),'[]')
     into events from (select e from jsonb_array_elements(case when page ? 'batch' then page->'batch'->'events'
       else jsonb_build_array(page->'partition') end) e limit 8) bounded;
   page:=page||jsonb_build_object('attribution_coverage',jsonb_build_object('scope','bounded_sources','lifetime_complete',false,
     'sources',coverage,'events',events,'authority','canonical_context_only_not_additional_testimony'));
   page:=page-'input_digest'-'page_digest';
   page:=page||jsonb_build_object('input_digest',encode(sha256(convert_to((page-'token')::text,'UTF8')),'hex'));
   page:=page||jsonb_build_object('page_digest',encode(sha256(convert_to(page::text,'UTF8')),'hex'));
 end if;
 return page;
end $$;
revoke all on function public.read_lifetime_memoir_lane_page(uuid,uuid) from public,anon,authenticated;
grant execute on function public.read_lifetime_memoir_lane_page(uuid,uuid) to service_role;

alter function public.lock_lifetime_memoir_lane_publication(jsonb) rename to lock_lifetime_memoir_lane_publication_before_attribution;
revoke all on function public.lock_lifetime_memoir_lane_publication_before_attribution(jsonb) from public,anon,authenticated,service_role;
create function public.lock_lifetime_memoir_lane_publication(p_fence jsonb) returns double precision
language plpgsql security definer set search_path='' as $$
declare remaining double precision; page jsonb;
begin
 remaining:=public.lock_lifetime_memoir_lane_publication_before_attribution(p_fence);
 if p_fence ? 'profile_context' then return remaining;end if;
 page:=public.read_lifetime_memoir_lane_page((p_fence->>'lane_id')::uuid,(p_fence->>'token')::uuid);
 if coalesce(p_fence->'attribution_context','null') is distinct from coalesce(page->'attribution_context','null')
   or coalesce(p_fence->'attribution_coverage','null') is distinct from coalesce(page->'attribution_coverage','null') then
   raise exception 'attribution context changed' using errcode='40001';end if;
 return remaining;
end $$;
revoke all on function public.lock_lifetime_memoir_lane_publication(jsonb) from public,anon;
grant execute on function public.lock_lifetime_memoir_lane_publication(jsonb) to authenticated,service_role;

-- Direct evidence determines linked coverage; attempt receipts only account for
-- the remaining ranges. Context/temporal dependencies cannot promote a passage.
create function public.lifetime_source_attribution_rows(p_owner uuid,p_project text,p_source uuid)
returns table(char_start integer,char_end integer,disposition text,reason text,event_id text)
language sql stable security definer set search_path='' as $$
 with source as materialized (
   select * from public.user_narrator_source where user_id=p_owner and project_id=p_project and id=p_source and status='active'
 ), windows as materialized (
   select w.* from public.user_memory_attribution_window w join source s on w.source_id=s.id and w.source_version=s.version
   join public.user_memoir_project p on p.user_id=w.user_id and p.project_id=w.project_id and p.policy_epoch=w.policy_epoch
   where w.user_id=p_owner and w.project_id=p_project
 ), links as materialized (
   select distinct (r.evidence->>'char_start')::integer lo,(r.evidence->>'char_end')::integer hi,e.id
   from source s join public.user_memory_event_source r on r.user_id=s.user_id and r.project_id=s.project_id
     and r.source_id=s.id and r.source_version=s.version
   join public.user_memory_event e on e.user_id=r.user_id and e.project_id=r.project_id and e.id=r.event_id and e.status='active'
   where r.stage_progress_role in ('primary','legacy_primary')
     and r.evidence->>'char_start' ~ '^[0-9]+$' and r.evidence->>'char_end' ~ '^[0-9]+$'
     and (r.evidence->>'char_end')::integer<=(select length(text) from source)
     and substring(s.text from (r.evidence->>'char_start')::integer+1 for
       (r.evidence->>'char_end')::integer-(r.evidence->>'char_start')::integer)=r.evidence->>'quote'
     and not exists(select 1 from public.user_memory_event_source_exclusion x where x.user_id=r.user_id
       and x.project_id=r.project_id and x.event_id=r.event_id and x.source_id=r.source_id)
 ), boundaries as (
   select 0 n union select length(text) from source
   union select char_start from windows union select char_end from windows
   union select lo from links union select hi from links
 ), segments as (select n lo,lead(n) over(order by n) hi from boundaries), classified as (
   select g.lo,g.hi,l.id,
     case when w.disposition='withheld' then 'withheld' when l.id is not null then 'linked'
       when w.disposition is not null then w.disposition
       when (select processing_status from source)='succeeded' then 'unresolved' else 'pending' end status,
     case when w.disposition='withheld' then w.reason when l.id is not null then 'direct_evidence'
       when w.reason is not null then w.reason
       when (select processing_status from source)='succeeded' then 'legacy_unresolved' else 'awaiting_reconciliation' end why
   from segments g left join links l on l.lo<=g.lo and l.hi>=g.hi
   left join lateral (select * from windows w where w.char_start<=g.lo and w.char_end>=g.hi
     order by (w.disposition='withheld') desc,w.char_end-w.char_start limit 1) w on true
   where g.hi>g.lo
 ) select distinct lo,hi,status,why,case when status='linked' then id else null end from classified
$$;
revoke all on function public.lifetime_source_attribution_rows(uuid,text,uuid) from public,anon,authenticated,service_role;

create function public.lifetime_source_attribution_summary(p_owner uuid,p_project text,p_source uuid) returns jsonb
language sql stable security definer set search_path='' as $$
 select jsonb_build_object('source_id',p_source,'complete',coalesce(bool_and(disposition<>'pending'),false),
   'resolved',coalesce(bool_and(disposition in ('linked','non_story')),false),
   'pending_passages',count(*) filter(where disposition='pending'),
   'unresolved_passages',count(*) filter(where disposition='unresolved'),
   'linked_passages',count(*) filter(where disposition='linked'),
   'non_story_passages',count(*) filter(where disposition='non_story'),
   'withheld_passages',count(*) filter(where disposition='withheld'),
   'retrieval','/v1/story/sources/'||p_project||'/'||p_source||'/attribution')
 from (select distinct char_start,char_end,disposition from public.lifetime_source_attribution_rows(p_owner,p_project,p_source)) passages
$$;
revoke all on function public.lifetime_source_attribution_summary(uuid,text,uuid) from public,anon,authenticated,service_role;

alter function public.read_lifetime_collection_page(text,text,uuid,integer,text) rename to read_lifetime_collection_page_before_attribution;
revoke all on function public.read_lifetime_collection_page_before_attribution(text,text,uuid,integer,text) from public,anon,authenticated,service_role;
create function public.read_lifetime_collection_page(p_project_id text,p_kind text,p_after uuid default null,p_limit integer default 8,p_event_id text default null)
returns jsonb language plpgsql security definer set search_path='' as $$
declare result jsonb;
begin
 result:=public.read_lifetime_collection_page_before_attribution(p_project_id,p_kind,p_after,p_limit,p_event_id);
 if p_kind='sources' and exists(select 1 from public.lifetime_two_lane_rollout where singleton and enabled) then
   result:=jsonb_set(result,'{sources}',coalesce((select jsonb_agg(s||jsonb_build_object('attribution',
     public.lifetime_source_attribution_summary(auth.uid(),p_project_id,(s->>'id')::uuid))) from jsonb_array_elements(result->'sources') s),'[]'));
 end if;
 return result;
end $$;
revoke all on function public.read_lifetime_collection_page(text,text,uuid,integer,text) from public,anon;
grant execute on function public.read_lifetime_collection_page(text,text,uuid,integer,text) to authenticated;

create function public.read_lifetime_source_attribution(p_project_id text,p_source_id uuid,p_after uuid default null,p_limit integer default 8)
returns jsonb language plpgsql security definer set search_path='' as $$
declare owner uuid:=auth.uid(); project public.user_memoir_project%rowtype; source public.user_narrator_source%rowtype;
 identity public.user_lifetime_conversation%rowtype; cursor_row public.user_lifetime_read_cursor%rowtype;
 records jsonb; last_key text:=''; cursor_id uuid; more boolean; attempted boolean; resolved boolean;
begin
 if owner is null or p_limit is null or p_limit not between 1 and 8 then raise exception 'invalid attribution page' using errcode='22023';end if;
 select * into project from public.user_memoir_project where user_id=owner and project_id=p_project_id for share;
 select * into identity from public.user_lifetime_conversation where user_id=owner and project_id=p_project_id;
 if not found then raise exception 'owned conversation required' using errcode='42501';end if;
 select * into source from public.user_narrator_source where user_id=owner and project_id=p_project_id and id=p_source_id and status='active';
 if not found then raise exception 'current owned source required' using errcode='42501';end if;
 if p_after is not null then
   select * into cursor_row from public.user_lifetime_read_cursor where id=p_after and user_id=owner
     and project_id=p_project_id and kind='attribution' and source_id=p_source_id;
   if not found then raise exception 'attribution cursor scope mismatch' using errcode='22023';end if;
   if cursor_row.source_revision<>project.source_sequence or cursor_row.event_revision<>project.event_sequence
     or cursor_row.policy_epoch<>project.policy_epoch or cursor_row.attribution_revision<>project.attribution_revision
     or cursor_row.preference_revision<>identity.preference_revision then raise exception 'attribution page changed' using errcode='40001';end if;
   last_key:=cursor_row.after_key;
 end if;
 select coalesce(jsonb_agg(item order by key),'[]') into records from (
   select lpad(a.char_start::text,8,'0')||':'||coalesce(a.event_id,'') key,
     jsonb_build_object('key',lpad(a.char_start::text,8,'0')||':'||coalesce(a.event_id,''),
       'char_start',a.char_start,'char_end',a.char_end,'disposition',a.disposition,'reason',a.reason,
       'context_event',case when a.disposition in ('unresolved','non_story') then public.lifetime_source_context(owner,p_project_id,p_source_id) else null end,
       'event',public.lifetime_attribution_event_context(owner,p_project_id,e.id)) item
   from public.lifetime_source_attribution_rows(owner,p_project_id,p_source_id) a
   left join public.user_memory_event e on e.user_id=owner and e.project_id=p_project_id and e.id=a.event_id
   where lpad(a.char_start::text,8,'0')||':'||coalesce(a.event_id,'')>last_key
   order by key limit p_limit+1) bounded;
 more:=jsonb_array_length(records)>p_limit;
 if more then
   records:=records-p_limit;
   insert into public.user_lifetime_read_cursor(user_id,project_id,conversation_id,kind,source_id,policy_epoch,
     preference_revision,source_revision,event_revision,attribution_revision,after_key)
   values(owner,p_project_id,identity.conversation_id,'attribution',p_source_id,project.policy_epoch,
     identity.preference_revision,project.source_sequence,project.event_sequence,project.attribution_revision,records->-1->>'key') returning id into cursor_id;
 end if;
 select bool_and(disposition<>'pending'),bool_and(disposition in ('linked','non_story')) into attempted,resolved
   from public.lifetime_source_attribution_rows(owner,p_project_id,p_source_id);
 return jsonb_build_object('source_id',source.id,'source_version',source.version,'policy_epoch',project.policy_epoch,
   'attribution_revision',project.attribution_revision,'complete',coalesce(attempted,false),'resolved',coalesce(resolved,false),
   'items',records,'next_cursor',cursor_id,'page_complete',not more);
end $$;
revoke all on function public.read_lifetime_source_attribution(text,uuid,uuid,integer) from public,anon;
grant execute on function public.read_lifetime_source_attribution(text,uuid,uuid,integer) to authenticated;

create function public.read_lifetime_event_places(p_project_id text,p_event_id text,p_after uuid default null,p_limit integer default 8)
returns jsonb language plpgsql security definer set search_path='' as $$
declare owner uuid:=auth.uid(); project public.user_memoir_project%rowtype; identity public.user_lifetime_conversation%rowtype;
 cursor_row public.user_lifetime_read_cursor%rowtype; records jsonb; last_key text:=''; more boolean; cursor_id uuid;
begin
 if p_limit is null or p_limit not between 1 and 8 then raise exception 'bounded event place page required' using errcode='22023';end if;
 select * into project from public.user_memoir_project where user_id=owner and project_id=p_project_id for share;
 select * into identity from public.user_lifetime_conversation where user_id=owner and project_id=p_project_id;
 if not found or not exists(select 1 from public.user_memory_event where user_id=owner and project_id=p_project_id and id=p_event_id and status='active') then
   raise exception 'owned active event required' using errcode='42501';end if;
 if p_after is not null then
   select * into cursor_row from public.user_lifetime_read_cursor where id=p_after and user_id=owner and project_id=p_project_id
     and kind='event_places' and event_id=p_event_id;
   if not found then raise exception 'event place cursor scope mismatch' using errcode='22023';end if;
   if cursor_row.policy_epoch<>project.policy_epoch or cursor_row.source_revision<>project.source_sequence
     or cursor_row.event_revision<>project.event_sequence or cursor_row.attribution_revision<>project.attribution_revision
     or cursor_row.preference_revision<>identity.preference_revision then raise exception 'event place page changed' using errcode='40001';end if;
   last_key:=cursor_row.after_key;
 end if;
 select coalesce(jsonb_agg(item order by key),'[]') into records from (
   select source_id::text||':'||source_version||':'||lpad(char_start::text,8,'0')||':'||lpad(char_end::text,8,'0')||':'||role||':'||place_key key,
     to_jsonb(p)-array['user_id','project_id']||jsonb_build_object('key',source_id::text||':'||source_version||':'||
       lpad(char_start::text,8,'0')||':'||lpad(char_end::text,8,'0')||':'||role||':'||place_key) item
   from public.lifetime_event_place_rows(owner,p_project_id,p_event_id) p
   where source_id::text||':'||source_version||':'||lpad(char_start::text,8,'0')||':'||lpad(char_end::text,8,'0')||':'||role||':'||place_key>last_key
   order by key limit p_limit+1) bounded;
 more:=jsonb_array_length(records)>p_limit;
 if more then
   records:=records-p_limit;
   insert into public.user_lifetime_read_cursor(user_id,project_id,conversation_id,kind,event_id,policy_epoch,
     preference_revision,source_revision,event_revision,attribution_revision,after_key)
   values(owner,p_project_id,identity.conversation_id,'event_places',p_event_id,project.policy_epoch,identity.preference_revision,
     project.source_sequence,project.event_sequence,project.attribution_revision,records->-1->>'key') returning id into cursor_id;
 end if;
 return jsonb_build_object('event_id',p_event_id,'items',records,'next_cursor',cursor_id,'complete',not more);
end $$;
revoke all on function public.read_lifetime_event_places(text,text,uuid,integer) from public,anon;
grant execute on function public.read_lifetime_event_places(text,text,uuid,integer) to authenticated;

alter function public.commit_lifetime_memoir_lane_page(uuid,uuid,bigint,jsonb,text) rename to commit_lifetime_memoir_lane_page_before_attribution;
revoke all on function public.commit_lifetime_memoir_lane_page_before_attribution(uuid,uuid,bigint,jsonb,text) from public,anon,authenticated,service_role;
create function public.commit_lifetime_memoir_lane_page(p_lane_id uuid,p_token uuid,p_page_number bigint,p_result jsonb,p_page_digest text)
returns jsonb language plpgsql security definer set search_path='' as $$
declare snap public.user_lifetime_lane_snapshot%rowtype; page jsonb; result jsonb; hash text; item jsonb; ref jsonb;
 proposal jsonb; selected_event text; matches integer; current_source public.user_narrator_source%rowtype; base boolean;
 changed text[]:='{}'; inserted integer; next_change bigint; event_row public.user_memory_event%rowtype;
begin
 snap:=public.lock_lifetime_memoir_lane(p_lane_id,p_token);
 hash:=encode(sha256(convert_to(p_result::text,'UTF8')),'hex');
 if exists(select 1 from public.user_memory_attribution_receipt where snapshot_id=snap.id and page_number=p_page_number) then
   if exists(select 1 from public.user_memory_attribution_receipt where snapshot_id=snap.id and page_number=p_page_number
     and page_digest=p_page_digest and result_digest=hash) then return jsonb_build_object('status','page_saved','replayed',true);end if;
   raise exception 'attribution replay conflict' using errcode='40001';
 end if;
 page:=public.read_lifetime_memoir_lane_page(p_lane_id,p_token);
 base:=p_page_number=snap.page_number and page ? 'attribution_context';
 if not base then
   return public.commit_lifetime_memoir_lane_page_before_attribution(p_lane_id,p_token,p_page_number,p_result,p_page_digest);
 end if;
 if octet_length(p_result::text)>131072 then raise exception 'bounded attribution result required' using errcode='22023';end if;
 if jsonb_typeof(coalesce(p_result->'event_places','[]'))<>'array' or jsonb_array_length(coalesce(p_result->'event_places','[]'))>32
   or jsonb_typeof(coalesce(p_result->'passage_dispositions','[]'))<>'array'
   or jsonb_array_length(coalesce(p_result->'passage_dispositions','[]'))>64 then
   raise exception 'bounded attribution proposals required' using errcode='22023';end if;
 if page->'attribution_context'->>'decision'<>'extract' and
   (jsonb_array_length(coalesce(p_result->'event_places','[]'))>0 or jsonb_array_length(coalesce(p_result->'passage_dispositions','[]'))>0) then
   raise exception 'rule handling cannot add model attribution' using errcode='22023';end if;
 select * into current_source from public.user_narrator_source where user_id=snap.user_id and project_id=snap.project_id
   and id=(page->'source'->>'id')::uuid and version=(page->'source'->>'version')::bigint and status='active';
 for item in select value from jsonb_array_elements(coalesce(p_result->'event_places','[]')||coalesce(p_result->'passage_dispositions','[]')) loop
   ref:=item->'source_ref';
   if ref->>'source_id' is distinct from current_source.id::text or ref->>'version' is distinct from current_source.version::text
     or jsonb_typeof(ref->'char_start') is distinct from 'number' or jsonb_typeof(ref->'char_end') is distinct from 'number'
     or (ref->>'char_start')::integer<(page->'source'->>'char_start')::integer
     or (ref->>'char_end')::integer>(page->'source'->>'char_end')::integer
     or (ref->>'char_end')::integer<=(ref->>'char_start')::integer
     or substring(current_source.text from (ref->>'char_start')::integer+1 for
       (ref->>'char_end')::integer-(ref->>'char_start')::integer) is distinct from ref->>'quote' then
     raise exception 'exact current attribution evidence required' using errcode='22023';end if;
 end loop;
 result:=public.commit_lifetime_memoir_lane_page_before_attribution(p_lane_id,p_token,p_page_number,
   p_result-array['event_places','passage_dispositions'],p_page_digest);
 if result->>'status'='page_saved' then
   insert into public.user_memory_attribution_window(user_id,project_id,source_id,source_version,char_start,char_end,policy_epoch,disposition,reason)
   values(snap.user_id,snap.project_id,(page->'source'->>'id')::uuid,(page->'source'->>'version')::bigint,
     (page->>'core_start')::integer,(page->>'core_end')::integer,snap.policy_epoch,
     case when page->'attribution_context'->>'decision' in ('non_story','withheld') then page->'attribution_context'->>'decision' else 'unresolved' end,
     case when page->'attribution_context'->>'decision'='extract' then 'no_supported_event' else page->'attribution_context'->>'reason' end)
   on conflict(user_id,project_id,source_id,source_version,char_start,char_end) do update set
     policy_epoch=excluded.policy_epoch,disposition=excluded.disposition,reason=excluded.reason;
   update public.user_memory_attribution_window set method=case when page->'attribution_context'->>'decision'='extract' then 'model' else 'rule' end
     where user_id=snap.user_id and project_id=snap.project_id and source_id=current_source.id and source_version=current_source.version
       and char_start=(page->>'core_start')::integer and char_end=(page->>'core_end')::integer;
   for item in select value from jsonb_array_elements(coalesce(p_result->'passage_dispositions','[]')) loop
     ref:=item->'source_ref';
     if exists(select 1 from jsonb_object_keys(item) k where k not in ('disposition','reason','source_ref'))
       or coalesce(item->>'disposition','') not in ('non_story','unresolved','withheld')
       or coalesce(item->>'reason','') not in ('conversation_control','profile_introduction','ambiguous_context','no_supported_event',
         'uncertain_identity','uncertain_attribution','privacy_withheld') then raise exception 'invalid passage disposition' using errcode='22023';end if;
     if item->>'disposition' in ('non_story','withheld') and exists(select 1 from public.user_memory_event_source r
       where r.user_id=snap.user_id and r.project_id=snap.project_id and r.source_id=current_source.id
         and r.source_version=current_source.version and r.stage_progress_role='primary'
         and (r.evidence->>'char_start')::integer<(ref->>'char_end')::integer
         and (r.evidence->>'char_end')::integer>(ref->>'char_start')::integer) then
       raise exception 'non-story disposition conflicts with direct testimony' using errcode='22023';end if;
     insert into public.user_memory_attribution_window(user_id,project_id,source_id,source_version,char_start,char_end,policy_epoch,disposition,reason)
     values(snap.user_id,snap.project_id,current_source.id,current_source.version,(ref->>'char_start')::integer,
       (ref->>'char_end')::integer,snap.policy_epoch,item->>'disposition',item->>'reason')
     on conflict(user_id,project_id,source_id,source_version,char_start,char_end) do update set
       policy_epoch=excluded.policy_epoch,disposition=excluded.disposition,reason=excluded.reason,method='model';
   end loop;
   for item in select value from jsonb_array_elements(coalesce(p_result->'event_places','[]')) loop
     if jsonb_typeof(item->'event_index') is distinct from 'number' or item->>'event_index' !~ '^[0-9]{1,2}$' then
       raise exception 'bounded event proposal index required' using errcode='22023';end if;
     ref:=item->'source_ref';proposal:=p_result->'events'->((item->>'event_index')::integer);
     if exists(select 1 from jsonb_object_keys(item) k where k not in ('event_index','role','place','source_ref'))
       or proposal is null or coalesce(item->>'role','') not in ('setting','origin','destination')
       or exists(select 1 from jsonb_object_keys(item->'place') k where k not in ('place','hierarchy','granularity')) then
       raise exception 'invalid selective event place' using errcode='22023';end if;
     perform public.validate_two_lane_places(ref->>'quote',jsonb_build_array(item->'place'||'{"schema_version":1}'));
     if exists(select 1 from jsonb_array_elements_text(item->'place'->'hierarchy') label where
       label ~* '(医院|学校|大学|学院|车站|家属院|小区|大厦|大楼|街|路|巷)([0-9]+号)?$|\m(hospital|school|university|college|station|street|road|lane|avenue|building|compound)\M(\s+[0-9]+)?$') then
       raise exception 'public coarse geography required' using errcode='22023';end if;
     select min(e.id),count(*) into selected_event,matches from public.user_memory_event e
     where e.user_id=snap.user_id and e.project_id=snap.project_id and e.status='active'
       and ((proposal ? 'existing_id' and e.id=proposal->>'existing_id') or (not(proposal ? 'existing_id')
         and e.change_sequence>snap.event_high_water and e.kind=proposal->>'kind' and e.data->>'title'=proposal->>'title'))
       and exists(select 1 from public.user_memory_event_source r where r.user_id=e.user_id and r.project_id=e.project_id
         and r.event_id=e.id and r.source_id=current_source.id and r.source_version=current_source.version and r.stage_progress_role='primary'
         and (r.evidence->>'char_start')::integer<=(ref->>'char_start')::integer
         and (r.evidence->>'char_end')::integer>=(ref->>'char_end')::integer
         and proposal->'source_refs' @> jsonb_build_array(r.evidence));
     if matches<>1 then raise exception 'place requires one exact event passage' using errcode='22023';end if;
     insert into public.user_memory_event_place(user_id,project_id,event_id,source_id,source_version,char_start,char_end,role,place)
     values(snap.user_id,snap.project_id,selected_event,current_source.id,current_source.version,
       (ref->>'char_start')::integer,(ref->>'char_end')::integer,item->>'role',item->'place')
     on conflict(user_id,project_id,event_id,source_id,source_version,char_start,char_end,role,place_key) do nothing;
     get diagnostics inserted=ROW_COUNT;
     if inserted>0 then changed:=array_append(changed,selected_event);end if;
   end loop;
   for selected_event in select distinct v from unnest(changed) v loop
     update public.user_memoir_project set event_sequence=event_sequence+1 where user_id=snap.user_id and project_id=snap.project_id
       returning event_sequence into next_change;
     update public.user_memory_event set revision=revision+1,change_sequence=next_change,
       data=data||jsonb_build_object('place_revision',coalesce((data->>'place_revision')::bigint,0)+1)
     where user_id=snap.user_id and project_id=snap.project_id and id=selected_event returning * into event_row;
     insert into public.user_memory_event_revision(user_id,project_id,event_id,revision,record,actor,origin)
       values(snap.user_id,snap.project_id,selected_event,event_row.revision,public.memory_event_record(event_row),'model','author_timeline');
   end loop;
   if cardinality(changed)>0 then update public.user_lifetime_lane_snapshot set event_high_water=(select event_sequence
     from public.user_memoir_project where user_id=snap.user_id and project_id=snap.project_id) where id=snap.id;end if;
   update public.user_memoir_project set attribution_revision=attribution_revision+1 where user_id=snap.user_id and project_id=snap.project_id;
   insert into public.user_memory_attribution_receipt values(snap.id,p_page_number,p_page_digest,hash);
   result:=result||jsonb_build_object('attribution',public.lifetime_source_attribution_summary(snap.user_id,snap.project_id,current_source.id)
     ||jsonb_build_object('timeline_method',case when page->'attribution_context'->>'decision'='extract' then 'model' else 'rule' end));
 end if;
 return result;
end $$;
revoke all on function public.commit_lifetime_memoir_lane_page(uuid,uuid,bigint,jsonb,text) from public,anon,authenticated;
grant execute on function public.commit_lifetime_memoir_lane_page(uuid,uuid,bigint,jsonb,text) to service_role;
notify pgrst,'reload schema';
commit;
