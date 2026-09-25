begin;

-- Payment state is server-controlled. Storytellers can read their own
-- entitlement, but cannot insert or update it through the browser token.
create table if not exists public.story_entitlements (
  user_id uuid primary key references auth.users(id) on delete cascade,
  status text not null check (status in ('paid', 'revoked')),
  plan_key text not null,
  book_count integer not null check (book_count >= 0),
  amount_minor integer not null check (amount_minor >= 0),
  currency text not null,
  electronic_only boolean not null default false,
  family_tree boolean not null default false,
  timeline boolean not null default false,
  expanded_details boolean not null default false,
  stripe_session_id text not null unique,
  stripe_payment_intent_id text,
  paid_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.story_entitlements enable row level security;

drop policy if exists story_entitlement_owner_select on public.story_entitlements;
create policy story_entitlement_owner_select on public.story_entitlements
  for select to authenticated
  using (user_id = (select auth.uid()));

revoke all on public.story_entitlements from anon;
grant select on public.story_entitlements to authenticated;
grant all on public.story_entitlements to service_role;

commit;
