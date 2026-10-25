# Memoir composer: lossless preparation and live comparison

**Full acceptance: fail.** This change removes model summarization for short,
complete primary-narrator batches while retaining original evidence and every
draft/review/SQL gate. The bounded candidate saved all six checkpoints with
14 model submissions; the baseline saved five with 24 submissions. Candidate
English prose nevertheless adds an unsupported spatial claim. Faster rows are
observations, not quality-qualified acceptance or a deployed-product speedup.
Independent cloud review is pending; keep the PR in draft.

Baseline source is main `ef42b2b1ab98002ad31d76c7618137a9adbf7e6f` (also verified
against live `origin/main` before implementation and after profiling began).
Baseline observer ran at documentation-only head
`b18b8c7ee46a82b48ceb344cf01436122362be89`; application code equals that main.
Profiled candidate code is `a20689248a6dae91c83c29e087cf9b119cd6985f` on
`codex/memoir-composer-optimization-20261025`. Later report commits do not alter
profiled code. No prompts, schemas, receipts, provider settings or production
services changed; nothing was merged, deployed or published to Langfuse.

## Measurement and limits

This is **live composer HTTP + canonical application API + disposable real
PostgreSQL**, with controlled upstream collector, source-policy and extraction
responses. The observer reuses `Conversation`, `MemoryEventWorker`,
`execute_lifetime_lane`, the actual bounded worker/provider transport and real
SQL page admission/commit/read APIs. API-to-worker transport is in-process.
The provider streams real Responses; it is not a prompt-only probe. It does not
measure browser paint, real upstream model dependencies, production queue wait,
a deployed candidate worker, or chat meaningful-text latency.

The metric below is monotonic **composer trigger to saved-reader API response**.
Successful completion requires a durable ready root, finished coverage and the
actual authorized read. A heading alone is not meaningful narrative. Raw model
first-delta timings are retained but are not user-visible prose. Composer runs
in background Lane B; the skill's 5s/10s chat targets are unmeasured and do not
automatically apply to these background checkpoints. Every measured checkpoint
exceeded 10s; this is not a claim to meet either chat target.

The manifest and rubric were frozen before baseline dispatch. Both arms use the
same six checkpoints: en-AU and zh-CN, rounds 5/10/15; round 10 corrects blue to
green, adds longer context and restarts from a saved SQL draft; round 15 is
held out for uncertain attribution and a shed/garage caption conflict. Each
arm consumes its own prior responses/state. After round 15, withdrawing every
original must settle without a generation and withhold old prose. Empty initial
checkpoints, mixed authors and over-limit batches have additional offline tests.
These live batches contain 104–1,035 characters of joined original context;
they do not cover maximum-window or >4,000-character live preparation.

Each arm was capped at 24 actual application submissions including repairs,
30 minutes, zero paid judges, 98,304 input/16,384 output tokens per call.
The shared budget also caps aggregate input/output tokens. Worker deadlines
remain 600s draft/240s other phases, bounded by the arm deadline. No budget was
reset. Baseline hit 24; one further review was blocked before HTTP. Candidate
finished at 14; no more generations are planned in this round.

The existing `memoir-luna-low` alias served `gpt-5.6-luna`. Requested effort and
completed-response echo are `low`; effective internal reasoning and account
failovers remain opaque. The running gateway config hash was unchanged:
`416c9ef816942cd2b47ab1e0b0c9712f837cf5ad1d18a773c12eaf155894f5e4`.
It specifies zero outer retries, no fallbacks, and zero token cost on the
subscription route. Estimated/configured marginal API charge is **$0**;
no billing audit is claimed. The cost response header was absent, and tokens
and subscription quota were consumed. No new service, subscription or paid
commitment was created.

Arms were sequential, not randomized pairs. Provider-reported first response
creation times were 02:45:21Z baseline and 03:19:13Z candidate on 2026-10-25.
Load/account/cache drift is uncontrolled. Reported cached input was 4,480 tokens
baseline and 2,816 candidate. Each row has n=1; its median/range equals its single
observation. There is no defensible tail percentile or statistical speed claim.

## Before/after: actual live observations

Positive reduction means shorter. Calls are prepare/draft/review. The five
completed pairs are structurally matched; semantic failures remain visible.

