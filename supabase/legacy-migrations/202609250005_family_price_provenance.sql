begin;

-- Keep the server-side entitlement tied to the configured Stripe price when
-- the Family feature is enabled. Existing rows remain readable and require
-- the normal plan fallback until they are reconciled or repurchased.
alter table public.story_entitlements
  add column if not exists stripe_price_id text;

commit;
