"""Opt-in model regressions for grounded, non-redundant follow-up questions.

Run with MEMORY_SPARK_RUN_LIVE_INTERVIEW_TESTS=1 and the application's
MEMORY_SPARK_LLM_* settings. Each case uses an isolated, ephemeral Codex thread.
"""
import asyncio
import os
import re

import pytest

from apps.api.codex_agent import CodexConnection, provider_config
from apps.api.codex_runtime import CodexRuntime, build_conversation_system_prompt
from apps.api.interview_plan import collector_schema, validate_collector_result


ZH_MEMORY = (
    '离宫很近，每到夏天就会用吃过的水果罐子系上绳，'
    '罐子里面放上虾和小鱼爱吃的鸡骨头、剩菜（当然鸡骨头是最好用的）。'
    '去离宫的湖边上，四五个罐子往水里一扔，然后人就去旁边聊天，'
    '等一二十分钟把罐子拉上来看看有没有贪吃的河虾和小鱼游到罐子里。'
    '后来我长大了离宫已经不让人闷虾了，小时候的趣事是很多现在生活在城市里的小朋友想象不到的。'
)
EN_MEMORY = (
    'Every summer we tied string to four or five empty fruit tins, baited them with '
    'chicken bones and leftovers, and threw them into the lake near the palace '
    'to catch shrimp and little fish. Chicken bones worked best. We chatted nearby '
    'and pulled the tins up after ten or twenty minutes to check for shrimp and little fish. '
    'By the time I grew up, trapping shrimp there was no longer allowed.'
)
# Catch the reported question and paraphrases asking for the same supplied fact.
# This is a narrow regression oracle, not a general semantic question validator.
REDUNDANT_CATCH_QUESTION = re.compile(
    r'(?:捞|抓|捕|钓|装|收获)[^。？！?\n]{0,25}(?:什么(?!样)|哪些|哪种)'
    r'|罐[^。？！?\n]{0,12}(?:里面|里头|里)[^。？！?\n]{0,12}(?:什么(?!样)|哪些|哪种)'
    r'|(?:什么东西|什么动物|哪些鱼|哪些东西)[^。？！?\n]{0,30}(?:罐|捞|抓|捕|钓)'
    r'|\bwhat\s+(?:did|would|could|can)\s+(?:you|we)\s+(?:(?:usually|typically)\s+)?(?:catch|trap|capture|find)\b'
    r'|\b(?:what|which)\s+(?:(?:kind|types?|sorts?)\s+of\s+)?(?:fish|animals|creatures|things)\b',
    re.IGNORECASE,
)


def test_regression_oracle_catches_the_reported_redundant_question():
    bad = '罐子拉出水的那一刻，你记得捞上来的都是些什么吗？'
    assert REDUNDANT_CATCH_QUESTION.search(bad)
    assert REDUNDANT_CATCH_QUESTION.search('What did you catch in the tins?')
    assert not REDUNDANT_CATCH_QUESTION.search('捞到河虾和小鱼后，你们怎么处理？')
    assert not REDUNDANT_CATCH_QUESTION.search('What did you do with the shrimp and little fish afterwards?')
    assert not REDUNDANT_CATCH_QUESTION.search('你还记得提起罐子时，里面通常是什么样子吗？')
    assert not REDUNDANT_CATCH_QUESTION.search('What do you remember about pulling up a tin?')


@pytest.mark.skipif(
    os.getenv('MEMORY_SPARK_RUN_LIVE_INTERVIEW_TESTS') != '1',
    reason='Opt-in live model evaluation; requires the configured application provider',
)
@pytest.mark.parametrize('language,memory', [('zh-CN', ZH_MEMORY), ('en-AU', EN_MEMORY)], ids=['zh-CN', 'en-AU'])
@pytest.mark.parametrize('earlier_context', [False, True], ids=['current-message', 'earlier-context'])
def test_live_followup_builds_on_the_known_catch(tmp_path, language, memory, earlier_context):
    runtime = CodexRuntime()
    (tmp_path / 'config.toml').write_text(provider_config(runtime.base_url, runtime.model))
    context = runtime._memory_context([{'content': f'Storyteller: {memory}'}]) if earlier_context else '(none)'
    message = (
        ('那是我们小时候夏天常做的事。' if language == 'zh-CN' else 'That was our usual summer pastime as children.')
        if earlier_context else memory
    )

    async def run():
        async with CodexConnection(
            runtime.command, tmp_path,
            provider_env={'MEMORY_SPARK_LLM_API_KEY': runtime.api_key},
            timeout=runtime.timeout,
        ) as connection:
            result = await connection.request('thread/start', {
                'cwd': str(tmp_path), 'ephemeral': True,
                'modelProvider': 'llm_provider', 'model': runtime.model,
                'approvalPolicy': 'never', 'sandbox': 'read-only',
                'baseInstructions': build_conversation_system_prompt(context, language=language),
            })
            return await connection.turn(result['thread']['id'], f'Storyteller message:\n{message}')

    reply = asyncio.run(run())
    print(f'{language}, earlier_context={earlier_context}: {reply}')
    assert reply.strip(), 'The model must produce a visible reply'
    # Examine questions only: acknowledgements may correctly mention the catch.
    questions = re.findall(r'[^。.!?？！\n]*[?？]', reply)
    assert all(not REDUNDANT_CATCH_QUESTION.search(question) for question in questions), reply