| Checkpoint | Baseline seconds | Candidate seconds | Reduction seconds / percent | Calls before → after | Result and quality limit |
| --- | ---: | ---: | ---: | --- | --- |
| en-AU 5 | 24.618 | 21.263 | 3.355 / 13.6% | 1/1/1 → 0/1/1 | both saved; baseline API preview heading-only; candidate narrative |
| en-AU 10, saved-draft restart | 28.570 | 38.650 | -10.081 / -35.3% | 1/1/1 → 0/2/1 | both saved; candidate repair and unsupported “close at hand” |
| en-AU 15, held out | 59.142 | 20.640 | 38.502 / 65.1% | 1/2/1 → 0/1/1 | both saved; candidate retains unsupported spatial claim; omissions below |
| zh-CN 5 | 25.970 | 23.218 | 2.752 / 10.6% | 1/1/1 → 0/1/1 | both saved; baseline certainty concern |
| zh-CN 10, saved-draft restart | 96.513 | 42.668 | 53.845 / 55.8% | 1/4/2 → 0/2/1 | both saved; baseline unsupported memory certainty |
| zh-CN 15, held out | 48.930 **incomplete** | 27.116 | **unavailable** | 1/2/1 → 0/1/1 | baseline cap blocked another review; candidate saved; no successful latency pair |

| Arm totals (different completed denominators) | Baseline | Candidate |
| --- | ---: | ---: |
| Actual provider submissions / complete Responses | 24 / 24 | 14 / 14 |
| Durable ready checkpoints | 5/6 | 6/6 |
| Entire arm elapsed, including setup/controls | 321.472s | 205.297s |
| Prepare / draft / review submissions | 6 / 11 / 7 | 0 / 8 / 6 |
| Provider input / output tokens | 219,530 / 38,342 | 151,764 / 23,317 |
| Saved-draft restart controls | 2/2 | 2/2 |
| Withdrawal controls, zero calls and prose withheld | 1/2; Chinese not reached | 2/2 |

Do not compute an aggregate improvement from the unequal completion outcomes.
Large per-row changes include different repairs and manuscript choices, not
just preparation removal. Application attempts are fully counted; internal
subscription-provider failovers are unobserved.

## Quality comparison and acceptance

[The semantic packet](memoir-composer-latency-20261025.transcripts.json) contains
exact final review-input candidates, original source versions, prior manuscripts,
prepared context, reader responses and review findings. Full raw phase replies,
requests, schemas and SSE remain in hash-pinned raw receipts. These are synthetic
narratives; there are no customer originals or credentials.

- Baseline en-AU-5's reader response is only **“The Blue Tin”**. Its full accepted
  manuscript includes the bicycle and school paragraphs. This originates in the
  existing SQL path: each block, including headings, becomes a section preview,
  and the root reader chooses its first page at limit 1. Candidate first-reader
  prose is a different model layout, not a fix for that SQL behavior.
- Baseline zh-CN-10 says **“绿色这一点，我记得很清楚”** (“green—I remember clearly”).
  Testimony corrects the colour but does not supply that certainty. The model
  review flags a warning yet allows readiness. Baseline zh-CN-5's “清楚可见” also
  merits review for strengthened visual certainty. These defects predate the diff.
- Candidate en-AU-10 says **“with the green tin of bicycle tools close at hand.”**
  No original establishes that location. English-15 retains the same claim;
  its model review explicitly warns about it but still allows readiness.
  This is a **candidate semantic failure**. A baseline defect does not excuse it.
- Both candidate held-out chapters preserve uncertainty about Father's recalled
  words (“cannot promise those were his exact words” / “不能保证这是他的原话”).
  Both omit his pre-birth neighbour-repair account and the later garage caption.
  Their positive handling of that attribution/conflict is therefore unexercised.
  Do not call source/schema checks full semantic acceptance.
- Candidate en-AU-10 explicitly defers the supported school event from a focused
  chapter; baseline includes it. In both arms the correction invalidates the
  prior combined chapter, and the authoritative prior chapter list is empty at
  that checkpoint. This divergence is not proof of unchanged-text preservation;
  the dedicated SQL/transport tests cover actual carry-forward behavior.
- The candidate removes the blue description after correction, uses current
  source versions and target languages, and never grants publication approval.
  Both candidate restarts resume saved drafts. Both candidate withdrawals settle
  with no model submission and no old prose. No human or paid-judge acceptance
  is claimed; independent cloud review is pending.

