"""Progress reports application work, without an obsolete question pool."""
import asyncio
import inspect
import json

import pytest

from apps.api.turn_progress import TurnProgress


@pytest.mark.parametrize('language', ['en-AU', 'zh-CN'])
def test_progress_has_no_question_pool_or_lane_b_selection_interface(language):
    progress = TurnProgress(None, 'turn', 'project', language)
    assert not hasattr(progress, 'record_question_pool')
    assert 'question_pool' not in inspect.signature(progress.update).parameters
    asyncio.run(progress.update('save', 'Conversation memory saved', '对话记忆已保存', status='completed'))
    assert [step['id'] for step in progress.steps] == ['save']
    assert 'question_pool' not in json.dumps(progress.steps)
