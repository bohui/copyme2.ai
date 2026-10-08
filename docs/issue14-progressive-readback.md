# Progressive chapter readback bridge

This source-only bridge prepares correlations and checks returned application
readback shapes for the two published chapter cases. It does **not** run an
evaluation, authenticate a readback, prove persistence, or grant live admission.

## Exact bounded input

`scripts/issue14_progressive_readback.py` verifies the unchanged Issue 6 dataset
SHA-256 `bea8a31f8d4ab0539e2f1c99e08978acbcb4d60ffc25bf36579f04c8a27392c7`.
Only `chapters.transitions.en-AU` and `chapters.transitions.zh-CN` are accepted.
Each has 15 original narrator turns and saved-draft checkpoints at 5, 10 and 15.
Acknowledgements count as turns but need not create events or prose citations.

`ProgressiveReadback(case_id=..., run_id=..., project_id=...,
source_revision=<exact 40-character commit>)` provides:

- `driver_inputs()`: detached case/project IDs, original texts and locale. No
  expected answers, provider configuration, live mode, or execution function.
- `before_round(case_id, ordinal)`: existing synchronous driver hook; stable
  distinct round trace IDs bound to run, project, source, dataset and case.
  All fields survive the application's existing correlation normalizer.
- `capture(terminal_outcome)`: consumes the result returned by
  `CanonicalEvaluationDriver.run_case`, not its mutable progress lists. Requires
  all 15 completed/settled rounds, matching trajectory correlations and complete
  original-source snapshots, then ready saved checkpoints at 5/10/15.
- `observation(terminal_outcome)`: SDK-neutral output/metadata data. Invalid or
  incomplete evidence yields `output=None`. Nothing is uploaded.

The saved-state checks require matching project/language/kind/source versions,
zero pending extraction, exact coverage, positive manuscript revisions, matching
completed milestone history, a locale-matching nonempty saved preview, and no
pending proposal/update/error. Section references resolve against originals
present at that checkpoint; actual string-version, span-only composer references
are supported. Same-ID/same-fingerprint sections retain their full stored data;
changed fingerprints require a newer section revision. Manuscript revision may
stay unchanged only when the saved preview and sections also stay unchanged.

The returned projection includes the dataset-to-application source-ID mapping
and stored section text/references/revisions for each checkpoint. It omits raw
trajectories, private reasoning and arbitrary metadata. It is for these synthetic
cases only and is not authorization to export customer testimony.

## What the evidence means

The result is `structural_readback_complete`, with
`evidence_basis=caller_supplied_application_readback`, `durability_verified=false`,
`provider_cohort_verified=false`, and `live_ready=false`. A caller can fabricate
a shape; source checks are not a signature or independently observed persistence.
The declared execution mode is retained as a label, not trusted as proof.

No automatic semantic score is produced. Human review still covers factual
entailment, meaningful transitions, chronology and adult prose/locale. This
projection also does not prove chapter-wide word limits, canonical event
entailment, original workflow/DB execution or provider usage. Existing application
validators and eventual full saved-manuscript evidence remain necessary.

The bilingual item `bilingual.chapters.transitions` still needs independently
verified matching run/source/dataset/provider-model/reasoning cohorts and both
locale gold contracts, followed by human review. Equality of missing provider
metadata is not cohort evidence. This bridge does not execute or score that item.

## Integration and stopping point

Controlled tests exercise the real driver's hook ABI with fake in-process
storage/runtime/lane outcomes. They establish compatibility of the bridge, not a
native Postgres/Temporal/provider experiment. The historical driver live branch
continues to require exactly five turns; it must not be relabelled or relaxed to
dispatch these 15-turn cases. The dedicated Issue 14 launcher still denies before
any runtime/worker/judge factory.

After this bridge's source review, the user explicitly removed the strict token
limit requirement for this progressive evaluation. That permits planning a
**separate subscription evaluation mode** on the existing route; it does not
change the historical Issue 14 token/currency contracts or make them pass.
This bridge still contains no executor or live admission path.

The minimal next execution contract must explicitly state:

1. The two fixed 15-turn synthetic cases, checkpoints 5/10/15, a shared request
   ceiling, absolute run deadline and concurrency bound. The earlier suggestions
   of 160 attempts, 30 minutes and concurrency 1 remain proposals until the run
   scope is agreed. No new paid provider/account or credential/security change is
   authorized by removing a token-limit requirement.
2. The counted boundary. Private worker HTTP requests are not provider requests.
   A dedicated task-only client-to-existing-gateway seam could count Codex sends,
   including its tool loops, without claiming visibility into gateway-internal
   retries. Receipts must name that limitation. Error/cancellation stops further
   client dispatch; disconnect cannot prove upstream work has stopped.
3. No hard token or dollar guarantee. Observed usage can be recorded as reported,
   but missing/uncertain usage cannot become a fabricated bound. The historical
   byte-token/XTS fixture remains synthetic-only. Historical stripped-output-cap
   evidence no longer blocks this separately scoped evaluation merely because
   it cannot prove a strict token ceiling.
4. An isolated native executor that obtains actual saved workflow outcomes and
   supplies this bridge's hooks, then a pinned SDK experiment callback. Native
   execution and any authenticated Langfuse experiment writes must be coordinated
   through the parent. All four existing rules stay disabled; no judge/photo call
   or semantic score is supplied by this bridge.
5. Human rubric/calibration inputs and full native evidence before semantic
   acceptance. Matching provider-model/reasoning/run cohorts remain necessary for
   a bilingual comparison, even when no strict token cap is requested.

The full Issue 14 strict accounting ACs still require complete final-payload
input/tokenizer accounting, verified hard output/reasoning caps, account/wire-model
and rate/currency evidence, pre-send reservations and strict settlement around
every actual provider attempt, and explicit numerical approval. They remain open.

No runtime hook, historical launcher/gateway/judge, publication asset or
source-contract pin changes are included here. This bridge does not relabel a
15-turn run as the historical five-turn canary, or as mock-only live execution.

## Source gate and verification

Base `9895006f0aaec8425abb21a99f88e39a3a982c2f` already fails the old closed
source inventory with `source_inventory_invalid` after the merged photo-memory
runtime changes. This addition is also outside that snapshot. The historical
proof and inventory are preserved; do not repin or waive old evidence. A future
versioned current-source contract requires independent review of the full new
runtime inventory. This draft is not ready for merge while that gate is failing.

Focused tests: `python -m pytest tests/test_issue14_progressive_readback.py -q`.
Regression tests also cover the unchanged Issue 14 protocol/admission modules and
Issue 6 publication/evaluator assets. No live/native evaluation is claimed.
