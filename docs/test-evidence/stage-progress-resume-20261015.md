# PR68: restart readiness recovery after saved-project Begin

Verified source commit: `4d2602ef9377dffd977bd0a62da686557dd71e24`.
Base: `46caa5fc2c2c5af2d4f7280bea74cc75184c9cbc`.
The following evidence-only commit is the exact review head recorded in PR68.
Keep draft; acceptance is incomplete.

## Root cause and repair

Landing-page project hydration starts readiness recovery. Begin resumes that same
saved interview through `navigateTo`, which invalidates the old navigation scope
and aborts its recovery job. The saved-project resume branch then starts its
greeting without replacing the cancelled job. Extraction completing afterwards
therefore remains invisible until another save or reload.

Resume now calls `refreshStageReadiness()` immediately after navigation, before
awaiting the greeting. The existing recovery implementation captures the new
project/principal/navigation scope, cancels obsolete work, coalesces duplicate
requests and rejects stale snapshots. The greeting does not delay recovery. The
only production change in this continuation is three added lines in that branch.

## TDD and navigation coverage

Before the patch, the readiness suite had **18 passed / 4 failed**. Five new cases
exercise the actual `startStory` → `startMemoirStory` → `navigateTo` functions with
the real recovery loop and a controlled clock. Four expose the missing restart;
one already verifies cancellation during history hydration. All **22 now pass**:

- A queued landing poll is replaced in the new scope before a blocked greeting
  finishes, and later persisted progress is observed.
- An in-flight landing read is aborted; its late result and cleanup cannot paint
  or detach the resumed job.
- Duplicate Begin clicks coalesce while history hydrates; a concurrent explicit
  refresh shares the resumed job and serializes its follow-up read.
- Navigation away while resume awaits history prevents any stale restart.
- Navigation after resume aborts the new read, clears its timers and suppresses
  late painting. Existing tests also retain project/principal isolation.

The new production browser regression failed in **both languages** before the fix:
100 words / 10% remained after 60 simulated seconds, while reload immediately
restored 300 words / 30%. It follows the real landing-page Begin button and saved
interview URL, not a direct invocation of the recovery function. Original text,
successful replies and later extraction use actual RPCs on disposable PostgreSQL;
the fenced HTTP readiness route supplies the totals. No new narrator turn or
replacement project is allowed during resume.

The final browser test waits for the initial boot read, then lets real Auth/HTTP
work settle between simulated timer events. An earlier candidate's single
60-second clock jump could expire the ten-second request timeout before its
asynchronous fetch began; another case asserted before boot had issued its read.
After synchronization, both functional assertions passed, but element screenshots
failed because hydration replaced the navigator. The final capture uses viewport
pixels and current bounds. These intermediate failures are retained in the receipt.

## Verification

The tested file bytes were finalized as the source commit above. Amending the
unpublished candidate captured browser-test synchronization only; production and
JavaScript-test blobs match the candidate on which the build/aggregate ran.

| Check | Result |
| --- | --- |
| Readiness unit file, including five new navigation cases | **22 passed** |
| JavaScript/composer/historical-news aggregate | **521 passed**, no failures/skips |
| Stage/counter, real attribution RPCs, provenance/cost, read API and commit files | **70 passed**, no failures/skips |
| Acknowledgement/transport/schema/timings and real save/publication selection | **115 passed**, no failures/skips |
| Rebuilt production standalone Next + real RPC/HTTP + Chromium | **6 passed**, no failures/skips: two new resume cases and four existing ring/recovery cases |
| Deterministic acceptance catalogue | **55/55 passed**; MemoryStore scope |
| Production webpack build and mobile TypeScript | **Passed** |
| Localization/ICU and route audit | **647 messages**, all **63 required routes** present among 125 routes |
| Focused readiness-test lint, JS/Python syntax and whitespace | **Passed** |
| Whole-client/stream-latency lint selection | **Five existing unused-binding errors**, unchanged findings |

The resume cases assert 30% amber **before reload**, then verify the same 300-word
result after reload. The inspected screenshots were captured after that reload:
[English](stage-progress-resume-en-AU.png), [Chinese](stage-progress-resume-zh-CN.png).
The other four production cases retain pixel coverage, thresholds, fractional
arcs, empty stages, isolation and delayed 409/503 recovery. Synthetic auth and
unrelated workspace services are substituted; stage totals are not mocked. No
live provider/extractor or real concurrent revision race is claimed.

## Scope and remaining gates

PR69 was checked at `dccff32bd6e921c2c43a7e8d734535b134ac3097`. Its client changes
affect different locations. This update neither absorbs nor overwrites them; the
original browser and stream-latency fixtures are untouched. Attribution SQL and
all existing attribution tests match prior PR68 head `4d475fab` byte for byte.

The supplied independent review reported that the prior attribution repair
passed short-cue narration, correction, enrichment, seven turns and three bounded
extraction pages, plus 70 stage/API/commit, four extra attribution/page, 115
transport, 516 JavaScript, four production browser and 55 catalogue checks. Those
reviewer files are not shared with this executor; these are reviewer-reported
results for **the prior head**, not independent verification of this new commit.

The previous author-run broader selection was **151 passed / 68 failed / 3 skipped**,
versus current-main **122 passed / 68 failed / 3 skipped**, with all 193 common
statuses matching. The reviewer independently reported the same comparison and
four older browser cases failing on both heads. These results are historical for
this client-only continuation; the broader failing selection and older browser
cases were not rerun here. Matching failures remain open gates. Full Python and
complete mobile/platform suites are unrun; five lint findings remain.

Historical attribution limitations are preserved. Identical old records can
represent different primary/background roles, as both author and reviewer
substantiated. Only provable attribution is recovered; unknown legacy roles remain
excluded and older accounts can undercount. The resume fix does not guess roles,
relax background isolation or change the stage-specific word/percentage policy.

Independent final-head runtime review, required-check configuration (earlier
403), live extraction and the supplied Library image remain incomplete. The
original PNG could not be downloaded in the earlier supported materialization
attempt and remains uninspected; no new image claim is made here. The existing
five-minute recovery budget still cannot guarantee longer queued, retried or
multi-page extraction finishes. Later explicit save/reload can still be required.

Only synthetic data and controlled service/model boundaries were used. No real
memoir access, provider calls, production migration, deployment, merge, credential
export or Mac execution occurred. PR67 and PR69 remain separately owned.

[Commands, case outcomes, receipt hashes and source/blob proofs](stage-progress-resume-checks-20261015.json).
