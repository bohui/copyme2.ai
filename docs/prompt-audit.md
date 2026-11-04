# Prompt and evaluation audit — 4 November 2026

**The prompt inventory is now accountable; complete prompt-quality coverage is
not established.** A dataset association, a passing controlled regression and a
scored experiment are different kinds of evidence. None alone proves that the
current version of every conditional prompt was exercised successfully.

The audit starts from local main `46322f05` on `codex/prompt-coverage-audit`.
The linked Langfuse project is `cmut9t75w00071z02n8bdv7it` (display name `memior`).
API credentials and the local metadata database were independently checked
against that exact project before interpreting or changing its records.

## Complete tables and evidence

- [Every retained prompt: source, consumer, scenario, evaluator and dataset](prompt-coverage.md).
- [Machine-readable prompt matrix](prompt-coverage.json), including every target
  dependency and active hosted-rule ID, not just a preferred parent target.
- [Live metadata snapshot](prompt-audit-live.json): dataset IDs, case hashes,
  observed experiment/score counts, actual evaluator versions and rule filters.
  It contains no customer trace text or raw case inputs/expected outputs.
- [Retired-source recovery archive](prompt-audit-retired.json).
- [Workflow for future prompt, dataset and evaluator changes](prompt-evaluation-workflow.md).

The inventory reconciles **97 originally managed sources: 96 retained and one
retired**, plus **11 upstream instruction files** used by NovelToGame. All owned
prompt-directory Markdown is checked against the catalog. Vendor instructions
are separately pinned by `deps/novel-to-game.lock.json`; the table includes their
stage consumers and hashes. The experiment's code-defined `FORMAT` field and
the separately installed Higgsfield skill are identified explicitly. A separate
table records the frozen age-eight example adapter and its six inline stage
tasks; these historical sources have no active hosted evaluator or dataset and
are not supported production instructions. Photo-research invocation examples
are identified as documentation rather than claimed evaluation results.

The live snapshot contains **95 datasets, 562 dataset items, 46 experiments and
477 experiment items, of which 473 have at least one score**. These are evidence
counts, not pass rates. There are **eight hosted evaluator definitions**:
four LLM quality judges and four CODE evaluators. **68 rules** exist: 64 active
and four inactive; no evaluator is blocked. All four hosted judge prompt hashes
match their checked-in source. All 95 configured dataset names/IDs match the
server. The older `job_configurations`/`eval_templates` tables are empty and are
not the current evaluator store; current records live in `evaluation_rules`,
`evaluators`, `evaluator_versions` and their assignment table.

The deployed server does not expose the newer hosted-evaluator public API used
by the installed SDK. Hosted metadata was therefore verified through an explicit
project-scoped, read-only local PostgreSQL transaction. Prompt/dataset/experiment
metadata uses the available public APIs. The obsolete dataset-runs endpoint
returns 404; the snapshot uses the current experiment and experiment-item APIs,
requesting score fields explicitly.

## Findings and implemented repairs

| Finding | Evidence and repair |
| --- | --- |
| Unused Mira strategy-proposal prompt was still published and listed as a reply dependency. | No application, script, experiment or supported dynamic loader consumes the artifact. The strategy data types retained for old records do not load this prompt. Its source and exact publication receipt are archived, and it is removed from current catalogs and bindings. |
| Summary evaluation pointed at the wrong prompt. | `summary_contract()` sends `memoir/skills/memory-context/summary`; the binding identified `author-timeline/window`. The target now identifies the actual summary source. A regression compares the real assembled manifest with the binding. |
| Game production and whitebox bindings did not identify their executed stages. | The production stage executes `production.md`, with adapter/journey/assets. The registry pointed to `production_style`; whitebox pointed only to assets. Both now bind their actual stage and dependencies. |
| Outline and shared components were incompletely represented. | The outline target now includes leaf/merge × en-AU/zh-CN, with shared prefix/suffix. Rendered template components, bounded-lane locale policy, historical-search skill/contract, dispatch and conditional components are represented. Validation rejects a missing composed dependency. |
| Place-hint extraction sent an unresolved prompt macro. | The derived-hint fragment was loaded as raw Markdown, leaving `{{prompt:timeline_grounding}}` in model instructions. It now uses the shared renderer. New place-only and joint-skill cases reject unresolved macros and verify the grounding/derived-hint provenance. |
| The source-window prompt was sent but omitted from native provenance. | `lane_extraction_packet()` places the versioned window contract in model input. The native receipt previously scanned instruction text and skill reads only. Exact active window contracts are now explicitly included in the outer and native manifests. A controlled native replay first reproduced the omission, then passed with the fix. |
| Inventory and evaluation reviews could silently drift. | The coverage check rejects new unregistered prompt files, missing scenarios or consumers, removed functions, stale prompt/dataset/evaluator review hashes, dataset ID drift and hosted judge text drift. `make prompt-check` now runs it. `AGENTS.md` preserves the workflow for future Codex sessions. |
| The database replay treated a brief scheduling deferral as completion. | A failed replay showed an unclaimed pending lane with no error and an eligibility timestamp about 0.4 seconds ahead of database time. The fixture now waits at most two seconds only for that short, unclaimed/no-error state. Genuine error/backoff states still stop. |
| The CSS-only repair prompt initially appeared unused in production. | A repository-wide scan found its maintained experimental loader in `experiments/novel-to-game/stages.py`. It is retained as an experimental workflow, with a separate target; it is not the production-stage prompt. |
| Recovery needed the raw API's name and version-metadata conventions. | The read-only retirement plan initially returned 404 for a slash-separated name. Matching the installed SDK's encoding convention fixed the live read. The guard then caught an omitted `latest` label in the archive. GET/DELETE paths now encode the exact name, the backup preserves raw version metadata, and regressions cover name encoding and unarchived label/tag changes. |

