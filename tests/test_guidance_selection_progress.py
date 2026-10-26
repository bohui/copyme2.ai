"""Only validated selection provenance reaches thinking steps."""
import asyncio
import json

import pytest

from apps.api.turn_progress import TurnProgress


@pytest.mark.parametrize('language', ['en-AU', 'zh-CN'])
def test_selected_topic_transition_has_public_provenance_without_private_candidates(language):
    candidate = 'bq-' + 'a' * 64
    plan = {'chosen_id': candidate, 'candidates': [dict(
        id=candidate, question='Private selected question', bridge='Private bridge', order=0)]}
    context = {'prepared_questions': [dict(
        id=candidate, trigger='topic_transition', quote='Private original')]}
    progress = TurnProgress(None, 'turn', 'project', language)
    asyncio.run(progress.record_question_pool(plan, context=context))
    selection = next(step for step in progress.steps if step['id'] == 'question-selection')
    assert selection['status'] == 'completed'
    assert 'B' in selection['detail']
    assert ('衔接新话题' if language == 'zh-CN' else 'connected topic transition') in selection['detail']
    assert 'Private' not in json.dumps(progress.steps)
    assert candidate not in json.dumps(progress.steps)


def test_available_candidate_is_not_reported_as_selected_when_a_chooses_its_own_question():
    progress = TurnProgress(None, 'turn', 'project', 'en-AU')
    plan = {'chosen_id': 'immediate-current', 'candidates': [dict(
        id='immediate-current', question='Private current question', bridge='', order=0)]}
    context = {'prepared_questions': [dict(id='bq-' + 'a' * 64, trigger='topic_transition')]}
    asyncio.run(progress.record_question_pool(plan, context=context))
    selection = next(step for step in progress.steps if step['id'] == 'question-selection')
    assert 'current narration' in selection['detail']
    assert 'Selected Lane B' not in selection['detail']


def test_cached_validated_b_question_keeps_its_origin_without_reloading_private_candidates():
    candidate = 'bq-' + 'a' * 64
    progress = TurnProgress(None, 'turn', 'project', 'zh-CN')
    plan = {'chosen_id': candidate, 'candidates': [dict(
        id=candidate, question='Private saved question', bridge='', order=0)]}
    asyncio.run(progress.record_question_pool(plan))
    selection = next(step for step in progress.steps if step['id'] == 'question-selection')
    assert selection['detail'] == '已选用 B 访谈建议'
