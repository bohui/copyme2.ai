-- Count complete Unicode exchanges independently of database LC_CTYPE.
-- No historical data rewrite or changed ownership/deduplication semantics.
create or replace function public.record_private_draft_change() returns trigger
language plpgsql security definer set search_path='' as $$
declare m public.user_memory%rowtype; next_round bigint; inserted integer;
begin
  if TG_OP='DELETE' then m:=old; else m:=new; end if;
  if m.kind <> 'agent' or m.project_id is null then return null; end if;
  if TG_OP='INSERT' or (TG_OP='UPDATE' and old.project_id is null) then
    -- A durable assistant-only greeting or incomplete exchange is not a round.
    if m.content !~ '^Storyteller: ' or
       pg_catalog.strpos(m.content,E'\nMemory Spark: ')=0 or
       pg_catalog.btrim(pg_catalog.regexp_replace(pg_catalog.split_part(m.content,E'\nMemory Spark: ',1),'^Storyteller: ',''))='' or
       pg_catalog.btrim(pg_catalog.split_part(m.content,E'\nMemory Spark: ',2))='' then return null; end if;
    perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(m.user_id::text||':'||m.project_id,0));
    select coalesce(max(ordinal),0)+1 into next_round from public.user_completed_round
      where user_id=m.user_id and project_id=m.project_id;
    insert into public.user_completed_round(user_id,project_id,memory_id,turn_id,ordinal)
      values(m.user_id,m.project_id,m.id,coalesce(m.client_turn_id,m.id),next_round)
      on conflict do nothing;
    get diagnostics inserted=ROW_COUNT;
    if inserted=0 then return null; end if;
    insert into public.user_private_draft_outbox(user_id,project_id,memory_id,change_kind)
      values(m.user_id,m.project_id,m.id,'round');
  elsif TG_OP='DELETE' then
    insert into public.user_private_draft_outbox(user_id,project_id,memory_id,change_kind)
      values(m.user_id,m.project_id,m.id,'delete');
  elsif old.content is distinct from new.content or old.life_stage is distinct from new.life_stage or
        old.project_id is distinct from new.project_id then
    insert into public.user_private_draft_outbox(user_id,project_id,memory_id,change_kind)
      values(m.user_id,m.project_id,m.id,case when old.content is distinct from new.content then 'edit' else 'assignment' end);
  end if;
  return null;
end $$;
