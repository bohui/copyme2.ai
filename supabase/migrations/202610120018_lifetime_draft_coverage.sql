-- Acknowledged canonical intake prefixes make append/repeated-receipt work
-- proportional to new evidence. No source bytes, commercial grants, historical
-- mapping/backfill or production activation are introduced here.
begin;
alter table public.user_memoir_project add column draft_round_epoch bigint not null default 0;
alter table public.user_lifetime_draft_snapshot
 add column coverage_schema_version integer not null default 0 check(coverage_schema_version in (0,1)),
 add column base_snapshot_id uuid references public.user_lifetime_draft_snapshot(id) deferrable initially deferred,
 add column source_after bigint not null default 0,
 add column round_after bigint not null default 0,
 add column round_revision bigint not null default 0,
 add column scan_complete boolean not null default false,
 add constraint lifetime_draft_coverage_bounds check(source_after between 0 and source_revision
   and round_after between 0 and round_high_water and round_revision>=0
   and (base_snapshot_id is null)=(source_after=0 and round_after=0)
   and base_snapshot_id is distinct from id);
-- The former uniqueness did not distinguish completed-round metadata edits.
do $$ declare key_name text; begin
 select conname into key_name from pg_constraint where conrelid='public.user_lifetime_draft_snapshot'::regclass and contype='u';
 execute format('alter table public.user_lifetime_draft_snapshot drop constraint %I',key_name);
end $$;
alter table public.user_lifetime_draft_snapshot add constraint lifetime_draft_snapshot_scope
 unique(event_id,policy_epoch,preference_revision,locale,round_revision);
create index lifetime_draft_acknowledged_prefix on public.user_lifetime_draft_snapshot
 (user_id,conversation_id,policy_epoch,preference_revision,locale,round_revision,source_revision desc,round_high_water desc,id)
 where scan_complete;
create index lifetime_draft_round_coverage on public.user_lifetime_draft_snapshot(user_id,project_id,round_high_water);

-- Round ordinals/identities remain authoritative and untouched. Appending a
-- new highest ordinal does not invalidate an old prefix; editing/deleting a
-- covered link or backfilling a covered ordinal does. Even an in-flight frozen
-- snapshot must restart after such a mutation.
create function public.fence_lifetime_draft_round_change() returns trigger
language plpgsql security definer set search_path='' as $$
begin
 if TG_OP='INSERT' then
   if exists(select 1 from public.user_lifetime_draft_snapshot s
       where s.user_id=new.user_id and s.project_id=new.project_id and s.round_high_water>=new.ordinal) then
     update public.user_memoir_project set draft_round_epoch=draft_round_epoch+1 where user_id=new.user_id and project_id=new.project_id;
   end if;
 elsif TG_OP='DELETE' or row(old.user_id,old.project_id,old.turn_id,old.ordinal,old.memory_id)
       is distinct from row(new.user_id,new.project_id,new.turn_id,new.ordinal,new.memory_id) then
   update public.user_memoir_project set draft_round_epoch=draft_round_epoch+1 where user_id=old.user_id and project_id=old.project_id;
   if TG_OP='UPDATE' and row(old.user_id,old.project_id) is distinct from row(new.user_id,new.project_id) then
     update public.user_memoir_project set draft_round_epoch=draft_round_epoch+1 where user_id=new.user_id and project_id=new.project_id;
   end if;
 end if;
 return null;
end $$;
create trigger lifetime_draft_round_change after insert or update or delete on public.user_completed_round
 for each row execute function public.fence_lifetime_draft_round_change();
revoke all on function public.fence_lifetime_draft_round_change() from public,anon,authenticated,service_role;

-- ACK freezes the current governing scope too: preference/round changes do
-- not necessarily emit their own receipt. An authoritative conflict requires
-- the broker to discard its completed local checkpoint and page afresh.
create function public.assert_lifetime_draft_receipt_scope(p_receipt_id uuid) returns void
language plpgsql security definer set search_path='' as $$
declare receipt public.user_private_draft_outbox%rowtype; identity public.user_lifetime_conversation%rowtype;
 project public.user_memoir_project%rowtype;
