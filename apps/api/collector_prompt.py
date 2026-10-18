"""Small, role-specific interviewing contract for the visible collector pass."""

from pathlib import Path

from .prompt_composition import render_prompt_artifact

COMPACT_COLLECTOR_PROMPT = render_prompt_artifact(
    Path(__file__).with_name("prompts") / "collector-compact.md"
)
