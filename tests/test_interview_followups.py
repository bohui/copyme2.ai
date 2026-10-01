"""Opt-in model regressions for questions whose answers are already supplied.

Run with MEMORY_SPARK_RUN_LIVE_INTERVIEW_TESTS=1 and the application's
MEMORY_SPARK_LLM_* settings. Each case uses an isolated, ephemeral Codex thread.
"""
import asyncio
import os
import re

import pytest

from apps.api.codex_agent import CodexConnection, provider_config
from apps.api.codex_runtime import CodexRuntime, build_conversation_system_prompt


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
