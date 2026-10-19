# Dataset and evaluator design for every Memoir skill

Status: proposed design for review, 19 October 2026. The judge templates in
[evaluation-design/skill-judge-prompts.md](evaluation-design/skill-judge-prompts.md)
are drafts. This document does not register evaluators, publish prompts, or run
models. Scenario counts below are design targets, not executed coverage.

## What exists and why it looks incomplete

Read-only requests to the existing `memior` project
(`cmut9t75w00071z02n8bdv7it`) returned Langfuse 4.21.0, 12 datasets, 70 prompt
entries, four managed code evaluators, and four inactive experiment rules.
The source audit started at commit `11473012` on `fix-photo`.
There were no managed LLM-as-a-judge evaluators. Four judge prompt components
already exist: `five-case-judge`, its `guard`, and `trajectory-judge/system` and
`trajectory-judge/rubric`, all under `memoir/evaluation/`, with versions 1 and 2.
Having a prompt does not connect it to an evaluator or evaluation rule.

The current skill runner uses Python callbacks passed to `run_experiment` to
write `contract_pass` or `availability` scores. It does not create managed
evaluators. Its nine trigger groups and 19 delivery probes therefore do not
appear as nine skill evaluators in the Evaluators screen. The four visible code
evaluators belong to the older event-grounding, temporal-placement,
chapter-continuity, and bilingual-consistency suite.

