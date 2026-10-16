-- Issue 73, application schema only. NOT APPLIED to any shared environment.
-- No bucket provisioning, Storage policies, credentials or access changes.
begin;
create table public.original_recording_rollout (
 singleton boolean primary key default true check(singleton), enabled boolean not null default false
);
insert into public.original_recording_rollout default values;
alter table public.original_recording_rollout enable row level security;
revoke all on public.original_recording_rollout from public,anon,authenticated,service_role;

-- Deliberate fail-closed integration seam. Current canonical Supabase journey
-- has no approved purpose-specific retention/AI consent authority. Replacing
-- this requires separately approved integration, never a caller consent flag.
create function public.original_recording_authorized(p_owner uuid,p_project_id text) returns boolean
language sql stable security definer set search_path='' as $$select false$$;
revoke all on function public.original_recording_authorized(uuid,text) from public,anon,authenticated,service_role;

create table public.user_original_recording (
 id uuid primary key default gen_random_uuid(), user_id uuid references auth.users on delete set null,
 project_id text, upload_project_id text, upload_key uuid not null, object_path text not null unique,
 content_type text not null check(content_type in ('audio/webm','audio/mp4','audio/ogg','audio/wav')),
 codec text not null, byte_size bigint not null check(byte_size between 1 and 10485760),
 duration_seconds double precision not null check(duration_seconds>0 and duration_seconds<=300),
 content_sha256 text not null check(content_sha256 ~ '^[a-f0-9]{64}$'),
 storage_status text not null default 'pending' check(storage_status in ('pending','ready','deleted')),
 transcription_status text not null default 'not_started' check(transcription_status in ('not_started','failed','succeeded')),
 asr_result jsonb, lifecycle text not null default 'draft' check(lifecycle in ('draft','attached','deleted')),
 cleanup_status text not null default 'not_requested' check(cleanup_status in ('not_requested','pending','complete')),
 write_revision bigint not null default 0,
 created_at timestamptz not null default clock_timestamp(), unique(user_id,upload_key)
);
-- Cancellation survives requests that have not finished decoding/reserving yet.
-- No audio is stored here; keys never expire into reusable upload identities.
create table public.user_original_recording_cancel (
 user_id uuid not null references auth.users on delete cascade, upload_key uuid not null,
 created_at timestamptz not null default clock_timestamp(), primary key(user_id,upload_key)
);
-- An unfinished writer makes byte erasure uncertain, even after a successful
-- DELETE response. A process crash leaves a pending cleanup intent, not success.
create table public.user_original_recording_upload (
 id uuid primary key default gen_random_uuid(), recording_id uuid not null references public.user_original_recording on delete cascade,
 finished_at timestamptz
);
alter table public.user_original_recording_cancel enable row level security;
alter table public.user_original_recording_upload enable row level security;
revoke all on public.user_original_recording_cancel,public.user_original_recording_upload from public,anon,authenticated,service_role;

create table public.user_source_recording (
 user_id uuid not null, project_id text not null, source_id uuid not null, source_version bigint not null,
 client_turn_id uuid not null, recording_id uuid not null unique references public.user_original_recording,
 position integer not null check(position between 0 and 19),
 primary key(user_id,project_id,source_id,position),
 foreign key(user_id,project_id,source_id) references public.user_narrator_source on delete cascade
);
alter table public.user_original_recording enable row level security;
alter table public.user_source_recording enable row level security;
revoke all on public.user_original_recording,public.user_source_recording from public,anon,authenticated,service_role;

create function public.original_recording_visible(r public.user_original_recording,p_owner uuid) returns boolean
language sql stable security definer set search_path='' as $$
 select r.user_id=p_owner and r.lifecycle<>'deleted'
 and not exists(select 1 from public.user_original_recording_cancel where user_id=p_owner and upload_key=r.upload_key)
 and exists(select 1 from public.original_recording_rollout where enabled)
 and public.original_recording_authorized(p_owner,r.project_id)
 and (r.project_id is null or exists(select 1 from public.user_memoir_project p
   where p.user_id=p_owner and p.project_id=r.project_id))
 and not exists(select 1 from public.user_lifetime_pending_policy where user_id=p_owner and project_id=r.project_id)
 and not exists(select 1 from public.user_lifetime_policy_inventory_pending where user_id=p_owner and project_id=r.project_id)
 and (r.lifecycle='draft' or exists(select 1 from public.user_source_recording l
   join public.user_narrator_source s on s.user_id=l.user_id and s.project_id=l.project_id and s.id=l.source_id
   where l.recording_id=r.id and l.user_id=p_owner and s.status='active'))
