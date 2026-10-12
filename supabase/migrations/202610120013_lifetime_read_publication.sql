-- Issue 60: bounded read snapshots without an exclusive generation lease.
-- Additive functions and triggers only; no historical mapping, backfill or activation.
begin;
-- Initial profile insertion must serialize with a read of an absent profile.
-- BEFORE INSERT takes this owner-only advisory gate before inserting a tuple;
-- normal existing-profile reads retain their row lock and need no advisory lock.
create function public.lock_lifetime_profile_creation() returns trigger
language plpgsql security definer set search_path='' as $$
begin
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('memoir-profile:'||new.user_id::text,0));
  return new;
end $$;
create trigger lifetime_profile_creation before insert on public.user_profile
  for each row execute function public.lock_lifetime_profile_creation();
revoke all on function public.lock_lifetime_profile_creation() from public,anon,authenticated;

-- Deleting preferences is also a revision change. Invalidate before removal,
-- and let the deleting transaction commit both changes atomically.
create function public.advance_lifetime_deleted_preferences() returns trigger
language plpgsql security definer set search_path='' as $$
begin
  update public.user_lifetime_conversation set preference_revision=preference_revision+1
    where user_id=old.user_id;
  return old;
end $$;
create trigger lifetime_deleted_preferences before delete on public.user_profile
  for each row execute function public.advance_lifetime_deleted_preferences();
revoke all on function public.advance_lifetime_deleted_preferences() from public,anon,authenticated;

create function public.read_lifetime_project_identity(p_project_id text)
returns jsonb language plpgsql security definer set search_path='' as $$
begin
  if auth.uid() is null then raise exception 'authenticated owner required' using errcode='42501'; end if;
  return (select jsonb_build_object('schema_version',1,'owner_id',user_id,
    'conversation_id',conversation_id,'product',product,'project_id',project_id)
    from public.user_lifetime_conversation where user_id=auth.uid() and project_id=p_project_id and product='memoir');
end $$;
create function public.capture_lifetime_read_fence(p_project_id text)
returns jsonb language plpgsql security definer set search_path='' set lock_timeout='2s' as $$
declare owner uuid:=auth.uid(); identity public.user_lifetime_conversation%rowtype;
  project public.user_memoir_project%rowtype; phase_revision bigint:=0;
begin
  if owner is null then raise exception 'authenticated owner required' using errcode='42501'; end if;
  select * into identity from public.user_lifetime_conversation
    where user_id=owner and project_id=p_project_id and product='memoir';
  if not found then raise exception 'lifetime conversation unavailable' using errcode='42501'; end if;
  -- Same ordering as generation publication, but never lock or claim its lease.
  select * into project from public.user_memoir_project
    where user_id=owner and project_id=p_project_id for share;
  if not found then raise exception 'project unavailable' using errcode='42501'; end if;
  perform 1 from public.user_profile where user_id=owner for share;
  if not found then
    -- A missing row cannot be row-locked. Block only this owner's first INSERT
    -- without creating data from a GET or blocking other tenants' profile writes.
    perform pg_catalog.pg_advisory_xact_lock_shared(pg_catalog.hashtextextended('memoir-profile:'||owner::text,0));
    perform 1 from public.user_profile where user_id=owner for share;
  end if;
  select * into identity from public.user_lifetime_conversation
    where user_id=owner and project_id=p_project_id and product='memoir';
  if not found then raise exception 'lifetime conversation unavailable' using errcode='42501'; end if;
  select coalesce((select revision from public.user_conversation_phase
    where user_id=owner and project_id=p_project_id),0) into phase_revision;
  return jsonb_build_object('schema_version',1,'identity',jsonb_build_object('schema_version',1,
    'owner_id',owner,'conversation_id',identity.conversation_id,'product','memoir','project_id',p_project_id),
    'policy_epoch',project.policy_epoch,'source_revision',project.source_sequence,
    'execution_generation',identity.execution_generation,'phase_revision',phase_revision,
    'preference_revision',identity.preference_revision,
    'captured_at_ms',floor(extract(epoch from clock_timestamp())*1000)::bigint);
end $$;

create function public.lock_lifetime_read_publication(p_fence jsonb)
returns double precision language plpgsql security definer set search_path='' as $$
declare current_fence jsonb; captured bigint; remaining double precision;
begin
  if jsonb_typeof(p_fence) is distinct from 'object' or
    jsonb_typeof(p_fence->'identity') is distinct from 'object' or
    jsonb_typeof(p_fence->'captured_at_ms') is distinct from 'number' or
    p_fence->>'captured_at_ms' !~ '^[1-9][0-9]{0,18}$' then
    raise exception 'invalid read fence' using errcode='22023'; end if;
  if (p_fence->'identity'->>'owner_id')::uuid is distinct from auth.uid() then
    raise exception 'owner mismatch' using errcode='42501'; end if;
  captured:=(p_fence->>'captured_at_ms')::bigint;
  current_fence:=public.capture_lifetime_read_fence(p_fence->'identity'->>'project_id');
  -- Whole-object equality rejects missing fields, wrong identity, types, writer
  -- lease tokens and extra keys. Only the original capture time is retained.
  if current_fence-'captured_at_ms' is distinct from p_fence-'captured_at_ms' then
    raise exception 'stale lifetime read fence' using errcode='40001'; end if;
  remaining:=30.0-(extract(epoch from clock_timestamp())-captured/1000.0);
  if remaining<=0 or remaining>30 then
    raise exception 'expired or future read fence' using errcode='40001'; end if;
  -- This transaction MUST remain open through the actual bounded ASGI send.
  -- A completed PostgREST RPC alone is not a publication guard.
  return remaining;
end $$;
revoke all on function public.read_lifetime_project_identity(text),public.capture_lifetime_read_fence(text),public.lock_lifetime_read_publication(jsonb) from public,anon;
grant execute on function public.read_lifetime_project_identity(text),public.capture_lifetime_read_fence(text),public.lock_lifetime_read_publication(jsonb) to authenticated;
commit;
