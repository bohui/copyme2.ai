-- Governed private-draft intake is bounded and resumable. This is not the
-- bounded composer implementation: mapped lanes wait explicitly, without
-- invoking the old all-history aggregation or granting a commercial draft.
begin;
create table public.user_lifetime_draft_snapshot (
 id uuid primary key default gen_random_uuid(), event_id uuid not null references public.user_private_draft_outbox(id) on delete cascade,
 user_id uuid not null, project_id text not null, conversation_id uuid not null,
 policy_epoch bigint not null, preference_revision bigint not null,
 source_revision bigint not null, event_revision bigint not null, round_high_water bigint not null,
 completed bigint not null, locale text not null,
 unique(event_id,policy_epoch,preference_revision,locale),
 foreign key(user_id,conversation_id) references public.user_lifetime_conversation(user_id,conversation_id) on delete cascade
);
create table public.user_lifetime_draft_cursor (
 id uuid primary key default gen_random_uuid(), snapshot_id uuid not null references public.user_lifetime_draft_snapshot(id) on delete cascade,
 last_source bigint not null, last_offset integer not null, last_round bigint not null,
 sources_complete boolean not null,
 constraint lifetime_draft_cursor_scope unique(snapshot_id,last_source,last_offset,last_round,sources_complete)
);
alter table public.user_lifetime_draft_snapshot enable row level security;
alter table public.user_lifetime_draft_cursor enable row level security;
revoke all on public.user_lifetime_draft_snapshot,public.user_lifetime_draft_cursor from public,anon,authenticated;

create function public.private_draft_event_page(p_event_id uuid,p_cursor uuid default null,p_limit integer default 32)
returns jsonb language plpgsql security definer set search_path=public,auth as $$
declare receipt public.user_private_draft_outbox%rowtype; identity public.user_lifetime_conversation%rowtype;
 project public.user_memoir_project%rowtype; frozen public.user_lifetime_draft_snapshot%rowtype;
 position public.user_lifetime_draft_cursor%rowtype;
 records jsonb:='[]'; rounds jsonb:='[]'; last_row jsonb; next_cursor uuid;
 source_done boolean:=false; last_source bigint:=0; last_offset integer:=-1; last_round bigint:=0;
 remaining integer; has_more boolean; output_locale text;
