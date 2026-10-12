-- Stable owner/conversation/epoch-scoped opaque cursors. No secret leaves SQL.
begin;
-- Position metadata contains no narrator bytes. Updates preserve the old
-- sequence as a superseded tombstone instead of making compaction infer a gap.
create table public.user_lifetime_source_position (
  user_id uuid not null, project_id text not null, sequence bigint not null check(sequence>0),
  source_id uuid not null, version bigint not null,
  primary key(user_id,project_id,sequence),
  foreign key(user_id,project_id) references public.user_memoir_project on delete cascade
);
alter table public.user_lifetime_source_position enable row level security;
revoke all on public.user_lifetime_source_position from public,anon,authenticated;
create function public.record_lifetime_source_position() returns trigger
language plpgsql security definer set search_path='' as $$
begin
  if tg_op='UPDATE' then
    insert into public.user_lifetime_source_position values(old.user_id,old.project_id,old.sequence,old.id,old.version) on conflict do nothing;
  end if;
  insert into public.user_lifetime_source_position values(new.user_id,new.project_id,new.sequence,new.id,new.version) on conflict do nothing;
  return new;
end $$;
create trigger lifetime_source_position after insert or update of version,sequence on public.user_narrator_source
 for each row execute function public.record_lifetime_source_position();
revoke all on function public.record_lifetime_source_position() from public,anon,authenticated;
-- Constant-size mechanically maintained inventory proof. Historical rows are
-- deliberately not backfilled: an approved mapping must first reconcile them.
create table public.user_lifetime_source_inventory (
 user_id uuid not null, project_id text not null, record_count bigint not null check(record_count>=0),
 max_sequence bigint not null check(max_sequence>=0), primary key(user_id,project_id),
 foreign key(user_id,project_id) references public.user_memoir_project on delete cascade
);
alter table public.user_lifetime_source_inventory enable row level security;
revoke all on public.user_lifetime_source_inventory from public,anon,authenticated;
create function public.track_lifetime_source_inventory() returns trigger
language plpgsql security definer set search_path='' as $$
begin
 if tg_op='INSERT' then
   insert into public.user_lifetime_source_inventory values(new.user_id,new.project_id,1,new.sequence)
   on conflict(user_id,project_id) do update set record_count=public.user_lifetime_source_inventory.record_count+1,
     max_sequence=greatest(public.user_lifetime_source_inventory.max_sequence,excluded.max_sequence);
 else
   update public.user_lifetime_source_inventory set record_count=record_count-1,
     max_sequence=case when max_sequence=old.sequence then coalesce((select max(sequence) from public.user_lifetime_source_position
       where user_id=old.user_id and project_id=old.project_id),0) else max_sequence end
     where user_id=old.user_id and project_id=old.project_id;
 end if;
 return coalesce(new,old);
end $$;
create trigger lifetime_source_inventory after insert or delete on public.user_lifetime_source_position
 for each row execute function public.track_lifetime_source_inventory();
revoke all on function public.track_lifetime_source_inventory() from public,anon,authenticated;

create table public.user_lifetime_source_cursor (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  conversation_id uuid not null,
  policy_epoch bigint not null,
  high_water bigint not null,
  last_sequence bigint not null,
  last_offset integer not null,
  query text not null default '',
  expires_at timestamptz not null default clock_timestamp()+interval '1 day',
  constraint lifetime_cursor_scope unique(user_id,conversation_id,policy_epoch,high_water,last_sequence,last_offset,query),
  foreign key(user_id,conversation_id) references public.user_lifetime_conversation(user_id,conversation_id) on delete cascade
);
alter table public.user_lifetime_source_cursor enable row level security;
revoke all on public.user_lifetime_source_cursor from public,anon,authenticated;

create function public.read_lifetime_source_page(p_conversation_id uuid,p_policy_epoch bigint,
  p_cursor uuid default null,p_limit integer default 32,p_query text default '')
returns jsonb language plpgsql security definer set search_path=public,auth as $$
declare owner uuid:=auth.uid(); project text; epoch bigint; high_water bigint; last_sequence bigint:=0;
  last_offset integer:=-1; cursor_row public.user_lifetime_source_cursor%rowtype;
  records jsonb; has_more boolean; next_cursor uuid; last_row jsonb;
