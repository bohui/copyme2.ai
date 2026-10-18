"""Small, role-specific interviewing contract for the visible collector pass."""

from .prompt_artifact import load_prompt_artifact, prompt_path
from .prompt_composition import render_prompt_artifact

COMPACT_COLLECTOR_PROMPT = render_prompt_artifact(
    prompt_path('memoir/skills/memoir-interviewer/collector')
)


def governed_collector_instructions(context):
    from .codex_runtime import conversation_language_instruction
    from .interview_plan import collector_instructions
    from .lifetime_memory_continuity import GOVERNED_CONTINUITY_INSTRUCTIONS
    from .two_lane_memory import CONVERSATION_INSTRUCTIONS

    language = conversation_language_instruction(context['interview_language'])
    continuity = GOVERNED_CONTINUITY_INSTRUCTIONS
    if context.get('two_lane_memory') or context.get('strategy_selector'):
        continuity = continuity.partition('Return place_journeys')[0]
    if context.get('strategy_selector'):
        from .interview_strategy import strategy_instructions
        return strategy_instructions(context['active_strategy']) + '\n' + language + continuity
    privacy = load_prompt_artifact(prompt_path('memoir/skills/memoir-interviewer/privacy-guard'))
    instructions = COMPACT_COLLECTOR_PROMPT + '\n' + language + '\n' + privacy + collector_instructions({}) + continuity
    if context.get('two_lane_memory'):
        instructions += CONVERSATION_INSTRUCTIONS
    return instructions
