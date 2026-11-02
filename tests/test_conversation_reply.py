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
    return dict(acknowledgement='We can follow that memory.', recall_limit_quote=None, question='What do you remember about the move?',
        reason='latest_story', hint=None, quote=None, strategy='explore', workspace_focus=None,
        deferred_hints=[], historical_clue_id=None, resolved_questions=[], associations=[], response_photo_ids=[])


def test_next_question_selects_one_grounded_city_from_a_two_city_reply():
    text='我叫慧博，现在生活在悉尼，但是我于1983年4月出生在河北省承德市附属医院'
    ctx=reply_context(text)
    raw=dict(proposal(),acknowledgement='慧博，很高兴认识你。你现在生活在悉尼，人生的起点则是1983年4月的承德。',
        question='说起小时候，你最先想起的是怎样的一个画面？',
        workspace_focus=dict(place='承德',quote='我于1983年4月出生在河北省承德市附属医院',source_id=None))
    validate(raw,governed_collector_schema(ctx))
    focus=validate_governed_collector_result(raw,ctx)['plan']['workspace_focus']
    assert focus['place']=='承德'
    evidence=focus['evidence']
    assert evidence['source_id']==ctx['source']['id']
    assert text[evidence['char_start']:evidence['char_end']]==raw['workspace_focus']['quote']


@pytest.mark.parametrize('focus', [dict(place='北京',quote='我在承德出生'),
    dict(place='附属医院',quote='我在附属医院出生'),dict(place='承德',quote='不存在的原话')])
def test_question_focus_cannot_invent_geography_or_use_an_institution(focus):
    with pytest.raises(ValueError):
        validate_governed_collector_result(dict(proposal(),workspace_focus=focus),reply_context('我在承德出生。'))


def test_question_focus_can_continue_a_supplied_earlier_narrator_place():
    ctx=reply_context('I remember the trees outside.')
    prior=dict(id='prior-source',version=1,role='user',kind='narrator_chat',complete=True,text='I grew up in Montreal.')
    ctx['recent_dialogue']=[dict(response=prior)]
    raw=dict(proposal(),workspace_focus=dict(place='Montreal',quote=prior['text'],source_id=prior['id']))
    focus=validate_governed_collector_result(raw,ctx)['plan']['workspace_focus']
    assert focus['evidence']['source_id']==prior['id']
    prior['complete']=False
    with pytest.raises(ValueError):
        validate_governed_collector_result(raw,ctx)


def test_a_pause_cannot_publish_a_question_city():
    with pytest.raises(ValueError):
        validate_governed_collector_result(dict(proposal(),question=None,reason='pause',
            workspace_focus=dict(place='Montreal',quote='I grew up in Montreal.')),reply_context('I grew up in Montreal.'))


def test_small_wire_keeps_compatibility_and_rejects_host_metadata():
    ctx = reply_context()
    raw = proposal()
    schema = governed_collector_schema(ctx)
    validate(raw, schema)
    result = validate_governed_collector_result(raw, ctx)
    assert result['plan']['work'] == {'mode': 'extract', 'name': None}
    assert 'work' not in schema['properties'] and 'TurnWorkPlan' not in schema.get('$defs', {})
    assert result['plan']['candidates'][0]['question'] == raw['question']
    assert raw['question'] in result['reply']
    assert result['continuity_updates'] == result['place_journeys'] == []
    assert not {'source_id', 'continuity_updates', 'used_strategy'} & schema['properties'].keys()
    for key in ('source_id', 'source_version', 'continuity_updates', 'char_start'):
        with pytest.raises(ValueError):
            validate_governed_collector_result({**raw, key: []}, ctx)


@pytest.mark.parametrize('strategy',['comfort','explore','shape'])
def test_reply_selects_its_own_interviewing_strategy(strategy):
    ctx = reply_context()
    ctx.update(strategy_selector=True, active_strategy='comfort',
        strategy_context={'plan':{'strategy':'comfort'}})
    raw = dict(proposal(),strategy=strategy)
    schema = governed_collector_schema(ctx)
    assert 'strategy' in schema['required']
    assert next(iter(schema['properties']))=='acknowledgement'
    assert schema['properties']['strategy']['enum']==['comfort','explore','shape']
    validate(raw,schema)
    result = validate_governed_collector_result(raw,ctx)
    assert result['strategy_outcome']['used_strategy']==strategy


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


