# Memoir composer optimization: baseline and prerequisites

**Outcome: inconclusive.** Source inspection and offline contracts are complete;
no application behavior or model prompt was changed. This is a baseline handoff,
not an accepted optimization or a live latency improvement.

Baseline main is `ef42b2b1ab98002ad31d76c7618137a9adbf7e6f` (tree
`0b36598cebec11b6e3622827adaa90d78c9a523d`). The live GitHub main ref matched it
before work began. Main remained clean. The isolated worktree is
`/Users/bohuihan/Documents/Codex/2026-10-25/task/memoir-composer-worktree`, branch
`codex/memoir-composer-optimization-20261025`. This branch contains only the
baseline report and static evidence summary. Nothing was pushed or published.

## Authorization and isolation

The exact requested [optimization skill](/Users/bohuihan/.codex/skills/memoir-response-optimization/SKILL.md)
was read first, followed by its repository map, repository `AGENTS.md`, README's
versioned prompt workflow, the composer skill/contracts, and relevant local
TDD guidance. The delegation restricts live calls, external tests, migrations,
deployment, credentials/security changes, production operations, push and PR
creation. It overrides the skill's normal publication/delivery steps.

Ordinary Git inspection found two detached worktrees with extensive uncommitted
composer changes:

| Worktree under `~/.codex/worktrees/` | HEAD | Overlap |
| --- | --- | --- |
| `canonical-fifty/memoir` | `deed9b6993ba8c52b680e91e430d121f2fce7eca` | canonical composer, preview, lane/runtime/worker and related tests |
| `progressive-fifty-rerun/memoir` | `96616430f18e5ffbbbca7be239a8beaad5c261ce` | canonical/progressive composer, persistence, publication and related tests |

Their age does not prove inactivity. Owners cannot be determined from the allowed
Git state. They were left untouched. No UI, hidden sessions, task databases or
owner-discovery workaround was used. The task worktree safely separates the
evidence work; competing implementation scope remains for the parent to resolve.

The skill's section 3 explicitly says: **"Without a live baseline, mark findings
provisional and resolve that prerequisite before implementation unless the user
explicitly approves an offline-only exception."** Live spend/runtime authorization
and an explicit offline-only exception are both absent. Implementation therefore
has not started. The [local TDD skill](/Users/bohuihan/.agents/skills/tdd/SKILL.md)
also says **"Before writing any test, write down the seams under test and confirm
them with the user."** Only existing tests were run. Proposed seams for subsequent
red/green slices are `compose_shared_snapshot` / `execute_lifetime_lane`, external
worker HTTP, and checkpoint read/save/commit behavior. Parent confirmation is
still needed before new tests at those seams.

One authorized status report to source thread
`01a157b8-9f91-7516-a390-c0051d6f60fe` failed with **"Codex app tool request
failed"**. Delivery is unconfirmed; it was not retried or worked around. This is
not a denied owner handoff. This report carries the substantive gaps forward.

## Actual execution and delivery boundaries

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

No new Lane B deferral is proposed. Moving summary/review later would change
current draft inputs or its acceptance proof, durable checkpoints and subsequent
consumers. No evidence justifies that change.

Model routing is source/config evidence only: local selected nonsecret settings
specify `memoir-luna-low` and composer effort `low`; the general model is
`gpt-5.6-luna-pooled`. Worker code permits an explicit service effort override.
No serving-worker identity, effective provider model/effort, usage, cache hit,
provider attempts or cost was observed. Offline workflow tests explicitly use
`synthetic-byte-bpe` budgeting and a source-copy fixture, not these provider models.
Current worker deadlines are 240s for preparation/review and 600s for drafting;
API allowances are 255s and 615s respectively. Lane execution defaults to 900s.

## Complete prompt ownership for the traced paths

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

## Frozen scenarios and quality gates

The exact 16 synthetic cases (eight families × en-AU/zh-CN) were frozen before
fixture dispatch: first checkpoint, new evidence, preserve unchanged, corrected
event, empty checkpoint, withdrawal, independent-review boundary, publication
boundary. Updated cases consume their own first saved in-memory bundle; they do
not inject an unrelated baseline response. Existing regressions additionally
exercise cancellation/resume, completed-phase reuse, strict admission/privacy,
exact source spans, bounded repair and language separation.

The frozen rubric requires original-source factual entailment and exact spans;
faithful roles, uncertainty, quoted language and narrator voice; consent/privacy/
ownership/stop and rights enforcement; target language; unchanged/protected text;
strict deterministic validation plus separate semantic review; truthful coverage,
durable checkpoint/retry semantics and next-consumer state; <=7,000 words per
chapter without padding; and no generated publication approval.

