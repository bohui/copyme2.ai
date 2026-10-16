-- Keep semantic-summary SQL evidence admission aligned with the exact-subspan validator.
begin;
create or replace function public.commit_lifetime_memory_summary_page(p_lane_id uuid,p_token uuid,p_revision bigint,p_result jsonb,p_page_digest text)
returns jsonb language plpgsql security definer set search_path=public,auth as $$
declare snap public.user_lifetime_lane_snapshot%rowtype; proof public.user_lifetime_compaction%rowtype; page jsonb;
 item jsonb; ref jsonb; original public.user_narrator_source%rowtype; fingerprint text;
begin
 snap:=public.lock_lifetime_memoir_lane(p_lane_id,p_token);
 fingerprint:=encode(sha256(convert_to(p_result::text,'UTF8')),'hex');
 select p.* into proof from public.user_lifetime_compaction p join public.user_lifetime_summary_receipt r on r.maintenance_id=p.id
   where p.user_id=snap.user_id and p.conversation_id=snap.conversation_id and r.revision=p_revision and r.page_digest=p_page_digest;
 if found then
   if not exists(select 1 from public.user_lifetime_summary_receipt r where r.maintenance_id=proof.id and r.revision=p_revision and r.result_digest=fingerprint) then
     raise exception 'summary replay conflict' using errcode='PT409';end if;
   return jsonb_build_object('status','page_saved','replayed',true);
 end if;
 page:=public.read_lifetime_memoir_lane_page(p_lane_id,p_token);
 if page->'memory_summary' is null or p_page_digest is distinct from page->>'page_digest'
   or p_revision is distinct from (page->'memory_summary'->>'revision')::bigint then raise exception 'stale summary page' using errcode='PT409';end if;
 select * into proof from public.user_lifetime_compaction where id=(page->'memory_summary'->>'maintenance_id')::uuid for update;
 if jsonb_typeof(p_result) is distinct from 'object' or exists(select 1 from jsonb_object_keys(p_result) k where k<>'items')
   or jsonb_typeof(p_result->'items') is distinct from 'array' or jsonb_array_length(p_result->'items')>16
   or octet_length(p_result::text)>8192 then raise exception 'bounded semantic summary required' using errcode='22023';end if;
 if page->'memory_summary'->>'work_mode'='reply_only' and p_result is distinct from proof.summary_data then
   raise exception 'fact-free summary step must preserve prior context' using errcode='22023';end if;
 for item in select value from jsonb_array_elements(p_result->'items') loop
   if jsonb_typeof(item) is distinct from 'object' or exists(select 1 from jsonb_object_keys(item) k where k not in ('text','uncertainty','source_refs'))
     or jsonb_typeof(item->'text') is distinct from 'string' or length(item->>'text') not between 1 and 500
     or jsonb_typeof(item->'uncertainty') is distinct from 'string' or length(item->>'uncertainty') not between 1 and 500
     or jsonb_typeof(item->'source_refs') is distinct from 'array' or jsonb_array_length(item->'source_refs') not between 1 and 4 then
     raise exception 'typed derived summary item required' using errcode='22023';end if;
   for ref in select value from jsonb_array_elements(item->'source_refs') loop
     if jsonb_typeof(ref) is distinct from 'object' or exists(select 1 from jsonb_object_keys(ref) k where k not in ('source_id','version','quote','char_start','char_end'))
       or not(ref ?& array['source_id','version','quote','char_start','char_end']) or jsonb_typeof(ref->'quote') is distinct from 'string'
       or length(ref->>'quote') not between 1 and 500 or coalesce(ref->>'version','')!~'^[1-9][0-9]*$'
       or coalesce(ref->>'char_start','')!~'^[0-9]+$' or coalesce(ref->>'char_end','')!~'^[1-9][0-9]*$' then
       raise exception 'exact summary evidence required' using errcode='22023';end if;
     select * into original from public.user_narrator_source where user_id=snap.user_id and project_id=snap.project_id
       and id=(ref->>'source_id')::uuid and version=(ref->>'version')::bigint and status='active';
     if not found or (ref->>'char_end')::integer-(ref->>'char_start')::integer<>length(ref->>'quote')
       or substring(original.text from (ref->>'char_start')::integer+1 for length(ref->>'quote')) is distinct from ref->>'quote'
       or not ((page->'source'->>'id'=ref->>'source_id' and page->'source'->>'version'=ref->>'version'
         and (ref->>'char_start')::integer>=(page->'source'->>'char_start')::integer
         and (ref->>'char_end')::integer<=(page->'source'->>'char_end')::integer)
         or exists(select 1 from jsonb_array_elements(proof.summary_data->'items') old
           cross join lateral jsonb_array_elements(old->'source_refs') r
           where r->>'source_id'=ref->>'source_id' and r->>'version'=ref->>'version'
             and (ref->>'char_start')::integer>=(r->>'char_start')::integer
             and (ref->>'char_end')::integer<=(r->>'char_end')::integer
             and substring(r->>'quote' from (ref->>'char_start')::integer-(r->>'char_start')::integer+1
               for length(ref->>'quote'))=ref->>'quote')) then
       raise exception 'summary evidence outside accepted inputs' using errcode='22023';end if;
   end loop;
 end loop;
 update public.user_lifetime_compaction set summary_data=p_result,summary_sequence=(page->'memory_summary'->>'sequence')::bigint,
   summary_offset=(page->'memory_summary'->>'char_start')::integer,summary_revision=summary_revision+1,summary_windows=summary_windows+1
   where id=proof.id and summary_revision=p_revision;
 if not found then raise exception 'summary CAS failed' using errcode='PT409';end if;
 insert into public.user_lifetime_summary_receipt values(proof.id,p_revision,p_page_digest,fingerprint);
 return jsonb_build_object('status','page_saved');
end $$;
revoke all on function public.commit_lifetime_memory_summary_page(uuid,uuid,bigint,jsonb,text) from public,anon,authenticated;
grant execute on function public.commit_lifetime_memory_summary_page(uuid,uuid,bigint,jsonb,text) to service_role;
commit;
