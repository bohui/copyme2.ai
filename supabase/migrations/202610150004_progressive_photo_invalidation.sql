-- Progressive passage keys no longer encode photo-link UUIDs. Revoke the
-- rendered photo's exact source/asset dependency in originals and proposals.
begin;

create or replace function public.invalidate_lifetime_lane_photo() returns trigger
language plpgsql security definer set search_path=public,auth as $$
begin
 if tg_op='INSERT' then return new;end if;
 if tg_op='UPDATE' and old is not distinct from new then return new;end if;
 delete from public.user_lifetime_memoir_section section
  where section.user_id=old.user_id and section.project_id=old.project_id
   and (section.event_id=old.event_id or
     section.event_dependencies @> jsonb_build_array(jsonb_build_object('id',old.event_id)))
   and (right(section.partition_key,37)=':'||old.id::text or exists(
    select 1 from jsonb_path_query(jsonb_build_array(section.bundle,section.proposal),
      '$.** ? (@.type == "photo" && exists(@.asset_id))') photo,
      lateral jsonb_array_elements(coalesce(photo->'source_refs','[]'::jsonb)) ref
    where photo->>'asset_id'=old.photo_id
      and ref->>'source_id'=old.source_id::text
      and ref->>'version'=old.source_version::text));
 return coalesce(new,old);
end $$;

-- Existing trigger and function grants remain unchanged. No historical
-- originals, identities, round counters or permissions are rewritten.
commit;