$$;
revoke all on function public.original_recording_visible(public.user_original_recording,uuid) from public,anon,authenticated,service_role;

create function public.original_recording_descriptor(r public.user_original_recording) returns jsonb
language sql immutable set search_path='' as $$
 select jsonb_build_object('id',r.id,'content_type',r.content_type,'codec',r.codec,'byte_size',r.byte_size,
 'duration_seconds',r.duration_seconds,'content_sha256',r.content_sha256,'storage_status',r.storage_status,
 'transcription_status',r.transcription_status,'lifecycle',r.lifecycle,'created_at',r.created_at,
 'backend_saved',r.storage_status='ready' and r.lifecycle<>'deleted',
 'content_url','/api/v1/memoir/story/recordings/'||r.id::text||'/content')
$$;
revoke all on function public.original_recording_descriptor(public.user_original_recording) from public,anon,authenticated,service_role;

create function public.read_user_original_recording(p_recording_id uuid) returns jsonb
language sql stable security definer set search_path='' as $$
 select public.original_recording_descriptor(r) || jsonb_build_object('asr_result',r.asr_result) from public.user_original_recording r
 where r.id=p_recording_id and public.original_recording_visible(r,auth.uid())
$$;
revoke all on function public.read_user_original_recording(uuid) from public,anon,service_role;
grant execute on function public.read_user_original_recording(uuid) to authenticated;

create function public.read_user_source_recordings(p_project_id text,p_source_id uuid) returns jsonb
language sql stable security definer set search_path='' as $$
 select coalesce(jsonb_agg(public.original_recording_descriptor(r) order by l.position),'[]')
 from public.user_source_recording l join public.user_original_recording r on r.id=l.recording_id
 where l.user_id=auth.uid() and l.project_id=p_project_id and l.source_id=p_source_id
 and public.original_recording_visible(r,auth.uid()) and r.storage_status='ready'
$$;
revoke all on function public.read_user_source_recordings(text,uuid) from public,anon,service_role;
grant execute on function public.read_user_source_recordings(text,uuid) to authenticated;

