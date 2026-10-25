"""Small reply proposals preserve the existing news, hint and photo contracts."""
from copy import deepcopy
import json

from jsonschema import validate
import pytest

from apps.api.interview_plan import historical_acknowledgements
from apps.api.lifetime_memory_continuity import governed_collector_schema, validate_governed_collector_result
from test_conversation_reply import proposal, reply_context


@pytest.mark.parametrize('locale', ['en-AU', 'zh-CN'])
@pytest.mark.parametrize('stopping', [False, True])
def test_historical_news_supplies_its_required_acknowledgement_without_a_conflicting_pattern(locale, stopping):
    ctx = reply_context()
    ctx.update(interview_language=locale, historical_news={'enabled': True, 'clues': [{'id': 'public'}]})
    field = governed_collector_schema(ctx)['properties']['acknowledgement']
    assert set(field['enum']) == historical_acknowledgements(ctx)
    assert 'pattern' not in field
    acknowledgement = {'en-AU': 'We can keep following your memories at your pace.',
                       'zh-CN': '我们可以按您的节奏继续回忆。'}[locale]
    raw = {**proposal(), 'acknowledgement': acknowledgement}
    if stopping:
        raw.update(question=None, reason='pause', work={'mode': 'reply_only', 'name': None})
    validate(raw, governed_collector_schema(ctx))
    result = validate_governed_collector_result(raw, ctx)
    if stopping:
        expected = {'en-AU': 'Understood. We’ll stop here for today.', 'zh-CN': '好的，今天就到这里。'}[locale]
        assert result['acknowledgement'] == result['reply'] == expected
        assert not result['plan']['candidates']
        assert result.get('historical_context') is None
    else:
        assert result['acknowledgement'] == acknowledgement


@pytest.mark.parametrize('locale,acknowledgement', [
    ('en-AU', 'You witnessed the Boston fair in 1970.'),
    ('zh-CN', '您1970年在波士顿参加了展会。'),
    ('en-AU', '好的，今天就到这里。'),
    ('zh-CN', 'Understood. We’ll stop here for today.'),
])
def test_news_stop_copies_do_not_admit_personal_facts_or_switch_language(locale, acknowledgement):
    ctx = reply_context()
    ctx.update(interview_language=locale, historical_news={'enabled': True, 'clues': [{'id': 'public'}]})
    raw = {**proposal(), 'acknowledgement': acknowledgement, 'question': None, 'reason': 'pause'}
    from jsonschema import ValidationError
    with pytest.raises(ValidationError):
        validate(raw, governed_collector_schema(ctx))
    with pytest.raises(ValueError, match='Historical context cannot supply personal acknowledgement facts'):
        validate_governed_collector_result(raw, ctx)


@pytest.mark.parametrize('locale', ['en-AU', 'zh-CN'])
def test_news_copy_reader_accepts_the_published_scalar_inventory_during_rollout(monkeypatch, locale):
    from apps.api import interview_plan
    legacy = {'en-AU': 'We can keep following your memories at your pace.', 'zh-CN': '我们可以按您的节奏继续回忆。'}
    monkeypatch.setattr(interview_plan, 'load_prompt_artifact', lambda path: json.dumps(legacy))
    assert historical_acknowledgements({'interview_language': locale}) == {legacy[locale]}
    assert historical_acknowledgements({}) == set(legacy.values())


def hint(ctx, identity, *, confirmation=False):
    source = ctx['source']
    return dict(id='bq-' + identity * 64, question='What changed after that?',
        topic='move', quote=source['text'], source_id=source['id'], source_version=source['version'],
        char_start=0, char_end=len(source['text']), requires_confirmation=confirmation)


@pytest.mark.parametrize('planned', [False, True])
def test_active_strategy_offers_only_hints_that_its_transaction_can_commit(planned):
    ctx = reply_context()
    ctx.update(strategy_selector=True, strategy_context={'mode': 'active', 'plan': None})
    ctx['prepared_questions'] = [hint(ctx, 'a')]
    if planned:
        ctx['strategy_context']['plan'] = dict(plan_revision=1, strategy='explore', candidates=[hint(ctx, 'b')])
    assert governed_collector_schema(ctx)['properties']['hint']['enum'] == ([None, 0] if planned else [None])
    if not planned:
        with pytest.raises(ValueError):
            validate_governed_collector_result({**proposal(), 'hint': 0, 'reason': 'prepared_candidate',
                'question': ctx['prepared_questions'][0]['question']}, ctx)