For chat, meaningful correct content should arrive within 5s, with every >10s
attempt reported. For composer, meaningful delivery is an authorized,
validated/reviewed private passage, not a generic progress event, greeting or
raw JSON token. These chat thresholds do not automatically apply to background
completion. No meaningful-text/browser/durable-save target was measured here.

## Offline baseline measurements, not live latency

One sample per case. Each value below times the controlled Python orchestration,
in-process worker replies, in-memory checkpoint RPCs and real Node guardrails.
It excludes any real model, durable database, queue wait, browser or deployed
worker. Two-checkpoint sequences include both checkpoints. With n=1, median and
range equal the observed value; no tail percentile is reported.

| Scenario | Fixture calls per locale (prepare/draft/review) | en-AU seconds | zh-CN seconds | Structural contract |
| --- | --- | ---: | ---: | --- |
| First checkpoint | 1/1/1 | 0.675 | 0.476 | pass / pass |
| New evidence (two checkpoints) | 2/2/2 | 0.942 | 0.946 | pass / pass |
| Preserve unchanged (two checkpoints) | 2/2/2 | 1.098 | 1.003 | pass / pass |
| Corrected event (two checkpoints) | 2/2/2 | 1.229 | 1.164 | pass / pass |
| Empty checkpoint | 0/0/0 | 0.079 | 0.052 | pass / pass |
| Withdrawal (two checkpoints) | 1/2/2 | 1.102 | 1.141 | pass / pass |
| Independent-review boundary | 1/1/1 | 0.700 | 0.677 | pass / pass |
| Publication boundary | 1/1/1 | 0.779 | 0.795 | pass / pass |

The successful cohort made 64 controlled dispatches; **paid submissions = 0**.
Structural contracts passed 16/16; semantic quality was unavailable 16/16;
durable canonical save/browser witnesses were unavailable 16/16. The review
fixture returns a controlled approval flag and is not independent acceptance.
Provider token counts are unknown; static bytes must not be called actual tokens.

Current normal batch behavior is already one preparation + one draft + one
review. Non-batch dirty-event preparation costs E calls (bounded concurrency)
followed by draft/review. Saved successful checkpoints can reduce fresh calls;
up to three draft attempts and three semantic reviews can occur in one
composition attempt. A failed draft skips review. A batch with new messages but
no supported events can still need its source summary; the empty fixtures here
contain no new messages. SQL lane claims stop after three ordinary failures,
with explicit deferral/new-source/manual-retry rules separate from model repair.
Provider-internal attempts remain unknown.

The observer recorded 68 Node planning operations, 44 validation operations and
22 render operations. Median operation times were 58.2ms, 59.0ms and 60.2ms;
their ranges were 50.6–291.8ms, 52.4–108.2ms and 54.6–98.1ms. Some planning and
validation are repeated for transport admission proofs. They are actual local
subprocess observations in the controlled workflow, not a live critical-path
attribution. No overlapped spans are summed into a live latency claim.

For the frozen first-page fence, batch compiled instruction bytes were 1,971
(prepare), 10,561 (draft), 10,437 (review); compact JSON schema bytes were 917,
8,640 and 428. Draft schema hashes vary with the exact authorized evidence
spans, including locale-specific offsets. Twelve exact phase × batch × locale
contracts, their full composed instructions/schemas and manifests are retained.

Important adapter limitation: the existing workflow fixture recompiles the
schema without the actual fence before passing it to its external fixture.
The canonical HTTP envelope itself is validated, and real output guardrails run,
but this adapter is not a canonical live-worker proof. The observer separately
records the actual fenced worker schema. A live adapter must use that exact
runtime schema and retain its receipts.

## Candidates and before/after status

| Candidate | Evidence and possible gain | Contract/risk and decision |
| --- | --- | --- |
| Avoid repeated deterministic Node planning/launches with exact immutable request reuse | Observed ~59ms median per local operation; several calls per checkpoint | Must retain source/policy/config/schema invalidation and admission proofs. Provisional; no live bottleneck evidence or implementation. |
| Reduce repeated context/schema bytes or cache immutable prompt compilation | Exact static sizes/hashes retained; runtime input/output usage unknown | Preserve complete original evidence, language, strict schema and semantic review; prompt publication would need merged-main governance. Provisional. |
| Eliminate preparation or defer review/summary | Could remove a serial model stage only if truly unnecessary | Current draft consumes prepared context and registered proof; review is a quality gate and summary has durable consumers. Unsupported; not selected. |
| Reduce model effort/change route | Local requested route/effort known, effective provider unknown | No quality-preserving measured comparison. Unsupported; not selected. |

No best method is selected before the required baseline. The before/after
comparison is: baseline source/controlled counts as above; candidate unchanged
and unmeasured; absolute/percentage **live** improvement unavailable; 5s/10s
meaningful-response counts unavailable. Nothing in the subsecond fixtures is a
claim that the live product meets either threshold.

