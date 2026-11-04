# Prompt ownership and usage

The current [complete audit](prompt-audit.md) and [generated inventory](prompt-coverage.md)
cover 96 retained managed sources, one retired source and 11 locked upstream
instruction files. Counts and profiling results dated below describe their
recorded snapshots, rather than current prompt-quality coverage.

Verified on 18 October 2026. The catalog contains **69 model-consumed sources**:
20 runtime, 21 conditional runtime, 10 shared runtime, and 18 evaluation inputs.
The application and exporter use the same explicit catalog in
`apps/api/prompt_catalog.py`. Each source has one owner, one name and one exact
version receipt. These are caller-level classifications, not traffic counts.

The recall-limit policy adds `memoir/shared/recall-invitations` as managed host
copy. After a reply identifies unavailable details, the host renders a selected
broader pool question verbatim or this optional invitation. It makes no extra
model call and does not treat the unavailable detail as an answered fact.

Mira uses only `reply-v2`, with four agent-owned prompt sources under
`apps/api/prompts/mira/`: `system`, `policy-review`, `repair` and `repair-codes`.
The unused strategy-proposal artifact is archived by the current audit. The
retained sources publish under `memoir/agents/mira/...` from the
committed branch; new namespace receipts are not fabricated from the older skill pins.

Mira is the interviewer; Atlas is the background memoir curator. Their Langfuse
trace names are `memoir-mira` and `memoir-atlas`. Observation names identify the
step, such as `memoir-mira.reply`, `memoir-mira.policy-review` and
`memoir-atlas.orchestrate`. A nested skill keeps the owning agent's trace name
while naming its own step, such as `memoir-composer.review`. Each run has a unique
trace ID; the trace name labels similar runs. Historical observations keep their
original labels.

Mira's paired prompt evaluation uses the trace name `evaluation/memoir-mira`
and observation names such as `evaluation/memoir-mira.baseline.<case>` and
`evaluation/memoir-mira.judge`.

Atlas's system prompt lives in `apps/api/prompts/atlas/system.md` and publishes
under `memoir/agents/atlas/skill-selection`. The former `memoir/shared/background-agent`
record has been removed from Langfuse after the old application workers stopped. The generic
`memoir/shared/skill-agent` runner instructions remain shared infrastructure.

The retired `memoir/skills/memoir-interviewer/*` prompt family and its old
`memoir/evaluation/skills/memoir-interviewer/rubric` are no longer dependencies
and can be removed from Langfuse. Keep managed shared prompts: bounded context,
skill execution, recall invitations, historical acknowledgements and place
conflicts still have runtime callers. Zero linked observations alone does not
establish that a prompt is unused; runtime reads checked-in artifacts.

`memoir-interview-guidance` is also retired: its skill package, managed prompt,
worker role and model execution path have been removed. Historical guidance
data validators and storage remain for old records. Inspected news is delivered
directly as host-owned context for Mira; it needs no guidance skill.

The greeting endpoint returns localized application text without a model call.
Duplicate dispatch instructions, the separate early-ack template and three repair
fragments have been removed or folded into the retained sources. The system
prompt owns voice and interviewing judgement; the schema and host validate the
private work handoff to Lane B. Background workers read the accepted original
source, so Mira does not extract or retell it in that handoff.

Privacy is enforced by Memoir's current-source policy review and database policy
fences, not by the generic Codex harness. Its review prompt remains separate from
Mira's conversational role. Existing `memoir-interviewer` evaluation case IDs are
stable historical identifiers; evaluation inventory classifies Mira as an agent.
Its quality rubric and paired comparison prompt save under
`memoir/evaluators/agents/mira/reply/{interview-quality,comparison}`. The older skill rubric name
is no longer managed, and its receipt is not reused for the new agent identity.

Earlier character counts below describe the recorded optimization, not the new
draft. See the [paired draft evaluation](test-evidence/mira-role-prompt-20261029.json).


## Mira role-prompt evaluation — 29 October 2026

