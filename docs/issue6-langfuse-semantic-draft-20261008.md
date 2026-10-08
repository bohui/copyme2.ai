# Issue6 semantic dataset draft

Status: local draft for source review. No Langfuse dataset, experiment, trace or
score was published. No model, judge or photo request was made. This draft does
not certify Issue6 semantic acceptance or authorize provider execution.

Runtime source under test is pinned to merged main
`050a664ceadeaeacedd9ac4c38448db494fcf1a4`. The complete Issue6 contract remains
in [the acceptance map](acceptance/issue-6-current-main-e2e.json); this smaller
dataset addresses its outstanding semantic questions, chiefly stories
1, 2, 8, 9, 34 and 36. Standalone operator experience remains deferred. The two
historical unexplained failures and the remaining live gates are preserved in
[the acceptance report](issue6-current-main-e2e-20261008.md).

## Dataset design

[The versioned fixture](../tests/evaluation/issue6_semantic_datasets.json) contains
28 authored synthetic items. None came from customer databases or transcripts.
Each item has an input, expected evidence or review criteria, language/pair
identity and rubric version. Dataset names share `memoir/issue6/20261008-v1/`.

| Dimension | Items | Scope |
|---|---:|---|
| `event-grounding` | 8 | English/Chinese acknowledgements, leading assistant questions, multiple events and distinct recurring events |
| `temporal-placement` | 14 | All seven stages, exact and approximate dates, ages with/without birth evidence, periods and competing accounts |
| `chapter-continuity` | 2 | One 15-round story workflow in each locale, with private draft checkpoints at 5/10/15 |
| `bilingual-consistency` | 4 | Paired outcomes from the same source/dataset/model/run cohort; no additional model calls |

Original source language stays separate from output locale. Long periods remain
one interval; unknown dates stay unknown; capture timestamps do not become story
dates. A chapter may group several events around a supported transition. Neither
one chapter per event nor seven stage chapters is the expected answer.

The gold labels and human rubric are proposed review material, not calibrated
human judgments. Language pairs express equivalent synthetic facts, without
requiring identical prose, titles or opaque server IDs.

## Evaluator scope

[`score_events`](../scripts/issue6_semantic_evaluation.py) accepts the raw
schema-bound timeline proposal, the original sources/context and the item's
expected event contract. It uses the existing public extraction validator for
schema and exact original citations, then scores the validator's normalized,
retained proposals for event count and one-to-one stage/date placement. A
recording-vetoed proposal earns no event or placement credit; an independent
allowed proposal in the same input still advances. The schema score describes
schema/citation validity, not retention or factual entailment. This function
expects an extraction proposal, not a saved
canonical database row with additional storage fields.

Date expressions may include surrounding original words: `1958` and `in 1958`
both retain the same date. A date cannot match inside a different numeric token
such as `19580`. Exact year/range, precision, original evidence and uncertainty
checks remain in force. Output order, opaque IDs and title wording are not
equality targets.

An identity anchor can occur in event, stage or timing evidence; each citation
still passes the same public original-source validator. Period gold labels list
explicit `date_expression_alternatives` for either original endpoint phrase,
because the runtime contract permits choosing one original date expression
while retaining the other date evidence in the basis. Expected range endpoints
and precision remain required.

The age-with-birth-evidence gold cases retain the narrator's original age phrase
and a possible 1958–1959 calendar range with uncertainty. Birth year 1946 plus
age 12 does not uniquely establish 1958. Without birth evidence, the paired
cases retain the age but require unknown calendar years. These are proposed gold
corrections, not evidence of an application or model defect.

Unavailable output has null scores and explicit `unavailable` status. Empty
extraction can receive a code score only for an actual supplied empty proposal;
the future application callback must also verify successful worker completion
and source coverage. Reading an empty event table while work is pending is not
evidence of successful empty extraction.

Valid citations do not prove factual entailment. That score remains null with
`human_review_required`. Meaningful chapter transitions, natural prose and
cross-language factual equivalence also require the proposed rubric's review.
No model judge, endpoint, price or calibrated reviewer is assumed.

