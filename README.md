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

The Next.js frontend serves the platform landing page at `/`, the Memoir entry page at `/memoir`, and the interview/workspace shell from the Memoir routes. An optional catch-all App Router page preserves direct links without adding locale prefixes or changing the public URL contract.

## Repository layout

```text
apps/
├── api/                    # FastAPI application and Supabase user-data adapters
│   ├── main.py             # Memoir HTTP interface
│   ├── story_payments.py   # Stripe Checkout and server-side entitlements
│   ├── store.py            # Project, session, memory, chapter, and edition state
│   └── namespaces.py       # /api/v1/memoir compatibility seam
└── web/
    ├── app/                # Next.js App Router and product catch-all route
    ├── components/         # browser-only adapters used by the App Router
    ├── client/             # browser client and route catalog
    ├── public/             # CSS, icons, and static assets
    ├── package.json        # Next.js runtime and build scripts
    └── Containerfile       # production Next.js image
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

The connected story journey uses Supabase Auth, RLS-protected `user_profile`/`user_memory` rows, and the private `memory-spark` Storage bucket. The backward-compatible specification routes retain an explicit in-memory adapter; there is no application-owned Postgres state store.

```bash
MEMORY_SPARK_TEST_MODE=1 python3 -m uvicorn apps.api.main:app --reload --host 127.0.0.1 --port 8000
```

Install the web dependencies once with `npm --prefix apps/web ci`, then run the Next.js frontend with `MEMORY_SPARK_API_ORIGIN=http://127.0.0.1:8000 npm --prefix apps/web run dev -- --hostname 127.0.0.1 --port 3010`. Open [http://127.0.0.1:3010](http://127.0.0.1:3010). Configure `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY`, then enable **Allow manual linking** and **Allow anonymous sign-ins** under Supabase Auth → Sign In / Providers. Configure both Google and Facebook there as well; the browser uses Supabase `linkIdentity` after round five. See [Supabase anonymous sign-ins](https://supabase.com/docs/guides/auth/auth-anonymous) and [manual identity linking](https://supabase.com/docs/guides/auth/auth-identity-linking#manual-linking-beta).

Memoir's UI supports reviewed `en-AU` and `zh-CN` catalogues through `next-intl`. The language selector keeps the current URL, persists a device choice in `copyme2_ui_locale`, negotiates the browser language when no choice exists, and updates the authenticated Supabase user's `ui_locale` metadata when available. The active Memoir conversation, agent trace, and speech requests use that same locale; source language, edition language, and the memoir's AUD pricing remain separate. Validate the catalogues with `make localization-catalog-test` and the rendered browser journey with `make browser-localization-test`. The implementation spec is [`docs/Memoir_Localization_Spec.md`](docs/Memoir_Localization_Spec.md).

To enable server-side voice, set `OPENAI_API_KEY` in `.env`. The API uses `gpt-4o-mini-transcribe` for recordings and `gpt-4o-mini-tts` for spoken questions by default; override them with `MEMORY_SPARK_STT_MODEL` and `MEMORY_SPARK_TTS_MODEL`. Keep the key server-side. If it is unset or speech is unavailable, typed answers and browser read-aloud remain available.

The authenticated Realtime/WebRTC backend is available at `POST /api/v1/memoir/realtime/calls`. It exchanges a browser SDP offer for an SDP answer using the server-only OpenAI key, loads the signed-in user's existing private context, and configures Mira's spoken interview with interruption support. `MEMORY_SPARK_REALTIME_MODEL` defaults to `gpt-realtime-2.1`; `MEMORY_SPARK_REALTIME_VOICE` defaults to `marin`. This is a backend integration point: the current recording UI has **not** been switched to WebRTC, and this endpoint does not persist new voice turns. See [the frontend handoff and API contract](docs/Realtime_WebRTC.md).

## Story packages and Stripe

After the free first chapter, the story journey offers three one-time packages in Australian dollars:

| Package | Price | Includes |
| --- | ---: | --- |
| Electronic memoir | A$49 | Electronic version only |
| Printed memoir | A$79 | Electronic version and 2 printed books |
| Family legacy memoir | A$129 | Electronic version, 2 printed books, family tree, timeline, and more detailed story context |

Additional printed books cost A$10 each for either printed package. The API calculates the total from the selected package and quantity; the browser cannot set the amount. Stripe Checkout is hosted by Stripe, and the paid entitlement is granted only by the signed webhook at `/api/v1/memoir/story/stripe/webhook` after a successful `checkout.session.completed` or asynchronous payment event.