The initial concise role was **1,033 characters**, down from **1,922** characters for the
previous reply-plus-dispatch instructions (46% less static text). The output
schema and host validators still own evidence spans, prepared-question identity,
private work routing, privacy epochs and atomic saving. No judgement rules were
moved into hidden runtime string classifiers as part of this simplification.

Paired evaluation used the configured `gpt-6.1-sol` route at low requested effort
for both prompts. A separate `gpt-5.6-luna-memoir-low` call reviewed anonymous A/B
outputs. All inputs were fictional: 36 existing bilingual conversation cases and
six additional Lane B cases covering prepared clarification, recall difficulty
and the latest redirect overriding queued hints.

| Observed measure | Previous prompt | Concise Mira role |
| --- | ---: | ---: |
| Validated proposals | 42/42 | 42/42 |
| Blind mean quality, 0–4 | 3.762 | 3.810 |
| Critical issues flagged in final sample | 0 | 0 |
| Preferred in paired review | 7 | 9 |

The other 26 comparisons tied. This small exploratory sample supports preserving
conversation quality; the score difference is not evidence of statistical
superiority. Initial pilots caught an assumed narrator presence and an unsupported
causal link. The final role therefore preserves uncertainty about who was involved
and how events connect. The judge rubric also distinguishes acknowledging rejected
wording from asserting it as true. Pilot and refinement evidence are retained.

- [36-case comparison](test-evidence/mira-role-prompt-20261029.json)
- [Six Lane B comparisons](test-evidence/mira-lane-b-prompt-20261029.json)
- [Initial pilot](test-evidence/mira-role-prompt-20261029-pilot.json)
- [Intermediate refinement](test-evidence/mira-role-prompt-20261029-refinement.json)

The required `make test-place-research` regression passed: 633 web tests,
631 Python cases and 96 skill-unit checks. The current privacy/early-ack tests
passed 52 PostgreSQL-backed cases. Legacy native-runtime fixtures still expect
retired reply shapes and are not included in these passing results. Live prompt
comparisons establish model-proposal quality only; runtime publication still
requires merged-main Langfuse receipts. No new receipt versions were invented.

## Emotional attunement refinement — 29 October 2026

The current compiled system role is **1,504 characters**. Mira listens with the ease and
care of an old friend, notices emotional meaning in specific details, and keeps
unspoken feelings as hunches the narrator can confirm or correct. The narrator's
account defines their feelings, relationships and motives. The role also makes
room for joy and ordinary moments, follows boundaries, and keeps the conversation
moving with a useful next question when one helps.

The configured model and independent blind judge compared this role with the
1,033-character role on 16 new fictional cases, paired across English and Chinese.
They cover humour masking hurt, unexplained absence, minimised childhood
responsibility, private relief, quiet joy, a topic boundary, an ordinary day and
correction of an emotional interpretation. All 16 proposals passed production
validation for each prompt. Mean quality was **3.750 versus 3.438** on a 0–4 scale;
the new role was preferred six times, the baseline once, and nine pairs tied.
Neither prompt had a critical issue flagged in this final emotional sample.

The 36 existing conversation cases also passed for both prompts, with no critical
issues flagged. Mean quality was 3.944 for the new role and 3.917 for the baseline;
three pairs preferred the new role, two preferred the baseline and 31 tied.
All six Lane B probes passed for both prompts, with no critical issues flagged.
Their mean quality was 3.833 for the new role versus 4.000 for the baseline;
five pairs tied and one preferred the baseline. Across all three final samples,
both prompts passed 58/58 proposal validations. The 91 focused offline prompt,
projection and transport tests also passed.
These are small exploratory comparisons, not statistical evidence of superiority.

An initial pilot caught an omitted follow-up, an unsupported shared-life claim
and an overconfident emotional inference. Three generation requests encountered
gateway 502 errors across the pilot and initial refined runs. A final Lane B
rerun with the unchanged refined prompt completed all six cases. The refinement
made emotional readings explicitly tentative
and restored the existing next-question guidance. Final comparisons reuse the
verified baseline outputs and rerun candidate generation and blind judging;
baseline judgments can therefore differ between rounds. Pilot evidence is retained.
These are draft model proposals; publication and recovery of the pending live turn
still require the merged-main prompt workflow.

