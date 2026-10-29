"""Three internal strategies are suggestions; existing user policy owns authority."""
from copy import deepcopy
import json
import pytest


def context(strategy='shape',text="Let's talk about my garden."):
    return {'source':{'id':'00000000-0000-4000-8000-000000000001','version':1,'status':'active','text':text},
        'strategy_selector':True,'interview_language':'en-AU','opening_turn':False,'has_accepted_narration':True,
        'strategy_context':{'mode':'active','plan':{'plan_revision':3,'strategy':strategy,'based_on_sequence':10,
            'candidates':[{'id':'candidate-1','question':'Was that before the move?','topic':'move','quote':'before'}]}},
        'events':[],'photos':[],'photo_context':[]}


def wire(question='What do you enjoy growing?',**changes):
    return {'acknowledgement':'We can follow the garden.','question':question,'selected_candidate_id':None,
        'selection_reason':'user_redirect','used_strategy':'explore','work':{'mode':'extract','name':None},
        'associations':[],'response_photo_ids':[],'stopped':False,'continuity_updates':[],
        'question_evidence':None,**changes}


def test_reply_keeps_strategy_in_context_instead_of_prompt_variants():
    from apps.api.conversation_reply import reply_instructions
    from apps.api.prompt_catalog import PROMPT_PATHS
    prompt = reply_instructions()
    assert 'Active internal strategy:' not in prompt
    assert "narrator's latest wishes" in prompt
    assert [name for name in PROMPT_PATHS if name.startswith(
        'memoir/agents/mira/strategy-')] == [
            'memoir/agents/mira/strategy-proposal']


def test_compact_selector_has_no_fresh_future_pool():
    from apps.api.lifetime_memory_continuity import governed_collector_schema
    schema=governed_collector_schema(context())
    assert 'plan' not in schema['properties'] and 'candidates' not in schema['properties']
    assert 'question' in schema['required'] and 'selected_candidate_id' in schema['required']


def test_selector_schema_only_admits_current_candidate_ids():
    from jsonschema import validate, ValidationError
    from apps.api.lifetime_memory_continuity import governed_collector_schema
    schema = governed_collector_schema({**context(text='Please go on.'), 'two_lane_memory': True})
    validate(wire(question='Was that before the move?', selected_candidate_id='candidate-1',
        selection_reason='prepared_candidate', resolved_questions=[], deferred_questions=[]), schema)
    with pytest.raises(ValidationError):
        validate(wire(selected_candidate_id='stale-candidate', selection_reason='adapted_candidate',
            resolved_questions=[], deferred_questions=[]), schema)






def test_local_redirect_does_not_mutate_the_stored_strategy():
    from apps.api.lifetime_memory_continuity import validate_governed_collector_result
    c=context();before=deepcopy(c['strategy_context'])
    result=validate_governed_collector_result(wire(),c)
    assert c['strategy_context']==before
    assert result['strategy_outcome']['plan_revision_seen']==3
    assert result['strategy_outcome']['used_strategy']=='explore'
    assert result['strategy_outcome']['selection_reason']=='user_redirect'
    assert len(result['plan']['candidates'])==1
    assert result['plan'].get('phase_update') is None


@pytest.mark.parametrize('text',['Not today.','I want to stop here.','今天不聊了。'])
def test_pause_never_delivers_a_prepared_candidate(text):
    from apps.api.lifetime_memory_continuity import validate_governed_collector_result
    c=context(text=text)
    with pytest.raises(ValueError):validate_governed_collector_result(wire(selected_candidate_id='candidate-1',selection_reason='prepared_candidate'),c)
    result=validate_governed_collector_result(wire(question=None,selection_reason='pause',stopped=True),c)
    assert not result['plan']['candidates']


def test_direct_answer_may_have_no_question_without_pausing_or_changing_strategy():
    from apps.api.lifetime_memory_continuity import validate_governed_collector_result
    result=validate_governed_collector_result(wire(question=None,selection_reason='direct_answer',stopped=False),context(text='What happens to my memories?'))
    assert result['stopped'] is False and result['strategy_outcome']['question_delivered'] is None




def test_unknown_or_reused_candidates_cannot_be_selected():
    from apps.api.lifetime_memory_continuity import validate_governed_collector_result
    with pytest.raises(ValueError):validate_governed_collector_result(wire(selected_candidate_id='cross-project',selection_reason='prepared_candidate'),context(text='Please go on.'))


@pytest.mark.parametrize('padding',[' \n\t','\u00a0\u3000'])
def test_prepared_candidate_allows_edge_trimming_but_not_changed_words(padding):
    from apps.api.lifetime_memory_continuity import validate_governed_collector_result
    value=context(text='Please go on.')
    candidate=value['strategy_context']['plan']['candidates'][0]
    original=candidate['question']
    candidate['question']=padding+original+padding
    output=wire(question=original,selected_candidate_id=candidate['id'],selection_reason='prepared_candidate')
    assert validate_governed_collector_result(output,value)['reply'].endswith(original)
    output['question']='Was that after the move?'
    with pytest.raises(ValueError,match='Prepared candidate text changed'):
        validate_governed_collector_result(output,value)




def test_strategy_flag_defaults_off(monkeypatch):
    from apps.api.interview_strategy import strategy_enabled
    monkeypatch.delenv('MEMOIR_INTERVIEW_STRATEGY',raising=False)
    assert strategy_enabled() is False
