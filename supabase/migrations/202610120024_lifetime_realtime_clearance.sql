-- Source-only interlock. Installing this migration does NOT clear old calls or
-- activate canonical generation. The migration default is deliberately closed.
begin;
create table public.lifetime_realtime_clearance (
 singleton boolean primary key default true check(singleton),
 stage text not null default 'legacy_only' check(stage in ('legacy_only','draining','canonical_ready')),
 revision bigint not null default 0 check(revision>=0),
 termination_attestation_reference text,
 changed_at timestamptz not null default clock_timestamp(),
 check(termination_attestation_reference is null or termination_attestation_reference ~ '^[A-Za-z0-9][A-Za-z0-9:/._-]{0,255}$'),
 check((stage='canonical_ready')=(termination_attestation_reference is not null))
);
alter table public.lifetime_realtime_clearance enable row level security;
revoke all on public.lifetime_realtime_clearance from public,anon,authenticated,service_role;
insert into public.lifetime_realtime_clearance default values;

create function public.enforce_lifetime_realtime_clearance_transition() returns trigger
language plpgsql security definer set search_path='' as $$
begin
 if new.singleton<>old.singleton or new.revision<>old.revision+1
    or not ((old.stage='legacy_only' and new.stage='draining')
         or (old.stage='draining' and new.stage='canonical_ready')) then
   raise exception 'realtime clearance transitions are monotonic' using errcode='55000';
 end if;
 return new;
end $$;
create trigger lifetime_realtime_clearance_monotonic before update on public.lifetime_realtime_clearance
 for each row execute function public.enforce_lifetime_realtime_clearance_transition();

-- Database-owner-only CAS operations. These lock ONLY the rollout row.
-- Calling the second function is a human/operator attestation, never automatic
-- verification: all old connected calls AND admitted/in-flight call creations
-- must have reached a verified terminated state outside this database first.
create function public.begin_lifetime_realtime_drain(p_expected_revision bigint) returns bigint
language plpgsql security definer set search_path='' as $$
declare next_revision bigint;
begin
 update public.lifetime_realtime_clearance set stage='draining',revision=revision+1,changed_at=clock_timestamp()
 where singleton and stage='legacy_only' and revision=p_expected_revision returning revision into next_revision;
 if not found then raise exception 'realtime drain state changed' using errcode='40001';end if;
 return next_revision;
end $$;
create function public.attest_lifetime_realtime_clearance(p_expected_revision bigint,p_termination_attestation_reference text)
returns bigint language plpgsql security definer set search_path='' as $$
declare next_revision bigint;
begin
 if p_termination_attestation_reference is null or p_termination_attestation_reference !~ '^[A-Za-z0-9][A-Za-z0-9:/._-]{0,255}$' then
   raise exception 'bounded external termination attestation reference required' using errcode='22023';end if;
 update public.lifetime_realtime_clearance set stage='canonical_ready',revision=revision+1,
   termination_attestation_reference=p_termination_attestation_reference,changed_at=clock_timestamp()
 where singleton and stage='draining' and revision=p_expected_revision returning revision into next_revision;
 if not found then raise exception 'realtime clearance state changed' using errcode='40001';end if;
 return next_revision;
end $$;
revoke all on function public.enforce_lifetime_realtime_clearance_transition(),
 public.begin_lifetime_realtime_drain(bigint),public.attest_lifetime_realtime_clearance(bigint,text)
 from public,anon,authenticated,service_role;

create function public.require_lifetime_canonical_clearance() returns void
language plpgsql security definer set search_path='' as $$
declare current_stage text;
begin
 select stage into current_stage from public.lifetime_realtime_clearance where singleton for share;
 if not found or current_stage<>'canonical_ready' then
   raise exception 'LIFETIME_REALTIME_CLEARANCE_REQUIRED' using errcode='55000';end if;
end $$;
revoke all on function public.require_lifetime_canonical_clearance() from public,anon,authenticated,service_role;

create function public.lock_lifetime_provider_activation() returns void
language plpgsql security definer set search_path='' as $$
begin
 if auth.uid() is null or not exists(select 1 from auth.users where id=auth.uid()) then
   raise exception 'authenticated owner required' using errcode='42501';end if;
 perform public.require_lifetime_canonical_clearance();
end $$;
revoke all on function public.lock_lifetime_provider_activation() from public,anon,service_role;
grant execute on function public.lock_lifetime_provider_activation() to authenticated;

create function public.guard_lifetime_identity_adoption() returns trigger
language plpgsql security definer set search_path='' as $$
begin
 -- Covers the resolver and any present/future transfer or historical mapping
 -- insertion. Existing identity reads and safe replay do not invoke this gate.
 perform public.require_lifetime_canonical_clearance();return new;
end $$;
revoke all on function public.guard_lifetime_identity_adoption() from public,anon,authenticated,service_role;
create trigger lifetime_identity_requires_realtime_clearance before insert on public.user_lifetime_conversation
 for each row execute function public.guard_lifetime_identity_adoption();

create function public.lock_lifetime_realtime_admission() returns void
language plpgsql security definer set search_path='' as $$
declare current_stage text;
begin
 -- Existing authority rows precede the global rollout lock in every path.
 if not public.lock_lifetime_legacy_worker_admission() then
   raise exception 'governed realtime unavailable' using errcode='55000';end if;
 select stage into current_stage from public.lifetime_realtime_clearance where singleton for share;
 if not found or current_stage<>'legacy_only' then
   raise exception 'LIFETIME_REALTIME_CLEARANCE_REQUIRED' using errcode='55000';end if;
end $$;
revoke all on function public.lock_lifetime_realtime_admission() from public,anon,service_role;
grant execute on function public.lock_lifetime_realtime_admission() to authenticated;
commit;
