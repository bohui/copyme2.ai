# Langfuse naming

`Trace Name` identifies the agent or workflow for one run. `Name` identifies an
observation (a model call, tool call or other step) within that run. A trace ID
groups its observations; reusing a trace name does not merge runs. Sessions link
related runs. Mira and Atlas use the same pseudonymous owner/project session ID;
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

Nested skill observations retain their skill-specific names and inherit the
coordinator's trace name. For example, `memoir-composer.review` normally appears
under `memoir-atlas`. A directly invoked skill can have its own trace root.
Evaluation worker runs prefix both levels with `evaluation/`. The generic worker
fallback is `memoir-skill-agent.run`; its tool steps follow the Atlas convention.
The existing conditional guidance lane retains `memoir-interview-guidance.guidance`
until that separate workflow is retired. These labels describe instrumentation;
they do not imply that every skill has a live standalone model path.

Historical traces keep their recorded names. Only new observations use changed
labels. Speech and image observations contain bounded summaries rather than full
text or media, so textual online quality judges exclude these observations.

## Datasets

Dataset names follow `memoir/<category>/<owner>/<task>/<suite>`. The final segment
is a dataset; earlier segments appear as folders in Langfuse.

| Category | Purpose | Example |
| --- | --- | --- |
| `golden` | Reference regression cases; preserve each suite's review status | `memoir/golden/memoir-mira/reply/core` |
| `safety` | Privacy, consent and harmful-output cases | `memoir/safety/memoir-mira/reply/privacy` |
| `relevance` | Topic changes, redirects and concise replies | `memoir/relevance/memoir-mira/reply/redirects` |
| `stress` | Long contexts, repeated updates and difficult inputs | `memoir/stress/memoir-atlas/skill-selection/long-context` |
| `calibration` | Compare judge results against reviewed human labels | `memoir/calibration/memoir-judges/quality/core` |

Moving a suite into `golden` does not grant human approval to its existing labels.
Dataset items retain their metadata, including any pending review status.
Safety, relevance and stress are supported categories; create their datasets when
there are corresponding cases. Do not create empty placeholder suites.

The 4 November 2026 migration renamed 35 datasets in place, preserving all 432
items and 45 experiment links. No dataset was deleted. Historical v2, dated and
campaign suites use distinct leaf names to avoid collisions. The old
`memoir/evaluation`, `memoir/archive` and `memoir/issue6` dataset folders disappear
because no dataset retains those prefixes. Prompt names are an independent
namespace and may still contain `evaluation`.

The classifier and producers share `scripts/langfuse_dataset_names.py` so normal
publication does not recreate the retired dataset prefixes.

## Quality judges

Four independent LLM evaluators use versioned prompts under `memoir/evaluators/`.
Each returns a score from 0 to 1 with its own reasoning; 1 is the favorable score
for every dimension, including safety.

| Judge | Variables | Scope |
| --- | --- | --- |
| Correctness | `expected_output`, `output` | Dataset experiment roots with a reference answer or constraints |
| Relevance | `input`, `output` | Dataset experiments and 10% of eligible live text generations |
| Completeness | `input`, `output` | Dataset experiments and the same 10% live sample |
| Safety | `input`, `output` | Dataset experiments and the same 10% live sample |

The online rule selects generation observations with production names beginning
`memoir-`, excluding speech and illustration summaries. `evaluation/` and `test/`
names do not match. Judges must not evaluate their own outputs. Experiment rules
are confined to explicitly selected datasets whose items have expected outputs;
new datasets require explicit inclusion after checking that contract. There is
no historical backfill. Judge scores are separate from deterministic validators
and do not certify human calibration.

Model, sampling and judge prompt names are recorded in
`config/langfuse-evaluators.json`. Published prompt receipts pin exact content;
evaluator receipts record the corresponding Langfuse evaluator and rule IDs.
