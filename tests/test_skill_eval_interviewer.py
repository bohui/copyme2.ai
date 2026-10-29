"""Adapt PR93's current-intent checks to the stable 160-item catalog."""
import asyncio
from copy import deepcopy

import pytest

from scripts import memoir_skill_eval_suite as suite


@pytest.mark.parametrize('locale', ['en-AU', 'zh-CN'])
@pytest.mark.parametrize('pause', [False, True])
def test_isolated_interviewer_packet_uses_reply_v2_without_retired_prompts(locale, pause):
    from apps.api.conversation_reply import reply_instructions
    from test_conversation_reply import proposal, reply_context
    context = {**reply_context(), 'interview_language': locale, 'strategy_selector': True}
    reason = 'pause' if pause else 'latest_story'
    item = dict(id='isolated-reply-' + locale, skill='memoir-interviewer', locale=locale,
        task=dict(context=context), gold=dict(facts=dict(stopped=pause,
            question=not pause, selection_reason=reason)))
    request = suite.packet(item)
    assert request['instructions'] == reply_instructions()
    assert request['input']['reply_language'] == locale
    assert request['input']['reply_contract'] == 'reply-v2'
    assert request['input']['brief']['hints'] == []
    output = {**proposal(), 'reason': reason}
    if pause:
        output['question'] = None
    suite.validate(item, output)


@pytest.mark.parametrize('locale', ['en-AU', 'zh-CN'])
@pytest.mark.parametrize('case', ['grounded-question', 'pause', 'redirect', 'correction', 'slow-pacing',
                                  'uncertain-date', 'photo-metadata', 'input-injection'])
def test_foreground_packets_validate_real_selector_and_current_intent(tmp_path, locale, case):
    from test_conversation_reply import proposal
    from apps.api.conversation_reply import reply_instructions
    item, = suite.plan(case=[f'memoir-interviewer/{case}/{locale}'])['items']
    pause = case == 'pause'
    reason = {'pause': 'pause', 'redirect': 'user_redirect', 'correction': 'current_correction',
              'slow-pacing': 'pacing'}.get(case, 'latest_story')
    output = {**proposal(), 'question': None if pause else
        '您还记得什么？' if locale == 'zh-CN' else 'What else do you remember?', 'reason': reason}
    class Provider:
        async def call(self, packet):
            assert packet['input']['strategy_selector'] is True
            assert 'gold' not in packet and 'rubric' not in packet
            assert packet['input']['reply_contract'] == 'reply-v2'
            assert packet['instructions'] == reply_instructions()
            return dict(output=deepcopy(output), response_id='selector-fixture', model='controlled', usage=None)
    receipt = asyncio.run(suite.run(suite.plan(case=[item['id']]), tmp_path, skill=Provider()))
    row, = receipt['results']
    assert row['contract']['status'] == 'pass', row
    assert row['positive_delivery'] is not pause
    invalid = deepcopy(output)
    invalid.update(hint=999, reason='prepared_candidate')
    with pytest.raises(Exception): suite.validate(item, invalid)
    if case in {'pause', 'redirect', 'correction', 'slow-pacing'}:
        invalid = deepcopy(output); invalid['reason'] = 'latest_story'
        with pytest.raises(Exception): suite.validate(item, invalid)
