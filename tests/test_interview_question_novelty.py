"""Fictional continuity replays; live checks never use customer history."""
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

QUESTION_BUDGET = BUDGET.model_copy(update={'context_window': 70000, 'input_budget': 60000})


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


def live_question(context, view, monkeypatch):
    from dotenv import dotenv_values
    from apps.api.collector_configuration import collector_configuration

    config = {**dotenv_values(Path(__file__).resolve().parents[1] / '.env'), **os.environ}
    for key in ('MEMORY_SPARK_COLLECTOR_MODEL', 'MEMORY_SPARK_COLLECTOR_REASONING_EFFORT',
                'MEMORY_SPARK_COLLECTOR_PROMPT_VERSION'):
        if config.get(key):
            monkeypatch.setenv(key, config[key])
    selected = collector_configuration(config['MEMORY_SPARK_LLM_MODEL'])
    output, receipt = asyncio.run(stream_reply(view=view, prompt=GOVERNED_TURN_PROMPT,
        schema=governed_collector_schema(context), model=selected.model, effort=selected.effort,
        budget=QUESTION_BUDGET, base_url=config['MEMORY_SPARK_LLM_BASE_URL'],
        api_key=config['MEMORY_SPARK_LLM_API_KEY'], publisher=FakePublisher(), fence=FENCE,
        metadata={}, timeout=120))
    raw = json.loads(output)
    assert raw.get('question') is not None, raw
    result = validate_governed_collector_result(raw, context)
    question = result['plan']['candidates'][0]['question']
    assert receipt['response_id']
    return question, receipt


@pytest.mark.skipif(os.getenv('MEMOIR_LIVE_QUESTION_NOVELTY') != '1',
                    reason='Opt in to fictional model calls with MEMOIR_LIVE_QUESTION_NOVELTY=1')
@pytest.mark.parametrize('locale', ['en-AU', 'zh-CN'])
@pytest.mark.parametrize('reply_kind', ['partial', 'unanswered', 'reopen'])
def test_live_reply_moves_on_unless_the_narrator_explicitly_reopens_the_question(locale, reply_kind, monkeypatch):
    context, view = partial_answer(locale, reply_kind=reply_kind)
    question, receipt = live_question(context, view, monkeypatch)
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


SCENARIOS = ('new_scene', 'known_company', 'closed_topic', 'unfolding', 'routine', 'consequence', 'reflection')


def question_goal_case(locale, scenario, contract):
    if locale == 'zh-CN':
        earlier = '小时候我和学校家属院的小朋友一起玩，下雨后我和小宁一起捉蜗牛。'
        asked = '那次捉蜗牛后来发生了什么？'
        current = '这张照片是河畔公园的钟楼。小时候从大门走到钟楼总觉得好远，长大后觉得没有那么远了。'
        known, paused = '那时每次去都是妈妈带我去的。', '先不聊家属院的小朋友了。'
    else:
        earlier = ('As a child I played with the other children in our housing compound. '
                   'Robin and I collected snails after rain.')
        asked = 'What happened after you caught the snails?'
        current = ('This photo is of the clock tower in River Gardens. As a child the walk '
                   'from the entrance felt very long, but it seemed much shorter when I grew up.')
        known = 'Those visits were always with my mother.'
        paused = 'Please set aside the children from the compound. '
    current = {'new_scene': current, 'known_company': current + known, 'closed_topic': paused + current}.get(scenario)
    if current is None:
        if locale == 'zh-CN':
            earlier, asked = '我在一家修车铺当学徒。', '您还记得工作中的哪些事？'
            if scenario == 'routine':
                earlier, asked = '我小时候常跟奶奶一起做饭。', '你们通常一起做些什么？'
            elif scenario == 'consequence':
                earlier, asked = '我曾经因为降工资辞过职。', '您当时是怎么离开的？'
            elif scenario == 'reflection':
                earlier, asked = '妈妈开了一家修车铺。', '您怎么看妈妈经营修车铺的那段生活？'
            current = {
                'unfolding': '有一天我独自在店里，水管突然爆了。我关上阀门，可水还在不断上涨。',
                'routine': '每周六奶奶教我包饺子。她包的不会破，我包的一煮就裂开了。',
                'consequence': '老板宣布降工资，我就辞职了。我交接完工作，周五离开了。那次决定改变了我后来选工作的方式。',
                'reflection': '妈妈总是把修车铺开到很晚。现在我明白了，那是她照顾我们一家人的方式。',
            }[scenario]
        else:
            earlier, asked = 'I was an apprentice in a repair shop.', 'What do you remember about working there?'
            if scenario == 'routine':
                earlier, asked = 'I often cooked with Grandma as a child.', 'What did you usually make together?'
            elif scenario == 'consequence':
                earlier, asked = 'I once resigned after a pay cut.', 'How did you leave that job?'
            elif scenario == 'reflection':
                earlier, asked = 'Mother ran a repair shop.', 'How do you look back on her time running it?'
            current = {
                'unfolding': 'One day I was alone in the shop when a pipe burst. I closed the valve, but the water kept rising.',
                'routine': 'Every Saturday Grandma taught me to fold dumplings. Hers stayed intact, but mine split when boiled.',
                'consequence': 'The boss announced a pay cut, so I resigned. I finished the handover and left on Friday. That decision changed how I chose later jobs.',
                'reflection': 'Mother always kept the repair shop open late. Now I understand that was how she cared for our family.',
            }[scenario]
    governed, context = fixture()
    context.update(reply_contract=contract, two_lane_memory=True, interview_language=locale,
        opening_turn=False, recent_dialogue=[dict(status='responded',
            question=dict(id='fictional-snail-question', text=asked, role='assistant',
                          personal_testimony=False, delivered=True),
            response=dict(id='00000000-0000-0000-0000-000000000005', version=1,
                          text=earlier, role='user', kind='narrator_chat', complete=True))])
    context['source']['text'] = current
    if contract == 'reply-v2':
        instructions = reply_instructions()
    else:
        from apps.api.interview_strategy import strategy_instructions
        from apps.api.prompt_composition import render_prompt_artifact
        from apps.api.prompt_artifact import prompt_path
        from apps.api.lifetime_memory_continuity import GOVERNED_CONTINUITY_INSTRUCTIONS
        context.update(strategy_selector=True, active_strategy='explore')
        instructions = '\n'.join((strategy_instructions('explore'), render_prompt_artifact(
            prompt_path('memoir/skills/memoir-interviewer/language-' + locale)),
            GOVERNED_CONTINUITY_INSTRUCTIONS))
    packet = json.loads(governed.packet)
    packet['current']['narrator'].update(original=current, char_end=len(current), language=locale)
    packet['pinned']['language'] = locale
    packet.update(instructions=instructions, interview_context={
        key: value for key, value in context.items() if key not in {'source', 'sources'}})
    governed = encode(packet).model_copy(update={'budget': QUESTION_BUDGET})
    return context, reply_packet(validate_governed_context(governed, context))