`memoir/evaluation/v2/skill-triggers` and `.../skill-deliveries` were introduced
to preserve the original datasets and experiments when game integration and
prompt-bearing cases changed. Both generations retain nine groups and 19
probes, with different content hashes. The publisher rejects different content
at an existing name with `dataset_content_conflict`; the separate names avoided
that conflict. The [retained report](skill-trigger-delivery-evaluation-20261018.md#follow-up-after-game-integration)
records the transition. `v2` here is a manually chosen folder name.

The zero experiment counts visible beside some datasets are not a complete
execution audit. The retained report records separate SDK experiments against
specific dataset generations; verify those through experiment/item readbacks.

Future revisions should use stable dataset names, stable case IDs, Git review,
and timestamp-pinned [Langfuse dataset versions](https://langfuse.com/docs/evaluation/experiments/datasets).
Every experiment records its dataset snapshot, exact item IDs/hashes, source
commit, application prompt pins, evaluator versions, and judge prompt pins.
Dataset schema changes require an explicit compatibility migration because item
versioning does not version the dataset schema. Keep the historical datasets
and scores intact; do not rename, delete, or relabel old experiments.
New item IDs derive from skill, case identity and locale, rather than mutable
prompt/input content. The current `item_id()` hashes the entire row; replace
that behavior for the new datasets. The publisher should preflight reviewed
item diffs, update the same IDs, archive retired items, and read back the pinned
snapshot. An uncertain write outcome requires inspection before retrying.

## Coverage inventory

Use the union of `apps/api/background_skills.py::SKILLS` and owners under
`memoir/skills/` in `apps/api/prompt_catalog.py`. At this checkout the union is
ten skills. Comparing only `skills/*/SKILL.md` misses the foreground interviewer,
which has a prompt directory but no `SKILL.md`.

| Skill | Execution to evaluate | Current gap |
| --- | --- | --- |
| `memoir-interviewer` | Foreground reply, immediate question selection, background strategy planning | Absent from the nine-skill suite |
| `memoir-author-timeline` | Grounded event extraction, reconciliation, publication | Live probes cover only two small positive inputs |
| `memoir-composer` | Prepare, compose, review, progressive checkpoints | Two isolated pipelines; independent editorial judging missing |
| `memoir-family-tree` | Person/relationship proposals, graph validation, entitlement | Isolated positive output exists; canonical runner is `unwired` |
| `memoir-memory-context` | Profile proposals plus host cadence and manual field locks | Seven isolated cases; live saved-effect evidence is separate |
| `memoir-place-journey` | Place extraction embedded in the timeline pass | One live two-place case; more ambiguity and correction cases needed |
| `memoir-place-groups` | Actual deterministic grouping, labels, independent map pins | Live instruction quiz is not the production execution path |
| `memoir-place-photo-research` | Configured discovery providers, inspection, ranking, fallback, pagination | Native-search-only probe misses current parallel CSE/SerpAPI behavior |
| `memoir-historical-news-research` | Public discovery, source verification, scoped delivery | Native discovery success has not established verified delivery |
| `memoir-story-game` | Authorized proposal, validation, review, private delivery and play | Live skill probe only checks missing-authority rejection |

A missing dataset, case family, adapter, or judge mapping must fail the coverage
preflight. An unavailable production runner must stay visible in the denominator;
its rejection cases can pass while its positive delivery remains unavailable.

## Stable Langfuse structure

Create one dataset per row above, named
`memoir/evaluation/skills/<full-skill-name>`. For example:

```text
memoir/evaluation/skills/memoir-interviewer
memoir/evaluation/skills/memoir-composer
memoir/evaluation/skills/memoir-place-photo-research
```

Add two shared datasets:

- `memoir/evaluation/workflows`: multi-skill conversations and saved/UI outcomes.
- `memoir/evaluation/judge-calibration`: reviewed good, bad, borderline, and
  insufficient-evidence outputs, separate from the skill regression holdout.

Each skill gets two visible managed evaluator definitions:

- `memoir/evaluators/<full-skill-name>/contract`: deterministic assertions and
  execution availability, sharing the repository's validators.
- `memoir/evaluators/<full-skill-name>/quality`: LLM judge using the common policy
  and that skill's rubric, with categorical `pass`, `partial`, `fail`,
  `unavailable`, and `not_applicable` results and an evidence-based explanation.

This gives ten skill datasets and 20 named skill evaluators. Shared workflow
and calibration datasets have their own evaluation tasks; they do not expand
the count of product skills. Names, schemas, cases, rubrics, variable mappings,
and rules belong in a reviewed repository manifest. Numeric versions and hashes
belong in receipts, rather than new `v3` folders or issue/date names.

## Dataset item and execution contract

Keep model input separate from gold expectations and host-owned authority.
Dataset inputs describe the application task; the runner builds the exact
production packet and composed prompts. Do not embed a copied application
prompt in every dataset row.

```json
{
  "id": "interviewer-pause-zh-CN",
  "input": {
    "task": "Continue the current interview turn.",
    "locale": "zh-CN",
    "narrator_message": "今天先到这里。",
    "history": [],
    "saved_context": {}
  },
  "expected_output": {
    "action": "pause",
    "required": ["acknowledge the pause", "no follow-up question"],
    "forbidden": ["new question", "invented personal fact", "private plan in reply"],
    "required_witnesses": ["validated reply", "delivered turn receipt"]
  },
  "metadata": {
    "skill": "memoir-interviewer",
    "case_family": "pause",
    "case_kind": "negative",
    "execution_scope": "application_delivery",
    "pair_id": "interviewer-pause",
    "split": "regression",
    "synthetic": true,
    "contains_customer_data": false
  }
}
```

The model receives only the production packet derived from `input`. The task
adapter receives the host fixture; validators and judges also receive
`expected_output`. Expectations are reviewed invariants and evidence, not a
mandatory prose string. Never pass expected answers, assertions, judge rubrics,
or calibration labels to the skill under test.

Record the attempted scope separately from observed evidence: `controlled`,
`isolated_live`, `application_live`, or `browser_live`. Host fixture permissions
apply only to fictional identities in disposable evaluation state. A dataset
expectation cannot grant permission on a real account or game.

Execution output contains the actual artifact, deterministic findings, completed
provider response IDs and model identity when returned, source/version evidence,
scoped database readbacks, and browser witnesses where required. Reference every
witness by a stable ID and content hash. A judge receives the bounded witness
content needed for its criteria, not merely paths or hashes it cannot inspect.
Over-budget evidence stays unjudged rather than being silently truncated.

An isolated response can satisfy an isolated contract case. An application
delivery case also needs successful scoped persistence/readback; a browser case
needs the claimed rendering, interaction, and reload witnesses. A deterministic
skill must run its actual code, with zero production model dispatches. An LLM
judge may assess its visible labels or explanation in a separate evaluation call.

## Initial case families for all ten skills

Author eight scenario families for each skill, each in `en-AU` and `zh-CN`:
80 families and 160 localized items. This is an initial design target. Every
family declares its expected action, assertions, required witnesses, execution
scope, and which quality criteria apply. Some families are controlled race or
authorization tests; they do not all need a live generation.

| Skill | Eight required families |
| --- | --- |
| `memoir-interviewer` | Comfort entry; Explore follows the last memory; Shape clarifies supported order; pause/direct answer; redirect/correction overrides a prepared question; stale/reused candidate; photo-only input without invented testimony; quoted instructions and language preference |
| `memoir-author-timeline` | Explicit grounded event; acknowledgement/leading question creates none; multiple versus recurring events; approximate date/age basis; conflicting account and explicit correction; linked event versus unrelated person; edited/withdrawn source; replay and cross-project identity |
| `memoir-composer` | First grounded checkpoint; rounds 5→10→15 preserve unchanged passages; empty checkpoint; new source changes only supported prose; correction/withdrawal; coherent chapters without invented causes; English/Chinese fact equivalence; bounded batching, review failure, and resume |
| `memoir-family-tree` | Explicit mother and introduction; unnamed/uncertain relative; same-name distinct people; relationship direction and spouse/parent links; non-relative/book character; correction without identity duplication; entitlement/owner denial; canonical save/reload or explicit `unwired` result |
| `memoir-memory-context` | Explicit narrator fields; current residence versus childhood place; relative/quoted speaker exclusion; manual value and manual blank locks; narrator correction; ambiguous avatar/date; stopped/empty targets; host 1/5/10/20 cadence, coalescing, replay and readback |
| `memoir-place-journey` | Two cities in a move; multiple visits/periods; unnamed river or unsupported place; explicit uncertainty; Chengde alias versus Beijing palace; corrected place/source withdrawal; period derivation and unknown boundaries; shared timeline pass, scoped publication and reload |
| `memoir-place-groups` | City with suburb; two separate cities; same name with conflicting regions; incomplete/localized hierarchy; child without coordinates; parent coordinates never become a child pin; owner/stale response rejection; stable grouping and independent album selection after reload |
| `memoir-place-photo-research` | Explicit memory period and verified aliases; direct request without a period defaults current; capture date versus upload date; location/year ranking and labelled relaxed matches; empty-result fallback versus blocked provider; parallel provider success/failure and cache; pagination/deduplication/owner scope; item rights, attribution and verified display |
| `memoir-historical-news-research` | Verified public event; unsupported lead rejected; public time/place query without private narrator identity; wrong place/date or conflicting claim; multiple native calls with source-to-call binding; inspect failure/timeout; setting-off, after-reply scheduling and lease release; cache/replay and contextual use without personal-testimony promotion |
| `memoir-story-game` | Valid synthetic completed edition and proposal; missing completion/consent/Shape delivery; stale edition/source or revoked consent; invented scene/dialogue rejected; exact candidate review and person permissions; replay/busy job; private publication/readback; real browser interaction and reload |

Reuse the existing semantic fixtures, production prompt builders, validators,
and trigger tests where they express these families. Split grouped pytest runs
into inspectable cases or child evidence so one green group cannot hide which
behaviors ran. Add stable regression items for real failures, including repeated
JSON documents, the omitted interviewer, photo ranking/fallback, and missing
native receipts.

The two language variants share facts and uncertainty; wording may differ.
Pair checks compare accepted facts and outcomes, not exact translations.
Representative scenarios are seeds for concrete fixtures, not substitutes for
writing their input, gold constraints and witnesses before publication.

## Contract checks and LLM judges

Code owns exact schemas, original quotation offsets, IDs, versions, entitlement,
source availability, provider/search receipts, rights flags, persisted revisions,
counts, budgets, replay and UI assertions. Reuse production parsing and add
independent gold checks for omission or factual errors the parser cannot detect.
Neither the evaluated skill's self-review nor its output may manufacture the
host evidence consumed by a validator.

The independent LLM judge assesses meaning: grounded acknowledgement, useful
questions, correct attribution, preserved uncertainty, narrative coherence,
research relevance, and equivalent facts across languages. The
[draft prompts](evaluation-design/skill-judge-prompts.md) define all ten rubrics.
The judge cannot browse, invoke product tools, repair output, or certify evidence
it was not given. A critical unsupported claim makes the semantic verdict fail;
absent evidence makes the relevant judgment unavailable. Judge provider errors
and malformed judge responses remain unavailable and retain their call receipts.

Report separate columns per skill and locale:

| Result | Meaning |
| --- | --- |
| Contract | Passed/failed assertions against the expected action |
| Execution | Completed, correctly skipped, unavailable, failed, or not run |
| Positive delivery | Required artifact and witnesses observed, or missing |
| Quality | Judge category and cited evidence, or unavailable/not applicable |
| Calibration | Human-reviewed judge agreement, or pending |

A correct refusal is a successful negative case; it contributes nothing to the
positive delivery numerator. A timeout or unwired runner never becomes a pass
because a judge likes the prose. If an expected delivery is missing, the case
cannot pass even when the refusal wording is good. Report positive-case totals,
unavailable counts, and judgment coverage alongside pass rates. Keep every
planned item in the report, including items not dispatched due to budget limits.

## Connecting the design to the Langfuse UI

Use managed evaluators so all ten skills are discoverable on the Evaluators
page. The repository runner still owns fixtures, production adapters, independent
assertions and evidence collection. Hosted contract code verifies its scoped
receipt against the actual item input/output hashes and emits those code scores;
it must not trust an unbound `status: passed` supplied in model output.

Publish a common judge policy and ten composed skill judge prompts under
`memoir/evaluation/judges/...`. A managed evaluator stores the compiled prompt
text; its publication receipt binds that text to the exact reviewed prompt
versions and hash. Prompt registration alone does not update an evaluator.
Updating prompts requires checking and, when changed, publishing the matching
evaluator definition too. Record its version with every resulting score.

For the deployed 4.21.0 API, evaluator definitions and rule assignments are
separate resources. Definitions hold the prompt/output/model; rules select the
experiment dataset. Use each returned dataset ID, and map the three judge
variables `input`, `output`, and `expected_output` to their corresponding
experiment fields. Verify model connectivity and every mapping before enabling
an experiment rule. See the tagged
[evaluator contract](https://github.com/langfuse/langfuse/blob/v4.21.0/fern/apis/server/definition/unstable/evaluators.yml)
and [mapping/output contract](https://github.com/langfuse/langfuse/blob/v4.21.0/fern/apis/server/definition/unstable/commons.yml).

Choose one judge executor for each run. With managed experiment rules enabled,
the SDK callback writes contract/execution scores and waits for the managed
judge's readback; it does not send a duplicate judge call. An SDK judge fallback
requires those managed rules disabled and records `judge_executor=sdk`. Use
idempotent score identities and check existing results before retrying.

Use an explicit existing project model connection for the judge. Pin its model,
reasoning configuration where supported, prompt versions and evaluator version;
log actual response/model/usage fields when available. Separate skill and judge
dispatch/token/time budgets. Count failed dispatches, and preflight planned
composer phases and repairs rather than assuming one call per dataset item.
No model call is needed to generate the plan or validate inventory coverage.

Start with rules disabled, then enable only the synthetic experiment datasets
after fixture and model preflight. Keep routine application observations outside
these rules. Changes create new evaluator versions; verify the enabled rule's
resolved version before and after a run to detect configuration drift. A score
readback must match the expected item, evaluator, prompt and source snapshot.

## Calibration, migration and completion

Seed each skill's judge calibration set with at least six reviewed examples per
language: two good, two bad, one borderline and one insufficient-evidence output.
That is 120 proposed calibration items across ten skills, separate from the
160 task items. Include deliberately fluent hallucinations, correct refusals,
injection attempts inside evidence, and missing witnesses. Do not fabricate a
reviewer's identity, approval or accepted gold label.

Split calibration development and held-out validation; use independent human
labels, check disagreements by skill/language, and test that adding fluent but
unsupported detail cannot improve the verdict. Proposed initial acceptance is
zero false passes on critical violations plus at least 90% agreement on held-out
categories. These targets require human review and are not statistical proof
from a small sample. Until accepted calibration exists, publish judge results
as advisory and keep deterministic acceptance separate.

Implementation order:

1. Review this inventory, case families and judge drafts. Add one manifest and
   coverage preflight against the runtime registry plus prompt owners.
2. Author concrete fixtures and adapters for the ten datasets. Preserve existing
   datasets/experiments and link migrated cases to their old IDs and snapshots.
3. Register the shared judge policy and ten composed prompts in the normal
   prompt catalog. Review and merge Markdown to `main`, publish with
   `make prompt-sync`, then review/commit generated receipts. Never invent pins.
4. Publish and read back the new datasets, 20 evaluator definitions and initially
   disabled rules. Verify the actual code dispatcher and configured judge model.
5. Run bounded skill and judge experiments, then workflow cases through saved
   readbacks/browser witnesses. Run `make test-place-research` when implementing
   photo/place/localization evaluation changes.
6. Produce a ten-row coverage report with per-language results, skill and judge
   calls, dataset/prompt/evaluator versions, unavailable reasons, and calibration
   status. Explicitly retain family-tree's missing canonical runner until it is
   implemented in a separate product change.

The design is complete when every skill has a dataset specification, positive
and negative cases, a production adapter definition, contract checks, a judge
rubric, and named evidence requirements. Implementation is complete only after
the corresponding artifacts exist and their results are read back. Dataset
presence, prompt presence and a successful negative probe are different forms
of coverage and must remain distinguishable in that report.
