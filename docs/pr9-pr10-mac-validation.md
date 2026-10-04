# PR9 + PR10 Mac integration validation

This is the native/offline handoff for cloud review. Live provider evaluation,
the new source-claim pilot, and the five separate 50-round datasets remain a
later phase coordinated by the parent session.

## Identity and scope

- Cloud base: `d11a25389edabfd5e0f5d0e92a74174b0bf7badb`.
- Cloud tree: `b687763efee2c86bc6043ea166402cd947514a30`.
- Ordered parents: PR9 `84366778f50495d065e794a00f16184d16dc4216`, then PR10
  `90dee1f2be4f6a83fbc44e779f8d2e91106c6061`.
- Mac branch: `codex/mac-pr9-pr10-validation-20261004`.
- Broad-run code head: `4529258ad0f5a88e5c5fc019789c8f6f69f756ff`.
- Broad-run code tree: `d3424e73be7ed3f3636b81744e5df5ca302a2926`.
- Later focused repair head: `90e28bc3f00506f225fcd4e5f46fa34986d0d154`.
- Focused repair tree: `dd3da78128f716c9e6318a6918afe6b4c1335d5b`.

The broad Python/JavaScript/29-browser counts belong to the broad-run head.
Independent cloud review subsequently requested the narrow repairs described
below. They have separate receipts and were not followed by another broad Mac
run. Documentation/evidence commits follow the focused repair head.

The cloud branch SHA/tree and parent order were checked against the published
ref. Work used a fresh isolated worktree. The original dirty checkout and the
older Issue2/Issue6 worktrees were left in place; final preservation checks are
recorded in the accompanying evidence.

Changes are test dependencies, test fixtures, and this report. The application,
migration and skill trees are identical to the cloud base:

| Path | Git tree |
| --- | --- |
| `apps` | `ecbbb7b75630ab1187c2bfaef0b85d5ff8d6a09a` |
| `supabase` | `2e49d91944dcd5341f50a963fcda62fbb92e0dc2` |
| `skills` | `1bfa049f95023bcb2424ebb22e568b604e12304f` |

Canonical MemoryEvents, accepted narrator sources, explicit event vetoes,
attributed/timing evidence, null-claim rejection, cN validation, and metadata
stripping retain the integrated implementation and its assertions.

## Fixtures repaired with red/green checks

The inherited quota fake omitted `accept_narrator_source`. Sixteen photo tests
monkeypatched a module absent from both PR9 and the integrated tree. Removing
that obsolete patch exposed stale expectations: a bare year follows the existing
decade search contract, while an explicit equal-year range remains authoritative.
The fixes preserve that policy and do not import the excluded PR8 implementation.
The test extra now declares `jsonschema`.

JavaScript fixtures now load their real helper dependencies and supply valid
capture dates, coordinates and cache-policy metadata. Assertions still cover
pagination, deduplication, retries, period isolation, source eligibility, history,
and paid/free workspace tabs. Browser fixtures similarly use the current
localized copy, readiness names, explicit artwork preference, and paginated
chapter view. Pagination measures scroll after Playwright has brought the retry
control into view, so its own automatic scrolling cannot invalidate the premise.

The standalone family/timeline journeys read canonical `/story/events` through
the public API seam and check original evidence. The 10/30/31-turn journeys
assert original `conversation_text`, `narrator_chat`, and absence of duplicate
legacy memory-answer calls. The ten-turn test holds a real NDJSON stream open
until its streaming assertions finish. External profile, model, auth, media,
photo research and renderer boundaries are synthetic where the scenario controls
them. Separate PostgreSQL browser tests exercise the actual router, worker,
source persistence, draft polling, corrections and fenced commits.

The disposable PostgreSQL fixture reuses psql transports to reduce Apple
Container stream pressure. Concurrent SQL calls retain separate sessions. Each
call resets roles/settings, rolls back an unfinished transaction, and preserves
ON_ERROR_STOP; genuine SQL errors are not retried. Its boundary test checks role
reset, rollback, stopping at the first error, and subsequent reconnection. The
later portability repair captures initial database identity before SET ROLE
instead of assuming every native non-root runner initializes `postgres`.
Screenshots now use the isolated output directory or pytest's `tmp_path`.

