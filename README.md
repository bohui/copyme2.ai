# CopyMe2

CopyMe2 is the platform umbrella: **preserve the parts of you that matter**. The first live product is Memoir, a guided, source-linked memoir journey that turns memories, photographs, and the storyteller's own voice into a family book.

Memoir recall includes 20 successful conversation replies by default. Set the
positive integer `MEMORY_SPARK_FREE_RECALL_ROUNDS` to change this allowance.
Usage belongs to the user across projects and is recorded atomically with each
saved reply; failed replies do not consume it. Once exhausted, the interview
shows package selection and resumes only after a verified paid entitlement.
Customer-facing copy does not show the free-round allowance.

The development database starts with a consolidated schema baseline and uses
incremental migrations for later changes. Run `make migrate` to apply pending
changes through Supabase's tracked migration history.
For a disposable development database after changing the schema baseline, use
`supabase db reset --db-url "$SUPABASE_DB_URL" --yes`; this recreates the
schema and applies the baseline and subsequent migrations.

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

Memoir interviews default to the ChatGPT subscription pool through LiteLLM's
`gpt-5.6-luna-pooled` route, backed by `codex-lb`, with
`MEMORY_SPARK_LLM_REASONING_EFFORT=max`. Preview and private memoir composition
use `legal2ai-luna-low` with low reasoning by default, so drafting does not
inherit the interview's slower max setting. Set
`MEMORY_SPARK_LLM_BASE_URL` to the provider network's current gateway on port
4000; the LiteLLM gateway and `codex-lb` must both be running. Keep the Memoir
consumer key in `MEMORY_SPARK_LLM_API_KEY` authorized for both model routes; the
`codex-lb` key stays in the provider stack.

### Public hostname through Cloudflare Tunnel