- [Emotional comparison](test-evidence/mira-emotional-attunement-20261029.json)
- [Conversation regression comparison](test-evidence/mira-emotional-core-20261029.json)
- [Lane B comparison](test-evidence/mira-emotional-lane-b-20261029.json)
- [Emotional pilot](test-evidence/mira-emotional-attunement-20261029-pilot.json)
- [Conversation pilot](test-evidence/mira-emotional-core-20261029-pilot.json)
- [Lane B pilot](test-evidence/mira-emotional-lane-b-20261029-pilot.json)
- [Lane B run with a gateway failure](test-evidence/mira-emotional-lane-b-20261029-transport-retry.json)

## Earlier recorded request measurements

For a normal `reply-v2` narrator turn, these are separate model calls:

| Foreground call | Static prompt components | Baseline characters | Proposed characters |
| --- | --- | ---: | ---: |
| Privacy review | `policy-review` | 2,753 | 993 |
| Reply generation | `reply` + newline + `governed-turn` | 1,986 | 1,986 |
| Both calls | Separate requests | 4,739 | 2,979 |

The under-2,000 budget applies to the normal reply generator's static instructions,
not the whole Lane A flow or total request size. Conversation evidence, output
schema and transport framing are additional. The proposed optional early-ack
template composes the core rules and original acknowledgement guidance into
1,998 characters. On a rejected reply, selected repair guidance uses 431–823
static characters, down from 3,215, plus error data and the optional
acknowledgement-preservation rule. Greetings and Lane B have separate triggers;
the five-source inventory is not the prompt input for every turn. See the
[profiled optimization](issue53-policy-repair-20261022.md), including slower
held-out cases and the remaining deployment/acceptance gates.

## Ownership

- `memoir/skills/<skill>/...` owns the skill's instructions, phases and reusable policy.
  Its repository sources live under `skills/<skill>/`.
- `memoir/shared/...` owns bounded-context instructions shared by timeline and composer.
- `memoir/evaluators/...` owns judge instructions; `memoir/probes/...` owns diagnostic inputs.
- `memoir/workflows/speech/synthesis/...` owns synthesis instructions.

`lane`, `two-lane` and `organiser-job` are execution details, not parallel prompt
owners. Composer batch preparation and composition now belong to composer;
place fields extend the existing timeline request. The foreground reply consumes
bounded background hints as data.

The composer guide points to the actual phase templates and shared policies.
Its guide, integration contracts and editorial documentation remain ordinary
repository resources. Their presence in a bundle or a cache fingerprint does
not make them an application model input.

## Code paths

All bounded requests are assembled and budgeted through `lane_contract` (or
`job_contract` for selected-collection outlines). The same builders supply the
worker's actual instructions and schema. The separate partial budget builders
were removed from extraction, summaries, profile extraction and composition.

The legacy model-generated composer index, full-source preview execution and
uncalled private-draft executor were removed. Canonical composition consumes
host-owned events. Historical preview job IDs resolve to canonical draft state;
polling cannot restart the retired model workflow. Deterministic source-reference
and cache readers remain available for historical data.

## Prompt inventory