begin
 select * into receipt from public.user_private_draft_outbox where id=p_receipt_id;
 select * into identity from public.user_lifetime_conversation where user_id=receipt.user_id and project_id=receipt.project_id;
 if not found then return;end if;
 select * into project from public.user_memoir_project where user_id=receipt.user_id and project_id=receipt.project_id for share;
 select * into identity from public.user_lifetime_conversation where conversation_id=identity.conversation_id for share;
 if not exists(select 1 from public.user_lifetime_draft_snapshot where event_id=p_receipt_id and scan_complete) then
   raise exception 'private draft receipt coverage incomplete' using errcode='40001';
 end if;
 if not exists(select 1 from public.user_lifetime_draft_snapshot s where s.event_id=p_receipt_id and s.scan_complete
     and s.user_id=receipt.user_id and s.project_id=receipt.project_id and s.conversation_id=identity.conversation_id
     and s.policy_epoch=project.policy_epoch and s.preference_revision=identity.preference_revision
     and s.round_revision=project.draft_round_epoch) then
   raise exception 'private draft receipt scope stale' using errcode='40001';
 end if;
end $$;
revoke all on function public.assert_lifetime_draft_receipt_scope(uuid) from public,anon,authenticated,service_role;
create function public.require_lifetime_draft_receipt_coverage() returns trigger
language plpgsql security definer set search_path='' as $$
begin
 if new.delivered and not old.delivered then perform public.assert_lifetime_draft_receipt_scope(new.id);end if;
 return new;
end $$;
create trigger lifetime_draft_receipt_coverage before update of delivered on public.user_private_draft_outbox
 for each row execute function public.require_lifetime_draft_receipt_coverage();
revoke all on function public.require_lifetime_draft_receipt_coverage() from public,anon,authenticated,service_role;

create or replace function public.private_draft_event_page(p_event_id uuid,p_cursor uuid default null,p_limit integer default 32)
returns jsonb language plpgsql security definer set search_path=public,auth as $$
declare receipt public.user_private_draft_outbox%rowtype; identity public.user_lifetime_conversation%rowtype;
 project public.user_memoir_project%rowtype; frozen public.user_lifetime_draft_snapshot%rowtype;
 position public.user_lifetime_draft_cursor%rowtype;
 records jsonb:='[]'; rounds jsonb:='[]'; last_row jsonb; next_cursor uuid;
 source_done boolean:=false; last_source bigint:=0; last_offset integer:=-1; last_round bigint:=0;
 remaining integer; has_more boolean; output_locale text; round_high bigint;
 prefix public.user_lifetime_draft_snapshot%rowtype; output jsonb;
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
   if frozen.policy_epoch<>project.policy_epoch or frozen.preference_revision<>identity.preference_revision or frozen.locale<>output_locale or frozen.round_revision<>project.draft_round_epoch then
     raise exception 'stale private draft snapshot' using errcode='40001'; end if;
   last_source:=position.last_source;last_offset:=position.last_offset;last_round:=position.last_round;source_done:=position.sources_complete;
 else
   select coalesce(max(ordinal),0) into round_high from public.user_completed_round
     where user_id=receipt.user_id and project_id=receipt.project_id;
   -- Prefixes are server-owned attestations, never client-selected offsets.
   -- Completed but unacknowledged work cannot be used to skip a required job.
   select s.* into prefix from public.user_lifetime_draft_snapshot s
     join public.user_private_draft_outbox r on r.id=s.event_id and r.delivered
     where s.user_id=receipt.user_id and s.project_id=receipt.project_id and s.conversation_id=identity.conversation_id
       and s.policy_epoch=project.policy_epoch and s.preference_revision=identity.preference_revision
       and s.locale=output_locale and s.round_revision=project.draft_round_epoch and s.scan_complete
       and s.source_revision<=project.source_sequence and s.round_high_water<=round_high
       and (s.source_revision>0 or s.round_high_water>0) and s.event_id<>receipt.id
     order by s.source_revision desc,s.round_high_water desc,s.id limit 1;
   insert into public.user_lifetime_draft_snapshot(event_id,user_id,project_id,conversation_id,policy_epoch,
      preference_revision,source_revision,event_revision,round_high_water,completed,locale,
      coverage_schema_version,base_snapshot_id,source_after,round_after,round_revision)
   values(receipt.id,receipt.user_id,receipt.project_id,identity.conversation_id,project.policy_epoch,
      identity.preference_revision,project.source_sequence,project.event_sequence,round_high,
      coalesce((select rounds_completed from public.user_recall_usage where user_id=receipt.user_id),0),output_locale,
      1,prefix.id,coalesce(prefix.source_revision,0),coalesce(prefix.round_high_water,0),project.draft_round_epoch)
   on conflict on constraint lifetime_draft_snapshot_scope do nothing;
   select * into frozen from public.user_lifetime_draft_snapshot where event_id=receipt.id and policy_epoch=project.policy_epoch
     and preference_revision=identity.preference_revision and locale=output_locale and round_revision=project.draft_round_epoch;
   last_source:=frozen.source_after;last_round:=frozen.round_after;
   last_offset:=case when last_source>0 then 2147483647 else -1 end;
   source_done:=last_source=frozen.source_revision;
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
   -- Source positions are the append-only inventory, including tombstones.
   -- A missing historical position is an inventory/reconciliation gate, never
   -- permission to report an apparently complete highest-numbered record.
   for last_row in select value from jsonb_array_elements(records) loop
     if (last_row->>'sequence')::bigint not between last_source and last_source+1 then
       raise exception 'private draft source inventory incomplete' using errcode='40001';
     end if;
     last_source:=(last_row->>'sequence')::bigint;last_offset:=(last_row->>'char_start')::integer;
   end loop;
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
 if not has_more then
   if last_source<>frozen.source_revision or last_round<>frozen.round_high_water then
     raise exception 'private draft coverage incomplete' using errcode='40001';
   end if;
   update public.user_lifetime_draft_snapshot set scan_complete=true where id=frozen.id;
 end if;
 output:=to_jsonb(frozen)-'id'-'scan_complete';
 -- In-flight pre-upgrade cursors must replay byte-identical page envelopes.
 if frozen.coverage_schema_version=0 then
   output:=output-'coverage_schema_version'-'base_snapshot_id'-'source_after'-'round_after'-'round_revision';
 end if;
 return output || jsonb_build_object('schema_version',1,'protocol','lifetime_draft_pages',
   'snapshot_id',frozen.id,'cursor',p_cursor,'records',records,'complete',not has_more,'next_cursor',next_cursor);
