# PR69 scoped compatibility repair

Tested executable head: `9a89c4961b2448d8243c39fccdf1a66bc0b00edb`; main `400f352885f3cba49203924bba3adec0686583ee`.
SQL repair `862780abdc5d6924721828bcc1516ab48b6a8af3`; final browser-fixture repair `9a89c4961b2448d8243c39fccdf1a66bc0b00edb`.
The following commit adds evidence only. Human ready-for-review status is preserved;
the PR remains unmerged. **Acceptance is incomplete.**

## Repairs and TDD

Upstream migration003 recreated the stage writer with three application-conflict
`40001` branches after the earlier nonretryable conversion. New forward migration006
restores only those error codes to `PT409`; upstream attribution DDL, predicates,
messages, function identity, owner, grants and data are preserved. Native red was
**3 failed / 5 passed** (source/event wrong-version RPCs and global audit). Green
was **38 passed**, including stale evidence, all-table no-mutation snapshots,
authority preservation, upgrade replay and stage/provenance/lifecycle regressions.
PostgREST documents `PTxyz` custom status codes; actual HTTP retry behavior was not
measured here. [PostgREST error reference](https://docs.postgrest.org/en/stable/references/errors.html#raise-errors-with-http-status-codes).

The resume fixture installed a fake clock after boot scheduled native timers,
then jumped virtual request deadlines while Auth/HTTP still ran in real time.
Playwright documents that installation ordering as unsupported. A controlled
probe observed **10% with late install versus 30% with install before boot** after
the same 60-second virtual jump (under 0.1s wall). The corrected scenario uses actual
browser timers and the same 60-second bound, asserting 30% **before reload**, then
retaining reload, amber-color, 300-word, project and no-new-turn assertions.
[Playwright clock ordering](https://playwright.dev/python/docs/clock).

The production client is unchanged. Removing only its saved-project recovery
restart in a temporary source copy caused **both real-clock cases to fail at 10%**.
With production source, all 14 source-browser cases passed. The exact original
intermittent application timer interleaving was not captured; this repairs a
demonstrated fixture defect and does not claim a newly discovered polling defect.
Earlier failures remain in the checkpoint. Subsequent parent-supplied independent
review of exact `9a89c49`/`400f352` supports both scoped fixes: 41 native checks,
281 functions compared with only three intended substitutions and no data or
authority change; old mixed-clock 45/5 reproduced, revised real-time 46/4 with 14
source cases passed, and both missing-restart mutants failed. It reported 64 JS
subset passes, exact edition retirement passed, photo-policy/pending-proposal
failures retained, 15 PostgreSQL allocations/roots cleaned and three frontend
servers reaped. These scopes may overlap and are not summed with author results.
The original application interleaving remains unestablished. Reviewer raw artifacts
are not available here; full aggregate was not independently rerun and CI/container/
live/real-Auth/Mac gates remain open. Human ready status does not waive those gates.

## Fixed-head results

| Check | Result |
| --- | --- |
| Complete Python, two workers, 60s case bound | **5,517 passed, 574 failed, 21 error, 259 skipped**; 6,371 XML records; 1187.14s wall |
| Native SQL repair/stage selection | **38 passed, 0 failed, 0 error, 0 skipped** |
| Upstream acknowledgement/continuity/startup selection | **219 passed, 0 failed, 0 error, 0 skipped** |
| Seven large-capacity cases, 600s bound | **7 passed, 0 failed, 0 error, 0 skipped** |
| JavaScript/composer/historical-news | **523 passed**, no failures/skips |
| Expanded browser/fixture selection | **46 passed, 4 failed, 0 error, 0 skipped**; all 14 source cases passed |
| Mobile | **87 Node + 66 UI Jest + 21 integration Jest passed**, types/lint/OpenAPI/native-config passed |
| Host web build and offline mobile JavaScript export | Passed; Node24, no native device execution |
| Acceptance catalogue | **55 passed**, MemoryStore scope |
| Localization/routes | **647 messages**, 63 required routes present among 125 |
| Syntax/whitespace | **557 Python files parsed**, whitespace passed |
| Node26 container runtime | Unrun: prior Docker registry DNS gate remains blocked; unchanged Containerfile |

The original runtime/read/transport/route/read-side-effect scopes and both SQL
conflict modules are indexed separately in the manifest. No assertion is waived
by a passing focused/capacity run. Every remaining current failure/error and skip
is indexed with trace/classification evidence and its full raw XML record.

| Current observed classification | Records |
| --- | ---: |
| `aggregate_case_time_budget` | 5 |
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
| `unresolved_process_observation_failure` | 1 |

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

Four canonical identity/recovery fixture failures remain in the expanded browser
selection. All aggregate skips remain recorded; the 14 separate source-browser
passes do not make other opt-in/CLI/plugin/live gates pass. Pending-proposal and
photo-policy decisions, older workspace/draft policy and canonical dataset/model
approvals remain open. Capacity600s passes establish only that separate bounded
correctness run; aggregate timeouts remain failures and no latency SLA is claimed.

The final aggregate also newly failed
`test_completed_process_is_reaped_before_receipt_return`: the unchanged process
fixture returned `incomplete` instead of `observation`. Its unchanged isolated
probe passed in 1.50s with the original 2s execution/.4s cleanup/.1s stop-grace
budgets. The original child temporary receipt is unavailable after pytest
retention; exact cause and that child's aggregate cleanup details are unestablished.
This remains a newly observed unresolved failure, with no assumption that it is
baseline or environmental. Compared with `59086eb`, the SQL audit improves, four
new SQL cases pass, this process case fails and one additional capacity case
times out. All outcomes remain in both raw runs and the per-case comparison.

## Retained attempts, provenance and limits

The earlier two complete integration runs and review findings are preserved
unchanged at [checkpoint affb313](https://github.com/bohui/copyme2.ai/blob/affb313a6668c930189271be660785402a8b87fe/docs/test-evidence/memoir-baseline-main-integration-20261015.md).
No older failure was assumed preexisting solely by matching status. The original
unverified 647-failure/275-error aggregate is not baseline proof. The manifest
compares every case against b4 and 59086eb, recording additions and status changes.

Diagnostic attempts remain explicit: the first observer had an import error
before tests; v2 was confounded by its timer wrappers and introduced six reload
bootstrap failures (40 passed/10 failed, with both resume snapshots 30% before
reload). This is not reproduction of the original 10% symptom. The first temporary
mutant server used the wrong standalone subpath and failed before tests; v2's
two functional failures are the valid mutation result. None is silently removed
or relabeled as passing acceptance.

Primary final helper hashes were captured before execution and verified afterwards;
per-check metadata retains exact actual arguments. Precommit probes/TDD retain
their retained source versions and receipts without claiming prior hash snapshots
for every helper. The uncommitted SQL red test file was not separately snapshotted
before the later upgrade test and Path import were added; final test bytes are
not presented as its exact earlier version. Raw native rejections and the unchanged
committed audit remain available. No earlier red source is reconstructed.
The historical qualification remains: **c747/e8 final helper
settings differ from eight earlier receipt commands; earlier versions were not
supplied.** Their receipts remain authoritative. All 42 historical originals still
match their audited hashes; no missing original or helper version was reconstructed.

Registered native roots/sessions and browser frontend/backend teardown are
verified within their task scope. Ordinary-runner zombies are reported as PID1,
not running and not reaped. No global PID-absence claim or unrelated cleanup is
made. Earlier parent-reported Mac/Node26 results remain historical and narrower;
there is no new Mac, native-mobile, live-provider or container-runtime acceptance.

[Manifest and all current unmet records](memoir-baseline-repair-20261015.json) · [Lossless raw archive](memoir-baseline-repair-20261015.tar.gz).
Archive: **150 regular files**, 490,589 bytes,
SHA256 `c39fa390b805c54edfe7943e5e3e4a55bbd0c89339c8014a88ef5b39ed81e5e5`. Every member was read back and matched to its original
bytes/hash. Full JUnit identities, problem entries, attributes and durations,
every raw check/TDD/diagnostic log/receipt and all retained helper versions are available without
redaction; long synthetic parameter IDs are abbreviated only in readable JSON.

Only disposable synthetic data/services were used. No real memoir data, provider
calls, production migration, merge to main, deployment, credential export,
access/security change or external-agent contact occurred.