## Checks, failures and cleanup

| Existing command scope | Result |
| --- | --- |
| Composer provenance, progressive composer, repair budget, policy/clearance, bounded lane/job engine, prompt composition; `-k 'not pg'` | 204 passed, 1 failed, 20 deselected |
| `tests/test_skill_eval_workflows.py -k composer` | 15 passed, 26 deselected |
| `node --test skills/memoir-composer/tests/*.test.mjs` | 62 passed |
| Observed frozen controlled suite | 16/16 structural contracts, 64 fixture dispatches, no semantic/live acceptance |

The one baseline failure is
`test_prompt_composition.py::test_acknowledgement_guidance_is_conditional_and_reuses_policy_rules`:
the policy prompt is 1,199 characters against a test threshold `<1100`.
No files had changed before the run, so it is an existing main failure. Privacy
instructions were not shortened to satisfy it.

All checks ran through `scripts/run_isolated_check.py`, which strips inherited
provider/DB authority. Pytest additionally denies external network. Initial
sandbox runs failed supervision because `ps` was unavailable; their children
were terminated. After source inspection established the exact process-identity
requirement, a single supervised retry of each succeeded in running the tests.
All original failure receipts are retained, and a later identity-checked cleanup
verified/removes those three task-owned roots. Successful-run cleanup receipts
also confirm their allocation roots removed; no database process was started.

The task-local observer initially used `events.title` instead of the canonical
projection's `events.summary`; 14 draft fixtures failed after 14 successful
preparations (28 budgeted controlled dispatches). That observer defect was
corrected, not an application change. The original script, frozen inputs, raw
failures, outputs and budget receipts are archived in `observer-attempt-1`.
The corrected cohort reused the frozen cases and completed with 64 dispatches.
Total observed-suite fixture submissions across both attempts: 92; paid: 0.
The separate passing existing test suite's controlled calls are not included in
that 92. No failed or incomplete run is represented as a latency success.

No new regression tests were written and no red/green implementation cycle is
claimed. PostgreSQL/schema, hosted/browser, model quality, warm/cold cache,
long-context live repair, true durable resume and held-out live tests were not
run. No place/photo/news research or workspace-localization code changed, so
`make test-place-research` is not required for this documentation-only handoff.

## Evidence and exact remaining prerequisites

The [checked-in evidence summary](memoir-composer-latency-20261025.evidence.json)
contains hashes, local pins, counts, timings and test results without private
data. Full synthetic evidence is in the ignored worktree directory
`var/composer-response-optimization/20261025-offline/`:

- `plan.md`, `frozen-scenarios.json`: pre-dispatch rubric, scenarios and budgets.
- `fixture-suite/receipt.json`: all outputs, source-page and checkpoint witnesses,
  failure/call accounting, evaluator provenance and explicit missing witnesses.
- `controlled-dispatches.json`, `controlled-stage-timings.json`: full synthetic
  model requests/replies and monotonic local stage durations.
- `compiled-contracts.json`, `prompt-sources.json`, `source-hashes.json`: complete
  composed contracts, pins and source/helper provenance.
- `checkout-state.json`, `selected-config.json`: allowed Git inspection and only
  selected nonsecret settings; no credentials or owner-session data.
- `checks/`, `initial-runner-cleanup.json`, `observer-attempt-1/`: actual exit
  receipts/logs, verified cleanup, preserved failed observer evidence.

The parent must resolve the potentially competing composer scope, confirm the
public TDD seams, and either authorize a bounded canonical live baseline or
obtain an explicit offline-only exception before behavior changes. A possible
later diagnostic is first-checkpoint and corrected-event in each locale, one
sample per arm: hard cap **24 application dispatches per arm (48 total), zero
paid judges, 30 minutes per arm**, retaining partial/failing rows on exhaustion.
Keep the actual 600s/240s worker and 615s/255s API per-call limits. Gateway
pricing/effective route and a **dollar cap are unknown**. Matching task-owned
API/worker provenance and permission for any isolated synthetic DB/schema setup
are separate prerequisites. No earlier timeline-testing budget is reused.

| Gate | Status |
| --- | --- |
| Exact skill/repository access, current-main identity, isolated evidence, unrelated edits/secrets preserved | pass |
| Existing targeted structural contracts | 281 tests pass; one existing failure; observed cohort 16/16 pass |
| Active composer scope safely coordinated | inconclusive; owners unknown |
| Approved live baseline or explicit offline-only exception before implementation | unavailable |
| TDD implementation, selected optimization, candidate comparison | not started; prerequisites above |
| Real model semantic quality, meaningful reply/background latency, durable save/retry/next-consumer state | inconclusive |
| Independent cloud review | pending parent arrangement |
| Push / PR / prompt publication / merge / deployment | not performed; outside current permission |