end $$;
revoke all on function public.private_draft_event_page(uuid,uuid,integer) from public,anon,authenticated;
grant execute on function public.private_draft_event_page(uuid,uuid,integer) to service_role;

-- Materialize the exact pre-existing commercial milestone set in bounded
-- chunks. This cursor authorizes no purchase, allowance, consent or draft.
create table public.user_lifetime_milestone_cursor (
 user_id uuid not null,project_id text not null,locale text not null,
 cadence integer not null check(cadence between 1 and 1000000),
 covered_milestone bigint not null default 0 check(covered_milestone>=0),
 primary key(user_id,project_id,locale,cadence),
 foreign key(user_id,project_id) references public.user_memoir_project on delete cascade
);
alter table public.user_lifetime_milestone_cursor enable row level security;
revoke all on public.user_lifetime_milestone_cursor from public,anon,authenticated;
alter function public.queue_memoir_receipt(uuid,integer) rename to queue_memoir_receipt_legacy_coverage;
revoke all on function public.queue_memoir_receipt_legacy_coverage(uuid,integer) from public,anon,authenticated,service_role;

create or replace function public.queue_memoir_receipt(p_receipt_id uuid,p_cadence integer default 5)
returns jsonb language plpgsql security definer set search_path='' as $$
declare receipt public.user_private_draft_outbox%rowtype; project public.user_memoir_project%rowtype; lane_id uuid; composer_id uuid;
  completed_round bigint; milestone bigint; output_locale text;
  covered bigint; through_milestone bigint;
