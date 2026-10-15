# PR69 integration with PR68 and current main

Tested executable head: `59086ebed443d2b5e3d2fe51a53f462911a2a0c9`. Current main: `400f352885f3cba49203924bba3adec0686583ee`.
The following evidence-only commit changes no executable/test bytes. PR69 remains
ready for review by human choice, open and unmerged. **Acceptance is incomplete.**

## Merge and ownership preservation

Old PR69 was `e8e7025d2338295d89cbd825a673c871e8baf37c`. The first normal merge `09cd7ad973c7b1df1774c639401b4ef9895a9cb7`
has parents old PR69 and PR68/main `327b21068d1fbd5e9877b44cde334bdb5a7dffee` (reviewed PR68 head
`b9e2cdea6ba608c277e78c1152bc483dc03fb594`). Its only manual conflict was
`apps/web/client/memoir/client.js`; automatic overlaps were
`tests/js/stream-latency.test.mjs` and `tests/test_stage_readiness_browser.py`.
The complete PR68 readiness recovery body, navigation/turn/resume functions,
attribution migration and regressions were retained. PR69 draft eligibility,
unused-binding cleanup, transport assertions and canonical lifecycle work survive.

Main then advanced by 11 paths. The second normal merge `59086ebed443d2b5e3d2fe51a53f462911a2a0c9` has parents
`09cd7ad973c7b1df1774c639401b4ef9895a9cb7` and `400f352885f3cba49203924bba3adec0686583ee`.
It had no manual conflict. Automatic overlaps were `apps/api/lifetime_memory_engine.py`,
`tests/test_container_startup.py` and `tests/test_lifetime_actual_engines.py`.
The main acknowledgement prompt and unique-quote validation are retained exactly,
including the Node26 container change and diagnostic-only prototype. PR69 trajectory,
Unix-socket/publication fixtures and spaced env-file assertions remain intact.
Only those 11 upstream paths differ from the first merge. No upstream policy,
authority guard or migration was rewritten to obtain a passing check.

Before the first merge, the PR68 readiness harness against old PR69 source was
**6 passed / 16 failed**. The combined candidate was **48 passed**, and native
stage/provenance/lifecycle SQL was **29 passed**. Those precommit files were
committed unchanged; the complete fixed-head executions below are separate.
Current-main client lint had four unused-binding findings; the merged client
has zero, preserving the existing PR69 cleanup.

## Current fixed-head results

| Check | Result |
| --- | --- |
| Complete Python, two workers, 60-second case bound | **5,514 passed, 573 failed, 21 error, 259 skipped**, 6,367 XML records; 1225.04s wall |
| Seven large-capacity cases, separate 600-second bound | **7 passed, 0 failed, 0 error, 0 skipped** |
| Upstream acknowledgement/continuity/startup/container and prototype selection | **219 passed, 0 failed, 0 error, 0 skipped** |
| All JavaScript/composer/historical-news cases | **523 passed**, no failures/skips |
| Changed-JavaScript lint | Passed |
| Expanded browser/fixture selection | **46 passed, 4 failed, 0 error, 0 skipped**; actual source-frontend subset **14 passed** |
| Mobile checks | **87 Node + 66 UI Jest + 21 integration Jest passed**; type/lint/OpenAPI/native-config passed |
| Host production web build; offline mobile JS export | Passed; host Node24.19.0 |
| Node26 production container build/runtime | **Blocked before compilation**: Docker daemon DNS lookup for `auth.docker.io` refused; runtime unrun |
| Deterministic acceptance catalogue | **55 passed**, MemoryStore scope |
| Localization and route audit | **647 messages** across two locales; all **63 required** among 125 application routes |
| Python syntax and whitespace | **556 files parsed**, whitespace passed |

The originally diagnosed target scopes are visible in the same full run:
runtime **25 passed, 0 failed, 0 error, 0 skipped**,
read fences **67 passed, 0 failed, 0 error, 0 skipped**,
transport contracts **25 passed, 0 failed, 0 error, 0 skipped**,
original-text route variants **4 passed, 0 failed, 0 error, 0 skipped**,
and the two legacy phase-read side-effect invariants
**2 passed, 0 failed, 0 error, 0 skipped**.
The SQL read assertions snapshot every other public table, verify idempotent phase
initialization and owned-project locking, and retain no-admission/no-generation
and cross-owner checks. RPC failure remains fail-closed. Route fixtures supply
governed publication authority rather than bypassing it. The transport suite's
Apple inspection cases are simulated here and do not claim native Mac coverage.

