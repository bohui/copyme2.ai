-- Crash-resumable coverage of every canonical position and source chunk.
-- Raw coverage is not semantic inference or an assertion that every claim is true.
begin;
create table public.user_lifetime_compaction (
  id uuid primary key default gen_random_uuid(), user_id uuid not null, conversation_id uuid not null,
  fence jsonb not null, predecessor_id uuid, starting_after bigint not null, through_sequence bigint not null,
  last_sequence bigint not null, last_offset integer not null default -1, revision bigint not null default 0,
  item_count bigint not null default 0, digest text not null default '', complete boolean not null default false,
  pinned jsonb not null,
  foreign key(user_id,conversation_id) references public.user_lifetime_conversation(user_id,conversation_id) on delete cascade
);
create table public.user_lifetime_covered_evidence (
  maintenance_id uuid not null references public.user_lifetime_compaction(id) on delete cascade,
  sequence bigint not null, source_id uuid not null, version bigint not null,
  char_start integer not null, char_end integer not null,
  status text not null check(status in ('active','withdrawn','superseded')),
  content_sha256 text, kind text not null default 'covered_evidence' check(kind='covered_evidence'),
  primary key(maintenance_id,sequence,char_start)
);
alter table public.user_lifetime_compaction enable row level security;
alter table public.user_lifetime_covered_evidence enable row level security;
revoke all on public.user_lifetime_compaction,public.user_lifetime_covered_evidence from public,anon,authenticated;
alter table public.user_lifetime_checkpoint add column coverage_proof_id uuid;

create function public.begin_lifetime_compaction(p_fence jsonb,p_through_sequence bigint) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare owner uuid:=auth.uid(); conversation uuid:=(p_fence->'identity'->>'conversation_id')::uuid;
  project text; predecessor uuid; start_sequence bigint:=0; saved public.user_lifetime_compaction%rowtype;
begin
  select project_id,checkpoint_id into project,predecessor from public.user_lifetime_conversation where user_id=owner and conversation_id=conversation;
  if not found then raise exception 'conversation unavailable'; end if;
  perform 1 from public.user_memoir_project where user_id=owner and project_id=project for update;
  perform public.lock_lifetime_publication(p_fence);
  select checkpoint_id into predecessor from public.user_lifetime_conversation where user_id=owner and conversation_id=conversation;
  if predecessor is not null then select coverage_end into start_sequence from public.user_lifetime_checkpoint where id=predecessor and published; end if;
  start_sequence:=coalesce(start_sequence,0);
  if p_through_sequence is null or p_through_sequence<=start_sequence or p_through_sequence>(p_fence->>'source_revision')::bigint then raise exception 'invalid maintenance interval'; end if;
  if (select count(*) from public.user_lifetime_source_position where user_id=owner and project_id=project
      and sequence>start_sequence and sequence<=p_through_sequence)<>p_through_sequence-start_sequence then
    raise exception 'historical position inventory is incomplete; explicit mapping inventory required';
  end if;
  -- One existing matching session is sufficient after an uncertain response.
  select * into saved from public.user_lifetime_compaction where user_id=owner and conversation_id=conversation
    and fence-'lease_token'=p_fence-'lease_token' and pinned=public.read_lifetime_pinned(conversation) and predecessor_id is not distinct from predecessor and starting_after=start_sequence and through_sequence=p_through_sequence
    order by id limit 1;
  if not found then
    insert into public.user_lifetime_compaction(user_id,conversation_id,fence,predecessor_id,starting_after,through_sequence,last_sequence,pinned)
      values(owner,conversation,p_fence,predecessor,start_sequence,p_through_sequence,start_sequence,public.read_lifetime_pinned(conversation)) returning * into saved;
  end if;
  if saved.fence is distinct from p_fence then
    update public.user_lifetime_compaction set fence=p_fence where id=saved.id returning * into saved;
  end if;
  return to_jsonb(saved)-'user_id'-'pinned';
end $$;

create function public.step_lifetime_compaction(p_id uuid,p_fence jsonb,p_expected_revision bigint) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare owner uuid:=auth.uid(); saved public.user_lifetime_compaction%rowtype; project text; item record;
  processed integer:=0; fingerprint text; count_items bigint; chain text; last_seq bigint; last_start integer;