begin
 if p_limit is null or p_limit not between 1 and 32 then raise exception 'invalid draft page bounds' using errcode='22023'; end if;
 select * into receipt from public.user_private_draft_outbox where id=p_event_id;
 if not found then return null; end if;
 select * into identity from public.user_lifetime_conversation where user_id=receipt.user_id and project_id=receipt.project_id;
 if not found then raise exception 'governed draft identity required' using errcode='22023'; end if;
 select * into project from public.user_memoir_project where user_id=receipt.user_id and project_id=receipt.project_id for share;
 select * into identity from public.user_lifetime_conversation where conversation_id=identity.conversation_id for share;
 select case when profile->>'preferred_language'='zh-CN' then 'zh-CN' else 'en-AU' end into output_locale
   from public.user_profile where user_id=receipt.user_id;
 output_locale:=coalesce(output_locale,'en-AU');
 if p_cursor is not null then
   select * into position from public.user_lifetime_draft_cursor where id=p_cursor;
   if not found then raise exception 'invalid draft cursor' using errcode='22023'; end if;
   select * into frozen from public.user_lifetime_draft_snapshot where id=position.snapshot_id
     and event_id=receipt.id and user_id=receipt.user_id and project_id=receipt.project_id and conversation_id=identity.conversation_id;
   if not found then raise exception 'draft cursor scope mismatch' using errcode='22023'; end if;
   if frozen.policy_epoch<>project.policy_epoch or frozen.preference_revision<>identity.preference_revision or frozen.locale<>output_locale then
     raise exception 'stale private draft snapshot' using errcode='40001'; end if;
   last_source:=position.last_source;last_offset:=position.last_offset;last_round:=position.last_round;source_done:=position.sources_complete;
 else
   insert into public.user_lifetime_draft_snapshot(event_id,user_id,project_id,conversation_id,policy_epoch,
      preference_revision,source_revision,event_revision,round_high_water,completed,locale)
   values(receipt.id,receipt.user_id,receipt.project_id,identity.conversation_id,project.policy_epoch,
      identity.preference_revision,project.source_sequence,project.event_sequence,
      coalesce((select max(ordinal) from public.user_completed_round where user_id=receipt.user_id and project_id=receipt.project_id),0),
      coalesce((select rounds_completed from public.user_recall_usage where user_id=receipt.user_id),0),output_locale)
   on conflict(event_id,policy_epoch,preference_revision,locale) do nothing;
   select * into frozen from public.user_lifetime_draft_snapshot where event_id=receipt.id and policy_epoch=project.policy_epoch
     and preference_revision=identity.preference_revision and locale=output_locale;
 end if;
 if not source_done then
   select coalesce(jsonb_agg(r.data order by r.sequence,r.chunk_start),'[]') into records from (
     select s.sequence,chunk_start,jsonb_build_object('record_type','source','source_id',s.source_id,'version',s.version,
       'sequence',s.sequence,'char_start',chunk_start,'char_end',case when s.status='active' then least(chunk_start+2048,length(s.text)) else 0 end,
       'text',case when s.status='active' then substring(s.text from chunk_start+1 for 2048) else null end,
       'kind',coalesce(s.kind,'narrator_chat'),'language',coalesce(s.language,'en-AU'),'status',s.status) as data
     from (select pos.sequence,pos.source_id,pos.version,src.kind,src.language,
         case when src.id is null then 'withdrawn' when src.version<>pos.version then 'superseded' else src.status end as status,
         case when src.version=pos.version and src.status='active' then src.text else null end as text
       from (select * from public.user_lifetime_source_position where user_id=receipt.user_id and project_id=receipt.project_id
           and sequence>=last_source and sequence<=frozen.source_revision order by sequence limit p_limit+2) pos
       left join public.user_narrator_source src on src.user_id=pos.user_id and src.project_id=pos.project_id and src.id=pos.source_id) s
     cross join lateral generate_series(0,case when s.status='active' then greatest(length(s.text)-1,0) else 0 end,2048) chunk_start
     where s.sequence>last_source or chunk_start>last_offset
     order by s.sequence,chunk_start limit p_limit+1) r;
   source_done:=jsonb_array_length(records)<=p_limit;
   if not source_done then records:=records-p_limit; end if;
   if jsonb_array_length(records)>0 then
     last_row:=records->-1;last_source:=(last_row->>'sequence')::bigint;last_offset:=(last_row->>'char_start')::integer;
   end if;
 end if;
 remaining:=p_limit-jsonb_array_length(records);
 has_more:=not source_done;
 if source_done then
   select coalesce(jsonb_agg(r.data order by r.ordinal),'[]') into rounds from (
     select ordinal,jsonb_build_object('record_type','round','turn_id',turn_id,'ordinal',ordinal,'memory_id',memory_id) as data
     from public.user_completed_round where user_id=receipt.user_id and project_id=receipt.project_id
       and ordinal>last_round and ordinal<=frozen.round_high_water order by ordinal limit remaining+1) r;
   has_more:=jsonb_array_length(rounds)>remaining;
   if has_more then rounds:=rounds-remaining; end if;
   if jsonb_array_length(rounds)>0 then last_round:=(rounds->-1->>'ordinal')::bigint;end if;
   records:=records||rounds;
 end if;
 if has_more then
   insert into public.user_lifetime_draft_cursor(snapshot_id,last_source,last_offset,last_round,sources_complete)
    values(frozen.id,last_source,last_offset,last_round,source_done)
    on conflict on constraint lifetime_draft_cursor_scope do update set snapshot_id=excluded.snapshot_id
    returning id into next_cursor;
 end if;
 return to_jsonb(frozen)-'id' || jsonb_build_object('schema_version',1,'protocol','lifetime_draft_pages',
   'snapshot_id',frozen.id,'cursor',p_cursor,'records',records,'complete',not has_more,'next_cursor',next_cursor);
end $$;
revoke all on function public.private_draft_event_page(uuid,uuid,integer) from public,anon,authenticated;
grant execute on function public.private_draft_event_page(uuid,uuid,integer) to service_role;

alter function public.private_draft_event_snapshot(uuid) rename to private_draft_event_snapshot_legacy_lifetime;
revoke all on function public.private_draft_event_snapshot_legacy_lifetime(uuid) from public,anon,authenticated,service_role;
create function public.private_draft_event_snapshot(p_event_id uuid) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
begin
 if exists(select 1 from public.user_private_draft_outbox r join public.user_lifetime_conversation c
     on c.user_id=r.user_id and c.project_id=r.project_id where r.id=p_event_id) then
   return public.private_draft_event_page(p_event_id);
 end if;
 return public.private_draft_event_snapshot_legacy_lifetime(p_event_id);
