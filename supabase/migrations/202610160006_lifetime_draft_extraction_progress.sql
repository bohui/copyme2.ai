-- A queued composer cannot hide a failed upstream extraction lane.
begin;
alter function public.read_lifetime_private_draft_head(text,text) rename to read_lifetime_private_draft_head_before_extraction_progress;
revoke all on function public.read_lifetime_private_draft_head_before_extraction_progress(text,text) from public,anon,authenticated,service_role;

create function public.read_lifetime_private_draft_head(p_project_id text,p_locale text) returns jsonb
language plpgsql security definer set search_path=public,auth as $$
declare result jsonb; lane public.user_memoir_lane%rowtype; extraction jsonb; pending bigint; extracted bigint;
begin
 result:=public.read_lifetime_private_draft_head_before_extraction_progress(p_project_id,p_locale);
 if result is null or result->>'project_id' is distinct from p_project_id then return result;end if;
 select * into lane from public.user_memoir_lane where user_id=auth.uid() and project_id=p_project_id and skill='timeline';
 select count(*) into pending from public.user_narrator_source where user_id=auth.uid() and project_id=p_project_id
  and status='active' and processing_status<>'succeeded';
 select extraction_cursor into extracted from public.user_memoir_project where user_id=auth.uid() and project_id=p_project_id;
 extraction:=public.memoir_lane_progress(lane)||jsonb_build_object('pending_inputs',pending,'extracted_through',coalesce(extracted,0));
 if pending>0 and extraction->>'state'='finished' then
  extraction:=extraction||jsonb_build_object('state','pending','pending',true);
 end if;
 result:=result||jsonb_build_object('progress',coalesce(result->'progress','{}')||jsonb_build_object('extraction',extraction));
 if coalesce((result->'background_progress'->>'target_milestone')::bigint,0)<5 then return result;end if;
 if pending>0 and extraction->>'state'='retry_required' then
  return result||jsonb_build_object('updating',false,'error',coalesce(extraction->>'error','MEMOIR_UNAVAILABLE'),
   'background_progress',coalesce(result->'background_progress','{}')||jsonb_build_object('state','retry_required','phase','extracting'));
 end if;
 if pending>0 and coalesce(result->'progress'->'composition'->>'state','pending') in ('pending','finished') then
  result:=result||jsonb_build_object('updating',true,'background_progress',
   coalesce(result->'background_progress','{}')||jsonb_build_object('state',extraction->>'state','phase','extracting'));
 end if;
 return result;
end $$;
revoke all on function public.read_lifetime_private_draft_head(text,text) from public,anon;
grant execute on function public.read_lifetime_private_draft_head(text,text) to authenticated;
notify pgrst,'reload schema';
commit;
