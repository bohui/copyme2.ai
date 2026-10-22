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


def test_native_engine_uses_the_small_view_after_full_governed_validation(tmp_path):
    import asyncio
    from test_lifetime_memory_engine import fixture, encode, FakeConnection, FakePublisher, BUDGET
    from apps.api.lifetime_memory_engine import run_governed_collector
    governed, ctx = fixture()
    ctx.update(reply_contract='reply-v2', two_lane_memory=True)
    packet = json.loads(governed.packet)
    packet.update(instructions=reply_instructions(), interview_context={
        key: value for key, value in ctx.items() if key not in {'source', 'sources'}})
    governed = encode(packet)
    class Connection(FakeConnection):
        reply = json.dumps(proposal())
    result = asyncio.run(run_governed_collector(command=['fake'], home_root=tmp_path,
        base_url='http://provider.invalid/v1', api_key='synthetic', model=BUDGET.model,
        governed=governed, interview_context=ctx, connection_factory=Connection, publisher=FakePublisher()))
    connection = Connection.instances[-1]
    sent = json.loads(connection.requests[0][1]['baseInstructions'])
    assert sent['current']['narrator'] == packet['current']['narrator']
    assert sent['current']['sequence'] == packet['current']['sequence']
    assert sent['dialogue'] == packet['tail']
    assert 'fence' not in sent and 'identity' not in sent
    assert sent['brief']['covered_through_sequence'] == 0
    assert result['reply'] == Connection.reply


def test_repair_identifies_a_copied_stored_name_instead_of_repeating_a_generic_failure(tmp_path):
    import asyncio
    from test_lifetime_memory_engine import fixture, encode, FakeConnection, FakePublisher, BUDGET
    from apps.api.lifetime_memory_engine import run_governed_collector
    governed, ctx = fixture()
    ctx.update(reply_contract='reply-v2', two_lane_memory=True)
    packet = json.loads(governed.packet)
    packet.update(instructions=reply_instructions(), interview_context={
        key: value for key, value in ctx.items() if key not in {'source', 'sources'}})
    class Connection(FakeConnection):
        prompts = []
        async def turn(self, thread_id, prompt, **options):
            self.prompts.append(prompt)
            raw = proposal()
            if len(self.prompts) == 1:
                raw['work']['name'] = 'Stored name absent from source'
            else:
                assert 'CONTRACT_30' in prompt
            return json.dumps(raw)
    result = asyncio.run(run_governed_collector(command=['fake'], home_root=tmp_path,
        base_url='http://provider.invalid/v1', api_key='synthetic', model=BUDGET.model,
        governed=encode(packet), interview_context=ctx, connection_factory=Connection, publisher=FakePublisher()))
    assert len(Connection.prompts) == 2
    assert json.loads(result['reply'])['work']['name'] is None
