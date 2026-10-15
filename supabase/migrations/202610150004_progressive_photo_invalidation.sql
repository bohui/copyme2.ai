-- Stored composer images use the schema's image block type. The canonical
-- producer currently declares no image assets; this repairs validated stored
-- bundle/proposal cleanup without enabling image admission or an asset mapping.
begin;

create or replace function public.invalidate_lifetime_lane_photo() returns trigger
language plpgsql security definer set search_path=public,auth as $$
declare section public.user_lifetime_memoir_section%rowtype; original_text text;
 original_depends boolean; proposal_depends boolean;
begin
 if tg_op='INSERT' then return new;end if;
 if tg_op='UPDATE' and old is not distinct from new then return new;end if;
 select text into original_text from public.user_narrator_source where user_id=old.user_id
  and project_id=old.project_id and id=old.source_id and version=old.source_version;
 for section in select s.* from public.user_lifetime_memoir_section s
  where s.user_id=old.user_id and s.project_id=old.project_id
   and (s.event_id=old.event_id or s.event_dependencies @> jsonb_build_array(jsonb_build_object('id',old.event_id)))
   and ((s.partition_key not like 'progressive:%' and right(s.partition_key,37)=':'||old.id::text)
    or (old.status='confirmed' and old.provenance='narrator_metadata' and
     jsonb_path_exists(jsonb_build_array(s.bundle,s.proposal),
      '$.** ? (@.type == "image" && @.asset_id == $asset)',jsonb_build_object('asset',old.photo_id))))
  for update loop
  if section.partition_key not like 'progressive:%' and right(section.partition_key,37)=':'||old.id::text then
   delete from public.user_lifetime_memoir_section where user_id=section.user_id and project_id=section.project_id
    and locale=section.locale and partition_key=section.partition_key and snapshot_id=section.snapshot_id;
   continue;
  end if;
  select coalesce(bool_or(kind='original'),false),coalesce(bool_or(kind='proposal'),false)
   into original_depends,proposal_depends
   from (values ('original',section.bundle),('proposal',section.proposal)) bodies(kind,body),
    lateral jsonb_path_query(body,'$.** ? (@.type == "image" && exists(@.asset_id))') image,
    lateral jsonb_array_elements(coalesce(image->'source_refs','[]'::jsonb)) ref
   where image->>'asset_id'=old.photo_id and ref->>'source_id'=old.source_id::text
    and ref->>'version'=old.source_version::text
    and strpos(substring(original_text from (ref->>'char_start')::integer+1
      for (ref->>'char_end')::integer-(ref->>'char_start')::integer),old.quote)>0;
  if original_depends then
   delete from public.user_lifetime_memoir_section where user_id=section.user_id and project_id=section.project_id
    and locale=section.locale and partition_key=section.partition_key and snapshot_id=section.snapshot_id;
  elsif proposal_depends then
   -- A proposal-only image cannot revoke the independently eligible original.
   update public.user_lifetime_memoir_section set proposal=null where user_id=section.user_id and project_id=section.project_id
    and locale=section.locale and partition_key=section.partition_key and snapshot_id=section.snapshot_id;
  end if;
 end loop;
 return coalesce(new,old);
end $$;

-- Retain all existing ownership, root, policy and evidence checks. A protected
-- current-row bundle with no remaining proposal is its original, not a new
-- unapproved candidate merely because another row keeps the root proposed.
create or replace function public.read_lifetime_private_draft_page(p_project_id text,p_snapshot_id uuid,p_after text default null,p_limit integer default 8)
returns jsonb language plpgsql security definer set search_path=public,auth as $$
declare owner uuid:=auth.uid(); identity public.user_lifetime_conversation%rowtype; project public.user_memoir_project%rowtype;
 root public.user_lifetime_lane_snapshot%rowtype; records jsonb; has_more boolean; next_key text; after_key text:=''; next_cursor uuid;