@pytest.mark.parametrize('locale', ['en-AU', 'zh-CN'])
@pytest.mark.parametrize('scenario', SCENARIOS)
@pytest.mark.parametrize('contract', ['reply-v2', 'two-lane-v1'])
def test_question_goal_request_preserves_the_prior_exchange_and_current_narration(locale, scenario, contract):
    context, view = question_goal_case(locale, scenario, contract)
    messages = reply_messages(view, GOVERNED_TURN_PROMPT)
    sent = json.loads(messages[1]['content'])['context']['recent_dialogue']
    assert sent == context['recent_dialogue']
    assert sent[0]['response']['id'] != context['source']['id']
    assert json.loads(messages[-1]['content'])['current']['narrator']['original'] == context['source']['text']


@pytest.mark.skipif(os.getenv('MEMOIR_LIVE_QUESTION_NOVELTY') != '1',
                    reason='Opt in to fictional model calls with MEMOIR_LIVE_QUESTION_NOVELTY=1')
@pytest.mark.parametrize('locale', ['en-AU', 'zh-CN'])
@pytest.mark.parametrize('scenario', SCENARIOS)
@pytest.mark.parametrize('contract', ['reply-v2', 'two-lane-v1'])
def test_live_next_question_changes_purpose_with_the_current_story(locale, scenario, contract, monkeypatch):
    context, view = question_goal_case(locale, scenario, contract)
    question, receipt = live_question(context, view, monkeypatch)
    peers = r'小朋友|孩子|伙伴|朋友|小宁' if locale == 'zh-CN' else r'\b(children|kids|friends?|Robin)\b'
    # Fixture-specific checks supplement review of the actual questions; these are not production filters.
    assert not re.search(r'蜗牛|snails?|难忘|memorable', question, re.I), question
    assert not re.search(r'谁.*(?:或者|以及).*做什么|who.*(?:or|and).*what', question, re.I), question
    if scenario == 'new_scene':
        assert re.search(r'公园|钟楼|那里|那儿|这段路|那段路|gardens|tower|there|that walk|the walk', question, re.I), question
        assert re.search(r'谁|一起|怎么去|小朋友|children|with|who|go', question, re.I), question
        assert not re.search(r'和.*(?:去|逛).*(?:的时候|时，)', question), question
    elif scenario in {'known_company', 'closed_topic'}:
        assert not re.search(peers, question, re.I), question
        if scenario == 'known_company':
            assert not re.search(r'跟谁|和谁|谁.*一起|who.*(?:with|along)', question, re.I), question
    else:
        focus = {
            'unfolding': r'后来|接着|接下来|之后|怎么办|做|处理|应对|next|then|after|do|respond|stop|handle',
            'routine': r'包|捏|折|教|煮|饺|裂|破|fold|dumpling|teach|show|split',
            'consequence': r'后来|以后|之后|选择|影响|改变|挑|工作|later|job|work|change|affect|choice',
            'reflection': r'现在|如今|意义|理解|照顾|感受|意味|看待|mean|now|care|understand|view',
        }[scenario]
        assert re.search(focus, question, re.I), question
    print(json.dumps(dict(locale=locale, scenario=scenario, contract=contract,
        question=question, model=receipt['model']), ensure_ascii=False))
