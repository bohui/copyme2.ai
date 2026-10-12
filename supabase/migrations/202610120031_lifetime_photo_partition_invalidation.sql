-- Photo changes revoke their exact partition, never unrelated narrator prose.
-- Keep this additive repair usable after the earlier lifetime migrations.
begin;

-- The bounded composer partition key ends in the confirmed photo-link UUID;
-- source-only partitions end in an empty photo component. Index that existing
-- dependency without backfilling or rewriting historical evidence/prose.
create index lifetime_section_photo_dependency
 on public.user_lifetime_memoir_section(user_id,project_id,(right(partition_key,37)));

create or replace function public.invalidate_lifetime_lane_photo() returns trigger
language plpgsql security definer set search_path=public,auth as $$
begin
 if tg_op='INSERT' then return new;end if;
 if tg_op='UPDATE' and old is not distinct from new then return new;end if;
 -- Invalidate every saved copy/proposal that used the changed link, including
 -- protected copies of that dependency. Other photos and source-only prose
 -- keep their original bytes and approval flags.
 delete from public.user_lifetime_memoir_section
   where user_id=old.user_id and project_id=old.project_id and event_id=old.event_id
     and right(partition_key,37)=':'||old.id::text;
 return coalesce(new,old);
end $$;
revoke all on function public.invalidate_lifetime_lane_photo() from public,anon,authenticated;

commit;
