# CopyMe2

CopyMe2 is the platform umbrella: **preserve the parts of you that matter**. The first live product is Memoir, a guided, source-linked memoir journey that turns memories, photographs, and the storyteller's own voice into a family book.

Memoir recall includes 20 successful conversation replies by default. Set the
positive integer `MEMORY_SPARK_FREE_RECALL_ROUNDS` to change this allowance.
Usage belongs to the user across projects and is recorded atomically with each
saved reply; failed replies do not consume it. Once exhausted, the interview
shows package selection and resumes only after a verified paid entitlement.
Customer-facing copy does not show the free-round allowance.

The development database is defined by one fresh-install migration,
`supabase/migrations/202610180001_initial_schema.sql`. It creates only the current
schema, with no upgrade backfills or legacy import paths. After pulling this
baseline replacement, reset your disposable database yourself with
`supabase db reset --db-url "$SUPABASE_DB_URL" --yes`. Existing migration history
is intentionally unsupported. `make migrate` still uses Supabase migration
tracking for fresh databases. Until production deployment is explicitly announced,
update this single baseline in place for every schema change. See
[the database design](docs/Database_Design.md) for retained tables and indexes.

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

Memoir's UI supports `en-AU` and `zh-CN` catalogues through `next-intl`. The language selector keeps the current URL, persists an explicit device choice in `copyme2_ui_locale`, negotiates the browser language when no choice exists, and updates the authenticated Supabase user's `ui_locale` metadata when available. A saved profile conversation language also seeds the page language when no explicit page-language choice exists, so a Chinese profile remains Chinese after refresh; an explicit page-language choice wins. With no fixed device, account, or profile language choice, the first substantive onboarding reply can switch the current UI session and first Mira response to its detected supported language. Later interview replies and voice transcripts remain separate from UI locale. Source language, edition language, time zone, and memoir AUD pricing stay unchanged. Exact dates/times are formatted with the UI locale while uncertain expressions remain expressions. Validate the catalogues with `make localization-catalog-test` and the rendered browser journey with `make browser-localization-test`. Sensitive copy is listed in [`apps/web/messages/human-review.json`](apps/web/messages/human-review.json) for human/native-speaker sign-off. The implementation spec is [`docs/Memoir_Localization_Spec.md`](docs/Memoir_Localization_Spec.md).

To enable server-side voice, set `OPENAI_API_KEY` in `.env`. The API uses `gpt-4o-mini-transcribe` for recordings and `gpt-4o-mini-tts` for spoken questions by default; override them with `MEMORY_SPARK_STT_MODEL` and `MEMORY_SPARK_TTS_MODEL`. Keep the key server-side. If it is unset or speech is unavailable, typed answers and browser read-aloud remain available.

Voice conversations choose Mira's character from the interview language, independently of the interface language. Chinese (`zh-CN`) defaults to `coral` with a warm female voice and natural Mandarin delivery at 1.1× speed; English (`en-AU`) defaults to `marin` with relaxed conversational Australian English. Each language keeps its configured voice across turns. If generation or playback fails, the reply remains in the chat with a voice-unavailable notice; the next turn uses the same configured character. Separate read-aloud controls are hidden during voice conversations so browser voices cannot interrupt Mira.

