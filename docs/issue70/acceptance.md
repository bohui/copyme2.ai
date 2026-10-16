# Issue 70 review handoff

Draft PR: https://github.com/bohui/copyme2.ai/pull/71
Base: `83e48e166568fe949eccd6f68ffa13273dcf55af`.
Source/test head: `481f42ae693bc91b8a7c2ac1b1adb93091627935`.
Later commits contain evidence only; inspect the exact current PR head before review.

The bounded vertical slice is implemented. **Full issue acceptance is false.**
Both the environment flag and private database rollout row default OFF. Installing
this schema does not activate it. No production migration, deploy, access or
credential operation, paid/live-provider campaign, merge, review comment or
external-agent contact occurred. No existing owner of #6/#41/#53/#66 was replaced.
Original checkout and the separately created exact-base checkout stayed clean.

## Implemented behavior

A accepts the original with a canonical ID/sequence before generation, pins the
existing authorized checkpoint and complete tail, and uses one normal collector
pass for reply, chosen question and work decision. Current literal policy and
language remain application-owned. It validates/persists the required plan and
reply before `reply_complete` / `conversation_saved`, with a distinct durable
reply_id. A failed commit remains source-accepted/pending and blocks a different
accepted turn until reconciliation. Technical replay keeps both identities and
adds no source, question or charge.

B is the existing unique project timeline lane. Acceptance transactionally wakes
its monotonic newest target. An active A without a saved work decision makes B
yield without a model call. After A failure/lease release, the accepted original
remains an extraction obligation. Reply-only work can finish empty without a B
model call. Extract work adds optional coarse places and evidence-linked prepared
questions to the existing bounded extraction pass, not another foreground pass.
Exact page/source versions, policy/preference revisions, phase, generation and
lease receipts fence commit/retry. B never delivers a question, changes language,
grants access, publishes or records a completed round.

Bounded B maintenance uses canonical compaction/proof/checkpoint tables with
32-window steps and predecessor CAS, through at most snapshot high-water minus
one. It preserves all raw-position/tombstone coverage. This is canonical raw
coverage plus exact excerpts, not a claim of an all-source semantic summary.
Composer summary_source, character summary_offset, 2,000-character fragments and
completed-round ordinals are untouched. Occupancy overflow remains explicit
bounded catch-up/fail-closed. Cold bounded execution remains the safe default.

The existing bounded readiness poll carries independently authorized workspace
snapshots. Ordinary B delay/failure/empty extraction preserves stored places,
selection, recording and valid photo/group metadata; privacy revisions discard
old decorations/inaccessible places. No background result is saved as preference
authority. A targeted `POST /v1/story/memory/retry` retries only the timeline lane.
Worker capacity bounds four active requests/two background requests and eight
waiters per lane, including serial-lock waits, with a five-second admission bound.
This reserve is per worker; aggregate provider quota/reservation is unproven.

20 free turns, configured five-round private-draft cadence/opt-in and the
7,000-word chapter cap (including headings/captions) retain existing authority.

## Acceptance checklist

| AC | Evidence and status | Remaining gate |
|---|---|---|
| 1 | Default-off API and private DB guard; flag-off canonical regressions, replay/save/source identities preserved; direct RPC cannot activate rollout. | Independent rollback review; no production migration was run. |
| 2 | PASS, deterministic: real native SQL + actual governed NDJSON/ASGI barriers hold B at provider while A text, useful chosen question, save and final result complete. B failure cannot undo it. Commit failure blocks overlapping acceptance and retry keeps the original source. | Live latency/semantic quality is separate. |
| 3 | Seven flag-on controlled cases cover name-only, rich Chinese, short clue, language request, explicit question, pause and sensitive correction; complete two-turn/resume/replay test consumes a prepared hint with one A call per turn. Existing runtime regressions cover later/privacy/language behavior. | Controlled proposals prove contracts, not actual model choices; blind live quality remains unrun. |
| 4 | K20/current23 complete-tail + tombstone test; missing gaps fail. B proof scans a long Unicode backlog in bounded resumable windows, checks exact versions and keeps composer cursors unchanged. Existing context overflow checks pass. | The inherited 10,000-turn aggregate timeout remains failed, not waived. |
| 5 | Stale source, privacy/policy, generation, phase, lease and rollout results reject; cross-account candidate read denied. Existing publication/policy and protected-edit checks remain required. | Independent complete race/access/cancellation review. |
| 6 | Burst target coalesces to four; concurrent claims acquire one owner; expired lease restarts at committed page, old token rejects, durable obligations remain, no completed round from B. Identical replay is idempotent. | Full production-like interruption/worker/transport review remains a release gate. |
| 7 | Relevant canonical composer/policy/clearance/place regressions, full JS and English/Chinese source-browser update ordering passed. Empty/failed updates and policy removal are covered. | Existing broader photo/composition/opt-in and aggregate failures remain; no live uploads/providers validated. |
| 8 | Existing bounded cold collector/lane adapter and interruption tests retained; no shared resumed transcript. Interactive reserve and finite queue/cancellation tests pass. Official protocol source checked. | Provider-wide quota across replicas and actual harness/provider validation unproven; no unsupported warm-pool API added. |
| 9 | Preregistered model/scenarios/revisions/sample counts/deadlines and call/token ceilings in architecture-and-benchmark.md, before live dispatch. | No live authorization or funded cost ceiling; effective provider usage/cost and playable audio unmeasured. |
| 10 | BLOCKED. No live improvement or absolute SLA claimed. | Authorized matched baseline/candidate evidence must show useful-question improvement with no safety/save/quality degradation. |
| 11 | Task-only isolated worktree, failing tests first, task-only commits/pushes, draft PR and raw evidence. | Independent cloud review of the exact published head; aggregate is not all green. |

