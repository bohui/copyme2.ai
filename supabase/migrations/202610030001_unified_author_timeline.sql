-- Keep events and periods in one author timeline without changing their IDs,
-- date expressions, people links, privacy, print settings, or source metadata.
-- The temporary helper exists only for this migration session.
create or replace function pg_temp.unify_author_timeline(p_document jsonb)
returns jsonb
language sql
immutable
as $$
  select (p_document - 'life_periods') || jsonb_build_object(
    'schema_version', 2,
    'timeline', coalesce((
      select jsonb_agg(entry order by
        coalesce(parts[1]::integer, 9999),
        coalesce(parts[2]::integer, case when parts is null then 12 else 7 end),
        coalesce(parts[3]::integer, case when parts is null then 31 else 1 end),
        ordinal
      )
      from (
        select value || jsonb_build_object('kind', coalesce(value->>'kind', 'event')) as entry,
               ordinality as ordinal
        from jsonb_array_elements(coalesce(p_document->'timeline', '[]'::jsonb)) with ordinality
        union all
        select value || jsonb_build_object('kind', 'period') as entry,
               ordinality + jsonb_array_length(coalesce(p_document->'timeline', '[]'::jsonb)) as ordinal
        from jsonb_array_elements(coalesce(p_document->'life_periods', '[]'::jsonb)) with ordinality
      ) entries
      cross join lateral (
        select regexp_match(
          coalesce(case when entry->>'kind' = 'period'
            then entry->>'start_expression' else entry->>'date_expression' end, ''),
          '(?<![0-9])([12][0-9]{3})(?:[-/]([0-9]{1,2})(?:[-/]([0-9]{1,2}))?)?(?![0-9])'
        ) as parts
      ) dates
    ), '[]'::jsonb)
  );
$$;

update public.user_family_context
set document = pg_temp.unify_author_timeline(document) || jsonb_build_object(
      'revision', revision + 1, 'updated_at', now()),
    revision = revision + 1,
    updated_at = now()
where document->'schema_version' is distinct from '2'::jsonb
   or document ? 'life_periods';