## Verification

The actual TDD workflow reproduced the interrupted compatibility failure:
3 passed, 1 failed. After the wording repair, 4 passed. A subsequent adversarial
numeric-token case failed before its boundary repair. That initial draft's
offline verification passed 5 tests. Cloud review then reproduced two bilingual
evidence-role failures, four period-expression failures, one recording-veto
false pass and two age-gold failures before their respective repairs. Final
review-fix verification: **15 passed, zero failures/errors/skips**, with socket
connect/connect_ex blocked.
All outputs in these tests are controlled, not live-model generations.

The first numeric-boundary run also contained a misplaced test assertion. Its
receipt is retained separately; after correcting the fixture, the only red was
the numeric-token behavior. Neither is an application regression or either of
the two historical Issue6 failures.

The first age-gold red run had an unrelated assertion placed in the wrong test;
it was caught and corrected before changing gold labels. Both red receipts are
retained; the corrected run reproduced only the two age-gold mismatches.

Static validation checked all 28 items for unique identities, source/gold quote
references, stage vocabulary, date-expression provenance, checkpoint shape and
paired-case links. That is fixture integrity, not 28 semantic passes. Receipt
files outside the repository include `date-expression-red.json`,
`date-expression-green.json`, `numeric-date-boundary-red-corrected-fixture.json`,
`final-offline-evaluator.json` and `dataset-static-validation.json`, with their
JUnit/log artifacts.

Review-fix receipts are retained separately as `review-evidence-roles-red/green`,
`review-period-expression-red/green`, `review-recording-veto-red/green`,
`review-age-gold-red-corrected-test-placement`, `review-age-gold-green`,
`review-final-offline-evaluator` and
`review-dataset-static-validation-corrected-paired-locale`. The first static
checker incorrectly rejected the intentional `paired` locale; its four checker
errors are retained in `review-dataset-static-validation.json`. Earlier
receipts and content hashes describe the earlier source, not this corrected
fixture. None of these controlled tests calibrates the human rubric.

No application, gateway, migration, entitlement or service configuration changed.
The user's manual-testing checkout and shared stack were left untouched.

## Remaining decisions and execution work

1. Review this source and the proposed gold/rubric. A human reviewer/date and
   accepted examples still need to be recorded before semantic release gates.
2. Obtain explicit publication approval for the identified existing local
   Langfuse project. Publication of these synthetic items is separate from
   approval to execute model requests.
3. Complete the separately reviewed Issue14 actual-provider accounting and
   enforcement, verified existing account/model/reasoning binding, and an exact
   numerical request/input/output/per-request/currency envelope. No execution
   budget is inferred from general enforcement approval.
4. Implement the Langfuse experiment callback at the existing application/worker
   seam, using task-owned synthetic PostgreSQL/projects and a reviewed provider
   adapter. Keep customer databases and shared services outside the run. Verify
   the selected launcher; resolve Issue13/G1 if that launcher requires it.
5. Publish and pin the exact dataset version/content hash, then run one case at
   a time. Stop further provider dispatch on exhausted caps, cancellation,
   failure or unknown usage; no silent retries, budget resets or model changes.
6. Read back dataset/run/trace/score linkage and safe actual usage receipts.
   Keep code checks, unavailable results and pending human judgments separate.

This draft includes no dataset uploader, experiment callback or live-run entry
point. The existing legacy live runner's fail-closed gate is unchanged.

For prompt management, start with the model-facing timeline and composer
templates plus these synthetic datasets. Keep reviewed copies in Git and pin
approved prompt versions and dataset content hashes in experiment receipts.
Privacy, entitlement and persistence rules remain application-owned. Publishing
assets does not authorize model dispatch, and SDK evaluator functions do not
automatically create managed evaluator configurations in the Langfuse UI.

Langfuse supports hosted dataset versions and SDK experiments with custom
item/run evaluators. See the official [dataset documentation](https://langfuse.com/docs/evaluation/experiments/datasets)
and [experiment documentation](https://langfuse.com/docs/evaluation/experiments/experiments-via-sdk).
