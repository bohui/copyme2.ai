"""Background guidance cannot replace or delay Mira's own acknowledgement."""
import asyncio
import json

import pytest

from apps.api.conversation_reply import reply_instructions
from apps.api.lifetime_memory_continuity import validate_governed_collector_result
from test_conversation_reply import proposal
from test_conversation_reply_transport import install_reply_provider
from test_lifetime_memory_engine import fixture, encode, FakePublisher, BUDGET


@pytest.mark.parametrize('locale,current,question,unpunctuated,neutral', [
    ('en-AU', 'The umbrella might have been blue or green. Please continue.',
     'Was the umbrella blue or green?', 'Was the umbrella blue or green',
     'We can keep following your memories at your pace.'),
    ('zh-CN', '那把雨伞可能是蓝色或绿色的，请继续聊。', '雨伞是蓝色还是绿色的？',
     '雨伞是蓝色还是绿色的呢', '我们可以按您的节奏继续回忆。'),
])
@pytest.mark.parametrize('revisable', [False, True])
def test_retired_guidance_cannot_supply_the_acknowledgement_or_next_question(
        tmp_path, monkeypatch, locale, current, question, unpunctuated, neutral, revisable):
    from apps.api.lifetime_memory_engine import run_governed_collector
    governed, context = fixture()
    context.update(reply_contract='reply-v2', two_lane_memory=True,
        interview_language=locale, revisable_reply=revisable)
    context['source']['text'] = current
    source = context['source']
    context['prepared_questions'] = [dict(id='bq-' + 'a'*64, question=question,
        topic='umbrella', source_id=source['id'], source_version=source['version'],
        quote=current, char_start=0, char_end=len(current), requires_confirmation=True)]
    context['interview_guidance'] = dict(acknowledgement_guidance=dict(text=unpunctuated))
    packet = json.loads(governed.packet)
    packet['current']['narrator'].update(original=current, char_end=len(current), language=locale)
    packet['pinned']['language'] = locale
    packet.update(instructions=reply_instructions(), interview_context={
        key: value for key, value in context.items() if key not in {'source', 'sources'}})
    own_question = '那天还有什么让您记得？' if locale == 'zh-CN' else 'What else do you remember about that day?'
    raw = {**proposal(), 'acknowledgement': neutral, 'question': own_question}
    captured = install_reply_provider(monkeypatch, [raw])
    monkeypatch.setenv('MEMORY_SPARK_PARALLEL_POLICY_REVIEW', '1' if revisable else '0')
    visible = []
    async def delta(value):
        visible.append(json.loads(value)['acknowledgement'])
    result = asyncio.run(run_governed_collector(command=['forbidden'], home_root=tmp_path,
        base_url='https://provider.invalid/v1', api_key='synthetic', model=BUDGET.model,
        governed=encode(packet), interview_context=context, publisher=FakePublisher(), on_delta=delta))
    accepted = validate_governed_collector_result(result['reply'], context)
    assert accepted['reply'] == neutral + '\n\n' + own_question
    assert unpunctuated not in accepted['reply']
    assert visible == [neutral]
    assert len(captured) == 1


def test_interview_plan_has_no_prepared_acknowledgement_adapter():
    from apps.api import interview_plan
    assert not hasattr(interview_plan, 'defer_prepared_acknowledgement')
