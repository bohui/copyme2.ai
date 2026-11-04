# Calibrate judges, then evaluate agents and skills

Calibration checks the grader against fixed answers. Agent/skill evaluation
checks the generated work. The fifty-round command tests a complete conversation
through the application; it is a different, longer test.

```sh
# Plans: no credentials, writes or model calls.
make llm_judge_calibrate_plan
make memoir-agent-eval-plan EVAL_AGENT=mira
make memoir-agent-eval-plan EVAL_SKILL=memoir-author-timeline
make prompt-eval-all-plan

# Run development first; diagnose disagreements before opening holdout results.
make llm_judge_calibrate JUDGE_SPLIT=development
make llm_judge_calibrate JUDGE_SPLIT=holdout

# Later regression runs can check both splits together.
make llm_judge_calibrate

# Evaluate the current Mira or Atlas agent, or one skill.
make memoir-agent-eval EVAL_AGENT=mira
make memoir-agent-eval EVAL_AGENT=atlas
make memoir-agent-eval EVAL_SKILL=memoir-author-timeline

# Run the complete supported scenario catalog and publish all prompt coverage.
make prompt-eval-all
```

These host commands use the existing gateway at `http://127.0.0.1:4000/v1`.
Override `EVAL_GATEWAY_URL` when necessary. Model/key settings come from `ENV_FILE`
(default `.env`); Langfuse credentials come from `PROMPT_CREDENTIAL_FILE`.
`AGENT_EVAL_ARGS='--full'` extends a selected agent/skill run. Calibration accepts
`JUDGE_EVAL_ARGS='--judge correctness'` for diagnosis; a selected judge run alone
does not satisfy the all-prompt prerequisite.
Each call has a recorded 180-second default timeout, capped at 240 seconds;
`JUDGE_EVAL_ARGS='--timeout 240'` changes that bound explicitly. No automatic
model retry hides a failed attempt.

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
