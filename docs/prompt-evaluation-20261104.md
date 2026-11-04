# Prompt execution evaluation — 4 November 2026

The shared judge calibration and the complete supported 198-case agent/skill
catalog were executed against the current published prompt pins. Nine completed
composer rechecks and a retained-output profile regrade follow the original
campaign. The per-prompt Langfuse ledger records observed versions and gaps for
all 96 retained managed prompts. It does not claim that every prompt or every
conditional branch passed a quality evaluation.

## Commands

```sh
make llm_judge_calibrate
make prompt-eval PROMPT_EVAL_NAME=memoir/agents/mira/reply
make prompt-eval PROMPT_EVAL_NAME=memoir/agents/atlas/skill-selection
make prompt-eval SKILL_EVAL_NAME=author-timeline
make prompt-eval-all
```

These are the current commands. `prompt-eval` now selects its frozen datasets
and graders automatically; `prompt-eval-plan` previews the selection without
model calls. The raw prompt preflight and separate agent Make targets used during
the original campaign are retired. Historical results below retain their original
receipts and source revisions.

See the [command guide](judge-calibration.md) for budgets, selected rechecks and
publishing retained results without dispatching the full catalog again.

## Judge calibration

The [shared dataset](http://127.0.0.1:3001/project/cmut9t75w00071z02n8bdv7it/datasets/cmw1wgk0x00sp1z02dpgfqqcf)
contains 80 fictional cases and 140 applicable judgments across 18 contracts.
All 21 managed evaluator prompt components have current-pin agreement evidence.
Inputs, answer keys, outputs, named scores, prompt manifests and exact score
subjects were read back. Original mistakes, unavailable responses and previous
versions remain in their original experiments.

These are agent-authored specification answer keys. Independent human labels
remain pending. Chinese holdout variants share scenario families with development
cases, and exposed holdout failures informed subsequent fixes. The final agreement
result is a synthetic regression result, not independent generalization or human
editorial acceptance. See the [calibration report](judge-calibration-20261104.md).

## Grading and execution fixes

| Finding | Change and verification |
| --- | --- |
| Five-case grading rejected omitted, unobserved dimensions. | Accept a validated, evidenced subset; retain rejection of malformed/unknown scores and unavailable verdicts with numeric grades. |
| Relevance interpolated below its declared partial-usefulness anchor. | Published relevance v2 with explicit 0, 0.5 and 1 anchors; updated the independently versioned hosted evaluator to the same content. Eight development checks matched. |
| Timeline quality demanded an undeclared negation flag. | Published timeline quality v2: correctly attributed exact quotes satisfy the supplied contract without an invented field. Six regression judgments matched. |
| Profile grading rejected an offset mismatch that production repairs. | Apply the actual production normalizer, independently verify its resulting Unicode spans against the original, then compare unchanged expected facts. Preserve and regrade the original model response without another model call. Missing facts and unsupported quotes still fail. |
| Composer's per-call limit was also imposed on its entire workflow. | Keep a 150-second provider-call budget and a separate 600-second multi-call workflow budget in the full campaign. Recheck only the 12 affected cases; nine completed before local interruption. Recover those nine without more model calls; the other three retain their earlier unavailable outcome. Completed phases never establish a complete workflow result. |
| A provider HTTP error without a response counted as model contract failure. | Classify the missing execution as unavailable. Retained-result publication records the original status and the reclassification without editing the original experiment. A returned, invalid model proposal remains a failure. |
| Prompt-ledger publication assumed all dataset inputs had a skill field. | Support prompt-only ledger rows and exercise the actual generic publisher in a regression. Retain the completed 198-case campaign instead of dispatching it again. |
| Live experiment SDK results and score summaries differ from old APIs. | Use the installed experiment API/result URL, decode serialized I/O, verify full calibration score metadata/subjects and match named scores to exact outputs. |

## Interpretation and remaining work

- Mira and Atlas results check current production prompt construction, schema,
  tool selection and task-specific code contracts. Disposable host state makes
  these proposal evaluations; it does not prove canonical database delivery,
  UI footprints, map camera behavior or a saved conversation.
- Four original timeline cases returned empty events against a nonempty-event
  answer key: ambiguous identity and another person's recollection, in both
  locales. Keep these failures and inspect their task/oracle semantics before
  changing either the prompt or answer key. They have not been relabeled as
  successes merely to improve the score.
- Native photo discovery produced no independently verified artifact in its
  evaluated attempt. Native historical-news discovery has its own inspected
  source evidence. A useful-looking search response alone does not pass photo
  verification.
- Family extraction has no wired canonical runner; game delivery needs its
  actual authorization and browser workflow. Their 32 cases remain unavailable.
  Speech and unexecuted probe/conditional prompts need their own supported
  scenarios. Dataset associations do not fill these gaps.
- Trajectory judgments on sampled agent outputs are same-model advisory scores.
  Synthetic rubric calibration does not turn them into independent human
  acceptance. Missing judgments and failures remain visible.
- Direct HTTP dispatch counts are known. Native provider attempt counts,
  gateway retries and total monetary cost are not established by these receipts.

The [prompt inventory](prompt-coverage.md) maps every source to its consumers,
scenarios, evaluator and datasets. The execution tables below add observed
current-pin evidence. Future prompt changes must review the dataset and grader
together under the [prompt evaluation workflow](prompt-evaluation-workflow.md).

## Executed results

Completed on 5 November in Australia/Sydney; run identifiers and the metadata snapshot use 4 November UTC.

The retained 198-case projection is **154 pass, 6 fail and 38 unavailable**. Mira passes 70/70 and Atlas 14/14 code-contract cases. The per-prompt ledger observes 43 exact current pins: **30 pass and 13 fail**; **53 current pins have no executed supported scenario**.

| Component / skill | Pass | Fail | Unavailable |
| --- | ---: | ---: | ---: |
| lane-a / memoir-interviewer | 70 | 0 | 0 |
| lane-b / memoir-background-agent | 14 | 0 | 0 |
| skills / memoir-author-timeline | 12 | 4 | 0 |
| skills / memoir-composer | 9 | 1 | 6 |
| skills / memoir-family-tree | 0 | 0 | 16 |
| skills / memoir-historical-news-research | 1 | 0 | 0 |
| skills / memoir-memory-context | 16 | 0 | 0 |
| skills / memoir-place-groups | 16 | 0 | 0 |
| skills / memoir-place-journey | 16 | 0 | 0 |
| skills / memoir-place-photo-research | 0 | 1 | 0 |
| skills / memoir-story-game | 0 | 0 | 16 |

The baseline was 148 pass, 6 fail and 44 unavailable. The profile regrade repairs one false failure. Nine completed composer rechecks replace nine earlier timeouts: five pass, one remains a workflow failure and three are unavailable after provider errors/timeouts. Three more recheck results were not finalized before interruption and retain their earlier unavailable status. Original attempts and the interrupted receipt are preserved.

The 38 unavailable cases comprise 16 family, 16 game and 6 composer cases. The six failures comprise four timeline omissions against the current answer key, one composer workflow failure and one unverified photo-discovery result. These are task findings, not a claim that the run passed.

The baseline has 163 direct dispatch records (151 completed, 12 failed), including 11 same-model advisory judge calls. The interrupted composer receipt has 36 phase-call records (33 completed, 3 failed). Fourteen native runs are recorded separately; their internal provider attempts and total cost remain unknown. Profile regrading, composer-result recovery and final ledger publication dispatched no new model calls.

## Langfuse experiments

[All-prompt coverage ledger](http://127.0.0.1:3001/project/cmut9t75w00071z02n8bdv7it/datasets/cmw1zbw9e013z1z02h8zhs4os/runs/54deb0f957ed37c4) — all 96 inputs, expected coverage flags, outputs and named scores read back. Coverage flags are not editorial quality scores.

| Run | Dataset | Items | Verified experiment |
| --- | --- | ---: | --- |
| baseline | `memoir/agents/mira/reply/golden/campaign-b176fe2d7734` | 70 | [16b4980b3b50defb](http://127.0.0.1:3001/project/cmut9t75w00071z02n8bdv7it/datasets/cmw1xdco600v51z024evmmr1v/runs/16b4980b3b50defb) |
| baseline | `memoir/agents/atlas/skill-selection/golden/campaign-068f68a58ef3` | 14 | [a3209468e41acbbd](http://127.0.0.1:3001/project/cmut9t75w00071z02n8bdv7it/datasets/cmw0mxvhl001p1z02md3xby14/runs/a3209468e41acbbd) |
| baseline | `memoir/skills/author-timeline/extract/golden/campaign-47b4a4b14664` | 16 | [7902d039cd3e61fa](http://127.0.0.1:3001/project/cmut9t75w00071z02n8bdv7it/datasets/cmw1xdh4100x61z02j759k06p/runs/7902d039cd3e61fa) |
| baseline | `memoir/workflows/composer-checkpoints/golden/campaign-0c088257c478` | 16 | [2203430d16a32c56](http://127.0.0.1:3001/project/cmut9t75w00071z02n8bdv7it/datasets/cmw1xdhmc00xp1z02agkwl62w/runs/2203430d16a32c56) |
| baseline | `memoir/skills/family-tree/extract/golden/campaign-8dbc6feacd76` | 16 | [87e8fb160edfa61c](http://127.0.0.1:3001/project/cmut9t75w00071z02n8bdv7it/datasets/cmw1xdi4j00y81z029fh1psap/runs/87e8fb160edfa61c) |
| baseline | `memoir/skills/memory-context/profile/golden/campaign-c9782a9df9b5` | 16 | [1ac226f1421ffe49](http://127.0.0.1:3001/project/cmut9t75w00071z02n8bdv7it/datasets/cmw1xdio600yr1z027vlqx7x8/runs/1ac226f1421ffe49) |
| baseline | `memoir/skills/place-journey/extract/golden/campaign-eac77f97ffe3` | 16 | [e89304f376748dd0](http://127.0.0.1:3001/project/cmut9t75w00071z02n8bdv7it/datasets/cmw1xdj8r00za1z02ebar0x6p/runs/e89304f376748dd0) |
| baseline | `memoir/skills/place-groups/group/golden/campaign-30393d2d8676` | 16 | [9103fbcedd74ea09](http://127.0.0.1:3001/project/cmut9t75w00071z02n8bdv7it/datasets/cmw1xdjpy00zt1z029rbi0l7p/runs/9103fbcedd74ea09) |
| baseline | `memoir/workflows/story-game-adaptation/golden/campaign-c84200bd1d72` | 16 | [60442d1503034136](http://127.0.0.1:3001/project/cmut9t75w00071z02n8bdv7it/datasets/cmw1xdk6r010c1z025otonsvs/runs/60442d1503034136) |
| baseline | `memoir/skills/place-photo-research/discovery/golden/campaign-ebb28c084918` | 1 | [44b18f4afaab830a](http://127.0.0.1:3001/project/cmut9t75w00071z02n8bdv7it/datasets/cmw1xdknq010v1z02vg558r8m/runs/44b18f4afaab830a) |
| baseline | `memoir/skills/historical-news-research/discovery/golden/campaign-c7979e3b2ce3` | 1 | [98e928fb4b4c9e19](http://127.0.0.1:3001/project/cmut9t75w00071z02n8bdv7it/datasets/cmw1xdkp3010z1z02aj7o7fsu/runs/98e928fb4b4c9e19) |
| recovered_composer | `memoir/workflows/composer-checkpoints/golden/campaign-ce3edc4b782f` | 9 | [cc2503aedc9d68b3](http://127.0.0.1:3001/project/cmut9t75w00071z02n8bdv7it/datasets/cmw2mgxk700071z02gnaeok6e/runs/cc2503aedc9d68b3) |
| profile_regrade | `memoir/skills/memory-context/profile/golden/campaign-93cfb9cb67ba` | 1 | [2cc1106657744d2f](http://127.0.0.1:3001/project/cmut9t75w00071z02n8bdv7it/datasets/cmw2mfnh400031z02m8ma6xhy/runs/2cc1106657744d2f) |

All experiment rows above have exact input/gold/output/named-score readback. The latest metadata snapshot contains 111 datasets and 1,024 experiment items, including history and incomplete/failed attempts; those counts are not pass rates. Eight hosted evaluator definitions and 68 automation rules remain. SDK experiment grading is recorded separately from hosted rules in the prompt inventory.

New scores use `<evaluated-target>/<metric>` so the global Scores table identifies the agent, skill or judge. Historical experiments retain their original score names. The latest ledger has no model-prompt binding of its own: it records coverage rather than pretending to be a quality dataset for all prompts.

## Current prompt outcomes

A failure takes precedence when any observed scenario fails. An unavailable or missing scenario cannot earn a passing quality score. Shared-component outcomes describe the scenarios that used that exact component; they do not identify that component as the cause of a workflow failure.

| Prompt | Version | Current pin observed | Result | Evidence rows |
| --- | ---: | --- | --- | ---: |
| `memoir/agents/atlas/skill-selection` | 1 | yes | pass | 12 |
| `memoir/agents/mira/policy-review` | 1 | no | unavailable | 0 |
| `memoir/agents/mira/repair` | 1 | no | unavailable | 0 |
| `memoir/agents/mira/repair-codes` | 5 | no | unavailable | 0 |
| `memoir/agents/mira/reply` | 7 | yes | pass | 70 |
| `memoir/evaluators/agents/mira/reply/comparison` | 1 | yes | pass | 4 |
| `memoir/evaluators/agents/mira/reply/interview-quality` | 1 | yes | pass | 6 |
| `memoir/evaluators/shared/completeness` | 1 | yes | pass | 14 |
| `memoir/evaluators/shared/correctness` | 1 | yes | pass | 16 |
| `memoir/evaluators/shared/evidence-policy` | 1 | yes | pass | 60 |
| `memoir/evaluators/shared/relevance` | 2 | yes | pass | 16 |
| `memoir/evaluators/shared/safety` | 1 | yes | pass | 14 |
| `memoir/evaluators/shared/semantic-boundaries` | 1 | yes | pass | 4 |
| `memoir/evaluators/shared/trajectory/rubric` | 2 | yes | pass | 6 |
| `memoir/evaluators/shared/trajectory/system` | 2 | yes | pass | 23 |
| `memoir/evaluators/skills/author-timeline/extract/quality` | 2 | yes | pass | 6 |
| `memoir/evaluators/skills/family-tree/extract/quality` | 1 | yes | pass | 6 |
| `memoir/evaluators/skills/historical-news-research/discovery/quality` | 1 | yes | pass | 6 |
| `memoir/evaluators/skills/memory-context/profile/quality` | 1 | yes | pass | 6 |
| `memoir/evaluators/skills/place-groups/group/quality` | 1 | yes | pass | 6 |
| `memoir/evaluators/skills/place-journey/extract/quality` | 1 | yes | pass | 6 |
| `memoir/evaluators/skills/place-photo-research/discovery/quality` | 1 | yes | pass | 6 |
| `memoir/evaluators/workflows/composer-checkpoints/quality` | 1 | yes | pass | 6 |
| `memoir/evaluators/workflows/five-case-memoir/guard` | 2 | yes | pass | 6 |
| `memoir/evaluators/workflows/five-case-memoir/trajectory` | 2 | yes | pass | 6 |
| `memoir/evaluators/workflows/story-game-adaptation/quality` | 4 | yes | pass | 6 |
| `memoir/probes/providers/connectivity` | 1 | no | unavailable | 0 |
| `memoir/probes/providers/web-search` | 1 | no | unavailable | 0 |
| `memoir/probes/providers/worker` | 1 | no | unavailable | 0 |
| `memoir/probes/shared/native-search` | 1 | no | unavailable | 0 |
| `memoir/probes/skills/author-timeline/extract` | 1 | no | unavailable | 0 |
| `memoir/probes/skills/historical-news-research/discovery` | 1 | no | unavailable | 0 |
| `memoir/probes/skills/place-groups/group` | 1 | no | unavailable | 0 |
| `memoir/probes/skills/place-groups/instructions` | 1 | no | unavailable | 0 |
| `memoir/probes/skills/place-photo-research/discovery` | 1 | no | unavailable | 0 |
| `memoir/probes/skills/story-game/brief` | 4 | no | unavailable | 0 |
| `memoir/shared/bounded-context/en-AU` | 2 | yes | fail | 34 |
| `memoir/shared/bounded-context/policy` | 1 | yes | fail | 70 |
| `memoir/shared/bounded-context/zh-CN` | 2 | yes | fail | 36 |
| `memoir/shared/historical-acknowledgements` | 1 | no | unavailable | 0 |
| `memoir/shared/place-conflicts` | 1 | no | unavailable | 0 |
| `memoir/shared/recall-invitations` | 1 | no | unavailable | 0 |
| `memoir/shared/skill-agent` | 1 | yes | pass | 12 |
| `memoir/skills/author-timeline/attribution` | 3 | no | unavailable | 0 |
| `memoir/skills/author-timeline/continuity` | 1 | no | unavailable | 0 |
| `memoir/skills/author-timeline/contract` | 1 | yes | fail | 42 |
| `memoir/skills/author-timeline/derived-hints` | 5 | yes | pass | 16 |
| `memoir/skills/author-timeline/extract` | 3 | yes | fail | 16 |
| `memoir/skills/author-timeline/extract-with-hints` | 3 | yes | pass | 16 |
| `memoir/skills/author-timeline/instructions` | 15 | yes | fail | 42 |
| `memoir/skills/author-timeline/shared/grounding` | 2 | yes | fail | 32 |
| `memoir/skills/author-timeline/window` | 2 | yes | fail | 32 |
| `memoir/skills/composer/batch/compose` | 1 | yes | fail | 38 |
| `memoir/skills/composer/batch/prepare` | 1 | no | unavailable | 0 |
| `memoir/skills/composer/draft` | 2 | yes | fail | 20 |
| `memoir/skills/composer/instructions` | 1 | yes | pass | 2 |
| `memoir/skills/composer/outline/leaf/en-AU` | 2 | no | unavailable | 0 |
| `memoir/skills/composer/outline/leaf/zh-CN` | 2 | no | unavailable | 0 |
| `memoir/skills/composer/outline/merge/en-AU` | 2 | no | unavailable | 0 |
| `memoir/skills/composer/outline/merge/zh-CN` | 2 | no | unavailable | 0 |
| `memoir/skills/composer/outline/shared/prefix` | 1 | no | unavailable | 0 |
| `memoir/skills/composer/outline/shared/suffix` | 1 | no | unavailable | 0 |
| `memoir/skills/composer/prepare` | 1 | no | unavailable | 0 |
| `memoir/skills/composer/review` | 4 | yes | fail | 18 |
| `memoir/skills/composer/shared/editorial-review` | 5 | yes | fail | 18 |
| `memoir/skills/composer/shared/narrative-enrichment` | 2 | yes | fail | 38 |
| `memoir/skills/family-tree/extract` | 1 | no | unavailable | 0 |
| `memoir/skills/historical-news-research/contract` | 1 | no | unavailable | 0 |
| `memoir/skills/historical-news-research/discovery` | 1 | no | unavailable | 0 |
| `memoir/skills/historical-news-research/instructions` | 2 | no | unavailable | 0 |
| `memoir/skills/memory-context/profile` | 5 | yes | pass | 20 |
| `memoir/skills/memory-context/summary` | 1 | no | unavailable | 0 |
| `memoir/skills/place-journey/extract` | 3 | yes | pass | 16 |
| `memoir/skills/place-journey/instructions` | 1 | yes | pass | 6 |
| `memoir/skills/place-photo-research/discovery` | 1 | no | unavailable | 0 |
| `memoir/skills/place-photo-research/instructions` | 2 | no | unavailable | 0 |
| `memoir/skills/story-game/brief` | 3 | no | unavailable | 0 |
| `memoir/skills/story-game/higgsfield` | 1 | no | unavailable | 0 |
| `memoir/skills/story-game/instructions` | 6 | no | unavailable | 0 |
| `memoir/skills/story-game/novel-to-game/adapter` | 2 | no | unavailable | 0 |
| `memoir/skills/story-game/novel-to-game/analyze` | 1 | no | unavailable | 0 |
| `memoir/skills/story-game/novel-to-game/art` | 2 | no | unavailable | 0 |
| `memoir/skills/story-game/novel-to-game/assets` | 1 | no | unavailable | 0 |
| `memoir/skills/story-game/novel-to-game/concept` | 1 | no | unavailable | 0 |
| `memoir/skills/story-game/novel-to-game/design` | 1 | no | unavailable | 0 |
| `memoir/skills/story-game/novel-to-game/illustration` | 1 | no | unavailable | 0 |
| `memoir/skills/story-game/novel-to-game/journey` | 1 | no | unavailable | 0 |
| `memoir/skills/story-game/novel-to-game/production` | 1 | no | unavailable | 0 |
| `memoir/skills/story-game/novel-to-game/production_style` | 1 | no | unavailable | 0 |
| `memoir/skills/story-game/novel-to-game/whitebox` | 1 | no | unavailable | 0 |
| `memoir/skills/story-game/proposal` | 3 | no | unavailable | 0 |
| `memoir/skills/story-game/runtime-contract` | 8 | no | unavailable | 0 |
| `memoir/skills/story-game/webpage` | 2 | no | unavailable | 0 |
| `memoir/workflows/speech/synthesis/default` | 1 | no | unavailable | 0 |
| `memoir/workflows/speech/synthesis/en-AU` | 1 | no | unavailable | 0 |
| `memoir/workflows/speech/synthesis/zh-CN` | 1 | no | unavailable | 0 |

## Verification

- Evaluation regressions: 255 passed, 4 Linux-only lifecycle checks skipped on macOS.
- Score-name/ledger follow-up: 52 passed; every managed prompt name can be scored, including `production_style`.
- Inventory, binding, score-name and snapshot follow-up: 46 passed.
- `make prompt-coverage` and `make prompt-check` passed, including 96 exact published prompt versions and 111 dataset identities.
- The documented individual Mira `make prompt-eval` preflight resolved v7 and 16 frozen dataset items without model calls.

[Machine-readable execution and prompt evidence](test-evidence/prompt-evaluation-20261104.json). [Judge calibration and recovery evidence](test-evidence/judge-calibration-20261104.json).
