"""Repository harness discovery and admission, without credentials or a provider."""
from pathlib import Path
from unittest.mock import patch

import pytest

from apps.api import codex_runtime
from apps.api.conversation_phase import PhaseState
from apps.api.memoir_story_game import StoryGameUnavailable
from apps.api.trajectory_evaluation import build_skill_manifest


def test_product_harness_loads_repository_skill_and_manifest_discovers_resources():
    root = Path(__file__).resolve().parents[1]
    assert codex_runtime.STORY_GAME_SKILL_PATH == root / 'skills/memoir-story-game/SKILL.md'
    assert codex_runtime.STORY_GAME_SKILL == codex_runtime.STORY_GAME_SKILL_PATH.read_text().strip()
    entry = next(item for item in build_skill_manifest(root / 'skills')['skills']
                 if item['name'] == 'memoir-story-game')
    paths = {item['path'] for item in entry['files']}
    assert {'SKILL.md', 'schemas/game.schema.json', 'references/runtime-contract.md'} <= paths


@pytest.mark.parametrize('phase', ['comfort', 'explore'])
def test_harness_rejects_other_phases(phase):
    result = codex_runtime.story_game_admission(PhaseState(phase=phase))
    assert result == {'skill': 'memoir-story-game', 'registered': True,
                      'available': False, 'reason': 'shape_required'}


def test_shape_alone_cannot_invoke_provider_or_construct_prompt():
    phase = PhaseState(phase='shape', selection='explicit', preferred_phase='shape', revision=3)
    with patch.object(codex_runtime, 'CodexConnection', side_effect=AssertionError('provider must not run')):
        result = codex_runtime.story_game_admission(phase)
        assert result['registered'] is True
        assert result['available'] is False
        assert result['reason'] == 'persisted_authority_required'
        with pytest.raises(StoryGameUnavailable, match='persisted_authority_required'):
            codex_runtime.build_story_game_prompt(phase)


@pytest.mark.parametrize('extra', ['storytelling_complete', 'composition_complete', 'game_adaptation_allowed'])
def test_browser_completion_or_consent_flags_cannot_enable_skill(extra):
    result = codex_runtime.story_game_admission({'phase': 'shape', extra: True})
    assert result['available'] is False
    assert result['reason'] == 'invalid_phase_state'


def test_missing_phase_and_missing_skill_file_fail_closed(tmp_path):
    assert codex_runtime.story_game_admission()['reason'] == 'phase_authority_required'
    with patch('apps.api.memoir_story_game.STORY_GAME_SKILL_PATH', tmp_path / 'missing.md'):
        assert codex_runtime.story_game_admission(PhaseState()) == {
            'skill': 'memoir-story-game', 'registered': False,
            'available': False, 'reason': 'skill_unavailable'}


def test_existing_worker_and_task_allowlists_do_not_admit_unbound_game_execution():
    from apps.api.codex_worker_service import WorkerTurnInput
    from apps.api.agent_tasks import TaskRequest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        WorkerTurnInput(user_id='00000000-0000-4000-8000-000000000001', agent_role='story_game')
    with pytest.raises(ValidationError):
        TaskRequest(kind='BuildStoryGame', memory_ids=['synthetic'])
