# Langfuse prompt structure and usage audit

Status: proposed structure, based on the 18 October 2026 repository and the local
`memior` Langfuse project. The five `memoir/issue6/20261008-v1/prompts/*` prompt
names have already been removed after confirming that their text is preserved as
version 1 of the corresponding stable names. The old Issue 6 datasets still
exist alongside their copied `memoir/evaluation/*` datasets.
`scripts/issue6_langfuse_publication.py` is a historical publisher and would
recreate the old names if deliberately run with `--apply`; routine export and
evaluation commands use the stable registry instead.

## Naming rule

Use stable names for **authored instruction components**, grouped by the job
that uses them. Langfuse's numeric versions record revisions. Release dates,
issue numbers, and another `prompts` path segment do not belong in names.

```text
memoir/
  interview/                       collector, conversation, browser fragments
  memory/                          extraction, profile, workspace task fragments
  composer/                        preparation, drafting, review task fragments
  research/                        historical discovery task fragments
  speech/                          speech instructions by locale
  skills/<skill>/instructions       each model-facing SKILL.md
  skills/<skill>/references/<name>  only references actually read by a model
  evaluation/                      judges and evaluation-only instructions
```

`<skill>` is the skill's stable name without a second `memoir-` prefix. Putting
the root skill at `instructions` avoids showing a folder and a prompt with the
same name at the same UI level. For example, the current
`memoir/skills/memoir-composer` becomes
`memoir/skills/composer/instructions`, and
`memoir/skills/memoir-composer/narrative-enrichment` becomes
`memoir/skills/composer/references/narrative-enrichment`.

Keep datasets at `memoir/evaluation/<suite>` and use Langfuse dataset versions
and experiment runs for history. The four `memoir/issue6/20261008-v1/*`
datasets are copied, item-for-item, to that stable folder; retire the old names
only after confirming their experiment/run history is no longer needed.

## One source for each instruction

A full runtime instruction assembled from a skill, references, and a task
suffix must not be independently edited as another Langfuse prompt. Export the
components, then assemble the repo artifact deterministically from a checked-in
composition manifest. Record every component's Langfuse name, numeric version,
and SHA-256 plus the assembled SHA-256. The application continues loading the
assembled repo artifact. Evaluation must resolve the same manifest and record
the component versions with each experiment; evaluating only a suffix would
test a different instruction.

The current registry has 107 names in seven groups: interview 32, memory 25,
composer 11, research 1, speech 3, skills 25, evaluation 10. All 107 have
distinct complete file bytes, but five runtime files contain substantial exact
copies of other managed files:

| Current runtime prompt | Embedded managed sources | Runtime use |
| --- | --- | --- |
| `memoir/memory/timeline` | author-timeline `SKILL.md` and `references/contract.md`, followed by a task suffix | Canonical MemoryEvent extraction through `memory_events.extraction_instructions()` and the lifetime lane |
| `memoir/memory/timeline-derived` | Same two author-timeline files, followed by a two-lane variant suffix | Two-lane extraction through `two_lane_memory.py` |
| `memoir/composer/draft` | Composer `SKILL.md` and three references, followed by a task suffix | Legacy/default composer instruction; no canonical lane call selects it |
| `memoir/composer/draft-canonical` | Composer narrative-enrichment reference plus canonical intro and shared draft suffix | Current bounded composer draft lane |
| `memoir/composer/review` | Composer editorial-review and narrative-enrichment references plus review suffix | Composer review lane |

This is a version-skew risk: exporting a new skill version does not rewrite the
copy embedded in a runtime file. Split each row into its unique task text and
shared components, then verify the assembled bytes match the current prompt
before removing the composite Langfuse name. The legacy/default composer
draft needs a caller audit before retirement; the canonical draft is active.

## What the remaining folders do today

| Folder | Observed loader or role | Decision |
| --- | --- | --- |
| `interview` | `codex_runtime.py`, collector and plan modules; browser fragments generate `browser-prompts.generated.mjs` | Keep as runtime instructions. |
| `memory` | `memory_events.py`, background profile, family/place workspace, lifetime lane | Keep actual task instructions. Remove `fallback/{family-tree,place-journey,author-timeline}` after making their source skill artifacts required at startup. |
| `composer` | `memoir_preview.composer_instructions()` and bounded lane; organiser job uses separate phase/locale prompts | Keep task-specific text, then derive complete instructions from the manifest. |
| `research` | `historical_news_provider.py` loads `historical-discovery.md` | Keep; this is the provider task, distinct from the research skill guide. |
| `speech` | `speech.py` loads locale/default instructions | Keep. |
| `skills` | Family tree, place journey, memory context, and legacy author marker are loaded by app code; other skills are read by the skill or evaluation harness | Keep model-facing instructions and use `/instructions` and `/references`. The registry now has an explicit model-facing reference allowlist. Developer contracts and provenance stay in Git only. |
| `evaluation` | Isolated skill cases and judge code load these; they are not ordinary conversation prompts | Keep, with an evaluation label. |

The canonical author-timeline skill and the legacy conversation marker are
different execution modes. `codex_runtime.py` loads
`skills/memoir-author-timeline/references/legacy-marker.md` for the paid
conversation marker, while `memory_events.py` loads the complete canonical
extraction prompt. Name the marker under `interview/legacy-marker/author-timeline`
when migrating; it is not a second canonical timeline task.

`memoir-story-game` is loaded for the skill harness but explicitly excluded
from conversational prompts in `codex_runtime.py`. Keep it labelled as a
candidate/evaluation skill until that application binding is enabled.

## Migration order

1. Check in an explicit inventory of managed sources and their consuming code
   path. Stop auto-registering every `references/*.md` file.
2. Extract the repeated timeline/composer text into uniquely named components.
   Assert byte-for-byte parity with all currently loaded complete prompts.
3. Update runtime loading, browser generation where relevant, and the Langfuse
   experiment command to use the same composition manifest. Fail when a required
   component or receipt is missing.
4. Create the new stable Langfuse names, export receipts, and verify every
   assembled artifact. Back up then remove superseded names. Retain version and
   migration metadata in the repo; do not put dates or versions in the new path.
5. Remove fallback prompts and unused legacy draft only after tests show the
   intended execution paths. Run `make prompt-check`, the affected runtime tests,
   and an experiment preflight against the assembled prompt and stable dataset.

Until steps 2–5 are complete, the existing 107 registered names and runtime
files remain the active export contract. A folder rename alone would not fix
the embedded copies.
