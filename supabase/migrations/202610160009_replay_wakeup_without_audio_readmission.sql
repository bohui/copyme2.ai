-- Wake replayed memory work directly; avoid re-entering recording admission with an empty recording list.
begin;
create or replace function public.accept_recorded_interview_turn(p_two_lane boolean,p_project_id text,p_client_turn_id uuid,p_text text,
 p_kind text,p_language text,p_uploaded_photo_ids jsonb,p_photo_selection jsonb,p_recording_ids jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare result jsonb; r public.user_original_recording%rowtype; identifier text; index integer:=0; saved jsonb; prior public.user_interview_turn%rowtype;
begin
 if jsonb_typeof(p_recording_ids) is distinct from 'array' or jsonb_array_length(p_recording_ids)>20 then raise exception 'invalid recording list';end if;
 if (select count(*)<>count(distinct value) from jsonb_array_elements_text(p_recording_ids)) then raise exception 'duplicate recording reference';end if;
 perform 1 from public.user_memoir_project where user_id=auth.uid() and project_id=p_project_id for update;
 select * into prior from public.user_interview_turn where user_id=auth.uid() and project_id=p_project_id and client_turn_id=p_client_turn_id;
 if found then
   select coalesce(jsonb_agg(recording_id::text order by position),'[]') into saved from public.user_source_recording
     where user_id=auth.uid() and project_id=p_project_id and client_turn_id=p_client_turn_id;
   if saved is distinct from p_recording_ids or prior.input_hash is distinct from md5(p_text) or prior.kind is distinct from p_kind then
     raise exception 'input revision conflict' using errcode='40001';end if;
   -- Replaying the same accepted input still wakes B at the latest project
   -- frontier. Do not attach/revalidate deleted audio or allocate a source.
   if p_two_lane and exists(select 1 from public.lifetime_two_lane_rollout where singleton and enabled) then
     insert into public.user_memoir_lane(user_id,project_id,skill,pending,target_source,target_event)
     select auth.uid(),p_project_id,'timeline',true,source_sequence,event_sequence from public.user_memoir_project
       where user_id=auth.uid() and project_id=p_project_id
     on conflict(user_id,project_id,skill) do update set pending=true,
       target_source=greatest(user_memoir_lane.target_source,excluded.target_source),
       target_event=greatest(user_memoir_lane.target_event,excluded.target_event),
       attempts=case when excluded.target_source>user_memoir_lane.target_source then 0 else user_memoir_lane.attempts end;
   end if;
   return public.read_user_interview_turn(p_project_id,p_client_turn_id);
 end if;
 if jsonb_array_length(p_recording_ids)>0 then
   if p_kind<>'narrator_transcript' or length(btrim(p_text))=0 then raise exception 'recorded narration required';end if;
   for identifier in select value from jsonb_array_elements_text(p_recording_ids) loop
     select * into r from public.user_original_recording where id=identifier::uuid for update;
     if not found or not public.original_recording_visible(r,auth.uid()) or r.storage_status<>'ready'
       or r.lifecycle<>'draft' or r.project_id is not null and r.project_id<>p_project_id then
       raise exception 'recording unavailable' using errcode='42501';end if;
   end loop;
   if (select sum(duration_seconds) from public.user_original_recording
     where id in (select value::uuid from jsonb_array_elements_text(p_recording_ids)))>300 then
     raise exception 'combined recording duration exceeds five minutes' using errcode='PT413';end if;
 end if;
 if p_two_lane then result:=public.accept_two_lane_interview_turn_before_recordings(p_project_id,p_client_turn_id,p_text,p_kind,p_language,p_uploaded_photo_ids,p_photo_selection);
 else result:=public.accept_user_interview_turn_before_recordings(p_project_id,p_client_turn_id,p_text,p_kind,p_language,p_uploaded_photo_ids,p_photo_selection);end if;
 for identifier in select value from jsonb_array_elements_text(p_recording_ids) loop
   insert into public.user_source_recording values(auth.uid(),p_project_id,(result->'source'->>'id')::uuid,
     (result->'source'->>'version')::bigint,p_client_turn_id,identifier::uuid,index);
   update public.user_original_recording set project_id=p_project_id,lifecycle='attached' where id=identifier::uuid;
   index:=index+1;
 end loop;
 return public.read_user_interview_turn(p_project_id,p_client_turn_id);
end $$;
revoke all on function public.accept_recorded_interview_turn(boolean,text,uuid,text,text,text,jsonb,jsonb,jsonb) from public,anon,authenticated,service_role;
commit;
