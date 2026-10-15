# PR68: current-main integration and approved direct-only counting

Current main/base: `e190885a21dc422faa7d17f34daaa3e943f30a39`.
Final tested code: `933e3611072d0e3735c342860f784078dc80aa2a`.
Previously reviewed PR head: `2508022616fc0235d7742704e4db290d62bc5b45`.
The following evidence commit changes documentation only.

## Current main is integrated without altering acknowledgement behavior

The four task commits were rebased cleanly onto verified current main. At the
rebased pre-policy checkpoint `5f6862ff57924ca584fe04cf3e3eb620c5d4b262`, the tree
delta from the reviewed head was exactly main's six-file acknowledgement-latency
change. All six files matched main's blobs. After the direct-only policy patch,
those upstream files still match main byte-for-byte; the client recovery source
also still matches the reviewed head. The check artifact records blob IDs and
the rebase range-diff. Rebase preserves the patches, but the historical reviewed
commit IDs are not ancestors of the rewritten branch.

The 115 targeted acknowledgement/transport/schema/timing/publication checks pass
on the combined code. The real-API tests exercise both worker and in-process
execution with disposable PostgreSQL and substituted model I/O: the safe
acknowledgement arrives while the private proposal remains blocked, no round is
committed early, the final reply contains the acknowledgement once, and replay
does not generate again. Privacy timing and publication/cancellation fences pass.

## Approved rule and failing regressions

The user approved counting only directly assigned stage evidence. The readiness
query now requires a current eligible event-source span to be explicitly included
in that event's `stage_evidence`. Primary, temporal, relation and other dependencies
that are only context do not contribute. Genuine explicit attribution to multiple
stages remains supported. Overlapping/duplicate direct spans count once within
each source/stage. Legacy explicitly staged response totals, word-equivalent
counting, percentage interpolation and colors are unchanged.

Before the SQL patch, the new policy suite had **3 failures / 1 pass** (two cost
cases deselected). It demonstrated these overcounts:

| Case | Before | Approved result, now passing |
| --- | --- | --- |
| Birth and relation context reused for school | Childhood 21 words | Childhood 11 direct words; baby remains 5 |
| Separate childhood/midlife spans in one source | 17 words in each stage | 6 directly assigned words in each stage |
| A source explicitly supporting both stages, plus birth background | 13 words in each stage | 8 directly assigned words in each stage |
| Duplicate and overlapping direct assignments | Already deduplicated | 200 words once in childhood; midlife zero |

Excluding reused birth background no longer changes childhood's direct total.
The original threshold tests still verify **100 words → 10% red; 300 → 30% amber;
1,000 → 50% green**, with the original fractional interpolation and 50% cap.
The unreleased PR migration was updated; no source evidence was rewritten and
no production migration was applied.

## Executed final checks

| Check | Result |
| --- | --- |
| SQL/readiness/read API/commit/persistence + approved provenance/cost | 64 passed, no failures/skips |
| Targeted upstream acknowledgement, transport, schema, timings, real save and publication | 115 passed, no failures/skips |
| JavaScript/composer/historical-news aggregate | 516 passed, no failures/skips |
| Production Next + actual fenced HTTP read + disposable PostgreSQL + Chromium | 4 passed, 4 old scenarios deselected |
| Production web build and mobile TypeScript | Passed; frontend unchanged by subsequent SQL-only policy patch |
| Acceptance catalogue | 55/55 passed on the integrated code before the SQL-only patch |
| Localization/ICU, route audit, recovery-test lint, JS syntax, whitespace | Passed; these source inputs were unchanged by the SQL-only patch |

The production cases cover ready and delayed/fenced recovery in both locales,
including 256 simulated seconds with 409/503 injection, painted arc coverage,
cross-stage isolation and reload. Their final synthetic screenshots were opened
and inspected. These remain author-executed tests, not fresh independent runtime
verification or live extractor/provider evaluation.

For broader visibility, the pre-policy integration selection produced **144 passed
/ 5 failed**. The five diagnostics failure IDs were reproduced exactly on current
main (**32 passed / 5 failed** in that file). The full actual-engines file produced
**2 passed / 12 failed**, with the identical 12 legacy-fixture failure IDs on current
main. These fixtures omit the required canonical contract or refer to retired
worker hooks. They were not repaired or relabeled as passes. The post-policy
115-case targeted run passes; the broader known-failing files and full Python
aggregate were not rerun after the SQL-only patch.

## Query cost and acceptance limits

The bounded cost fixture now explicitly declares its direct stage assignments,
so the revised query does real work rather than returning empty totals. It uses
1,000/5,000 synthetic saved source projections and 3,000/15,000 overlapping direct
links, with 20-second query and 30-second setup ceilings. With other checks on
this executor, the three RPC samples were:

| Sources | RPC execution times, ms |
| --- | --- |
| 1,000 | 426.339, 349.590, 365.337 |
| 5,000 | 2305.647, 1933.992, 1734.138 |

The query still scans scoped history and can spill temporary data. These samples
and recorded plans do not establish production capacity, concurrency, larger
histories or a guaranteed ten-second client read margin. Earlier different-policy
measurements in the historical recovery report are not substituted for these.

The five-minute recovery budget does **not** guarantee completion of longer
queued, retried or multi-page extraction. A later explicit save/reload may be
needed after expiration. No unbounded polling was added.

Source re-review reportedly cleared the two original client P2 cases at the prior
head. Independent final-head/fresh-runtime execution remains incomplete after the
reported runtime creation failure. Required-check and branch-protection settings
remain unverified after the reported 403. Original full-suite, older-browser,
lint, live-extractor and supplied-Library-image limitations remain visible in the
historical reports. **Acceptance remains incomplete.**

[Machine-readable integration proofs, failure IDs, checks and direct-policy query plans](stage-progress-integration-checks-20261015.json)
records exact details. Reproduce the final focused tests with:

```sh
export PATH="/workspace/copyme2.ai/.venv/bin:/workspace/.tools/postgresql/usr/lib/postgresql/17/bin:$PATH"
export LD_LIBRARY_PATH=/workspace/.tools/postgresql/usr/lib/x86_64-linux-gnu
export MEMOIR_TEST_POSTGRES_BACKEND=native-tcp
python -m pytest -q tests/test_stage_readiness_provenance.py tests/test_stage_progress_regression.py tests/test_stage_readiness.py tests/test_lifetime_memory_read_api.py tests/test_lifetime_memory_commit.py tests/test_persistence.py
python -m pytest -q tests/test_lifetime_memory_engine.py tests/test_lifetime_memory_transport.py tests/test_collector_canonical_schema.py tests/test_subscription_stream_diagnostics.py::test_protocol_message_timings_do_not_log_private_text tests/test_subscription_stream_diagnostics.py::test_protocol_progress_is_scoped_counts_queued_items_once_and_records_completion tests/test_lifetime_actual_engines.py::test_first_visible_ack_precedes_proposal_completion_and_durable_save tests/test_lifetime_memory_publication.py tests/test_lifetime_outer_publication.py
node --test tests/js/*.test.mjs skills/memoir-composer/tests/*.test.mjs tests/historical-news/*.test.mjs
MEMOIR_BROWSER_URL=http://127.0.0.1:3142 MEMOIR_BROWSER_EXECUTABLE=/usr/bin/chromium python -m pytest -q tests/test_stage_readiness_browser.py -k canonical
```

The browser command expects the task-owned production Next server on port 3142.
No PR merge, deployment, real memoir access, credential export, or live/paid
provider call was performed.
