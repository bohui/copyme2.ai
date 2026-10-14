-- Geographic recall cues remain dependent on their original narrator version.
begin;

create table public.user_lifetime_place_journey (
 user_id uuid not null,
 project_id text not null,
 source_id uuid not null,
 source_version bigint not null,
 journeys jsonb not null check(jsonb_typeof(journeys)='array' and jsonb_array_length(journeys)<=8
   and octet_length(journeys::text)<=8192),
 primary key(user_id,project_id,source_id),
 foreign key(user_id,project_id,source_id) references public.user_narrator_source(user_id,project_id,id) on delete cascade
);
alter table public.user_lifetime_place_journey enable row level security;
revoke all on public.user_lifetime_place_journey from public,anon,authenticated;

create function public.persist_lifetime_place_journeys(p_fence jsonb,p_source_id uuid,p_source_version bigint,p_journeys jsonb)
returns void language plpgsql security definer set search_path='' as $$
declare owner uuid:=auth.uid(); project text:=p_fence->'identity'->>'project_id';
 source public.user_narrator_source%rowtype; journey jsonb;
begin
 perform public.lock_lifetime_publication(p_fence);
 select * into source from public.user_narrator_source
   where user_id=owner and project_id=project and id=p_source_id and version=p_source_version and status='active';
 if not found then raise exception 'current narrator source required' using errcode='40001'; end if;
 if jsonb_typeof(p_journeys) is distinct from 'array' or jsonb_array_length(p_journeys)>8
   or octet_length(p_journeys::text)>8192 then raise exception 'bounded place journeys required' using errcode='22023'; end if;
 for journey in select * from jsonb_array_elements(p_journeys) loop
   if jsonb_typeof(journey) is distinct from 'object'
     or exists(select 1 from jsonb_object_keys(journey) k where k not in ('schema_version','place','hierarchy','granularity','duration_ms','latitude','longitude'))
     or journey->'schema_version' is distinct from '1'::jsonb
     or jsonb_typeof(journey->'place') is distinct from 'string'
     or length(journey->>'place') not between 1 and 120
     or strpos(lower(source.text),lower(journey->>'place'))=0
     or jsonb_typeof(journey->'hierarchy') is distinct from 'array'
     or jsonb_array_length(journey->'hierarchy') not between 2 and 6
     or journey->'hierarchy'->>0 is distinct from 'Earth'
     or journey->'hierarchy'->>-1 is distinct from journey->>'place'
     or exists(select 1 from jsonb_array_elements(journey->'hierarchy') label
       where jsonb_typeof(label) is distinct from 'string' or length(label#>>'{}') not between 1 and 120)
     or coalesce(journey->>'granularity','') not in ('country','region','city','suburb')
     then raise exception 'grounded coarse place journey required' using errcode='22023'; end if;
   if (journey ? 'latitude') is distinct from (journey ? 'longitude')
     or (journey ? 'latitude' and (jsonb_typeof(journey->'latitude') is distinct from 'number'
       or jsonb_typeof(journey->'longitude') is distinct from 'number'
       or (journey->>'latitude')::numeric not between -90 and 90
       or (journey->>'longitude')::numeric not between -180 and 180))
     then raise exception 'valid public place centre required' using errcode='22023'; end if;
 end loop;
 insert into public.user_lifetime_place_journey values(owner,project,p_source_id,p_source_version,p_journeys)
 on conflict(user_id,project_id,source_id) do update set source_version=excluded.source_version,journeys=excluded.journeys;
end $$;

create function public.read_lifetime_place_journeys(p_project_id text,p_source_id uuid default null)
returns jsonb language plpgsql security definer set search_path='' as $$
declare owner uuid:=auth.uid(); result jsonb;
begin
 if not exists(select 1 from public.user_lifetime_conversation where user_id=owner and project_id=p_project_id)
   then raise exception 'canonical conversation required'; end if;
 perform 1 from public.user_memoir_project where user_id=owner and project_id=p_project_id for share;
 select coalesce(jsonb_agg(journey||jsonb_build_object('source_sequence',sequence,
   'status','active','revision',version,'updated_at',created_at) order by sequence,ordinal),'[]') into result
 from (
   select distinct on (journey->'hierarchy',journey->>'granularity') journey,s.sequence,s.version,s.created_at,ordinal
   from public.user_lifetime_place_journey p join public.user_narrator_source s
     on s.user_id=p.user_id and s.project_id=p.project_id and s.id=p.source_id
       and s.version=p.source_version and s.status='active'
   cross join lateral jsonb_array_elements(p.journeys) with ordinality as items(journey,ordinal)
   where p.user_id=owner and p.project_id=p_project_id and (p_source_id is null or p.source_id=p_source_id)
   order by journey->'hierarchy',journey->>'granularity',s.sequence desc,ordinal
   limit 1000
 ) places;
 return result;
end $$;

revoke all on function public.persist_lifetime_place_journeys(jsonb,uuid,bigint,jsonb),
 public.read_lifetime_place_journeys(text,uuid) from public,anon,authenticated;
grant execute on function public.persist_lifetime_place_journeys(jsonb,uuid,bigint,jsonb),
 public.read_lifetime_place_journeys(text,uuid) to authenticated;
notify pgrst, 'reload schema';
commit;
