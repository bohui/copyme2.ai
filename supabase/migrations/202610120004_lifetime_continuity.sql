-- Evidence-backed typed continuity. Existing phase/language preference authorities
-- are not replaced; these rows are disposable source-dependent projections.
begin;
create table public.user_lifetime_continuity (
  user_id uuid not null,
  conversation_id uuid not null,
  record_id text not null check(length(record_id) between 1 and 128),
  kind text not null check(kind in ('chosen_name','language','active_question','unresolved_reference',
    'paused_topic','excluded_topic','commitment','person')),
  revision bigint not null check(revision>0),
  last_source_sequence bigint not null default 0 check(last_source_sequence>=0),
  policy_epoch bigint not null check(policy_epoch>0),
  data jsonb not null check(jsonb_typeof(data)='object'),
  primary key(user_id,conversation_id,record_id),
  foreign key(user_id,conversation_id) references public.user_lifetime_conversation(user_id,conversation_id) on delete cascade
);
create index lifetime_continuity_working_set on public.user_lifetime_continuity(user_id,conversation_id,
 (case kind when 'unresolved_reference' then 0 when 'commitment' then 1 else 2 end),last_source_sequence desc,record_id);
alter table public.user_lifetime_continuity enable row level security;
revoke all on public.user_lifetime_continuity from public,anon,authenticated;
-- No direct SELECT: policy/source dependencies must be checked by the reader RPC.

create function public.save_lifetime_continuity(p_conversation_id uuid,p_record_id text,p_kind text,
  p_expected_revision bigint,p_policy_epoch bigint,p_lease_token uuid,p_data jsonb)
returns jsonb language plpgsql security definer set search_path=public,auth as $$
declare owner uuid:=auth.uid(); project text; epoch bigint; ref jsonb; source public.user_narrator_source%rowtype;
  saved public.user_lifetime_continuity%rowtype; last_sequence bigint:=0;
begin
  if owner is null then raise exception 'authenticated owner required'; end if;
  select project_id into project from public.user_lifetime_conversation where user_id=owner and conversation_id=p_conversation_id;
  if not found then raise exception 'conversation unavailable'; end if;
  select policy_epoch into epoch from public.user_memoir_project where user_id=owner and project_id=project for update;
  if epoch is distinct from p_policy_epoch then raise exception 'stale policy' using errcode='40001'; end if;
  perform 1 from public.user_agent_turn_lease where user_id=owner and lease_token=p_lease_token and expires_at>clock_timestamp() for update;
  if not found then raise exception 'valid turn lease required' using errcode='40001'; end if;
  if p_data is null or jsonb_typeof(p_data)<>'object'
     or exists(select 1 from jsonb_object_keys(p_data) k where k not in ('text','assertion','uncertainty','source_refs'))
     or jsonb_typeof(p_data->'text') is distinct from 'string' or length(p_data->>'text') not between 1 and 2000
     or coalesce(p_data->>'assertion','') not in ('asserted','inferred')
     or (p_data->'uncertainty' is not null and p_data->'uncertainty'<>'null'::jsonb and
         (jsonb_typeof(p_data->'uncertainty')<>'string' or length(p_data->>'uncertainty')>2000))
     or jsonb_typeof(p_data->'source_refs') is distinct from 'array' then raise exception 'invalid continuity'; end if;
  if jsonb_array_length(p_data->'source_refs') not between 1 and 32 then raise exception 'bounded evidence required'; end if;
  for ref in select value from jsonb_array_elements(p_data->'source_refs') loop
    if jsonb_typeof(ref) is distinct from 'object' then raise exception 'evidence object required'; end if;
    if not (ref ?& array['source_id','version','char_start','char_end','quote'])
      or exists(select 1 from jsonb_object_keys(ref) k where k not in ('source_id','version','char_start','char_end','quote'))
      or jsonb_typeof(ref->'source_id') is distinct from 'string'
      or jsonb_typeof(ref->'version') is distinct from 'number' or coalesce(ref->>'version','') !~ '^[1-9][0-9]*$'
      or jsonb_typeof(ref->'char_start') is distinct from 'number' or coalesce(ref->>'char_start','') !~ '^[0-9]+$'
      or jsonb_typeof(ref->'char_end') is distinct from 'number' or coalesce(ref->>'char_end','') !~ '^[1-9][0-9]*$'
      or jsonb_typeof(ref->'quote') is distinct from 'string' or length(ref->>'quote') not between 1 and 100000
      then raise exception 'typed exact evidence required'; end if;
    select * into source from public.user_narrator_source where user_id=owner and project_id=project
      and id=(ref->>'source_id')::uuid and version=(ref->>'version')::bigint and status='active';
    if not found or (ref->>'char_start')::integer<0 or (ref->>'char_end')::integer<=(ref->>'char_start')::integer
      or (ref->>'char_end')::integer>length(source.text)
      or substring(source.text from (ref->>'char_start')::integer+1 for (ref->>'char_end')::integer-(ref->>'char_start')::integer)
         is distinct from ref->>'quote' then raise exception 'invalid source evidence'; end if;
    last_sequence:=greatest(last_sequence,source.sequence);
    if not (ref ?& array['source_id','version','char_start','char_end','quote']) then raise exception 'complete evidence required'; end if;
  end loop;
  if p_expected_revision is null or p_expected_revision<0 then raise exception 'revision required'; end if;
  insert into public.user_lifetime_continuity(user_id,conversation_id,record_id,kind,revision,policy_epoch,data,last_source_sequence)
    select owner,p_conversation_id,p_record_id,p_kind,1,epoch,p_data,last_sequence where p_expected_revision=0
    on conflict do nothing returning * into saved;
  if not found then
    update public.user_lifetime_continuity set kind=p_kind,revision=revision+1,policy_epoch=epoch,data=p_data,last_source_sequence=last_sequence
      where user_id=owner and conversation_id=p_conversation_id and record_id=p_record_id and revision=p_expected_revision returning * into saved;
    if not found then raise exception 'continuity revision conflict' using errcode='40001'; end if;
  end if;
  return to_jsonb(saved)-'user_id'-'conversation_id'-'last_source_sequence';
