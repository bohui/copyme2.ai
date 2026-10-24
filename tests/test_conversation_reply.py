"""The small wire retains host authority and original-source evidence."""
from copy import deepcopy
import json

from jsonschema import validate
import pytest

from apps.api.conversation_reply import reply_instructions, reply_packet
from apps.api.lifetime_memory_continuity import (governed_collector_schema,
    validate_governed_collector_result, validate_continuity_updates)
from test_lifetime_memory_continuity import context, update


def reply_context(text='My brother Ming moved to Perth.'):
    return {**context(text), 'two_lane_memory': True, 'reply_contract': 'reply-v2'}


def proposal():
    return dict(acknowledgement='We can follow that memory.', question='What do you remember about the move?',
        reason='latest_story', hint=None, quote=None, work={'mode': 'extract', 'name': None})


def test_small_wire_keeps_compatibility_and_rejects_host_metadata():
    ctx = reply_context()
    raw = proposal()
    schema = governed_collector_schema(ctx)
    validate(raw, schema)
    result = validate_governed_collector_result(raw, ctx)
    assert result['plan']['work'] == raw['work']
    assert result['plan']['candidates'][0]['question'] == raw['question']
    assert raw['question'] in result['reply']
    assert result['continuity_updates'] == result['place_journeys'] == []
    assert not {'source_id', 'continuity_updates', 'associations', 'used_strategy'} & schema['properties'].keys()
    for key in ('source_id', 'source_version', 'continuity_updates', 'char_start', 'associations'):
        with pytest.raises(ValueError):
            validate_governed_collector_result({**raw, key: []}, ctx)


def test_unique_current_quote_gets_exact_server_owned_source_and_offsets():
    ctx = reply_context('😀 My brother Ming moved to Perth.')
    raw = {**proposal(), 'quote': 'Ming moved to Perth'}
    before = deepcopy(raw)
    result = validate_governed_collector_result(raw, ctx)
    evidence = result['plan']['candidates'][0]['context']['evidence']
    assert evidence['source_id'] == ctx['source']['id']
    assert evidence['version'] == ctx['source']['version']
    assert ctx['source']['text'][evidence['char_start']:evidence['char_end']] == raw['quote']
    assert raw == before


@pytest.mark.parametrize('text,quote', [('Ming left. Ming left.', 'Ming left'), ('Ming left.', 'Ming stayed')])
def test_ambiguous_or_fabricated_quote_is_not_repaired(text, quote):
    with pytest.raises(ValueError):
        validate_governed_collector_result({**proposal(), 'quote': quote}, reply_context(text))


@pytest.mark.parametrize('change', [
    {'reason': 'pause'}, {'question': None}, {'hint': 0}, {'reason': 'prepared_candidate'},
    {'work': {'mode': 'reply_only', 'name': 'stored foreign name'}},
])
def test_inconsistent_control_or_foreign_name_is_rejected(change):
    with pytest.raises(ValueError):
        validate_governed_collector_result({**proposal(), **change}, reply_context())


def test_stop_keeps_new_story_work_without_a_followup():
    raw = {**proposal(), 'question': None, 'reason': 'pause'}
    result = validate_governed_collector_result(raw, reply_context())
    assert result['plan']['candidates'] == []
    assert result['reply'] == raw['acknowledgement']
    assert result['plan']['work']['mode'] == 'extract'


def test_stop_accepts_an_exact_current_anchor_without_creating_question_evidence():
    current = 'Please stop. No more questions today.'
    raw = {**proposal(), 'question': None, 'reason': 'pause', 'quote': current}
    result = validate_governed_collector_result(raw, reply_context(current))
    assert result['stopped'] and result['plan']['candidates'] == []
    with pytest.raises(ValueError):
        validate_governed_collector_result({**raw, 'quote': 'Invented narrator wording'}, reply_context(current))


def test_explicit_current_name_update_survives_extract_work_without_weakening_legacy_plan():
    raw = {**proposal(), 'work': {'mode': 'extract', 'name': 'Avery'}}
    result = validate_governed_collector_result(raw, reply_context('Please call me Avery. I grew up in Perth.'))
    assert result['immediate_name'] == 'Avery'
    assert result['plan']['work'] == {'mode': 'extract', 'name': None}