Bindings describe the **permitted component set** for a target. For example,
either locale policy can be permitted while one request uses only one locale.
Neither the matrix nor these repairs assert that every item executes every
permitted component. Native manifests identify what was actually used.
The corrected graph is the current repository declaration; old experiment
metadata and historical observations are preserved rather than rewritten as
current execution evidence.

Hosted evaluator names and rule IDs are listed per prompt in the machine-readable
matrix. The SDK/code grading entry points are
`scripts/run_memoir_agent_evaluation.py:scores`,
`scripts/run_memoir_skill_evaluation.py:evaluate`, and
`scripts/memoir_skill_eval_suite.py:validate`, `hosted_contract` and `quality`.
The controlled regression selectors are separate evidence and remain visible
when there is no hosted dataset or calibrated semantic grader.

## Coverage assessment

Before the audit, only **67 of 97** managed names appeared anywhere in the
binding registry. Every retained source now has a scenario, source consumer,
evaluation target, controlled regression path and reviewed change receipt.
**75 of 96 retained prompts have an active hosted dataset association.** That
association remains weaker than version-specific execution and passing quality.

One dataset, evaluator and evaluation run may cover multiple prompts together.
The counts above already include shared workflow/component associations. For
example, the historical-news core dataset and its hosted graders are associated
with the instructions, discovery and contract prompts. Extend or reuse suitable
shared suites for the remaining gaps; 21 missing associations do not imply 21
new datasets. Cases and actual manifests must establish which prompts and branches
were exercised within the shared run.

The remaining **21 prompts without an active hosted dataset** are:

| Group | Count | Evidence to add to shared or focused suites |
| --- | ---: | --- |
| Judge/comparison components | 6 | Human-labelled, held-out calibration for paired Mira preference, semantic boundaries, shared trajectory system/rubric and five-case trajectory/guard. Synthetic wiring checks establish connectivity, not agreement with expert judgement. |
| Diagnostic probe inputs | 10 | Explicit diagnostic fixtures for connectivity, worker transport, native search and the skill probes, or a documented decision to keep their command-level checks instead of a hosted dataset. Their outputs do not grade production skill quality. |
| Selective summary | 1 | Summary cases in a shared workflow suite or focused dataset, covering exact citations, prior summaries, uncertainty, restricted/deleted sources, empty output and budget retry. Existing summary regressions provide controlled correctness, not live summary quality. |
| Experimental styling repair | 1 | A CSS-only experiment fixture preserving source passages, markup/behavior, hidden states, accessibility and real desktop/touch replay. |
| Speech policies | 3 | Modality-specific speech fixtures for default, en-AU and zh-CN; actual audio and pronunciation/intelligibility review. Text-only judges on bounded speech metadata are inappropriate. |

There are also **nine unpublished `delivery-v3` dataset recipes** in the current
runner: timeline, composer checkpoints, family tree, profile, journey, grouping,
photo, history and game brief. Their exact names, item counts and content hashes
are in the live snapshot. The earlier `delivery-v2` datasets remain frozen
history. The runner publishes the new recipe when explicitly executing that
suite; absence of an experiment for that recipe is not a passing evaluation.
Profile gold now includes the directly stated avatar choice. Future comparisons
must use the matching recipe/version rather than interpreting the older gold as
the current expected contract.