@pytest.mark.parametrize('language,current,acknowledgement', [
    ('en-AU', 'One correction: the room was in Newcastle, not Sydney. Please use Newcastle for the room.',
     'Understood—the room was in Newcastle, not Sydney. We’ll leave it there for today.'),
    ('zh-CN', '更正一下：那个房间在纽卡斯尔，不在悉尼。关于那个房间，请用纽卡斯尔。',
     '已更正：那个房间在纽卡斯尔。今天先聊到这里。'),
])
@pytest.mark.parametrize('with_quote', [False, True])
def test_correction_without_a_followup_keeps_extract_work_and_no_question_outcome(
        language, current, acknowledgement, with_quote):
    ctx = {**reply_context(current), 'interview_language': language, 'strategy_selector': True}
    raw = {**proposal(), 'acknowledgement': acknowledgement, 'question': None,
           'reason': 'current_correction', 'quote': current if with_quote else None}
    before = deepcopy(raw)
    result = validate_governed_collector_result(raw, ctx)
    assert result['reply'] == acknowledgement and result['stopped']
    assert result['plan']['candidates'] == [] and result['plan']['chosen_id'] is None
    assert result['plan']['work'] == {'mode': 'extract', 'name': None}
    assert result['strategy_outcome']['selection_reason'] == 'current_correction'
    assert result['strategy_outcome']['question_delivered'] is None
    assert result['strategy_outcome']['selected_candidate_id'] is None
    assert raw == before
    with pytest.raises(ValueError):
        validate_governed_collector_result({**raw, 'quote': 'Invented narrator wording'}, ctx)


@pytest.mark.parametrize('mode', ['extract', 'reply_only'])
def test_older_worker_handoff_cannot_select_background_work_or_update_profile(mode):
    raw = {**proposal(), 'work': {'mode': mode, 'name': 'Avery'}}
    result = validate_governed_collector_result(raw, reply_context('Please call me Avery. I grew up in Perth.'))
    assert result['immediate_name'] is None
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


def test_engine_uses_native_history_with_the_current_narrator_last(tmp_path, monkeypatch):
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
    result = asyncio.run(run_governed_collector(command=['fake'], home_root=tmp_path,
        base_url='http://provider.invalid/v1', api_key='synthetic', model=BUDGET.model,
        governed=governed, interview_context=ctx, publisher=FakePublisher()))
    assert captured[0]['input'][-1]['content'] == packet['current']['narrator']['original']
    context = json.loads(captured[0]['input'][1]['content'])['memoir_context']['updates']
    assert 'fence' not in context and 'identity' not in context
    assert context['brief']['current']['covered_through_sequence'] == 0
    assert json.loads(result['reply']) == proposal()
    assert any(tmp_path.iterdir())


def test_retired_work_hint_does_not_repair_the_reply_or_publish_a_name(tmp_path, monkeypatch):
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
    captured = install_reply_provider(monkeypatch, [invalid])
    result = asyncio.run(run_governed_collector(command=['fake'], home_root=tmp_path,
        base_url='http://provider.invalid/v1', api_key='synthetic', model=BUDGET.model,
        governed=encode(packet), interview_context=ctx, publisher=FakePublisher()))
    assert len(captured) == 1
    assert 'work' not in captured[0]['text']['format']['schema']['properties']
    assert json.loads(result['reply']) == invalid


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
        assert 'CONTRACT_31' in body['input'][-2]['content']
        assert 'set quote=null' in body['input'][-2]['content']
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
def test_question_reason_repair_keeps_current_narration_before_optional_news_delivery(tmp_path, monkeypatch, language, current):
    import asyncio
    from apps.api.lifetime_memory_engine import run_governed_collector
    from test_conversation_reply_transport import install_reply_provider
    from test_historical_news import ready_context
    from test_lifetime_memory_engine import fixture, encode, FakePublisher, BUDGET

    governed, ctx = fixture()
    ctx.update(deepcopy(ready_context()), reply_contract='reply-v2', two_lane_memory=True, interview_language=language)
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
        feedback = body['input'][-2]['content']
        assert 'CONTRACT_16' in feedback and 'No-question outcome requires an explicit reason' in feedback
        delivery = json.loads(body['input'][1]['content'])['memoir_context']['updates']['deliveries']['memoir-historical-news-research']
        clue = delivery['clues'][0]
        assert clue['id'] == ctx['historical_news']['clues'][0]['id']
        assert body['input'][-1]['content'] == current
        return {**invalid, 'reason': 'latest_story', 'historical_clue_id': clue['id'],
            'question': 'Does that public fair connect with any memory of your neighbourhood?' if language=='en-AU'
                else '这场公开记载的集市，会让您想起当时街坊间的什么吗？'}

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
def test_ready_news_preserves_miras_explicit_stop(
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
    raw = {**proposal(), 'acknowledgement': stopped, 'question': None, 'reason': 'pause',
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