def test_pending_confirmation_and_fallback_hint_remain_selectable_in_their_authorized_modes():
    ctx = reply_context()
    ordinary, confirmation = hint(ctx, 'a'), hint(ctx, 'b', confirmation=True)
    ctx['prepared_questions'] = [ordinary]
    raw = {**proposal(), 'hint': 0, 'reason': 'prepared_candidate', 'question': ordinary['question']}
    assert validate_governed_collector_result(raw, ctx)['plan']['chosen_id'] == ordinary['id']
    ctx.update(strategy_selector=True, strategy_context={'mode': 'active', 'plan': None})
    ctx['prepared_questions'].append(confirmation)
    assert governed_collector_schema(ctx)['properties']['hint']['enum'] == [None, 0]
    assert validate_governed_collector_result(raw, ctx)['plan']['chosen_id'] == confirmation['id']


def test_nonselectable_queued_questions_remain_readable_for_evidence_backed_resolution():
    from apps.api.conversation_reply import reply_packet
    from apps.api.lifetime_memory_engine import validate_governed_context
    from test_lifetime_memory_engine import encode, fixture
    governed, ctx = fixture()
    ordinary, planned = hint(ctx, 'a'), hint(ctx, 'b')
    ordinary['question'] = 'What colour was the umbrella?'
    ctx.update(reply_contract='reply-v2', two_lane_memory=True, strategy_selector=True,
        prepared_questions=[ordinary, ordinary],
        strategy_context={'mode': 'active', 'plan': {'plan_revision': 1, 'strategy': 'explore', 'candidates': [planned]}})
    packet = json.loads(governed.packet)
    packet['interview_context'] = {key: value for key, value in ctx.items() if key not in {'source', 'sources'}}
    view = reply_packet(validate_governed_context(encode(packet), ctx))
    assert [row['id'] for row in view['brief']['hints']] == [planned['id']]
    assert view['brief']['resolution_only_questions'] == [dict(id=ordinary['id'], question=ordinary['question'])]
    raw = {**proposal(), 'deferred_hints': [], 'resolved_questions': [dict(question_id=ordinary['id'],
        source_id=ctx['source']['id'], source_version=1, char_start=12, char_end=16, quote='blue')]}
    validate(raw, governed_collector_schema(ctx))
    result = validate_governed_collector_result(raw, ctx)
    assert result['plan']['resolved_questions'][0]['question_id'] == ordinary['id']


def photo_context():
    ctx = reply_context('I recognise this gate in the photo from our childhood visits.')
    ctx['photo_context'] = [dict(photo_id='reference:gate', kind='public_reference', title='Gate')]
    association = dict(photo_id='reference:gate', event_id=None, source_id=ctx['source']['id'],
        source_version=ctx['source']['version'], quote=ctx['source']['text'],
        description='The narrator recognises the gate from childhood visits.', provenance='narrator_metadata')
    return ctx, {**proposal(), 'associations': [association], 'response_photo_ids': ['reference:gate']}


def test_available_photo_identification_reaches_the_existing_validated_association_contract():
    ctx, raw = photo_context()
    before = deepcopy(raw)
    validate(raw, governed_collector_schema(ctx))
    result = validate_governed_collector_result(raw, ctx)
    assert result['associations'] == raw['associations']
    assert result['response_photos'][0]['photo_id'] == 'reference:gate'
    assert raw == before


@pytest.mark.parametrize('fault', ['foreign_photo', 'foreign_source', 'fabricated_quote'])
def test_conditional_photo_fields_keep_existing_evidence_checks(fault):
    ctx, raw = photo_context()
    association = raw['associations'][0]
    if fault == 'foreign_photo':
        association['photo_id'] = 'another-project-photo'
    elif fault == 'foreign_source':
        association['source_id'] = 'another-project-source'
    else:
        association['quote'] = 'The model invented this identification.'
    with pytest.raises(ValueError):
        validate_governed_collector_result(raw, ctx)
