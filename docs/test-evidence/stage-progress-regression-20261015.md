# Memoir stage-progress ring repair

This is the initial PR68 review snapshot. The [recovery follow-up](stage-progress-recovery-20261015.md)
supersedes the original thirty-second retry behavior and records the current
checks, realistic dependency characterization and bounded query-cost evidence.

The canonical interview path lost stage progress at the persistence/read boundary,
and the client stopped refreshing it after saved turns. The existing CSS paints
the correct arcs when it receives nonzero percentages.

Base: `d12fac8a2b20cea3922a5994904d1fb8a7f17e21`. Tested code commit:
`0d58b2c0a309fb8cd25da174f0201916e4b7f09f`. Subsequent task changes only record
this evidence and the production screenshots. Work used an isolated cloud
worktree and branch; the original checkout was preserved. The only open PR found
was #67, the separate historical-news review; it was left alone.

## Root cause and repair

1. `commit_lifetime_turn` deliberately saves canonical `user_memory` rows with
   `life_stage='unplaced'`, and records the durable reply receipt. Stage placement
   now lives on canonical events and their versioned narrator evidence links.
2. `read_lifetime_stage_readiness` still summed `user_lifetime_stage_volume` by the
   legacy memory-row stage. Thus committed canonical narration with staged event
   evidence returned zero for every stage, including after a cold reload.
3. The web client applies optional `stage_readiness` workspace payloads, but the
   canonical runtime does not supply that field. It did not refresh readiness on
   `conversation_saved`. A slower earlier read could also overwrite newer totals.
4. `lifeStageNavigator` correctly uses each stage's `percent` and `color` for its
   custom property and class. The conic-gradient CSS correctly renders those
   values. A zero-percent foreground produces the reported grey ring behavior.

The additive `202610150003_canonical_stage_readiness.sql` migration reads current,
active evidence spans associated with each staged canonical event, restricted to
saved narrator replies. It unions overlapping spans within each source/stage,
checks exact source versions and text, and retains legacy explicitly staged
response totals without double-counting canonical receipts. Reassignment,
exclusion, edits and withdrawal are reflected on fresh reads. Existing evidence
rows are not rewritten or backfilled.

The existing Unicode word-equivalent counter and percentage/color curve remain:
100 words → 10% red; 300 → 30% amber; 1,000 → 50% green. Below 300 the curve is
words/10; from 300 to 1,000 it interpolates 30–50%, capped at 50%. This measures
stage context volume. Assistant text and words assigned only to another stage do
not contribute.

The client now refreshes on both the streamed save receipt and the final saved
response, as well as reload. A `pending` flag permits up to fifteen two-second
retries while extraction finishes. Scope and request-sequence checks reject stale
reads and queued retries after newer requests, navigation or principal changes.
CSS and the percentage formula were not changed.

Attribution is explicit: canonical progress counts the persisted stage evidence
spans, not all unlinked words in a multi-stage response. Unplaced and unsaved
material stays at zero. Live extractor span coverage and extraction taking longer
than the retry window were not evaluated; the next turn/reload reads fresh totals.
Large-history query performance has not been benchmarked.

## Verification

Before the fix, new PostgreSQL regressions produced **10 failures / 1 pass**:
canonical commits with staged evidence returned zero at all requested thresholds.
New client regressions produced **2 failures / 3 passes** for missing refresh,
same-project stale reads, and scope isolation. This established the failures
before implementation.

Final checks on the rebased code:

