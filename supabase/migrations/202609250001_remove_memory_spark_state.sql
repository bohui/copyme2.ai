begin;

-- These tables belonged to the retired singleton JSONB store and its durable
-- outbox. They are intentionally not replaced: user-owned story data lives in
-- user_profile/user_memory and Codex artifacts live in Storage.
drop table if exists public.memory_spark_outbox;
drop table if exists public.memory_spark_state;

commit;