Other important limits remain visible:

- The family-tree production runner is unwired; an isolated model contract
  probe cannot establish production availability.
- Composer, repair, locale, source-withdrawal, privacy and game branches need
  item-level manifests showing the branch was exercised, not just workflow-level
  scores. Existing case and regression paths are listed separately in the table.
- Upstream game instructions and generated artwork need a verified selected
  runtime, source/consent authority and actual play/replay evidence. Mocked
  protocol tests establish technical contracts rather than subjective quality.
- No human calibration labels were invented, no existing experiment was
  relabelled as a current-pin run, and no numeric quality pass was inferred from
  missing scores. This audit makes no new model-quality or 50-turn success claim.

Retirement is intentionally staged: the source is removed in this PR and every
published version is recoverable from the committed archive. Current remote
main still registers the legacy record. The main post-pull hook removes it after
merge, checking the project, archive, versions and source revision again before
the exact-name deletion. No remote record needed by main is deleted during PR review.

## Plan for complete quality coverage

| Priority | Dataset work | Evaluator / completion evidence |
| --- | --- | --- |
| P0: privacy, reply repair and sourced summary | Add bilingual normal, ambiguous, adversarial, restriction, withdrawal and failed-save cases. Keep exact expected spans and policy decisions outside model input. Include the Chengde childhood versus current Sydney residence regression. | Deterministic authority/span/schema checks plus calibrated interpretation judges. Each required branch must appear in the actual prompt manifest; retain failures and held-out cases. |
| P1: timeline and composition | Exercise attribution, continuity, selective extraction, summary retries, composer prepare/draft/review, batch and all four outline/locale combinations. Publish the reviewed delivery-v3 cases through the current runner. | Source grounding, chronology, completeness, uncertainty and bilingual consistency; measure live results against frozen expected outputs. Distinguish component results from end-to-end checkpoint delivery. |
| P1: evaluator reliability | Collect independent expert labels and disagreements for every active semantic judge and the six unbound judge components. Keep wiring cases separate from calibration cases. | Agreement, confusion matrices/critical false positives, blind pairwise ordering checks and held-out verification. Record evaluator version/model and calibration provenance; do not let judges recursively grade themselves. |
| P2: research and diagnostics | Include source-date/place mismatches, missing provenance, licensing/approval rejection, empty search and transient provider failure. Give probes explicit expected protocol outcomes if hosted history is useful. | Production validators and grounded source checks; unavailable remains unavailable. Smoke probes can stay command-level tests without being called semantic coverage. |
| P2: speech, artwork and games | Keep actual audio, generated images and playable artifacts with their prompt/dependency versions and consented synthetic fixtures. Include locale fallback and the experimental CSS-only branch. | Modality-specific human/automated review, real rendering/input/outcome/restart checks, source fidelity and accessibility. Text metrics alone do not complete these rows. |

For each row, use the production assembler, freeze the reviewed dataset version,
run the intended evaluator, retain actual component/version witnesses and assess
failures before release. Case counts and acceptance thresholds should follow the
observed error distribution and expert review; no universal synthetic case count
is asserted here.

This follows the task-specific, continuous and human-calibrated evaluation
process in [OpenAI's evaluation guidance](https://developers.openai.com/api/docs/guides/evaluation-best-practices),
and Langfuse's separation of [experiments](https://langfuse.com/docs/evaluation/experiments/overview)
from [judge calibration](https://langfuse.com/guides/llm-as-a-judge-calibration-skill).

## Validation performed

Checks were repeated against an isolated export of the staged audit sources so
unrelated working-tree reply/UI edits could not affect the result.

- `make prompt-check`: 77 targets, 95 dataset bindings, 25 online-rule declarations
  and all 96 retained exact published prompt pins verified.
- 312 focused tests passed, covering prompt publication/retirement, composition,
  provenance, evaluation bindings, inventory, snapshot filtering and skill/game
  integration. The subsequent inventory/snapshot recheck passed all 16 tests.
  All 31 publication tests were rerun after the live API compatibility repairs;
  the retirement cases also verify that SDK write retries are disabled so an
  uncertain deletion is read back before any retry.
- `MEMOIR_TEST_POSTGRES_BACKEND=apple-container make test-place-research` passed:
  741 web tests, 825 API/database tests and 96 photo-research skill tests.
- All 781 owned Python sources parsed successfully; the staged diff passed
  whitespace checks and contained no matching configured credential values.

These establish code and provenance checks. They do not supply the missing human
labels, modality reviews or current-version model-quality results described above.