Set `MEMORY_SPARK_TTS_VOICE_ZH_CN` or `MEMORY_SPARK_TTS_VOICE_EN_AU` to choose different built-in voices, and optionally set the matching `MEMORY_SPARK_TTS_INSTRUCTIONS_*` to customize delivery. Blank instructions use the localized defaults. Additional locales can use the same `MEMORY_SPARK_TTS_VOICE_<LOCALE>` and `MEMORY_SPARK_TTS_INSTRUCTIONS_<LOCALE>` convention (for example `FR_FR`); add those variables to the API service environment in `compose.yml` when running containers. Audio caches include the resolved voice, delivery and speed, so changing a character does not reuse old audio. Built-in voices are [optimized for English](https://developers.openai.com/api/docs/guides/text-to-speech), so Mandarin delivery still needs listening review.

Voice input uses microphone recording, `POST /api/v1/memoir/story/transcriptions`, and the same canonical saved conversation engine as typed input. Spoken replies use the speech endpoint. The separate direct WebRTC backend has been retired; see [the voice flow](docs/Realtime_WebRTC.md).

Set `MEMORY_SPARK_HISTORICAL_NEWS=1` in `.env` and recreate the API service to
enable optional public historical context during interviews. Research starts
after the saved reply has been sent and its interview lease released; only
inspected, cited clues become available to later questions. Missing or ambiguous
life context and project opt-outs suppress research. It uses the existing LLM
gateway and credentials. `MEMORY_SPARK_HISTORICAL_NEWS_MODEL` optionally selects
an existing gateway alias for low reasoning effort when the main alias forces
higher effort; blank uses `MEMORY_SPARK_LLM_MODEL`.

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

`make up` (also `make container-up`) validates every repository skill. Local Python
services use the Containerfiles' `runtime` targets with read-only application and
skill mounts, so Python, prompt, and skill edits do not rebuild those images.
Dependency manifests, Containerfiles, build arguments, or local image changes
still trigger builds. The frontend rebuilds when its source changes, preserving
Next's compiler cache and shipping only its standalone runtime files.
It builds the shared backend image once, then recreates all six local services on
every run with the current checkout, Compose settings, and environment values.
Named volumes, including Temporal history, are preserved. Startup refreshes
service aliases from Apple Container's live addresses before waiting for health;
Mocker's cached inspection addresses are not used. Running conversations and
background tasks may be interrupted during startup. Worktrees share the `memory-spark` Compose project;
running startup from a worktree changes the backend used by the main checkout.
The first run establishes a
local cache in `var/container-startup.json` after all health checks pass.
Use `make up CONTAINER_REBUILD=1` to rebuild all app images with cached build layers.
Startup uses `SUPABASE_DB_URL` for the publication guard when
`MEMOIR_PUBLICATION_DATABASE_URL` is unset; an explicit publication connection wins.
Run `make migrate` first when new Supabase migrations are present. Use
`make container-build` to rebuild without restarting services. The local images use
`localhost/` tags so Mocker does not try to
pull them from Docker Hub during a no-build startup.

The default ports are `http://127.0.0.1:3010` for the Next.js frontend and
`http://127.0.0.1:8010` for the API. Override them with
`MEMORY_SPARK_WEB_PORT` and `MEMORY_SPARK_API_PORT`. The API image is defined by
[`Containerfile`](Containerfile); the frontend image is defined by
[`apps/web/Containerfile`](apps/web/Containerfile); and Codex runtime execution
is in the private [`codex-worker/Containerfile`](codex-worker/Containerfile).

The API uses the user's Supabase bearer token for RLS-protected story and Codex-memory operations. Codex runs only in the private worker container, which uses a dedicated volume and per-user OS identities; the API sends it only the already-authorized memory context. Set `MEMORY_SPARK_CODEX_WORKER_SECRET` to a long random value outside local development. Private original/generated blobs remain below `var/memory-spark/objects`. Copy `.env.example` to `.env` and configure Supabase and the local LLM provider before using the connected Codex agent.

Memoir interviews default to the ChatGPT subscription pool through LiteLLM's
`gpt-5.6-luna-pooled` route, backed by `codex-lb`, with
`MEMORY_SPARK_LLM_REASONING_EFFORT=max`. Canonical event extraction, preview,
and private memoir composition use `MEMORY_SPARK_MEMOIR_COMPOSER_MODEL`, which
defaults to `memoir-luna-low`. The provider must configure this alias with a
dedicated same-model codex-lb key enforcing low reasoning; an alias alone
cannot override the shared upstream key's max policy. Set
`MEMORY_SPARK_AUTHOR_TIMELINE_REASONING_EFFORT` to control canonical event
extraction separately; it defaults to `low` for background checkpoints. The
Temporal worker also needs `SUPABASE_URL` and `SUPABASE_SECRET_KEY` to dispatch
and commit those shared memoir lanes. Set
`MEMORY_SPARK_LLM_BASE_URL` to the provider network's current gateway on port
4000; the LiteLLM gateway and `codex-lb` must both be running. Keep the Memoir
consumer key in `MEMORY_SPARK_LLM_API_KEY` authorized for both model routes; the
`codex-lb` key stays in the provider stack.

### Public hostname through Cloudflare Tunnel

The local Apple Container stack can serve [https://copyme2.ai](https://copyme2.ai)
through the dedicated `copyme2-memoir` tunnel. A macOS launch agent keeps
`cloudflared` running and forwards the hostname to the Next.js frontend on
`127.0.0.1:3010`; Next.js forwards `/api/v1/memoir/*` to the private API.

With the tunnel already configured and the local frontend running:

```bash
make cloudflare-link    # Connect copyme2.ai to localhost:3010.
make cloudflare-unlink  # Disconnect and keep the tunnel off across logins.
```

Unlink leaves the local app running and keeps the DNS route for the next link.
While disconnected, the public hostname cannot reach this Mac's frontend.

For initial setup and health checks:

```bash
make container-up
make tunnel-plan
make tunnel-setup TUNNEL_ARGS=--replace-existing # first cutover from copyme2-serenity
make tunnel-health
make tunnel-status
```

Set `MEMORY_SPARK_PUBLIC_URL=https://copyme2.ai` in `.env` before starting
containers. Tunnel login requires selecting `copyme2.ai` in Cloudflare; its
certificate and tunnel credentials stay outside the repository. The tunnel
launch agent starts at user login while enabled; the container stack must also
be running and this Mac must remain awake and online. See
[`infra/cloudflare/README.md`](infra/cloudflare/README.md) for restart, logs,
auth callback settings, and rollback.

### Collection agents and background tasks

For streamed conversations, private workspace extraction runs alongside the
visible reply. A complete, validated place marker emits a temporary map preview
immediately, without waiting for profile extraction or artifact transfer. The
browser preloads Cesium while the reply streams. Preview events do not write the
profile or start photo persistence; the normal workspace event confirms and
saves the place after the conversation commit. Ambiguous or ungrounded places
produce no preview, and project/turn ordering guards reject late results.

There are **six local Compose services**: `web`, `api`, `codex-worker`, `photo-worker`,
`worker`, and `temporal`. `container-up` rebuilds changed images, recreates every service,
and verifies the full stack. The API, background worker, and photo worker
share the backend image; Temporal uses its upstream image. API and worker Python
sources and all service skills are bind-mounted. The default `app` Containerfile
targets still bake application files into self-contained images for other deployments.

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

Keep all six services in the same Mocker `compose up` invocation so their service
aliases are populated. `make container-up` handles this. `container-health` also
checks the worker's Temporal connection. This is a persistent **local development**
setup, not a production Temporal deployment.

To permanently reset local user/application data while retaining the shared
keyword-to-photo search cache, run:

```bash
make db-truncate RESET_CONFIRM=1
```

The guarded target stops the local Compose stack and removes its persistent
`codex-worker-home`, `memoir-tasks`, and `temporal-data` volumes. It then loads
`.env`, clears every object in every Supabase Storage bucket through the Storage
API, clears local object and per-user Codex files, truncates the application
tables, and deletes every Supabase Auth user. It requires `SUPABASE_DB_URL`,
`SUPABASE_URL`, and the server-only `SUPABASE_SECRET_KEY` (or
`SUPABASE_SERVICE_ROLE_KEY`). Schemas, migration history, and Storage bucket
definitions are preserved. `public.place_photo_search` is preserved, including
its search keys, public photo results and update times. A preflight rejects
foreign-key/partition dependencies that would pull this table into `CASCADE` or
Auth deletion, before stopping services or clearing Storage/files. Per-run
SerpAPI/CSE metadata under `search-cache/` in photo-research run directories also
remains outside the user-file reset paths. This command leaves the web/API stopped;
service recovery is a separate action. `supabase db reset` recreates schemas and
does not offer this cache-preservation guarantee; use it only for an intentional
full schema reset. Use
`ENV_FILE=path/to/.env` to load a different file.

High-level Codex activity and early private-draft previews are hidden from storytellers by default. The two debug flags are independent and default to off. Set `MEMORY_SPARK_SHOW_THINKING_STEPS=1` to stream operation summaries and show "Thinking steps". Set `MEMORY_SPARK_SHOW_DRAFT_UPDATES=1` to stream live private-draft checkpoints and show the draft-status panel, including "您的私人草稿正在后台更新" while work is pending. Draft previews, language and retry controls appear beneath the message input when the workspace is hidden or collapsed. Either debug UI requires a browser URL at `localhost`, `127.0.0.1` or `[::1]`; draft streaming does not require the thinking-step flag. With thinking steps off, chat still streams its reply and saved/workspace events, but emits no thinking-step progress or trace. The draft endpoint negotiates `application/x-ndjson`, sends `draft_update` events when the saved view changes and periodic `heartbeat` events, then sends `complete` when background work settles or a safe `error` if delivery fails. The server checks durable draft state every two seconds while work is pending; the UI maintains one connection and only reconnects after transport interruptions, with two bounded retries. Each canonical update retains its own publication guard. Other browser hosts keep this debug UI hidden and cannot open the draft stream even when the flags are enabled. With draft debugging off, a one-time read loads the saved draft in the workspace's Chapters tab after the configured free recall rounds are complete (20 by default), including after refresh and for storytellers who paid early. Location/photo cues remain available alongside those tabs until composition unlock, when the composition views take over.

### First-response latency profiling

Measure the current HTTP conversation path with a fresh anonymous test account
and project:

```sh
python3 scripts/profile_first_reply.py first-turn --origin http://localhost:3010 --timeout 120
```

Use `--origin http://localhost:8010` to measure the API directly, without the web proxy.
This sends one synthetic introduction through the configured model and saves the
test conversation. JSON output includes response headers, first nonempty text,
reply completion, and conversation-save timings, without reply text or credentials.
Timing starts when the turn request is sent, after signup and project creation.
The account/project identifiers are printed for later cleanup. Browser paint is
not measured. `scripts/profile_canonical_controlled.py` remains available for
controlled backend measurements with a simulated model.

### Versioned prompt artifacts

Merged Git `main` owns prompt content; Memoir's Langfuse project owns published
versions. Each skill owns its model
instructions under `memoir/skills/<skill>/...`, including composer phases and
shared editorial policy. Repository sources live under that skill's directory.
Common bounded-worker instructions use `memoir/shared/...`; judge/probe and
synthesis instructions use `memoir/evaluation/...` and `memoir/speech/...`.
Issue numbers and release dates stay in metadata and numeric version history.
The [structure and usage audit](docs/Langfuse_Prompt_Structure_Refactor.md) explains
the execution paths, and the [individual inventory](docs/Langfuse_Prompt_Usage.md)
lists all 69 retained runtime, conditional, shared and evaluation sources.

Guide-only entries and the obsolete composer model index were removed from
Langfuse. Integration guides, schemas and validators remain repository resources.
Canonical composition consumes host-owned events. Its retired full-source preview
fallback and uncalled private-draft executor were removed. The HTTP first-response
and canonical controlled profilers remain available. Collector configuration
accepts `compact-v1` and `two-lane-v1`, defaulting to `compact-v1`.

Edit and review prompt Markdown in a pull request before creating a Langfuse
version. Feature branches do not publish or fabricate version receipts. The API
reads checked-in prompt files. Shared instructions have one source;
task templates reference them through `apps/api/prompt_composition.py`. Runtime
and dataset evaluations use this same builder. The browser sends original
narration, without constructing model instructions. Each managed file has a `.langfuse.json`
receipt with its exact numeric version and SHA-256. An unpublished draft does not
pass runtime receipt validation; synchronize merged `main` before running it.

Run `make prompt-sync-install` once per clone. The tracked Git `post-merge` hook
then synchronizes prompts automatically after a successful merge/fast-forward
pull on `main`. It quietly skips feature branches and refuses publication unless
local `main` matches the live `origin/main` tip and has no local edits other than
generated prompt receipts. It reads committed prompt content, reuses unchanged
Langfuse versions, and creates a version only when the text changed. Each new
version records the merged Git commit. Receipt updates remain visible as local
Git changes for review and commit; the hook does not commit, push or restart apps.
An already-up-to-date pull does not invoke Git's hook; `make prompt-sync` retries
a previously failed sync. If Langfuse is unavailable, the pull remains merged and
the hook reports the failure without inventing receipts.

`make prompt-sync-check` previews publication on current `main` without writing.
`make prompt-export` remains an explicit recovery command that exports the highest
numeric Langfuse version. `make prompt-check` compares checked-in pins with their
exact remote versions and validates template composition. Evaluation preflight includes the
component versions/hashes and compiled SHA-256. Prompt commands use the existing
local Memoir project credentials in
`$(HOME)/llm_provider/.env` by default. Override `PROMPT_CREDENTIAL_FILE` for a
different local credential-file location. The hook also honors an exported
`PROMPT_CREDENTIAL_FILE` environment variable.

```sh
python3 -m pip install -e '.[evaluation]'
make prompt-sync-install                   # Once per clone; enables the Git hook.
git switch main
git pull --ff-only origin main              # Automatically syncs after incoming main changes.
make prompt-sync                           # Manual retry; publishes changed merged content only.
make prompt-sync-check                     # Read-only preview on current main.
make prompt-check
make prompt-eval                           # Read-only preflight for timeline/event-grounding.
```

For recovery exports/checks, use `PROMPT_NAME=memoir/skills/memoir-composer/draft`
to select one artifact. Normal content changes go through Git review, then main
publication and a receipt update. To preflight another prompt/dataset pair, set
`PROMPT_EVAL_NAME` and `PROMPT_EVAL_DATASET`. `PROMPT_EVAL_VERSION` can select a
candidate version before export; otherwise the checked-in version is used.
Use this evaluation command for composed templates: it supplies the complete
model input using the same component pins as the app. The template text shown
in Langfuse is one source of that input, not the complete assembled request.
`make prompt-eval` pins the dataset at its current UTC snapshot and prints the
prompt version and item count without model calls. To run the experiment, set
`PROMPT_EVAL_RUN=1` and `PROMPT_EVAL_MODEL=...`. The command reads provider
credentials from `PROMPT_EVAL_PROVIDER_FILE` (the same `llm_provider/.env` by
default), or use a different credential file and `--base-url` via the Python CLI. It sends
one request at a time, up to 50 items by default. Structured dataset input is
sent as JSON text. Review Langfuse outputs and human or managed scores before
publishing a candidate. This generic experiment does not run application packet
validation or automatically assign a quality score; full application behavior
still needs its normal runtime checks.

Langfuse documents [prompt versions](https://langfuse.com/docs/prompt-management/features/prompt-version-control)
and [versioned dataset experiments](https://langfuse.com/docs/evaluation/experiments/datasets).

### Langfuse trajectory evaluation

The [ten-skill dataset evaluator](docs/memoir-skill-evaluation.md) inventories all
runtime skill prompt owners, including the foreground interviewer. It provides
stable skill datasets, controlled/isolated contract execution and optional pinned
LLM judges; the [implementation spec](https://github.com/bohui/copyme2.ai/issues/90)
tracks the remaining bilingual cases and managed evaluator publication.

Memoir keeps the evaluation runner beside the application and private
`codex-worker` boundary. The default dataset and callback are checked in at
[`tests/evaluation/cases.json`](tests/evaluation/cases.json) and
`apps.api.evaluation_cases:run_case`; each case uses an isolated synthetic
identity/project and calls `CodexRuntime.turn(..., evaluation=..., include_trajectory=True)`.
The recorder captures observable Codex protocol and application steps, pre-action
context, normalized tool arguments, results/errors/retries, marker/state
validation, persistence, deterministic task results, and the terminal response
while excluding private reasoning. Each case declares its language, profile,
memories, entitlement, enabled skills, available tools, and expected outcome.
Ordinary browser turns never request or return this payload.

Install the optional host-side SDK and run a case file with a callback module:

```bash
python3 -m pip install -e '.[evaluation]'
make langfuse-eval
```

Add `EVAL_PUBLISH=1` after configuring the `MEMORY_SPARK_LANGFUSE_*` variables
to publish the minimized root observation and deterministic scores to the
project hosted by `llm_provider`. Full local results and per-case failure
evidence are written under `var/evaluation-failures/`; the application and
worker do not wait for Langfuse judges. Use the CLI's `--variant` option to
compare model/provider or skill variants. The optional semantic judge requires
`--judge-base-url`, `--judge-model`, and a calibration manifest explicitly
marked `human-reviewed`; unreviewed examples are rejected. Dataset, rubric,
application revision, skill manifest, model, provider, and case IDs are
included in the correlation metadata. The publisher also exposes Langfuse SDK v4's `run_experiment` for
synchronous dataset callbacks; the local runner is the async adapter for the
real worker turn boundary.

The five-case runner can publish the same minimized evidence per round after a
successful Langfuse preflight:

```bash
python3 scripts/run_memoir_five_case_evaluation.py \
  --mode live --publish --run-id <isolated-run-id>
```

Each published round carries the complete ordered trajectory on its root
observation, creates child observations when the SDK supports them, preserves
worker-supplied observation ancestry and tool arguments, and sends deterministic
skill invocation/output/state scores. Unavailable judge or telemetry evidence
is recorded separately; it is never reported as a live pass.

Manual Google Web OAuth and Supabase Google sign-in setup is documented in [`gcp/google_oauth.md`](gcp/google_oauth.md). The standard Web OAuth client is created in Google Cloud Console and the client secret is stored in Supabase, not in the browser.

### Place journeys in the integrated Codex worker

The project skill at [`skills/memoir-place-journey/SKILL.md`](skills/memoir-place-journey/SKILL.md) turns an explicitly named, coarse place into a durable Earth-to-place workspace journey. The API validates the skill's `MEMORY_SPARK_PLACE_JOURNEY` marker, rejects markers not grounded in the current storyteller message, removes accepted markers from the spoken reply, persists the current versioned record in Supabase, and returns both `place_journey` and a `place_journey_change` envelope; the Memoir browser reveals and hydrates that record only after the current project has been activated by an explicit place cue, then uses CesiumJS `camera.flyTo` with the configured geocoder and map tiles when the matching server and browser keys are configured. The opening globe fits the map panel, and arrival finishes in a north-up 2D map at a scale appropriate to the place. Reduced-motion preferences skip the flight. The geocoding key stays server-side, and only the selected provider’s restricted browser key is exposed. The application still keeps places approximate and falls back to saved parents or the hierarchy view without treating a location as biographical fact. The finest supported location is a named suburb or town. Hospitals, schools, streets, compounds, and generic labels stay in the story; an explicitly named containing city or suburb becomes the journey location. The parser normalises `地球` to the canonical `Earth` root and accepts every grounded place in a message. Local Compose mounts the place skill into both the API and private Codex worker so restarting those services loads the current contract; built images retain a copy for deployment. Photo searches use a calendar period only for the place it describes and report `memoir-place-photo-research` progress in Thinking steps.

The background [`memoir-place-groups` skill](skills/memoir-place-groups/SKILL.md) checks every new place preview, confirmed update, and restored history against existing city groups. `POST /v1/projects/{project_id}/place-groups` uses public hierarchy and cached geocoder administrative metadata without another model call. A city's named suburbs, towns, and administrative districts share one map with independent pins; another city creates another choice. Original location records, stages, and photographs stay distinct. Partial matches and missing child coordinates remain visibly pending, rather than receiving the parent's centre coordinates. The newest mention is checked first, and stale responses cannot overwrite a correction or another project's workspace. Grouping and photo requests run independently of the conversation stream.

Choose the provider with `MEMOIR_GEO_PROVIDER` in the API environment. The flag selects both public-place geocoding and map tiles; Cesium keeps rendering the globe, flight and final map. Google remains the default when the flag is absent or blank. Changing the flag requires restarting/recreating the API service and reloading the browser.

| Flag value | Server-only geocoding key | Restricted browser map key | Displayed map |
| --- | --- | --- | --- |
| `google` (default) | `GOOGLE_MAPS_GEOCODING_API_KEY` | `GOOGLE_MAPS_BROWSER_API_KEY` | Google 2D roadmap tiles |
| `geoapify` | `GEOAPIFY_API_KEY` | `GEOAPIFY_BROWSER_API_KEY` | Geoapify OpenStreetMap tiles |

For Google, enable billing, [Geocoding API](https://developers.google.com/maps/documentation/geocoding) and [Map Tiles API](https://developers.google.com/maps/documentation/tile), with a server-restricted geocoding key and a separate HTTP-referrer-restricted browser key. For Geoapify, create separate server and browser keys and restrict them to the API server address and deployed web origins. Optional compatible proxies use `GOOGLE_MAPS_GEOCODING_URL` or `GEOAPIFY_GEOCODING_URL`. The public config exposes `geo_provider` and only the selected browser key. Missing credentials, unsupported flags or provider errors keep the existing saved-place/hierarchy fallback; they do not switch providers automatically. Query caches are separate for each provider.

The map enters its final 2D view after the first tile succeeds. Asynchronous imagery errors, including rejected keys and quota failures, remove the failed layer and restore the visible globe/hierarchy fallback. Geoapify results require numeric confidence of at least `0.95`, a matching place name and every supplied parent in geographic order. Missing or contradictory metadata stays unresolved; partial matches cannot supply a child map target or pin. These checks use the supplied labels, including normalized Chinese city/province suffixes; unrecognized translations and aliases can remain unresolved until explicitly supported. The threshold is a conservative application policy, not evidence of measured live accuracy. See [Geoapify's confidence fields](https://apidocs.geoapify.com/docs/geocoding/forward-geocoding/).

Before changing the deployment default, compare both providers on 50–100 representative Chinese and English place names, including Chinese/English pairs, city/district/town distinctions, same-name places in different provinces, sparse mainland locations, and Australian suburbs. Check correct administrative membership, centre accuracy, partial/no-match handling, latency and request cost. Provider fixtures verify integration, not real coverage; the live comparison awaits a working Google key. [MapLibre](https://maplibre.org/projects/gl-js/) is a separate renderer option, so this flag keeps Cesium. Amap would need a separate evaluation and explicit handling of its [GCJ-02 coordinates](https://lbs.amap.com/api/javascript-api-v2/guide/transform/convertfrom) before its results could enter a WGS84 coordinate pipeline.

### Family tree and author timeline in the integrated Codex worker

The [`memoir-author-timeline` skill](skills/memoir-author-timeline/SKILL.md) processes every durably accepted narrator message in the background. PostgreSQL stores one canonical MemoryEvent index with stable IDs, supported stage/year placement, uncertainty, revisions, and many-to-many original source links. Accepted evidence survives an assistant-delivery failure; completed-round usage requires a saved successful reply. Agent memory is a context view of those records.

The [`memoir-composer` skill](skills/memoir-composer/SKILL.md) consumes the same event IDs. Every five completed rounds by default, it waits for extraction, freezes the latest eligible snapshot, prepares dirty stage/year/event groups in bounded parallel work, and preserves unchanged prose and revisions. Temporal coordinates one active run per project/skill lane with coalesced catch-up, bounded deadlines, retries, and fenced commits. A validated repeat of unchanged event facts advances extraction without rewriting prose. A checkpoint with no supported events finishes collecting without inventing prose or requesting a provider retry.

Family legacy entitlement backed by `STRIPE_PRICE_FAMILY` still controls timeline workspace display and the [`memoir-family-tree` skill](skills/memoir-family-tree/SKILL.md). The tree runs for explicit relationship information or a relevant correction, validates `MEMORY_SPARK_FAMILY_TREE`, and persists people and relationships in `family_context`. Internal event indexing applies independently of that display entitlement; the former author-timeline marker remains a legacy adapter rather than a second canonical event index.

Apply the checked-in schema before using the connected agent:

```bash
make migrate
```

`make up` installs the repository skills during startup. To refresh only the
skill-bearing services in an already running Compose stack, use:

```bash
make install_skill
```

The target validates each `skills/*/SKILL.md` with the standard skill packager,
rebuilds the API and private `codex-worker` images, recreates those services so
their cached skill loaders reload, and removes the temporary ZIPs. Use
`SKILLS="memoir-place-journey"` only when debugging one skill. Generated
archives remain temporary, so `dist/` stays ignored.

Run `make migrate` before starting the API and worker. Conversations use the canonical engine only, with fresh bounded model execution and transactional publication fences. Old Codex homes are not imported or resumed.

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

### Photo favourites and interview cues

For authenticated users, favourites and the selected cue are private to the
signed-in account and keyed by interview project in its Supabase profile. This
also applies to family projects: the owner and storyteller each retain their
own selection, used by that principal's collector. Ordinary project members
cannot change favourites. Project and journey responses expose only the
viewer's current-project photo state; the shared project adapter does not
cache account photo maps. A failed authoritative read returns an error rather
than another member's cached selection. Local/demo projects continue to use
their project store.

Successful photo commands take precedence over project/profile refreshes that
started before them. Clearing the cue keeps the favourite; removing a selected
favourite also clears its cue. Failed saves preserve the previous cue, and
navigation or account changes invalidate in-flight responses. Reference-photo
metadata remains untrusted context, not evidence of the storyteller's life.

Offline regressions are in `tests/test_photo_memories.py` and
`tests/js/photo-memories.test.mjs`, including separate principals/projects,
project-store reloads, legacy contaminated snapshots, and delayed refreshes.
Mocked account storage does not establish live Supabase/RLS acceptance.

### Test commands

```bash
make test
make test-place-research
make browser-test
make browser-localization-test
make memoir-progressive-test
python3 scripts/run_acceptance_evidence.py
python3 scripts/audit_spec_routes.py
```

`make test` includes the JavaScript workspace tests as well as Python. The focused
`make test-place-research` also replays a Chinese interview mentioning Chengde
in the 1980s and present-day Sydney: foreground reply, delayed place extraction,
photo/news research, localized location buttons, selection and interview restore.
It uses disposable PostgreSQL and controlled external provider responses; Node.js
and local PostgreSQL tools are required. Separate browser commands cover layout
and real browser interactions.

For live evaluation against remote Supabase, use
`make memoir-live-fifty-plan` to inspect the five distinct cases, then
`make memoir-live-fifty-test` for 50 rounds per case (250 total). The live target
also saves a readable `report.md` beside the raw receipts, including partial
results after failure. Add `EVAL_CASE_ID=harbour-copper-notebook` (or another
original case ID) to run one complete 50-round conversation independently.
See [setup and report commands](docs/memoir-fifty-subscription-evaluation.md#make-commands-and-saved-reports)
for backend configuration and UI sign-in. The runner starts backend services only,
uses the current checkout, and retains each case's projects under its fixed account
(`test@test.com` through `test5@test.com`). Before each run, setup creates missing
accounts and sets all five passwords to `test1234`, confirming their emails
without prompts and preserving existing IDs and application data. It prints each
project ID and UI URL. Use
`make memoir-live-fifty-login` to save a private sign-in link without sending email.
The original local PostgreSQL launcher remains available through
`memoir-live-fifty-disposable-plan` and `memoir-live-fifty-disposable-test`.

For the recall/workspace browser acceptance suite, use a task-owned production
frontend against a fresh test-mode API rather than a development HMR session.
With that isolated API already running at `http://127.0.0.1:18042`:

```bash
MEMORY_SPARK_API_ORIGIN=http://127.0.0.1:18042 npm --prefix apps/web run build
MEMORY_SPARK_API_ORIGIN=http://127.0.0.1:18042 npm --prefix apps/web run start -- --hostname 127.0.0.1 --port 13042
```

In another terminal, run the actual source UI and controlled service boundaries:

```bash
MEMOIR_BROWSER_URL=http://127.0.0.1:13042 python3 -m pytest -q \
  tests/test_recall_browser.py tests/test_interview_workspace_browser.py \
  tests/test_progressive_memoir_navigation_browser.py
```

The saved-draft navigation cases require their disposable PostgreSQL fixtures;
never point them at live storyteller storage. Optional font CSS is controlled
on every test page, including fresh tabs; dedicated startup regressions keep it
pending. Production build/start removes the development-only HMR dependency
without disabling browser network security. Keep failed development-run evidence
separate from production acceptance results.

`make memoir-progressive-test` runs the deterministic composer validator and
renderer against ten distinct sample lives (five in China and five in
Australia, 31 rounds each), then drives 31-round `zh-CN` and `en-AU` browser
conversations. The browser assertion covers place grouping, photo references,
family/timeline cues, and the stage-3 delivery transition where structured
chapter tabs replace the earlier location/photo overview. See
[`docs/memoir-progressive-e2e.md`](docs/memoir-progressive-e2e.md) for the
coverage boundary and evidence produced.

The full implementation covers consent, invitations, resumable uploads, cue reactions, evidence-linked memories, version conflicts, preview builds, checkout and verified webhooks, chapters, editions, audio links, print proofs, deletion tombstones, audit metadata, regional provider switches, Supabase persistence, and the Codex memory integration. Production merchant, regional processor, media-rights, supplier, legal, and reliability gates remain configuration and operations decisions outside this credential-free local implementation.

### Historical photo search

Photo and historical-news research share `place_selection` admission and the
source-grounded period resolver in `apps/api/place_research.py`. A dated birth
cue such as “born in Chengde in April 1983” supplies a **1980s research window**
for that birthplace; it does not change the memoir's birth date or assign that
period to a separately mentioned present home. Explicit remembered ranges take
their own bounds. Snapshots retain `research_year=1983` separately from the
`research_period=1980s` search window, so ranking does not lose the original year.
Restored place snapshots carry that context, and selecting
the photo gallery also registers news research under the same place/period.
News retains its rollout switch, opt-out, reviewed public vocabulary, independent
source verification and durable deduplication. It does not require another birth
sentence, a stated country when the place is unambiguous, or a conversation-round
milestone. Current-photo searches remain available for undated places.

The V1 default is Wikimedia Commons plus server-side `SERPAPI_KEY` discovery,
with the configured Google CSE searched independently alongside SerpAPI.
SerpAPI searches Google Images, Google web records and, for Chinese places,
Baidu web records. A small source registry in
[`apps/api/place_photo_sources.py`](apps/api/place_photo_sources.py) prioritises
Chengde Municipal Archives and City of Sydney Archives for their localities;
City of Sydney is not treated as the archive for every greater-Sydney suburb.
The registry supplies search priorities, never item dates or reuse permission.
The normal pass uses at most three searches and twelve original pages; optional
`MEMOIR_PHOTO_EXPANSION=1` raises the limits to seven searches and 36 pages.
Both modes share a 65-second discovery budget and publish eligible results as
they arrive. Existing date/GPS fallback passes have their own bounded searches.
Flickr and Library of Congress remain available in the legacy route when
SerpAPI is not configured.

Search results are leads: inspect the original photograph's location, capture
date and licence before app display. An unknown licence does not allow embedding.
Commons uses `DateTimeOriginal`, never the Imageinfo upload timestamp, and retains
the file URL, source page, attribution, licence, dimensions and hash. Catalogue
records keep separate `usage_permissions` for app display, ebook, print and game
use; a compatible display licence leaves the other uses awaiting review. Public
catalogue rows contain no family uploads, memoir text or private reactions.

Set `MEMORY_SPARK_PHOTO_WEB_SEARCH=1` to add Responses-native LLM discovery
alongside the existing catalogues. It reuses the server-only gateway URL, model
and key and requires completed search receipts with source URLs; a plain model
answer cannot supply photo evidence. The API and private photo worker use the
same source inspection and capture-date checks as the
[memoir-place-photo-research helper](skills/memoir-place-photo-research/references/llm-web-search.md).
The option is disabled by default and requires a gateway/model with actual
`web_search` support. Discovered photos remain public memory references with
unresolved reuse rights.

The app's photo endpoint searches catalogues independently of local research
runs. When `GOOGLE_CSE_API_KEY` is blank it browses the configured
`GOOGLE_CSE_ID` or `GOOGLE_CSE_URL` with Crawl4AI, follows the visible image-result
links, and extracts photographs from their public source pages. When
`FLICKR_API_KEY` is blank, it browses Flickr's public search and item pages with
the same bounded crawler. The API image includes Crawl4AI and Chromium; for a
local Python server install `.[photo-browser]` and run
`python -m playwright install chromium`. Rebuild the API image after upgrading.
Blocked pages or browser failures leave the other catalogues available.
If none returns eligible photos and a provider fails, the endpoint reports
`UNAVAILABLE` with safe provider/reason diagnostics, and the gallery offers a
retry. It reports `NO_MATCH` only for completed, empty searches. An unrendered or
failed CSE widget is retryable, rather than a cacheable empty search. Configured
SerpAPI and CSE searches run concurrently; neither disables the other. An unavailable
legacy Google JSON API falls back to the public CSE browser. Provider configuration
and the search policy version separate cached results, so an older SerpAPI-only
result cannot suppress CSE research. Human verification
and search-page robots denials stop browser retries; they are not bypassed.
Source-page denials skip that original while later CSE result pages remain
eligible within the same research budget. Failed empty
searches are not cached, and the client invalidates the older empty-result cache.
The private `photo-worker` warms one Chromium process at startup and reuses it
across searches. Its separate 2 GiB container keeps browser memory outside the
API. Original source pages are checked two at a time; browser queries share the
warm process and fixed research budgets. Contexts and cookies are cleared between
searches. Set `MEMORY_SPARK_PHOTO_WORKER_SECRET` to a random server-only secret
outside local development. Google CSE combines verified aliases (currently
Chengde/承德) and years with uppercase `OR` in one query. For a narrow historical
range wholly inside one decade, its browser query includes that decade's Chinese
and English labels alongside years within ten years of the requested period.

Photo galleries enforce a 20 km radius around the selected coordinates and a
ten-year tolerance on either side of the selected year or range. Capture dates
and source coordinates must support the match; missing metadata, upload dates
and page revision dates cannot qualify a photo. The same checks apply to saved
photos, grouped-place fallbacks and every streamed page. Wikimedia originals,
thumbnails and file redirects share one identity; content fingerprints also
merge resized or rehosted copies and closely matching scenes.

Public photo research is persisted globally in Supabase `place_photo_search`,
keyed by search-policy version, normalized location and period. Any project requesting that key reuses
the full saved result set, including after a worker restart. Progressive batches
are saved independently of the browser; cursors remain bound to the project and
selected coordinates. Reference selection happens before pagination: use all
filters first, remove GPS/radius only for an empty result, then remove the time
filter only if the GPS-relaxed result is also empty. Source-backed place,
rights and attribution remain required; fallback photos carry explicit labels
and preserve their actual dates or date uncertainty. A provider failure during
dated research still allows the broader-date search; any provider failures stay
reported and the incomplete search remains retryable. Only the
trusted photo worker writes the cache with its server-side Supabase credential;
no memoir text, user ID, project ID, cookies or credentials enter its rows.
Apply the database baseline and configure
`SUPABASE_URL`/`SUPABASE_SECRET_KEY` on the photo worker. Saved historical results
do not expire with the in-memory 15-minute cursor cache. Current references are
checked against the recent capture window when restored. Completed empty searches
are reusable; provider failures remain retryable. An explicit request with
`refresh=true` starts fresh research. Page refresh and history hydration reuse
saved photos rather than invoking fresh discovery. Older search-policy results
are refreshed once so their previous filters cannot bypass the new limits.

Google cards are discovery leads. The source parser inspects image-specific
captions, structured capture metadata and MediaWiki file-description dates; a
missing date in the page title no longer discards dated images on that page.
Page publication dates, upload dates and Google preview thumbnails remain
insufficient photo evidence. Current Google queries include recent-year terms.

Source capture dates must fit the containing decade; a generic `80s` search hit
cannot establish the century. Google browser is skipped in the subsequent
decade fallback, including after a blocked search, because it already covered
both scopes. Flickr queries the original place language and verified aliases
separately. Other catalogues expand to the containing decade if fewer than ten
exact-period matches are found. Eligible photos rank by capture-year distance to
the selected place's context year, then date precision and GPS distance to that
place. Unknown years come last; missing GPS loses location ties. For 1983, exact
1983 captures precede 1982/1984, then more distant years. With only a decade or
range, captures within that window share temporal priority; undated current
context uses the current year. Source sites interleave only where relevance ties.
Wider matches retain their actual capture dates and reference labels. The supplied
Chengde Flickr album is also a bounded discovery source: its title establishes
location, never individual capture dates.
The initial result is filtered against the requested locality and capture period (or
the explicitly labelled containing-decade fallback);
without a period, the preceding 24-month current-photo window applies. Page,
upload and modification dates do not establish capture dates. Results are
deduplicated across providers by
asset ID, canonical original/thumbnail URLs and content hashes when available.
The gallery appends ten-photo pages when its bottom comes into view, with a
manual load/retry button. A bounded discovery pool (at most 150 matches) is
kept in memory for 15 minutes and persisted globally by public place/period,
making repeated searches across projects fast. Cursors remain project-bound. The client requests NDJSON and
displays verified batches immediately, keeping a loading indicator while the
remaining sources are checked. A bounded `photo_order` list promotes better
matches as they arrive; completed pages retain a stable relevance order. Context
year and coordinates scope cursors, while the public discovery pool remains
shared by place/period and can be ranked again without new provider calls.
Ordinary JSON clients receive completed pages. An expired cursor starts a new snapshot and
retains/deduplicates visible photos. Robots and research budgets still limit
coverage; scroll loading does not bypass them.
Eligible browser results retain source and capture-date metadata and are marked
`memory_reference_only`, with download, publish and print disabled. Unresolved
rights remain research leads with embedding disabled. Life-stage labels without years do not restrict
the automatic search; an explicit year/range still does.

To use Flickr's API alongside Wikimedia Commons and the Library of Congress,
set `FLICKR_API_KEY` in the server `.env` using your own Flickr application key,
then recreate the API and photo-worker services so Compose passes it through. Keep this key out of
browser configuration. Existing Google Custom Search JSON API customers can
set `GOOGLE_CSE_API_KEY` server-side; the public engine ID is already configured
as [`GOOGLE_CSE_ID=b2de41f6592f74c3e`](https://cse.google.com/cse?cx=b2de41f6592f74c3e)
and can be overridden. `GOOGLE_CSE_ID` identifies the search engine, not a
Google Cloud project; the Cloud project is the one that owns the API key. The
Programmable Search control panel therefore has no project selector. An API-key
restriction only limits which services a key may call; it does not grant the
project access to the Custom Search JSON API. Google image API
requests use the engine ID, `searchType=image`, rights filtering and ten-result
pagination. [Google's current documentation](https://developers.google.com/custom-search/v1/overview)
states that this API is closed to new customers and existing customers must
transition by January 1, 2027. See [the API research notes](docs/Historical_Photo_API_Research.md)
for sources, setup links and live coverage findings.

If a gallery appears empty, inspect the actual place-photo request's `period`
before testing a historical query. An empty period requests the preceding
24-month capture window. Merely naming a childhood place does not supply a
calendar year. The public CSE page also initially opens its Web tab; image
discovery selects Image and waits for rendered result cards. A working public
engine does not imply JSON API access or permission to display its results.

Flickr API queries use capture dates, bilingual Chengde/承德 terms and up to three
pages per term. API catalogues admit only supported CC BY, CC BY-SA, CC0 or public-domain-marked items
are admitted for embedding; noncommercial photos remain research leads. A bare
year such as `1980` means the ten-year window `1980–1989`; use `1980–1980` for
an exact year. The app reports a shortfall when
fewer than ten qualifying photographs are found; Google CSE API results are also
post-filtered by location, item date metadata and compatible licence after each
page. Adding an API does not guarantee coverage for every year and place.