## Environment and isolation

Python 3.12.11, Node 26.10, locked Next 16.3.6/React 19.3, Playwright Chromium,
and Temporal SDK 1.34 were used. Host PostgreSQL initialization was blocked by
exhausted SysV slots. Tests instead used Apple Container 1.4.1 and cached stock
`postgres:18.3`, image index
`sha256:7e32e9833a6fb1c92c32552794cb6ed569d51b445a54907d35fc112ef39684db`.
Each fixture creates a UUID container with no shared mounts or published ports,
TCP disabled, psql through container exec, and exact-ID cleanup. Temporal uses
the existing cached native binary, a task SQLite database, random loopback port,
and context-managed shutdown.

Checks ran with a whitelisted environment, test mode, legacy entitlement mode,
and controlled provider commands. No real credentials were printed, copied or
created. No shared services were restarted, unknown IPC/processes cleaned up,
host settings changed, PRs/main merged or retargeted, migrations applied to
production, or live provider runs initiated.

The production build must receive the task API origin at build time. Both
compiled Memoir rewrite rules were inspected, and a proxied config read
confirmed test mode before the final guarded runs. The browser network fixture
allows only the explicit task frontend/API origins and GET/HEAD reads from
listed public UI asset hosts. It also guards route continuations/fetches and
browser API requests; redirect following is disabled for direct fetches. Its
initial direct-request canary aborted an unapproved request before network
access. It did not cover Chromium's automatic redirects; see the later native
redirect checks below. Standalone runs opt
into synthetic private-profile and default photo-lookup fixtures; scenario mocks
take precedence.

An earlier build had baked in default port 8000. A bounded read-only audit of
existing access logs found five Memoir profile GETs and five project POSTs,
all 404, at an unrelated control API. Attribution is inferred from namespace,
counts and ordering; the access records have no request timestamps/IDs. The
mounted source declared no Memoir or catch-all route. No successful project or
model operation was evidenced. Owned runners/services were stopped, the frontend
was rebuilt with its own API origin, and the network guard was added before
continuing. No further request was sent to that shared service.

## Results

Final counts and commands are recorded in
[`test-evidence/pr9-pr10-mac.json`](test-evidence/pr9-pr10-mac.json).
The final evidence distinguishes successful runs, opt-in skips, failed attempts,
and interrupted attempts. Counts from overlapping targeted runs are not added
together as new test cases.

The first complete run at `866e4341f2ccd961f9ccae85ec413ef0542dedd8`
collected 975 cases: **970 passed,
1 failed, 4 skipped, 0 errors**. The sole failure was protected-draft enrichment:
`OSError: [Errno 23] Too many open files in system` at `os.pipe()` while starting
the third controlled composer subprocess. The exact case then passed unchanged
in a fresh disposable fixture. Earlier build/native attempts also encountered
host ENFILE; an earlier 124-case PostgreSQL run had 123 passes and one runtime
failure. Those attempts remain failures in the evidence. No application retry
or relaxed claim/event validation was introduced to hide them.

The subsequent complete run at the tested code head collected the same 975
cases: **966 passed, 5 failed, 4 skipped, 0 errors**. One failure was another
explicit ENFILE in `os.pipe()`. Three controlled-provider operations returned
`retry` rather than `saved`; their underlying child failure causes were not
proven. The Temporal interruption case observed three timeline invocations
instead of two while extracted coverage reached 20. All five cases then passed
unchanged in one fresh-fixture recheck (**5 passed, 0 failures/errors**).
Neither complete run is reported as green, and those targeted passes are not
added to the full-run pass count. Full-suite reliability remains unresolved.

The final standalone batch has **28 confirmed passes / 1 unconfirmed result**
across 29 scenarios. The image-lifecycle runner's final `git rev-parse HEAD`
lookup died with SIGABRT before saving its receipt. Its current test log was
empty and its old passing receipt was stale, so that earlier pass is not used
as this attempt's result. The scenario passed in earlier targeted/batch runs.
The final batch has no recorded browser network violations. No further heavy
Mac suite was launched after the user's request to move development to cloud.
The later expressly requested canaries were narrow owned-service checks.
Downloaded pinned renderer assets were retained, but the planned additional
real-library/fallback checks were not launched and are not counted as passes.