All database/service inputs were disposable and synthetic. Browser network guards
allowed only the owned loopback frontend/backend, with no external asset hosts or
blocked attempts; unknown backend requests return 503. Ten of the 14 browser
cases use native SQL stage totals; the other four test current workspace/draft
policy through synthetic services. The other 36 cases exercise fixture behavior.
Mobile exports are not native binary/device tests. No live provider performance,
latency SLA or real model quality claim follows from these controlled checks.

## Newly detected and retained failures

The SQL audit `test_public_application_functions_never_raise_serialization_failure`
was passing in the historical b4/51ca run and failed after importing PR68. Native
PostgreSQL now finds exactly `apply_user_memory_events_before_photos(text,jsonb,jsonb)`
with application SQLSTATE `40001`. Migration `202610140007_nonretryable_application_conflicts.sql`
converted earlier application conflicts to `PT409`, but PR68 migration
`202610150003_canonical_stage_readiness.sql` recreates this function with three
`40001` source/event/evidence revision branches. The audit expects zero such
functions and observes one. This is a newly observed upstream SQL contract
regression, not an assumed historical failure. Actual PostgREST HTTP retry
behavior was not measured. The migration and assertion remain intact under the
PR68 ownership boundary; a separate owner repair is needed.

The first integrated head had **5,505 passed / 574 failed / 21 errors / 259 skipped**
in 1,279.42s wall. Compared with the b4 baseline, it added 29 passing SQL cases and
10 browser skips, plus two newly failing cases: the SQL audit above and a 60-second
timeout in the 10,000-receipt case. All seven separately budgeted capacity cases
passed at that head. Their passing correctness run does not waive aggregate
timeouts or establish a capacity/latency SLA.

The first browser selection was **45 passed / 5 failed**: the four retained
identity-fixture failures and the English saved-project resume case, which stayed
at 10% before reload and reached 30% after reload. A focused repeat passed both
languages. The new-head run passed all 14 source cases; the parent also reported
14 passes in independent review of the first head. The original failure remains
archived with its cause unestablished; it is not attributed to baseline, product
or scheduling without proof. Main's five recovery/navigation/turn function
bodies remain byte-identical.

Every current failing assertion is indexed in the JSON, with trace comparisons,
classification evidence and its lossless XML record. No failure is converted to
a pass by matching history. The category counts are:

| Current observed category | Records |
| --- | ---: |
| `aggregate_case_time_budget` | 4 |
| `diagnostic_adapter_canonical_fixture_compatibility_defect` | 1 |
| `environment_zombie_process` | 1 |
| `evaluation_driver_canonical_context_compatibility_defect` | 6 |
| `legacy_lane_worker_fixture_compatibility_defect` | 3 |
| `stale_browser_identity_fixture` | 37 |
| `stale_browser_source_extraction_fixture` | 4 |
| `stale_canonical_execution_fixture` | 192 |
| `stale_guest_admission_contract` | 1 |
| `stale_guest_identity_fixture` | 6 |
| `stale_identity_rpc_fixture` | 2 |
| `stale_invalid_worker_request_fixture` | 5 |
| `stale_legacy_collection_contract` | 5 |
| `stale_phase_publication_fixture` | 6 |
| `stale_photo_partition_fixture_with_progressive_coverage` | 2 |
| `stale_progressive_photo_partition_fixture` | 7 |
| `stale_publication_authority_fixture` | 7 |
| `stale_retired_admission_fixture` | 65 |
| `stale_retired_api_fixture` | 225 |
| `stale_retired_artifact_fixture` | 1 |
| `stale_retired_clearance_contract` | 1 |
| `stale_retired_publisher_route_fixture` | 3 |
| `unresolved_legacy_evaluation_dataset_contract` | 7 |
| `unresolved_pending_proposal_root_authority_contract` | 1 |
| `unresolved_photo_policy_rework_contract` | 1 |
| `upstream_application_conflict_sqlstate_regression` | 1 |

The pending-proposal root-authority and outside-composer photo policy-epoch
failures still require explicit contract decisions. Other compatibility drivers
and stale canonical/retired fixtures remain unmet; they were not broadly mocked,
deleted, skipped or admitted through retired execution to turn the suite green.

## Skips and remaining execution limits

All 259 aggregate skips are individually indexed with reasons.
The selected browser run covers 14 of the source-frontend skipped cases; it does
not turn the other browser, native opt-in, CLI, plugin or live-model skips into
passes. No provider/live gate or Mac/native-mobile execution was attempted.

