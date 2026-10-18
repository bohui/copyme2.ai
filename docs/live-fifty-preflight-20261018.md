# Fifty-round live retest preflight — 18 October 2026

Status: blocked before live execution. **0/50 rounds submitted. No campaign
project or game has been generated.** Do not mistake the isolated map browser
fixture for a retained live-test project.

## Requested run

Run one fifty-round Chinese conversation, not five cases or 250 rounds. The
existing `chengdu-tea-ledger` case maps to `test2@test.com`. Read-only Auth
inspection found that this account does not currently exist; setup has not run.
The eventual receipt must retain the actual owner, canonical project ID, all
fifty original/reply pairs and ten saved checkpoints at rounds 5 through 50.

Use the existing subscription gateway routes: Lane A Luna/high and independent
Lane B low. Do not substitute an all-role override, skip privacy/evidence checks,
grant a real paid subscription or invent successful skill delivery. Verify the
test owner's scoped allowance, strategy eligibility and required skill gates
before admission.

After the conversation and checkpoints pass, the existing
`scripts/run_memoir_game_ui_acceptance.py` can exercise the fictional author's
formal completion, adaptation consent, exact-candidate/person review, private
publication, play and reload recovery. A passing missing-authority negative
test is not successful game generation. The final handoff must include the
actual project ID, owning test account, game result and UI reopening steps.

## Fix delivered locally

Saved places and the workspace now survive imagery/session/library failures.
The UI shows a localized error and explicit retry without an automatic provider
retry loop. Retry cannot affect a replaced project. Map availability participates
in the scene dataset so render reuse cannot retain an obsolete preview or retry
button. Both catalogues use the existing primary button style for readable text.

The frontend was rebuilt. Mocker recreated dependent services despite
`--no-deps`; the existing service-alias refresh was run afterward. No conversation
was submitted as part of this reload. No model prompt changed in this fix.

## External blockers and unverified delivery

- Google Map Tiles `createSession` returns HTTP 403 `PERMISSION_DENIED` with
  reason `API_KEY_SERVICE_BLOCKED`. The configured browser key is denied access
  to `tile.googleapis.com`. An owner must allow that API on the existing restricted
  browser key, or provide a separate browser-scoped `GEOAPIFY_BROWSER_API_KEY`.
  The server-only Geoapify credential was not exposed or repurposed.
- Earlier photo-worker diagnostics reported Flickr `robots_denied`, Google
  `source_unavailable`, and Library of Congress `http_403`. No access-control,
  robots, date, location, licensing or source-verification guard was bypassed.
- A new bounded Commons check returned no accepted 1983 Chengde photos. An
  unrestricted-date check returned eight metadata-qualified rows, including
  duplicates; this is not eight distinct delivered images and is not historical
  matching or successful UI photo delivery. The full photo path still needs a
  verified positive result with honest date/fallback labels.

## Verification

- 77 focused JavaScript map/grouping/workspace/module checks passed.
- 33 Mocker-alias/startup checks passed.
- English and Chinese production-frontend browser fixtures passed with mocked
  HTTP/Auth/model boundaries; no real Auth writes or model calls. They preserve
  the panel and require an explicit retry. These do not verify Google access.
- Localization catalogue parity and frontend production builds passed.
- The broader JavaScript run had 546 passes, 20 failures and one cancellation.
  The same 20 failures and cancellation reproduced in a process-local control
  using unchanged HEAD client sources. They involve isolated game-button fixture
  dependencies and navigation/recovery scenarios; they remain unresolved and
  are not reported as passing.

Do not start the requested full-quality campaign or claim all issues fixed until
the external access and remaining readiness gates are resolved.
