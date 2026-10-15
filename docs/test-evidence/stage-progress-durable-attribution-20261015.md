# PR68: durable stage attribution through real persistence RPCs

> This is the attribution receipt for the prior PR68 head. The reviewer later
> confirmed that repair and found a separate saved-project resume cancellation.
> See [the resume continuation](stage-progress-resume-20261015.md) for that fix,
> latest verification and the remaining acceptance gates.

Tested code: `98b112bfdf0a8e3c769f9911239c949b2483a136`.
Main/base: `46caa5fc2c2c5af2d4f7280bea74cc75184c9cbc`.
The following commit contains evidence only; PR68 records its exact review head.
Keep the PR draft. Acceptance is incomplete.

## Root cause and complete data path

The original regression remains established: `commit_lifetime_turn` deliberately
saves canonical `user_memory` rows as `unplaced`, while the former readiness read
summed legacy row stages. Canonical saves also stopped supplying the workspace
field which the client had relied on to update its rings. CSS correctly renders
nonzero percentages and is unchanged.

The earlier PR68 policy filter introduced a second defect: it treated the latest
`event.data.stage_evidence` as the complete, durable narration. Real persistence
does not preserve that property. `set_lifetime_event_correction` replaces it with
the correction cue; `apply_user_memory_events` replaces it on enrichment. Primary
`proposal.source_refs` can contain the long narrated account while placement has
only a short cue. The source-link table previously stored the union of primary,
stage, temporal and relation evidence, losing the distinction between those roles.

The corrected path is:

1. Accept original narrator text with its owner, project, turn and source version.
2. Commit the successful canonical interview reply, retaining the deliberate
   `unplaced` memory row and its durable reply receipt.
3. Validate and persist extraction through the real RPC. Store the primary or
   explicit-stage role on each versioned event-source link; temporal/relation-only
   dependencies remain background. Later proposals accumulate direct ownership
   without downgrading it. Corrections retain that ownership under the event's
   corrected stage and preserve existing author-override authority.
4. Read only active/current sources with successful saved replies, active placed
   events, the correct owner/project and no author exclusion. Union overlapping
   direct spans once per source/stage. Retain guarded legacy staged totals without
   double-counting canonical replies.
5. Serve the fenced HTTP readiness read into the existing client recovery job on
   save and project reload. Paint the returned percentages with the existing
   conic-gradient CSS. No global memoir-completion metric was introduced.

The curve and Unicode counter are unchanged: **100 words → 10% red; 300 → 30%
amber; 1,000 → 50% green**, with the existing fractional interpolation and 50% cap.
Both primary narration and explicit stage cues count; reused birth, temporal and
relation background alone does not. Genuine direct attribution to two stages is
supported, with overlap union inside each stage.

## TDD and actual lifecycle coverage

The initial three tests failed before this repair through actual persistence RPCs:

| Real operation | Broken result | Required and verified result |
| --- | --- | --- |
| Reassign a saved 300-word event through `set_lifetime_event_correction` | Both stages zero | Childhood zero; midlife 300 / 30% amber |
| Enrich an event with another saved 100-word account | 400 drops to 100 | 400 retained, then 557 after another turn with a short cue |
| Save 1,000 primary words with a four-character placement cue | Four words / 0.4% red | 1,000 / 50% green |

An additional upgrade regression failed with four instead of 300 words before
the immutable first-appearance recovery was added. The ten lifecycle tests now
pass. They use actual correction/enrichment RPCs, fresh PostgreSQL sessions,
author overrides, dependency-to-primary promotion, exclusions, owner and internal
function permissions, source editing/version replacement and withdrawal. Upgrade
tests preserve revision records and verify migration replay. The old projection
fixtures remain explicitly synthetic; they are not used to establish the new
lifecycle claims.

## Legacy recovery and its remaining limit

This unreleased migration preserves provable historical stage roles, including
stage cues replaced by later corrections or enrichment. It also recovers primary
ownership when a quote's **first** model revision includes it in the source union
and in no retained background/stage role. The complement of those other roles
proves it was primary at that write boundary. Later disappearance from a role is
not proof: old links accumulate.

