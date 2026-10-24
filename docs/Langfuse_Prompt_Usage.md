# Prompt ownership and usage

Verified on 18 October 2026. The catalog contains **69 model-consumed sources**:
20 runtime, 21 conditional runtime, 10 shared runtime, and 18 evaluation inputs.
The application and exporter use the same explicit catalog in
`apps/api/prompt_catalog.py`. Each source has one owner, one name and one exact
version receipt. These are caller-level classifications, not traffic counts.

The interviewer rows were refreshed on 22 October. The privacy optimization adds
one conditional opening template, making 24 catalog entries, all at the skill
root. Language, strategy, greeting and repair names are flat. None are classified
as retired. Changed and new sources below await main-only publication; existing
receipts remain untouched until then. The remaining rows retain the original
audit date. See the
[layout and migration details](Langfuse_Prompt_Structure_Refactor.md).

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
the other supported modes assemble their own prompts. The 24-entry inventory is
not the prompt input for every turn. See the
[profiled optimization](issue53-policy-repair-20261022.md), including slower
held-out cases and the remaining deployment/acceptance gates.

## Ownership

- `memoir/skills/<skill>/...` owns the skill's instructions, phases and reusable policy.
  Its repository sources live under `skills/<skill>/`.
- `memoir/shared/...` owns bounded-context instructions shared by timeline and composer.
- `memoir/evaluation/...` owns judge instructions and synthetic probe fixtures.
- `memoir/speech/...` owns synthesis instructions.

`lane`, `two-lane` and `organiser-job` are execution details, not parallel prompt
owners. Composer batch preparation and composition now belong to composer;
place/question fields extend the existing timeline request. The foreground
collector has its own background-memory guidance.

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

## Every retained prompt

