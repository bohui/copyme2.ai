# Current agents and skills baseline — 3 November 2026

Implemented and ran an 88-case bilingual baseline against the current GPT 6.1 Sol
configuration, three declared repeats of two agent cases, and a zero-call replay
after correcting one evaluator false positive. All **122 experiment items across
10 experiments** were read back from Langfuse with their exact inputs, expected
results, outputs and scores. Inputs were synthetic or public research queries.

## Results

These are contract results within the stated evidence scopes. They do not
certify canonical/UI delivery of model-generated artifacts or human editorial
quality.

| Area | Pass | Fail | Unavailable | Evidence |
| --- | ---: | ---: | ---: | --- |
| [Lane A, corrected replay](http://127.0.0.1:3001/project/cmut9t75w00071z02n8bdv7it/datasets/cmw0nje4n003j1z029k7hbywi) | 27 | 1 | 0 | Current reply projection/schema/validator; retained real model output |
| [Lane B](http://127.0.0.1:3001/project/cmut9t75w00071z02n8bdv7it/datasets/cmw0mxvhl001p1z02md3xby14) | 14 | 0 | 0 | Actual Codex tool loop and production capabilities; disposable domain operations |
| [Skill contracts](http://127.0.0.1:3001/project/cmut9t75w00071z02n8bdv7it/datasets/cmw0mxw4s00261z02ypyn2buw) | 39 | 2 | 5 | Model proposals, composition, deterministic geography and native public research |

The original Lane A experiment remains intact: 26 passed, two failed. The caption
fixture incorrectly required another question after a valid correction
acknowledgement. Production explicitly allows a correction without a question.
The corrected dataset and replay removed that false positive without another
model call. The historical-clue contract failure remained failed.

| Skill | Pass | Fail | Unavailable |
| --- | ---: | ---: | ---: |
| Author timeline | 6 | 0 | 0 |
| Composer | 3 | 0 | 1 |
| Narrator profile | 10 | 0 | 0 |
| Place journey | 4 | 0 | 0 |
| City grouping | 16 | 0 | 0 |
| Public photo research | 0 | 1 | 0 |
| Public historical research | 0 | 1 | 0 |
| Family tree | 0 | 0 | 2 |
| Story game | 0 | 0 | 2 |

Family-tree's canonical runner is unwired. Positive game generation/publication
was not run without an authorized application/browser workflow; its separate
controlled admission/runtime checks passed. Unavailable capabilities received
no numeric contract passing credit.

## Findings

1. **Mira can produce an invalid historical-clue reply.** The first Chinese
   relevant-news output supplied `historical_clue_id` with `question=null` and
   `reason=direct_answer`. The production validator rejected it: “Public context
   requires one optional question without personal evidence or a prepared hint.”
   Three declared additional runs of the same input all passed the contract.
   The original failure is retained: one failure among four observed outputs
   demonstrates variability, not a reliable failure-rate estimate.
2. **Both bounded public-research probes lacked verified delivery.** News native
   discovery completed, but no lead passed independent source inspection and
   evidence validation; a `ValueError` was recorded. Photo discovery returned archive/search pages; inspecting the
   first two produced no independently verified photograph with the requested
   1980s capture evidence. This does not establish that all research queries or
   the complete production research workflows fail. No unverified result was
   awarded passing delivery credit.
3. **English composition exceeded the 150-second case bound.** The Chinese first
   checkpoint completed in 86.181 seconds. The English first checkpoint was
   cancelled at 150.032 seconds and remains unavailable. Both empty checkpoints
   passed. No larger timeout or selected successful retry replaced the result.
4. **A queued-source packet-size assertion still fails.** Replaying 40 windows
   containing repeated control characters produced a 50,191-byte serialized work
   response against the regression's 49,152-byte envelope. Other parameterized
   inputs passed. This establishes a failed envelope check; the individual
   response remains below the runtime's 65,536-byte cumulative tool ceiling, so
   this test alone does not establish an actual production crash. The assertion
   remains unchanged for investigation.

Lane B's 14 compact cases passed, including no-fact source review, explicit
geography without unnecessary profile work, uncertain birth facts, injection
handling, read-before-execute, dependencies and two empty-work cases with no
model invocation. Residence selection also passed all three declared repeats.

## Grader and infrastructure corrections

- Manual-profile fixtures now use current writable fields and preserve manual
  name/blank-year authority. Removed childhood fields and inferred gender-based
  avatar artwork no longer appear as expected profile changes.
- Legacy wire probes now include required confidence/research fields and omit
  the removed prepared-question field. Trace expectations include the current
  `.extract`/`.profile` phase suffixes.
- Native SQL publisher tests request a real disposable TCP publication endpoint
  on Apple Container, instead of constructing a publisher with a null DSN.
- Retained Lane A/B output replay checks exact input hashes, records changed gold
  and original output hashes, and dispatches no model or advisory calls.
- Advisory decoding accepts the pinned judge's observed/exploratory/evaluated
  statuses and comment-list shape while retaining score bounds, known categories
  and evidence-citation requirements. Advisory results cannot override code
  failures. Human calibration remains pending.
- Cancelled direct model requests now record failure and consume their allowance;
  cancellation no longer leaves a misleading `started` call receipt.

## Verification

| Check | Observed result |
| --- | --- |
| Evaluation runner, fixtures, graders and readback tests | **208 passed** |
| Required `make test-place-research` | **741 JavaScript + 821 Python + 96 skill checks passed** |
| Published prompt pins | **94 exact pins verified**; no model prompt content changed |
| Controlled recovery/admission/persistence suites, initial expanded run | 193 passed; 23 failed; six browser cases skipped |
| Affected Lane B modules after endpoint/trace-fixture corrections | **53 passed; one packet-size assertion failed** |
| Previously skipped two-lane browser cases on task-owned source frontend | **6 passed**; owned server stopped |

The expanded run's 23 failures consisted of 18 missing-publication-endpoint
failures, four stale trace-name assertions and the remaining packet-size check.
Its passing privacy-recovery, game-runtime and family-admission checks used
controlled providers and disposable databases. They are distinct from live model
delivery evidence.

The baseline made 66 direct HTTP dispatches, including ten advisory judge calls,
plus 12 native model invocations. Two further Lane B cases skipped generation
because no work was queued. Reported direct usage was 230,470 input and 28,650
output tokens from 65 calls with usage; this excludes native usage and the
unfinished dispatch. Repeats added three direct calls and three native runs.
Direct completed responses identify `gpt-6.1-sol`. Gateway internal attempts and
monetary cost are not established. Same-model semantic scores remain advisory.

## Inspect and reproduce

The [machine-readable evidence ledger](test-evidence/agent-skill-evaluation-20261103.json)
contains dataset IDs/links, every experiment ID, exact readback counts, run
locations and receipt hashes. Local full artifacts:

- `var/agent-evaluation/20261103T115931Z-b74da5/`: frozen 88-case run, original
  outputs, source inspection receipts and matching implementation snapshots.
- `var/agent-evaluation/20261103T121620Z-87791d/`: corrected 28-output replay;
  zero model calls and a model-blind human review worksheet.
- `var/agent-evaluation/20261103T121820Z-0de243/`: six declared repeat results.

See the [runner guide](agent-skill-evaluation.md) for bounded commands, full-case
planning, calibration and evidence scopes. Results are under Langfuse
**Datasets/Experiments and Scores**. The screenshot's legacy hosted evaluator
templates/rules were not activated by these external SDK evaluators.
