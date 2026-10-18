"""Small, role-specific interviewing contract for the visible collector pass."""

from .prompt_artifact import prompt_path

from .prompt_composition import render_prompt_artifact

COMPACT_COLLECTOR_PROMPT = render_prompt_artifact(
    prompt_path('memoir/skills/memoir-interviewer/collector')
)