end;
$$;

create function public.read_lifetime_continuity(p_conversation_id uuid,p_policy_epoch bigint,p_after text default '',p_limit integer default 100)
returns jsonb language plpgsql security definer set search_path=public,auth as $$
declare owner uuid:=auth.uid(); project text; epoch bigint; records jsonb; has_more boolean;
begin
  select project_id into project from public.user_lifetime_conversation where user_id=owner and conversation_id=p_conversation_id;
  if not found then raise exception 'conversation unavailable'; end if;
  select policy_epoch into epoch from public.user_memoir_project where user_id=owner and project_id=project for share;
  if epoch is distinct from p_policy_epoch then raise exception 'stale policy' using errcode='40001'; end if;
  if p_limit is null or p_limit not between 1 and 100 or p_after is null then raise exception 'invalid page'; end if;
  select coalesce(jsonb_agg(to_jsonb(r)-'user_id'-'conversation_id'-'last_source_sequence' order by r.record_id),'[]') into records from (
    select c.* from public.user_lifetime_continuity c where c.user_id=owner and c.conversation_id=p_conversation_id
      and c.policy_epoch=epoch and c.record_id>p_after
      and not exists(select 1 from jsonb_array_elements(c.data->'source_refs') ref where not exists(
        select 1 from public.user_narrator_source s where s.user_id=owner and s.project_id=project
          and s.id=(ref->>'source_id')::uuid and s.version=(ref->>'version')::bigint and s.status='active'))
    order by c.record_id limit p_limit+1) r;
  has_more:=jsonb_array_length(records)>p_limit;
  if has_more then records:=records-p_limit; end if;
  return jsonb_build_object('schema_version',1,'records',records,'complete',not has_more,
    'next_cursor',case when has_more then records->-1->>'record_id' else null end);
end;
$$;
revoke all on function public.save_lifetime_continuity(uuid,text,text,bigint,bigint,uuid,jsonb),
 public.read_lifetime_continuity(uuid,bigint,text,integer) from public,anon;
grant execute on function public.save_lifetime_continuity(uuid,text,text,bigint,bigint,uuid,jsonb),
 public.read_lifetime_continuity(uuid,bigint,text,integer) to authenticated;
commit;
