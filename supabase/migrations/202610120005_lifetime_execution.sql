-- Issue 60 W2: epochs and transactional publication gates, initially inactive.
begin;
alter table public.user_lifetime_conversation add column thread_id text;
alter table public.user_lifetime_conversation add column thread_policy_epoch bigint;
alter table public.user_lifetime_conversation add column thread_schema_version integer;
alter table public.user_lifetime_conversation add column thread_prompt_version text;
alter table public.user_lifetime_conversation add column thread_model text;

create function public.invalidate_lifetime_projections() returns trigger
language plpgsql security definer set search_path='' as $$
begin
  if old.policy_epoch is distinct from new.policy_epoch then
    update public.user_lifetime_conversation set execution_generation=execution_generation+1,
      thread_id=null,thread_policy_epoch=null,thread_schema_version=null,thread_prompt_version=null,thread_model=null
      where user_id=new.user_id and project_id=new.project_id;
    -- Preserve independently supported typed state; erase invalid dependencies.
    delete from public.user_lifetime_continuity c using public.user_lifetime_conversation l
      where c.user_id=l.user_id and c.conversation_id=l.conversation_id
        and l.user_id=new.user_id and l.project_id=new.project_id and exists(
          select 1 from jsonb_array_elements(c.data->'source_refs') ref where not exists(
            select 1 from public.user_narrator_source s where s.user_id=new.user_id and s.project_id=new.project_id
              and s.id=(ref->>'source_id')::uuid and s.version=(ref->>'version')::bigint and s.status='active'));
    update public.user_lifetime_continuity c set policy_epoch=new.policy_epoch from public.user_lifetime_conversation l
      where c.user_id=l.user_id and c.conversation_id=l.conversation_id and l.user_id=new.user_id and l.project_id=new.project_id;
  end if;
  return new;
end $$;
create trigger lifetime_policy_invalidation after update of policy_epoch on public.user_memoir_project
  for each row execute function public.invalidate_lifetime_projections();
revoke all on function public.invalidate_lifetime_projections() from public,anon,authenticated;

create function public.advance_lifetime_preferences() returns trigger
language plpgsql security definer set search_path='' as $$
begin
  if tg_op='INSERT' or old.profile is distinct from new.profile then
    -- The UPDATE already owns the profile row; never acquire project here.
    -- Publication takes project -> profile -> lease and then reads this revision.
    update public.user_lifetime_conversation set preference_revision=preference_revision+1 where user_id=new.user_id;
  end if;
  return new;
end $$;
create trigger lifetime_preference_revision after insert or update of profile on public.user_profile
 for each row execute function public.advance_lifetime_preferences();
revoke all on function public.advance_lifetime_preferences() from public,anon,authenticated;

create function public.capture_lifetime_fence(p_conversation_id uuid,p_lease_token uuid)
returns jsonb language plpgsql security definer set search_path=public,auth as $$
declare owner uuid:=auth.uid(); identity public.user_lifetime_conversation%rowtype;
  project public.user_memoir_project%rowtype; phase_revision bigint:=0;
begin
  select * into identity from public.user_lifetime_conversation where user_id=owner and conversation_id=p_conversation_id;
  if not found then raise exception 'conversation unavailable'; end if;
  -- Shared project lock conflicts with every correction/phase/preference writer.
  select * into project from public.user_memoir_project where user_id=owner and project_id=identity.project_id for share;
  -- Ensure there is a lockable preference authority even for a new account.
  insert into public.user_profile(user_id,profile) values(owner,'{}') on conflict do nothing;
  perform 1 from public.user_profile where user_id=owner for share;
  -- Refresh after obtaining ordering locks; the first identity read is not a fence.
  select * into identity from public.user_lifetime_conversation where user_id=owner and conversation_id=p_conversation_id;
  perform 1 from public.user_agent_turn_lease where user_id=owner and lease_token=p_lease_token
    and expires_at>clock_timestamp() for share;
  if not found then raise exception 'valid turn lease required' using errcode='40001'; end if;
  if to_regclass('public.user_conversation_phase') is not null then
    execute 'select coalesce((select revision from public.user_conversation_phase where user_id=$1 and project_id=$2),0)'
      into phase_revision using owner,identity.project_id;
  end if;
  return jsonb_build_object('schema_version',1,'identity',jsonb_build_object('schema_version',1,
    'owner_id',owner,'conversation_id',identity.conversation_id,'product','memoir','project_id',identity.project_id),
    'policy_epoch',project.policy_epoch,'source_revision',project.source_sequence,
    'execution_generation',identity.execution_generation,'phase_revision',phase_revision,
    'preference_revision',identity.preference_revision,'lease_token',p_lease_token);
end $$;

create function public.lock_lifetime_publication(p_fence jsonb)
returns double precision language plpgsql security definer set search_path=public,auth as $$
declare current_fence jsonb; remaining double precision;
begin
  if (p_fence->'identity'->>'owner_id')::uuid is distinct from auth.uid() then raise exception 'owner mismatch'; end if;
  current_fence:=public.capture_lifetime_fence((p_fence->'identity'->>'conversation_id')::uuid,(p_fence->>'lease_token')::uuid);
  if current_fence is distinct from p_fence then raise exception 'stale lifetime fence' using errcode='40001'; end if;
  select extract(epoch from expires_at-clock_timestamp()) into remaining from public.user_agent_turn_lease
    where user_id=auth.uid() and lease_token=(p_fence->>'lease_token')::uuid;
  if remaining is null or remaining<=0 then raise exception 'expired publication lease' using errcode='40001'; end if;
  -- Caller must keep this transaction open through actual ASGI send, with a
  -- timeout shorter than remaining. An RPC call by itself is NOT a send fence.
  return remaining;
end $$;
revoke all on function public.capture_lifetime_fence(uuid,uuid),public.lock_lifetime_publication(jsonb) from public,anon;
grant execute on function public.capture_lifetime_fence(uuid,uuid),public.lock_lifetime_publication(jsonb) to authenticated;
-- Source edits advance the project epoch before updating the source row.
-- Reconcile again in the same transaction, after its new version is visible.
create function public.reconcile_lifetime_source_continuity() returns trigger
language plpgsql security definer set search_path='' as $$
begin
  if old.version is distinct from new.version or old.status is distinct from new.status then
    delete from public.user_lifetime_continuity c using public.user_lifetime_conversation l
      where c.user_id=l.user_id and c.conversation_id=l.conversation_id and l.user_id=new.user_id and l.project_id=new.project_id
        and exists(select 1 from jsonb_array_elements(c.data->'source_refs') ref where ref->>'source_id'=new.id::text);
  end if;
  return new;
end $$;
create trigger lifetime_source_continuity after update of version,status on public.user_narrator_source
 for each row execute function public.reconcile_lifetime_source_continuity();
revoke all on function public.reconcile_lifetime_source_continuity() from public,anon,authenticated;
commit;