| Agreed gate | Outcome |
| --- | --- |
| Isolated current-main task, privacy/secrets and unrelated work preserved | pass within this synthetic scope |
| Exact lossless context, references/order, Unicode boundaries, fallback eligibility | pass offline and captured request comparison, 6/6 exact original-text joins |
| Current source/policy/page proof and ownership enforcement | pass targeted real SQL negative tests |
| Durable save, saved-draft restart, empty/withdrawal behavior | candidate pass; baseline final Chinese/withdrawal incomplete |
| Observed completed-pair latency | four shorter, one longer; n=1 per arm |
| Source-grounded quality / no quality regression | **fail: candidate unsupported spatial claim** |
| Held-out pre-birth and caption handling | inconclusive: omitted in candidate prose |
| Browser meaningful text within 5s; >10s attribution | unavailable; browser/chat path not measured |
| Independent cloud review / deployed worker acceptance | pending / not run |
| Full optimization acceptance | **fail; draft review only** |

Next work on this same skill is independent review of the grounding findings and
repair semantics before acceptance, including the existing warning-only review
behavior and heading-only preview. Any behavioral fix after profiling requires
renewed affected live comparison under an explicitly renewed budget; none is
silently appended to this exhausted baseline.

## Selected change and alternatives

Measured preparation costs 4.172–6.129s (n=6, median 5.491s, sum 32.602s), versus
~57ms median Node plan/validation operations. Drafting dominates: n=11,
median 16.468s, sum 189.779s, including repairs. Separate reviews cost n=7,
median 4.296s, sum 31.505s. Node spans can nest inside phase spans; they must not
be added again to infer critical-path totals.

| Candidate | Measured basis / expected gain | Decision and retained contract |
| --- | --- | --- |
| Lossless preparation of eligible short originals | Remove one serial 4.2–6.1s stage per cold batch, estimated before candidate | selected; exact originals and refs, no inference/compression; all draft/review/save gates retained |
| Cache/reuse Node plans or prompt compilation | tens of milliseconds per operation | lower expected value; not implemented |
| Shorten prompts/evidence, change route/effort | quality/publishing risk; no matched evidence | not selected |
| Defer review or preparation to a later consumer | current draft/proof depends on them | not selected; no new Lane B deferral |

`progressive_composer.verbatim_summary` validates the batch, then joins complete
primary-narrator `narrator_chat`/`narrator_transcript` messages with exactly two
newlines. It copies original spans/versions/order without normalization,
translation, truncation or personal inference. It is eligible only for nonempty
context of at most 4,000 Unicode code points, with no active excluded/paused
topics. Over-limit, mixed-author, partial-window, restricted and whitespace-only
contexts keep the existing model preparation path.

`canonical_composer.compose_shared_snapshot` still reads existing preparation
checkpoints. On a lossless cache miss, it builds the same bounded preparation
packet, checks generation pause and feature admission, validates exact refs,
registers the host artifact through the existing current SQL page/token/digest
proof, and saves the same durable checkpoint. It does not manufacture a model
invocation. All later draft admission, separate semantic review, retries,
normalization, protected content and final SQL commit remain unchanged. There
is no schema/grant change. Rolling back the two application files restores
model preparation; existing checkpoint structure remains compatible.

## Actual execution and every reachable prompt

The composer is registered as a periodic durable lane in
`apps/api/background_skills.py:36`. Current defaults distinguish five completed
project rounds, the twenty-round free allowance, and separately authorized
formal composition. The skill guide supports more output modes than the active
private-checkpoint entry point; it is not itself a second production prompt.

