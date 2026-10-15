# PR68 recovery follow-up

Historical snapshot before the current-main integration and approved direct-only
counting rule. The [current integration/policy report](stage-progress-direct-policy-integration-20261015.md)
supersedes the unresolved attribution discussion and records final-head checks.

Reviewed head: `d96a17826fcae88dbfd5fe7b5c2f9c2a95eebb2b`.
Tested code: `a6c623329f8f697eeaa43b59b924f1b5f6de9aab`.
This follow-up preserves the reviewed commits and adds task-only updates on the
existing branch. No merge, deployment, production migration, real memoir data or
live/paid provider execution was performed.

## Reproductions and client changes

The two source-review findings were reproduced before changing the client.
An expanded deterministic suite running the actual client functions produced
**9 failed / 7 passed** on the reviewed head. Its delayed-completion case ended
with zero progress when extraction became available at 240 simulated seconds.
Its failed-final-save case showed that the newer failed read invalidated the
older healthy retry chain, leaving no subsequent read. Revision-fence failures,
immediate cancellation and hung-read cases exposed the same recovery limits.

The client now has one recovery job per project/principal/navigation scope:

- Streamed and final-save refreshes share the job. Requests are serialized, and
  refreshes arriving during a read are coalesced into the next read. A snapshot
  preceding the newer refresh is not painted.
- A later read failure keeps the last good ring and the active recovery job.
  Network failures and 409/503 revision-fence failures retry with 2/4/8/16-second
  backoff. Permanent 400/401/403/404/422 responses stop recovery.
- Recovery has a five-minute deadline after the latest explicit save/reload,
  covering the repository extractor's supported 240-second call. Automatic
  retries do not renew the budget. Each read has a ten-second deadline.
- Navigation aborts requests and timers immediately. Scope/job identity checks
  also reject late results. A hung auth/fetch operation cannot retain the job
  after cancellation because the read races its abort signal.

That finite window does not guarantee completion of longer queued, retried or
multi-page extraction. If it expires, a later explicit save/reload starts another
window; these author tests do not establish arbitrary-delay live recovery.

The **17 recovery cases pass**, including completion after 240 seconds, a failed
newer read during an older pending poll, repeated fenced failures, coalesced
ordering, hung-read rejection, project/principal/navigation isolation, permanent
auth failure, a fresh budget for a later save, and finite cleanup. Tests enforce
at most 25 reads per idle recovery window. The curve, colors, CSS and SQL function
are unchanged in this follow-up.

## Current executed checks

| Check | Result |
| --- | --- |
| JavaScript/composer/historical-news aggregate | 516 passed, no failures/skips |
| Focused backend/readiness/read/commit/persistence plus provenance/cost | 61 passed, no failures/skips |
| Production Next + real fenced HTTP read + disposable PostgreSQL + Chromium | 4 passed, 4 old cases deselected |
| Isolated provenance/cost rerun with statement ceilings | 3 passed |
| Acceptance catalogue | 55/55 passed |
| Production web build, mobile TypeScript, JS syntax | Passed |
| New/updated recovery test lint | Passed |
| Whole-PR changed-JavaScript ESLint selection | 5 known unused-binding findings; no new findings |
| Localization/ICU and specification routes | Passed: 647 messages; 63 required routes represented among 125 app routes |

The production browser covers ready and delayed/fenced cases in both locales.
For delayed cases, it saves a real canonical reply without stage evidence,
observes `pending`, advances the browser clock by 120 seconds, injects 409, advances
another 120 seconds, injects 503, persists stage evidence, then advances another
16 seconds. Progress recovers without another turn/reload; actual painted arc
coverage, other-stage isolation and a subsequent reload are checked. Failures are
injected at the HTTP seam, not claimed as an actual concurrent revision race.
The resulting synthetic production screenshots were opened and inspected.

## Dependency attribution remains an acceptance question

The new representative fixture uses actual `apply_user_memory_events`
persistence, rather than directly inserting simple stage links. It has birth,
school and bakery events plus separate temporal, stage and relation evidence.
The current readiness query counts event-source dependencies beyond
`stage_evidence`:

| Observed stage | Word equivalents |
| --- | --- |
| Baby | 5, from the birth statement |
| Childhood | 21: primary school 6 + shared birth basis 5 + stage evidence 5 + relation evidence 5 |
| Midlife | 7, from the bakery statement |
| Childhood after excluding its shared birth dependency | 16; baby remains 5 |

This characterization verifies present SQL behavior, **not approval of that metric
definition**. Shared provenance can contribute words to two stage totals. Whether
primary narration, dependency context, or another explicitly approved attribution
should drive stage volume remains unresolved. No new SQL attribution formula was
introduced to settle that question implicitly.

## Bounded query-cost evidence

The benchmark bulk-seeds synthetic canonical source/reply/event projections,
with 3,584 original characters per source and three overlapping evidence links
per source. It verifies union/deduplication totals, performs three post-warmup RPC
samples, and exposes the aggregation's inner `EXPLAIN (ANALYZE, BUFFERS)` plan under
the fixture's security-definer owner with the synthetic `auth.uid`. Queries have
a 20-second statement ceiling and setup has a 30-second ceiling.

| Sources / evidence links | RPC samples while other checks ran, ms | Otherwise-idle executor samples, ms |
| --- | --- | --- |
| 1,000 / 3,000 | 420.776, 432.193, 428.386 | 276.869, 292.226, 299.970 |
| 5,000 / 15,000 | 6603.166, 3251.242, 2436.400 | 1593.699, 1421.553, 1334.681 |

The 5,000-source aggregation plan scans and aggregates the full scoped history
and spills temporary data. Poll backoff bounds the number of reads but does not
remove their cost. These samples **do not establish production concurrency,
larger-history capacity or a guaranteed margin under the ten-second client read
deadline**. Ingestion, live extraction, HTTP/publication overhead and production
load are outside this experiment. The [check artifact](stage-progress-recovery-checks-20261015.json)
contains timings, complete flattened aggregation-plan node fields and raw-report
hashes from both runs.

## Reproduce and remaining gates

```sh
export PATH="/workspace/copyme2.ai/.venv/bin:/workspace/.tools/postgresql/usr/lib/postgresql/17/bin:$PATH"
export LD_LIBRARY_PATH=/workspace/.tools/postgresql/usr/lib/x86_64-linux-gnu
node --test tests/js/stage-readiness.test.mjs tests/js/profile-menu-races.test.mjs
node --test tests/js/*.test.mjs skills/memoir-composer/tests/*.test.mjs tests/historical-news/*.test.mjs
MEMOIR_READINESS_COST_REPORT=/tmp/readiness-cost python -m pytest -q -s tests/test_stage_readiness_provenance.py
MEMOIR_BROWSER_URL=http://127.0.0.1:3141 MEMOIR_BROWSER_EXECUTABLE=/usr/bin/chromium python -m pytest -q tests/test_stage_readiness_browser.py -k canonical
```

The last command expects the production Next server built from this code on port
3141. These are author-executed checks in the existing executor. The review
handoff reports that fresh independent cloud runtime creation failed; this update
does **not** complete independent execution or approval. Branch-protection and
required-check configuration remain unverified after the handoff's reported 403.

The full Python aggregate was not rerun in this client follow-up; its prior
baseline failure/skip gates, older browser baseline failures and non-clean lint
gate remain visible in the [initial report](stage-progress-regression-20261015.md).
Those earlier baseline comparisons are against the recorded initial base, not
a claim that newer main revisions have passed. The supplied Library screenshot
still has not been materialized. **Acceptance remains incomplete.**
