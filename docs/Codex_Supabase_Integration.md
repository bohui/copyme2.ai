# Codex and Supabase integration status

## Verified

- Supabase session-pooler connection succeeded. Both migrations in
  `supabase/migrations/` were applied to the requested project.
- `user_profile`, `user_memory`, and `user_agent_session` use authenticated-user
  ownership policies.
- The private `memory-spark` bucket uses the first path component as owner UUID.
  A live test confirmed owner access and denied cross-user memory and attachment
  access; temporary users and files were removed.
- The local `llm_provider` route accepts the project-scoped key stored only in the
  gitignored `.env` and returns successful `deepseek-v4-flash` Responses calls.
- Codex 0.156.1 app-server initialized inside the API image, created a thread,
  completed a real turn through `llm_provider`, and resumed the same thread on a
  second turn.
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

The adapter verifies the user with Supabase Auth, derives paths from that UUID,
and forwards the user's JWT for every storage and PostgREST operation. It never
uses the secret key for user operations. It excludes auth/config files, hidden
files, absolute paths and traversal paths from agent artifact uploads.

## Codex memory findings

Reviewed upstream commit `0a2eb4696c26ac33204bcd255721ab30220a4774` and the installed
0.156.1 generated app-server schema. Upstream may differ from the installed CLI.

Codex memory extraction selects eligible idle rollouts, produces per-thread
memory in its state database, then consolidates filesystem artifacts. It does
not generate a new memory file for every turn. That Codex app-server state
database is separate from Memory Spark's domain database: Memory Spark's
projects, sessions, answers, memories, chapters, jobs and outbox use
`SUPABASE_DB_URL`, while the per-user Codex runtime keeps its own local state
needed for memory jobs, leases and thread metadata. Synchronizing only Markdown
files is not a complete backup of Codex state.

Sources:
- https://github.com/openai/codex/blob/0a2eb4696c26ac33204bcd255721ab30220a4774/codex-rs/memories/README.md
- https://developers.openai.com/codex/app-server
- https://supabase.com/docs/guides/storage/security/access-control

## Implemented boundaries

- `apps/api/codex_agent.py`: app-server initialization, requests, turns and provider
  configuration. Callers must supply an isolated user runtime; CODEX_HOME alone
  is not an OS security boundary.
- `apps/api/agent_storage.py`: verified-user profile/memory operations, attachment
  uploads and Codex session/memory artifact upload/download.
- `apps/api/codex_runtime.py`: per-user Codex homes, thread resume, private-memory
  prompt context, allowlisted artifact synchronization, and a high-level loop
  trace for the UI.
- `/v1/user/profile`, `/v1/user/memories`, `/v1/user/attachments`: Supabase bearer
  token endpoints, separate from the prototype's demo account identities.
- `/v1/agent/config`, `/v1/agent/turn`: browser configuration and authenticated
  Codex turns.
- `SUPABASE_DB_URL`: canonical PostgreSQL connection for Memory Spark projects,
  sessions, answers, memories, chapters, jobs and the durable outbox. It may
  point to local Supabase or a hosted Supabase project. The production runtime
  does not fall back to the JSON store or a local PostgreSQL container.

## Deliberate prototype limits

- The browser stores the Supabase access and refresh tokens in session storage for
  this prototype; production should use a reviewed refresh and logout flow.
- Only Codex filesystem artifacts below `sessions`, `archived_sessions`, and
  `memories` are copied to Storage. Codex SQLite state, auth, configuration, and
  plugin files stay in the per-user container home; live SQLite/WAL files are not
  uploaded naively.
- The current memoir agent has no external tools and uses the deterministic
  chapter/session APIs for the rest of the prototype journey. The browser shows
  a simulated Codex loop for those calls, while connected turns show the
  allowlisted Codex adapter trace. Both traces expose action summaries and tool
  results, never hidden model reasoning.

The browser uses the connected Codex path after Supabase sign-in. The deterministic
journey is available only as an explicit test-mode fallback; production still
uses Supabase Postgres for all Memory Spark domain state.