| Langfuse name | Version | Classification | Consumer / condition |
| --- | ---: | --- | --- |
| [`memoir/agents/mira/reply`](../apps/api/prompts/mira/system.md) | Pending main publication | Agent runtime | Mira owns real-time clarification, connected topic development and tentative values reflection. Saved background deliveries are optional context after the current narration. |
| [`memoir/agents/mira/policy-review`](../apps/api/prompts/mira/policy-review.md) | Pending main publication | Runtime gate | Current-source privacy controls, with an optional schema-requested early acknowledgement. |
| [`memoir/agents/mira/repair`](../apps/api/prompts/mira/repair.md) | Pending main publication | Conditional runtime | Correction instructions for rejected or incomplete output; acknowledgement locking stays in the schema. |
| [`memoir/agents/mira/repair-codes`](../apps/api/prompts/mira/repair-codes.md) | Pending main publication | Conditional runtime | Only the matching validation rule and common guidance enter the repair. |
| [`memoir/agents/mira/strategy-proposal`](../apps/api/prompts/mira/strategy-proposal.md) | Pending main publication | Legacy compatibility | Current Mira replies do not load Lane B interview plans. |
| [`memoir/evaluators/workflows/five-case-memoir/trajectory`](../tests/evaluation/memoir_five_case_judge_prompt.md) | 1 | Evaluation only | [`scripts/run_memoir_five_case_semantic_judge.py`](../scripts/run_memoir_five_case_semantic_judge.py) — Five-case semantic judge template. |
| [`memoir/evaluators/workflows/five-case-memoir/guard`](../tests/evaluation/prompts/five-case-judge/guard.md) | 1 | Evaluation only | [`scripts/run_memoir_five_case_semantic_judge.py`](../scripts/run_memoir_five_case_semantic_judge.py) — Semantic judge guard for retained evaluation evidence. |
| [`memoir/probes/skills/historical-news-research/discovery`](../tests/evaluation/prompts/live-skills/historical-lead.md) | 1 | Evaluation only | [`scripts/memoir_live_skill_cases.py`](../scripts/memoir_live_skill_cases.py) — Isolated live-skill contract probe; no production persistence. |
| [`memoir/probes/skills/author-timeline/extract`](../tests/evaluation/prompts/live-skills/independent-events.md) | 1 | Evaluation only | [`scripts/run_memoir_live_skills.py`](../scripts/run_memoir_live_skills.py) — Isolated live-skill evaluation instructions. |
| [`memoir/probes/shared/native-search`](../tests/evaluation/prompts/live-skills/native-search.md) | 1 | Evaluation only | [`scripts/run_memoir_live_skills.py`](../scripts/run_memoir_live_skills.py) — Isolated live-skill evaluation instructions. |
| [`memoir/probes/skills/place-photo-research/discovery`](../tests/evaluation/prompts/live-skills/photo-lead.md) | 1 | Evaluation only | [`scripts/memoir_live_skill_cases.py`](../scripts/memoir_live_skill_cases.py) — Isolated live-skill contract probe; no production persistence. |
| [`memoir/probes/skills/place-groups/group`](../tests/evaluation/prompts/live-skills/place-groups.md) | 1 | Evaluation only | [`scripts/memoir_live_skill_cases.py`](../scripts/memoir_live_skill_cases.py) — Isolated live-skill contract probe; no production persistence. |
| [`memoir/probes/skills/story-game/brief`](../tests/evaluation/prompts/live-skills/story-game.md) | 3 | Evaluation only | [`scripts/memoir_live_skill_cases.py`](../scripts/memoir_live_skill_cases.py) — Isolated live-skill contract probe; no production persistence. |
| [`memoir/evaluators/shared/trajectory/rubric`](../apps/api/prompts/evaluation/trajectory-judge/rubric.md) | 1 | Evaluation only | [`apps/api/trajectory_evaluation.py`](../apps/api/trajectory_evaluation.py) — Trajectory evaluation judge; not a storyteller turn. |
| [`memoir/evaluators/shared/trajectory/system`](../apps/api/prompts/evaluation/trajectory-judge/system.md) | 1 | Evaluation only | [`apps/api/trajectory_evaluation.py`](../apps/api/trajectory_evaluation.py) — Trajectory evaluation judge; not a storyteller turn. |
| [`memoir/shared/bounded-context/en-AU`](../apps/api/prompts/shared/bounded-context/en-AU.md) | 2 | Runtime | [`apps/api/lifetime_memory_lane_engine.py`](../apps/api/lifetime_memory_lane_engine.py) — English edition suffix for a bounded partition; not a second lane. |
| [`memoir/shared/bounded-context/policy`](../apps/api/prompts/shared/bounded-context/policy.md) | 1 | Shared runtime | [`apps/api/lifetime_memory_lane_engine.py`](../apps/api/lifetime_memory_lane_engine.py) — One privacy/evidence policy shared by both edition locales. |
| [`memoir/shared/bounded-context/zh-CN`](../apps/api/prompts/shared/bounded-context/zh-CN.md) | 2 | Runtime | [`apps/api/lifetime_memory_lane_engine.py`](../apps/api/lifetime_memory_lane_engine.py) — Chinese edition suffix for a bounded partition; not a second lane. |
| [`memoir/shared/place-conflicts`](../apps/api/prompts/shared/place-conflicts.md) | 1 | Conditional runtime | [`apps/api/lifetime_memory_lane_engine.py`](../apps/api/lifetime_memory_lane_engine.py) — Appended only when a page has attribution coverage. |
| [`memoir/skills/historical-news-research/contract`](../skills/memoir-historical-news-research/references/contract.md) | 1 | Evaluation only | [`scripts/memoir_live_skill_cases.py`](../scripts/memoir_live_skill_cases.py) — Explicit isolated probe/native-search model input; does not prove a production binding. |
| [`memoir/skills/historical-news-research/discovery`](../skills/memoir-historical-news-research/prompts/discovery.md) | 1 | Conditional runtime | [`apps/api/historical_news_provider.py`](../apps/api/historical_news_provider.py) — Optional public-history provider discovery, behind its rollout flag. |
| [`memoir/skills/historical-news-research/instructions`](../skills/memoir-historical-news-research/SKILL.md) | 2 | Evaluation only | [`scripts/memoir_live_skill_cases.py`](../scripts/memoir_live_skill_cases.py) — Explicit isolated probe/native-search model input; does not prove a production binding. |
| [`memoir/skills/author-timeline/attribution`](../skills/memoir-author-timeline/prompts/attribution.md) | 1 | Conditional runtime | [`apps/api/two_lane_memory.py`](../apps/api/two_lane_memory.py) — Additional attribution output only for an attributed two-lane source page. |
| [`memoir/skills/author-timeline/contract`](../skills/memoir-author-timeline/references/contract.md) | 1 | Shared runtime | [`apps/api/memory_events.py`](../apps/api/memory_events.py) — Schema/evidence component in both timeline variants. |
| [`memoir/skills/author-timeline/derived-hints`](../skills/memoir-author-timeline/prompts/derived-hints.md) | Source update pending main publication | Conditional runtime | [`apps/api/two_lane_memory.py`](../apps/api/two_lane_memory.py) — Background extraction fields; Mira owns current interviewing. |
| [`memoir/skills/author-timeline/extract`](../skills/memoir-author-timeline/prompts/extract.md) | 3 | Runtime | [`apps/api/memory_events.py`](../apps/api/memory_events.py) — Events-only schema in the canonical timeline lane. |
| [`memoir/skills/author-timeline/extract-with-hints`](../skills/memoir-author-timeline/prompts/extract-with-hints.md) | 2 | Conditional runtime | [`apps/api/two_lane_memory.py`](../apps/api/two_lane_memory.py) — Same extraction request with additional place/question fields when MEMOIR_TWO_LANES is enabled. |
| [`memoir/skills/author-timeline/instructions`](../skills/memoir-author-timeline/SKILL.md) | Source update pending main publication | Shared runtime | [`apps/api/memory_events.py`](../apps/api/memory_events.py) — Canonical extraction; Mira owns interviewing in Lane A. |
| [`memoir/skills/author-timeline/shared/grounding`](../skills/memoir-author-timeline/prompts/shared/grounding.md) | 1 | Shared runtime | [`apps/api/memory_events.py`](../apps/api/memory_events.py) — Grounding rules shared by both extraction schemas. |
| [`memoir/skills/author-timeline/window`](../skills/memoir-author-timeline/prompts/window.md) | 1 | Runtime | [`apps/api/lifetime_memory_composer.py`](../apps/api/lifetime_memory_composer.py) — Bounded source-window instructions in the extraction packet. |
| [`memoir/skills/composer/batch/compose`](../skills/memoir-composer/prompts/batch/compose.md) | 1 | Runtime | [`apps/api/lifetime_memory_lane_engine.py`](../apps/api/lifetime_memory_lane_engine.py) — Batch-specific drafting/review instructions in the same canonical composer. |
| [`memoir/skills/composer/batch/prepare`](../skills/memoir-composer/prompts/batch/prepare.md) | 1 | Runtime | [`apps/api/lifetime_memory_lane_engine.py`](../apps/api/lifetime_memory_lane_engine.py) — Batch-specific preparation instructions in the same canonical composer. |
| [`memoir/skills/composer/draft`](../skills/memoir-composer/prompts/draft.md) | 2 | Runtime | [`apps/api/memoir_preview.py`](../apps/api/memoir_preview.py) — Canonical draft phase; shares event IDs and evidence with extraction. |
| [`memoir/skills/composer/outline/leaf/en-AU`](../skills/memoir-composer/prompts/outline/leaf/en-AU.md) | 2 | Conditional runtime | [`apps/api/lifetime_memory_job_engine.py`](../apps/api/lifetime_memory_job_engine.py) — Leaf paid-book organisation, en-AU; same job runner, different input-reference field/output language. |
| [`memoir/skills/composer/outline/leaf/zh-CN`](../skills/memoir-composer/prompts/outline/leaf/zh-CN.md) | 2 | Conditional runtime | [`apps/api/lifetime_memory_job_engine.py`](../apps/api/lifetime_memory_job_engine.py) — Leaf paid-book organisation, zh-CN; same job runner, different input-reference field/output language. |
| [`memoir/skills/composer/outline/merge/en-AU`](../skills/memoir-composer/prompts/outline/merge/en-AU.md) | 2 | Conditional runtime | [`apps/api/lifetime_memory_job_engine.py`](../apps/api/lifetime_memory_job_engine.py) — Merge paid-book organisation, en-AU; same job runner, different input-reference field/output language. |
| [`memoir/skills/composer/outline/merge/zh-CN`](../skills/memoir-composer/prompts/outline/merge/zh-CN.md) | 2 | Conditional runtime | [`apps/api/lifetime_memory_job_engine.py`](../apps/api/lifetime_memory_job_engine.py) — Merge paid-book organisation, zh-CN; same job runner, different input-reference field/output language. |
| [`memoir/skills/composer/outline/shared/prefix`](../skills/memoir-composer/prompts/outline/shared/prefix.md) | 1 | Shared runtime | [`apps/api/lifetime_memory_job_engine.py`](../apps/api/lifetime_memory_job_engine.py) — One bounded paid-collection policy shared by leaf/merge and both locales. |
| [`memoir/skills/composer/outline/shared/suffix`](../skills/memoir-composer/prompts/outline/shared/suffix.md) | 1 | Shared runtime | [`apps/api/lifetime_memory_job_engine.py`](../apps/api/lifetime_memory_job_engine.py) — One reference/size policy shared by leaf/merge and both locales. |
| [`memoir/skills/composer/prepare`](../skills/memoir-composer/prompts/prepare.md) | 1 | Runtime | [`apps/api/canonical_composer.py`](../apps/api/canonical_composer.py) — Prepare source-linked context before drafting. |
| [`memoir/skills/composer/review`](../skills/memoir-composer/prompts/review.md) | 3 | Runtime | [`apps/api/memoir_preview.py`](../apps/api/memoir_preview.py) — Review the generated candidate against original evidence. |
| [`memoir/skills/composer/shared/editorial-review`](../skills/memoir-composer/references/editorial-review.prompt.md) | 1 | Shared runtime | [`apps/api/memoir_preview.py`](../apps/api/memoir_preview.py) — Review-only editorial component. |
| [`memoir/skills/composer/shared/narrative-enrichment`](../skills/memoir-composer/references/narrative-enrichment.md) | 1 | Shared runtime | [`apps/api/memoir_preview.py`](../apps/api/memoir_preview.py) — Single narrative policy read by drafting and review. |
| [`memoir/skills/family-tree/extract`](../skills/memoir-family-tree/SKILL.md) | 1 | Evaluation only | [`scripts/memoir_live_skill_cases.py`](../scripts/memoir_live_skill_cases.py) — Explicit isolated probe/native-search model input; does not prove a production binding. |
| [`memoir/skills/memory-context/profile`](../skills/memoir-memory-context/SKILL.md) | 1 | Runtime | [`apps/api/background_profile.py`](../apps/api/background_profile.py) — Automatic profile extraction for currently admitted targets. |
| [`memoir/skills/memory-context/summary`](../skills/memoir-memory-context/prompts/summary.md) | 1 | Runtime | [`apps/api/lifetime_memory_summary.py`](../apps/api/lifetime_memory_summary.py) — Canonical source-linked memory summary phase. |
| [`memoir/probes/skills/place-groups/instructions`](../skills/memoir-place-groups/SKILL.md) | 1 | Evaluation only | [`scripts/memoir_live_skill_cases.py`](../scripts/memoir_live_skill_cases.py) — Explicit isolated probe/native-search model input; does not prove a production binding. |
| [`memoir/skills/place-journey/extract`](../skills/memoir-place-journey/references/two-lane.md) | 1 | Conditional runtime | [`apps/api/two_lane_memory.py`](../apps/api/two_lane_memory.py) — Place-specific schema guidance on the same optional extraction request. |
| [`memoir/skills/place-journey/instructions`](../skills/memoir-place-journey/SKILL.md) | 1 | Evaluation only | [`scripts/memoir_live_skill_cases.py`](../scripts/memoir_live_skill_cases.py) — Explicit isolated probe/native-search model input; does not prove a production binding. |
| [`memoir/skills/story-game/instructions`](../skills/memoir-story-game/SKILL.md) | 4 | Shared runtime | [`apps/api/story_game_runtime.py`](../apps/api/story_game_runtime.py) — Shared system instructions for the scene-pool and confirmed-brief planning phases. |
| [`memoir/skills/story-game/proposal`](../skills/memoir-story-game/prompts/proposal.md) | 3 | Runtime, step 1 | [`apps/api/story_game_runtime.py`](../apps/api/story_game_runtime.py) — Composer chapters plus canonical timeline to a full scene pool with recommendations; then pause for owner selection. |
| [`memoir/skills/story-game/brief`](../skills/memoir-story-game/prompts/brief.md) | 1 | Runtime, step 2 | [`apps/api/story_game_runtime.py`](../apps/api/story_game_runtime.py) — GPT-6.1 Sol max prepares the exact confirmed subset's creative brief. |
| [`memoir/skills/story-game/higgsfield`](../skills/memoir-story-game/prompts/higgsfield.md) | 1 | Delegated build | [`apps/api/higgsfield_game.py`](../apps/api/higgsfield_game.py) — Astra adapter for the independently installed upstream game skill and private export target. |
| [`memoir/skills/story-game/webpage`](../skills/memoir-story-game/prompts/webpage.md) | 2 | Delegated build | [`apps/api/higgsfield_game.py`](../apps/api/higgsfield_game.py) — Memoir HTML/CSS export contract for the separate Higgsfield game builder. |
| [`memoir/skills/story-game/runtime-contract`](../skills/memoir-story-game/references/runtime-contract.md) | 5 | Evaluation only | [`scripts/memoir_live_skill_cases.py`](../scripts/memoir_live_skill_cases.py) — Separate host-admission audit, outside the two generation phases. |
| [`memoir/skills/place-photo-research/instructions`](../skills/memoir-place-photo-research/SKILL.md) | 2 | Evaluation only | [`scripts/memoir_live_skill_cases.py`](../scripts/memoir_live_skill_cases.py) — Explicit isolated probe/native-search model input; does not prove a production binding. |
| [`memoir/workflows/speech/synthesis/default`](../apps/api/prompts/speech/default.md) | 1 | Conditional runtime | [`apps/api/speech.py`](../apps/api/speech.py) — Voice delivery instructions selected by locale; only used for synthesis. |
| [`memoir/workflows/speech/synthesis/en-AU`](../apps/api/prompts/speech/en-AU.md) | 1 | Conditional runtime | [`apps/api/speech.py`](../apps/api/speech.py) — Voice delivery instructions selected by locale; only used for synthesis. |
| [`memoir/workflows/speech/synthesis/zh-CN`](../apps/api/prompts/speech/zh-CN.md) | 1 | Conditional runtime | [`apps/api/speech.py`](../apps/api/speech.py) — Voice delivery instructions selected by locale; only used for synthesis. |

