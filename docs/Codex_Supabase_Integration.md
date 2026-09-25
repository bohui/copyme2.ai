# Codex and Supabase integration status

## Verified

- Supabase session-pooler connection succeeded. The checked-in user-data,
  agent-session, turn-lease, and entitlement migrations were applied to the
  requested project.
- `user_profile`, `user_memory`, and `user_agent_session` use authenticated-user
  ownership policies.
- The private `memory-spark` bucket uses the first path component as owner UUID.
  A live test confirmed owner access and denied cross-user memory and attachment
  access; temporary users and files were removed.
- The local `llm_provider` route accepts the project-scoped key stored only in the
  gitignored `.env` and returns successful `deepseek-v4-flash` Responses calls.
- Before the isolation upgrade, Codex 0.156.1 created a thread, completed a real
  turn through `llm_provider`, and resumed the same thread on a second turn.
  Those live-model results do not verify the new worker deployment.
- The authenticated API journey returned two replies, persisted two `agent`
  memory rows, synchronized Codex artifacts, and created an attachment with the
  requested owner path shape.
- The browser journey signed in through Supabase, sent the first profile answer
  through `/v1/agent/turn`, rendered the Codex reply, and passed the existing
  conversation and workspace smoke test.

## Storage layout

```text
memory-spark/                         # private bucket
  <auth.users.id>/
    attachment/<filename>_<UTC timestamp>.<extension>
    agent/
      sessions/<Codex relative rollout path>
      archived_sessions/<Codex relative rollout path>
      memories/
        raw_memories.md
        rollout_summaries/...
        MEMORY.md
        memory_summary.md
        skills/...
```

The paths above describe legacy objects. New turn snapshots insert
`turns/<lease UUID>/` immediately below `sessions`, `archived_sessions`, or
`memories`. Uploads are immutable, and the fenced database commit publishes
the snapshot paths with the memory and session in one transaction. Interrupted
uploads may leave private, unreferenced objects; cleanup is an operational task.

The adapter verifies the user with Supabase Auth, derives paths from that UUID,
and forwards the user's JWT for every storage and PostgREST operation. It never
uses the secret key for user operations. It excludes auth/config files, hidden
files, absolute paths and traversal paths from agent artifact uploads.

## Codex memory findings

Reviewed upstream commit `0a2eb4696c26ac33204bcd255721ab30220a4774` and the installed
0.156.1 generated app-server schema. Upstream may differ from the installed CLI.

Codex memory extraction selects eligible idle rollouts, produces per-thread
memory in its state database, then consolidates filesystem artifacts. It does
not generate a new memory file for every turn. The Codex app-server state
database is separate from the product's RLS data plane: the story flow uses the
authenticated user's `user_profile` and `user_memory` rows, while the per-user
Codex runtime keeps its own local state needed for memory jobs, leases and
thread metadata. Synchronizing only Markdown files is not a complete backup of
Codex state.

Sources:
- https://github.com/openai/codex/blob/0a2eb4696c26ac33204bcd255721ab30220a4774/codex-rs/memories/README.md
- https://developers.openai.com/codex/app-server
- https://supabase.com/docs/guides/storage/security/access-control

## Implemented boundaries

- `apps/api/codex_agent.py`: app-server initialization, requests, turns and provider
  configuration. It is used by the private worker, not by the public API image.
- `apps/api/agent_storage.py`: verified-user profile/memory operations, attachment
  uploads and Codex session/memory artifact upload/download.
- `apps/api/codex_runtime.py`: private-worker dispatch, per-user thread resume,
  private-memory prompt context, allowlisted artifact synchronization, and a
  high-level loop trace for the UI.
- `apps/api/agent_lock.py`: renewable Supabase-backed user turn leases. The lease
  is the cross-replica serialization mechanism; the local asyncio lock is only
  an in-process optimization. Heartbeat loss cancels the turn; in-flight storage
  IO settles before lease release. `commit_user_agent_turn` validates the lease
  under a row lock before saving both session and memory atomically.
- `apps/api/codex_worker_service.py`: private worker endpoint and per-user OS UID
  allocation for Codex subprocesses.
- `apps/api/codex_worker_files.py`: no-follow config replacement and atomic,
  non-destructive import of offline legacy homes. Worker replicas using the
  same user state must share the worker volume; filesystem locks serialize
  execution and UID allocation across processes.
- `/v1/user/profile`, `/v1/user/memories`, `/v1/user/attachments`: Supabase bearer
  token endpoints, separate from the prototype's demo account identities.
- `/v1/agent/config`, `/v1/agent/turn`: browser configuration and authenticated
  Codex turns.
- The Memoir story flow no longer uses `SUPABASE_DB_URL` or a singleton JSONB
  state/outbox adapter. User-owned story and agent records use Supabase RLS;
  the legacy project routes use an explicit local adapter during the prototype
  transition.

## Deliberate prototype limits

- The browser stores the Supabase access and refresh tokens in session storage for
  this prototype; production should use a reviewed refresh and logout flow.
- Only Codex filesystem artifacts below `sessions`, `archived_sessions`, and
  `memories` are copied to Storage. Codex SQLite state, auth, configuration, and
  plugin files stay in the private worker's per-user home; live SQLite/WAL files
  are not uploaded naively. Compose requests a read-only worker root and a
  limited capability set, but Mocker currently ignores those flags. Production
  requires a runtime that honors them. Codex subprocesses use distinct UIDs;
  the supervisor needs `CAP_KILL` to terminate and reap them.
- The API-to-worker network is private and authenticated with
  `MEMORY_SPARK_CODEX_WORKER_SECRET`; the worker has no public host port.
- The current memoir agent has no external tools and uses the deterministic
  chapter/session APIs for the rest of the prototype journey. The browser shows
  a simulated Codex loop for those calls, while connected turns show the
  allowlisted Codex adapter trace. Both traces expose action summaries and tool
  results, never hidden model reasoning.

## Isolation upgrade rollout

Apply `202609250004_fenced_agent_turn_commit.sql` before deploying the updated
API. This migration was verified against a disposable local PostgreSQL instance;
it has **not** been applied to the hosted project as part of this upgrade.
Drain/stop all old API writers before importing legacy homes: a read-only mount
does not make a concurrently changing SQLite/WAL pair a consistent snapshot.
Imports preserve the original home and never replace an existing worker home.
Do not remove the legacy mount until all returning users have migrated.

`scripts/verify_codex_worker_isolation.py` exercises a complete start/resume and
cleanup cycle using a deterministic app-server double under the exact Linux
capability set, plus sibling-read denial and symlink protection. This is an
offline OS-boundary test, not evidence of a new live-model or browser journey.

The browser starts with Supabase anonymous auth, asks five story rounds, then
requires linking Google or Facebook before claiming one free chapter. Full
memoir generation returns `PAYMENT_REQUIRED` until a payment entitlement is
granted by the server-side payment integration. The Supabase project must have
**Allow manual linking** and **Allow anonymous sign-ins** enabled, with the
Google and Facebook providers configured; these are Auth project settings, not
database/RLS settings.
