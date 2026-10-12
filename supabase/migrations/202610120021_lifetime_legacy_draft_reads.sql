-- Governed, bounded compatibility views of unchanged legacy manuscript sections.
-- Legacy prose is never fed into the canonical composer or silently rewritten.
begin;
create table public.user_lifetime_legacy_draft_snapshot (
 id uuid primary key default gen_random_uuid(),user_id uuid not null,project_id text not null,locale text not null,
 conversation_id uuid not null references public.user_lifetime_conversation(conversation_id) on delete cascade,
 manuscript_revision bigint not null,bundle_digest text not null,policy_epoch bigint not null,preference_revision bigint not null,
 created_at timestamptz not null default clock_timestamp(),
 unique(user_id,project_id,locale,manuscript_revision,bundle_digest,policy_epoch,preference_revision)
);
create table public.user_lifetime_legacy_draft_cursor (
 id uuid primary key default gen_random_uuid(),snapshot_id uuid not null references public.user_lifetime_legacy_draft_snapshot(id) on delete cascade,
 section_id text not null,char_offset integer not null default 0,ref_offset integer not null default 0,kind text not null default 'prose'
);
alter table public.user_lifetime_legacy_draft_snapshot enable row level security;
alter table public.user_lifetime_legacy_draft_cursor enable row level security;
revoke all on public.user_lifetime_legacy_draft_snapshot,public.user_lifetime_legacy_draft_cursor from public,anon,authenticated;

create function public.lifetime_legacy_section_eligible(s public.user_memoir_section_revision) returns boolean
language plpgsql stable security definer set search_path='' as $$
declare ref jsonb; original public.user_narrator_source%rowtype; event_ref jsonb;
begin
 if jsonb_typeof(s.data->'source_refs') is distinct from 'array' or jsonb_array_length(s.data->'source_refs')=0 or
    jsonb_typeof(s.event_manifest) is distinct from 'array' or jsonb_array_length(s.event_manifest)=0 then return false;end if;
 for ref in select value from jsonb_array_elements(s.data->'source_refs') loop
   if coalesce(ref->>'source_id','') !~ '^[0-9a-fA-F-]{36}$' or coalesce(ref->>'version','')!~'^[0-9]{1,18}$' or
      coalesce(ref->>'char_start','')!~'^[0-9]{1,9}$' or coalesce(ref->>'char_end','')!~'^[0-9]{1,9}$' then return false;end if;
   select * into original from public.user_narrator_source where user_id=s.user_id and project_id=s.project_id
     and id::text=ref->>'source_id' and version::text=ref->>'version' and status='active';
   if not found or (ref->>'char_start')::integer<0 or (ref->>'char_end')::integer<=(ref->>'char_start')::integer or
      (ref->>'char_end')::integer>length(original.text) or (ref ? 'quote' and ref->>'quote' is distinct from
      substring(original.text from (ref->>'char_start')::integer+1 for (ref->>'char_end')::integer-(ref->>'char_start')::integer)) then return false;end if;
 end loop;
 for event_ref in select value from jsonb_array_elements(s.event_manifest) loop
   if not exists(select 1 from public.user_memory_event e where e.user_id=s.user_id and e.project_id=s.project_id
     and e.id=event_ref->>'id' and e.revision::text=event_ref->>'revision' and e.status<>'withdrawn') then return false;end if;
 end loop;
 if jsonb_typeof(s.data->'event_ids') is distinct from 'array' or exists(select 1 from jsonb_array_elements_text(s.data->'event_ids') id
   where not exists(select 1 from jsonb_array_elements(s.event_manifest) e where e->>'id'=id)) then return false;end if;
 return true;
end $$;
revoke all on function public.lifetime_legacy_section_eligible(public.user_memoir_section_revision) from public,anon,authenticated;

create function public.read_lifetime_legacy_draft_page(p_project_id text,p_snapshot_id uuid,p_after uuid default null,p_limit integer default 8,
 p_section_id text default null) returns jsonb language plpgsql security definer set search_path='' as $$
