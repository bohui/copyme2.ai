-- Application version/lease conflicts must terminate the HTTP request. On
-- PostgREST 14, deliberately raising 40001 retries a stale request forever.
-- Retain every predicate, exception message, function setting and grant.
begin;
do $$
declare application_function record;
begin
  for application_function in
    select p.oid from pg_proc p join pg_namespace n on n.oid=p.pronamespace
    where n.nspname='public' and p.prokind='f'
      and p.prosrc like '%40001%'
  loop
    execute replace(regexp_replace(pg_get_functiondef(application_function.oid),
      '(errcode\s*=\s*)''40001''', '\1''PT409''', 'gi'),
      'exception when sqlstate ''40001'' or sqlstate ''55000'' then',
      'exception when sqlstate ''40001'' or sqlstate ''PT409'' or sqlstate ''55000'' then');
  end loop;
end $$;
notify pgrst, 'reload schema';
commit;