The four skips are the opt-in live follow-up cases in
`tests/test_interview_followups.py`, covering current-message/earlier-context
inputs in zh-CN/en-AU. They require the configured provider and are not passes.
The suite reports one upstream Starlette TestClient/httpx deprecation warning.

The native group includes 124 PostgreSQL fixture-group cases, 6 actual Temporal
cases and 48 controlled UI cases, of which 16 traverse actual PostgreSQL and
application routers/workers. The 42 `test_place_photo_browser.py` cases are API
photo eligibility tests, not additional Playwright UI cases. The 26 integrated
contracts, evaluator/runtime/source tests, 173 JavaScript tests (62 composer),
production build, compilation, localization/ICU and route audit are separately
identified in the evidence.

| Check | Result |
| --- | --- |
| Final native Python attempt | 966 passed / 5 failed / 4 skipped / 0 errors |
| Unchanged native failure-boundary recheck | 5 passed / 0 failed / 0 errors |
| Final standalone browser batch | 28 confirmed passed / 1 unconfirmed |
| JavaScript, including composer | 173 passed, including 62 composer |
| Production build, compile, localization/ICU, route audit | Passed at the heads recorded in the evidence |

The original dirty checkout and both older worktrees retained their exact HEAD,
NUL-delimited porcelain status digest, and tracked diff digest. Task API and
frontend process groups were stopped, and their ports had no remaining
listeners. No task PostgreSQL container remains; Temporal test contexts exited.
No unknown process or IPC object was removed. The isolated worktree and ignored
receipts remain available for inspection.

## Later independent cloud review repairs

The SQL transport boundary test now captures initial `current_user` before SET
ROLE and asserts restoration to that identity after normal/error calls. A safe
external SQL-boundary double using baseline `cloud_runner` failed before the
repair and passed afterward. This validates assertion portability, **not native
PostgreSQL/Linux execution**. Rollback, first-error and concurrency contracts
were retained.

Cloud review found Chromium's automatic redirect continuation in the
[primary Playwright source](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/server/chromium/crNetworkManager.ts).
Native GET 302 and POST 307 each reproduced an owned unapproved sink request with
an empty blocked list. A later initial `window.open` popup and literal two-
backslash GET Location also reproduced sink requests. The raw-backslash POST
red check had zero sink requests but no explicit block record; its underlying
native failure cause was not proven. Forward-slash authority forms `///host`
and `http:///host` subsequently reproduced GET sink requests. Their POST red
attempts similarly had no sink hit and no explicit enforcement record. These
malformed POST cases are not described as observed escapes.
The old zero-violation batch count is an observed receipt, not proof of complete
redirect enforcement.

The repair uses supported Chromium CDP response-header checks for known main-
frame pages, preserving native streaming and navigation. A strict Location
grammar accepts full HTTP(S) authorities, exactly-two-slash network references,
and relative path/query/fragment references with no first-segment scheme.
Missing authorities, lenient special-scheme forms, extra authority slashes,
credentials in authorities, invalid ports, backslashes and whitespace/control
forms fail closed before `urljoin`. A 20-case offline check went red/green:
9 accepted origins agree with Node's WHATWG parser and 11 forms are rejected.
Route/APIRequest boundary checks remain in place.

**Explicit controlled-harness restriction:** an initial popup or child-frame
request outside a covered main-frame Page uses supported `Route.fetch` with
`max_redirects=0`. Its finite response may be fulfilled, but every redirect at
that unsupported target is denied, including a redirect to an otherwise allowed
origin. Fetch errors fail closed. Non-redirect popup/frame documents are allowed.
This policy does not silently claim full native popup or iframe semantics.

On the final repair source bytes, **18 narrow native canaries passed**: blocked
GET/307 POST/two-hop GET; allowed GET/307 POST/navigation URL; held first/last
stream chunks; initial popup redirect denial; raw two-backslash GET/307 POST
rejection; ordinary popup/frame documents; frame initial-redirect denial and
frame redirected-fetch denial; triple-slash and HTTP triple-slash GET/307 POST
rejection. Green unapproved sinks received zero requests.
Both page creation entry points were covered. Browsers and owned HTTP server
contexts closed; no shared endpoint, real secret or security flag was involved.

