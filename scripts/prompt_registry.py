"""Repository artifacts whose text is versioned in Memoir's Langfuse project."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SPECIAL = {
    "memoir/evaluation/five-case-judge": "tests/evaluation/memoir_five_case_judge_prompt.md",
}

# Adding a skill directory alone must not publish its docs as runtime prompts.
MODEL_FACING_SKILLS = {
    'historical-news-research', 'memoir-author-timeline', 'memoir-composer',
    'memoir-family-tree', 'memoir-memory-context', 'memoir-place-groups',
    'memoir-place-journey', 'memoir-story-game', 'place-photo-research',
}

# A reference enters Langfuse only when an application or skill workflow reads
# it as model instructions. Other references remain ordinary repository docs.
MODEL_FACING_REFERENCES = {
    "skills/historical-news-research/references/contract.md",
    "skills/memoir-author-timeline/references/contract.md",
    "skills/memoir-composer/references/editorial-and-length.md",
    "skills/memoir-composer/references/editorial-review.prompt.md",
    "skills/memoir-composer/references/narrative-enrichment.md",
    "skills/memoir-composer/references/runtime-contract.md",
    "skills/memoir-composer/references/workflows.md",
    "skills/memoir-place-journey/references/two-lane.md",
    "skills/memoir-story-game/references/acceptance.md",
    "skills/memoir-story-game/references/formal-workflow.md",
    "skills/memoir-story-game/references/privacy-and-grounding.md",
    "skills/memoir-story-game/references/runtime-contract.md",
    "skills/place-photo-research/references/llm-web-search.md",
    "skills/place-photo-research/references/record-format.md",
    "skills/place-photo-research/references/source-strategy.md",
}

PROMPT_NAMES = {
    "canonical-extraction": "memoir/memory/timeline",
    "canonical-extraction-derived": "memoir/memory/timeline-derived",
    "collector-compact": "memoir/interview/collector",
    "collector-guidance": "memoir/interview/guidance",
    "collector-contract": "memoir/interview/collector-plan",
    "composer-draft-canonical": "memoir/composer/draft-canonical",
    "composer-index": "memoir/composer/index",
    "composer-prepare": "memoir/composer/prepare",
    "composer-review": "memoir/composer/review",
    "conversation-language-en-AU": "memoir/interview/language/en-AU",
    "conversation-language-zh-CN": "memoir/interview/language/zh-CN",
    "conversation-attribution": "memoir/memory/conversation-attribution",
    "extraction-window": "memoir/memory/extraction-window",
    "eval-independent-events": "memoir/evaluation/live-skills/independent-events",
    "eval-native-search": "memoir/evaluation/live-skills/native-search",
    "eval-place-groups": "memoir/evaluation/live-skills/place-groups",
    "eval-story-game": "memoir/evaluation/live-skills/story-game",
    "eval-historical-lead": "memoir/evaluation/live-skills/historical-lead",
    "eval-photo-lead": "memoir/evaluation/live-skills/photo-lead",
    "five-case-judge-guard": "memoir/evaluation/five-case-judge/guard",
    "greeting-begin": "memoir/interview/greeting/begin",
    "greeting-continue": "memoir/interview/greeting/continue",
    "governed-repair-prefix": "memoir/interview/governed-repair/prefix",
    "governed-repair-suffix": "memoir/interview/governed-repair/suffix",
    "governed-acknowledgement": "memoir/interview/governed-repair/acknowledgement",
    "governed-continuity": "memoir/interview/governed-continuity",
    "governed-turn": "memoir/interview/governed-turn",
    "memory-summary": "memoir/memory/summary",
    "historical-discovery": "memoir/research/historical-discovery",
    "lifetime-privacy-guard": "memoir/interview/privacy-guard",
    "lane-batch-prepare": "memoir/memory/lane/batch-prepare",
    "lane-batch-compose": "memoir/composer/lane/batch-compose",
    "lane-canonical-context-en-AU": "memoir/memory/lane/context/en-AU",
    "lane-canonical-context-zh-CN": "memoir/memory/lane/context/zh-CN",
    "lane-canonical-context": "memoir/memory/lane/context/shared",
    "lane-place-conflicts": "memoir/memory/lane/place-conflicts",
    "organiser-job-leaf-en-AU": "memoir/composer/organiser-job/leaf/en-AU",
    "organiser-job-leaf-zh-CN": "memoir/composer/organiser-job/leaf/zh-CN",
    "organiser-job-merge-en-AU": "memoir/composer/organiser-job/merge/en-AU",
    "organiser-job-merge-zh-CN": "memoir/composer/organiser-job/merge/zh-CN",
    "organiser-job-prefix": "memoir/composer/organiser-job/shared/prefix",
    "organiser-job-suffix": "memoir/composer/organiser-job/shared/suffix",
    "speech-en-AU": "memoir/speech/en-AU",
    "speech-zh-CN": "memoir/speech/zh-CN",
    "speech-default": "memoir/speech/default",
    "trajectory-judge-system": "memoir/evaluation/trajectory-judge/system",
    "trajectory-judge-rubric": "memoir/evaluation/trajectory-judge/rubric",
    "strategy-comfort": "memoir/interview/strategy/comfort",
    "strategy-explore": "memoir/interview/strategy/explore",
    "strategy-shape": "memoir/interview/strategy/shape",
    "strategy-selection": "memoir/interview/strategy/selection",
    "timeline-grounding": "memoir/memory/timeline-grounding",
    "two-lane-conversation": "memoir/interview/two-lane-conversation",
    "two-lane-extraction-extension": "memoir/memory/two-lane/extraction",
    "two-lane-strategy-extension": "memoir/memory/two-lane/strategy",
}


def prompt_registry(root: Path = ROOT) -> dict[str, str]:
    result = dict(SPECIAL)
    for path in sorted((root / "apps/api/prompts").glob("*.md")):
        result[PROMPT_NAMES[path.stem]] = str(path.relative_to(root))
    registered_paths = set(result.values())
    for skill in sorted(MODEL_FACING_SKILLS):
        path = root / 'skills' / skill / 'SKILL.md'
        if not path.is_file():
            raise ValueError(f'Registered skill instructions are missing: {skill}')
        relative = str(path.relative_to(root))
        if relative not in registered_paths:
            result[f"memoir/skills/{path.parent.name}"] = relative
    for path in sorted((root / "skills").glob("*/references/*.md")):
        relative = str(path.relative_to(root))
        if relative not in registered_paths and relative in MODEL_FACING_REFERENCES:
            result[f"memoir/skills/{path.parent.parent.name}/{path.stem}"] = relative
    missing_references = MODEL_FACING_REFERENCES - {
        str(path.relative_to(root)) for path in (root / "skills").glob("*/references/*.md")
    }
    if missing_references:
        raise ValueError(f"Registered skill references are missing: {sorted(missing_references)}")
    if len(result) != len(set(result.values())):
        raise ValueError("Two Langfuse prompt names target the same artifact")
    if any(not (root / path).is_file() for path in result.values()):
        raise ValueError("A registered prompt artifact is missing")
    return result