## Test provenance

Read verification.json and the compressed raw JUnit/log bundle. Counts from
separate overlapping runs must not be added together. Aggregate failures/skips
stay failed/skipped even where supplemental checks pass.

The initial unbounded aggregate was interrupted and preserved. The preliminary
bounded aggregate ran during development and is not final acceptance. The later
full aggregate started at 0acbf01; the last SQL change was only application
conflict code 40001 → PT409, and the last JS change preserved workspace metadata.
All final feature/catalog, JS and source-browser checks were rerun after those
changes. The source/test manifest records final file hashes. This timing is
explicit: do not pretend every aggregate case ran against one immutable final
snapshot. The final aggregate and supplemental final-source checks are separate
evidence; independent review may require a fully frozen rerun.

Exact-base comparison uses an additional detached task-owned worktree at the
base SHA: 36 runtime, PostgREST and Temporal cases pass. Six Temporal cases that
fail in aggregate while trying to download a server pass separately with the
preinstalled official local CLI and the same 60-second case budget. A broader
29-case local-CLI run has 24 passes/five failures; every failure is in the bundled
historical baseline. They are not converted to passes.

## Release blockers

- Independent exact-head review and resolution/disposition of inherited aggregate
  failures, skips and unresolved product contracts.
- Approved matched live model/quality/latency campaign, funded cost ceiling,
  observable usage/cost, and audio evidence where supported. No dispatch occurred.
- Confirmed shared-provider quota and reserved interactive capacity across
  replicas. Current in-worker limits alone do not prove that reservation. The
  API and worker must both receive the environment flag during an approved
  rollout; container configuration/enablement was not changed here.
- Separately authorized production migration/configuration/enablement; both
  rollout controls remain OFF. No merge or deployment is authorized here.

## Final recorded results

- Full Python aggregate: **5,542 passed / 576 failed / 21 errors / 261 skipped**,
  6,400 records, three warnings, 902.35 seconds. This run is failed.
- Of the 576 failures, 570 are in the bundled historical failed set and six
  attempted a Temporal server download. All six pass separately using the local
  CLI with the same 60-second case budget. All 21 error identities are historical.
  This is classification, not rewriting the aggregate result.
- Final feature + application-conflict checks: **32 passed**, no skips (27 feature
  cases and five PostgREST checks). Earlier relevant canonical regression run:
  **291 passed**; these overlap and must not be summed.
- Final full JavaScript set: **530 passed**. Final source Chromium cases:
  **two passed**, English and Chinese; synthetic API/auth/readiness only.
- Exact-base selected comparison: **36 passed** at 83e48e1. Supplemental local-CLI
  run: six previously masked cases passed; broader 29-case run remains
  24 passed/five historical failures.
- Changed Python syntax, changed JS syntax, and git diff whitespace checks passed.
  No configured first-party ESLint executable was available. Production build,
  real auth/storage/providers, playable audio, and live model quality/latency
  checks were not run. Existing skipped/live/product gates are retained.

The older bundled comparator has one container-cache test identity renamed on
main (now dependency_change), and two older failures now pass. No test was removed
by this branch; the complete differing identity list is in case-ledger.json.gz.
Parent-reported current-main 5,521/570/21/259 is context, not a fresh full-base
execution claim. The two new source-browser cases are skipped in the aggregate
and pass separately; their aggregate status remains skipped.

## Reproduction

Use a non-root disposable environment with Python dependencies, native PostgreSQL
17 tools/psycopg, Node, Playwright + Chromium, and a local official Temporal CLI.
The aggregate additionally uses pytest-xdist 3.8.0, pytest-timeout 2.4.0 and
execnet 2.1.2. Clear application/provider credentials and live opt-ins before
running; all PostgreSQL fixtures create their own random /tmp cluster. The
feature test fixture changes only its own disposable rollout row.

Commands (put the required executables/libraries on PATH/LD_LIBRARY_PATH):

```sh
python -m pytest -q tests/test_two_lane_memory.py tests/test_postgrest_application_conflicts.py
python -m pytest -q -n2 --dist=loadfile --timeout=60 --timeout-method=signal --tb=short
node --test tests/js/*.test.mjs skills/memoir-composer/tests/*.test.mjs tests/historical-news/*.test.mjs
```

For Temporal checks set `MEMOIR_TEST_TEMPORAL_CLI` to an absolute executable path;
our supplemental path was `/workspace/.tools/temporal/temporal`. For the source UI,
run Next from apps/web on a task-owned loopback port with `next dev --webpack
--hostname 127.0.0.1 --port 31170`, then run
`MEMOIR_BROWSER_URL=http://127.0.0.1:31170
MEMOIR_BROWSER_EXECUTABLE=/usr/bin/chromium python -m pytest -q
tests/test_two_lane_browser.py` as one shell command. Stop that frontend afterwards.
The temporary node_modules dependency link used here was removed; no dependency
or deployment configuration change is committed.

The raw archive keeps red tests, failed development/environment attempts,
interrupted/preliminary aggregate evidence, final JUnit/logs and source hashes.
`verification.json` indexes hashes and outcomes; `case-ledger.json.gz` retains
all final failure/error/skip identities and reasons.
