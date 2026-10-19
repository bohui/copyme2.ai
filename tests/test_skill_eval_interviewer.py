"""Adapt PR93's current-intent checks to the stable 160-item catalog."""
import asyncio
from copy import deepcopy

import pytest

from scripts import memoir_skill_eval_suite as suite


@pytest.mark.parametrize('locale', ['en-AU', 'zh-CN'])
@pytest.mark.parametrize('case', ['grounded-question', 'pause', 'redirect', 'correction', 'slow-pacing',
                                  'uncertain-date', 'photo-metadata', 'input-injection'])
def test_foreground_packets_validate_real_selector_and_current_intent(tmp_path, locale, case):
    from test_interview_strategy import wire
    item, = suite.plan(case=[f'memoir-interviewer/{case}/{locale}'])['items']
    pause = case == 'pause'
    reason = {'pause': 'pause', 'redirect': 'user_redirect', 'correction': 'current_correction',
              'slow-pacing': 'pacing'}.get(case, 'latest_story')
    output = wire(question=None if pause else '您还记得什么？' if locale == 'zh-CN' else 'What else do you remember?',
                  selection_reason=reason, stopped=pause, used_strategy='explore')
    class Provider:
        async def call(self, packet):
            assert packet['input']['strategy_selector'] is True
            assert 'gold' not in packet and 'rubric' not in packet
            assert 'Active internal strategy: explore' in packet['instructions']
            return dict(output=deepcopy(output), response_id='selector-fixture', model='controlled', usage=None)
    receipt = asyncio.run(suite.run(suite.plan(case=[item['id']]), tmp_path, skill=Provider()))
    row, = receipt['results']
    assert row['contract']['status'] == 'pass', row
    assert row['positive_delivery'] is not pause
    invalid = deepcopy(output)
    invalid.update(selected_candidate_id='foreign-candidate', selection_reason='prepared_candidate')
    with pytest.raises(Exception): suite.validate(item, invalid)
    if case in {'pause', 'redirect', 'correction', 'slow-pacing'}:
        invalid = deepcopy(output); invalid['selection_reason'] = 'latest_story'
        with pytest.raises(Exception): suite.validate(item, invalid)