Set these values in `.env` for a real checkout:

```text
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
SUPABASE_SECRET_KEY=your-server-only-supabase-secret
MEMORY_SPARK_PUBLIC_URL=https://your-domain.example
```

`STRIPE_PRICE_ELECTRONIC`, `STRIPE_PRICE_PRINTED`, `STRIPE_PRICE_FAMILY`, and `STRIPE_PRICE_ADDITIONAL_BOOK` are optional Dashboard-created Price IDs. If they are blank, the server uses Stripe `price_data` with the fixed server-side amounts. Never expose `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, or `SUPABASE_SECRET_KEY` to the browser.

To create or reuse the matching one-time Stripe products and prices, preview first and then run:

```bash
make setup_stripe_test \
  STRIPE_SECRET_KEY=sk_test_... \
  STRIPE_SETUP_ARGS=--dry-run
make setup_stripe_test STRIPE_SECRET_KEY=sk_test_...
```

For production, pass the public application URL. The Makefile creates `STRIPE_WEBHOOK_URL` by appending `/api/v1/memoir/story/stripe/webhook`:

```bash
make setup_stripe_live \
  STRIPE_SECRET_KEY=sk_live_... \
  MEMORY_SPARK_PUBLIC_URL=https://<public-domain>
```

The setup targets do not read `.env`; they require an explicitly supplied mode-matching `STRIPE_SECRET_KEY` and write it, the computed webhook URL, the Price IDs, and a newly created webhook secret to the local ignored config file under `infra/`. The test target creates a webhook URL only when `MEMORY_SPARK_PUBLIC_URL` or an explicit `STRIPE_WEBHOOK_URL` is supplied; the live target requires one. Use `make stripe_login` separately for local `stripe listen` forwarding.

Register the webhook URL in Stripe Workbench for `checkout.session.completed` and `checkout.session.async_payment_succeeded`. For local testing, forward events with the Stripe CLI:

```bash
stripe listen --forward-to 127.0.0.1:8000/api/v1/memoir/story/stripe/webhook
```

## Run with Apple Container and Mocker

```bash
make container-config
make container-up
make container-health
make container-ps
make container-logs SERVICE=api
make container-down
```

`make container-up` uses the existing local service images by default and
refreshes the non-bind-mounted Next.js web image from source. Run
`make container-build` or `make container-up CONTAINER_BUILD=1` after changing
a `Containerfile`, `pyproject.toml`, or image-baked skills. The local images use
`localhost/` tags so Mocker does not try to
pull them from Docker Hub during a no-build startup.

The default ports are `http://127.0.0.1:3010` for the Next.js frontend and
`http://127.0.0.1:8010` for the API. Override them with
`MEMORY_SPARK_WEB_PORT` and `MEMORY_SPARK_API_PORT`. The API image is defined by
[`Containerfile`](Containerfile); the frontend image is defined by
[`apps/web/Containerfile`](apps/web/Containerfile); and Codex runtime execution
is in the private [`codex-worker/Containerfile`](codex-worker/Containerfile).

The API uses the user's Supabase bearer token for RLS-protected story and Codex-memory operations. Codex runs only in the private worker container, which uses a dedicated volume and per-user OS identities; the API sends it only the already-authorized memory context. Set `MEMORY_SPARK_CODEX_WORKER_SECRET` to a long random value outside local development. Private original/generated blobs remain below `var/memory-spark/objects`. Copy `.env.example` to `.env` and configure Supabase and the local LLM provider before using the connected Codex agent.

### Collection agents and background tasks

There are **five local Compose services**: `web`, `api`, `codex-worker`, `worker`,
and `temporal`. `container-up` recreates all five containers;
normally it rebuilds only `web` (all buildable images when missing or when
`CONTAINER_BUILD=1`). API and worker Python sources are bind-mounted;
`codex-worker` Python and skills are image-baked and require a rebuild.

The collector and organiser are two **roles within `codex-worker`**, not separate
containers. Collection remains the default. In the profile menu, choose
**Review my memory collection**, record or explicitly skip each life period,
and confirm readiness before requesting a proposed book structure. The organiser
starts a separate thread and cannot replace the collection conversation. The
existing paid-memoir entitlement is still required for book organisation. New
collector turns invalidate the current project's readiness confirmation.