| Check | Observed result |
| --- | --- |
| Focused readiness, read API, canonical commit and persistence tests | 58 passed, no failures/skips |
| JavaScript, composer and historical-news aggregate | 508 passed, no failures/skips |
| Production Next + real HTTP readiness route + disposable PostgreSQL + Chromium | 2 passed (`en-AU`, `zh-CN`); 4 old scenarios deselected |
| Acceptance catalogue | 55/55 passed |
| Production web build | Passed |
| Mobile TypeScript projects | Passed |
| Localization catalogue / ICU | Passed, 647 messages |
| Specification route audit | Passed, 63 required routes represented among 125 app routes |
| New test / other changed JavaScript lint; client syntax; diff whitespace | Passed |
| ESLint over all changed JavaScript, including existing client/latency test | 6 unused-binding findings; identical 6 on baseline |
| Broader backend selection | 123 passed, 27 failed; baseline has 110 passed, the identical 27 failures |
| Full Python aggregate, fail-fast | 19 passed, 10 skipped, 1 failed; remaining cases unrun |

The 27 backend failure IDs were compared exactly against unmodified current main.
They include native runtime fixtures assuming `-p` in the PostgreSQL command and
legacy/unmapped read fixture failures. The full-suite stopping failure is
`test_agent_turn_forwards_original_text_separately_from_prompt[None-application/json]`
(503 instead of 200), also reproduced individually on main. The earlier
unbounded aggregate attempt was interrupted after stalling; it is not a pass.
The original English stage/private-draft browser scenarios also fail on baseline
at workspace/private-draft expectations. Those unrelated behaviors were not fixed.

The new browser cases do not mock progress totals. They commit canonical replies,
persist exact synthetic stage evidence, call the actual fenced HTTP read route,
and exercise the real frontend. They check empty stages, threshold colors,
15.7% fractional coverage, a newly saved reply, cross-stage isolation and reload.
Painted ring pixels are sampled against expected arc fractions (±4 percentage
points), alongside CSS/class assertions. External browser requests are blocked
except the synthetic auth seam. The production screenshots were opened and
inspected:

![English synthetic stage rings](stage-progress-rings-en-AU.png)

![Chinese synthetic stage rings](stage-progress-rings-zh-CN.png)

The supplied Library screenshot could not be materialized: its supported transfer
failed, and the download host did not resolve in this executor. No local image
bytes existed, so no assertion relies on that image's appearance.

## Reproduce in this executor

From the repository root, use the existing Python test environment and native
PostgreSQL binaries:

```sh
export PATH="/workspace/copyme2.ai/.venv/bin:/workspace/.tools/postgresql/usr/lib/postgresql/17/bin:$PATH"
export LD_LIBRARY_PATH=/workspace/.tools/postgresql/usr/lib/x86_64-linux-gnu
python -m pytest -q tests/test_stage_progress_regression.py tests/test_stage_readiness.py tests/test_lifetime_memory_read_api.py tests/test_lifetime_memory_commit.py tests/test_persistence.py
node --test tests/js/*.test.mjs skills/memoir-composer/tests/*.test.mjs tests/historical-news/*.test.mjs
MEMOIR_BROWSER_URL=http://127.0.0.1:3140 MEMOIR_BROWSER_EXECUTABLE=/usr/bin/chromium python -m pytest -q tests/test_stage_readiness_browser.py -k canonical
```

The browser command expects the task-owned production Next server on port 3140
(`npm --prefix apps/web run build`, then `npm --prefix apps/web run start -- --hostname 127.0.0.1 --port 3140`).
The broader backend command adds `tests/test_lifetime_memory_runtime.py` and
`tests/test_lifetime_memory_reads.py` to the focused selection. The full aggregate
used `python -m pytest -v -x --tb=short -o faulthandler_timeout=45`.

Versions: Python 3.12.14, Node 24.19.0, PostgreSQL 17.11, Chromium 154.0.8037.57,
Next 16.3.6. [Machine-readable check summary](stage-progress-checks-20261015.json)
records the baseline failure IDs and acceptance status.

**Acceptance remains incomplete.** The draft PR needs independent review and the
non-clean aggregate/lint/browser gates remain visible. Only disposable synthetic
databases were migrated. No real memoir data, production migration, deployment,
merge, paid/provider execution, or credential export was performed.
