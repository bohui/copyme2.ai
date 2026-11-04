# Langfuse naming

`Trace Name` identifies the agent or workflow for one run. `Name` identifies an
observation (a model call, tool call or other step) within that run. A trace ID
groups its observations; reusing a trace name does not merge runs. Sessions link
related runs. Mira and Atlas worker runs use the same pseudonymous owner/project session ID;
different owners and projects remain separate.

| Trace name | Observation names |
| --- | --- |
| `memoir-mira` | `memoir-mira.policy-review`, `.reply`, `.reply-repair`, `.read-context` |
| `memoir-atlas` | `memoir-atlas.orchestrate`, `.check-pending-work`, `.read-skill`, `.execute-skill`, `.process-source` |
| `memoir-author-timeline` | `memoir-author-timeline.extract`, `.summarize`, `.dispatch` |
| `memoir-composer` | `memoir-composer.prepare`, `.draft`, `.review`, `.outline-<phase>`, `.dispatch` |
| `memoir-memory-context` | `memoir-memory-context.profile`, `.dispatch` |
| `memoir-place-journey` | `memoir-place-journey.extract`, `.dispatch` |
| `memoir-place-groups` | `memoir-place-groups.<phase>` |
| `memoir-family-tree` | `memoir-family-tree.<phase>` |
| `memoir-place-photo-research` | `memoir-place-photo-research.discovery`, `.research` |
| `memoir-historical-news-research` | `memoir-historical-news-research.discovery`, `.research` |
| `memoir-speech` | `memoir-speech.transcription`, `.synthesis` |
| `memoir-story-game` | `memoir-story-game.scenes`, `.brief`, `.analyze`, `.concept`, `.design`, `.whitebox`, `.art`, `.production`, `.illustration`, `.build` |
| `evaluation/memoir-mira` | `evaluation/memoir-mira.<variant>` |
| `evaluation/memoir-judges` | `evaluation/memoir-judges.trajectory`, `.<judge>` |
| `evaluation/memoir-probes` | `evaluation/memoir-probes.connectivity`, `.web-search` |
| `evaluation/memoir-prompts` | `evaluation/memoir-prompts.generate` for a pinned prompt experiment |
| `evaluation/<skill>` | `evaluation/<skill>.probe` for isolated skill checks |

Nested skill observations retain their skill-specific names and inherit the
coordinator's trace name. For example, `memoir-composer.review` normally appears
under `memoir-atlas`. A directly invoked skill can have its own trace root.
Evaluation worker runs prefix both levels with `evaluation/`. The generic worker
fallback is `memoir-skill-agent.run`; its tool steps follow the Atlas convention.
These labels describe instrumentation; they do not imply that every skill has a
live standalone model path. Interview guidance is part of Mira's native context;
there is no separate interview-guidance model trace.

Historical traces keep their recorded names. Only new observations use changed
labels. Speech and image observations contain bounded summaries rather than full
text or media, so textual online quality judges exclude these observations.
Langfuse itself owns labels such as `Test evaluator` and `Execute evaluator: …`
in its reserved `langfuse-llm-as-a-judge` environment. The online rule explicitly
excludes these internal environments; application evaluation runs use the
`evaluation/` prefix above.
The SDK also owns `experiment-item-run` and `experiment-item-task` observations
in the `sdk-experiment` environment; their model calls carry the application
evaluation labels.

## Target-first evaluation paths

The same target path connects application prompts, datasets and evaluation rules:

| Object | Example |
| --- | --- |
| Prompt under test | `memoir/agents/mira/reply` |
| Dataset | `memoir/agents/mira/reply/golden/core` |
| Judge prompt and reusable evaluator | `memoir/evaluators/shared/relevance` |
| Dataset rule | `memoir/agents/mira/reply/golden/core/quality` |
| Online rule | `memoir/agents/mira/reply/online/quality` |

`quality` is a rule assigning several independent judges to one sampled item.
Dataset rules use correctness, relevance, completeness and safety. Online rules
use the latter three on the same 10% sample; correctness requires a reference.
Rule names with one metric end with that metric instead. All rules apply only to
new observations or experiments. Evaluation and internal judge environments are
excluded from online rules; speech and image summaries are not text outputs.

Targets belong to `memoir/agents/<name>/<operation>`,
`memoir/skills/<name>/<operation>` or `memoir/workflows/<specific-workflow>`.
Dataset categories (`golden`, `safety`, `relevance`, `stress`, `calibration`) follow
the target, then a suite name. A category is not evidence of human approval:
existing synthetic cases retain their review status.