def test_pending_hint_uses_exact_host_evidence_and_current_intent_can_override_it():
    ctx = reply_context()
    ctx['prepared_questions'] = [dict(id='bq-' + 'a'*64,
        question='Was the move before school?', quote='Ming moved to Perth',
        source_id=ctx['source']['id'], source_version=ctx['source']['version'],
        char_start=11, char_end=30, requires_confirmation=True)]
    raw = {**proposal(), 'question': ctx['prepared_questions'][0]['question'],
           'hint': 0, 'reason': 'prepared_candidate'}
    result = validate_governed_collector_result(raw, ctx)
    assert result['plan']['chosen_id'] == ctx['prepared_questions'][0]['id']
    with pytest.raises(ValueError):
        validate_governed_collector_result({**raw, 'quote': 'Invented words'}, ctx)
    stopped = validate_governed_collector_result({**proposal(), 'question': None, 'reason': 'pause'}, ctx)
    assert stopped['plan']['candidates'] == []


def test_all_strategy_and_locale_data_share_the_compiled_instruction_budget():
    from apps.api.lifetime_memory_engine import GOVERNED_TURN_PROMPT
    instructions = reply_instructions()
    assert len(instructions + '\n' + GOVERNED_TURN_PROMPT) < 2000
    assert '{{prompt:' not in instructions


def test_only_validated_packet_is_projected_without_dropping_narrator_evidence():
    from apps.api.lifetime_memory_engine import validate_governed_context
    from test_lifetime_memory_engine import fixture
    governed, ctx = fixture()
    packet = validate_governed_context(governed, ctx)
    view = reply_packet(packet)
    assert view['current'] == packet.current.model_dump(mode='json')
    assert view['dialogue'] == [row.model_dump(mode='json') for row in packet.tail]
    assert view['brief']['covered_through_sequence'] == packet.coverage_end
    assert 'lease_token' not in json.dumps(view)
    assert 'owner_id' not in view


def test_background_unique_quote_is_bound_to_the_admitted_absolute_window():
    ctx = reply_context('My brother Ming moved to Perth.')
    raw = update(ctx, quote='Ming', char_start=None, char_end=None)
    source = {**ctx['source'], 'char_start': 200}
    result = validate_continuity_updates([raw], source, background=True)
    ref = result[0]['data']['source_refs'][0]
    assert ref['char_start'] == 211 and ref['char_end'] == 215


@pytest.mark.parametrize('change', [
    {'char_start': 0, 'char_end': 4}, {'source_version': 2}, {'source_id': 'foreign'},
    {'quote': 'fabricated', 'text': 'fabricated'}, {'kind': 'excluded_topic'},
])
def test_background_continuity_cannot_discard_invalid_proposals(change):
    ctx = reply_context()
    raw = update(ctx, quote='Ming')
    raw.update(change)
    with pytest.raises(ValueError):
        validate_continuity_updates([raw], ctx['source'], background=True)


@pytest.mark.parametrize('field', ['char_start', 'char_end'])
def test_background_continuity_never_manufactures_missing_offset_fields(field):
    ctx = reply_context()
    raw = update(ctx, quote='Ming', char_start=None, char_end=None)
    raw.pop(field)
    with pytest.raises(ValueError):
        validate_continuity_updates([raw], ctx['source'], background=True)


def test_engine_sends_evidence_last_without_launching_a_general_agent(tmp_path, monkeypatch):
    import asyncio
    from test_lifetime_memory_engine import fixture, encode, FakePublisher, BUDGET
    from test_conversation_reply_transport import install_reply_provider
    from apps.api.lifetime_memory_engine import run_governed_collector
    governed, ctx = fixture()
    ctx.update(reply_contract='reply-v2', two_lane_memory=True)
    packet = json.loads(governed.packet)
    packet.update(instructions=reply_instructions(), interview_context={
        key: value for key, value in ctx.items() if key not in {'source', 'sources'}})
    governed = encode(packet)
    captured = install_reply_provider(monkeypatch, [proposal()])
    def forbidden(*args, **kwargs):
        raise AssertionError('reply-v2 launched a general agent')
    result = asyncio.run(run_governed_collector(command=['fake'], home_root=tmp_path,
        base_url='http://provider.invalid/v1', api_key='synthetic', model=BUDGET.model,
        governed=governed, interview_context=ctx, connection_factory=forbidden, publisher=FakePublisher()))
    current = json.loads(captured[0]['input'][-1]['content'])['current']
    context = json.loads(captured[0]['input'][1]['content'])
    assert current['narrator'] == packet['current']['narrator']
    assert current['sequence'] == packet['current']['sequence']
    assert context['dialogue'] == packet['tail']
    assert 'fence' not in context and 'identity' not in context
    assert context['brief']['covered_through_sequence'] == 0
    assert json.loads(result['reply']) == proposal()
    assert not list(tmp_path.iterdir())


