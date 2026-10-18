"""Repository harness discovery and admission, without credentials or a provider."""
from pathlib import Path
from unittest.mock import patch

import pytest

from apps.api import memoir_story_game
from apps.api.interview_strategy import InterviewStrategyPlan
from apps.api.memoir_story_game import StoryGameUnavailable
from apps.api.trajectory_evaluation import build_skill_manifest


def strategy_plan(strategy='shape'):
    return InterviewStrategyPlan(plan_revision=1,project_id='project',based_on_sequence=1,
        source_id='source',source_version=1,source_revision=1,policy_epoch=1,preference_revision=0,
        execution_generation=1,phase_revision=0,snapshot_id='snapshot',checkpoint_id=None,
        strategy=strategy,objective='clarify_order',focus_event_ids=[],candidates=[],background_lag_ms=0)


def test_product_harness_loads_repository_skill_and_manifest_discovers_resources():
    root = Path(__file__).resolve().parents[1]
    assert memoir_story_game.STORY_GAME_SKILL_PATH == root / 'skills/memoir-story-game/SKILL.md'
    assert memoir_story_game.load_story_game_skill() == memoir_story_game.STORY_GAME_SKILL_PATH.read_text().strip()
    entry = next(item for item in build_skill_manifest(root / 'skills')['skills']
                 if item['name'] == 'memoir-story-game')
    paths = {item['path'] for item in entry['files']}
    assert {'SKILL.md', 'schemas/game.schema.json', 'references/runtime-contract.md'} <= paths


@pytest.mark.parametrize('phase', ['comfort', 'explore'])
def test_harness_rejects_other_phases(phase):
    result = memoir_story_game.story_game_admission(strategy_plan(phase))
    assert result == {'skill': 'memoir-story-game', 'registered': True,
                      'available': False, 'reason': 'current_decision_required'}


def test_shape_alone_cannot_invoke_provider_or_construct_prompt():
    phase = strategy_plan()
    with patch('apps.api.codex_agent.CodexConnection', side_effect=AssertionError('provider must not run')):
        result = memoir_story_game.story_game_admission(phase)
        assert result['registered'] is True
        assert result['available'] is False
        assert result['reason'] == 'current_decision_required'
        with pytest.raises(StoryGameUnavailable, match='current_decision_required'):
            memoir_story_game.build_story_game_prompt(phase)


@pytest.mark.parametrize('extra', ['storytelling_complete', 'composition_complete', 'game_adaptation_allowed'])
def test_browser_completion_or_consent_flags_cannot_enable_skill(extra):
    result = memoir_story_game.story_game_admission({'phase': 'shape', extra: True})
    assert result['available'] is False
    assert result['reason'] == 'current_decision_required'


def test_missing_phase_and_missing_skill_file_fail_closed(tmp_path):
    assert memoir_story_game.story_game_admission()['reason'] == 'current_decision_required'
    with patch('apps.api.memoir_story_game.STORY_GAME_SKILL_PATH', tmp_path / 'missing.md'):
        assert memoir_story_game.story_game_admission(strategy_plan('comfort')) == {
            'skill': 'memoir-story-game', 'registered': False,
            'available': False, 'reason': 'skill_unavailable'}


def test_current_shape_still_requires_button_and_authenticated_game_workflow():
    current={'mode':'shape','reply_id':'server-recorded'}
    assert memoir_story_game.story_game_admission(current_mode=current)['reason']=='button_action_required'
    result=memoir_story_game.story_game_admission(current_mode=current,button_action=True)
    assert result['reason']=='authenticated_game_workflow_required' and not result['available']


def test_existing_worker_and_task_allowlists_do_not_admit_unbound_game_execution():
    from apps.api.codex_worker_service import WorkerTurnInput
    from apps.api.agent_tasks import TaskRequest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        WorkerTurnInput(user_id='00000000-0000-4000-8000-000000000001', agent_role='story_game')
    with pytest.raises(ValidationError):
        TaskRequest(kind='BuildStoryGame', memory_ids=['synthetic'])
