# PR9 + PR10 sanitized cloud test handoff

Continue from branch `codex/mac-pr9-pr10-validation-20261004`. Mac validation
was published at `741dc3797bf9e0ef5d7ee51c2977f9c011e92bf8`; its tested code
head is `4529258ad0f5a88e5c5fc019789c8f6f69f756ff`. The later focused repair
head is `90e28bc3f00506f225fcd4e5f46fa34986d0d154`; it has narrow receipts,
not a new complete-suite pass. This handoff is a documentation change. Read
[the Mac report](pr9-pr10-mac-validation.md) and
[its receipts](test-evidence/pr9-pr10-mac.json) before claiming acceptance.

This inventory comes from tracked `.env.example`, `compose.yml`, configuration
code and test fixtures. No laptop `.env` or credential file was read or copied.
No secret value, bearer token, service-role key, credential-bearing connection
URL or customer data was transferred. User-provided credentials belong in
secure cloud settings. This document does not configure them.

## Current controlled phase

The native/controlled suite requires **no external credentials**. Start in a
fresh isolated checkout and a clean environment with task-owned storage and
services. Leave all provider, Supabase, Stripe, voice, photo-provider and
Langfuse keys unset. Do not load a laptop `.env` or the deployed Compose
environment. Public UI assets may be read through the browser guard's explicit
GET/HEAD allowlist; these browser checks are not an air-gapped execution claim.

| Non-secret setting | Controlled test use |
| --- | --- |
| `MEMORY_SPARK_TEST_MODE=1` | Test auth and synthetic story storage |
| `MEMORY_SPARK_ENTITLEMENT_MODEL=legacy` | Existing acceptance suite contract; chapter tests explicitly opt in |
| `MEMORY_SPARK_SHOW_THINKING_STEPS=1` | Expected diagnostic UI in `browser_e2e` |
| `NEXT_TELEMETRY_DISABLED=1` | Build/test process setting |
| `MEMORY_SPARK_API_ORIGIN` | Fresh task-owned API origin, supplied **before** the production build |
| `MEMOIR_BROWSER_URL` | Fresh task-owned frontend origin; required for all 48 pytest UI cases |
| `MEMOIR_TEST_URL` | That frontend origin plus `/memoir`, used by standalone profile tests |
| `MEMOIR_NETWORK_RECEIPT` | Unique receipt filename per attempt |
| `MEMOIR_BROWSER_PROFILE_FIXTURE=1` | Standalone journeys only; leave unset for native pytest router/worker cases |
| `PLAYWRIGHT_BROWSERS_PATH` | Optional task-owned Chromium cache |
| `MEMOIR_TEST_POSTGRES_BACKEND` | Leave **unset** on Linux; `apple-container` is the Mac backend |
| `MEMOIR_RENDERER_FIXTURES`, `MEMOIR_RENDERER_EXPECT_FALLBACK` | Optional additional renderer checks; not exercised by the final Mac batch |

The guard lives in `tests/fixtures/browser_network_guard.py`. It permits the
explicit frontend/API origins and public reads from `unpkg.com`,
`cdn.jsdelivr.net`, `cesium.com`, `fonts.googleapis.com` and
`fonts.gstatic.com`. It records only origins, paths and methods. A zero blocked
count is required for normal scenarios. The explicit `--check` canary is the
one intentional blocked request.

## Linux dependencies and service assumptions

- Match the recorded Python 3.12.11 and Node 26.10 environment where possible;
  use the declared Python extras and locked web dependencies. The Mac receipts
  record the actual installed versions. Linux execution has not been verified
  in this Mac session.
- `initdb`, `pg_ctl` and `psql` must be on PATH, with an existing non-root
  execution account. Prefer PostgreSQL 18.3 to match the stock Mac fixture;
  record the actual version. Root/missing tools cause skips, which are blockers
  for complete native coverage rather than passes.
