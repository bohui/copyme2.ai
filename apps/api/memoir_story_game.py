"""Repository skill registration; execution remains closed pending game bindings.

This module deliberately accepts no caller-supplied completion/consent booleans.
The offline package validator is not imported into the production trust boundary.
"""
from pathlib import Path

from pydantic import ValidationError

from .conversation_phase import PhaseState

STORY_GAME_SKILL_NAME = 'memoir-story-game'
STORY_GAME_SKILL_PATH = Path(__file__).resolve().parents[2] / 'skills' / STORY_GAME_SKILL_NAME / 'SKILL.md'


def load_story_game_skill():
    """Same repository-native source convention as the place-journey loader."""
    try:
        return STORY_GAME_SKILL_PATH.read_text(encoding='utf-8').strip()
    except OSError:
        return ''


def story_game_admission(phase_state=None):
    """Phase alone is not authority. Persisted eligibility has a separate RPC."""
    registered = bool(load_story_game_skill())
    result = {'skill': STORY_GAME_SKILL_NAME, 'registered': registered, 'available': False}
    if not registered:
        return {**result, 'reason': 'skill_unavailable'}
    if phase_state is None:
        return {**result, 'reason': 'phase_authority_required'}
    try:
        phase = PhaseState.model_validate(phase_state)
    except (ValidationError, TypeError):
        return {**result, 'reason': 'invalid_phase_state'}
    if phase.phase != 'shape':
        return {**result, 'reason': 'shape_required'}
    # Shape is independently selectable. The authenticated eligibility endpoint
    # resolves durable completion and consent; this phase-only discovery helper
    # cannot substitute for it or enable the still-unbound game execution path.
    return {**result, 'reason': 'persisted_authority_required'}


class StoryGameUnavailable(ValueError):
    pass


def build_story_game_prompt(phase_state=None):
    """Reserved harness dispatch seam; cannot create an executable prompt yet."""
    admission = story_game_admission(phase_state)
    raise StoryGameUnavailable(admission['reason'])
