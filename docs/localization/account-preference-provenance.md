# Account UI preference and SSR follow-on

Baseline: `24e1edfd5879e1793213c3e885d5071eb5e44c49`. This is a bounded follow-on to
issue #1. Human translation review, full browser/manual acceptance, deployment
and remote migration remain separate gates.

## Current contract

A fresh explicit UI action persists the account preference. Otherwise a verified
persisted account preference outranks browser cookies/cache. Eligible first-reply
UI detection persists independently from conversation language, initializes only
once, and never replaces an established/manual preference. Existing source-less
account `ui_locale` is conservatively established/manual. Legacy bare/fixed locale
cookies are ambiguous (old account boot wrote them too), so no longer establish
explicit intent; a user can reselect once. New versioned cookies bind provenance
to a viewer and are hints, never authentication. Without a verified session,
account-bound hints are ignored. Anonymous pre-sign-in explicit choice can be
carried into the newly created anonymous account, not overwrite a signed-in one.

## Authentication and persistence

The official locked `@supabase/ssr` client shares same-origin session cookies
between browser and Next. It uses PKCE with the existing product return URLs;
proxy code exchanges the one-time code and strips it, never follows a `next`
parameter. Proxy refresh is not authorization: initial locale requests separately
call `getUser`, then the own-user locale RPC. No caller cookie/JWT metadata is
accepted as verified identity. Responses are dynamic and private/no-store.

Cookies use SameSite=Lax, Path=/ and Secure in production. The official
browser-coordinated SSR cookie store is intentionally browser-readable, not an
HttpOnly BFF. Session tokens are never serialized into HTML, locale cookies or
logs. Existing localStorage sessions import via the same Auth service, verify
with `getUser`, and retire the old entry with a tombstone only after success; a failed import does
not silently create a replacement guest. Explicit logout still revokes the current
session if browser storage is unavailable. It suppresses callback-triggered reload
and asks the user to clear site data if legacy retirement could not be assured.
No new service/admin credential is used.

A dedicated RLS-protected preference table and own-user RPC serialize account
writes, retaining manual-over-detection ordering even across concurrent clients.
Both reads and writes require an expected viewer equality check in addition to
`auth.uid()`, fencing SDK token changes before request dispatch. The argument
cannot select another target. No Auth metadata object is rewritten. Migration
`202610110002_ui_locale_preference.sql` has only been applied to disposable test
clusters. Production application requires separate approval.

Selector placement, recorder refusal, explicit conversation/profile controls,
first-reply onboarding and routes are retained. Client generations prevent late
reads/writes from installing a previous viewer's locale. Account UI persistence
and existing conversation-profile PATCH remain separate operations. The complete
manual PATCH→account sequence is serialized per browser client, newer intent
supersedes queued work, and navigation/viewer generations reject stale results.
If PATCH succeeds but account persistence fails, a localized partial-save warning
explains the state; repeating the selection retries idempotently. An eligible
committed first-reply decision reconciles a failed account write on later profile
load, while the atomic RPC still protects established/manual preferences.

## Verification and remaining gates

- Real Next HTTP TDD: three baseline failures reproduced; eight production
  account/legacy/isolation/refresh/PKCE/cache/expected-viewer cases pass.
- Atomic RPC TDD: initial missing-RPC failure; 39 cases pass on each of disposable
  PostgreSQL 17 and 18, including RLS, anonymous identity, row contention and
  expected-viewer checks. No remote migration has been run.
- Full offline Python suite: 3,816 passed, 458 explicitly skipped. The opt-in real
  HTTP and PostgreSQL suites are separately exercised above.
- Focused JavaScript session, bridge, logout, migration and policy checks pass.
  Eight remote-Make fixture failures also occur on the unchanged baseline because
  its local `.env` is absent; the remaining JavaScript cases pass.
- Optimized Next production build passes. Catalogue validation passes with 562
  messages across en-AU and zh-CN. Human translation review is still outstanding.
- Chromium cannot start because Unix sockets are denied, including after an
  approved escalation. Supported cloud CDP navigation was also attempted twice,
  once with explicit user retry approval; its permission request was dismissed
  before any navigation. No rendered-browser assertion is claimed.
- Existing browser fixtures now use synthetic Auth/PostgREST endpoints with the
  real bundled SDK instead of replacing the old CDN SDK. They compile, but their
  rendered acceptance remains unrun until browser access is available.
- Merge, deployment and full issue acceptance remain gated on the outstanding
  browser/manual and translation requirements. This source change does not apply
  the migration or change Auth project settings.

## Reproduction

`npm ci --prefix apps/web`; `node --test tests/js/*.test.mjs`;
`NEXT_TELEMETRY_DISABLED=1 npm --prefix apps/web run build`;
`MEMOIR_LOCALE_HTTP=1 MEMOIR_LOCALE_NEXT_MODE=start python -m pytest -q tests/test_ui_locale_account_http.py`.
Add `MEMOIR_LOCALE_BROWSER=1` only with a runnable Chromium; use
`PLAYWRIGHT_CHROMIUM_EXECUTABLE` to select an installed executable.
With isolated PostgreSQL tools on PATH, run
`python -m pytest -q tests/test_ui_locale_preference_postgres.py`.
These fixtures never connect to a remote database or live model provider.

References: [Supabase SSR client](https://supabase.com/docs/guides/auth/server-side/creating-a-client)
and [SSR lifecycle/security](https://supabase.com/docs/guides/auth/server-side/advanced-guide).