The cross-site frame check exposed **no OOPIF target**. Its old-guard attempt
already blocked the tested redirect and failed only the new policy-reason
assertion. It is not evidence of an observed OOPIF bypass, nor verification of
real separate-process frame coverage. Worker/service-worker response coverage
also remains **unverified**. These limits prevent a complete-egress claim.

Changed-file Python compilation passed. Commands, source hashes, red/green
observations and limits are in
[the focused repair evidence](test-evidence/pr9-pr10-mac-review-repairs.json).
The broad suite and 29-scenario batch were not rerun after these repairs. The
parent reported missing native PostgreSQL and Chromium socket EPERM in its
current cloud runtime. Full cloud E2E awaits a saved coding environment with
supported dependencies; no bypass was attempted.

The parent subsequently reported an independent cloud source review clearing
exact code head `90e28bc3f00506f225fcd4e5f46fa34986d0d154`: 20 parser checks,
4,854 variant comparisons with zero allowlist escapes, and 224 callback/fallback
checks passed. These are parent-reported cloud source checks, not additional
native Mac cases or a complete cloud E2E run. The controlled-harness, real
OOPIF/worker/session-detach coverage limits remain. Later commits change only
documentation/evidence.

## Reproduction

Use a fresh isolated checkout/environment, no production credentials, and
task-owned API/frontend ports. Build with that exact API origin, then inspect
`apps/web/.next/routes-manifest.json` before any partially mocked browser check.
The local receipts include the exact commands and whitelisted environment used.
Equivalent principal commands are:

```sh
MEMORY_SPARK_API_ORIGIN="$TASK_API_ORIGIN" npm --prefix apps/web run build
MEMOIR_TEST_POSTGRES_BACKEND=apple-container \
MEMOIR_BROWSER_URL="$TASK_WEB_ORIGIN" MEMORY_SPARK_API_ORIGIN="$TASK_API_ORIGIN" \
python tests/fixtures/browser_network_guard.py pytest -q
node --test skills/memoir-composer/tests/*.test.mjs tests/js/*.test.mjs
python -m compileall -q apps scripts tests
python scripts/check_localization_catalog.py
node apps/web/scripts/check_localization_icu.mjs
python scripts/audit_spec_routes.py
```

The task runner also sets `MEMORY_SPARK_TEST_MODE=1`,
`MEMORY_SPARK_ENTITLEMENT_MODEL=legacy`, and disables Next telemetry. Standalone
browser commands require `MEMOIR_BROWSER_PROFILE_FIXTURE=1`; profile-settings
also needs `MEMOIR_TEST_URL="$TASK_WEB_ORIGIN/memoir"`. The evidence lists all
standalone arguments, including both locales, blocked-photo and map/gallery
variants. The local ignored `output/mac-validation` directory retains detailed
receipts, JUnit XML, screenshots, red/green logs and the safe process audit.

## Remaining gate

Independent cloud source review cleared the final code head above. The parent
coordinates readiness and remaining acceptance gates before another live
provider/source-claim pilot or the full five-by-fifty run.
The native full-suite resource/runtime instability also needs resolution before
claiming a reliable complete native pass.
Cloud should also confirm the image-lifecycle scenario whose final Mac receipt
was unconfirmed. See the
[sanitized cloud setup handoff](pr9-pr10-cloud-test-setup.md) for services,
configuration names and the role/redirect repair limits. Native Linux, the full
post-repair browser batch, real OOPIF and worker/service-worker coverage remain
unverified. No laptop credentials or endpoints should be copied.
Durable Langfuse ClickHouse DateTime64 readback remains unresolved. No judge
configuration was invented. Prior live baselines remain separate:
`d67f390` had 205 pass / 8 fail / 37 unavailable out of 250; affected `28acda14`
had 152 pass / 5 fail / 43 unavailable out of 200. Diagnostic pilots do not replace
that acceptance gate.