- `tests/test_agent_commit_postgres.py::database` creates a unique temporary
  data directory and Unix socket, uses trust only inside that synthetic fixture,
  disables TCP (`-h ''`) and stops its own cluster in `finally`. No shared
  database or Supabase connection is required. The application RPC tests use
  actual PostgreSQL behind a controlled PostgREST transport.
- **Portability repair requiring native cloud confirmation:** the transport
  test captures initial `current_user` instead of assuming `postgres`. A safe
  SQL-boundary assertion double went red/green for another account; native
  Linux PostgreSQL was not run. Preserve role-reset, rollback, first-error and
  concurrency assertions.
- Actual Temporal tests use `WorkflowEnvironment.start_local`, task SQLite
  files, loopback ports, UI disabled and context-managed shutdown. The cache
  path is `/tmp/memoir-issue6-temporal`; fetch the Linux SDK test binary there
  using the supported SDK path. Do not copy the Mac executable or point these
  tests at shared Temporal. A separate continuously running application worker
  is unnecessary for the controlled suite.
- Install Chromium and its Linux system dependencies. Tests use synthetic
  narrator/provider/photo data and controlled app-server subprocesses.
  A live Codex CLI, Crawl4AI worker, paid billing service and external judge
  are unnecessary for this phase.
- Launch an isolated FastAPI and production Next server. Allocate two unused
  ports and track their exact process groups. Next compiles the API origin into
  its rewrites; the default port 8000 must never select a shared service.

The parent reported that the currently available cloud runtime lacks native
PostgreSQL and Chromium launch encounters socket EPERM. Do not bypass host
security or count missing prerequisites as passes. Full cloud E2E awaits a saved
coding environment with supported native tools/browser execution.

## Reproducible commands

Use a task directory and clean shell. The following preparation installs public
dependencies only; no `.env` is sourced. An existing cloud runtime may already
provide Python, Node, PostgreSQL and Chromium system packages.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install '.[test,evaluation]' 'httpx[socks]'
npm --prefix apps/web ci
.venv/bin/python -m playwright install chromium
```

In the isolated test shell, set the four fixed controlled flags in the table,
put `.venv/bin` and the selected Node/PostgreSQL tools on PATH, and set
`TASK_API_PORT` and `TASK_WEB_PORT` to fresh unused ports. Set the three origin
variables from those ports, rather than copying retired Mac endpoints:

```sh
export MEMORY_SPARK_TEST_MODE=1 MEMORY_SPARK_ENTITLEMENT_MODEL=legacy
export MEMORY_SPARK_SHOW_THINKING_STEPS=1 NEXT_TELEMETRY_DISABLED=1
export MEMORY_SPARK_API_ORIGIN="http://127.0.0.1:${TASK_API_PORT:?}"
export MEMOIR_BROWSER_URL="http://127.0.0.1:${TASK_WEB_PORT:?}"
export MEMOIR_TEST_URL="$MEMOIR_BROWSER_URL/memoir"
```

Start the API in its own supervised terminal/session, then build and start Next
in another owned session. Do not inherit secret environment variables:

```sh
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port "$TASK_API_PORT"
npm --prefix apps/web run build
npm --prefix apps/web run start -- --hostname 127.0.0.1 --port "$TASK_WEB_PORT"
```

Before a browser run, inspect `apps/web/.next/routes-manifest.json`: both
`/api/v1/memoir` rewrite destinations must begin with the exact task API origin.
Read only `auth_mode` from the proxied `/api/v1/memoir/agent/config` response
and require `test`; do not dump the config response in a credentialed session.
Run the native/full checks serially with receipt and JUnit output:

```sh
mkdir -p output/cloud-validation
MEMOIR_NETWORK_RECEIPT=cloud-native-network \
python tests/fixtures/browser_network_guard.py pytest -q \
  --junitxml=output/cloud-validation/native.xml
