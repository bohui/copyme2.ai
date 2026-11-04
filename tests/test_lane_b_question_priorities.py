"""Atlas supplies context; Mira owns the wording and direction of every question."""
from copy import deepcopy
import json

import pytest

from apps.api.conversation_reply import reply_packet, reply_schema
from apps.api.lifetime_memory_continuity import validate_governed_collector_result
from apps.api.lifetime_memory_engine import validate_governed_context
from test_conversation_reply import proposal, reply_context
from test_historical_news import ready_context
from test_lifetime_memory_engine import encode, fixture
from test_reply_v2_contract_compatibility import hint


def test_background_plans_cannot_change_the_reply_schema_or_selected_question():
    context = reply_context()
    context['strategy_selector'] = True
    before = reply_schema(context)
    candidate = hint(context, 'a', confirmation=True)
    context.update(prepared_questions=[candidate], strategy_context=dict(plan=dict(
        plan_revision=9, strategy='shape', objective='broaden_scope', candidates=[candidate])))
    assert reply_schema(context) == before
    result = validate_governed_collector_result(proposal(), context)
    assert result['plan']['candidates'][0]['question'] == proposal()['question']
    assert result['plan']['chosen_id'].startswith('immediate-')
    assert result['strategy_outcome']['plan_revision_seen'] is None
    assert result['strategy_outcome']['selected_candidate_id'] is None


def test_reply_packet_has_no_background_question_or_strategy_channels():
    governed, context = fixture()
    context.update(reply_contract='reply-v2', two_lane_memory=True, strategy_selector=True,
        active_strategy='shape', prepared_questions=[hint(context, 'a')],
        strategy_context=dict(plan=dict(objective='broaden_scope', candidates=[hint(context, 'b')])) )
    raw = json.loads(governed.packet)
    raw['interview_context'] = {key: value for key, value in context.items() if key not in {'source', 'sources'}}
    view = reply_packet(validate_governed_context(encode(raw), context))
    assert set(view['brief']) == {'covered_through_sequence'}
    assert not {'active_strategy', 'strategy_context', 'prepared_questions'} & view['context'].keys()
    assert 'bq-' not in json.dumps(view)


@pytest.mark.parametrize('locale', ['en-AU', 'zh-CN'])
@pytest.mark.parametrize('use_news', [False, True])
def test_public_news_is_optional_context_and_never_rewrites_miras_question(locale, use_news):
    context = {**reply_context(), **ready_context(), 'interview_language': locale}
    clue = context['historical_news']['clues'][0]
    question = '那份公开档案让您想起什么吗？' if locale == 'zh-CN' else 'Does that public archive bring any memory to mind?'
    raw = {**proposal(), 'question': question, 'historical_clue_id': clue['id'] if use_news else None}
    before = deepcopy(raw)
    result = validate_governed_collector_result(raw, context)
    assert result['plan']['candidates'][0]['question'] == question
    assert result['plan']['candidates'][0]['context'].get('evidence') is None
    assert bool(result.get('historical_context')) == use_news
    assert raw == before


@pytest.mark.parametrize('reason', ['pause', 'direct_answer', 'user_redirect', 'current_correction', 'pacing'])
def test_current_intent_has_no_background_question_override(reason):
    context = {**reply_context(), **ready_context()}
    context['prepared_questions'] = [hint(context, 'a', confirmation=True)]
    question = None if reason in {'pause', 'direct_answer'} else 'What would you like to share about your sister?'
    result = validate_governed_collector_result({**proposal(), 'reason': reason, 'question': question}, context)
    assert [candidate['question'] for candidate in result['plan']['candidates']] == ([] if question is None else [question])
