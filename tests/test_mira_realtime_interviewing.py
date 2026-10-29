"""Mira chooses the current question independently of optional background results."""
from copy import deepcopy

from jsonschema import validate
import pytest

from apps.api.conversation_reply import reply_schema
from apps.api.lifetime_memory_continuity import validate_governed_collector_result
from test_conversation_reply import proposal, reply_context
from test_historical_news import ready_context


def news_context():
    return {**reply_context('I remember painting the kitchen with my father.'), **ready_context()}


def test_interview_guidance_is_not_an_active_background_skill():
    from apps.api.background_skills import admit,execution_map,SkillUnavailable
    assert 'memoir-interview-guidance' not in {skill['name'] for skill in execution_map()}
    with pytest.raises(SkillUnavailable,match='legacy'):
        admit('memoir-interview-guidance','accepted_context_change')


def test_mira_can_ignore_ready_news_and_keep_her_current_grounded_reply():
    context = news_context()
    raw = {**proposal(), 'acknowledgement': 'You remember painting the kitchen with your father.',
        'question': 'What was it like spending that time together?', 'historical_clue_id': None}
    validate(raw, reply_schema(context))
    result = validate_governed_collector_result(raw, context)
    assert result['acknowledgement'] == raw['acknowledgement']
    assert result['plan']['candidates'][0]['question'] == raw['question']
    assert 'historical_context' not in result


def test_mira_can_choose_a_sourced_public_clue_without_a_background_question_pool():
    context = news_context()
    clue = context['historical_news']['clues'][0]
    raw = {**proposal(), 'acknowledgement': 'You remember painting the kitchen with your father.',
        'question': 'The town archive describes a public fair then; does that connect with any memory of your neighbourhood?',
        'historical_clue_id': clue['id']}
    before = deepcopy(raw)
    validate(raw, reply_schema(context))
    result = validate_governed_collector_result(raw, context)
    chosen = result['plan']['candidates'][0]
    assert chosen['question'] == raw['question']
    assert chosen['context']['historical_clue_id'] == clue['id']
    assert chosen['context'].get('evidence') is None
    assert result['historical_context']['source_url'] == clue['source_url']
    assert raw == before


def test_mira_keeps_her_connected_question_after_accepting_a_recall_limit():
    text = 'I cannot remember what we ate, but I remember my sister singing in the kitchen.'
    context = reply_context(text)
    raw = {**proposal(), 'reason': 'recall_limit', 'recall_limit_quote': 'I cannot remember what we ate',
        'question': 'What do you remember about your sister singing in the kitchen?'}
    result = validate_governed_collector_result(raw, context)
    assert result['plan']['candidates'][0]['question'] == raw['question']


def test_recall_limit_can_use_optional_news_without_turning_it_into_personal_testimony():
    context = news_context()
    context['source']['text']='I cannot remember our weekends, but I lived in Boston then.'
    raw={**proposal(), 'question':'Does the public fair in that archive bring any memories to mind?',
        'recall_limit_quote':'I cannot remember our weekends',
        'historical_clue_id':context['historical_news']['clues'][0]['id']}
    result=validate_governed_collector_result(raw,context)
    assert result['plan']['candidates'][0]['question']==raw['question']
    assert result['plan']['candidates'][0]['context'].get('evidence') is None
    assert result['historical_context']['source_url']==context['historical_news']['clues'][0]['source_url']


@pytest.mark.parametrize('change', ['opted_out', 'stale', 'foreign', 'unknown', 'personal_evidence'])
def test_optional_news_selection_preserves_public_source_and_privacy_checks(change):
    context = news_context()
    clue = context['historical_news']['clues'][0]
    raw = {**proposal(), 'historical_clue_id': clue['id']}
    if change == 'opted_out':
        context['historical_news']['enabled'] = False
    elif change == 'stale':
        clue['context_revision'] = 'obsolete'
    elif change == 'foreign':
        clue['project_id'] = 'another-project'
    elif change == 'unknown':
        raw['historical_clue_id'] = 'news-not-supplied'
    else:
        raw['quote'] = context['source']['text']
    with pytest.raises(ValueError):
        validate_governed_collector_result(raw, context)
