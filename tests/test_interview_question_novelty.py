"""Fictional partial-answer replay; live checks never use customer history."""
import asyncio
import json
import os
from pathlib import Path
import re

import pytest

from apps.api.conversation_reply import reply_instructions, reply_packet
from apps.api.conversation_reply_transport import reply_messages, stream_reply
from apps.api.lifetime_memory_continuity import (
    governed_collector_schema, validate_governed_collector_result,
)
from apps.api.lifetime_memory_engine import GOVERNED_TURN_PROMPT, validate_governed_context
from test_lifetime_memory_engine import BUDGET, FENCE, FakePublisher, encode, fixture


def partial_answer(locale, *, reply_kind='partial'):
    if locale == 'zh-CN':
        question = '去图书馆途中，你们通常会经过怎样的地方？'
        answer = '路旁有不少树。小宁爱看科幻小说，经常给我推荐书，后来我们还一起办了读书会。'
    else:
        question = 'What was the route to the library usually like?'
        answer = ('There were lots of trees. My friend Robin loved science fiction and often '
                  'recommended books to me. Later we started a book club together.')
    if reply_kind == 'unanswered':
        answer = ('后来我和小宁一起办了科幻读书会。' if locale == 'zh-CN'
                  else 'Later Robin and I started a science fiction book club together.')
    elif reply_kind == 'reopen':
        answer = ('请把刚才关于去图书馆路线的问题再问我一遍。' if locale == 'zh-CN'
                  else 'Please ask me that same question about the route to the library again.')
    governed, context = fixture()
    context.update(reply_contract='reply-v2', two_lane_memory=True, interview_language=locale,
        recent_dialogue=[dict(status='responded', question=dict(id='fictional-route-question',
            text=question, role='assistant', personal_testimony=False, delivered=True),
            response=dict(id=context['source']['id'], version=1, text=answer,
                role='user', kind='narrator_chat', complete=True))])
    context['source']['text'] = answer
    packet = json.loads(governed.packet)
    packet['current']['narrator'].update(original=answer, char_end=len(answer), language=locale)
    packet['pinned']['language'] = locale
    packet.update(instructions=reply_instructions(), interview_context={
        key: value for key, value in context.items() if key not in {'source', 'sources'}})
    governed = encode(packet)
    view = reply_packet(validate_governed_context(governed, context))
    return context, view


@pytest.mark.parametrize('locale', ['en-AU', 'zh-CN'])
def test_reply_packet_keeps_the_asked_question_and_its_partial_response(locale):
    context, view = partial_answer(locale)
    messages = reply_messages(view, GOVERNED_TURN_PROMPT)
    sent = json.loads(messages[1]['content'])['context']['recent_dialogue']
    assert sent == context['recent_dialogue']
    assert sent[0]['question']['delivered'] is True
    assert json.loads(messages[-1]['content'])['current']['narrator']['original'] == sent[0]['response']['text']


@pytest.mark.skipif(os.getenv('MEMOIR_LIVE_QUESTION_NOVELTY') != '1',
                    reason='Opt in to fictional model calls with MEMOIR_LIVE_QUESTION_NOVELTY=1')
@pytest.mark.parametrize('locale', ['en-AU', 'zh-CN'])
@pytest.mark.parametrize('reply_kind', ['partial', 'unanswered', 'reopen'])
def test_live_reply_moves_on_unless_the_narrator_explicitly_reopens_the_question(locale, reply_kind, monkeypatch):
    from dotenv import dotenv_values
    from apps.api.collector_configuration import collector_configuration

    config = {**dotenv_values(Path(__file__).resolve().parents[1] / '.env'), **os.environ}
    for key in ('MEMORY_SPARK_COLLECTOR_MODEL', 'MEMORY_SPARK_COLLECTOR_REASONING_EFFORT',
                'MEMORY_SPARK_COLLECTOR_PROMPT_VERSION'):
        if config.get(key):
            monkeypatch.setenv(key, config[key])
    selected = collector_configuration(config['MEMORY_SPARK_LLM_MODEL'])
    context, view = partial_answer(locale, reply_kind=reply_kind)
    output, receipt = asyncio.run(stream_reply(view=view, prompt=GOVERNED_TURN_PROMPT,
        schema=governed_collector_schema(context), model=selected.model, effort=selected.effort,
        budget=BUDGET, base_url=config['MEMORY_SPARK_LLM_BASE_URL'],
        api_key=config['MEMORY_SPARK_LLM_API_KEY'], publisher=FakePublisher(), fence=FENCE,
        metadata={}, timeout=120))
    raw = json.loads(output)
    assert raw.get('question') is not None, raw
    result = validate_governed_collector_result(raw, context)
    question = result['plan']['candidates'][0]['question']
    assert receipt['response_id']
    # Fixture-specific intent checks, never a production keyword filter.
    repeated = r'路|沿途|途中|经过|树' if locale == 'zh-CN' else r'\b(route|path|journey|trees|along the way)\b'
    new_thread = r'书|小说|科幻|推荐|读' if locale == 'zh-CN' else r'\b(book|books|club|fiction|reading|read|recommend\w*)\b'
    if reply_kind == 'reopen':
        assert re.search(repeated + r'|图书馆|library', question, re.I), question
    else:
        assert not re.search(repeated, question, re.I), question
        assert re.search(new_thread, question, re.I), question
    print(json.dumps(dict(locale=locale, reply_kind=reply_kind,
        question=question, model=receipt['model']), ensure_ascii=False))