The local Apple Container stack can serve [https://copyme2.ai](https://copyme2.ai)
through the dedicated `copyme2-memoir` tunnel. A macOS launch agent keeps
`cloudflared` running and forwards the hostname to the Next.js frontend on
`127.0.0.1:3010`; Next.js forwards `/api/v1/memoir/*` to the private API.

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
launch agent starts at user login; the container stack must also be running and
this Mac must remain awake and online. See
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
`worker`, and `temporal`. `container-up` recreates all six containers;
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
definitions are preserved. `public.place_photo_searches` is preserved, including
its search keys, public photo results and update times. A preflight rejects
foreign-key/partition dependencies that would pull this table into `CASCADE` or
Auth deletion, before stopping services or clearing Storage/files. Per-run
SerpAPI/CSE metadata under `search-cache/` in photo-research run directories also
remains outside the user-file reset paths. This command leaves the web/API stopped;
service recovery is a separate action. `supabase db reset` recreates schemas and
does not offer this cache-preservation guarantee; use it only for an intentional
full schema reset. Use
`ENV_FILE=path/to/.env` to load a different file.

High-level Codex activity is hidden from storytellers by default. For local debugging only, set `MEMORY_SPARK_SHOW_THINKING_STEPS=1`; the browser then shows the opt-in "Thinking steps" summary while private model reasoning remains hidden.

### Langfuse trajectory evaluation

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

The project skill at [`skills/memoir-place-journey/SKILL.md`](skills/memoir-place-journey/SKILL.md) turns an explicitly named, coarse place into a durable Earth-to-place workspace journey. The API validates the skill's `MEMORY_SPARK_PLACE_JOURNEY` marker, rejects markers not grounded in the current storyteller message, removes accepted markers from the spoken reply, persists the current versioned record in Supabase, and returns both `place_journey` and a `place_journey_change` envelope; the Memoir browser reveals and hydrates that record only after the current project has been activated by an explicit place cue, then uses CesiumJS `camera.flyTo` with Google Geocoding and Google 2D roadmap imagery when the matching server and browser keys are configured. The opening globe fits the map panel, and arrival finishes in a north-up 2D map at a scale appropriate to the place. Reduced-motion preferences skip the flight. Google keys are split by trust boundary: `GOOGLE_MAPS_GEOCODING_API_KEY` stays server-side and `GOOGLE_MAPS_BROWSER_API_KEY` is restricted to the web origin and Map Tiles API. The application still keeps places approximate and falls back to saved parents or the hierarchy view without treating a location as biographical fact. The finest supported location is a named suburb or town. Hospitals, schools, streets, compounds, and generic labels stay in the story; an explicitly named containing city or suburb becomes the journey location. The parser normalises `地球` to the canonical `Earth` root and accepts every grounded place in a message. Local Compose mounts the place skill into both the API and private Codex worker so restarting those services loads the current contract; built images retain a copy for deployment. Photo searches use a calendar period only for the place it describes and report `place-photo-research` progress in Thinking steps.

The background [`memoir-place-groups` skill](skills/memoir-place-groups/SKILL.md) checks every new place preview, confirmed update, and restored history against existing city groups. `POST /v1/projects/{project_id}/place-groups` uses public hierarchy and cached geocoder administrative metadata without another model call. A city's named suburbs, towns, and administrative districts share one map with independent pins; another city creates another choice. Original location records, stages, and photographs stay distinct. Partial matches and missing child coordinates remain visibly pending, rather than receiving the parent's centre coordinates. The newest mention is checked first, and stale responses cannot overwrite a correction or another project's workspace. Grouping and photo requests run independently of the conversation stream.

In Google Cloud, enable billing plus the [Geocoding API](https://developers.google.com/maps/documentation/geocoding) and [Map Tiles API](https://developers.google.com/maps/documentation/tile). Create a server-restricted key for geocoding and a separate HTTP-referrer-restricted browser key for Map Tiles, then place them in the two environment variables above. Google 2D Tiles must be paired with Google geocoding; the app does that through the server place-map endpoint rather than a model tool call.

### Family tree and author timeline in the integrated Codex worker

The project skills at [`skills/memoir-family-tree/SKILL.md`](skills/memoir-family-tree/SKILL.md) and [`skills/memoir-author-timeline/SKILL.md`](skills/memoir-author-timeline/SKILL.md) are loaded only after the server confirms a paid Family legacy entitlement backed by `STRIPE_PRICE_FAMILY`. The family-tree skill emits and validates `MEMORY_SPARK_FAMILY_TREE` for people and relationships; the author-timeline skill emits and validates `MEMORY_SPARK_AUTHOR_TIMELINE` for the author's events and life periods. Both persist into the shared, versioned `family_context` document under the authenticated Supabase user and Memoir project, and the response's `family_context_update.skills` field identifies which skill changed it. Unpaid, pending, revoked, and non-Family packages receive neither skill; uncertain dates and relationships remain explicit.

Apply the checked-in schema before using the connected agent:

```bash
make migrate
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

When upgrading from API-hosted Codex, drain and stop **all old API/Codex writers**
before starting the new worker. Compose mounts the old `var/memory-spark/codex-users`
directory read-only; the worker atomically imports each user's complete offline
home (including SQLite/WAL and rollouts) on first use. Existing worker homes are
never overwritten, and the original files remain intact. Keep the legacy mount
until every existing user has migrated. Run `make migrate` before starting the
updated API; the consolidated schema intentionally has no unfenced-save fallback.

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
make memoir-progressive-test
python3 scripts/run_acceptance_evidence.py
python3 scripts/audit_spec_routes.py
```

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

The app's photo endpoint searches catalogues independently of local research
runs. When `GOOGLE_CSE_API_KEY` is blank, it automatically browses the configured
`GOOGLE_CSE_ID` or `GOOGLE_CSE_URL` with Crawl4AI, follows the visible image-result
links, and extracts photographs from their public source pages. When
`FLICKR_API_KEY` is blank, it browses Flickr's public search and item pages with
the same bounded crawler. The API image includes Crawl4AI and Chromium; for a
local Python server install `.[photo-browser]` and run
`python -m playwright install chromium`. Rebuild the API image after upgrading.
Blocked pages or browser failures leave the other catalogues available.
If none returns eligible photos and a provider fails, the endpoint reports
`UNAVAILABLE` with safe provider/reason diagnostics, and the gallery offers a
retry. It reports `NO_MATCH` only for completed, empty searches. Human verification
and robots denials stop browser retries; they are not bypassed. Failed empty
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

Public photo research is persisted globally in Supabase `place_photo_searches`,
keyed by search-policy version, normalized location and period. Any project requesting that key reuses
the full saved result set, including after a worker restart. Progressive batches
are saved independently of the browser; cursors remain bound to the project and
selected coordinates. Radius filtering happens before pagination. Only the
trusted photo worker writes the cache with its server-side Supabase credential;
no memoir text, user ID, project ID, cookies or credentials enter its rows.
Apply migration `202610020003_place_photo_searches.sql` and configure
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
exact-period matches are found. Completed results place exact-period matches
first; streamed batches keep their arrival order. Wider matches retain their capture dates and show a
same-decade reference label. The supplied Chengde Flickr album is also a bounded
discovery source: its title establishes location, never individual capture dates.
Every result is filtered against the requested locality and capture period (or
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
remaining sources are checked. Streamed results retain stable arrival order;
ordinary JSON clients still receive completed pages. An expired cursor starts a new snapshot and
retains/deduplicates visible photos. Robots and research budgets still limit
coverage; scroll loading does not bypass them.
Browser results retain source and capture-date metadata and are marked
`memory_reference_only`, with download, publish and print disabled. Unresolved
rights remain labelled unknown. Life-stage labels without years do not restrict
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

Flickr API queries use capture dates, bilingual Chengde/承德 terms and up to three
pages per term. API catalogues admit only supported CC BY, CC BY-SA, CC0 or public-domain-marked items
are admitted for embedding; noncommercial photos remain research leads. A bare
year such as `1980` means the ten-year window `1980–1989`; use `1980–1980` for
an exact year. The app reports a shortfall when
fewer than ten qualifying photographs are found; Google CSE API results are also
post-filtered by location, item date metadata and compatible licence after each
page. Adding an API does not guarantee coverage for every year and place.
