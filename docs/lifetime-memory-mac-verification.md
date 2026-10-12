# #60 provider-free Mac verification matrix

Production-source pin: `2ad1659fe61202141c530f1d634a4254884409e3`, remote
`ed21b73736307decd6305aeec07e869a4c0ae67e`, tree
`bf1baad6a57e845ece03f31899126009e4e9fe4b`. Its full native aggregate passed
5,403 cases and skipped 213; skips are not passes. The eight separately passed
lifetime/collection standalone browser cases do not replace the matrix below.

## Applicability of the 205 browser/Auth-HTTP skips

Required shared-integration regressions: **125**.

| Cases | Suite/path | Why applicable |
|---:|---|---|
| 10 | account recovery | Original project, guest transfer, saved history/private draft |
| 38 | navigation/history | Account/project isolation, reload/fresh tab, failed storage, interrupted replies |
| 2 | conversation locale | Profile language across saved reply and reload |
| 16 | interview photo turns | Accepted source versus saved reply, retries, media and receipt recovery |
| 19 | recall, excluding optional-font startup | Saved draft, entitlement, preview/retry/recovery |
| 4 | stage readiness | Shared private-draft rendering |
| 16 | shared-memory browser | Actual SQL-backed polling, typed/dictated original and corrections |
| 2 | progressive navigation | Actual SQL-backed draft surviving reentry/fresh tab |
| 2 | selected scroll cases | Streaming submission and saved-draft reachability |
| 2 | selected album cases | Project route/pending reply through Back/Forward |
| 14 | interview workspace | Real test-mode project/session API and changed middleware |

Required phase integration unless exact equivalent revised-contract evidence is available: **14** in `test_conversation_phase_browser.py`.
Reconcile with the #59 owner using matching relevant source/fixture hashes, or run
on this pin. Separate ownership is not a waiver and does not authorize changing
#59 behavior.

Broader confidence coverage: **66**, explicitly unrun unless selected: Next locale
HTTP/browser 18+14, Next/Auth HTTP 9, family renderer 4, historical-news isolated
module 1, remaining scroll 3, remaining albums 13, photo favorites/selection 2 and
optional-font startup 2. The 41 Next locale/Auth cases exercise unchanged Next
proxy/auth/i18n code; the Auth fixture serves synthetic API responses rather than
`main.create_app`. Remaining renderer-only cases do not establish canonical storage
or publication fencing. These classifications are review decisions, not claimed
passes or blanket acceptance of the skipped environment matrix.

## Isolation and prerequisites

Use the existing authorized Mac task and a clean task-owned checkout. No `.env`
or `.env.local`, production credentials, provider/Auth/payment variables or live
account should be loaded. Python test dependencies, Node >=22.13, matching web
lockfile dependencies and Playwright Chromium are required. The 18 SQL/browser
cases additionally require non-root `initdb`, `pg_ctl`, `psql` and the existing
`native-tcp` backend. Do not substitute a shared database or silently skip them.

Use an owned-process supervisor with separate logs/readiness checks and complete
process-group cleanup. Check example ports **18042** (API) and **13042** (Next)
are free; never stop somebody else's process. Build/start must share the API origin
because Next rewrites are compiled. Start fresh test-mode API and production Next:

```sh
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 18042
npm --prefix apps/web run build
npm --prefix apps/web run start -- --hostname 127.0.0.1 --port 13042
```

The supervisor must derive a credential-free environment using
`scripts.run_isolated_check.offline_environment`, then set:

```text
MEMORY_SPARK_TEST_MODE=1
MEMORY_SPARK_ENTITLEMENT_MODEL=legacy
MEMOIR_LEGACY_ONLY_DEPLOYMENT=1
MEMORY_SPARK_SHOW_THINKING_STEPS=0
NEXT_TELEMETRY_DISABLED=1
MEMORY_SPARK_API_ORIGIN=http://127.0.0.1:18042
MEMORY_SPARK_LLM_BASE_URL=http://127.0.0.1:9/v1
MEMORY_SPARK_CODEX_WORKER_URL=http://127.0.0.1:9
```

This server is the explicitly synthetic legacy compatibility fixture. It is not a
configuration for a real mixed/canonical cohort. Give service processes a new
task-owned empty HOME, verify the intentionally unused loopback port 9 is closed,
and keep the provider/worker URLs there so any unexpected dispatch fails closed
instead of using a configured provider or personal Codex login. Actual governed SQL/transport
claims come from the separately pinned native tests. Use task-local SQLite paths
for `MEMORY_SPARK_TASK_DB` and `MEMORY_SPARK_DATABASE`; never configured stores.

## Grouped commands

From repository root, `PY` is the task venv Python and `EVIDENCE` an absolute path to a new task-owned
receipt directory. Preserve every failure and prerequisite skip.

