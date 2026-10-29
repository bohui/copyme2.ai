"""Export only model-consumed sources from the application's prompt catalog."""
from pathlib import Path

from apps.api.prompt_catalog import PROMPT_PATHS

ROOT = Path(__file__).resolve().parents[1]

# New evaluation sources enter the merged-main publisher before receipts exist.
# Runtime/export consumers still require an actual publication receipt.
EVALUATION_PROMPT_PATHS = {
    'memoir/evaluation/skills/shared-policy': 'tests/evaluation/prompts/skill-judges/policy.md',
    **{'memoir/evaluation/skills/' + name + '/rubric':
       'tests/evaluation/prompts/skill-judges/' + name + '.md' for name in (
           'memoir-interviewer', 'memoir-author-timeline', 'memoir-composer', 'memoir-family-tree',
           'memoir-memory-context', 'memoir-place-journey', 'memoir-place-groups',
           'memoir-place-photo-research', 'memoir-historical-news-research', 'memoir-story-game')},
}

# New runtime sources are published only after their reviewed Markdown reaches main.
NEW_RUNTIME_PROMPTS = {'memoir/shared/background-agent', 'memoir/shared/skill-agent',
    'memoir/skills/memoir-composer/instructions'}


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
