# Judge calibration — 4 November 2026

All 140 current-pin judgments match the synthetic answer keys, with exact inputs, gold, outputs and named scores verified in Langfuse. Independent human calibration is still pending.

Shared dataset: [memoir/evaluators/shared/judge-calibration/calibration/shared-v2](http://127.0.0.1:3001/project/cmut9t75w00071z02n8bdv7it/datasets/cmw1wgk0x00sp1z02dpgfqqcf).

| Judge | Development agreements | Holdout/regression agreements |
| --- | ---: | ---: |
| completeness | 7 | 7 |
| correctness | 8 | 8 |
| five-case | 3 | 3 |
| memoir-author-timeline | 3 | 3 |
| memoir-composer | 3 | 3 |
| memoir-family-tree | 3 | 3 |
| memoir-historical-news-research | 3 | 3 |
| memoir-interviewer | 3 | 3 |
| memoir-memory-context | 3 | 3 |
| memoir-place-groups | 3 | 3 |
| memoir-place-journey | 3 | 3 |
| memoir-place-photo-research | 3 | 3 |
| memoir-story-game | 3 | 3 |
| mira-comparison | 2 | 2 |
| relevance | 8 | 8 |
| safety | 7 | 7 |
| semantic-boundaries | 2 | 2 |
| trajectory | 3 | 3 |

## What changed

- Replaced 24 placeholder items across 14 old calibration datasets with one frozen shared dataset: 80 bilingual cases, 18 executable judge contracts and all 21 managed evaluator prompt components. Archived the old items and the superseded 80-case prototype; preserved datasets, experiments, split lineage and recovery records.
- Fixed the five-case consumer: omitted, unobserved score categories are valid; unsupported keys, malformed numeric values and unavailable verdicts carrying scores are rejected.
- Published relevance v2 with three explicit anchors. Development had assigned 0.2 where the published partly-useful/substantial-digression anchor was 0.5. All eight development relevance checks then matched. The hosted relevance evaluator was also updated to v2 with its existing model, parameters, mappings, output definition and rules preserved.
- Published timeline quality v2: judge the supplied contract rather than demanding an invented negation field. Correct attribution plus the exact quote preserves negation. All six timeline regression checks matched. There is no separate hosted timeline template to update.
- Corrected ambiguous v1 fixtures before opening v2 holdout: factual residence support, explicit serious privacy risk and a relevance/completeness constraint confound. Retained the original source and 67/70 local development result.
- Fixed calibration gating to retain latest current-pin failures and use recorded run timestamps rather than file modification order. Missing execution and failed grading remain in the denominator.
- Used the installed Langfuse v4 experiment/result APIs, decoded serialized I/O, read full score metadata with Scores v3, and verified score subjects and prompt/response provenance.

## Results and limits

The v2 development baseline matched 69/70; relevance v2 then matched 8/8. The first v2 holdout matched 68/70, with 69 available responses: the remaining rows were the timeline grading error and a trajectory timeout. Timeline v2 matched 6/6 across both splits. The isolated trajectory recheck matched with a recorded 180-second cap after two 90-second timeouts; the successful call took 70.634 seconds. The CLI default is now 180 seconds, capped at 240, with no automatic model retry.

Initial held-out run exposed one timeline grading mistake and one timeout. Subsequent timeline and trajectory rechecks are regressions after exposure, not independent fresh holdout acceptance.

These are small, agent-authored specification tests. The held-out Chinese cases vary language within the same scenario families; they are locale regressions, not unseen-family generalization. Passing them does not establish independent human agreement, every possible task failure, canonical persistence or UI quality. A fresh independently labeled holdout is needed before using semantic scores as a release gate. The agent/skill campaign uses separate generated outputs and code checks.

[Commands and interpretation](judge-calibration.md). [Machine-readable results](test-evidence/judge-calibration-20261104.json). [Retirement and recovery records](test-evidence/judge-calibration-retired-items-20261104.json).
