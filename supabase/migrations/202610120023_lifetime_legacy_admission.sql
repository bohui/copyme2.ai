-- Canonical adoption is monotonic across API/worker version and flag changes.
begin;
create function public.lock_lifetime_legacy_worker_admission() returns boolean
language plpgsql security definer set search_path='' as $$
begin
 if auth.uid() is null then raise exception 'authenticated owner required' using errcode='42501';end if;
 perform 1 from auth.users where id=auth.uid() for share;
 if not found then raise exception 'authenticated owner required' using errcode='42501';end if;
 return not exists(select 1 from public.user_lifetime_conversation where user_id=auth.uid() and product='memoir');
end $$;
revoke all on function public.lock_lifetime_legacy_worker_admission() from public,anon;
grant execute on function public.lock_lifetime_legacy_worker_admission() to authenticated;

alter function public.commit_user_agent_turn(uuid,text,text,text[],bigint,text,uuid,boolean,text)
 rename to commit_user_agent_turn_before_lifetime_adoption;
revoke all on function public.commit_user_agent_turn_before_lifetime_adoption(uuid,text,text,text[],bigint,text,uuid,boolean,text)
 from public,anon,authenticated;
create function public.commit_user_agent_turn(
 p_lease_token uuid,p_thread_id text,p_content text,p_source_paths text[] default '{}',
 p_source_sequence bigint default null,p_project_id text default null,p_client_turn_id uuid default null,
 p_user_response boolean default true,p_life_stage text default 'unplaced') returns jsonb
language plpgsql security definer set search_path='' as $$
begin
 if not public.lock_lifetime_legacy_worker_admission() then
   raise exception 'governed atomic commit required for canonical conversation' using errcode='40001';
 end if;
 return public.commit_user_agent_turn_before_lifetime_adoption(p_lease_token,p_thread_id,p_content,p_source_paths,
   p_source_sequence,p_project_id,p_client_turn_id,p_user_response,p_life_stage);
end $$;
revoke all on function public.commit_user_agent_turn(uuid,text,text,text[],bigint,text,uuid,boolean,text) from public,anon;
grant execute on function public.commit_user_agent_turn(uuid,text,text,text[],bigint,text,uuid,boolean,text) to authenticated;
commit;
