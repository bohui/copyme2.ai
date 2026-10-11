-- Locale belongs to the authenticated account. Keeping it outside Auth metadata
-- avoids updateUser's read/merge/write race and never rewrites unrelated data.
begin;

create table public.user_ui_locale_preference (
  user_id uuid primary key references auth.users(id) on delete cascade,
  locale text not null check (locale in ('en-AU', 'zh-CN')),
  source text not null check (source in ('manual', 'first_reply')),
  revision bigint not null default 1 check (revision > 0)
);

alter table public.user_ui_locale_preference enable row level security;
create policy user_ui_locale_preference_own_read
  on public.user_ui_locale_preference for select to authenticated
  using (user_id = (select auth.uid()));

-- Writes only pass through the own-user RPC so a client cannot bypass
-- first-reply immutability, provenance promotion or revision ordering.
revoke all on public.user_ui_locale_preference from public, anon, authenticated;
grant select on public.user_ui_locale_preference to authenticated;

create function public.read_ui_locale_preference(p_expected_viewer uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare
  v_owner uuid := auth.uid();
  v_preference public.user_ui_locale_preference%rowtype;
  v_legacy text;
begin
  if v_owner is null or p_expected_viewer is null or v_owner <> p_expected_viewer then
    raise exception 'authenticated user required' using errcode = '42501';
  end if;
  select u.raw_user_meta_data->>'ui_locale' into v_legacy
    from auth.users u where u.id = v_owner;
  if not found then
    raise exception 'authenticated user required' using errcode = '42501';
  end if;
  select * into v_preference from public.user_ui_locale_preference
    where user_id = v_owner;
  if found then
    return jsonb_build_object('locale', v_preference.locale,
      'source', v_preference.source, 'revision', v_preference.revision);
  end if;
  -- Source-less legacy preferences are established choices. An inference must
  -- never silently replace one. Revision 0 denotes this read-only fallback.
  if v_legacy in ('en-AU', 'zh-CN') then
    return jsonb_build_object('locale', v_legacy, 'source', 'manual', 'revision', 0);
  end if;
  return 'null'::jsonb;
end;
$$;

create function public.set_ui_locale_preference(p_locale text, p_source text, p_expected_viewer uuid)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  v_owner uuid := auth.uid();
  v_preference public.user_ui_locale_preference%rowtype;
  v_legacy text;
begin
  if v_owner is null or p_expected_viewer is null or v_owner <> p_expected_viewer then
    raise exception 'authenticated user required' using errcode = '42501';
  end if;
  if p_locale is null or p_locale not in ('en-AU', 'zh-CN') or
     p_source is null or p_source not in ('manual', 'first_reply') then
    raise exception 'invalid UI locale preference' using errcode = '22023';
  end if;

  -- The account row exists even before the first preference. Locking it makes
  -- competing initializations and legacy fallback atomic, without a caller
  -- owner target or advisory-lock collisions. The expected viewer is only
  -- an equality guard against a client session changing before RPC dispatch. Every writer locks this row
  -- first, including manual choices; authenticated anonymous users also have
  -- an auth.users row and use exactly the same path.
  select u.raw_user_meta_data->>'ui_locale' into v_legacy
    from auth.users u where u.id = v_owner for update;
  if not found then
    raise exception 'authenticated user required' using errcode = '42501';
  end if;

  select * into v_preference from public.user_ui_locale_preference
    where user_id = v_owner;
  if found then
    -- All detections after the first established preference are no-ops, even
    -- when their locale differs. A manual choice always has priority.
    if p_source = 'manual' and
       (v_preference.locale is distinct from p_locale or v_preference.source <> 'manual') then
      update public.user_ui_locale_preference
        set locale = p_locale, source = 'manual', revision = revision + 1
        where user_id = v_owner returning * into v_preference;
    end if;
  else
    -- Materialize valid legacy preferences as manual before considering an
    -- inference; explicit UI choices are free to replace the legacy value.
    insert into public.user_ui_locale_preference(user_id, locale, source)
      values (v_owner,
        case when p_source = 'first_reply' and v_legacy in ('en-AU', 'zh-CN')
          then v_legacy else p_locale end,
        case when p_source = 'first_reply' and v_legacy in ('en-AU', 'zh-CN')
          then 'manual' else p_source end)
      returning * into v_preference;
  end if;
  -- Return the effective record, including a winning manual choice, rather
  -- than echoing a detection request that lost the race.
  return jsonb_build_object('locale', v_preference.locale,
    'source', v_preference.source, 'revision', v_preference.revision);
end;
$$;

revoke all on function public.read_ui_locale_preference(uuid) from public, anon, authenticated;
revoke all on function public.set_ui_locale_preference(text, text, uuid) from public, anon, authenticated;
grant execute on function public.read_ui_locale_preference(uuid) to authenticated;
grant execute on function public.set_ui_locale_preference(text, text, uuid) to authenticated;

commit;