| Step / source | Trigger and input | Work / external call | Output / consumer | Lane and blocking dependency |
| --- | --- | --- | --- | --- |
| 1. `policy_review.py:88`, `lifetime_memory_runtime.py` | Accepted original narration, owner and source version | Separate source policy model, up to two attempts; current privacy/correction authority | Accepted policy and original-source state | Upstream Lane A and required authority for B; not a composer call |
| 2. SQL baseline `queue_memoir_receipt:8415` | Completed-round receipt, current locale, changes | Persist milestone/outbox; coalesce timeline/composer work | Durable lane IDs and truthful targets | B scheduling, independent of delivering composer prose |
| 3. `memory_event_worker.py:200`; SQL `claim_memoir_lane:4046` | Due lane with immutable claim token | Claim/read snapshot, privacy/source eligibility, extraction readiness, bounded heartbeat/deadline | Governed lane page | B; waits for canonical extraction and current policy |
| 4. `lifetime_memory_composer.py:217` | Canonical page | Defer incomplete privacy; handle complete/reuse/empty branches; execute at most eight pages per lease by default | Current page or metadata deferral | B; no stale content authority on policy deferral |
| 5. `progressive_composer.py:9`, `canonical_composer.py:165,337` | Up to five new messages, <=16 source windows, <=8 events, prior saved prose | Read-only canonical projection; stable source/event IDs and exact spans; fingerprint configuration; preserve supported sections | Immutable composition request and change set | B; source windows stay <=2,304 characters |
| 6. `canonical_composer.py:384` | Exact request/config/epoch | Read saved compose/preparation checkpoints; revalidate saved repair candidate | Resumable phase state | B; successful work can survive failure/cancellation |
| 7. `canonical_composer.py:390` | Unsaved preparation | Batch: one summary for new messages; non-batch: dirty event preparation with concurrency 1–4 (default 3); exact-ref validation and checkpoint write | Derived prepared context; original evidence remains authoritative | B, serial prerequisite to current draft; non-batch preparations can overlap |
| 8. `memoir_preview.py:489` | Full immutable request plus saved state | Node plan; bounded incremental model packet; empty context settles without a draft | Ready host plan or insufficient context | B; plan is deterministic, not a model outline call |
| 9. `memoir_preview.py:196`; `lifetime_memory_lane_engine.py:567,696,746` | Phase packet, schema, immutable fence | Strict request-budget validation, publication/admission guard, worker HTTP, direct structured streaming model call (`tools=[]`, no tools) | Complete JSON plus registered artifact digest | B; provider raw deltas are not reader prose |
| 10. `memoir_preview.py:508`, `canonical_composer.py:100` | Draft output and original request | Restore unchanged bytes, pin server-owned fields, normalize, Node validation plus canonical span/projection checks | Exact validated candidate | B; failed deterministic validation skips semantic review |
| 11. `memoir_preview.py:533` | Exact candidate, original evidence and validation | Separate review model; require ready=true, publication=false, no blocking findings | Reviewed private candidate | B; remains mandatory before readiness |
| 12. `memoir_preview.py:502–563` | Validation/review failure | At most three draft iterations; compact-to-full evidence fallback; drop oversized failed candidate only while retaining the unchanged originals | Repair or explicit retry-needed failure | B; failed attempts must remain in accounting |
| 13. `memoir_preview.py:564`, `canonical_composer.py:450`; SQL `save_memoir_checkpoint:11684`, `commit_lifetime_memoir_lane_page:4245` | Reviewed candidate and exact page/epoch/base | Node render; save phase state; fenced page commit and source/event dependencies | Reviewable private manuscript, summary and truthful coverage | B; rendered files alone do not prove durable DB save |
| 14. `lifetime_memory_composer.py:289`; SQL `complete_lifetime_memoir_lane:5461` | Committed page | Read next page, yield or complete/coalesce catch-up | Eventual source coverage and next-consumer state | B; failure/retry/next turn are acceptance gates |
| 15. `story_routes.py:407`, `lifetime_memory_read_api.py:38`, `private_draft_stream.py:34` | Authorized draft read | Saved-view read; local debug NDJSON checks every two seconds with publication guard | Chapters/private reader view; optional debug preview | Reader-visible after B; browser paint is separate and unobserved |
| 16. `lifetime_memory_collection_jobs.py:58,145`; `lifetime_memory_job_engine.py:136` | Explicit selected-collection BuildOutline job | Separate bounded leaf/merge model calls; original-window/child ancestry and owned persistence | Selected collection outline | Separate async job using composer-owned outline prompts; not step 8's deterministic plan |


Step 7 now conditionally uses the lossless host artifact described above; all other
steps retain the same authority and dependencies. There is no new Lane B deferral.

There are **13 composer-owned managed artifacts**, not 13 calls per checkpoint.
All have matching checked-in numeric version/SHA receipts at the baseline. This
is local receipt validation; no remote Langfuse check or publication occurred.
Full names, source hashes, composed hashes, conditional schemas and component
pins are retained in the evidence JSON and local raw inventory.

