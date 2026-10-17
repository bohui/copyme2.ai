"""Small, role-specific interviewing contract for the visible collector pass."""

from pathlib import Path

from .prompt_artifact import load_prompt_artifact

COMPACT_COLLECTOR_PROMPT = load_prompt_artifact(
    Path(__file__).with_name("prompts") / "collector-compact.md"
)