Some old roles are irrecoverably ambiguous in the retained schema. A regression
demonstrates that two different proposals—300 primary words versus four primary
words with the longer quote only a temporal dependency—produce identical old
records. A later revision dropping that temporal role still does not establish
primary ownership. Such quotes remain `legacy`, excluded from progress until a
new validated proposal establishes their direct role. This can undercount old
accounts with overlapping primary/background roles. Resolving those accounts
requires original role-bearing proposals, author confirmation or separately
authorized extraction; this task did not invent attribution or access user data.

## Verification on the tested code

| Check | Result |
| --- | --- |
| Stage counter, SQL regression, real RPC lifecycle, provenance and bounded query plans | **32 passed** |
| Read API and commit files | **38 passed** |
| Acknowledgement, transport/schema/timings and real save/publication selection | **115 passed** |
| JavaScript, composer and historical-news aggregate | **516 passed**, no failures/skips |
| Production standalone Next + real extraction RPCs + fenced HTTP + disposable PostgreSQL + Chromium | **4 passed**, no skips |
| Deterministic acceptance catalogue | **55/55 passed**; uses MemoryStore, not PostgreSQL |
| Production build and mobile TypeScript | **Passed**; checked frontend/TypeScript source trees are unchanged by the subsequent SQL/test commits |
| Localization/ICU and route audit | **647 messages**, **63 required routes** represented among 125 application routes |
| Recovery-test lint, JavaScript/Python syntax and whitespace | **Passed** |

The four production browser cases now replace the synthetic link seeding with
real `apply_user_memory_events` calls. Each uses a two-character placement cue and
full primary narration. They verify empty stages, thresholds, 15.7% fractional
coverage, isolation, save, reload, and 256 simulated seconds of pending recovery
with injected 409/503 HTTP fence errors. Stage totals are not mocked. Pixel checks
measure painted arc coverage; the final English and Chinese synthetic screenshots
were opened and inspected. Browser checks do not exercise a live extractor or a
real concurrent revision race. See the [English](stage-progress-direct-rpc-en-AU.png)
and [Chinese](stage-progress-direct-rpc-zh-CN.png) evidence.

The broader pinned backend/container selection remains **151 passed / 68 failed /
3 skipped**. The identical existing-file selection on current main is **122 passed /
68 failed / 3 skipped**. All 193 common case statuses match; all 29 added cases
pass. There are no PR-only failing/error IDs in this selection. Matching IDs do
not prove identical causes or waive failures. The ledger retains every case and
the baseline's failure summaries: 65 shared-memory workflow failures, one
unresolved identity/ownership expectation and two portable `.env` sourcing
failures. Three compose checks skip because Mocker is unavailable.

Whole-PR lint still reports four existing unused client functions and one unused
stream-latency test binding. Those files overlap PR69's baseline repairs; this
update does not absorb or overwrite its owner's changes. The client recovery,
original browser and stream-latency files match prior PR68 head `56ca6d1` byte for
byte. The six earlier task commits were cleanly rebased onto current main; all
14 files from main's latest change match main's blobs.

The final query benchmark uses 1,000/5,000 synthetic source projections and
3,000/15,000 overlapping direct links. RPC samples are **315.379–550.703 ms** and
**1280.242–1478.509 ms** respectively under other executor checks. Setup/query
limits are 30/20 seconds. This measures the projection only, not extraction,
production concurrency, larger histories, migration/backfill latency or a
guaranteed client timeout margin. Plans and receipt hashes are in the ledger.

## Open gates and scope

Full Python aggregate, remaining older browser scenarios, complete mobile/platform
checks, live extraction and independent final-head/fresh-runtime review are
unrun for this update. Broader failures, skips and lint remain open. The earlier
required-check/branch-protection read returned 403 and remains unverified. The
existing five-minute recovery window cannot guarantee completion of longer
queued/retried/multi-page extraction; later explicit save/reload may be required.

The supplied Library PNG `libfile_095545c1c9c88191812c9cc90ef3bf19` was prepared
again with supported Library materialization, but its supported download failed.
No local image was created; its actual pixels remain uninspected. No description
of that image is relied upon. The reproduction and inspected images here are
source-backed and synthetic.

Only disposable synthetic data and controlled model/service boundaries were used.
No provider calls, real memoir access, production migration, deployment, merge,
credential export or Mac execution occurred. PR67 and PR69 remain separately
owned. Exact commands, case ledger, source/blob proofs and query plans are in
[the check receipt](stage-progress-durable-attribution-checks-20261015.json).
