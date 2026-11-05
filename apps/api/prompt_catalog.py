"""Model-consumed prompt sources, owned by an agent, skill or shared workflow."""

PROMPT_PATHS = {
    'memoir/agents/mira/reply': 'apps/api/prompts/mira/system.md',
    'memoir/agents/mira/policy-review': 'apps/api/prompts/mira/policy-review.md',
    'memoir/agents/mira/repair': 'apps/api/prompts/mira/repair.md',
    'memoir/agents/mira/repair-codes': 'apps/api/prompts/mira/repair-codes.md',
    'memoir/agents/atlas/skill-selection': 'apps/api/prompts/atlas/system.md',
    'memoir/shared/skill-agent': 'apps/api/prompts/skill-agent.md',
    'memoir/skills/composer/instructions': 'skills/memoir-composer/SKILL.md',
    **{'memoir/skills/story-game/novel-to-game/' + name:
       'skills/memoir-story-game/prompts/novel-to-game/' + name + '.md'
       for name in ('adapter', 'journey', 'assets', 'analyze', 'concept', 'design',
                    'whitebox', 'art', 'production', 'production_style', 'illustration')},
    'memoir/skills/author-timeline/continuity': 'skills/memoir-author-timeline/prompts/continuity.md',
    'memoir/evaluators/shared/semantic-boundaries': 'apps/api/prompts/evaluation/semantic-boundaries-judge.md',
    'memoir/skills/place-photo-research/discovery': 'skills/memoir-place-photo-research/prompts/discovery.md',
    'memoir/shared/historical-acknowledgements': 'apps/api/prompts/shared/historical-acknowledgements.md',
    'memoir/shared/recall-invitations': 'apps/api/prompts/shared/recall-invitations.md',
    'memoir/probes/providers/connectivity': 'apps/api/prompts/evaluation/probes/connectivity.md',
    'memoir/probes/providers/worker': 'apps/api/prompts/evaluation/probes/worker.md',
    'memoir/probes/providers/web-search': 'apps/api/prompts/evaluation/probes/web-search.md',
    'memoir/evaluators/workflows/five-case-memoir/trajectory': 'tests/evaluation/memoir_five_case_judge_prompt.md',
    'memoir/evaluators/workflows/five-case-memoir/guard': 'tests/evaluation/prompts/five-case-judge/guard.md',
    'memoir/probes/skills/historical-news-research/discovery': 'tests/evaluation/prompts/live-skills/historical-lead.md',
    'memoir/probes/skills/author-timeline/extract': 'tests/evaluation/prompts/live-skills/independent-events.md',
    'memoir/probes/shared/native-search': 'tests/evaluation/prompts/live-skills/native-search.md',
    'memoir/probes/skills/place-photo-research/discovery': 'tests/evaluation/prompts/live-skills/photo-lead.md',
    'memoir/probes/skills/place-groups/group': 'tests/evaluation/prompts/live-skills/place-groups.md',
    'memoir/probes/skills/story-game/brief': 'tests/evaluation/prompts/live-skills/story-game.md',
    'memoir/evaluators/shared/trajectory/rubric': 'apps/api/prompts/evaluation/trajectory-judge/rubric.md',
    'memoir/evaluators/shared/trajectory/system': 'apps/api/prompts/evaluation/trajectory-judge/system.md',
    'memoir/shared/bounded-context/en-AU': 'apps/api/prompts/shared/bounded-context/en-AU.md',
    'memoir/shared/bounded-context/policy': 'apps/api/prompts/shared/bounded-context/policy.md',
    'memoir/shared/bounded-context/zh-CN': 'apps/api/prompts/shared/bounded-context/zh-CN.md',
    'memoir/shared/place-conflicts': 'apps/api/prompts/shared/place-conflicts.md',
    'memoir/skills/historical-news-research/contract': 'skills/memoir-historical-news-research/references/contract.md',
    'memoir/skills/historical-news-research/discovery': 'skills/memoir-historical-news-research/prompts/requests/discovery.md',
    'memoir/skills/historical-news-research/components/discovery': 'skills/memoir-historical-news-research/prompts/discovery.md',
    'memoir/skills/historical-news-research/instructions': 'skills/memoir-historical-news-research/SKILL.md',
    'memoir/skills/author-timeline/attribution': 'skills/memoir-author-timeline/prompts/attribution.md',
    'memoir/skills/author-timeline/contract': 'skills/memoir-author-timeline/references/contract.md',
    'memoir/skills/author-timeline/derived-hints': 'skills/memoir-author-timeline/prompts/derived-hints.md',
    'memoir/skills/author-timeline/extract': 'skills/memoir-author-timeline/prompts/requests/extract.md',
    'memoir/skills/author-timeline/components/extract': 'skills/memoir-author-timeline/prompts/extract.md',
    'memoir/skills/author-timeline/extract-with-hints': 'skills/memoir-author-timeline/prompts/extract-with-hints.md',
    'memoir/skills/author-timeline/instructions': 'skills/memoir-author-timeline/SKILL.md',
    'memoir/skills/author-timeline/shared/grounding': 'skills/memoir-author-timeline/prompts/shared/grounding.md',
    'memoir/skills/author-timeline/window': 'skills/memoir-author-timeline/prompts/window.md',
    'memoir/skills/composer/batch/compose': 'skills/memoir-composer/prompts/batch/compose.md',
    'memoir/skills/composer/batch/prepare': 'skills/memoir-composer/prompts/batch/prepare.md',
    'memoir/skills/composer/draft': 'skills/memoir-composer/prompts/requests/draft.md',
    'memoir/skills/composer/components/draft': 'skills/memoir-composer/prompts/draft.md',
    'memoir/skills/composer/outline/leaf/en-AU': 'skills/memoir-composer/prompts/outline/leaf/en-AU.md',
    'memoir/skills/composer/outline/leaf/zh-CN': 'skills/memoir-composer/prompts/outline/leaf/zh-CN.md',
    'memoir/skills/composer/outline/merge/en-AU': 'skills/memoir-composer/prompts/outline/merge/en-AU.md',
    'memoir/skills/composer/outline/merge/zh-CN': 'skills/memoir-composer/prompts/outline/merge/zh-CN.md',
    'memoir/skills/composer/outline/shared/prefix': 'skills/memoir-composer/prompts/outline/shared/prefix.md',
    'memoir/skills/composer/outline/shared/suffix': 'skills/memoir-composer/prompts/outline/shared/suffix.md',
    'memoir/skills/composer/prepare': 'skills/memoir-composer/prompts/requests/prepare.md',
    'memoir/skills/composer/components/prepare': 'skills/memoir-composer/prompts/prepare.md',
    'memoir/skills/composer/review': 'skills/memoir-composer/prompts/requests/review.md',
    'memoir/skills/composer/components/review': 'skills/memoir-composer/prompts/review.md',
    'memoir/skills/composer/shared/editorial-review': 'skills/memoir-composer/references/editorial-review.prompt.md',
    'memoir/skills/composer/shared/narrative-enrichment': 'skills/memoir-composer/references/narrative-enrichment.md',
    'memoir/skills/family-tree/extract': 'skills/memoir-family-tree/SKILL.md',
    'memoir/skills/memory-context/profile': 'skills/memoir-memory-context/prompts/requests/profile.md',
    'memoir/skills/memory-context/components/profile': 'skills/memoir-memory-context/SKILL.md',
    'memoir/skills/memory-context/summary': 'skills/memoir-memory-context/prompts/requests/summary.md',
    'memoir/skills/memory-context/components/summary': 'skills/memoir-memory-context/prompts/summary.md',
    'memoir/probes/skills/place-groups/instructions': 'skills/memoir-place-groups/SKILL.md',
    'memoir/skills/place-journey/extract': 'skills/memoir-place-journey/prompts/requests/extract.md',
    'memoir/skills/place-journey/components/extract': 'skills/memoir-place-journey/references/two-lane.md',
    'memoir/skills/place-journey/instructions': 'skills/memoir-place-journey/SKILL.md',
    'memoir/skills/story-game/instructions': 'skills/memoir-story-game/SKILL.md',
    'memoir/skills/story-game/proposal': 'skills/memoir-story-game/prompts/requests/proposal.md',
    'memoir/skills/story-game/components/proposal': 'skills/memoir-story-game/prompts/proposal.md',
    'memoir/skills/story-game/brief': 'skills/memoir-story-game/prompts/requests/brief.md',
    'memoir/skills/story-game/components/brief': 'skills/memoir-story-game/prompts/brief.md',
    'memoir/skills/story-game/higgsfield': 'skills/memoir-story-game/prompts/requests/higgsfield.md',
    'memoir/skills/story-game/components/higgsfield': 'skills/memoir-story-game/prompts/higgsfield.md',
    'memoir/skills/story-game/webpage': 'skills/memoir-story-game/prompts/webpage.md',
    'memoir/skills/story-game/runtime-contract': 'skills/memoir-story-game/references/runtime-contract.md',
    'memoir/skills/place-photo-research/instructions': 'skills/memoir-place-photo-research/SKILL.md',
    'memoir/workflows/speech/synthesis/default': 'apps/api/prompts/speech/default.md',
    'memoir/workflows/speech/synthesis/en-AU': 'apps/api/prompts/speech/en-AU.md',
    'memoir/workflows/speech/synthesis/zh-CN': 'apps/api/prompts/speech/zh-CN.md',
}