declare owner uuid:=auth.uid(); identity public.user_lifetime_conversation%rowtype; project public.user_memoir_project%rowtype;
 root public.user_lifetime_legacy_draft_snapshot%rowtype;saved public.user_memoir_manuscript%rowtype; cursor_row public.user_lifetime_legacy_draft_cursor%rowtype;
 section public.user_memoir_section_revision%rowtype; pins jsonb; records jsonb:='[]'; refs jsonb; source_ref jsonb;
 boundary text:=''; offset_chars integer:=0; offset_refs integer:=0; part text; next_cursor uuid; has_more boolean:=false;
 next_section text; next_offset integer; next_ref integer:=0; digest text; valid boolean; total_chars integer; missing_sections bigint;
begin
 if owner is null or p_limit is null or p_limit not between 1 and 8 or (p_section_id is not null and length(p_section_id)>128)
   then raise exception 'invalid legacy page' using errcode='22023';end if;
 select * into identity from public.user_lifetime_conversation where user_id=owner and project_id=p_project_id;
 if not found then raise exception 'canonical conversation unavailable' using errcode='42501';end if;
 select * into project from public.user_memoir_project where user_id=owner and project_id=p_project_id for share;
 perform 1 from public.user_profile where user_id=owner for share;
 select * into identity from public.user_lifetime_conversation where conversation_id=identity.conversation_id for share;
 select * into root from public.user_lifetime_legacy_draft_snapshot where id=p_snapshot_id and user_id=owner and project_id=p_project_id
   and conversation_id=identity.conversation_id;
 if not found then raise exception 'legacy snapshot scope mismatch' using errcode='42501';end if;
 select * into saved from public.user_memoir_manuscript where user_id=owner and project_id=p_project_id and locale=root.locale for share;
 pins:=public.read_lifetime_pinned(identity.conversation_id);
 if saved.revision is distinct from root.manuscript_revision or saved.eligible is not true or saved.bundle is null or
    root.policy_epoch<>project.policy_epoch or root.preference_revision<>identity.preference_revision or
    root.bundle_digest<>encode(sha256(convert_to(saved.bundle::text,'UTF8')),'hex') or pins->'privacy_complete' is distinct from 'true'::jsonb or
    pins->'excluded_topics' is distinct from '[]'::jsonb or pins->'paused_topics' is distinct from '[]'::jsonb then
   raise exception 'legacy snapshot changed or privacy provenance unavailable' using errcode='40001';end if;
 select count(*) into missing_sections from jsonb_array_elements(saved.bundle->'sections') current_section
   where not exists(select 1 from public.user_memoir_section_revision s where s.user_id=owner and s.project_id=p_project_id
     and s.locale=root.locale and s.data=current_section);
 if p_after is not null then
   select * into cursor_row from public.user_lifetime_legacy_draft_cursor where id=p_after and snapshot_id=root.id
     and kind=case when p_section_id is null then 'prose' else 'evidence' end
     and (p_section_id is null or section_id=p_section_id);
   if not found then raise exception 'legacy cursor scope mismatch' using errcode='22023';end if;
   boundary:=cursor_row.section_id;offset_chars:=cursor_row.char_offset;offset_refs:=cursor_row.ref_offset;
 end if;
 if p_section_id is not null then
   select s.* into section from public.user_memoir_section_revision s where s.user_id=owner and s.project_id=p_project_id and s.locale=root.locale and s.section_id=p_section_id
     and exists(select 1 from jsonb_array_elements(saved.bundle->'sections') current_section where current_section=s.data) order by s.revision desc limit 1;
   if not found or not public.lifetime_legacy_section_eligible(section) then raise exception 'legacy section provenance unavailable' using errcode='40001';end if;
   select coalesce(jsonb_agg(value order by ordinal),'[]') into refs from jsonb_array_elements(section.data->'source_refs') with ordinality r(value,ordinal)
     where ordinal>offset_refs and ordinal<=offset_refs+p_limit;
   has_more:=offset_refs+jsonb_array_length(refs)<jsonb_array_length(section.data->'source_refs');
   if has_more then insert into public.user_lifetime_legacy_draft_cursor(snapshot_id,section_id,ref_offset,kind)
     values(root.id,p_section_id,offset_refs+jsonb_array_length(refs),'evidence') returning id into next_cursor;end if;
   return jsonb_build_object('snapshot_id',root.id,'section_id',p_section_id,'source_refs',refs,'complete',not has_more,'next_cursor',next_cursor);
 end if;
 for section in select selected.* from (select distinct on(s.section_id) s.* from public.user_memoir_section_revision s
   where s.user_id=owner and s.project_id=p_project_id and s.locale=root.locale and s.section_id>=boundary
     and exists(select 1 from jsonb_array_elements(saved.bundle->'sections') current_section where current_section=s.data)
   order by s.section_id,s.revision desc) selected order by selected.section_id limit p_limit+1 loop
   if section.section_id<>boundary then offset_chars:=0;end if;
   if jsonb_array_length(records)>=p_limit then has_more:=true;next_section:=section.section_id;next_offset:=0;exit;end if;
   valid:=public.lifetime_legacy_section_eligible(section);
   total_chars:=length(coalesce(section.data->>'content',''));
   if not valid or total_chars=0 then
     records:=records||jsonb_build_array(jsonb_build_object('id',section.section_id,'preview',null,'original_withheld',true,
       'error','LIFETIME_LEGACY_PROVENANCE_REQUIRED','human_locked',saved.human_locked,'publication_approved',false));
   else
     while offset_chars<total_chars loop
       if jsonb_array_length(records)>=p_limit then has_more:=true;next_section:=section.section_id;next_offset:=offset_chars;exit;end if;
       part:=substring(section.data->>'content' from offset_chars+1 for 4000);
       -- Reference identities/spans only; the dedicated evidence page preserves
       -- every original reference without lifetime-sized nested lists.
       select coalesce(jsonb_agg(jsonb_build_object('source_id',value->'source_id','version',value->'version',
         'char_start',value->'char_start','char_end',value->'char_end') order by ordinal),'[]') into refs
         from jsonb_array_elements(section.data->'source_refs') with ordinality r(value,ordinal) where ordinal<=8;
       records:=records||jsonb_build_array(jsonb_build_object('id',section.section_id||':'||offset_chars,'section_id',section.section_id,
         'section_revision',section.revision,'char_start',offset_chars,'char_end',offset_chars+length(part),'original_length',total_chars,
         'preview',jsonb_build_object('title',left(coalesce(section.data->>'title',section.section_id),300),'text',part),
         'source_refs',refs,'source_refs_complete',jsonb_array_length(section.data->'source_refs')<=8,
         'human_locked',saved.human_locked,'publication_approved',false));
       offset_chars:=offset_chars+length(part);
     end loop;
     if has_more then exit;end if;
   end if;
 end loop;
 if has_more then insert into public.user_lifetime_legacy_draft_cursor(snapshot_id,section_id,char_offset)
   values(root.id,next_section,next_offset) returning id into next_cursor;end if;
 return jsonb_build_object('schema_version',1,'snapshot_id',root.id,'project_id',p_project_id,'locale',root.locale,
   'root_digest',root.bundle_digest,'revision',root.manuscript_revision,'legacy',true,'coverage_scope','legacy_saved_sections',
   'records',records,'complete',not has_more,'next_cursor',next_cursor,'publication_approved',false,
   'missing_provenance_sections',missing_sections,'coverage_complete',false);