-- Only a trusted server connection may reserve media metadata, attest original
-- readback or persist provider provenance. An authenticated JWT cannot forge
-- ready status by finding an object or calling the attestation RPC directly.
create function public.recording_server_operation(p_owner uuid,p_operation text,p_recording_id uuid,p_data jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare r public.user_original_recording%rowtype; identifier uuid; project text:=p_data->>'project_id';
begin
 perform 1 from auth.users where id=p_owner for share;
 if not found then raise exception 'recording owner unavailable' using errcode='42501';end if;
 if p_operation='find_upload' then
   select * into r from public.user_original_recording where user_id=p_owner and upload_key=(p_data->>'upload_key')::uuid;
   return case when found then to_jsonb(r) else null end;
 end if;
 if p_operation='cancel_upload' then
   perform pg_advisory_xact_lock(hashtextextended(p_owner::text||':'||(p_data->>'upload_key'),0));
   select * into r from public.user_original_recording where user_id=p_owner and upload_key=(p_data->>'upload_key')::uuid for update;
   if found and r.lifecycle='attached' then
     return jsonb_build_object('cancelled',true,'recording_id',r.id,'already_attached',true);
   end if;
   insert into public.user_original_recording_cancel(user_id,upload_key) values(p_owner,(p_data->>'upload_key')::uuid) on conflict do nothing;
   if r.id is not null then
     update public.user_original_recording set lifecycle='deleted',storage_status='deleted',asr_result=null,
       cleanup_status=case when cleanup_status='complete' then 'complete' else 'pending' end where id=r.id;
   end if;
   return jsonb_build_object('cancelled',true,'recording_id',r.id,'already_attached',false);
 end if;
 if p_operation in ('read','begin_upload','finalize','asr_failed','asr_succeeded') then
   -- Disable is a committed revocation boundary: it waits for admitted reads/
   -- provider work, and no later guard can admit after it commits.
   perform 1 from public.original_recording_rollout where enabled for share;
   if not found then raise exception 'recording unavailable' using errcode='42501';end if;
 end if;
 if p_operation in ('authorize','reserve') then
   perform 1 from public.original_recording_rollout where enabled for share;
   if not found or not public.original_recording_authorized(p_owner,project) then
     raise exception 'recording authority required' using errcode='42501';end if;
   if project is not null then
     perform 1 from public.user_memoir_project where user_id=p_owner and project_id=project for share;
     if not found then raise exception 'recording project unavailable' using errcode='42501';end if;
   end if;
   if p_operation='authorize' then return '{}'::jsonb;end if;
   perform pg_advisory_xact_lock(hashtextextended(p_owner::text||':'||(p_data->>'upload_key'),0));
   if exists(select 1 from public.user_original_recording_cancel where user_id=p_owner and upload_key=(p_data->>'upload_key')::uuid) then
     raise exception 'upload was cancelled' using errcode='40001';end if;
   select * into r from public.user_original_recording where user_id=p_owner and upload_key=(p_data->>'upload_key')::uuid for update;
   if found then
     if r.lifecycle='deleted' or r.upload_project_id is distinct from project
       or r.content_sha256 is distinct from p_data->>'content_sha256'
       or r.content_type is distinct from p_data->>'content_type'
       or r.codec is distinct from p_data->>'codec'
       or r.byte_size is distinct from (p_data->>'byte_size')::bigint
       or r.duration_seconds is distinct from (p_data->>'duration_seconds')::double precision then
       raise exception 'upload retry identity conflict' using errcode='40001';end if;
     return to_jsonb(r);end if;
   identifier:=gen_random_uuid();
   insert into public.user_original_recording(id,user_id,project_id,upload_project_id,upload_key,object_path,content_type,codec,byte_size,duration_seconds,content_sha256)
   values(identifier,p_owner,project,project,(p_data->>'upload_key')::uuid,'originals/'||identifier::text,
     p_data->>'content_type',p_data->>'codec',(p_data->>'byte_size')::bigint,
     (p_data->>'duration_seconds')::double precision,p_data->>'content_sha256') returning * into r;
   return to_jsonb(r);
 end if;
 if p_operation='read' then
   select project_id into project from public.user_original_recording where user_id=p_owner and id=p_recording_id;
   if project is not null then
     perform 1 from public.user_memoir_project where user_id=p_owner and project_id=project for share;
   end if;
 end if;
 select * into r from public.user_original_recording where user_id=p_owner and id=p_recording_id for update;
 if not found then raise exception 'recording unavailable' using errcode='42501';end if;
 -- Withdrawal must never prevent an owner from requesting cleanup.
 if p_operation='read' then
   if r.project_id is distinct from project then raise exception 'recording scope changed' using errcode='40001';end if;
   if not public.original_recording_visible(r,p_owner) then raise exception 'recording unavailable' using errcode='42501';end if;
   return to_jsonb(r);
 elsif p_operation='delete' then
   if (p_data->>'draft_only')::boolean is true and r.lifecycle='attached' then
     raise exception 'recording already attached; reconcile acceptance' using errcode='40001';end if;
   update public.user_original_recording set lifecycle='deleted',storage_status='deleted',
     cleanup_status=case when cleanup_status='complete' then 'complete' else 'pending' end,asr_result=null
     where id=r.id returning * into r;
 elsif p_operation='finish_upload' then
   update public.user_original_recording_upload set finished_at=clock_timestamp()
     where id=(p_data->>'attempt_id')::uuid and recording_id=r.id and finished_at is null;
   if found then
     -- A completed writer invalidates every DELETE receipt taken before it
     -- stopped, even if that DELETE's HTTP response was delayed until later.
     update public.user_original_recording set write_revision=write_revision+1,
       cleanup_status=case when lifecycle='deleted' then 'pending' else cleanup_status end
       where id=r.id returning * into r;
   end if;
 elsif p_operation='cleanup_complete' and r.lifecycle='deleted' then
   if r.write_revision=(p_data->>'write_revision')::bigint
     and not exists(select 1 from public.user_original_recording_upload where recording_id=r.id and finished_at is null) then
     update public.user_original_recording set cleanup_status='complete' where id=r.id returning * into r;
   end if;
 else
   if not public.original_recording_visible(r,p_owner) then raise exception 'recording unavailable' using errcode='42501';end if;
   if p_operation='begin_upload' then
     update public.user_original_recording set write_revision=write_revision+1 where id=r.id returning * into r;
     insert into public.user_original_recording_upload(recording_id) values(r.id) returning id into identifier;
     return to_jsonb(r)||jsonb_build_object('upload_attempt_id',identifier);
   elsif p_operation='finalize' then
     if r.content_sha256 is distinct from p_data->>'content_sha256'
       or r.byte_size is distinct from (p_data->>'byte_size')::bigint then
       raise exception 'original readback conflict' using errcode='40001';end if;
     update public.user_original_recording set storage_status='ready' where id=r.id returning * into r;
   elsif p_operation in ('asr_failed','asr_succeeded') and r.storage_status='ready' then
     if p_operation='asr_succeeded' and (jsonb_typeof(p_data->'result')<>'object' or length(btrim(coalesce(p_data->'result'->>'text','')))=0
       or octet_length((p_data->'result')::text)>262144) then raise exception 'invalid transcription';end if;
     -- A racing failed attempt cannot overwrite a persisted successful result.
     if r.transcription_status<>'succeeded' then
       update public.user_original_recording set transcription_status=case when p_operation='asr_succeeded' then 'succeeded' else 'failed' end,
         asr_result=case when p_operation='asr_succeeded' then p_data->'result' else null end where id=r.id returning * into r;
     end if;
   else raise exception 'invalid recording transition';end if;
 end if;
 return to_jsonb(r);
end $$;
revoke all on function public.recording_server_operation(uuid,text,uuid,jsonb) from public,anon,authenticated,service_role;

alter function public.accept_user_interview_turn(text,uuid,text,text,text,jsonb,jsonb) rename to accept_user_interview_turn_before_recordings;
alter function public.accept_two_lane_interview_turn(text,uuid,text,text,text,jsonb,jsonb) rename to accept_two_lane_interview_turn_before_recordings;
revoke all on function public.accept_user_interview_turn_before_recordings(text,uuid,text,text,text,jsonb,jsonb),
 public.accept_two_lane_interview_turn_before_recordings(text,uuid,text,text,text,jsonb,jsonb) from public,anon,authenticated,service_role;

create function public.accept_recorded_interview_turn(p_two_lane boolean,p_project_id text,p_client_turn_id uuid,p_text text,
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

create function public.accept_user_interview_turn(p_project_id text,p_client_turn_id uuid,p_text text,
 p_kind text default 'narrator_chat',p_language text default 'en-AU',p_uploaded_photo_ids jsonb default '[]',p_photo_selection jsonb default null,p_recording_ids jsonb default '[]')
returns jsonb language sql security definer set search_path='' as $$
 select public.accept_recorded_interview_turn(false,p_project_id,p_client_turn_id,p_text,p_kind,p_language,p_uploaded_photo_ids,p_photo_selection,p_recording_ids)
$$;
create function public.accept_two_lane_interview_turn(p_project_id text,p_client_turn_id uuid,p_text text,
 p_kind text default 'narrator_chat',p_language text default 'en-AU',p_uploaded_photo_ids jsonb default '[]',p_photo_selection jsonb default null,p_recording_ids jsonb default '[]')
returns jsonb language sql security definer set search_path='' as $$
 select public.accept_recorded_interview_turn(true,p_project_id,p_client_turn_id,p_text,p_kind,p_language,p_uploaded_photo_ids,p_photo_selection,p_recording_ids)
$$;
revoke all on function public.accept_user_interview_turn(text,uuid,text,text,text,jsonb,jsonb,jsonb),public.accept_two_lane_interview_turn(text,uuid,text,text,text,jsonb,jsonb,jsonb) from public,anon,service_role;
grant execute on function public.accept_user_interview_turn(text,uuid,text,text,text,jsonb,jsonb,jsonb),public.accept_two_lane_interview_turn(text,uuid,text,text,text,jsonb,jsonb,jsonb) to authenticated;

alter function public.read_user_interview_turn(text,uuid) rename to read_user_interview_turn_before_recordings;
revoke all on function public.read_user_interview_turn_before_recordings(text,uuid) from public,anon,authenticated,service_role;
create function public.read_user_interview_turn(p_project_id text,p_client_turn_id uuid) returns jsonb
language sql stable security definer set search_path='' as $$
 select public.read_user_interview_turn_before_recordings(p_project_id,p_client_turn_id) || jsonb_build_object(
   -- Accepted request identity survives audio-only deletion. Readable
   -- descriptors remain independently filtered by current access/lifecycle.
   'recording_ids',(select coalesce(jsonb_agg(recording_id::text order by position),'[]')
     from public.user_source_recording where user_id=auth.uid() and project_id=p_project_id and client_turn_id=p_client_turn_id),
   'recordings',
   public.read_user_source_recordings(p_project_id,(select source_id from public.user_interview_turn
     where user_id=auth.uid() and project_id=p_project_id and client_turn_id=p_client_turn_id)))
$$;
revoke all on function public.read_user_interview_turn(text,uuid) from public,anon,service_role;
grant execute on function public.read_user_interview_turn(text,uuid) to authenticated;

alter function public.validate_lifetime_replay_input(uuid,uuid,text,text) rename to validate_lifetime_replay_before_recordings;
revoke all on function public.validate_lifetime_replay_before_recordings(uuid,uuid,text,text) from public,anon,authenticated,service_role;
create function public.validate_lifetime_replay_input(p_conversation_id uuid,p_client_turn_id uuid,p_text text,p_kind text,p_recording_ids jsonb default '[]')
returns boolean language plpgsql security definer set search_path='' as $$
declare accepted boolean; saved jsonb;
begin
 accepted:=public.validate_lifetime_replay_before_recordings(p_conversation_id,p_client_turn_id,p_text,p_kind);
 if accepted then
   select coalesce(jsonb_agg(l.recording_id::text order by l.position),'[]') into saved
   from public.user_source_recording l join public.user_lifetime_conversation c on c.user_id=l.user_id and c.project_id=l.project_id
   where c.user_id=auth.uid() and c.conversation_id=p_conversation_id and l.client_turn_id=p_client_turn_id;
   if saved is distinct from p_recording_ids then raise exception 'recording replay conflict' using errcode='PT409';end if;
 end if;
 return accepted;
end $$;
revoke all on function public.validate_lifetime_replay_input(uuid,uuid,text,text,jsonb) from public,anon,service_role;
grant execute on function public.validate_lifetime_replay_input(uuid,uuid,text,text,jsonb) to authenticated;

create function public.tombstone_project_recordings() returns trigger
language plpgsql security definer set search_path='' as $$
begin
 update public.user_original_recording set lifecycle='deleted',storage_status='deleted',cleanup_status='pending',asr_result=null
 where user_id=old.user_id and project_id=old.project_id and lifecycle<>'deleted';
 return old;
end $$;
create trigger tombstone_original_recordings before delete on public.user_memoir_project
 for each row execute function public.tombstone_project_recordings();
revoke all on function public.tombstone_project_recordings() from public,anon,authenticated,service_role;

create function public.tombstone_source_recordings() returns trigger
language plpgsql security definer set search_path='' as $$
begin
 update public.user_original_recording set lifecycle='deleted',storage_status='deleted',cleanup_status='pending',asr_result=null
 where lifecycle<>'deleted' and id in (select recording_id from public.user_source_recording where user_id=old.user_id and project_id=old.project_id and source_id=old.id);
 return old;
end $$;
create trigger tombstone_original_recordings before delete on public.user_narrator_source
 for each row execute function public.tombstone_source_recordings();
create function public.tombstone_account_recordings() returns trigger
language plpgsql security definer set search_path='' as $$
begin
 update public.user_original_recording set lifecycle='deleted',storage_status='deleted',cleanup_status='pending',asr_result=null where user_id=old.id and lifecycle<>'deleted';
 return old;
end $$;
create trigger tombstone_original_recordings before delete on auth.users
 for each row execute function public.tombstone_account_recordings();
revoke all on function public.tombstone_source_recordings(),public.tombstone_account_recordings() from public,anon,authenticated,service_role;

-- The supported guest transfer snapshots and moves metadata in its existing
-- transaction. Object names remain immutable; old principals lose metadata.
alter function public.interview_transfer_snapshot(uuid,text) rename to interview_transfer_snapshot_before_recordings;
revoke all on function public.interview_transfer_snapshot_before_recordings(uuid,text) from public,anon,authenticated,service_role;
create function public.interview_transfer_snapshot(p_owner uuid,p_project_id text) returns jsonb
language sql stable security definer set search_path='' as $$
 select public.interview_transfer_snapshot_before_recordings(p_owner,p_project_id) || jsonb_build_object(
  'user_original_recording',coalesce((select jsonb_agg(to_jsonb(r) order by r.id) from public.user_original_recording r where user_id=p_owner and project_id=p_project_id),'[]'),
  'user_source_recording',coalesce((select jsonb_agg(to_jsonb(l) order by l.recording_id) from public.user_source_recording l where user_id=p_owner and project_id=p_project_id),'[]'))
$$;
revoke all on function public.interview_transfer_snapshot(uuid,text) from public,anon,authenticated,service_role;
create table public.user_original_recording_transfer (
 attachment_id uuid primary key references public.user_conversation_attachment on delete cascade,
 user_id uuid not null references auth.users on delete cascade
);
alter table public.user_original_recording_transfer enable row level security;
revoke all on public.user_original_recording_transfer from public,anon,authenticated,service_role;
alter function public.attach_guest_conversation(text,boolean) rename to attach_guest_conversation_before_recordings;
revoke all on function public.attach_guest_conversation_before_recordings(text,boolean) from public,anon,authenticated,service_role;
create function public.attach_guest_conversation(p_token text,p_guest_wins boolean default false) returns jsonb
language plpgsql security definer set search_path='' as $$
declare result jsonb; attachment public.user_conversation_attachment%rowtype; snapshot jsonb; live jsonb; guest uuid;
begin
 result:=public.attach_guest_conversation_before_recordings(p_token,p_guest_wins);
 select * into attachment from public.user_conversation_attachment where user_id=auth.uid() and id=(result->>'conversation_id')::uuid;
 if exists(select 1 from public.user_original_recording_transfer where attachment_id=attachment.id) then return result;end if;
 guest:=(result->>'guest_user_id')::uuid;
 snapshot:=attachment.workspace->'interview_photos';
 if snapshot ? 'user_original_recording' then
   live:=public.interview_transfer_snapshot(guest,attachment.project_id);
   if snapshot->'user_original_recording' is distinct from live->'user_original_recording'
     or snapshot->'user_source_recording' is distinct from live->'user_source_recording' then
     raise exception 'guest recording state changed' using errcode='40001';end if;
   update public.user_original_recording set user_id=auth.uid() where user_id=guest and project_id=attachment.project_id;
   update public.user_source_recording set user_id=auth.uid() where user_id=guest and project_id=attachment.project_id;
 end if;
 insert into public.user_original_recording_transfer values(attachment.id,auth.uid());
 return result;
end $$;
revoke all on function public.attach_guest_conversation(text,boolean) from public,anon,service_role;
grant execute on function public.attach_guest_conversation(text,boolean) to authenticated;

notify pgrst,'reload schema';
commit;
