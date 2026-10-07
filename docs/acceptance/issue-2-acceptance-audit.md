# Issue #2: trajectory-evaluation acceptance audit

Audit base: `291622826cdfb776e946dcd92b65d2fdaf4923ad`, tree
`1b5ab8687053bd18e8dbf44609430a60a2917918`, independently confirmed as
GitHub `main` on 2026-10-06. [Issue #2](https://github.com/bohui/copyme2.ai/issues/2)
is open, labelled `ready-for-agent`, and has no comments or literal acceptance
criteria section. This audit maps its 35 user stories and eight testing decisions.
**Keep #2 open.** Scoped passing tests, code review, provider connectivity, and
full product acceptance are different claims.

## Evidence boundaries

- The initial read-only audit reran the exact-main trajectory, checked-in synthetic cases,
  skill installation, runtime configuration and five-case evaluator tests:
  **48 passed, zero failures/errors/skips**. That initial check did not rerun
  native services, browsers, providers, judges, Langfuse or the full repository
  suite. Later repair-branch checks are recorded separately below.
- Checked-in synthetic cases use controlled model replies. Native PostgreSQL /
  Temporal fixtures with controlled replies exercise real application and
  persistence behavior, but cannot establish extraction or prose quality.
- Synthetic storyteller fixtures with actual provider calls are valid live
  evidence at the seam exercised. The earlier four actual provider requests
  (four HTTP 200 responses, 394 reported tokens) establish connectivity only;
  they did not execute the application 250-round campaign.
- The parent reports a separate, conditional ten-round/two-draft application
  canary, capped at 80 new actual requests. It has not run. This does not approve
  or establish five × 50, photos, geocoding or semantic judging.
- Historical workload counts remain tied to their original source and revision.
  Neither historical runs nor a full controlled 250-round fixture establish the
  requested exact-main five × 50 live acceptance.

## Ownership and current checkpoints

| Owner | Verified source or reported checkpoint | What remains |
|---|---|---|
| [#12 canonical launcher](https://github.com/bohui/copyme2.ai/issues/12) | `codex/issue12-guarded-app-launcher`; owner reports `12ceb2306b2658e64146165dad6fd3a31261b82e`, 265 offline passes, two native tests deselected | Native resource/actor compatibility; route/auth accounting reconciliation; reviewed exact-main live canary; separately bounded 250-round campaign |
| [#13 skill acceptance](https://github.com/bohui/copyme2.ai/issues/13) | Published `be0b9ef95ef57b999f99b5a458b776733c3d1b61` in [PR20](https://github.com/bohui/copyme2.ai/pull/20); owner reports 160 focused passes/four live skips and 1,086 offline passes/183 skips | Independent review requests a fix: non-executed UI receipts can falsely pass; explicit versus natural selection; actual loaded versions; eight-input live pilot/four followups; seven-skill live outputs; semantic review |
| [#14 provider accounting and judging](https://github.com/bohui/copyme2.ai/issues/14) | Owner reports reviewed `beab363e4b903f5d25a94adf75e018931edc62b8`, 251 affected offline passes/two native deselections and 62 independent focused probes | No live/native actor test or durable gateway rows; verified existing route/auth; full bounds and cost; authorised judge; named reviewer/date/calibration; fixed-case variants |
| [#15 Langfuse linkage/replay](https://github.com/bohui/copyme2.ai/issues/15) / [PR18](https://github.com/bohui/copyme2.ai/pull/18) | Draft head `701032f608a7d4c35b3ad098cf3ff1ec7c705563`; narrow code review cleared; retained post-exit API/ClickHouse receipt | Authenticated browser; canonical run/case/round/step joins; retention decision; final evidence review. Repeated same-process submissions are proven; live restarted-process / cross-UTC-date replay is not |
| [#6 persistence](https://github.com/bohui/copyme2.ai/issues/6) | Active `codex/issue6-canonical-contract-20261006`, staged tree `6beb9fda506fca1f59f0160d3fdda2c2bd0ede73`; owner reports 200 Python + 62 Node controlled passes, four native tests skipped | Independent rereview of legacy carry-forward/offset fixes; publication decision; native exact-head validation; live stories 1/2/8/9/34/36 |
| [#1 localization](https://github.com/bohui/copyme2.ai/issues/1) / [PR19](https://github.com/bohui/copyme2.ai/pull/19) | Draft head `0ccd6cb60bfe10c17c64fce5bdacd2474e48d46f`; catalogue/locale fallback fixes | Independent review, browser and native-speaker/product decisions. This is an adjacent bilingual UI gate, not proof of #2 trajectory quality |

Owner reports above are not independent reruns by this audit. Active branches may
advance; use the final reviewed and landed SHA for acceptance execution.

PR18's retained readback at `2026-10-06T13:30:04.556670+00:00`, after publisher
exit, found three identical submissions produced one logical API score and one
ClickHouse `FINAL` row, retaining the original millisecond UTC timestamp and
worker-child linkage. The 3,750 historical logical rows retained fingerprint
`10146712981589141912`; retention remained NULL. These facts supersede the older
blanket statement that durable duplicate replay was entirely unverified. They
do not supply missing browser or canonical-run evidence.

## Exact user-story map

“Contract” below means scoped deterministic evidence, not full live acceptance.
Source test names and the earlier native receipts are indexed in the
[prior disposition](../landing-issue-disposition-20261005.md#test-references).
The original issue defines each numbered story verbatim.

| Story | Requirement | Current evidence / limit | Closure owner |
|---:|---|---|---|
| 1 | One local evaluation command | Generic synthetic CLI and canonical fixture CLI exist; live canonical launcher incomplete | #12 |
| 2 | Same application/private-worker boundary | Synthetic runtime tests pass; native canonical evidence exists, live application canary not run | #12 + #6 |
| 3 | Isolated synthetic storyteller/project | Contract fixtures isolate/refuse reused projects; five fresh live identities need receipts | #12 |
| 4 | Declarative message/context/entitlement/language/skills/outcome | Checked-in cases and reproducible-context test pass | #12 manifest |
| 5 | Pin application, skills, model, provider, evaluator | Code hashes/versions exist; actual execution/configuration pins pending | #12 + #14 |
| 6 | Explicit enabled-skill testing | Controlled synthetic case contract; live loading/adherence unavailable | #13 |
| 7 | Natural skill selection | Selection fixtures exist; real positive/negative behavior unavailable | #13 |
| 8 | Record loaded skill/reference versions | Filesystem manifest exists; actual process-loaded readback absent | #13 |
| 9 | Pre-action context | Fresh recorder test passes; live case evidence still required | #12 / #13 |
| 10 | Tool, normalized arguments, action category | Fresh protocol normalization test passes | #12 live receipt |
| 11 | Ordered results/errors/timeouts/retries | Fresh recorder and bounded-retry contracts pass | #12 live receipt |
| 12 | Application validation, persistence, publication, artifacts | Deterministic recorder contracts and prior native public-state checks; live joins incomplete | #6 + #12 |
| 13 | Exclude private reasoning | Fresh recorder and protocol-reasoning omission tests pass | #15 export audit |
| 14 | Visible response, stop/status, final state | Terminal outcome contract passes; unhandled generic callback exception currently loses result persistence | #2 repair + #12 |
| 15 | Deterministic permission/schema/grounding/ownership/budget/state gates | Fresh core trajectory gates plus prior domain/native tests; not semantic quality | #6 + #12 + #13 + #14 |
| 16 | Run-level and failed-step trajectory scores | Mock target/linkage tests pass; accepted semantic scoring unavailable | #14 + #15 |
| 17 | Separate selection/adherence/execution/state/final-response scores | Category contracts exist; #13 corrects optional counting and stale statuses; live calibrated scores absent | #13 + #14 |
| 18 | Judge appropriateness/evidence/recovery/repetition/stopping | Rubric and controlled judge tests exist; no accepted live judge/calibration | #14 |
| 19 | Credit equivalent safe valid paths | Deterministic outcome checks; semantic calibration absent | #14 |
| 20 | Sensible retry versus duplicate success | Fresh bounded-retry/duplicate-success test passes | #14 live rubric |
| 21 | Prior/current/no-skill comparison | Synthetic variant wiring only; accepted comparison not executed | #14 with #13 |
| 22 | Fixed-case/rubric model-provider comparisons | Comparison helper exists; real controlled comparison not executed | #14 |
| 23 | Useful local evidence with async/unavailable judging | Fresh unavailable-judge test passes; unavailable remains distinct from acceptance | #14 |
| 24 | Inline runtime limits/authorization before evaluation | Existing runtime contracts; actual request-bound guard pending native/live proof | #12 + #14 |
| 25 | Minimize/redact export; follow retention policy | Fresh minimization passes; project retention NULL, decision unresolved | #15 |
| 26 | Idempotent score writes | Main still lacks PR18 repair; PR18 stable-ID/date code and bounded durable replay pass | #15 review/landing + final evidence |
| 27 | Local result linked to trace/run | Mock linkage and synthetic live canary IDs exist; canonical round/step/browser joins unavailable | #12 + #15 |
| 28 | Inspect real artifact and saved state | Prior native public-storage receipts; full live artifact/milestone readback unavailable | #6 + #12 |
| 29 | Place-photo/time/uncertainty/unrelated/ambiguous cases | Checked-in fixtures and prior domain contracts; all live gates outstanding | #13 |
| 30 | Paid/unpaid/pending/revoked Family cases | Existing server-owned entitlement contracts; live campaign evidence outstanding | #13 + #6 |
| 31 | Collection review/handoff/source ownership/task result | Existing controlled ownership/task contracts; canonical live trajectory still required | #13 + #12 |
| 32 | Preserve failed-case local evidence | **New defect reproduced:** one unhandled callback error discards completed sibling and failure receipts | #2 bounded generic-runner repair |
| 33 | Ordinary host/CI checks without removed harness | Fresh 48 exact-main focused tests; repair-branch full offline evidence below; native/browser/live skips remain | Each final-head owner |
| 34 | Refresh every skill-caching runtime | Fresh installer/config-recipe tests pass; two-runtime loaded-version refresh readback missing | #13 |
| 35 | Accepted dataset/rubric versions every run | Versioned files exist; calibration remains `requires-human-review`, reviewer/date null | #14 + #12 |

## Testing-decision map

| Decision | Evidence and remaining gate |
|---:|---|
| 1 | Real application seam is represented in controlled integration/native tests; #12 supplies complete live invocation |
| 2 | Fresh normalization/error/retry/reasoning tests pass; these are protocol fixtures |
| 3 | Fresh core deterministic evaluator tests pass; prior domain/native tests cover ownership/state/artifact boundaries |
| 4 | Fresh checked-in synthetic provider/application runtime tests pass; canonical native fixtures are separate evidence |
| 5 | Fresh mock publishing/linkage passes; PR18 repairs stable identity/date and adds controlled SDK plus durable readback evidence |
| 6 | Fixtures distinguish skill scenarios; #13 still owes actual explicit/natural loading and live outputs |
| 7 | Existing runtime/domain tests remain; later repair-branch offline suite is recorded separately below, with native/browser/live skips retained |
| 8 | Installer/config tests pass, prior Compose/native/build receipts exist; do not enable semantic release gates before #14/#15 closure |

## Newly found gap and closure ordering

The generic `scripts/run_langfuse_evaluation.py` persists only after
`MemoirEvaluationRunner.run` returns. That method uses `asyncio.gather` without
per-case error capture. An offline public CLI probe ran a successful controlled
application case followed by a controlled callback exception at concurrency one.
The first case finished, but the CLI exited 1 without creating either the output
JSON or failure directory. This is separate from the canonical #12 launcher and
five-case #13 evaluator. No provider call was used to establish it.

1. Resolve this bounded generic exception-persistence defect with public CLI
   red/green tests; keep failures explicit and retain completed siblings.
2. Finish/review/land each scoped code fix, then pin the actual resulting main.
3. Reconcile #12/#14 native actor, existing route/auth, accounting, resource and
   cleanup gates before the conditional ten-round application canary.
4. Resolve actual loaded versions, judge configuration, named human calibration,
   and retention decisions with their existing owners. Do not invent settings or
   approvals. Bilingual fixtures alone cannot close these gates.
5. Derive and obtain the distinct full-campaign envelope, run five isolated
   50-round cases on exact main, inspect every five-round persisted milestone,
   preserve failures and separately grade invocation/output/semantic outcomes.
6. Complete durable API/database and authenticated-browser linkage, then do the
   fix/cloud-review/landing/affected-rerun loop. Close #2 only when its remaining
   requirements genuinely pass; no current branch or narrow code clearance does so.

## Bounded callback-recovery repair on this branch

The public CLI regression first reproduced **three failures / one pass** on
the exact main base. The proposed repair catches ordinary callback errors and
invalid/missing trajectory results per case, retains correlation/version fields,
and writes an explicit `acceptance.status = error` with no fabricated trajectory
or scores. Other case results are retained. The CLI saves all returned results
and failure receipts before returning exit code 1 for callback errors. Successful
synthetic command behavior is unchanged. Exception text is not exported into
receipts because it may contain private content; the error type and failing stage
are recorded. Cancellation and other `BaseException` signals are not swallowed.

Focused verification: **36 passed, no skips/failures/errors**, including eight
new public CLI cases: success-before-failure, failure-before-success, concurrent
siblings, missing trajectory, invalid callback result, timeout, variant-specific
receipts and unchanged successful output. No provider or judge calls were made.

This repair is limited to failures before a callback returns a valid trajectory.
It does not claim durable recovery from publication failures, process termination,
filesystem failure or a later evaluator exception. Those paths need their own
evidence before treating story 32 as universally satisfied. Independent cloud
review remains required; #2 stays open.

The final full isolated offline run passed **1,076 tests**, with **183 explicit
skips and one warning**, zero failures/errors. Native PostgreSQL/Temporal, browser
and configured-provider gates remain skipped where their required environment is
absent. [Raw output](../test-evidence/issue2/full-offline-green.log),
[exit-code receipt](../test-evidence/issue2/full-offline-receipt.json) and
[tested source hashes](../test-evidence/issue2/tested-source.json) are retained.
The runner receipt records the unchanged base HEAD/tree; the source-hash manifest
identifies the modified source actually tested. [RED](../test-evidence/issue2/callback-red.log)
and [focused GREEN](../test-evidence/issue2/focused-green.log) remain separate.

## Independent-review correction: unavailable variant baselines

Independent review of local commit `2686a12538933b5ac586107bc037f8397dbec591`
found an introduced interaction with the existing comparison helper: callback
error receipts correctly had `scores: []`, but a successful candidate was then
compared against invented baseline zeros. The public CLI could therefore retain
an honest error receipt yet report ten false `+1.0` improvements.

The bounded correction preserves all case/error receipts and actual score values,
but produces a delta only when both non-error results contain that numeric metric.
Rows now say `unavailable`, `partial`, or `compared`, and list unavailable metrics.
A genuinely measured zero is comparable; a missing value is not converted to zero.
An error result is not a comparison baseline even if it retains partial scores.

TDD: [five failures/eight passes before the correction](../test-evidence/issue2/comparison-red.log),
then [41 focused passes](../test-evidence/issue2/comparison-focused-green.log).
Added cases cover failed baseline, failed candidate, partially overlapping metrics,
partial scores attached to an error and measured-zero versus absent-value behavior.
This is comparison correctness, not a live variant-quality comparison or closure
of stories 21/22. No model calls, external publication or canonical/five-case
implementation changes were made.

The final comparison-fix offline suite passed **1,081 tests**, with **183 skips,
one warning, zero failures/errors**. Native/browser/live acceptance remains
unverified at skipped seams. See [raw output](../test-evidence/issue2/comparison-full-offline-green.log),
[exit-code receipt](../test-evidence/issue2/comparison-full-offline-receipt.json)
and [tested-source hashes](../test-evidence/issue2/comparison-tested-source.json).
Independent rereview is pending; #2 and its full acceptance gates remain open.
