-- Accept Chinese digit-by-digit years in the same way as Arabic years.
-- The application validator already supports forms such as 一九八八; the
-- database validator must recognize the original evidence too.
begin;

create or replace function public.validate_memory_temporal(p_owner uuid,p_project_id text,p_temporal jsonb) returns void
language plpgsql security definer set search_path='' as $$
declare basis jsonb; birth_basis jsonb; target_year integer; age_number integer; birth_match text[]; supported boolean;
begin
  if pg_catalog.jsonb_typeof(p_temporal) is distinct from 'object' or
     p_temporal->>'precision' is null or p_temporal->>'precision' not in ('unknown','day','month','year','range','approximate','age','season') or
     length(coalesce(p_temporal->>'expression','')) not between 1 and 500 then
    raise exception 'invalid temporal placement' using errcode='22023'; end if;
  if (p_temporal->>'year_start')::integer>(p_temporal->>'year_end')::integer then
    raise exception 'invalid temporal range' using errcode='22023'; end if;
  for basis in select value from pg_catalog.jsonb_array_elements(coalesce(p_temporal->'basis','[]')) loop
    perform public.validate_memory_evidence(p_owner,p_project_id,basis);
  end loop;
  for target_year in select (p_temporal->>'year_start')::integer union select (p_temporal->>'year_end')::integer loop
    if target_year is null then continue; end if;
    if target_year not between 1 and 9999 or p_temporal->>'precision'='unknown' then
      raise exception 'unsupported numeric date' using errcode='22023'; end if;
    supported:=false;
    if p_temporal->>'precision'='age' then
      for basis in select value from pg_catalog.jsonb_array_elements(coalesce(p_temporal->'basis','[]')) loop
        age_number:=public.memory_age_number(basis->>'quote');
        if age_number is not null then
          for birth_basis in select value from pg_catalog.jsonb_array_elements(p_temporal->'basis') loop
            if birth_basis->>'quote' ~* '(born|birth|出生|生于)' then
              birth_match:=coalesce(
                pg_catalog.regexp_match(birth_basis->>'quote','(?i)(?:\mi\M\s+(?:was\s+)?born\s+(?:in\s+)?|\mmy\s+(?:birth year|year of birth)\s+(?:was|is)?\s*)([0-9]{4})'),
                pg_catalog.regexp_match(birth_basis->>'quote','我(?:是|于|在)?([0-9]{4})年?(?:出生|生于)'),
                pg_catalog.regexp_match(birth_basis->>'quote','我(?:是)?(?:出生|生于)(?:于|在)?([0-9]{4})'));
              if birth_match is not null and birth_match[1]::integer+age_number=target_year then supported:=true; end if;
            end if;
          end loop;
        end if;
      end loop;
    else
      select exists(select 1 from pg_catalog.jsonb_array_elements(coalesce(p_temporal->'basis','[]')) b
        where b->>'quote' ~ ('(^|[^0-9])'||target_year::text||'([^0-9]|$)')
           or pg_catalog.strpos(b->>'quote',pg_catalog.translate(target_year::text,'0123456789','〇一二三四五六七八九'))>0
           or pg_catalog.strpos(b->>'quote',pg_catalog.replace(pg_catalog.translate(target_year::text,'0123456789','〇一二三四五六七八九'),'〇','零'))>0) into supported;
    end if;
    if not supported then raise exception 'numeric date requires supported original evidence' using errcode='22023'; end if;
  end loop;
  if p_temporal->>'expression'<>'unknown' and not exists
      (select 1 from pg_catalog.jsonb_array_elements(coalesce(p_temporal->'basis','[]')) b where pg_catalog.strpos(b->>'quote',p_temporal->>'expression')>0) then
    raise exception 'date expression requires its original evidence' using errcode='22023'; end if;
end $$;
revoke all on function public.validate_memory_temporal(uuid,text,jsonb) from public,anon,authenticated;
grant execute on function public.validate_memory_temporal(uuid,text,jsonb) to authenticated;

commit;
