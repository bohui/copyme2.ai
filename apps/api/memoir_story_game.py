"""Repository skill registration; execution remains closed pending game bindings.

This module deliberately accepts no caller-supplied completion/consent booleans.
The offline package validator is not imported into the production trust boundary.
"""
from pathlib import Path

from pydantic import ValidationError

from .interview_strategy import InterviewStrategyPlan

STORY_GAME_SKILL_NAME = 'memoir-story-game'
STORY_GAME_SKILL_PATH = Path(__file__).resolve().parents[2] / 'skills' / STORY_GAME_SKILL_NAME / 'SKILL.md'


def load_story_game_skill():
    """Same repository-native source convention as the place-journey loader."""
    try:
        return STORY_GAME_SKILL_PATH.read_text(encoding='utf-8').strip()
    except OSError:
        return ''


def story_game_admission(strategy_plan=None):
    """An internal strategy cannot substitute for persisted game authority."""
    registered = bool(load_story_game_skill())
    result = {'skill': STORY_GAME_SKILL_NAME, 'registered': registered, 'available': False}
    if not registered:
        return {**result, 'reason': 'skill_unavailable'}
    if strategy_plan is None:
        return {**result, 'reason': 'strategy_plan_required'}
    try:
        plan = InterviewStrategyPlan.model_validate(strategy_plan)
    except (ValidationError, TypeError):
        return {**result, 'reason': 'invalid_strategy_plan'}
    if plan.strategy != 'shape':
        return {**result, 'reason': 'shape_required'}
    # The explicit game action, completion and consent still need bindings.
    return {**result, 'reason': 'persisted_authority_required'}


class StoryGameUnavailable(ValueError):
    pass


def build_story_game_prompt(strategy_plan=None):
    """Reserved harness dispatch seam; cannot create an executable prompt yet."""
    admission = story_game_admission(strategy_plan)
    raise StoryGameUnavailable(admission['reason'])
