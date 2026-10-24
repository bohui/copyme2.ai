"""A prepared clarification must not appear once in speech and again as its question."""
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
def test_unpunctuated_question_never_escapes_as_a_clarification_acknowledgement(
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
    packet = json.loads(governed.packet)
    packet['current']['narrator'].update(original=current, char_end=len(current), language=locale)
    packet['pinned']['language'] = locale
    packet.update(instructions=reply_instructions(), interview_context={
        key: value for key, value in context.items() if key not in {'source', 'sources'}})
    raw = {**proposal(), 'acknowledgement': unpunctuated,
        'question': question, 'reason': 'prepared_candidate', 'hint': 0}
    captured = install_reply_provider(monkeypatch, [raw])
    monkeypatch.setenv('MEMORY_SPARK_PARALLEL_POLICY_REVIEW', '1' if revisable else '0')
    visible = []
    async def delta(value):
        visible.append(json.loads(value)['acknowledgement'])
    result = asyncio.run(run_governed_collector(command=['forbidden'], home_root=tmp_path,
        base_url='https://provider.invalid/v1', api_key='synthetic', model=BUDGET.model,
        governed=encode(packet), interview_context=context, publisher=FakePublisher(), on_delta=delta))
    accepted = validate_governed_collector_result(result['reply'], context)
    assert accepted['reply'] == neutral + '\n\n' + question
    assert visible == [neutral]
    assert len(captured) == 1
