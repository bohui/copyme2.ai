begin;

-- One versioned, renderable Family/Timeline document per authenticated user
-- and legacy Memoir project. The project id is only a correlation key; RLS
-- keeps the document scoped to the Supabase user who owns it.
create table if not exists public.user_family_context (
  user_id uuid not null references auth.users(id) on delete cascade,
  project_id text not null check (char_length(project_id) between 1 and 128),
  document jsonb not null check (jsonb_typeof(document) = 'object'),
  revision bigint not null default 0 check (revision >= 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (user_id, project_id)
);

alter table public.user_family_context enable row level security;

drop policy if exists user_family_context_select_own on public.user_family_context;
create policy user_family_context_select_own
  on public.user_family_context for select
  to authenticated
  using (user_id = auth.uid());

drop policy if exists user_family_context_insert_own on public.user_family_context;
create policy user_family_context_insert_own
  on public.user_family_context for insert
  to authenticated
  with check (user_id = auth.uid());

drop policy if exists user_family_context_update_own on public.user_family_context;
create policy user_family_context_update_own
  on public.user_family_context for update
  to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

revoke all on table public.user_family_context from anon;
grant select, insert, update on table public.user_family_context to authenticated;
grant all on table public.user_family_context to service_role;

create or replace function public.upsert_user_family_context(
  p_project_id text,
  p_document jsonb,
  p_expected_revision bigint default null
)
returns jsonb
language plpgsql
security invoker
set search_path = public
as $$
declare
  current_row public.user_family_context%rowtype;
  next_revision bigint;
  next_document jsonb;
begin
  if auth.uid() is null then
    raise exception 'authenticated user required';
  end if;
  if p_project_id is null or char_length(p_project_id) < 1 or char_length(p_project_id) > 128 then
    raise exception 'invalid project id';
  end if;
  if p_document is null or jsonb_typeof(p_document) <> 'object' then
    raise exception 'family document must be a JSON object';
  end if;

  select * into current_row
    from public.user_family_context
   where user_id = auth.uid() and project_id = p_project_id
   for update;

  if found then
    if p_expected_revision is not null and current_row.revision <> p_expected_revision then
      raise exception 'family context revision conflict';
    end if;

    -- Ignore transport metadata when deciding whether a retry changed the
    -- canonical records. This makes a retried Codex turn idempotent.
    if (current_row.document - 'revision' - 'updated_at') = (p_document - 'revision' - 'updated_at') then
      return jsonb_build_object(
        'changed', false,
        'document', current_row.document,
        'revision', current_row.revision,
        'updated_at', current_row.updated_at
      );
    end if;

    next_revision := current_row.revision + 1;
    next_document := p_document || jsonb_build_object('revision', next_revision, 'updated_at', now());
    update public.user_family_context
       set document = next_document,
           revision = next_revision,
           updated_at = now()
     where user_id = auth.uid() and project_id = p_project_id;
  else
    if p_expected_revision is not null and p_expected_revision <> 0 then
      raise exception 'family context revision conflict';
    end if;
    next_revision := 1;
    next_document := p_document || jsonb_build_object('revision', next_revision, 'updated_at', now());
    insert into public.user_family_context(user_id, project_id, document, revision)
    values (auth.uid(), p_project_id, next_document, next_revision);
  end if;

  return jsonb_build_object(
    'changed', true,
    'document', next_document,
    'revision', next_revision,
    'updated_at', now()
  );
end;
$$;

revoke all on function public.upsert_user_family_context(text, jsonb, bigint) from public;
grant execute on function public.upsert_user_family_context(text, jsonb, bigint) to authenticated;
grant execute on function public.upsert_user_family_context(text, jsonb, bigint) to service_role;

commit;