def test_repair_identifies_a_copied_stored_name_instead_of_repeating_a_generic_failure(tmp_path, monkeypatch):
    import asyncio
    from test_lifetime_memory_engine import fixture, encode, FakePublisher, BUDGET
    from test_conversation_reply_transport import install_reply_provider
    from apps.api.lifetime_memory_engine import run_governed_collector
    governed, ctx = fixture()
    ctx.update(reply_contract='reply-v2', two_lane_memory=True)
    packet = json.loads(governed.packet)
    packet.update(instructions=reply_instructions(), interview_context={
        key: value for key, value in ctx.items() if key not in {'source', 'sources'}})
    invalid = {**proposal(), 'work':{'mode':'extract', 'name':'Stored name absent from source'}}
    def repaired(body):
        assert 'CONTRACT_30' in body['input'][0]['content'][1]['text']
        return proposal()
    captured = install_reply_provider(monkeypatch, [invalid, repaired])
    result = asyncio.run(run_governed_collector(command=['fake'], home_root=tmp_path,
        base_url='http://provider.invalid/v1', api_key='synthetic', model=BUDGET.model,
        governed=encode(packet), interview_context=ctx, publisher=FakePublisher()))
    assert len(captured) == 2
    assert json.loads(result['reply'])['work']['name'] is None


def test_hint_quote_mismatch_is_rejected_then_repaired_without_replacing_its_evidence(tmp_path, monkeypatch):
    import asyncio
    from test_lifetime_memory_engine import fixture, encode, FakePublisher, BUDGET
    from test_conversation_reply_transport import install_reply_provider
    from test_reply_v2_contract_compatibility import hint
    from apps.api.lifetime_memory_engine import run_governed_collector
    governed, ctx = fixture()
    candidate = hint(ctx, 'a')
    ctx.update(reply_contract='reply-v2', two_lane_memory=True, prepared_questions=[candidate])
    packet = json.loads(governed.packet)
    packet.update(instructions=reply_instructions(), interview_context={
        key: value for key, value in ctx.items() if key not in {'source', 'sources'}})
    valid = {**proposal(), 'hint': 0, 'question': candidate['question'], 'reason': 'prepared_candidate'}
    invalid = {**valid, 'quote': 'Invented evidence'}
    before = deepcopy(invalid)
    with pytest.raises(ValueError, match='cannot change its referenced passage'):
        validate_governed_collector_result(invalid, ctx)
    assert invalid == before
    def repaired(body):
        assert 'CONTRACT_31' in body['input'][0]['content'][1]['text']
        assert 'set quote=null' in body['input'][0]['content'][1]['text']
        return valid
    captured = install_reply_provider(monkeypatch, [invalid, repaired])
    result = asyncio.run(run_governed_collector(command=['forbidden'], home_root=tmp_path,
        base_url='https://provider.invalid/v1', api_key='synthetic', model=BUDGET.model,
        governed=encode(packet), interview_context=ctx, publisher=FakePublisher()))
    assert len(captured) == 2
    adapted = validate_governed_collector_result(json.loads(result['reply']), ctx)
    assert adapted['plan']['candidates'][0]['context']['evidence']['quote'] == candidate['quote']


