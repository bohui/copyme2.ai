# Database design

The application schema is defined by `supabase/migrations/202610180001_initial_schema.sql`.
It replaces the development migration history and requires a fresh database or an
explicit reset. There is no upgrade, import, or preservation path for old data.
Supabase owns the Auth and Storage schemas; the baseline adds the application
tables, RPCs, grants, Storage policies, buckets, and Auth triggers in one transaction.
Bucket creation also tolerates managed metadata retained by a remote Supabase reset.

## Names and ownership

Tables use singular `snake_case`. Private account data has the `user_` prefix;
shared reference data and server configuration do not. The shared photo cache is
`place_photo_search`, and paid account access is `story_entitlement`. Python
collection names remain plural where they hold multiple records.

`user_memoir_edition` stores revision, coverage, milestone, and human-lock metadata
for each owner/project/language. Draft content and proposed replacements live in
`user_lifetime_memoir_section` under a frozen lane snapshot. The former manuscript
table's duplicated `bundle`, `proposal`, `reuse`, and `eligible` columns are gone.

All 107 application tables enable RLS. Existing owner checks, restricted worker
RPCs, Storage access checks, and recording tombstones remain in place. Internal
function layers that implement active policy, provenance, replay, and publication
checks remain part of the runtime; only unreachable functions and legacy readers
and importers were removed.

The baseline clears inherited Supabase table/function grants for its own objects
before restoring their intended permissions. The PostgreSQL fixtures model the
configured database's broad default grants, so restricted tables and internal
helpers cannot accidentally become client-accessible on a fresh Supabase reset.

## Removed storage

| Removed table | Replacement or reason |
| --- | --- |
| `user_conversation_phase_archive` | Retired user-selected conversation phases; the AI strategy is authoritative. |
| `user_lifetime_legacy_draft_snapshot` | Canonical lane snapshots identify saved drafts. |
| `user_lifetime_legacy_draft_cursor` | Canonical draft cursors page through those snapshots. |
| `user_memoir_section_revision` | Canonical memoir sections retain the current and proposed text. |
| `user_memory_event_alias` | Only historical imports created legacy event aliases. |
| `user_narrator_source_alias` | Fresh narrator sources link directly to client turn IDs. |

The family document, conversation memories, completed rounds, and memoir milestones
remain: current family views, guest transfers, recall charging, and composition
still use them. A historical-looking name alone does not make a table disposable.

## Access paths

Every foreign key has a usable, nonpartial B-tree index on the referencing columns
or an existing index with those columns as its leading keys. This adds 43 indexes
for cascade deletes and joins without adding redundant indexes to already-covered
keys. Ordinary index names use their table and indexed columns with an `_idx`
suffix; uniqueness is expressed by `_key` or `_pkey`.

Three additional indexes cover the application's current reads:

- Conversation history: `(user_id, project_id, created_at DESC, id DESC)` supports
  the existing keyset boundary and stable page order.
- Undelivered receipts: `(created_at, id) WHERE NOT delivered` keeps polling
  independent of retained delivered receipts.
- Runnable lanes: `(available_at, id) WHERE attempts < 3 AND (pending OR token IS
  NOT NULL)` narrows the worker's ordered search to queued and leased work.

These are access-path improvements, not a measured production throughput claim.
Further tuning should follow real query plans and workloads once they exist.

## Development and verification

Reset the disposable database explicitly after adopting this baseline:

```sh
supabase db reset --db-url "$SUPABASE_DB_URL" --yes
```

`make migrate` retains its existing tracked `supabase db push` command. Tests load
the same baseline into task-owned PostgreSQL clusters. Coverage includes atomic
schema rollback, Supabase CLI parsing and migration tracking, removed objects,
foreign-key index coverage, owner isolation, representative query plans, and the
canonical conversation and composition workflows. No test requires resetting the
configured Supabase database.