# Local sources retain hashes and evaluation coverage, without separate Langfuse rows.
LOCAL_PROMPT_NAMES = frozenset({
    *[name for name in PROMPT_PATHS if '/components/' in name],
    *[name for name in PROMPT_PATHS if name.startswith('memoir/skills/author-timeline/')
      and name != 'memoir/skills/author-timeline/extract'],
    *[name for name in PROMPT_PATHS if name.startswith('memoir/shared/bounded-context/')],
    *[name for name in PROMPT_PATHS if name.startswith('memoir/skills/composer/batch/')
      or '/outline/shared/' in name or name.startswith('memoir/skills/composer/shared/')],
    'memoir/shared/place-conflicts',
})

PROMPT_PATHS['memoir/skills/story-game/novel-to-game/analyze'] = 'skills/memoir-story-game/prompts/novel-to-game/requests/analyze.md'
PROMPT_PATHS['memoir/skills/story-game/novel-to-game/components/analyze'] = 'skills/memoir-story-game/prompts/novel-to-game/analyze.md'

PROMPT_PATHS['memoir/skills/story-game/novel-to-game/concept'] = 'skills/memoir-story-game/prompts/novel-to-game/requests/concept.md'
PROMPT_PATHS['memoir/skills/story-game/novel-to-game/components/concept'] = 'skills/memoir-story-game/prompts/novel-to-game/concept.md'