## Removed entries

| Former name | Reason |
| --- | --- |
| `memoir/composer/index` | Retired model-generated event indexing; canonical composition consumes the existing event index. |
| `memoir/skills/memoir-composer` | Guide/reference without an application or evaluation model consumer; retained as repository documentation. |
| `memoir/skills/memoir-composer/editorial-and-length` | Guide/reference without an application or evaluation model consumer; retained as repository documentation. |
| `memoir/skills/memoir-composer/runtime-contract` | Guide/reference without an application or evaluation model consumer; retained as repository documentation. |
| `memoir/skills/memoir-composer/workflows` | Guide/reference without an application or evaluation model consumer; retained as repository documentation. |
| `memoir/skills/memoir-story-game/acceptance` | Guide/reference without an application or evaluation model consumer; retained as repository documentation. |
| `memoir/skills/memoir-story-game/formal-workflow` | Guide/reference without an application or evaluation model consumer; retained as repository documentation. |
| `memoir/skills/memoir-story-game/privacy-and-grounding` | Guide/reference without an application or evaluation model consumer; retained as repository documentation. |
| `memoir/skills/memoir-place-photo-research/llm-web-search` | Guide/reference without an application or evaluation model consumer; retained as repository documentation. |
| `memoir/skills/memoir-place-photo-research/record-format` | Guide/reference without an application or evaluation model consumer; retained as repository documentation. |
| `memoir/skills/memoir-place-photo-research/source-strategy` | Guide/reference without an application or evaluation model consumer; retained as repository documentation. |

