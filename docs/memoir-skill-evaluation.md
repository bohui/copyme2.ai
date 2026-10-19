# Running the ten-skill evaluation suite

Spec: [GitHub #90](https://github.com/bohui/copyme2.ai/issues/90).
See the [full design](memoir-skill-evaluation-design.md) for the intended case
families, delivery witnesses, and calibration requirements.

## Current implementation

The existing evaluation CLI now discovers background skills and foreground
prompt owners together. Its initial catalog has ten stable skill datasets and
45 executable items: ten controlled trigger groups and 35 delivery/contract
items. Sixteen new interviewer items cover eight scenarios in both English and
Chinese. Other existing cases retain their actual locale and scope; this is
not yet the complete 160-item bilingual target.

Each skill has a planned contract and quality evaluator name. Managed evaluator
and rule publication is still pending. Current execution writes SDK contract
scores and optional independent SDK judge scores. Historical and v2 datasets
are left intact.

## Plan and select cases

These commands read local sources and make zero model or Langfuse calls:

```sh
python3 scripts/run_memoir_skill_evaluation.py
python3 scripts/run_memoir_skill_evaluation.py --skill memoir-interviewer --locale zh-CN
python3 scripts/run_memoir_skill_evaluation.py --phase deliveries --case interviewer-pause-en-AU
```

The JSON plan includes selected cases, stable dataset names, twenty evaluator
definitions to implement/publish, judge prompt hashes/publication state, and
separate skill/judge call limits. `--phase triggers` selects controlled
application checks; `--phase deliveries` selects actual deterministic execution,
isolated model contracts, composer pipelines and native discovery probes.

## Execute contract checks

Execution uses the existing Memoir Langfuse credentials and gateway configuration.
It creates missing new skill datasets and verifies their exact items before
dispatch. A selected subset still synchronizes the full local dataset for each
selected skill, so a scoped rerun cannot accidentally archive other local cases.

```sh
python3 scripts/run_memoir_skill_evaluation.py --execute --phase triggers
python3 scripts/run_memoir_skill_evaluation.py --execute --phase deliveries \
  --skill memoir-interviewer --case interviewer-pause-en-AU
```

The default `--judge off` reports contract checks only. It does not claim quality
or calibrated acceptance. Deterministic grouping executes production grouping
and validates explicit expected city/pin counts without a skill model request.
An isolated response is labelled `isolated_output`; a correct negative result
is `correct_skip`. Neither label asserts canonical persistence or UI delivery.

## Enable an independent judge

The shared policy and ten rubric sources are under
`tests/evaluation/prompts/skill-judges/`. They are staged evaluation prompts in
the publication catalog. Merge reviewed source to `main`, run `make prompt-sync`,
review/commit the generated receipts, and run `make prompt-check`. No receipt
or published version is invented on the feature branch. Missing/invalid judge
pins stop judged execution before contacting services or dispatching a model.

After those pins exist:

```sh
python3 scripts/run_memoir_skill_evaluation.py --execute --phase deliveries \
  --skill memoir-interviewer --case interviewer-pause-en-AU \
  --judge sdk --judge-model EXISTING_GATEWAY_MODEL \
  --max-calls 1 --max-judge-calls 1
```

The judge is a separate request and generation observation. It receives the
reviewed target and actual bounded evidence, which remain withheld from the
skill request. Pass/partial/fail verdicts need evidence citations. Malformed
responses, missing evidence and exhausted judge budgets stay unavailable. Prompt
components and the compiled prompt hash are attached to the result. All current
judge scores are advisory with calibration pending. Managed judging is not yet
enabled, so this executor cannot duplicate an active managed judge run.

## Dataset revisions and results

Case IDs depend on stable identity rather than content. Changed or retired
hosted items fail preflight by default. After reviewing the local plan, pass
`--update-datasets` with `--execute` to upsert the same IDs and archive retired
items in the selected skill datasets. Publication preflights every selected
dataset before writing, and readback checks the timestamp-pinned active items.
It never deletes historical experiments or edits the old v2 datasets.

Receipts and reports are written under `var/skill-evaluation/` by default.
Reports separate contract results, observed execution, delivery scope and
advisory quality. Every selected planned item remains present when its budget
is exhausted. Experiment verification checks item/dataset identity, input,
expected output, actual output and both score values; an unrelated score is
insufficient. Client dispatches are bounded; opaque gateway retries and monetary
cost remain unknown. Composer pipelines can use several calls per item, so a
large selection may need an explicitly larger reviewed call limit or stay
incomplete at the existing limit.

Remaining work in #90 includes the full 160-item case set, concrete workflow and
calibration datasets, managed evaluator/rule publication, expanded research/game
delivery adapters and live/human-calibrated acceptance. Family-tree's canonical
runner remains unwired and is reported unavailable independently of proposal
quality.