end $$;
revoke all on function public.private_draft_event_snapshot(uuid) from public,anon,authenticated;
grant execute on function public.private_draft_event_snapshot(uuid) to service_role;

-- The active canonical dispatcher selects the bounded ingress from this
-- owner-resolved receipt scope, never a client supplied identity or flag.
create or replace function public.read_memoir_receipt_scope(p_receipt_id uuid) returns jsonb
language sql security definer set search_path='' as $$
 select pg_catalog.jsonb_build_object('user_id',r.user_id,'project_id',r.project_id,'change_kind',r.change_kind)
   || case when c.conversation_id is null then '{}'::jsonb else
      pg_catalog.jsonb_build_object('conversation_id',c.conversation_id) end
 from public.user_private_draft_outbox r left join public.user_lifetime_conversation c
   on c.user_id=r.user_id and c.project_id=r.project_id where r.id=p_receipt_id and not r.delivered
$$;
revoke all on function public.read_memoir_receipt_scope(uuid) from public,anon,authenticated;
grant execute on function public.read_memoir_receipt_scope(uuid) to service_role;

-- Read-only detection never resolves or maps historical accounts.
create function public.read_lifetime_private_draft_head(p_project_id text) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare identity public.user_lifetime_conversation%rowtype; project public.user_memoir_project%rowtype;
begin
 if auth.uid() is null then raise exception 'authenticated owner required';end if;
 select * into identity from public.user_lifetime_conversation where user_id=auth.uid();
 if not found then return null;end if;
 -- A client-selected project may never downgrade a governed owner to the
 -- account-wide legacy adapter. Historical accounts without a mapping still
 -- return null above; no project is created, merged or reassigned here.
 if identity.project_id is distinct from p_project_id then
   return jsonb_build_object('schema_version',1,'owner_id',auth.uid(),'conversation_id',identity.conversation_id,
     'project_id',identity.project_id,'status','pending','preview',null,'updating',false,
     'retrieval_complete',false,'error','LIFETIME_PROJECT_REQUIRED');
 end if;
 select * into project from public.user_memoir_project where user_id=auth.uid() and project_id=p_project_id for share;
 return jsonb_build_object('schema_version',1,'owner_id',auth.uid(),'conversation_id',identity.conversation_id,
   'project_id',p_project_id,'policy_epoch',project.policy_epoch,'source_revision',project.source_sequence,
   'status','pending','preview',null,'updating',false,'retrieval_complete',false,'error','LIFETIME_COMPOSER_PENDING');
end $$;
revoke all on function public.read_lifetime_private_draft_head(text) from public,anon;
grant execute on function public.read_lifetime_private_draft_head(text) to authenticated;

-- Temporary, explicit capacity gate. The old claim constructs unbounded JSON
-- before Python can bound a prompt. Never enter it for a governed identity.
-- This gate must be replaced by source/event page-backed canonical lane claims
-- and bounded protected-section composition before W4 can be called complete.
-- Remaining implementation seams: memory_event_worker.execute_lane must
-- consume bounded claims; canonical_composer.composer_request and
-- compose_shared_snapshot must partition evidence/events without a full prior
-- manuscript; memoir_preview indexing/draft/review fallback and the composer
-- skill's host validators need page-backed manifests. Receipt coalescing or
-- incremental coverage is also required to avoid rescanning one frozen history
-- for every queued event. Do not remove this guard merely after paging intake.
alter function public.claim_memoir_lane(uuid,integer) rename to claim_memoir_lane_legacy_lifetime;
revoke all on function public.claim_memoir_lane_legacy_lifetime(uuid,integer) from public,anon,authenticated,service_role;
create function public.claim_memoir_lane(p_lane_id uuid,p_run_seconds integer default 300) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
begin
 if exists(select 1 from public.user_memoir_lane l join public.user_lifetime_conversation c
     on c.user_id=l.user_id and c.project_id=l.project_id where l.id=p_lane_id) then
   update public.user_memoir_lane set pending=true,error='LIFETIME_COMPOSER_PENDING',
     available_at=greatest(available_at,clock_timestamp()+interval '5 minutes') where id=p_lane_id and token is null;
   return null;
 end if;
 return public.claim_memoir_lane_legacy_lifetime(p_lane_id,p_run_seconds);
end $$;
revoke all on function public.claim_memoir_lane(uuid,integer) from public,anon,authenticated;
grant execute on function public.claim_memoir_lane(uuid,integer) to service_role;
commit;