def _live_collector_result(tmp_path, prompt_version, language, message, *, opening_turn=True, memories='(none)'):
    runtime = CodexRuntime()
    (tmp_path / 'config.toml').write_text(provider_config(runtime.base_url, runtime.model))
    context = {
        'source': {'id': 'followup-source', 'version': 1, 'status': 'active', 'text': message},
        'opening_turn': opening_turn,
        'interview_language': language,
    }

    async def run():
        async with CodexConnection(
            runtime.command, tmp_path,
            provider_env={'MEMORY_SPARK_LLM_API_KEY': runtime.api_key},
            timeout=runtime.timeout,
        ) as connection:
            result = await connection.request('thread/start', {
                'cwd': str(tmp_path), 'ephemeral': True,
                'modelProvider': 'llm_provider', 'model': runtime.model,
                'approvalPolicy': 'never', 'sandbox': 'read-only',
                'baseInstructions': build_conversation_system_prompt(
                    memories, language=language, interview_context=context,
                    conversation_rounds_completed=0 if opening_turn else 1, prompt_version=prompt_version,
                ),
            })
            return await connection.turn(result['thread']['id'], f'Storyteller message:\n{message}',
                output_schema=collector_schema(context))

    result = validate_collector_result(asyncio.run(run()), context)
    print(f'{prompt_version}, {language}: {result["reply"]}')
    return result


@pytest.mark.skipif(
    os.getenv('MEMORY_SPARK_RUN_LIVE_INTERVIEW_TESTS') != '1',
    reason='Opt-in live model evaluation; requires the configured application provider',
)
@pytest.mark.parametrize('prompt_version', ['legacy', 'compact-v1'])
@pytest.mark.parametrize('language,message,place', [
    ('zh-CN', '我叫慧博，现在生活在悉尼，但是我于1983年4月出生在河北省承德市附属医院', '承德'),
    ('en-AU', 'My name is Huibo. I live in Sydney now, but I was born in April 1983 at a hospital in Chengde, Hebei.', 'Chengde'),
], ids=['zh-CN', 'en-AU'])
def test_live_first_reply_follows_the_volunteered_birthplace(tmp_path, prompt_version, language, message, place):
    result = _live_collector_result(tmp_path, prompt_version, language, message)
    plan = result['plan']
    question = next(candidate['question'] for candidate in plan['candidates']
        if candidate['id'] == plan['chosen_id'])
    # A question can follow the birthplace by clarifying where they grew up.
    assert place.casefold() in question.casefold() or re.fullmatch(
        r'Where did you grow up\?|您(?:小时候)?(?:是)?在哪[里儿]长大(?:的)?？',
        question, re.IGNORECASE,
    ), result['reply']
    assert question.count('?') + question.count('？') == 1
    assert plan['work'] == {'mode': 'extract', 'name': None}
    assert not re.search(
        r'(?:您|你)(?:小时候|童年|成长时)(?:一直|就)?(?:住在|生活在)承德'
        r'|\byour childhood (?:home|neighbou?rhood) in Chengde\b'
        r'|\b(?:you grew up|growing up|your upbringing) in Chengde\b', question, re.IGNORECASE,
    ), result['reply']


@pytest.mark.skipif(
    os.getenv('MEMORY_SPARK_RUN_LIVE_INTERVIEW_TESTS') != '1',
    reason='Opt-in live model evaluation; requires the configured application provider',
)
@pytest.mark.parametrize('prompt_version', ['legacy', 'compact-v1'])
@pytest.mark.parametrize('language,message,previous_question', [
    ('zh-CN', '我想聊一下小时候的故事', '您今天最想先聊哪一段记忆？'),
    ('en-AU', 'I would like to talk about my childhood.', 'Which memory would you like to talk about today?'),
], ids=['zh-CN', 'en-AU'])
def test_live_topic_choice_gets_a_followup_without_an_echo(tmp_path, prompt_version, language, message, previous_question):
    result = _live_collector_result(tmp_path, prompt_version, language, message,
        opening_turn=False, memories=f'Memory Spark: {previous_question}')
    # Catch the reported declarative restatement, not every use of a topic word.
    assert not re.search(
        r'(?:您|你)(?:说|提到|想|希望|愿意|打算)[^。.!?？！\n]{0,40}(?:小时候|童年)'
        r'|\byou(?:[’\']d|\s+(?:would|want|wanted|mentioned|said|wish))[^.!?\n]{0,80}(?:childhood|growing up)',
        result['acknowledgement'], re.IGNORECASE,
    ), result['reply']
    plan = result['plan']
    question = next(candidate['question'] for candidate in plan['candidates']
        if candidate['id'] == plan['chosen_id'])
    assert re.search(r'小时候|童年|那时|当时|childhood|as a child|growing up|back then',
        question, re.IGNORECASE), result['reply']
    assert question.count('?') + question.count('？') == 1
