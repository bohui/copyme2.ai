-- The stage attribution upgrade replaces a function after the earlier
-- nonretryable-conflict conversion. Preserve its complete body, guards and
-- grants; only restore application revision conflicts to HTTP 409.
begin;
do $$
declare definition text; restored text;
begin
  definition := pg_catalog.pg_get_functiondef(
    'public.apply_user_memory_events_before_photos(text,jsonb,jsonb)'::regprocedure);
  restored := pg_catalog.regexp_replace(definition,
    '(errcode\s*=\s*)''40001''', '\1''PT409''', 'gi');
  if restored is distinct from definition then
    execute restored;
  end if;
end $$;
notify pgrst, 'reload schema';
commit;