begin
  if p_cadence is null or p_cadence not between 1 and 1000000 then raise exception 'invalid cadence' using errcode='22023'; end if;
  select * into receipt from public.user_private_draft_outbox where id=p_receipt_id for update;
  if not found then return null; end if;
  if not exists(select 1 from public.user_lifetime_conversation where user_id=receipt.user_id and project_id=receipt.project_id) then
    return public.queue_memoir_receipt_legacy_coverage(p_receipt_id,p_cadence);
  end if;
  select * into project from public.user_memoir_project where user_id=receipt.user_id and project_id=receipt.project_id for update;
  if not found then return null; end if;
  perform public.assert_lifetime_draft_receipt_scope(receipt.id);
  select coalesce(max(ordinal),0) into completed_round from public.user_completed_round where user_id=receipt.user_id and project_id=receipt.project_id;
  milestone:=(completed_round/p_cadence)*p_cadence;
  select coalesce(profile->>'preferred_language','en-AU') into output_locale from public.user_profile where user_id=receipt.user_id;
  output_locale:=case when output_locale='zh-CN' then 'zh-CN' else 'en-AU' end;
  insert into public.user_lifetime_milestone_cursor(user_id,project_id,locale,cadence)
    values(receipt.user_id,receipt.project_id,output_locale,p_cadence) on conflict do nothing;
  select covered_milestone into covered from public.user_lifetime_milestone_cursor
    where user_id=receipt.user_id and project_id=receipt.project_id and locale=output_locale and cadence=p_cadence for update;
  through_milestone:=least(milestone,covered+128*p_cadence::bigint);
  if through_milestone>covered then
    insert into public.user_memoir_milestone(user_id,project_id,locale,milestone)
      select receipt.user_id,receipt.project_id,output_locale,checkpoint
        from pg_catalog.generate_series(covered+p_cadence::bigint,through_milestone,p_cadence::bigint) checkpoint
      on conflict do nothing;
    update public.user_lifetime_milestone_cursor set covered_milestone=through_milestone
      where user_id=receipt.user_id and project_id=receipt.project_id and locale=output_locale and cadence=p_cadence;
  end if;
  if through_milestone<milestone then
    return pg_catalog.jsonb_build_object('coverage_pending',true,'timeline_lane_id',null,'composer_lane_id',null);
  end if;
  insert into public.user_memoir_lane(user_id,project_id,skill,pending,target_source,target_event)
    values(receipt.user_id,receipt.project_id,'timeline',true,project.source_sequence,project.event_sequence)
    on conflict(user_id,project_id,skill) do update set
      pending=public.user_memoir_lane.pending or exists(select 1 from public.user_narrator_source
        where user_id=receipt.user_id and project_id=receipt.project_id and processing_status<>'succeeded' and status='active'),
      attempts=case when excluded.target_source>public.user_memoir_lane.target_source then 0 else public.user_memoir_lane.attempts end,
      error=case when excluded.target_source>public.user_memoir_lane.target_source then null else public.user_memoir_lane.error end,
      target_source=greatest(public.user_memoir_lane.target_source,excluded.target_source),target_event=excluded.target_event
    returning id into lane_id;
  if milestone>0 then
    insert into public.user_memoir_lane(user_id,project_id,skill,pending,target_source,target_event,target_milestone,locale)
      values(receipt.user_id,receipt.project_id,'composer',true,project.source_sequence,project.event_sequence,milestone,output_locale)
      on conflict(user_id,project_id,skill) do update set
        pending=public.user_memoir_lane.pending or excluded.locale<>public.user_memoir_lane.locale or excluded.target_milestone>public.user_memoir_lane.target_milestone or
          (receipt.change_kind in ('correction','revocation','edit','delete') and
            (excluded.target_event>public.user_memoir_lane.successful_event or excluded.target_source>public.user_memoir_lane.successful_source)),
        attempts=case when excluded.target_milestone>public.user_memoir_lane.target_milestone or excluded.target_event>public.user_memoir_lane.target_event then 0 else public.user_memoir_lane.attempts end,
        error=case when excluded.target_milestone>public.user_memoir_lane.target_milestone or excluded.target_event>public.user_memoir_lane.target_event then null else public.user_memoir_lane.error end,
        target_source=excluded.target_source,target_event=excluded.target_event,target_milestone=excluded.target_milestone,locale=excluded.locale
      returning id into composer_id;
  end if;
  update public.user_private_draft_outbox set delivered=true where id=p_receipt_id;
  return pg_catalog.jsonb_build_object('timeline_lane_id',lane_id,'composer_lane_id',composer_id);
end $$;
revoke all on function public.queue_memoir_receipt(uuid,integer) from public,anon,authenticated;
grant execute on function public.queue_memoir_receipt(uuid,integer) to service_role;

commit;