begin
 if owner is null or p_limit is null or p_limit not between 1 and 8 or length(coalesce(p_after,''))>512 then raise exception 'invalid memoir page';end if;
 select * into identity from public.user_lifetime_conversation where user_id=owner and project_id=p_project_id;
 if not found then raise exception 'canonical conversation unavailable';end if;
 select * into project from public.user_memoir_project where user_id=owner and project_id=p_project_id for share;
 perform 1 from public.user_profile where user_id=owner for share;
 select * into identity from public.user_lifetime_conversation where conversation_id=identity.conversation_id for share;
 select s.* into root from public.user_lifetime_lane_snapshot s join public.user_memoir_lane l on l.id=s.lane_id
   where s.id=p_snapshot_id and s.user_id=owner and s.project_id=p_project_id and s.conversation_id=identity.conversation_id
     and s.state in ('completed','proposed') and l.skill='composer' and s.policy_epoch=project.policy_epoch and s.preference_revision=identity.preference_revision;
 if not found then raise exception 'stale memoir root' using errcode='PT409';end if;
 if p_after is not null then
   select last_partition into after_key from public.user_lifetime_memoir_cursor where id=p_after::uuid
     and snapshot_id=root.id and user_id=owner and project_id=p_project_id and root_digest=root.root_digest;
   if not found then raise exception 'memoir page cursor scope mismatch';end if;
 end if;
 select coalesce(jsonb_agg(item order by partition_key),'[]') into records from (
   select s.partition_key,jsonb_build_object('id',s.partition_key,'event_id',s.event_id,'event_revision',s.event_revision,
     'source_refs',coalesce(s.bundle->'source_refs',jsonb_build_array(jsonb_build_object('source_id',s.source_id,'version',s.source_version,'char_start',s.char_start,'char_end',s.char_end))),
     'preview',case when root.state='proposed' and s.snapshot_id=root.id and s.proposal is null and not(s.approved or s.human_locked) then null else s.bundle->'preview' end,
     'proposed_preview',case when root.state='proposed' and s.snapshot_id=root.id and s.proposal is null and not(s.approved or s.human_locked) then s.bundle->'preview' else s.proposal->'preview' end,
     'proposal_digest',case when s.proposal is not null then encode(sha256(convert_to(s.proposal::text,'UTF8')),'hex') else null end,
     'original_withheld',s.proposal is not null and not(s.bundle ? 'preview'),'approval_required',root.state='proposed',
     'approved',s.approved,'human_locked',s.human_locked) item
   from public.user_lifetime_memoir_section s join public.user_lifetime_lane_snapshot ss on ss.id=s.snapshot_id
     join public.user_memory_event e on e.user_id=s.user_id and e.project_id=s.project_id and e.id=s.event_id and e.revision=s.event_revision and e.status='active'
     join public.user_narrator_source n on n.user_id=s.user_id and n.project_id=s.project_id and n.id=s.source_id and n.version=s.source_version and n.status='active'
   where s.user_id=owner and s.project_id=p_project_id and s.locale=root.locale and s.partition_key>after_key and not s.retired
     and not exists(select 1 from jsonb_array_elements(s.source_dependencies) dependency where not exists(
       select 1 from public.user_narrator_source original where original.user_id=s.user_id and original.project_id=s.project_id
        and original.id::text=dependency->>'id' and original.version::text=dependency->>'version' and original.status='active'))
     and not exists(select 1 from jsonb_array_elements(s.event_dependencies) dependency where not exists(
       select 1 from public.user_memory_event original where original.user_id=s.user_id and original.project_id=s.project_id
        and original.id=dependency->>'id' and original.revision::text=dependency->>'revision' and original.status='active'))
     and (ss.state='completed' or ss.id=root.id and ss.state='proposed') and ss.preference_revision=root.preference_revision and ss.policy_epoch=root.policy_epoch and ss.created_at<=root.created_at
     and not exists(select 1 from public.user_lifetime_memoir_section newer join public.user_lifetime_lane_snapshot ns on ns.id=newer.snapshot_id
       where newer.user_id=s.user_id and newer.project_id=s.project_id and newer.locale=s.locale and newer.partition_key=s.partition_key
         and (ns.state='completed' or ns.id=root.id and ns.state='proposed') and ns.created_at>ss.created_at and ns.created_at<=root.created_at)
   order by s.partition_key limit p_limit+1) selected;
 has_more:=jsonb_array_length(records)>p_limit;
 if has_more then
   records:=records-p_limit;next_key:=records->-1->>'id';
   insert into public.user_lifetime_memoir_cursor(snapshot_id,user_id,project_id,last_partition,root_digest) values(root.id,owner,p_project_id,next_key,root.root_digest)
     on conflict(snapshot_id,last_partition,root_digest) do update set last_partition=excluded.last_partition returning id into next_cursor;
 end if;
 return jsonb_build_object('schema_version',1,'owner_id',owner,'conversation_id',identity.conversation_id,'project_id',p_project_id,
   'snapshot_id',root.id,'root_digest',root.root_digest,'locale',root.locale,'source_revision',root.source_high_water,'event_revision',root.event_high_water,
   'policy_epoch',root.policy_epoch,'preference_revision',root.preference_revision,'snapshot_complete',true,
   'snapshot_state',root.state,'approval_required',root.state='proposed',
   'records',records,'complete',not has_more,'next_cursor',next_cursor,'publication_approved',false);
end $$;

-- CREATE OR REPLACE preserves existing function privileges and triggers.
commit;