```sh
export MEMOIR_BROWSER_URL=http://127.0.0.1:13042
export MEMORY_SPARK_API_ORIGIN=http://127.0.0.1:18042
export MEMOIR_TEST_POSTGRES_BACKEND=native-tcp
CHROMIUM="$("$PY" -c 'from playwright.sync_api import sync_playwright
with sync_playwright() as p: print(p.chromium.executable_path)')"
check() {
  name="$1"; shift
  "$PY" scripts/run_isolated_check.py --output-dir "$EVIDENCE" \
    --name "$name" --timeout 1800 -- env CHROMIUM_EXECUTABLE="$CHROMIUM" \
    PLAYWRIGHT_CHROMIUM_EXECUTABLE="$CHROMIUM" \
    MEMOIR_NETWORK_RECEIPT="$EVIDENCE/$name-network.json" "$@"
}
browser_check() {
  name="$1"; shift
  check "$name" "$PY" tests/fixtures/browser_network_guard.py pytest -q "$@"
}

# 89 recovery/shared-client cases
browser_check issue60-recovery \
  tests/test_account_recovery_browser.py tests/test_navigation_history_browser.py \
  tests/test_conversation_locale_browser.py tests/test_interview_photo_turns_browser.py \
  tests/test_stage_readiness_browser.py tests/test_recall_browser.py \
  -k 'not startup_does_not_wait_for_optional_font_stylesheet'

# 18 actual PostgreSQL/browser cases; no competing heavy DB run
browser_check issue60-pg-browser \
  tests/test_shared_memory_browser.py tests/test_progressive_memoir_navigation_browser.py

# Four selected interrupted-navigation/readability cases
browser_check issue60-interruptions \
  tests/test_conversation_scroll_browser.py::test_send_stream_scrollback_late_content_and_keyboard \
  tests/test_conversation_scroll_browser.py::test_saved_draft_stays_reachable_without_page_scroll \
  tests/test_phone_map_albums_browser.py::test_workspace_toggle_and_album_back_preserve_project_route \
  tests/test_phone_map_albums_browser.py::test_album_back_forward_preserves_a_pending_chat_reply

# 14 real test-mode project/session API cases
browser_check issue60-workspace tests/test_interview_workspace_browser.py

# 14 #59 cases only after coordinating its equivalent evidence/owner
browser_check issue59-phase-integration tests/test_conversation_phase_browser.py
```

`run_isolated_check` strips Chromium-path and locale/historical opt-in variables;
inject them after its `--` using `env`, as above. The browser network guard permits
declared loopback origins and public read-only assets from unpkg.com,
cdn.jsdelivr.net, cesium.com, fonts.googleapis.com and fonts.gstatic.com. This is
provider-free, not network-free. No paid maps/model calls or account creation is
required. The family fixture also retrieves three pinned public unpkg assets.

The optional AuthHTTP nine own two dynamic loopback ports. Do not wrap them in the
fixed-origin browser guard unchanged; their rendered case already aborts HTTPS.
Run sequentially, credential-free, with no competing Next dev session:

```sh
check issue60-auth-http env MEMOIR_LOCALE_HTTP=1 MEMOIR_LOCALE_BROWSER=1 \
  MEMOIR_LOCALE_NEXT_MODE=dev "$PY" -m pytest -q tests/test_ui_locale_account_http.py
```

This dev run does not establish production-only cookie/cache assertions.

## Mocker and Apple Container

The three Mocker checks passed on the exact remote pin on the Mac: **3 passed,
zero failed/skipped, exit 0**, existing Mocker 0.9.3, 0.51s pytest/1.4s wrapper.
They are separate evidence, not a retroactive change to the 213-skip aggregate.
Reproduction starts no services/containers and requires no ports:

```sh
python scripts/run_isolated_check.py --root "$PWD" \
  --output-dir /tmp/issue60-mac-compose-ed21 --name compose-config --timeout 60 -- \
  python -m pytest -q -ra tests/test_collector_compose_config.py
```

Do not use `make container-up/config` for this check or print configured Compose
values. The test inspects only safe collector model/effort fields.

The skipped Apple launcher is applicable shared-worker/SQL compatibility: five
synthetic owners, 250 originals and 50 checkpoint receipts, zero provider calls.
Its fixture currently lacks a genuine publication-authority DSN after environment
scrubbing, while its stock container disables TCP. That authority path must be
repaired and reviewed before expensive execution; do not set a legacy-only bypass
against a mixed-capable fixture. An opt-in explicit guest-IPv4 listener with host
127.0.0.1-only ephemeral publication is under code review. Actual guest-network
exposure and the 250-turn run await the user's specific approval. Default no-TCP
behavior, unique UUID ownership, cancellation and verified cleanup must remain.

No browser/Compose pass resolves direct-WebRTC parity, existing-call termination,
production reconciliation/activation or live model quality/latency/cost. Four live
provider evaluations remain separately approval-gated.