The versioned binding registry is
[`config/langfuse-evaluation-bindings.json`](../config/langfuse-evaluation-bindings.json).
Each dataset has an explicit target, prompt dependencies, applicable metrics,
status, ID and source-item lineage. `scripts/check_langfuse_evaluation_bindings.py`
rejects missing prompts, misplaced dataset paths, incomplete splits, judge
self-evaluation and overlapping online rules. It runs with `make prompt-check`.
New datasets require a binding before hosted judging is enabled.

## Workflow and deterministic tests

The former `memoir-workflows/integration/core` is
`memoir/workflows/source-to-private-draft/golden/core`: testimony acceptance,
event extraction, progressive draft and source-withdrawal readback, in two
languages. It evaluates a workflow involving several prompts, not one prompt.
Composer checkpoint and story-game adaptation suites likewise name their actual
workflow. Each experiment's prompt manifest records the exact executed components,
numeric versions and hashes; registry dependencies describe the permitted set.

Place grouping and admission checks are deterministic. Their bindings declare
the validator and no evaluated model prompt. They do not receive text quality
judges. Workflow trajectory judges and deterministic acceptance remain separate
from single-output quality scores.

## Preserving history during splits

The redesign retains all 36 source dataset IDs, all 436 source items (including
the four synthetic judge wiring cases) and their experiment associations. Seven
mixed datasets remain as clearly described historical batch records; their
59 target-specific child datasets copy the original inputs, expected outputs,
source observation references and metadata with explicit source-dataset/item
lineage. The originals are excluded from new judging. No old experiment is
rewritten as a new single-target experiment.

All 97 managed prompts are retained, with 86 moved to the canonical paths.
Prompt text, version IDs, numeric versions and historical observation links are
preserved. Judge prompts use `memoir/evaluators/...`; diagnostic test inputs use
`memoir/probes/...`. `memoir/evaluation` is retired as a current prompt namespace.
Physical source Markdown stays with its owning application or skill.

## Published judges

Four independent LLM evaluators use the same names as their judge prompts:
`memoir/evaluators/shared/{correctness,relevance,completeness,safety}`. Each returns
0 to 1, with 1 favorable. Evaluator descriptions point to their exact prompt pin
and binding registry. Target-specific rules identify the dataset or online flow.
The four existing CODE evaluators retain their implementations and inactive
state; their canonical names identify the target and semantic metric.

Correctness maps `expected_output` to `experimentItemExpectedOutput`. Dataset
experiments must use the SDK `run_experiment` path; the legacy run-item association
alone does not populate that reference on v4 observations. Four earlier synthetic
checks verified wiring, including reference rendering, not human calibration.

Live Langfuse metadata and rules are migrated separately from application
deployment. Application changes are committed on `codex/langfuse-taxonomy`;
the shared API and workers are not restarted by this migration.

## Verification — target-first migration

`make prompt-check` passed all 97 exact published prompt pins and the 58-target,
95-dataset, 25-online-rule binding checks. Prompt synchronization created zero
new versions; all 183 original prompt version records remain intact.
The focused naming, prompt, evaluator, agent, speech and game checks passed
298 tests, with one known controlled-CLI fixture check deselected.

The final `MEMOIR_TEST_POSTGRES_BACKEND=apple-container make test-place-research`
completed successfully: 738 web checks, 814 API/database checks and 96 standalone
photo-skill checks passed. This includes both standalone photo callers updated
for the renamed discovery prompt.

A broader legacy evaluation run still exposes pre-existing fixture failures:
the profile case builder contains the removed `childhood_place` field, and the
controlled positive-delivery CLI fixture reports incomplete. The profile case
builder is unchanged from baseline `bb65c7d8`. These are not claimed as passing;
this change does not alter the profile contract or publication guards.

Live readback verified all 95 dataset names, 97 prompt names, eight evaluator
names, 64 enabled target-specific rules and four retained inactive CODE rules.
All enabled rules are NEW-only; no historical backfill was requested. Non-text
suite descriptions identify their validator, SDK workflow judge or calibration
purpose rather than a hosted text-quality rule.

The [migration receipt](langfuse-target-migration-20261104.json) preserves the
36 original dataset IDs, 436 source items and all 46 existing experiment IDs;
59 child datasets contain 126 copies with explicit source lineage. The private
full-content backup is not committed. Other checkouts should use the updated
catalog before prompt synchronization so they do not recreate retired names.
