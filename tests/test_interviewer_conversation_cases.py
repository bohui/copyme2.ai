"""Real-prefix builders cannot leak later answers or mislabel gate fixtures."""
from copy import deepcopy
import pytest

from scripts import memoir_skill_eval_suite as suite
from scripts.interviewer_conversation_cases import conversation_cases


def minimal_template():
    return dict(skill='memoir-interviewer', task=dict(context={}), gold=dict(facts={}, required=[], forbidden=[]))


def original(n, text):
    return dict(id='s' + str(n), version=1, sequence=n, project_id='selected-project', status='active',
                text=text, language='en-AU', kind='narrator_chat')


def controls(sources, *, stopped=False, question=True, reason=None):
    return {source['id']: dict(source_version=source['version'], text_sha256=suite.digest(source['text']),
        facts=dict(stopped=stopped, question=question, selection_reason=reason)) for source in sources}


def test_unsaved_reply_cannot_remove_accepted_narration_from_the_next_prefix():
    sources = [original(1, 'My father repaired bicycles.'), original(2, 'I meant my mother.'),
               original(3, 'She worked in our shed.')]
    turns = [dict(source_id='s1', collector=dict(reply='Where did he work?'))]
    rows = conversation_cases(minimal_template(), sources, turns, control_expectations=controls(sources))
    second = rows[1]['task']['context']
    third = rows[2]['task']['context']
    assert [s['narrator'] for s in third['recent_dialogue']] == [s['text'] for s in sources[:2]]
    assert third['recent_dialogue'][1]['assistant_reply'] is None
    assert second['opening_turn'] is False and third['opening_turn'] is False
    first_missing = conversation_cases(minimal_template(), sources, [], control_expectations=controls(sources))
    assert first_missing[1]['task']['context']['opening_turn'] is False
    assert first_missing[1]['task']['context']['has_accepted_narration'] is True


@pytest.mark.parametrize('text', ['Not today. Stop here.', 'I meant my mother. Please stop.', '今天先到这里。'])
def test_observed_stop_gold_does_not_require_a_followup(text):
    sources = [original(1, text)]
    row = conversation_cases(minimal_template(), sources, [],
        control_expectations=controls(sources, stopped=True, question=False, reason='pause'))[0]
    assert row['gold']['facts'] == dict(stopped=True, question=False, selection_reason='pause')
    assert not any('unanswered question' in requirement for requirement in row['gold']['required'])


def test_reviewed_indirect_departure_accepts_the_valid_production_stop():
    from test_conversation_reply import proposal
    text = 'I meant my mother. I need to leave for my appointment.'
    sources = [original(1, text)]
    template = suite.plan(case=['memoir-interviewer/grounded-question/en-AU'])['items'][0]
    row = conversation_cases(template, sources, [], control_expectations=controls(
        sources, stopped=True, question=False, reason='pause'))[0]
    output = {**proposal(), 'question': None, 'reason': 'pause'}
    suite.validate(row, output)
    with pytest.raises(Exception):
        suite.validate(row, {**proposal(), 'reason': 'current_correction'})


def test_unreviewed_or_changed_source_cannot_silently_gain_question_gold():
    sources = [original(1, 'I meant my mother. I need to leave for my appointment.')]
    with pytest.raises(ValueError, match='reviewed_source_control_expectation_required'):
        conversation_cases(minimal_template(), sources, [], control_expectations={})
    reviewed = controls(sources, stopped=True, question=False, reason='pause')
    sources[0]['text'] = 'I meant my mother. Please continue.'
    with pytest.raises(ValueError, match='reviewed_source_control_expectation_required'):
        conversation_cases(minimal_template(), sources, [], control_expectations=reviewed)


def test_reviewed_direct_answer_does_not_inherit_story_followup_requirements():
    from test_conversation_reply import proposal
    sources = [original(1, 'What happens to my memories?')]
    template = suite.plan(case=['memoir-interviewer/grounded-question/en-AU'])['items'][0]
    row = conversation_cases(template, sources, [], control_expectations=controls(
        sources, question=False, reason='direct_answer'))[0]
    suite.validate(row, {**proposal(), 'question': None, 'reason': 'direct_answer'})
    assert not any('unanswered question' in requirement for requirement in row['gold']['required'])


def test_prefixes_are_exact_and_counterfactuals_are_separate():
    template = suite.plan(case=['memoir-interviewer/grounded-question/zh-CN'])['items'][0]
    sources = [dict(id='s'+str(n), version=1, sequence=n, project_id='selected-project',
        status='active', text=text, language='zh-CN', kind='narrator_chat')
        for n, text in enumerate(['小时候我和朋友玩。', '我们坐车去河边。'], 1)]
    turns = [dict(source_id=s['id'], collector=dict(reply='您还记得什么？')) for s in sources]
    before = deepcopy((sources, turns, template))
    rows = conversation_cases(template, sources, turns, control_expectations=controls(sources))
    originals = [row for row in rows if not row['origin']['synthetic']]
    assert originals[0]['task']['context']['recent_dialogue'] == []
    history = originals[1]['task']['context']['recent_dialogue']
    assert len(history) == 1 and history[0]['narrator'] == sources[0]['text']
    assert history[0]['assistant_is_testimony'] is False
    assert originals[1]['task']['source']['text'] == sources[1]['text']
    assert len({row['id'] for row in rows}) == len(rows)
    probes = {row['case']: row for row in rows if row['origin']['synthetic']}
    assert probes['ready-transition']['task']['context']['breadth_checkpoint']['suggested_stage'] == 'adolescence'
    assert probes['below-gate']['task']['context']['breadth_checkpoint'] is None
    assert probes['ready-pause']['gold']['facts']['question'] is False
    for row in rows:
        request = suite.packet(row)
        assert 'gold' not in request['input'] and 'required' not in request['input']
    assert (sources, turns, template) == before
