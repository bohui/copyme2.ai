"""Repository artifacts whose text is versioned in Memoir's Langfuse project."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SPECIAL = {
    "memoir/interview/journalist": "Mira_Memoir_Journalist_System_Prompt_v1.0.md",
    "memoir/memory/place-journey": "skills/memoir-place-journey/SKILL.md",
    "memoir/memory/family-tree": "skills/memoir-family-tree/SKILL.md",
    "memoir/memory/author-timeline-marker": "skills/memoir-author-timeline/references/legacy-marker.md",
    "memoir/memory/context": "skills/memoir-memory-context/SKILL.md",
    "memoir/story-game/skill": "skills/memoir-story-game/SKILL.md",
    "memoir/evaluation/five-case-judge": "tests/evaluation/memoir_five_case_judge_prompt.md",
}

PROMPT_NAMES = {
    "browser-profile-intake": "memoir/interview/browser/profile-intake",
    "browser-follow-up": "memoir/interview/browser/follow-up",
    "browser-memory-follow-up": "memoir/interview/browser/memory-follow-up",
    "browser-media-context": "memoir/interview/browser/media-context",
    "browser-message": "memoir/interview/browser/message",
    "canonical-extraction": "memoir/memory/timeline",
    "canonical-extraction-derived": "memoir/memory/timeline-derived",
    "collector-compact": "memoir/interview/collector",
    "collector-contract": "memoir/interview/collector-plan",
    "collector-repair": "memoir/interview/collector-repair",
    "collection-task-base": "memoir/interview/collection-task/base",
    "collection-task-with-sources": "memoir/interview/collection-task/with-sources",
    "composer-draft": "memoir/composer/draft",
    "composer-draft-canonical": "memoir/composer/draft-canonical",
    "composer-index": "memoir/composer/index",
    "composer-prepare": "memoir/composer/prepare",
    "composer-review": "memoir/composer/review",
    "conversation-language-en-AU": "memoir/interview/language/en-AU",
    "conversation-language-zh-CN": "memoir/interview/language/zh-CN",
    "conversation-attribution": "memoir/memory/conversation-attribution",
    "conversation-breadth-default": "memoir/interview/breadth/default",
    "conversation-breadth-checkpoint": "memoir/interview/breadth/checkpoint",
    "conversation-breadth-pending-plural": "memoir/interview/breadth/pending-plural",
    "conversation-breadth-pending-singular": "memoir/interview/breadth/pending-singular",
    "conversation-response-contract": "memoir/interview/response-contract",
    "extraction-window": "memoir/memory/extraction-window",
    "fallback-place-journey": "memoir/memory/fallback/place-journey",
    "fallback-family-tree": "memoir/memory/fallback/family-tree",
    "fallback-author-timeline": "memoir/memory/fallback/author-timeline",
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
    "profile-intake": "memoir/memory/profile-intake",
    "memory-summary": "memoir/memory/summary",
    "marker-location-identity": "memoir/memory/marker/location-identity",
    "marker-place-grounding": "memoir/memory/marker/place-grounding",
    "marker-family-context": "memoir/memory/marker/family-context",
    "conversation-photo-header": "memoir/interview/photo/header",
    "conversation-photo-guidance": "memoir/interview/photo/guidance",
    "historical-discovery": "memoir/research/historical-discovery",
    "lifetime-privacy-guard": "memoir/interview/privacy-guard",
    "lane-batch-prepare": "memoir/memory/lane/batch-prepare",
    "lane-batch-compose": "memoir/composer/lane/batch-compose",
    "lane-canonical-context-en-AU": "memoir/memory/lane/context/en-AU",
    "lane-canonical-context-zh-CN": "memoir/memory/lane/context/zh-CN",
    "lane-place-conflicts": "memoir/memory/lane/place-conflicts",
    "organiser-task": "memoir/composer/organiser-task",
    "organiser-job-leaf-en-AU": "memoir/composer/organiser-job/leaf/en-AU",
    "organiser-job-leaf-zh-CN": "memoir/composer/organiser-job/leaf/zh-CN",
    "organiser-job-merge-en-AU": "memoir/composer/organiser-job/merge/en-AU",
    "organiser-job-merge-zh-CN": "memoir/composer/organiser-job/merge/zh-CN",
    "speech-en-AU": "memoir/speech/en-AU",
    "speech-zh-CN": "memoir/speech/zh-CN",
    "speech-default": "memoir/speech/default",
    "trajectory-judge-system": "memoir/evaluation/trajectory-judge/system",
    "trajectory-judge-rubric": "memoir/evaluation/trajectory-judge/rubric",
    "strategy-comfort": "memoir/interview/strategy/comfort",
    "strategy-explore": "memoir/interview/strategy/explore",
    "strategy-shape": "memoir/interview/strategy/shape",
    "two-lane-conversation": "memoir/interview/two-lane-conversation",
    "two-lane-extraction-extension": "memoir/memory/two-lane/extraction",
    "two-lane-strategy-extension": "memoir/memory/two-lane/strategy",
    "workspace-family-focused": "memoir/memory/workspace/family-focused",
    "workspace-place-recovery": "memoir/memory/workspace/place-recovery",
    "workspace-canonical": "memoir/memory/workspace/canonical",
    "workspace-extraction": "memoir/memory/workspace/extraction",
    "workspace-timeline-claim": "memoir/memory/workspace/timeline-claim",
    "workspace-family-recovery": "memoir/memory/workspace/family-recovery",
    "workspace-timeline-recovery": "memoir/memory/workspace/timeline-recovery",
}


def prompt_registry(root: Path = ROOT) -> dict[str, str]:
    result = dict(SPECIAL)
    for path in sorted((root / "apps/api/prompts").glob("*.md")):
        result[PROMPT_NAMES[path.stem]] = str(path.relative_to(root))
    registered_paths = set(result.values())
    for path in sorted((root / "skills").glob("*/SKILL.md")):
        relative = str(path.relative_to(root))
        if relative not in registered_paths and not path.parent.name.startswith("deprecated-"):
            result[f"memoir/skills/{path.parent.name}"] = relative
    for path in sorted((root / "skills").glob("*/references/*.md")):
        relative = str(path.relative_to(root))
        if relative not in registered_paths and not path.parent.parent.name.startswith("deprecated-"):
            result[f"memoir/skills/{path.parent.parent.name}/{path.stem}"] = relative
    if len(result) != len(set(result.values())):
        raise ValueError("Two Langfuse prompt names target the same artifact")
    if any(not (root / path).is_file() for path in result.values()):
        raise ValueError("A registered prompt artifact is missing")
    return result