node --test skills/memoir-composer/tests/*.test.mjs tests/js/*.test.mjs
python -m compileall -q apps scripts tests
python scripts/check_localization_catalog.py
node apps/web/scripts/check_localization_icu.mjs
python scripts/audit_spec_routes.py
```

The full Mac suite collected 975 cases. Only the four explicitly opted-out live
follow-up cases should skip in this controlled phase. Every failure, additional
skip or setup error must retain its cause and receipt. Do not aggregate unchanged
targeted rechecks into a green complete run. The final Mac counts remain
966 passed / 5 failed / 4 skipped / 0 errors.

Replay all 29 standalone commands from `test-evidence/pr9-pr10-mac.json`,
substituting the cloud-owned frontend for each old `--base-url` argument and
using the clean controlled environment. Set
`MEMOIR_BROWSER_PROFILE_FIXTURE=1` for these commands. Keep `--locale all` on
the ten-turn/progressive cases, `--expect-thinking-steps` on `browser_e2e`,
and the separate `--blocked` photo / `--with-gallery` map variants. For example:

```sh
MEMOIR_BROWSER_PROFILE_FIXTURE=1 \
MEMOIR_NETWORK_RECEIPT=cloud-image-lifecycle-network \
python tests/fixtures/browser_network_guard.py \
  tests/browser_workspace_image_lifecycle.py --base-url "$MEMOIR_BROWSER_URL"
```

Capture Git SHA/tree **before** starting each run and persist the child's exit
code even if later metadata commands fail. Use unique attempt filenames and
clear provenance: the final Mac image-lifecycle receipt is unconfirmed, and an
older passing receipt cannot stand in for a new attempt. The guard writes its
network JSON under the legacy directory name `output/mac-validation`; retain
or copy that fresh file with the corresponding cloud receipt. Optional pinned
real-renderer and forced-fallback checks were prepared but not run on Mac;
cloud may add them with separate results.

The later redirect repair has 18 narrow native Mac canary passes. It uses the
supported Chromium CDP response-header API for known main-frame pages and an
**explicit harness restriction** elsewhere: initial popup/child-frame requests
use finite `Route.fetch(max_redirects=0)` responses, and all redirects there are
denied, even if their destination would otherwise be allowed. Ordinary static
popup/frame documents still load; main-page redirects/streams stay native.
A strict Location grammar rejects missing authorities, special-scheme leniency,
extra authority slashes, authority credentials/invalid ports, backslashes and
whitespace/control forms before resolution. A 20-case offline WHATWG-origin
check passes (9 accepted, 11 rejected). This bounded policy is not proof of full
native popup/iframe semantics.
Real OOPIF and worker/service-worker response coverage remain unverified; no
separate iframe target was observed in the native cross-site canary.

Run the canaries directly, without the outer guard wrapper: they create their
own fresh allowed origin and owned sink, then install the guard. They never
contact a shared endpoint. Capture per-case receipts rather than relying on a
shell loop's last exit code:

```sh
for canary_case in get post get-chain allowed-get allowed-post allowed-navigation stream \
  popup backslash-get backslash-post popup-static iframe iframe-static iframe-fetch \
  triple-get triple-post http-triple-get http-triple-post
do
  python tests/fixtures/browser_guard_redirect_canary.py --case "$canary_case" || exit
done
python tests/fixtures/redirect_url_policy_check.py --node node
```

See [the focused repair evidence](test-evidence/pr9-pr10-mac-review-repairs.json)
for source hashes, red/green results and the precise scope limits. The full
native suite and original 29-scenario batch still need post-repair cloud runs.

At completion, close browser contexts, let PostgreSQL/Temporal fixture cleanup
finish, and stop only the tracked task API/Next process groups. Confirm owned
ports are clear and retain the isolated checkout/results. Do not clean unknown
processes, containers, IPC objects or change host limits to hide resource errors.

## Configuration names for the later live phase

These are **names and purposes only**, not authorization to run live providers.
Non-secret values must be chosen for the new isolated cloud environment; any
URL containing credentials or sensitive query parameters belongs in secure
settings instead. No model/provider/judge choice is inferred from laptop values
or repository defaults.

| Non-secret name group | Purpose |
| --- | --- |
| `MEMORY_SPARK_MODE`, `MEMORY_SPARK_REGION`, `MEMORY_SPARK_API_PORT`, `MEMORY_SPARK_WEB_PORT`, `MEMORY_SPARK_LLM_NETWORK`, `MEMORY_SPARK_COOKIE_SECURE` | New isolated deployment metadata, task port mappings/network names and cookie policy; do not copy Mac service assumptions |
| `MEMORY_SPARK_LLM_BASE_URL`, `MEMORY_SPARK_LLM_MODEL`, `MEMORY_SPARK_LLM_REASONING_EFFORT` | Approved cloud conversation provider and model |
| `MEMORY_SPARK_MEMOIR_COMPOSER_MODEL`, `MEMORY_SPARK_MEMOIR_COMPOSER_REASONING_EFFORT` | Approved composer model/budget |
| `MEMORY_SPARK_CODEX_BIN`, `MEMORY_SPARK_CODEX_VERSION`, `MEMORY_SPARK_CODEX_HOME`, `MEMORY_SPARK_CODEX_PRIVDROP_BIN`, `MEMORY_SPARK_CODEX_WORKER_TIMEOUT` | Isolated Linux worker runtime and tenant homes; Linux uses `setpriv` by default |
| `MEMORY_SPARK_CODEX_WORKER_URL`, `MEMORY_SPARK_TASK_STORE_URL`, `MEMORY_SPARK_PHOTO_WORKER_URL` | Private task-owned service origins, reachable from the calling service |
| `MEMORY_SPARK_TASK_DB`, `MEMORY_SPARK_OBJECT_STORE_PATH`, `LOCAL_OBJECT_STORE_PATH` | Fresh task-owned SQLite/object locations; template and runtime use different object-store names |
| `MEMORY_SPARK_TEMPORAL_ADDRESS`, `MEMORY_SPARK_TEMPORAL_NAMESPACE`, `MEMORY_SPARK_TEMPORAL_TASK_QUEUE`, `MEMORY_SPARK_WORKER_ID` | Isolated durable task worker/Temporal setup |
| `SUPABASE_URL`, `SUPABASE_JWKS_URL`, `SUPABASE_STORAGE_BUCKET` | User-selected synthetic-only development auth/RLS/storage project |
| `MEMORY_SPARK_LANGFUSE_BASE_URL`, `MEMORY_SPARK_LANGFUSE_ENVIRONMENT` | User-selected tracing service/environment |
| `MEMORY_SPARK_APP_REVISION` | Exact reviewed code identity in evaluator metadata |
| `MEMORY_SPARK_FREE_RECALL_ROUNDS`, `MEMORY_SPARK_PRIVATE_DRAFT_CADENCE`, `MEMORY_SPARK_PRIVATE_DRAFTS_ENABLED`, `MEMORY_SPARK_MEMOIR_RUN_SECONDS`, `MEMORY_SPARK_MEMOIR_PREPARATION_CONCURRENCY`, `MEMORY_SPARK_OUTBOX_POLL_SECONDS` | Approved product cadence/concurrency/deadline settings |
| `OPENAI_BASE_URL`, `MEMORY_SPARK_STT_MODEL`, `MEMORY_SPARK_TTS_MODEL`, `MEMORY_SPARK_REALTIME_MODEL`, `MEMORY_SPARK_REALTIME_VOICE` | Optional voice integration |
| `MEMORY_SPARK_PHOTO_WEB_SEARCH`, `GOOGLE_MAPS_GEOCODING_URL`, `GOOGLE_CSE_URL`, `GOOGLE_CSE_ID` | Optional real photo research/geocoding configuration |
| `MEMORY_SPARK_PUBLIC_URL`, `MEMORY_SPARK_PRINT_COUNTRIES`, `STRIPE_SUCCESS_URL`, `STRIPE_CANCEL_URL`, `STRIPE_PRICE_ELECTRONIC`, `STRIPE_PRICE_PRINTED`, `STRIPE_PRICE_FAMILY`, `STRIPE_PRICE_ADDITIONAL_BOOK` | Optional isolated billing/output configuration |

| Secret/key name | Purpose / when needed |
| --- | --- |
| `MEMORY_SPARK_LLM_API_KEY` | Approved live model provider authentication |
| `MEMORY_SPARK_CODEX_WORKER_SECRET` | Matching trusted API/worker/task-store authentication |
| `MEMORY_SPARK_PHOTO_WORKER_SECRET` | Matching photo worker authentication when used |
| `SUPABASE_PUBLISHABLE_KEY` | Development browser/auth project key; enter through secure configuration, no laptop copy |
| `SUPABASE_SECRET_KEY` | Canonical trusted lane broker/server authentication; keep outside tenant runtimes |
| `SUPABASE_DB_URL` | Credential-bearing URI only if isolated synthetic database administration requires it; not needed by native fixtures |
| `OPENAI_API_KEY` | Optional real voice integration |
| `MEMORY_SPARK_LANGFUSE_PUBLIC_KEY`, `MEMORY_SPARK_LANGFUSE_SECRET_KEY` | Tracing project authentication |
| `FLICKR_API_KEY`, `GOOGLE_CSE_API_KEY`, `GOOGLE_MAPS_GEOCODING_API_KEY`, `GOOGLE_MAPS_BROWSER_API_KEY` | Optional real photo research/maps; browser key requires appropriate restrictions |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | Optional isolated billing integration; not needed for controlled billing tests |

Langfuse supports SDK aliases `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`,
`LANGFUSE_HOST`, `LANGFUSE_BASE_URL` and `LANGFUSE_TRACING_ENVIRONMENT`; the
adapter maps Memoir names to the SDK and checks auth. Durable ClickHouse
DateTime64 readback is still unresolved; successful authentication/submission
alone is insufficient. No tracing credentials were inspected for this handoff.

The older `SUPABASE_SERVICE_ROLE_KEY` name appears in test/tool compatibility
paths; the canonical trusted broker reads `SUPABASE_SECRET_KEY`. Do not silently
substitute a deployed project or transfer existing keys. The repository Compose
topology includes API, Next, Codex/photo/task workers and Temporal, but its
network names, volumes, provider defaults and ports require a new isolated cloud
topology. Native cloud pytest needs only the ephemeral fixtures and API/Next
pair described above. The Mac Apple Container executable/socket, cached Darwin
Temporal binary, loopback services and retired ports are local assumptions, not
portable resources.

## Acceptance gates preserved

Independent cloud review of the final pushed branch comes before another live
provider/source-claim pilot or the five separate 50-round datasets. Cloud must
also resolve complete-suite reliability, confirm native role portability and
the post-repair browser batch, and confirm the previously unconfirmed
image-lifecycle attempt. Guard scope limits must remain explicit until verified.
Keep canonical MemoryEvents,
original narrator sources, explicit attributed/timing vetoes, null-claim
rejection and cN validation/metadata stripping assertions intact.

For the later five-by-fifty phase, secure approved credentials/configuration
first, then verify actual invocation/output coverage for all seven memoir
skills, all life stages, browser behavior and durable Langfuse readback on
synthetic isolated data. Do not invent a judge endpoint/model/configuration.
The existing five-case runner defaults its `--env-file` to `.env`; when using
secure environment injection, pass `--env-file /dev/null` to prevent reading an
unintended local file. Do not put secret flags in command lines or logs. Its
current judge result remains `unavailable` until an approved judge integration
is established. Earlier live baselines and diagnostic pilots remain distinct
from new acceptance results.
