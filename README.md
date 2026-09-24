# CopyMe2

CopyMe2 is the platform umbrella: **preserve the parts of you that matter**. The first live product is Memoir, a guided, source-linked memoir journey that turns memories, photographs, and the storyteller's own voice into a family book.

## Product URLs

The public URL structure is product-scoped so future products can live beside Memoir:

```text
copyme2.ai/
├── memoir/                  # live Memoir product
│   ├── start
│   ├── my-story
│   ├── interview/:sessionId
│   ├── memories/:id
│   ├── diary
│   ├── photos
│   ├── people
│   ├── timeline
│   ├── chapters/:id
│   ├── preview
│   ├── package
│   ├── checkout
│   ├── book
│   ├── print
│   ├── settings
│   └── family/{people,review}
└── voice/                   # reserved for a future product
```

The browser prototype serves the platform landing page at `/`, the Memoir entry page at `/memoir`, and the interview/workspace shell from the Memoir routes. Direct links are handled by the web shell so the route shape is ready for a future framework-backed frontend.

## Repository layout

```text
apps/
├── api/                    # FastAPI application and adapters
│   ├── main.py             # Memoir HTTP interface
│   ├── store.py            # Project, session, memory, chapter, and edition state
│   └── namespaces.py       # /api/v1/memoir compatibility seam
└── web/
    ├── app/
    │   ├── routes.js       # platform and Memoir route catalog
    │   └── memoir/client.js # current vanilla SPA implementation
    └── public/             # deployable HTML and CSS shell
docs/                       # product specification and implementation notes
supabase/                   # database migrations
tests/                      # API, workflow, persistence, and browser checks
```

Domain entities remain product-neutral (`Project`, `MemorySession`, `Memory`, `Chapter`, and `Edition`). The URL namespace is the product seam; it does not leak `/memoir` into database names.

## API namespace

Memoir's canonical API is:

```text
/api/v1/memoir/projects
/api/v1/memoir/memory-sessions
/api/v1/memoir/memories
/api/v1/memoir/people
/api/v1/memoir/chapters
/api/v1/memoir/editions
```

The existing `/v1/...` interface remains as a backwards-compatible adapter for the current specification tests and older clients. Both paths use the same implementation and domain store.

## Run locally

The production-shaped runtime uses Supabase Postgres as the canonical state store. Tests may opt into the explicit in-memory adapter.

```bash
SUPABASE_DB_URL='postgresql://...' python3 -m uvicorn apps.api.main:app --reload --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The demo account is `demo-storyteller`.

## Run with Apple Container and Mocker

```bash
make container-config
make container-up
make container-health
make container-ps
make container-logs SERVICE=api
make container-down
```

The default ports are `http://127.0.0.1:3010` for the web shell, `http://127.0.0.1:8010` for the API, and `ws://127.0.0.1:8765` for the Codex harness. Override them with `MEMORY_SPARK_WEB_PORT`, `MEMORY_SPARK_API_PORT`, and `MEMORY_SPARK_CODEX_HARNESS_PORT`. The API image is defined by [`Containerfile`](Containerfile); the browser proxy is [`infra/nginx/memory-spark.conf`](infra/nginx/memory-spark.conf).

The API and worker use `SUPABASE_DB_URL` for canonical state and the durable outbox. Private original/generated blobs remain below `var/memory-spark/objects`. Copy `.env.example` to `.env` and configure Supabase and the local LLM provider before using the connected Codex agent.

Apply the checked-in migrations before using the connected agent:

```bash
psql "$SUPABASE_DB_URL" -f supabase/migrations/202609230001_user_agent_storage.sql
psql "$SUPABASE_DB_URL" -f supabase/migrations/202609230002_agent_sessions.sql
psql "$SUPABASE_DB_URL" -f supabase/migrations/202609240001_memory_spark_state.sql
```

## Verify

```bash
python3 -m pytest -q
make browser-test
python3 scripts/run_acceptance_evidence.py
python3 scripts/audit_spec_routes.py
```

The full implementation covers consent, invitations, resumable uploads, cue reactions, evidence-linked memories, version conflicts, preview builds, checkout and verified webhooks, chapters, editions, audio links, print proofs, deletion tombstones, audit metadata, regional provider switches, Supabase persistence, and the Codex memory integration. Production merchant, regional processor, media-rights, supplier, legal, and reliability gates remain configuration and operations decisions outside this credential-free local implementation.