The earlier cleanup also removed the retired journalist, workspace/marker,
fallback, browser wrapper and obsolete migration prompts.

## Migration and verification

53 names moved to their owner namespace. All 85 retained versions were verified
for exact text, config, tags, labels and commit message; numeric version order is
preserved. The public prompt API creates new records when moving names, so moved
versions have new IDs and timestamps. Original IDs and metadata are backed up in
`var/langfuse-skill-ownership-backup-20261018.json` outside Git. The 11 unused names
were removed after destination verification. Dataset items and prior experiment
records were not rewritten.

All 69 assembled source hashes and 18 phase/locale/feature contract hashes match
the inputs before this ownership refactor. Bounded request admission still checks
schema, authoritative page, privacy, token budget and publication fences. No live
model evaluation, deployment or service restart is implied by these checks.

## NovelToGame default builder (27 October 2026)

`memoir-story-game` retains the scene-pool and owner-confirmation boundary.
Both planning calls and the default staged builder use GPT-6.1 Sol max.
`apps/api/novel_game.py` loads managed adapter, journey and asset policies plus
per-stage prompts under `memoir/skills/memoir-story-game/novel-to-game/`:
`analyze`, `concept`, `design`, `whitebox`, `art`, `production` and the standalone
`production_style` repair. Exact published versions are the sibling receipts.
Upstream NovelToGame Markdown is loaded separately from the reviewed dependency
and its content digest is recorded; it is not copied into Langfuse. The retained
Higgsfield/Astra prompts serve the explicitly configured backup.