@pytest.mark.parametrize('language,current', [
    ('en-AU', 'What else could we explore from those years?'),
    ('zh-CN', '关于那些年，我们还可以聊些什么？'),
])
def test_question_reason_repair_keeps_the_current_invitation_and_ready_news_hint(tmp_path, monkeypatch, language, current):
    import asyncio
    from apps.api.lifetime_memory_engine import run_governed_collector
    from test_conversation_reply_transport import install_reply_provider
    from test_historical_news import ready_context
    from test_lifetime_memory_engine import fixture, encode, FakePublisher, BUDGET

    governed, ctx = fixture()
    ctx.update(deepcopy(ready_context()), reply_contract='reply-v2', two_lane_memory=True,
        interview_language=language)
    ctx['source']['text'] = current
    packet = json.loads(governed.packet)
    packet['current']['narrator'].update(original=current, char_end=len(current), language=language)
    packet['pinned']['language'] = language
    packet.update(instructions=reply_instructions(), interview_context={
        key: value for key, value in ctx.items() if key not in {'source', 'sources'}})
    acknowledgement = ('我们可以按您的节奏继续回忆。' if language == 'zh-CN'
                       else 'We can keep following your memories at your pace.')
    invalid = {**proposal(), 'acknowledgement': acknowledgement, 'reason': 'direct_answer'}

    def repaired(body):
        feedback = body['input'][0]['content'][1]['text']
        assert 'CONTRACT_16' in feedback and 'No-question outcome requires an explicit reason' in feedback
        context = json.loads(body['input'][1]['content'])
        hint = context['brief']['hints'][0]
        assert hint['historical_clue_id'] == ctx['historical_news']['clues'][0]['id']
        assert json.loads(body['input'][-1]['content'])['current']['narrator']['original'] == current
        return {**invalid, 'reason': 'prepared_candidate', 'hint': 0, 'question': hint['question']}

    captured = install_reply_provider(monkeypatch, [invalid, repaired])
    result = asyncio.run(run_governed_collector(command=['forbidden'], home_root=tmp_path,
        base_url='https://provider.invalid/v1', api_key='synthetic', model=BUDGET.model,
        governed=encode(packet), interview_context=ctx, publisher=FakePublisher()))
    assert len(captured) == 2
    accepted = validate_governed_collector_result(json.loads(result['reply']), ctx)
    assert accepted['historical_context']['source_url'] == ctx['historical_news']['clues'][0]['source_url']
    assert accepted['acknowledgement'] == acknowledgement


@pytest.mark.parametrize('language,current,continuation,stopped', [
    ('en-AU', 'Please stop. No more questions today.',
     'We can keep following your memories at your pace.', 'Understood. We’ll stop here for today.'),
    ('zh-CN', '今天到这里，请不要再问了。',
     '我们可以按您的节奏继续回忆。', '好的，今天就到这里。'),
])
@pytest.mark.parametrize('revisable', [False, True])
@pytest.mark.parametrize('anchored', [False, True])
def test_ready_news_pause_delivers_an_explicit_stop_instead_of_the_continuation_copy(
        tmp_path, monkeypatch, language, current, continuation, stopped, revisable, anchored):
    import asyncio
    from apps.api.lifetime_memory_engine import run_governed_collector
    from test_conversation_reply_transport import install_reply_provider
    from test_historical_news import ready_context
    from test_lifetime_memory_engine import fixture, encode, FakePublisher, BUDGET

    governed, ctx = fixture()
    ctx.update(deepcopy(ready_context()), reply_contract='reply-v2', two_lane_memory=True,
        interview_language=language, revisable_reply=revisable)
    monkeypatch.setenv('MEMORY_SPARK_PARALLEL_POLICY_REVIEW', '1' if revisable else '0')
    ctx['source']['text'] = current
    packet = json.loads(governed.packet)
    packet['current']['narrator'].update(original=current, char_end=len(current), language=language)
    packet['pinned']['language'] = language
    packet.update(instructions=reply_instructions(), interview_context={
        key: value for key, value in ctx.items() if key not in {'source', 'sources'}})
    raw = {**proposal(), 'acknowledgement': continuation, 'question': None, 'reason': 'pause',
        'quote': current if anchored else None, 'work': {'mode': 'reply_only', 'name': None}}
    captured = install_reply_provider(monkeypatch, [raw])
    visible = []
    async def delta(value):
        visible.append(json.loads(value)['acknowledgement'])

    result = asyncio.run(run_governed_collector(command=['forbidden'], home_root=tmp_path,
        base_url='https://provider.invalid/v1', api_key='synthetic', model=BUDGET.model,
        governed=encode(packet), interview_context=ctx, publisher=FakePublisher(), on_delta=delta))

    accepted = validate_governed_collector_result(json.loads(result['reply']), ctx)
    assert accepted['reply'] == stopped
    assert visible == [stopped]
    assert accepted['plan']['candidates'] == [] and accepted.get('historical_context') is None
    assert len(captured) == 1