| Component / source under `skills/memoir-composer/` | Purpose / call site | Conditions / input dependencies | Local pin |
| --- | --- | --- | --- |
| `prompts/prepare.md` | `composer_instructions('prepare')` | One canonical event or batch summary; exact originals, IDs, refs | v1 |
| `prompts/batch/prepare.md` | Appended by `lane_contract` | Batch preparation; new-message summary <=4,000 characters | v1 |
| `prompts/draft.md` | `composer_instructions('draft')` | Host plan, target locale, originals, prior/protected prose, optional repairs | v2 |
| `prompts/review.md` | `composer_instructions('review')` | Exact validated candidate and original evidence, optional full fallback | v3 |
| `prompts/batch/compose.md` | `lane_contract` appends to BOTH batch draft and review | Progressive deltas, stable IDs, canonical citations, summaries are derived | v1 |
| `references/narrative-enrichment.md` | Named component in draft AND review | Scene/voice quality while prohibiting invented personal facts | v1 |
| `references/editorial-review.prompt.md` | Named component in review | Assertion-by-assertion grounding, roles/uncertainty/media/readability | v1 |
| `prompts/outline/leaf/en-AU.md`, `zh-CN.md` | `job_contract` | Explicit BuildOutline leaf, one original source window | v2 each |
| `prompts/outline/merge/en-AU.md`, `zh-CN.md` | `job_contract` | Explicit BuildOutline merge, bounded derived child summaries/ancestry | v2 each |
| `prompts/outline/shared/prefix.md`, `suffix.md` | Named components in four outline templates | Original-vs-derived rules, language and data-only boundary | v1 each |

Every composer phase additionally renders
`memoir/shared/bounded-context/{en-AU,zh-CN}` with its `lane_context` policy
component. These distinguish target edition language from conversation language,
retain complete current exclusions/pauses, treat data as untrusted, and forbid
invented permissions. `memoir/shared/place-conflicts` is conditional on fenced
attribution coverage. Schemas originate in `memoir_preview.composer_output_schema`
and `schemas/draft.schema.json`; the draft ref schema is restricted to exact
fenced source/version/offset choices. Inline repair feedback is the prior
candidate + validation + review in the packet; no separate repair model prompt
is reachable. Current worker system instructions are the composed phase block;
tools are disabled. There is no hidden tool-planning call in this path.

Upstream prerequisite prompts are inventoried separately: policy-review and
policy-review-opening (including `previous_review` on retry); timeline extract
or extract-with-hints plus grounding/contract/window; optional place-journey,
derived-hints, attribution, continuity and strategy-proposal; memory-context
summary/profile when due; common bounded-context policy/language. Timeline
extraction/summary each allows up to three validation attempts. These are not
extra composer calls or targets of this round. The composer skill guide,
workflows, sources/rights and length documents are human/runtime contracts,
not additional dispatched instructions. The obsolete composer index prompt and
retired fallback executor are absent from current production callers.

The quality evaluator's `skill-judges/policy.md` and `memoir-composer.md` are
**evaluator prompts**, not application instructions. They were inventoried but
never submitted. No judge score or human review is claimed.

## Tests, TDD and failures

The agreed seams were canonical composition/`execute_lifetime_lane`, external
worker HTTP, and real SQL checkpoint/proof/reader boundaries. TDD first made a
real SQL short-batch test fail on a controlled preparation-provider 503. The
lossless path made it save through draft/review despite that unavailable
summary provider. Subsequent red/green slices caught active excluded/paused
preference handling and generation pause before proof registration.

Tests cover exact Unicode/combining text/whitespace/order; 4,000/4,001 code-point
boundaries; no truncation; mixed author and partial-window fallback; incomplete
privacy; empty context; withdrawn source/changed policy/stale digest/missing
prepare proof/wrong owner before draft; corrections, protected/unchanged text,
retry budget and durable restart. The old eleven model-phase transport fault
cases use >4,000 characters to keep exercising the complete fallback path.

| Command scope, all supervised | Result |
| --- | --- |
| Seven composer/transport/provenance/repair/policy/clearance/lane modules at candidate | **209 passed**, final combined run (80.91s) |
| `test_skill_eval_workflows.py -k composer` | 15 passed, 26 deselected |
| `node --test skills/memoir-composer/tests/*.test.mjs` | 62 passed |
| Bilingual SQL/live-observer fixture preflight | 6/6 checkpoints, 18 fixture calls, restart/withdrawal pass; **not live** |
| Earlier offline source-copy cohort | 16/16 structural cases, 64 controlled calls; **not semantic/live acceptance** |

Earlier combined regression runs exposed only stale assertions expecting a
preparation call for newly eligible batches; the assertions were updated while
retaining their substantive SQL/source/checkpoint checks. The intermediate
208-passed/1-failed result and the subsequent 7-passed clearance rerun remain
in evidence, along with every TDD red result. Initial offline observer error
used `events.title` instead of canonical `events.summary`; its 28 fixture calls
remain archived separately rather than counted as successful evidence.

