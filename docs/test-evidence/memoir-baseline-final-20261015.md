# Memoir baseline continuation: final isolated checks

Draft PR69 remains incomplete acceptance. The fixed tested commit is
`e15c0fbeb3b2fe5658fee9ea6361c98062deaca4`, with source/test changes through
`75bc1fb2ef620440d9015f7ce3d031c92d845a05`. Current main remains
`46caa5fc2c2c5af2d4f7280bea74cc75184c9cbc`. All applicable checks below used that
same fixed checkout; no source/test edits occurred during the aggregate.

The complete Python run collected **6,278 records: 5,434 passed, 574 failed,
21 setup errors, 249 skipped**, with three warnings. It took 1,289.34 seconds
wall time (JUnit 1,282.085 seconds). Every remaining failure/error and skip is
listed in [the current per-case ledger](memoir-baseline-current-checks-20261015.json),
with classification evidence and comparison to both verified historical runs.
Matching historical IDs or summaries alone does not establish a cause or exclude
a defect. The old unverified aggregate is not used as a verified baseline.

| Remaining disposition | Cases |
| --- | ---: |
| Stale fixtures or retired contracts | 569 |
| Identified tooling/fixture compatibility work | 10 |
| Environment or aggregate case budget | 7 |
| Unresolved functional/authority contracts | 9 |
| Total failures and setup errors | 595 |

The 10 compatibility cases are the six old profiler cases, three legacy lane
worker/Temporal fixtures and one timeout diagnostic adapter. Their original
behaviour assertions remain unmet; no retired engine or admission exception is
restored. The nine unresolved cases are seven generic legacy dataset cases,
one photo-policy/rework-retention case and the new pending-proposal overlap
regression. Exact decisions are in [the contract record](memoir-baseline-tooling-contracts-20261015.md).

The new native overlap regression remains an ordinary failing test. After a
completely processed proposed root for A, the application admits rework for B;
after B saves, the next page queues A again. A's stored bytes are unchanged at
that point. No actual overwrite or exposure is claimed. Choosing whether later
roots inherit pending proposals or wait for decisions changes the latest-root
review contract; the published patch does not relax that guard.

Compared with the preserved `cd73917` checkpoint, the two pure orchestration
fixtures, realistic migration-history upgrade and stranded-request recovery now
pass. The newly failing IDs are the retained overlap regression and an additional
10,000-source case that exceeded the aggregate's 60-second allowance. All seven
large cases pass their separately recorded 600-second correctness allowance.
Aggregate timeouts remain failures. There is no performance SLA or latency claim.

## Other completed checks at the same commit

| Check | Result |
| --- | --- |
| Seven large correctness cases | 7 passed, 648.55 seconds total |
| JavaScript | 501 passed, zero skips |
| Mobile | 87 Node + 66 UI + 21 integration = 174 passed |
| Mobile types/lint/OpenAPI/native config | Passed; 43 operations; no native binary/device test |
| Web production build | Webpack and standalone passed |
| Browser/fixture selection | 36 passed, 4 failed |
| Actual standalone Chromium stage cases | 4 passed with controlled Auth/API, paid round 20 and debug off |
| Specification acceptance | 55 passed |
| Localization / route audit | 647 messages in both locales; 63 required / 125 application routes |
| Changed JavaScript lint / Python syntax / whitespace | Passed; 52 Python files parse; no lint rules disabled |

All 14 actual-worker/in-process controlled streaming, save and replay checks
pass, preserving current main's acknowledgement ordering. This does not establish
provider effort, semantic quality or production latency.

The four browser failures are preserved recovery fixtures that admit only
`read_lifetime_project_identity` and reject canonical identity resolution before
the original recovery assertions. They are also itemized in the ledger. This is
not a claim that those original recovery assertions pass.

## Skips and checks not run

All 249 aggregate skips are itemized. They comprise 214 frontend/locale/historical
browser conditional cases, 12 live-model cases, 10 complete-round gates, four
artifact gates, six unavailable Mocker Compose-parser checks, two unavailable
Supabase CLI splitter checks and one explicit PostgreSQL TCP opt-in case. Four
stage cases were separately executed against the selected standalone frontend;
that selection is not the full opt-in browser suite. Mocker here is the Compose
CLI, not a missing pytest-mock plugin.

Live provider/judge or semantic acceptance, real Auth, full 250-round acceptance,
full opt-in UI/artifact/complete-round gates, Mac/device/native binaries,
production migration/deployment and independent cloud runtime acceptance remain
unrun or outstanding. No real user data, configured provider/service credentials,
production database or paid provider call was used. Controlled evidence remains
`mock_only`.

## Provenance and scope

The [historical ledger](memoir-baseline-checks-20261015.json), complete
[165f330 checkpoint](memoir-baseline-checkpoint-165f330-20261015.json), complete
[cd73917 checkpoint](memoir-baseline-checkpoint-cd73917-20261015.json), and
[all repair batches](memoir-baseline-batches-20261015.json) remain preserved.
The current ledger includes commands, versions, source hashes, raw evidence
SHA-256 values, all remaining cases and all skip reasons. Raw XML/logs remain in
`/tmp/memoir-final5-*` in the selected cloud environment.

Native tests use owned Unix-socket PostgreSQL 17.11 and local Temporal CLI 1.9.1
on Linux (4 CPUs/16 GiB). Two aggregate workers ran concurrently with separately
budgeted large checks and the static/browser selections. This is bounded
correctness evidence, not timing acceptance.

The corrected stored-image matrix validates real `image` schema and rendering
against a declared synthetic catalog. Current production `assets=[]`; no live
image path or upload-to-composer mapping is enabled or established. Earlier
invalid `photo` matrix claims remain explicitly superseded.

PR68's active owner keeps its polling, attribution and readiness migrations.
Overlap paths remain `apps/web/client/memoir/client.js`,
`tests/test_stage_readiness_browser.py`, and `tests/js/stream-latency.test.mjs`.
No PR68 implementation was copied. No merge, deployment, production migration,
access/security-policy change, credential export, Mac execution or external-agent
contact occurred.
