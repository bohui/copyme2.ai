begin;

-- Usage survives refreshes, new projects, and deletion of conversation records.
-- Clients can read their usage but cannot reset or grant it through a profile.
create table public.user_recall_usage (
  user_id uuid primary key references auth.users(id) on delete cascade,
  rounds_completed bigint not null default 0 check (rounds_completed >= 0)
);
alter table public.user_recall_usage enable row level security;
revoke all on public.user_recall_usage from public, anon, authenticated;
grant select on public.user_recall_usage to authenticated;
create policy recall_usage_owner on public.user_recall_usage for select to authenticated
  using (user_id = (select auth.uid()));

insert into public.user_recall_usage(user_id, rounds_completed)
  select user_id, count(*) from public.user_memory where kind = 'agent' group by user_id;

-- The conversation commit and charge share one transaction. Failed replies
-- consume nothing; a crash after saving cannot lose the charge.
create function public.count_recall_reply() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  if new.kind = 'agent' then
    insert into public.user_recall_usage(user_id, rounds_completed) values(new.user_id, 1)
      on conflict(user_id) do update set rounds_completed = public.user_recall_usage.rounds_completed + 1;
  end if;
  return new;
end;
$$;
revoke all on function public.count_recall_reply() from public, anon, authenticated;
create trigger count_recall_reply after insert on public.user_memory
  for each row execute function public.count_recall_reply();

-- Imported replies are counted above. Preserve any additional consumed guest
-- rounds whose records were deleted, exactly once on redemption of a transfer.
create function public.transfer_recall_usage() returns trigger
language plpgsql security definer set search_path = '' as $$
declare guest_usage bigint; imported bigint;
begin
  if old.target_user_id is null and new.target_user_id is not null then
    select rounds_completed into guest_usage from public.user_recall_usage where user_id = old.guest_user_id;
    select count(*) into imported from jsonb_array_elements(old.memories) m where m->>'kind' = 'agent';
    insert into public.user_recall_usage(user_id, rounds_completed)
      values(new.target_user_id, greatest(0, coalesce(guest_usage, 0) - imported))
      on conflict(user_id) do update set rounds_completed = public.user_recall_usage.rounds_completed + excluded.rounds_completed;
  end if;
  return new;
end;
$$;
revoke all on function public.transfer_recall_usage() from public, anon, authenticated;
create trigger transfer_recall_usage after update of target_user_id on public.guest_conversation_transfer
  for each row execute function public.transfer_recall_usage();

commit;
