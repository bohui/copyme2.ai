"""Repository skill discovery; generation uses the authenticated game workflow.

This module deliberately accepts no caller-supplied completion/consent booleans.
The offline package validator is not imported into the production trust boundary.
"""
from pathlib import Path

STORY_GAME_SKILL_NAME = 'memoir-story-game'
STORY_GAME_SKILL_PATH = Path(__file__).resolve().parents[2] / 'skills' / STORY_GAME_SKILL_NAME / 'SKILL.md'


def load_story_game_skill():
    """Same repository-native source convention as the place-journey loader."""
    try:
        from .prompt_artifact import load_prompt_artifact
        return load_prompt_artifact(STORY_GAME_SKILL_PATH).strip()
    except OSError:
        return ''


def story_game_admission(strategy_plan=None, *, current_mode=None, button_action=False):
    """An internal strategy cannot substitute for persisted game authority."""
    registered = bool(load_story_game_skill())
    result = {'skill': STORY_GAME_SKILL_NAME, 'registered': registered, 'available': False}
    if not registered:
        return {**result, 'reason': 'skill_unavailable'}
    # A plan (including a valid future/shadow B shape proposal) is never current
    # authority. Only the authenticated action route supplies this SQL readback.
    if not isinstance(current_mode,dict) or not current_mode.get('reply_id'):
        return {**result, 'reason': 'current_decision_required'}
    if current_mode.get('mode') != 'shape':
        return {**result, 'reason': 'shape_required'}
    if not button_action:
        return {**result, 'reason': 'button_action_required'}
    # This collector seam owns no job, edition or consent. Only the separate
    # authenticated game routes can resolve those gates and invoke the provider.
    return {**result, 'reason': 'authenticated_game_workflow_required'}


class StoryGameUnavailable(ValueError):
    pass


def build_story_game_prompt(strategy_plan=None):
    """Reserved harness dispatch seam; cannot create an executable prompt yet."""
    admission = story_game_admission(strategy_plan)
    raise StoryGameUnavailable(admission['reason'])
