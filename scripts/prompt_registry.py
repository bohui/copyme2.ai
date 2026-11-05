"""Export only model-consumed sources from the application's prompt catalog."""
from pathlib import Path

from apps.api.prompt_catalog import PROMPT_PATHS

ROOT = Path(__file__).resolve().parents[1]

# New evaluation sources enter the publisher before receipts exist.
# Runtime/export consumers still require an actual publication receipt.
EVALUATION_PROMPT_PATHS = {
    **{'memoir/evaluators/shared/' + dimension: 'tests/evaluation/prompts/quality/' + dimension + '.md'
       for dimension in ('correctness', 'relevance', 'completeness', 'safety')},
    'memoir/evaluators/agents/mira/reply/comparison': 'tests/evaluation/prompts/mira-comparison.md',
    'memoir/evaluators/agents/mira/reply/interview-quality': 'tests/evaluation/prompts/mira-rubric.md',
    'memoir/evaluators/shared/evidence-policy': 'tests/evaluation/prompts/skill-judges/policy.md',
    'memoir/evaluators/skills/author-timeline/extract/quality': 'tests/evaluation/prompts/skill-judges/memoir-author-timeline.md',
    'memoir/evaluators/workflows/composer-checkpoints/quality': 'tests/evaluation/prompts/skill-judges/memoir-composer.md',
    'memoir/evaluators/skills/family-tree/extract/quality': 'tests/evaluation/prompts/skill-judges/memoir-family-tree.md',
    'memoir/evaluators/skills/memory-context/profile/quality': 'tests/evaluation/prompts/skill-judges/memoir-memory-context.md',
    'memoir/evaluators/skills/place-journey/extract/quality': 'tests/evaluation/prompts/skill-judges/memoir-place-journey.md',
    'memoir/evaluators/skills/place-groups/group/quality': 'tests/evaluation/prompts/skill-judges/memoir-place-groups.md',
    'memoir/evaluators/skills/place-photo-research/discovery/quality': 'tests/evaluation/prompts/skill-judges/memoir-place-photo-research.md',
    'memoir/evaluators/skills/historical-news-research/discovery/quality': 'tests/evaluation/prompts/skill-judges/memoir-historical-news-research.md',
    'memoir/evaluators/workflows/story-game-adaptation/quality': 'tests/evaluation/prompts/skill-judges/memoir-story-game.md',
}

# New runtime sources need publication receipts before runtime/export use.
NEW_RUNTIME_PROMPTS = {'memoir/shared/skill-agent',
    *[name for name in PROMPT_PATHS if name.startswith('memoir/agents/')]}


def prompt_registry(root: Path = ROOT, *, include_unpublished: bool = False) -> dict[str, str]:
    result = {name: path for name, path in PROMPT_PATHS.items()
              if name not in NEW_RUNTIME_PROMPTS or include_unpublished
              or (root / (path + '.langfuse.json')).is_file()}
    result.update({name: path for name, path in EVALUATION_PROMPT_PATHS.items()
                   if include_unpublished or (root / (path + '.langfuse.json')).is_file()})
    if len(result) != len(set(result.values())):
        raise ValueError("Two Langfuse prompt names target the same artifact")
    if any(not (root / path).is_file() for path in result.values()):
        raise ValueError("A registered prompt artifact is missing")
    return result