The preview, outline, chapter, and source-export jobs are **not retired**. They
now have deterministic handlers: previews/chapters assemble verbatim source
blocks, outlines assemble a validated structure, and exports package sources.
These handlers do not call an LLM or produce polished prose. The organiser uses
the LLM to propose headings and source assignments before queuing `BuildOutline`.
The collector may request previews and source exports; normal code can also
publish validated tasks through the private `codex-worker` publisher.

Temporal runs locally with the `memoir-tasks` task queue and a persistent
`temporal-data` volume. Open its UI at **http://127.0.0.1:8233**. A private SQLite
store on the `memoir-tasks` volume shared only by API and deterministic workers retains the dispatch outbox, authorised
source snapshots, collection reviews, and task results. Only opaque task IDs and
statuses enter Temporal history. The Codex publisher forwards tasks to an
authenticated API ingress; its tenant-hosting container has no task-database mount.
Workers dispatch pending rows, execute claimed
tasks with fenced leases and bounded retries, and save results for the owner.
This replaces the disconnected in-memory worker in the normal Compose path;
the explicit `--store` specification-test adapter remains available.

See [the updated architecture](memoir-architecture.html) and
[the task contract and operational limits](docs/Memory_Collection_Tasks.md).

Verify the real publisher → Temporal → worker path using synthetic data:

```bash
mocker compose exec -f compose.yml -i -T api python - < scripts/verify_task_pipeline.py
```

Keep all five services in the same Mocker `compose up` invocation so their service
aliases are populated. `make container-up` handles this. `container-health` also
checks the worker's Temporal connection. This is a persistent **local development**
setup, not a production Temporal deployment.

To reset local application data, stop the local API/worker first and run:

```bash
make db-truncate RESET_CONFIRM=1
```

The target loads `.env` before running, then removes rows from the application-owned Supabase tables, deletes every object in the `memory-spark` bucket through the Storage API, and clears `var/memory-spark/objects`. It requires `SUPABASE_DB_URL`, `SUPABASE_URL`, and the server-only `SUPABASE_SECRET_KEY`; Supabase Auth/system schemas and the bucket definition are preserved. Use `ENV_FILE=path/to/.env` to load a different file.

High-level Codex activity is hidden from storytellers by default. For local debugging only, set `MEMORY_SPARK_SHOW_THINKING_STEPS=1`; the browser then shows the opt-in "Thinking steps" summary while private model reasoning remains hidden.

### Langfuse trajectory evaluation

Memoir keeps the evaluation task callback beside the application and private
`codex-worker` boundary. The callback receives one synthetic case and the
correlation envelope, then returns the `trajectory` from
`CodexRuntime.turn(..., evaluation=..., include_trajectory=True)`. The recorder
captures observable Codex protocol and application steps, tool results and
errors, marker/state validation, persistence, and the terminal response while
redacting credentials and private reasoning. Ordinary browser turns never
request or return this payload.

Install the optional host-side SDK and run a case file with a callback module:

```bash
python3 -m pip install -e '.[evaluation]'
make langfuse-eval \
  EVAL_CASES=tests/evaluation/cases.json \
  EVAL_TASK=your_eval_module:run_case
```

Add `EVAL_PUBLISH=1` after configuring the `MEMORY_SPARK_LANGFUSE_*` variables
to publish the root observation and deterministic scores to the project hosted
by `llm_provider`. Publishing is optional for local regression runs; the
application and worker do not wait for Langfuse judges. The generic correlation
fields are forwarded to the provider through Codex's
`responsesapiClientMetadata`, so provider generations can be joined to the
Memoir run without moving Memoir skill or state semantics into `llm_provider`.
The publisher also exposes Langfuse SDK v4's `run_experiment` for synchronous
dataset callbacks; the local runner is the async adapter for the real worker
turn boundary.

Manual Google Web OAuth and Supabase Google sign-in setup is documented in [`gcp/google_oauth.md`](gcp/google_oauth.md). The standard Web OAuth client is created in Google Cloud Console and the client secret is stored in Supabase, not in the browser.

### Place journeys in the integrated Codex worker

The project skill at [`skills/memoir-place-journey/SKILL.md`](skills/memoir-place-journey/SKILL.md) turns an explicitly named, coarse place into a durable Earth-to-place workspace journey. The API validates the skill's `MEMORY_SPARK_PLACE_JOURNEY` marker, rejects markers not grounded in the current storyteller message, removes accepted markers from the spoken reply, persists the current versioned record in Supabase, and returns both `place_journey` and a `place_journey_change` envelope; the Memoir browser reveals and hydrates that record only after the current project has been activated by an explicit place cue, then uses CesiumJS `camera.flyTo` for the Places surface without treating a location as biographical fact. The skill is baked into the API and private Codex worker images and is refreshed with `make install_skill`.