PROMPT_PATHS['memoir/skills/story-game/novel-to-game/design'] = 'skills/memoir-story-game/prompts/novel-to-game/requests/design.md'
PROMPT_PATHS['memoir/skills/story-game/novel-to-game/components/design'] = 'skills/memoir-story-game/prompts/novel-to-game/design.md'

PROMPT_PATHS['memoir/skills/story-game/novel-to-game/whitebox'] = 'skills/memoir-story-game/prompts/novel-to-game/requests/whitebox.md'
PROMPT_PATHS['memoir/skills/story-game/novel-to-game/components/whitebox'] = 'skills/memoir-story-game/prompts/novel-to-game/whitebox.md'

PROMPT_PATHS['memoir/skills/story-game/novel-to-game/art'] = 'skills/memoir-story-game/prompts/novel-to-game/requests/art.md'
PROMPT_PATHS['memoir/skills/story-game/novel-to-game/components/art'] = 'skills/memoir-story-game/prompts/novel-to-game/art.md'

PROMPT_PATHS['memoir/skills/story-game/novel-to-game/production'] = 'skills/memoir-story-game/prompts/novel-to-game/requests/production.md'
PROMPT_PATHS['memoir/skills/story-game/novel-to-game/components/production'] = 'skills/memoir-story-game/prompts/novel-to-game/production.md'

LOCAL_PROMPT_NAMES = LOCAL_PROMPT_NAMES | frozenset({
    *[name for name in PROMPT_PATHS if '/components/' in name],
    'memoir/skills/historical-news-research/instructions',
    'memoir/skills/historical-news-research/contract',
    'memoir/skills/story-game/instructions',
    'memoir/skills/story-game/webpage',
    *['memoir/skills/story-game/novel-to-game/' + p for p in ('adapter', 'journey', 'assets')],
    'memoir/skills/composer/instructions',
    'memoir/skills/place-journey/instructions',
    'memoir/skills/place-photo-research/instructions',
})
