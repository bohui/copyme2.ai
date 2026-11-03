# Current agents and skills evaluation

`scripts/run_memoir_agent_evaluation.py` runs a bounded synthetic baseline of
the current Memoir agents and skill contracts. It extends the existing scenario
catalog, native skill agent, production validators, progressive composer and
Langfuse SDK experiment helpers. It creates no narrator account or canonical
memoir records.

The compact campaign contains 88 cases:

| Area | Coverage | Evidence |
| --- | --- | --- |
| Lane A | 28 English/Chinese reply, stop, correction, caption, injection, emotional-boundary and background-hint cases | Current production instructions, native message projection, reply schema and validator; real gateway output |
| Lane B | 14 English/Chinese source selection, empty-work and dependency cases | Real Codex app-server tool loop; production `SkillTools` and `BackgroundSkills`; disposable host domain operations |
| Skills | 46 cases across the nine current skill packages | Exact source spans, profile manual authority, uncertainty, geographic grounding, deterministic city grouping, live progressive composition and native public research |

Family-tree remains unwired. Full game generation/publication requires a separate
authorized application/browser workflow. Their unavailable rows receive no
numeric contract passing credit. The retired interview-guidance package is an
embedded legacy dependency, not another standalone current agent.

## Run and inspect

```sh
# No credentials, model calls, dataset writes or deployment.
make memoir-agent-eval-plan

# Existing local host gateway; publish three SDK experiments in Memoir Langfuse.
make memoir-agent-eval \
  AGENT_EVAL_ARGS='--gateway-url http://127.0.0.1:4000/v1 --timeout 150'

# Repeat a difficult native selection case without relaunching every workflow.
python3 scripts/run_memoir_agent_evaluation.py --execute --publish \
  --gateway-url http://127.0.0.1:4000/v1 \
  --case lane-b/residence/en-AU --repeat 3 --max-native-runs 3 \
  --judge-cases 0 --seconds 300

# Extended fixture inventory, still subject to the explicit run limits.
python3 scripts/run_memoir_agent_evaluation.py --full

# Regrade the exact retained Lane A outputs after an evaluator correction.
# No model or advisory judge is dispatched; the original experiment is retained.
python3 scripts/run_memoir_agent_evaluation.py --execute --publish \
  --component lane-a --replay-receipt var/agent-evaluation/<run>/receipt.json
```

The default limits are 128 direct HTTP calls, 16 native runs, 32 dynamic tool
calls per native run, 120 seconds per case and 30 minutes for the campaign.
Advisory judges consume the same direct HTTP allowance. Failed dispatches count;
the runner adds no direct transport retry. Native provider calls, gateway retries
and monetary spend are not established by these counters. `--repeat` shares the
campaign limits, so increase bounds deliberately when repeating the full catalog.
The CLI returns nonzero when cases fail, capabilities are unavailable or hosted
verification stays pending. Inspect the saved receipt before deciding to rerun.

Receipts, actual model outputs, source inspections, a Markdown report and an
unlabelled human review worksheet live in `var/agent-evaluation/<run>/`. Receipts
record exact dataset/input/gold hashes, prompt pins, implementation hashes,
working diff hash, requested/served model identities, available token usage,
case timing and experiment IDs. Dataset names include content hashes so a
changed task or expectation creates a distinct retained benchmark.

Publication verifies exact hosted dataset contents before execution. Each
experiment is read back through Langfuse v4, including pagination and every
input, expected result, actual output and externally computed score. Missing
scores stay pending; conflicting evidence fails verification. Experiment IDs are
saved before readback so a read failure never requires another model invocation.

## Interpret the scores

`execution_available` describes whether a case was evaluable. `contract_pass`
requires the applicable independent code checks to pass. Named checks expose
skill selection, dependency order, reading before execution, narrator control
and source/schema validation separately. Latency measures the case before its
optional advisory judge. A correct exclusion is different from positive artifact
delivery. Every row explicitly withholds canonical/UI delivery certification.

The runner selects up to 12 cases with observed outputs across components and skills for semantic review
using the existing pinned trajectory judge prompts. The current configured
model also serves as judge. These scores are named `advisory.*`, require bounded
known categories and evidence comments, and never override a code failure or
unavailable capability. Same-model bias and missing human calibration remain
explicit. `--judge-cases 0` disables them.

The human worksheet has separate development/holdout assignments with empty
labels. Bilingual variants of the same scenario stay in the same split. The
worksheet supplies task, gold and actual output while withholding model identity
and advisory scores. No generated label is presented as human review. Before using semantic
thresholds as a release gate, have domain reviewers independently label examples,
resolve disagreements and measure judge agreement on the held-out split.
Do not tune against that holdout. Repeat cases to measure variation, and preserve
failed runs and changed evaluator definitions when investigating false positives.

The Langfuse **Datasets/Experiments and Scores** views contain these results.
The Evaluators tab in the screenshot lists hosted evaluator templates/rules;
tracing or running external SDK evaluators does not activate those legacy rules.
This runner explicitly supplies its judge model and does not require a project
default LLM judge. No background scoring of all production traces is enabled.

## Verification and remaining coverage

The evaluator tests deliberately feed wrong tool selections, wrong dependency
orders, missing skill reads, missing hosted items/scores, altered inputs/gold/
outputs, unavailable execution and unsupported judge scores. They verify that
an advisory success cannot turn a deterministic failure into passing credit.

The fixed fixtures cover the current profile fields and manual authority; they
no longer request the removed `childhood_place` or infer avatar artwork from
gender. Legacy schema probes also use the current required confidence/research
fields and no longer emit the removed prepared-question field.

Live privacy-review classification, saved two-lane handoff, retries, revocation,
UI footprint/camera behavior and game play need application/SQL/browser evidence
in addition to proposal scoring. Use the existing controlled application and
PostgreSQL/browser regression suites for those boundaries. A live prompt output
cannot establish that an artifact reached the UI.

This design follows the task-specific datasets, representative/edge/adversarial
coverage, separate deterministic and semantic metrics, repeated runs, human
calibration and trace/artifact inspection described in the official
[OpenAI evaluation guidance](https://developers.openai.com/api/docs/guides/evaluation-best-practices),
[skill evaluation guide](https://developers.openai.com/blog/eval-skills) and
[Langfuse SDK experiment guide](https://langfuse.com/docs/evaluation/experiments/experiments-via-sdk).
