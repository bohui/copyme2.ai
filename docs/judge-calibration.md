# Calibrate judges and evaluate prompts

Use one evaluation command for a prompt or an entire skill. Dataset recipes and
graders come from the current target bindings and production scenario catalog;
you do not need to choose a dataset, evaluator, model or run flag separately.

```sh
# One prompt: graded production scenarios, published and read back in Langfuse.
make prompt-eval PROMPT_EVAL_NAME=memoir/agents/mira/reply

# All managed prompts owned by a skill; shared scenarios run once.
make prompt-eval SKILL_EVAL_NAME=author-timeline

# Preview either selection without credentials, writes or model calls.
make prompt-eval-plan PROMPT_EVAL_NAME=memoir/agents/mira/reply
make prompt-eval-plan SKILL_EVAL_NAME=author-timeline

# Shared judge calibration, or the complete supported prompt catalog.
make llm_judge_calibrate
make prompt-eval-all
```

For Atlas, use `PROMPT_EVAL_NAME=memoir/agents/atlas/skill-selection`. For one
profile prompt, use `PROMPT_EVAL_NAME=memoir/skills/memory-context/profile`.
A judge prompt such as `memoir/evaluators/shared/relevance` automatically uses
its applicable shared answer keys and agreement grader instead of generating
an ungraded response.

The managed Mira prompt name is `memoir/agents/mira/reply`, rather than the
shorthand `agent.mira.reply`. Its source is `apps/api/prompts/mira/system.md`.
Shared components still belong to the real assembled request.

A skill selection includes every owned name under `memoir/skills/<skill>/`.
It combines the relevant production scenario datasets, preserving their frozen
input/gold hashes. It does not claim that every conditional branch ran: each
requested prompt receives its own observed-version flag and scenario result.
An unexecuted current pin remains unavailable and makes the command nonzero,
even if a parent workflow passes. Unsupported standalone prompts fail with a
coverage-gap explanation rather than falling back to raw text generation.

Advanced filtering stays on the same command:

```sh
make prompt-eval PROMPT_EVAL_NAME=memoir/agents/mira/reply \
  PROMPT_EVAL_ARGS='--case lane-a/memoir-interviewer/grounded-question/en-AU'
```

The automatic runtime selection uses the extended catalog, up to 400 direct
HTTP calls and two hours, with 150 seconds per provider call and 600 seconds
per composer workflow. Advisory trajectory judgments remain distinct from
production contract grades. Judge calibration uses its recorded 180-second
call default, capped at 240 seconds. Limits and selected cases are visible in
the plan; `PROMPT_EVAL_ARGS` can narrow a selection or set explicit bounds.

Host commands use the existing gateway at `http://127.0.0.1:4000/v1`;
`EVAL_GATEWAY_URL` overrides it. Model/key settings come from `ENV_FILE`
(default `.env`), and Langfuse credentials from `PROMPT_CREDENTIAL_FILE`.
`memoir-agent-eval` and its plan target have been removed. The former raw
`prompt-eval` generation mode and manual dataset/model/run variables are retired.
The fifty-round command remains a separate full application conversation test.

The shared dataset has 80 fictional cases: 40 development and 40 holdout. Its
18 judge contracts consume all 21 managed evaluator prompt components and make
140 calls across both splits. Cases include supported answers, contradictions,
missing evidence, exclusions, prompt injection, public-history attribution,
partial deliverables, pairwise ordering and unobserved trajectory categories.
Inputs contain task evidence and factual references; answer-key grades and their
rationales stay outside the judge request. Code compares each judgment with its
answer key. Missing responses remain in the denominator.

These are agent-authored specification answer keys. They are **not independently
human-reviewed**. Passing them is a synthetic calibration regression result;
it does not establish human editorial agreement. Domain reviewers still need to
label a separate sample before semantic grades become release gates. Once a
holdout result has informed a change, use a new unseen holdout to measure
independent generalization; preserve the original results.
The existing split holds out Chinese variants of the same scenario families;
it measures a locale regression, not unseen-family generalization.

`prompt-eval-all` checks that every current judge pin has passing, read-back
calibration evidence before dispatching. It runs the 198-case extended agent and
skill catalog. Its per-prompt ledger credits only exact versions/hashes found in
actual executed request manifests, including native skill reads. Merely appearing
in a target binding does not earn credit. Missing conditional branches, the
unwired family runner, game delivery and media review remain explicit gaps.
The command returns nonzero for failures, unavailable coverage or pending hosted
verification. It saves results before reporting failure; inspect the receipt
before dispatching another run.
The full campaign allows 400 direct calls and two hours overall. A provider call
has 150 seconds; a multi-call composer workflow has 600 seconds. These are
separate limits. Completed phases do not make an unfinished workflow pass.

To refresh only the coverage ledger from retained outputs, without model calls:

```sh
make prompt-eval-all \
  PROMPT_EVAL_ARGS='--agent-receipt var/prompt-evaluation/<run>/agents/<campaign>/receipt.json'
```

After a selected skill recheck, append `--recheck-receipt <recheck>/receipt.json`
to those arguments. Rechecks must have identical input/gold hashes. The latest
recorded attempt owns each case, including failed or unavailable attempts;
original experiments remain intact.

## Langfuse views

The shared dataset is
`memoir/evaluators/shared/judge-calibration/calibration/shared-v2`.
Calibration runs appear as `evaluation/memoir-judges.calibration`; individual
generations identify the judge. Scores are `available/<judge>` and
`agreement/<judge>`, with the exact prompt manifest, response ID, synthetic label
origin and human-review status. Readback verifies inputs, gold, outputs, named
scores and score provenance, rather than counting score rows.

Agent/skill runs appear under each content-pinned target dataset. The all-prompt
coverage ledger appears as `evaluation/memoir-prompts.coverage`, with a row for
every retained prompt and links/IDs for its observed scenarios. Its
`current_pin_observed` score describes coverage. It is not a quality score.

Find these in **Datasets/Experiments, Scores and Tracing**. The Evaluators page
lists hosted templates and automation rules; SDK experiment evaluators do not
need an active background rule or a project-default judge. This workflow does
not enable automatic judging of all production traces.

Local receipts and raw synthetic judgments live in `var/judge-calibration/`;
full campaign receipts and reports live in `var/prompt-evaluation/`. Previous
placeholder dataset items are archived after the shared replacement is verified;
historical datasets and experiments remain available.

## Changes found during implementation

The five-case consumer required all seven rubric scores even though the prompt
instructs the judge to omit unobserved categories. It now accepts a validated,
evidenced subset and rejects unavailable verdicts carrying numeric scores.

The initial development run agreed on 67/70 judgments. Three disagreements
revealed ambiguous fixtures: a factual reference did not establish residence,
fictional-test wording reduced privacy severity, and an exact-output constraint
confounded relevance with completeness. The preserved `shared-v1` source and
run retain those results; `shared-v2` makes the evidence and requested constraints
explicit. Judge rubrics were not changed to fit a faulty answer key.

See the [4 November results and grading fixes](judge-calibration-20261104.md)
for original disagreements, exact current-pin results and held-out limitations.
