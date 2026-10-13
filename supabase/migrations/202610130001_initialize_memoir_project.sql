-- Initialize anonymous and legacy project ownership before phase controls load.
begin;
create or replace function public.ensure_user_memoir_project(p_project_id text) returns void
language plpgsql security definer set search_path='' as $$
begin
 if auth.uid() is null then
   raise exception 'authenticated user required' using errcode='42501';
 end if;
 if p_project_id is null or p_project_id !~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$' then
   raise exception 'invalid project' using errcode='22023';
 end if;
 if not public.lock_lifetime_legacy_worker_admission() then
   raise exception 'canonical conversation required' using errcode='42501';
 end if;
 insert into public.user_memoir_project(user_id,project_id)
   values(auth.uid(),p_project_id) on conflict do nothing;
end $$;
revoke all on function public.ensure_user_memoir_project(text) from public,anon;
grant execute on function public.ensure_user_memoir_project(text) to authenticated;
commit;