| Langfuse name | Version | Classification | Consumer / condition |
| --- | ---: | --- | --- |
| [`memoir/evaluation/five-case-judge`](../tests/evaluation/memoir_five_case_judge_prompt.md) | 1 | Evaluation only | [`scripts/run_memoir_five_case_semantic_judge.py`](../scripts/run_memoir_five_case_semantic_judge.py) — Five-case semantic judge template. |
| [`memoir/evaluation/five-case-judge/guard`](../tests/evaluation/prompts/five-case-judge/guard.md) | 1 | Evaluation only | [`scripts/run_memoir_five_case_semantic_judge.py`](../scripts/run_memoir_five_case_semantic_judge.py) — Semantic judge guard for retained evaluation evidence. |
| [`memoir/evaluation/live-skills/historical-lead`](../tests/evaluation/prompts/live-skills/historical-lead.md) | 1 | Evaluation only | [`scripts/memoir_live_skill_cases.py`](../scripts/memoir_live_skill_cases.py) — Isolated live-skill contract probe; no production persistence. |
| [`memoir/evaluation/live-skills/independent-events`](../tests/evaluation/prompts/live-skills/independent-events.md) | 1 | Evaluation only | [`scripts/run_memoir_live_skills.py`](../scripts/run_memoir_live_skills.py) — Isolated live-skill evaluation instructions. |
| [`memoir/evaluation/live-skills/native-search`](../tests/evaluation/prompts/live-skills/native-search.md) | 1 | Evaluation only | [`scripts/run_memoir_live_skills.py`](../scripts/run_memoir_live_skills.py) — Isolated live-skill evaluation instructions. |
| [`memoir/evaluation/live-skills/photo-lead`](../tests/evaluation/prompts/live-skills/photo-lead.md) | 1 | Evaluation only | [`scripts/memoir_live_skill_cases.py`](../scripts/memoir_live_skill_cases.py) — Isolated live-skill contract probe; no production persistence. |
| [`memoir/evaluation/live-skills/place-groups`](../tests/evaluation/prompts/live-skills/place-groups.md) | 1 | Evaluation only | [`scripts/memoir_live_skill_cases.py`](../scripts/memoir_live_skill_cases.py) — Isolated live-skill contract probe; no production persistence. |
| [`memoir/evaluation/live-skills/story-game`](../tests/evaluation/prompts/live-skills/story-game.md) | 3 | Evaluation only | [`scripts/memoir_live_skill_cases.py`](../scripts/memoir_live_skill_cases.py) — Isolated live-skill contract probe; no production persistence. |
| [`memoir/evaluation/trajectory-judge/rubric`](../apps/api/prompts/evaluation/trajectory-judge/rubric.md) | 1 | Evaluation only | [`apps/api/trajectory_evaluation.py`](../apps/api/trajectory_evaluation.py) — Trajectory evaluation judge; not a storyteller turn. |
| [`memoir/evaluation/trajectory-judge/system`](../apps/api/prompts/evaluation/trajectory-judge/system.md) | 1 | Evaluation only | [`apps/api/trajectory_evaluation.py`](../apps/api/trajectory_evaluation.py) — Trajectory evaluation judge; not a storyteller turn. |
| [`memoir/shared/bounded-context/en-AU`](../apps/api/prompts/shared/bounded-context/en-AU.md) | 2 | Runtime | [`apps/api/lifetime_memory_lane_engine.py`](../apps/api/lifetime_memory_lane_engine.py) — English edition suffix for a bounded partition; not a second lane. |
| [`memoir/shared/bounded-context/policy`](../apps/api/prompts/shared/bounded-context/policy.md) | 1 | Shared runtime | [`apps/api/lifetime_memory_lane_engine.py`](../apps/api/lifetime_memory_lane_engine.py) — One privacy/evidence policy shared by both edition locales. |
| [`memoir/shared/bounded-context/zh-CN`](../apps/api/prompts/shared/bounded-context/zh-CN.md) | 2 | Runtime | [`apps/api/lifetime_memory_lane_engine.py`](../apps/api/lifetime_memory_lane_engine.py) — Chinese edition suffix for a bounded partition; not a second lane. |
| [`memoir/shared/place-conflicts`](../apps/api/prompts/shared/place-conflicts.md) | 1 | Conditional runtime | [`apps/api/lifetime_memory_lane_engine.py`](../apps/api/lifetime_memory_lane_engine.py) — Appended only when a page has attribution coverage. |
| [`memoir/skills/memoir-historical-news-research/contract`](../skills/memoir-historical-news-research/references/contract.md) | 1 | Evaluation only | [`scripts/memoir_live_skill_cases.py`](../scripts/memoir_live_skill_cases.py) — Explicit isolated probe/native-search model input; does not prove a production binding. |
| [`memoir/skills/memoir-historical-news-research/discovery`](../skills/memoir-historical-news-research/prompts/discovery.md) | 1 | Conditional runtime | [`apps/api/historical_news_provider.py`](../apps/api/historical_news_provider.py) — Optional public-history provider discovery, behind its rollout flag. |
| [`memoir/skills/memoir-historical-news-research/instructions`](../skills/memoir-historical-news-research/SKILL.md) | 2 | Evaluation only | [`scripts/memoir_live_skill_cases.py`](../scripts/memoir_live_skill_cases.py) — Explicit isolated probe/native-search model input; does not prove a production binding. |
| [`memoir/skills/memoir-author-timeline/attribution`](../skills/memoir-author-timeline/prompts/attribution.md) | 1 | Conditional runtime | [`apps/api/two_lane_memory.py`](../apps/api/two_lane_memory.py) — Additional attribution output only for an attributed two-lane source page. |
| [`memoir/skills/memoir-author-timeline/contract`](../skills/memoir-author-timeline/references/contract.md) | 1 | Shared runtime | [`apps/api/memory_events.py`](../apps/api/memory_events.py) — Schema/evidence component in both timeline variants. |
| [`memoir/skills/memoir-author-timeline/derived-hints`](../skills/memoir-author-timeline/prompts/derived-hints.md) | 1 | Conditional runtime | [`apps/api/two_lane_memory.py`](../apps/api/two_lane_memory.py) — Optional derived fields on the same extraction call. |
| [`memoir/skills/memoir-author-timeline/extract`](../skills/memoir-author-timeline/prompts/extract.md) | 3 | Runtime | [`apps/api/memory_events.py`](../apps/api/memory_events.py) — Events-only schema in the canonical timeline lane. |
| [`memoir/skills/memoir-author-timeline/extract-with-hints`](../skills/memoir-author-timeline/prompts/extract-with-hints.md) | 2 | Conditional runtime | [`apps/api/two_lane_memory.py`](../apps/api/two_lane_memory.py) — Same extraction request with additional place/question fields when MEMOIR_TWO_LANES is enabled. |
| [`memoir/skills/memoir-author-timeline/instructions`](../skills/memoir-author-timeline/SKILL.md) | 1 | Shared runtime | [`apps/api/memory_events.py`](../apps/api/memory_events.py) — Canonical extraction instruction component. |
| [`memoir/skills/memoir-author-timeline/shared/grounding`](../skills/memoir-author-timeline/prompts/shared/grounding.md) | 1 | Shared runtime | [`apps/api/memory_events.py`](../apps/api/memory_events.py) — Grounding rules shared by both extraction schemas. |
| [`memoir/skills/memoir-author-timeline/window`](../skills/memoir-author-timeline/prompts/window.md) | 1 | Runtime | [`apps/api/lifetime_memory_composer.py`](../apps/api/lifetime_memory_composer.py) — Bounded source-window instructions in the extraction packet. |
| [`memoir/skills/memoir-composer/batch/compose`](../skills/memoir-composer/prompts/batch/compose.md) | 1 | Runtime | [`apps/api/lifetime_memory_lane_engine.py`](../apps/api/lifetime_memory_lane_engine.py) — Batch-specific drafting/review instructions in the same canonical composer. |
| [`memoir/skills/memoir-composer/batch/prepare`](../skills/memoir-composer/prompts/batch/prepare.md) | 1 | Runtime | [`apps/api/lifetime_memory_lane_engine.py`](../apps/api/lifetime_memory_lane_engine.py) — Batch-specific preparation instructions in the same canonical composer. |
| [`memoir/skills/memoir-composer/draft`](../skills/memoir-composer/prompts/draft.md) | 2 | Runtime | [`apps/api/memoir_preview.py`](../apps/api/memoir_preview.py) — Canonical draft phase; shares event IDs and evidence with extraction. |
| [`memoir/skills/memoir-composer/outline/leaf/en-AU`](../skills/memoir-composer/prompts/outline/leaf/en-AU.md) | 2 | Conditional runtime | [`apps/api/lifetime_memory_job_engine.py`](../apps/api/lifetime_memory_job_engine.py) — Leaf paid-book organisation, en-AU; same job runner, different input-reference field/output language. |
| [`memoir/skills/memoir-composer/outline/leaf/zh-CN`](../skills/memoir-composer/prompts/outline/leaf/zh-CN.md) | 2 | Conditional runtime | [`apps/api/lifetime_memory_job_engine.py`](../apps/api/lifetime_memory_job_engine.py) — Leaf paid-book organisation, zh-CN; same job runner, different input-reference field/output language. |
| [`memoir/skills/memoir-composer/outline/merge/en-AU`](../skills/memoir-composer/prompts/outline/merge/en-AU.md) | 2 | Conditional runtime | [`apps/api/lifetime_memory_job_engine.py`](../apps/api/lifetime_memory_job_engine.py) — Merge paid-book organisation, en-AU; same job runner, different input-reference field/output language. |
| [`memoir/skills/memoir-composer/outline/merge/zh-CN`](../skills/memoir-composer/prompts/outline/merge/zh-CN.md) | 2 | Conditional runtime | [`apps/api/lifetime_memory_job_engine.py`](../apps/api/lifetime_memory_job_engine.py) — Merge paid-book organisation, zh-CN; same job runner, different input-reference field/output language. |
| [`memoir/skills/memoir-composer/outline/shared/prefix`](../skills/memoir-composer/prompts/outline/shared/prefix.md) | 1 | Shared runtime | [`apps/api/lifetime_memory_job_engine.py`](../apps/api/lifetime_memory_job_engine.py) — One bounded paid-collection policy shared by leaf/merge and both locales. |
| [`memoir/skills/memoir-composer/outline/shared/suffix`](../skills/memoir-composer/prompts/outline/shared/suffix.md) | 1 | Shared runtime | [`apps/api/lifetime_memory_job_engine.py`](../apps/api/lifetime_memory_job_engine.py) — One reference/size policy shared by leaf/merge and both locales. |
| [`memoir/skills/memoir-composer/prepare`](../skills/memoir-composer/prompts/prepare.md) | 1 | Runtime | [`apps/api/canonical_composer.py`](../apps/api/canonical_composer.py) — Prepare source-linked context before drafting. |
| [`memoir/skills/memoir-composer/review`](../skills/memoir-composer/prompts/review.md) | 3 | Runtime | [`apps/api/memoir_preview.py`](../apps/api/memoir_preview.py) — Review the generated candidate against original evidence. |
| [`memoir/skills/memoir-composer/shared/editorial-review`](../skills/memoir-composer/references/editorial-review.prompt.md) | 1 | Shared runtime | [`apps/api/memoir_preview.py`](../apps/api/memoir_preview.py) — Review-only editorial component. |
| [`memoir/skills/memoir-composer/shared/narrative-enrichment`](../skills/memoir-composer/references/narrative-enrichment.md) | 1 | Shared runtime | [`apps/api/memoir_preview.py`](../apps/api/memoir_preview.py) — Single narrative policy read by drafting and review. |
| [`memoir/skills/memoir-family-tree/instructions`](../skills/memoir-family-tree/SKILL.md) | 1 | Evaluation only | [`scripts/memoir_live_skill_cases.py`](../scripts/memoir_live_skill_cases.py) — Explicit isolated probe/native-search model input; does not prove a production binding. |
| [`memoir/skills/memoir-interviewer/reply`](../skills/memoir-interviewer/prompts/reply.md) | 1 | Runtime | [`apps/api/conversation_reply.py`](../apps/api/conversation_reply.py) — Small foreground proposal for `reply-v2`; locale and strategy arrive as data. |
| [`memoir/skills/memoir-interviewer/policy-review`](../skills/memoir-interviewer/prompts/policy-review.md) | Pending | Runtime | [`apps/api/policy_review.py`](../apps/api/policy_review.py) — Source-only privacy policy review before the governed reply; changed source awaits publication. |
| [`memoir/skills/memoir-interviewer/policy-review-opening`](../skills/memoir-interviewer/prompts/policy-review-opening.md) | Pending | Conditional runtime | [`apps/api/policy_review.py`](../apps/api/policy_review.py) — Composes the core once with original style guidance only when early acknowledgement is requested. |
| [`memoir/skills/memoir-interviewer/repair-codes`](../skills/memoir-interviewer/prompts/governed-repair/codes.md) | Pending | Conditional runtime | [`apps/api/lifetime_memory_engine.py`](../apps/api/lifetime_memory_engine.py) — Managed rule catalog; only common guidance and the matching rule enter a bounded repair. |
| [`memoir/skills/memoir-interviewer/governed-places`](../skills/memoir-interviewer/prompts/governed-places.md) | 1 | Compatibility runtime | [`apps/api/lifetime_memory_runtime.py`](../apps/api/lifetime_memory_runtime.py) — Foreground place extraction when background extraction is disabled. |
| [`memoir/skills/memoir-interviewer/background-memory`](../skills/memoir-interviewer/prompts/background-memory.md) | 2 | Compatibility runtime | [`apps/api/lifetime_memory_runtime.py`](../apps/api/lifetime_memory_runtime.py) — Optional foreground hint when background extraction owns place work. |
| [`memoir/skills/memoir-interviewer/collector`](../skills/memoir-interviewer/prompts/collector.md) | 2 | Compatibility runtime | [`apps/api/lifetime_memory_runtime.py`](../apps/api/lifetime_memory_runtime.py) — Default foreground collector; one governed request. |
| [`memoir/skills/memoir-interviewer/collector-plan`](../skills/memoir-interviewer/prompts/collector-plan.md) | 4 | Compatibility runtime | [`apps/api/interview_plan.py`](../apps/api/interview_plan.py) — Structured result/plan contract appended to the default collector. |
| [`memoir/skills/memoir-interviewer/governed-continuity`](../skills/memoir-interviewer/prompts/governed-continuity.md) | 3 | Compatibility runtime | [`apps/api/lifetime_memory_runtime.py`](../apps/api/lifetime_memory_runtime.py) — Continuity output contract appended to the same collector call. |
| [`memoir/skills/memoir-interviewer/repair-acknowledgement`](../skills/memoir-interviewer/prompts/governed-repair/acknowledgement.md) | 1 | Conditional runtime | [`apps/api/lifetime_memory_engine.py`](../apps/api/lifetime_memory_engine.py) — Retain the already streamed acknowledgement during bounded repair. |
| [`memoir/skills/memoir-interviewer/repair-prefix`](../skills/memoir-interviewer/prompts/governed-repair/prefix.md) | 1 | Conditional runtime | [`apps/api/lifetime_memory_engine.py`](../apps/api/lifetime_memory_engine.py) — Bounded repair prefix after a rejected collector output. |
| [`memoir/skills/memoir-interviewer/repair-suffix`](../skills/memoir-interviewer/prompts/governed-repair/suffix.md) | 1 | Conditional runtime | [`apps/api/lifetime_memory_engine.py`](../apps/api/lifetime_memory_engine.py) — Bounded repair suffix after a rejected collector output. |
| [`memoir/skills/memoir-interviewer/governed-turn`](../skills/memoir-interviewer/prompts/governed-turn.md) | 1 | Runtime | [`apps/api/lifetime_memory_engine.py`](../apps/api/lifetime_memory_engine.py) — Structured governed user packet, not a second collector workflow. |
| [`memoir/skills/memoir-interviewer/greeting-begin`](../skills/memoir-interviewer/prompts/greeting/begin.md) | 1 | Runtime | [`apps/api/agent_routes.py`](../apps/api/agent_routes.py) — Server-owned begin action through the same governed conversation transport. |
| [`memoir/skills/memoir-interviewer/greeting-continue`](../skills/memoir-interviewer/prompts/greeting/continue.md) | 1 | Runtime | [`apps/api/agent_routes.py`](../apps/api/agent_routes.py) — Server-owned return action through the same governed conversation transport. |
| [`memoir/skills/memoir-interviewer/guidance`](../skills/memoir-interviewer/prompts/guidance.md) | 4 | Compatibility runtime | [`apps/api/prompt_composition.py`](../apps/api/prompt_composition.py) — One behavior component shared by the default collector and three strategy variants. |
| [`memoir/skills/memoir-interviewer/language-en-AU`](../skills/memoir-interviewer/prompts/language/en-AU.md) | 1 | Compatibility runtime | [`apps/api/codex_runtime.py`](../apps/api/codex_runtime.py) — Select the English interview policy; does not create another generation. |
| [`memoir/skills/memoir-interviewer/language-zh-CN`](../skills/memoir-interviewer/prompts/language/zh-CN.md) | 1 | Compatibility runtime | [`apps/api/codex_runtime.py`](../apps/api/codex_runtime.py) — Select the Chinese interview policy; does not create another generation. |
| [`memoir/skills/memoir-interviewer/privacy-guard`](../skills/memoir-interviewer/prompts/privacy-guard.md) | 1 | Compatibility runtime | [`apps/api/lifetime_memory_runtime.py`](../apps/api/lifetime_memory_runtime.py) — Default collector privacy rule in the existing request. |
| [`memoir/skills/memoir-interviewer/strategy-comfort`](../skills/memoir-interviewer/prompts/strategy/comfort.md) | 2 | Compatibility runtime | [`apps/api/interview_strategy.py`](../apps/api/interview_strategy.py) — Comfort selection within the existing foreground collector, gated by two-lane/strategy configuration. |
| [`memoir/skills/memoir-interviewer/strategy-explore`](../skills/memoir-interviewer/prompts/strategy/explore.md) | 2 | Compatibility runtime | [`apps/api/interview_strategy.py`](../apps/api/interview_strategy.py) — Explore selection within the existing foreground collector, gated by two-lane/strategy configuration. |
| [`memoir/skills/memoir-interviewer/strategy-proposal`](../skills/memoir-interviewer/prompts/strategy/proposal.md) | 1 | Conditional runtime | [`apps/api/two_lane_memory.py`](../apps/api/two_lane_memory.py) — Optional future-strategy output on that extraction call. |
| [`memoir/skills/memoir-interviewer/strategy-selection`](../skills/memoir-interviewer/prompts/strategy/selection.md) | 6 | Compatibility runtime | [`apps/api/interview_strategy.py`](../apps/api/interview_strategy.py) — One selection/work-hint contract shared by the three strategies. |
| [`memoir/skills/memoir-interviewer/strategy-shape`](../skills/memoir-interviewer/prompts/strategy/shape.md) | 2 | Compatibility runtime | [`apps/api/interview_strategy.py`](../apps/api/interview_strategy.py) — Shape selection within the existing foreground collector, gated by two-lane/strategy configuration. |
| [`memoir/skills/memoir-memory-context/instructions`](../skills/memoir-memory-context/SKILL.md) | 1 | Runtime | [`apps/api/background_profile.py`](../apps/api/background_profile.py) — Automatic profile extraction for currently admitted targets. |
| [`memoir/skills/memoir-memory-context/summary`](../skills/memoir-memory-context/prompts/summary.md) | 1 | Runtime | [`apps/api/lifetime_memory_summary.py`](../apps/api/lifetime_memory_summary.py) — Canonical source-linked memory summary phase. |
| [`memoir/skills/memoir-place-groups/instructions`](../skills/memoir-place-groups/SKILL.md) | 1 | Evaluation only | [`scripts/memoir_live_skill_cases.py`](../scripts/memoir_live_skill_cases.py) — Explicit isolated probe/native-search model input; does not prove a production binding. |
| [`memoir/skills/memoir-place-journey/extraction`](../skills/memoir-place-journey/references/two-lane.md) | 1 | Conditional runtime | [`apps/api/two_lane_memory.py`](../apps/api/two_lane_memory.py) — Place-specific schema guidance on the same optional extraction request. |
| [`memoir/skills/memoir-place-journey/instructions`](../skills/memoir-place-journey/SKILL.md) | 1 | Evaluation only | [`scripts/memoir_live_skill_cases.py`](../scripts/memoir_live_skill_cases.py) — Explicit isolated probe/native-search model input; does not prove a production binding. |
| [`memoir/skills/memoir-story-game/instructions`](../skills/memoir-story-game/SKILL.md) | 4 | Shared runtime | [`apps/api/story_game_runtime.py`](../apps/api/story_game_runtime.py) — Shared system instructions for the scene-pool and confirmed-brief planning phases. |
| [`memoir/skills/memoir-story-game/proposal`](../skills/memoir-story-game/prompts/proposal.md) | 3 | Runtime, step 1 | [`apps/api/story_game_runtime.py`](../apps/api/story_game_runtime.py) — Composer chapters plus canonical timeline to a full scene pool with recommendations; then pause for owner selection. |
| [`memoir/skills/memoir-story-game/brief`](../skills/memoir-story-game/prompts/brief.md) | 1 | Runtime, step 2 | [`apps/api/story_game_runtime.py`](../apps/api/story_game_runtime.py) — Composer model prepares the exact confirmed subset's creative brief. |
| [`memoir/skills/memoir-story-game/higgsfield`](../skills/memoir-story-game/prompts/higgsfield.md) | 1 | Delegated build | [`apps/api/higgsfield_game.py`](../apps/api/higgsfield_game.py) — Astra adapter for the independently installed upstream game skill and private export target. |
| [`memoir/skills/memoir-story-game/webpage`](../skills/memoir-story-game/prompts/webpage.md) | 2 | Delegated build | [`apps/api/higgsfield_game.py`](../apps/api/higgsfield_game.py) — Memoir HTML/CSS export contract for the separate Higgsfield game builder. |
| [`memoir/skills/memoir-story-game/runtime-contract`](../skills/memoir-story-game/references/runtime-contract.md) | 5 | Evaluation only | [`scripts/memoir_live_skill_cases.py`](../scripts/memoir_live_skill_cases.py) — Separate host-admission audit, outside the two generation phases. |
| [`memoir/skills/memoir-place-photo-research/instructions`](../skills/memoir-place-photo-research/SKILL.md) | 2 | Evaluation only | [`scripts/memoir_live_skill_cases.py`](../scripts/memoir_live_skill_cases.py) — Explicit isolated probe/native-search model input; does not prove a production binding. |
| [`memoir/speech/default`](../apps/api/prompts/speech/default.md) | 1 | Conditional runtime | [`apps/api/speech.py`](../apps/api/speech.py) — Voice delivery instructions selected by locale; only used for synthesis. |
| [`memoir/speech/en-AU`](../apps/api/prompts/speech/en-AU.md) | 1 | Conditional runtime | [`apps/api/speech.py`](../apps/api/speech.py) — Voice delivery instructions selected by locale; only used for synthesis. |
| [`memoir/speech/zh-CN`](../apps/api/prompts/speech/zh-CN.md) | 1 | Conditional runtime | [`apps/api/speech.py`](../apps/api/speech.py) — Voice delivery instructions selected by locale; only used for synthesis. |

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