begin
  select * into saved from public.user_lifetime_compaction where id=p_id and user_id=owner;
  if not found then raise exception 'maintenance unavailable'; end if;
  select project_id into project from public.user_lifetime_conversation where user_id=owner and conversation_id=saved.conversation_id;
  perform 1 from public.user_memoir_project where user_id=owner and project_id=project for update;
  perform public.lock_lifetime_publication(p_fence);
  select * into saved from public.user_lifetime_compaction where id=p_id and user_id=owner for update;
  if saved.fence is distinct from p_fence or saved.revision is distinct from p_expected_revision
    or saved.pinned is distinct from public.read_lifetime_pinned(saved.conversation_id) then raise exception 'stale maintenance' using errcode='40001'; end if;
  if saved.complete then return to_jsonb(saved)-'user_id'-'pinned'; end if;
  chain:=saved.digest;count_items:=saved.item_count;last_seq:=saved.last_sequence;last_start:=saved.last_offset;
  for item in
    select pos.sequence,pos.source_id,pos.version,chunk_start,
      case when src.version=pos.version and src.status='active' then least(chunk_start+2000,length(src.text)) else 0 end as chunk_end,
      case when src.id is null then 'withdrawn' when src.version<>pos.version then 'superseded' else src.status end as status,
      case when src.version=pos.version and src.status='active' then substring(src.text from chunk_start+1 for 2000) else null end as content
    from public.user_lifetime_source_position pos left join public.user_narrator_source src
      on src.user_id=pos.user_id and src.project_id=pos.project_id and src.id=pos.source_id
    cross join lateral generate_series(0,case when src.version=pos.version and src.status='active' then greatest(length(src.text)-1,0) else 0 end,2000) chunk_start
    where pos.user_id=owner and pos.project_id=project and pos.sequence>saved.starting_after and pos.sequence<=saved.through_sequence
      and (pos.sequence>saved.last_sequence or (pos.sequence=saved.last_sequence and chunk_start>saved.last_offset))
    order by pos.sequence,chunk_start limit 32
  loop
    fingerprint:=case when item.content is not null then encode(sha256(convert_to(item.content,'UTF8')),'hex') else null end;
    insert into public.user_lifetime_covered_evidence(maintenance_id,sequence,source_id,version,char_start,char_end,status,content_sha256)
      values(p_id,item.sequence,item.source_id,item.version,item.chunk_start,item.chunk_end,item.status,fingerprint);
    chain:=encode(sha256(convert_to(chain||':'||item.sequence||':'||item.source_id||':'||item.version||':'||item.chunk_start||':'||item.chunk_end||':'||item.status||':'||coalesce(fingerprint,''),'UTF8')),'hex');
    processed:=processed+1;count_items:=count_items+1;last_seq:=item.sequence;last_start:=item.chunk_start;
  end loop;
  update public.user_lifetime_compaction set revision=revision+1,item_count=count_items,digest=chain,last_sequence=last_seq,last_offset=last_start,
    complete=processed<32 where id=p_id returning * into saved;
  return to_jsonb(saved)-'user_id'-'pinned';
end $$;

-- The previous function remains an internal validator only. No caller can
-- create a checkpoint that jumps over an unfinished interval.
alter function public.create_lifetime_checkpoint(jsonb,bigint,text,text,jsonb) rename to create_lifetime_checkpoint_before_proof;
revoke all on function public.create_lifetime_checkpoint_before_proof(jsonb,bigint,text,text,jsonb) from public,anon,authenticated;
create function public.create_lifetime_checkpoint(p_fence jsonb,p_coverage_end bigint,p_model text,p_prompt_version text,
  p_evidence jsonb default '[]',p_coverage_proof uuid default null) returns uuid
language plpgsql security definer set search_path=public,auth as $$
declare proof public.user_lifetime_compaction%rowtype; project text; head uuid; candidate uuid;
begin
  select * into proof from public.user_lifetime_compaction where id=p_coverage_proof and user_id=auth.uid();
  if not found then raise exception 'complete coverage proof required'; end if;
  select project_id into project from public.user_lifetime_conversation where user_id=auth.uid() and conversation_id=proof.conversation_id;
  perform 1 from public.user_memoir_project where user_id=auth.uid() and project_id=project for update;
  perform public.lock_lifetime_publication(p_fence);
  select checkpoint_id into head from public.user_lifetime_conversation where user_id=auth.uid() and conversation_id=proof.conversation_id;
  if not proof.complete or proof.fence is distinct from p_fence or proof.through_sequence is distinct from p_coverage_end
    or proof.predecessor_id is distinct from head or proof.pinned is distinct from public.read_lifetime_pinned(proof.conversation_id)
    or proof.item_count<>(select count(*) from public.user_lifetime_covered_evidence where maintenance_id=proof.id) then
    raise exception 'incomplete or stale coverage proof' using errcode='40001'; end if;
  candidate:=public.create_lifetime_checkpoint_before_proof(p_fence,p_coverage_end,p_model,p_prompt_version,p_evidence);
  update public.user_lifetime_checkpoint set coverage_proof_id=proof.id where id=candidate;
  return candidate;
end $$;

create function public.purge_lifetime_compaction() returns trigger
language plpgsql security definer set search_path='' as $$
begin
  if old.policy_epoch is distinct from new.policy_epoch then
    delete from public.user_lifetime_compaction c using public.user_lifetime_conversation l
      where c.user_id=l.user_id and c.conversation_id=l.conversation_id and l.user_id=new.user_id and l.project_id=new.project_id;
  end if;
  return new;
end $$;
create trigger lifetime_compaction_invalidation after update of policy_epoch on public.user_memoir_project
 for each row execute function public.purge_lifetime_compaction();
revoke all on function public.purge_lifetime_compaction(),public.begin_lifetime_compaction(jsonb,bigint),
 public.step_lifetime_compaction(uuid,jsonb,bigint),public.create_lifetime_checkpoint(jsonb,bigint,text,text,jsonb,uuid) from public,anon;
grant execute on function public.begin_lifetime_compaction(jsonb,bigint),public.step_lifetime_compaction(uuid,jsonb,bigint),
 public.create_lifetime_checkpoint(jsonb,bigint,text,text,jsonb,uuid) to authenticated;
commit;