### Family tree and author timeline in the integrated Codex worker

The project skills at [`skills/memoir-family-tree/SKILL.md`](skills/memoir-family-tree/SKILL.md) and [`skills/memoir-author-timeline/SKILL.md`](skills/memoir-author-timeline/SKILL.md) are loaded only after the server confirms a paid Family legacy entitlement backed by `STRIPE_PRICE_FAMILY`. The family-tree skill emits and validates `MEMORY_SPARK_FAMILY_TREE` for people and relationships; the author-timeline skill emits and validates `MEMORY_SPARK_AUTHOR_TIMELINE` for the author's events and life periods. Both persist into the shared, versioned `family_context` document under the authenticated Supabase user and Memoir project, and the response's `family_context_update.skills` field identifies which skill changed it. Unpaid, pending, revoked, and non-Family packages receive neither skill; uncertain dates and relationships remain explicit.

Apply the checked-in migrations before using the connected agent:

```bash
psql "<your Supabase Postgres connection string>" -f supabase/migrations/202609230001_user_agent_storage.sql
psql "<your Supabase Postgres connection string>" -f supabase/migrations/202609230002_agent_sessions.sql
psql "<your Supabase Postgres connection string>" -f supabase/migrations/202609250002_agent_turn_leases.sql
psql "<your Supabase Postgres connection string>" -f supabase/migrations/202609250003_story_entitlements.sql
psql "<your Supabase Postgres connection string>" -f supabase/migrations/202609250004_fenced_agent_turn_commit.sql
psql "<your Supabase Postgres connection string>" -f supabase/migrations/202609250005_family_price_provenance.sql
psql "<your Supabase Postgres connection string>" -f supabase/migrations/202609260001_user_family_context.sql
psql "<your Supabase Postgres connection string>" -f supabase/migrations/202609260002_user_place_journey.sql
```

With the local Compose stack running, refresh every repository skill with:

```bash
make install_skill
```

The target validates each `skills/*/SKILL.md` with the standard skill packager,
rebuilds the API and private `codex-worker` images, recreates those services so
their cached skill loaders reload, and removes the temporary ZIPs. Use
`SKILLS="memoir-place-journey"` only when debugging one skill. Generated
archives remain temporary, so `dist/` stays ignored.

For an installation that previously applied the retired JSONB-state migration, run `supabase/migrations/202609250001_remove_memory_spark_state.sql` once with your normal Supabase migration connection. It drops only the retired `memory_spark_state` and `memory_spark_outbox` tables.

When upgrading from API-hosted Codex, drain and stop **all old API/Codex writers**
before starting the new worker. Compose mounts the old `var/memory-spark/codex-users`
directory read-only; the worker atomically imports each user's complete offline
home (including SQLite/WAL and rollouts) on first use. Existing worker homes are
never overwritten, and the original files remain intact. Keep the legacy mount
until every existing user has migrated. Apply the fenced-commit migration before
starting the updated API; it intentionally has no unfenced-save fallback.

Artifact snapshots now use `agent/<root>/turns/<lease UUID>/<relative path>`.
Only the lease-checked database commit publishes their paths. Failed attempts
can leave unreferenced, private snapshots; they never overwrite committed ones.

Mocker currently warns that it ignores `cap_add`, `cap_drop`, and `read_only`.
Use a runtime that enforces these Compose settings for production. The offline
Linux verification below explicitly constrains its own capabilities so its
result does not depend on Mocker honoring those flags:

```bash
mocker compose exec -f compose.yml -T codex-worker python /usr/local/libexec/verify_codex_worker_isolation.py
```

This check uses temporary fixtures and a deterministic app-server double. It
does not call the model or Supabase, and it is not a live-model integration test.

## Verify

```bash
python3 -m pytest -q
make browser-test
make browser-localization-test
python3 scripts/run_acceptance_evidence.py
python3 scripts/audit_spec_routes.py
```

The full implementation covers consent, invitations, resumable uploads, cue reactions, evidence-linked memories, version conflicts, preview builds, checkout and verified webhooks, chapters, editions, audio links, print proofs, deletion tombstones, audit metadata, regional provider switches, Supabase persistence, and the Codex memory integration. Production merchant, regional processor, media-rights, supplier, legal, and reliability gates remain configuration and operations decisions outside this credential-free local implementation.