end $$;
revoke all on function public.read_lifetime_legacy_draft_page(text,uuid,uuid,integer,text) from public,anon;
grant execute on function public.read_lifetime_legacy_draft_page(text,uuid,uuid,integer,text) to authenticated;

create function public.read_lifetime_legacy_draft_head(p_project_id text,p_locale text default null) returns jsonb
language plpgsql security definer set search_path='' as $$
declare owner uuid:=auth.uid();identity public.user_lifetime_conversation%rowtype;project public.user_memoir_project%rowtype;
 saved public.user_memoir_manuscript%rowtype;root public.user_lifetime_legacy_draft_snapshot%rowtype;pins jsonb;page jsonb;output_locale text;
begin
 if owner is null or (p_locale is not null and p_locale not in ('en-AU','zh-CN')) then raise exception 'invalid legacy edition' using errcode='22023';end if;
 select * into identity from public.user_lifetime_conversation where user_id=owner and project_id=p_project_id;
 if not found then raise exception 'canonical conversation unavailable' using errcode='42501';end if;
 select * into project from public.user_memoir_project where user_id=owner and project_id=p_project_id for share;
 perform 1 from public.user_profile where user_id=owner for share;
 select * into identity from public.user_lifetime_conversation where conversation_id=identity.conversation_id for share;
 pins:=public.read_lifetime_pinned(identity.conversation_id);output_locale:=coalesce(p_locale,pins->>'language','en-AU');
 select * into saved from public.user_memoir_manuscript where user_id=owner and project_id=p_project_id and locale=output_locale for share;
 if saved.revision is null or saved.eligible is not true or saved.bundle is null or jsonb_typeof(saved.bundle->'sections') is distinct from 'array' or
   jsonb_array_length(saved.bundle->'sections')=0 or pins->'privacy_complete' is distinct from 'true'::jsonb or
   pins->'excluded_topics' is distinct from '[]'::jsonb or pins->'paused_topics' is distinct from '[]'::jsonb then
   return jsonb_build_object('status','pending','preview',null,'locale',output_locale,'legacy',true,'original_withheld',true,
     'error','LIFETIME_LEGACY_PROVENANCE_REQUIRED','updating',false,'publication_approved',false,'retrieval_complete',false);
 end if;
 insert into public.user_lifetime_legacy_draft_snapshot(user_id,project_id,locale,conversation_id,manuscript_revision,bundle_digest,policy_epoch,preference_revision)
   values(owner,p_project_id,output_locale,identity.conversation_id,saved.revision,encode(sha256(convert_to(saved.bundle::text,'UTF8')),'hex'),project.policy_epoch,identity.preference_revision)
   on conflict(user_id,project_id,locale,manuscript_revision,bundle_digest,policy_epoch,preference_revision) do update set manuscript_revision=excluded.manuscript_revision returning * into root;
 page:=public.read_lifetime_legacy_draft_page(p_project_id,root.id,null,1);
 return jsonb_build_object('schema_version',1,'project_id',p_project_id,'locale',output_locale,'snapshot_id',root.id,'root_digest',root.bundle_digest,
   'revision',saved.revision,'coverage_round',saved.covered_round,'coverage_scope','legacy_saved_sections','legacy',true,
   'status',case when page->'records'->0->'preview' is not null and page->'records'->0->'preview'<>'null'::jsonb then 'ready' else 'pending' end,
   'preview',page->'records'->0->'preview','first_record',page->'records'->0,'original_withheld',(page->>'missing_provenance_sections')::bigint>0 or coalesce((page->'records'->0->>'original_withheld')::boolean,false),
   'page_complete',page->'complete','next_cursor',page->'next_cursor','retrieval_complete',false,'updating',false,
   'error',case when (page->>'missing_provenance_sections')::bigint>0 then to_jsonb('LIFETIME_LEGACY_PROVENANCE_REQUIRED'::text) else page->'records'->0->'error' end,'publication_approved',false);
end $$;
revoke all on function public.read_lifetime_legacy_draft_head(text,text) from public,anon;
grant execute on function public.read_lifetime_legacy_draft_head(text,text) to authenticated;
commit;
