"""Export only model-consumed sources from the application's prompt catalog."""
from pathlib import Path

from apps.api.prompt_catalog import PROMPT_PATHS

ROOT = Path(__file__).resolve().parents[1]


def prompt_registry(root: Path = ROOT) -> dict[str, str]:
    result = dict(PROMPT_PATHS)
    if len(result) != len(set(result.values())):
        raise ValueError("Two Langfuse prompt names target the same artifact")
    if any(not (root / path).is_file() for path in result.values()):
        raise ValueError("A registered prompt artifact is missing")
    return result