begin
  if owner is null then raise exception 'authenticated owner required'; end if;
  if p_limit is null or p_limit not between 1 and 32 or p_query is null or length(p_query)>128 then raise exception 'invalid page bounds'; end if;
  select project_id into project from public.user_lifetime_conversation where user_id=owner and conversation_id=p_conversation_id;
  if not found then raise exception 'conversation unavailable'; end if;
  select policy_epoch,source_sequence into epoch,high_water from public.user_memoir_project
    where user_id=owner and project_id=project for share;
  if epoch is distinct from p_policy_epoch then raise exception 'stale source policy' using errcode='40001'; end if;
  if high_water>0 and not exists(select 1 from public.user_lifetime_source_inventory where user_id=owner and project_id=project
    and record_count=high_water and max_sequence=high_water) then
    raise exception 'LIFETIME_INVENTORY_REQUIRED: historical source positions are incomplete' using errcode='40001';
  end if;
  if p_cursor is not null then
    select * into cursor_row from public.user_lifetime_source_cursor where id=p_cursor
      and user_id=owner and conversation_id=p_conversation_id and policy_epoch=epoch
      and query=p_query and expires_at>clock_timestamp();
    if not found then raise exception 'invalid or stale source cursor'; end if;
    high_water:=cursor_row.high_water;last_sequence:=cursor_row.last_sequence;last_offset:=cursor_row.last_offset;
  end if;
  select coalesce(jsonb_agg(r.data order by r.sequence,r.chunk_start),'[]') into records from (
    select s.sequence,chunk_start,jsonb_build_object('source_id',s.id,'version',s.version,'sequence',s.sequence,
      'char_start',chunk_start,'char_end',case when s.status='active' then least(chunk_start+2048,length(s.text)) else 0 end,
      'text',case when s.status='active' then substring(s.text from chunk_start+1 for 2048) else null end,
      'kind',s.kind,'language',s.language,'status',s.status) as data
    from (select pos.user_id,pos.project_id,pos.sequence,pos.source_id as id,pos.version,src.kind,src.language,
        case when src.id is null then 'withdrawn' when src.version<>pos.version then 'superseded' else src.status end as status,
        case when src.version=pos.version and src.status='active' then src.text else null end as text
      from public.user_lifetime_source_position pos left join public.user_narrator_source src
        on src.user_id=pos.user_id and src.project_id=pos.project_id and src.id=pos.source_id) s
    cross join lateral generate_series(case when p_query<>'' then greatest(position(lower(p_query) in lower(s.text))-257,0) else 0 end,
      case when p_query<>'' then greatest(position(lower(p_query) in lower(s.text))-257,0)
        when s.status='active' then greatest(length(s.text)-1,0) else 0 end,2048) chunk_start
    where s.user_id=owner and s.project_id=project and s.sequence<=high_water
      and (s.sequence>last_sequence or (s.sequence=last_sequence and chunk_start>last_offset))
      and (p_query='' or (s.status='active' and position(lower(p_query) in lower(s.text))>0))
    order by s.sequence,chunk_start limit p_limit+1) r;
  has_more:=jsonb_array_length(records)>p_limit;
  if has_more then
    records:=records-p_limit;last_row:=records->-1;
    insert into public.user_lifetime_source_cursor(user_id,conversation_id,policy_epoch,high_water,last_sequence,last_offset,query)
      values(owner,p_conversation_id,epoch,high_water,(last_row->>'sequence')::bigint,(last_row->>'char_start')::integer,p_query)
      on conflict on constraint lifetime_cursor_scope
      do update set expires_at=greatest(public.user_lifetime_source_cursor.expires_at,excluded.expires_at)
      returning id into next_cursor;
  end if;
  return jsonb_build_object('schema_version',1,'owner_id',owner,'conversation_id',p_conversation_id,
    'policy_epoch',epoch,'source_revision',high_water,'records',records,'complete',not has_more,'next_cursor',next_cursor);
end $$;
revoke all on function public.read_lifetime_source_page(uuid,bigint,uuid,integer,text) from public,anon;
grant execute on function public.read_lifetime_source_page(uuid,bigint,uuid,integer,text) to authenticated;
commit;