The existing main prompt-length failure was reproduced before behavior changes:
`test_prompt_composition.py::test_acknowledgement_guidance_is_conditional_and_reuses_policy_rules`
expects `<1100` characters, but the normal policy prompt is **1,199**. The test
and prompt blobs match baseline main byte-for-byte. Prompt SHA256 is
`1dc91059adb7397c0a0dd3e157c63d670e4c8a320aa866da8061f9fc32a3bd55`;
test SHA256 is
`716ff62edccd65dae9c31522a358b5c4cb87fdf851de2daf6d598f1be4359f3e`.
The earlier broad run was 204 passed, 1 failed, 20 deselected. Privacy instructions
were not shortened, and no claim is made that the entire repository suite is green.
No place/photo/news/workspace-localization behavior changed, so its special
`make test-place-research` check is not applicable.

Native PostgreSQL setup initially failed because macOS shared-memory identifiers
were exhausted (`shmget`, not disk capacity); it made no model calls. No kernel
settings or other PostgreSQL processes were changed. The existing Apple
Container postgres:18.3 image and fixture supplied one task UUID database at a
time, with 1 CPU/1 GiB and a random loopback-only port. The unchanged baseline
schema was loaded into those disposable containers only. All successful test
and both live-arm supervisor cleanup receipts verify task roots removed; both
arms' per-locale containers are gone. No production migration/data was touched.
Initial sandbox process-supervision failures were terminated; preserved receipts
and identity-checked cleanup record them. The native `container` CLI was used
when `mocker inspect/exec` disagreed with the actual running gateway inventory.

## Worktree recommendation

Keep both older trees. Their HEADs are ancestors of main, but they contain unique
uncommitted content, so age or ancestry does not make removal safe:

| Existing worktree | HEAD / ancestry at audit | Dirty state / unreconciled examples |
| --- | --- | --- |
| `~/.codex/worktrees/canonical-fifty/memoir` | `deed9b6993ba8c52b680e91e430d121f2fce7eca`, 430 commits behind | 50 tracked changes + 12 untracked; four exact working blobs absent from every reachable ref: fifty-subscription report, Supabase evaluation runner/test, extraction-span repair test |
| `~/.codex/worktrees/progressive-fifty-rerun/memoir` | `96616430f18e5ffbbbca7be239a8beaad5c261ce`, 426 behind | 33 tracked changes + 13 untracked; four unique blobs in lifetime continuity/publication/transport and API main |

Ordinary process/open-file checks found no matching active process, but cannot
establish owner completion. Neither tree was changed, deleted or archived.
The isolated task branch avoids their edits. No owner contact, Codex UI or
hidden-session workaround was used. The previously failed Codex task-status
message was not retried; parent reads the written task results. There is no
remaining ownership or spending permission blocker for the completed scope.

## Evidence and reproduction

- [Evidence summary](memoir-composer-latency-20261025.evidence.json): every actual
  invocation, compiled prompt/schema hash, usage, stage statistics, tests,
  comparison and gate findings.
- [Semantic review packet](memoir-composer-latency-20261025.transcripts.json):
  original source versions, prior manuscript, exact normalized review candidate,
  prepared context, model findings and saved-reader API result for every case.
- Ignored raw directory `var/composer-response-optimization/20261025-live/`:
  `manifest.json`, frozen `profile.py`, `baseline/receipt.json`,
  `candidate/receipt.json`, all supervised logs/receipts, TDD red/green receipts.
  Full Responses/SSE, request bodies, schemas, outputs and monotonic events are
  retained. The evidence JSON pins both receipt hashes and observer/input hashes.
- Earlier source/prompt inventory and preflight audit are preserved in
  `var/composer-response-optimization/20261025-offline/` and
  `20261025-live-preflight/`. The initial provisional report is archived in the
  live directory; it is superseded by this report.

The exact matched command used the existing isolated supervisor:

```sh
MEMOIR_TEST_POSTGRES_BACKEND=apple-container MEMOIR_TEST_PUBLICATION_TCP=1 \
python3 scripts/run_isolated_check.py \
  --output-dir var/composer-response-optimization/20261025-live/checks \
  --name live-candidate --timeout 1830 -- \
  python3 var/composer-response-optimization/20261025-live/profile.py \
  --execute --arm candidate
```

This is a provenance record, **not authorization to rerun**: the baseline cap is
exhausted and directories deliberately reject reuse. Repeating or extending
live work needs an explicitly renewed budget and affected comparisons. No live
judge, browser, hosted production or deployed-worker acceptance was performed.