| Exact aggregate skip reason | Records |
| --- | ---: |
| Requires isolated source frontend | 114 |
| Actual disposable PostgreSQL artifact tests require explicit opt-in | 4 |
| Complete-round PostgreSQL gate requires explicit opt-in | 10 |
| Requires a selected local source frontend | 21 |
| Requires isolated frontend | 49 |
| Requires an explicitly selected running browser test server | 16 |
| Opt-in live model evaluation; requires the configured application provider | 12 |
| Requires source frontend | 14 |
| Requires isolated Next/Auth HTTP fixture; enable MEMOIR_LOCALE_HTTP=1 | 8 |
| Requires runnable Chromium; enable MEMOIR_LOCALE_BROWSER=1 | 1 |
| Mocker is not installed | 6 |
| Supabase CLI required to exercise its SQL statement splitter | 2 |
| Requires a permitted local Chromium launch; opt in with MEMOIR_RUN_HISTORICAL_BROWSER=1 | 1 |
| Requires explicit approval and MEMOIR_TEST_PUBLICATION_TCP=1 for the disposable guest SQL endpoint | 1 |

The container failure is environmental: the Docker daemon could not resolve its
anonymous registry-token endpoint before fetching Node26. No owned image/tag or
container exists after that attempt; its temporary Docker config was removed.
Daemon/network/security settings were not changed and no global cleanup was run.
Host builds use Node24 and do not verify the new Node26 runtime image.

All check receipts reconcile their registered native roots/sessions. This is not
a global PID-absence proof. The ordinary timeout test's exact-group observations
retain PID1 zombies as unreaped, rather than claiming running descendants or
claiming successful reaping. Frontend/backend teardown is recorded separately.
Shared Docker build cache is retained; unrelated owners/resources are untouched.

Independent review supplied by the parent covered **523 JS, 14 browser, 146 Python
passes with three retained failures, and 21 lifecycle probes** at the first
`09cd7ad` head against `327b210`, plus 71 allocations/89 roots removed and no
running PostgreSQL in that review's scope. Its raw files are not shared here and
it does not review the new executable head. A subsequent parent-supplied review
of `59086eb` against `400f352` confirmed the inherited SQLSTATE blocker with a
native 4-pass/1-fail gate and direct stale-source RPC, plus another English resume
failure in a 45-pass/5-fail expanded browser run. That review also reported 212
contract, 523 JS, 146 affected Python passes with three retained failures, nine
lifecycle, three native quote-persistence and 14 quote-boundary passes; these
scopes may overlap and are not summed. It reported Node26 standalone builds,
with no container runtime, 63 allocations/78 roots cleaned and browser servers
reaped; full aggregate was unrun and CI empty. Its report/bundle is inaccessible
in this executor. These are supplied findings, distinct from own executions.
Scoped TDD repairs and re-review are now authorized; this checkpoint claims no
repair of either blocker. Earlier parent-reported Mac evidence is historical
and narrower; no new Mac execution is claimed. Human ready status does not waive
any gate or authorize merge/deployment.

## Reviewable raw evidence and provenance

[Complete manifest and every current failed/error/skipped record](memoir-baseline-main-integration-20261015.json)
and [lossless raw evidence archive](memoir-baseline-main-integration-20261015.tar.gz) preserve both fixed-head runs,
exact JUnit identities/attributes/problem entries/durations, all raw logs and
receipts, red/green evidence, helper source, argument snapshots, comparisons and
focused probes. Archive: **189 regular files**, 895,428
bytes, SHA256 `79e5d1876be68842151f6319620b53b3e28f444669b35686387c8f4ba36c89f0`. Every archived member was read back and
matched to its original bytes/hash. There are no redactions. Very long synthetic
image/body parameter IDs are abbreviated only in readable JSON; SHA256 and
zero-based XML testcase indices map them to their complete raw records.

Primary helper hashes were captured before each round, and exact command
snapshots plus post-run hash/HEAD checks are retained. Additional focused/probe
helper versions are archived separately without claiming independent prior hash
snapshots. The earlier historical qualification remains: **the c747/e8 archived
final helper settings differ from eight earlier receipt commands; earlier helper
versions were not supplied.** Their receipts remain authoritative for actual
commands. All 42 historical raw originals still match the independently audited
archive; none was reconstructed or modified. The earlier unverified 647-failure/
275-error aggregate is not used as baseline proof.

No real user data, provider calls, production migration, PR merge, deployment,
credential export, access/security change or external-agent contact occurred.
