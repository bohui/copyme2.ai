"""Real judge assemblers, answer-key separation, and deterministic grade comparisons."""
from copy import deepcopy
from types import SimpleNamespace as NS

import pytest

from scripts import memoir_judge_calibration as suite
from scripts import run_memoir_judge_calibration as runner


def test_shared_cases_cover_all_actual_judge_sources_in_both_splits():
    from scripts.prompt_registry import prompt_registry
    rows=suite.cases()
    assert len(rows)==80
    assert sum(len(row['input']['judge_ids']) for row in rows)==140
    expected={n for n in prompt_registry() if n.startswith('memoir/evaluators/')}
    assert {p for j in suite.judges().values() for p in j['prompts']}==expected
    assert {r['input']['locale'] for r in rows}=={'en-AU','zh-CN'}
    assert all(r['expected_output'] for r in rows)


def test_answer_key_grades_and_rationales_never_enter_judge_requests():
    for row in suite.cases():
        changed=deepcopy(row)
        changed['expected_output']={'do_not_send_answer_key':{'score':.1234,'rationale':'PRIVATE ANSWER KEY'}}
        for name in row['input']['judge_ids']:
            actual=suite.request(name,changed['input'])
            import json
            assert 'PRIVATE ANSWER KEY' not in json.dumps(actual)
            assert actual['manifest']['artifacts']
            if actual['schema']:
                assert '{{input}}' not in actual['instructions']


@pytest.mark.parametrize('actual,expected,correct',[
    ({'score':0},{'score':0},True),({'score':1},{'score':0},False),
    ({'score':None},{'score':None},True),({'score':1},{'score':None},False),
    ({'score':True},{'score':1},False),({'score':float('nan')},{'score':1},False),
    ({'status':'pass','critical':False},{'status':'fail','critical':True},False),
    ({'status':'unavailable','scores':{'recovery':1}},{'status':'unavailable'},False),
    ({'scores':{'recovery':1}},{'omit_scores':['recovery']},False),
])
def test_fixed_answer_keys_reject_false_passes_and_invented_observations(actual,expected,correct):
    assert suite.grade(actual,expected)['agreement'] is correct


def test_transport_or_protocol_failures_stay_in_the_denominator():
    case=suite.cases()[0]
    results=[dict(input=case['input'],expected_output=case['expected_output'],output=dict(judgments={
        name:dict(available=False) for name in case['input']['judge_ids']}))]
    assert all(v['planned']==1 and v['available']==0 and v['agreement']==0
        for v in runner.summarize(results).values())


def test_five_case_consumer_accepts_observed_subset_and_omits_unobserved_categories():
    from scripts.run_memoir_five_case_semantic_judge import validate_judge_result
    status,result=validate_judge_result(dict(status='scored',scores={'evidence_use':1},
        comments={'evidence_use':'observed-1 contains the exact source quote.',
            'recovery':'No recovery was observed.'},evidence=['observed-1']))
    assert status=='scored'
    assert result['scores']=={'evidence_use':1}


@pytest.mark.parametrize('scores',[
    {'unknown_category':1},{'evidence_use':True},{'evidence_use':float('nan')},
    {'evidence_use':2},{}
])
def test_five_case_consumer_does_not_turn_partial_support_into_unvalidated_scores(scores):
    from scripts.run_memoir_five_case_semantic_judge import validate_judge_result
    status,_=validate_judge_result(dict(status='scored',scores=scores,
        comments={'evidence_use':'observed-1'},evidence=['observed-1']))
    assert status=='invalid'


def test_wrong_project_is_refused_before_any_dataset_mutation():
    client=NS(api=NS(projects=NS(get=lambda:NS(data=[NS(id='wrong-project')]))))
    with pytest.raises(ValueError,match='project'):runner.publish(client,suite.cases())


def test_five_case_unavailable_cannot_silently_keep_numeric_scores():
    from scripts.run_memoir_five_case_semantic_judge import validate_judge_result
    status,_=validate_judge_result(dict(status='unavailable',scores={'evidence_use':1},
        comments={'evidence_use':'No evidence exists.'}))
    assert status=='invalid'


def test_installed_experiment_api_serialized_io_is_compared_with_full_answer_key():
    import json
    expected=dict(input={'case_id':'c1'},expected_output={'correctness':{'score':1,'rationale':'source agrees'}},
        output={'judgments':{'correctness':dict(available=True,actual={'score':1},manifest={'artifacts':[]},response_id='r1')}})
    scores=[NS(id=e.name,name=e.name,value=e.value,metadata=e.metadata,
        subject=NS(kind='observation',trace_id='trace')) for e in runner.evaluations(**expected)]
    item=NS(experiment_dataset_id='dataset',trace_id='trace',input=json.dumps(expected['input']),
        output=json.dumps(expected['output']),expected_output=json.dumps(expected['expected_output']),scores=scores)
    client=NS(api=NS(experiments=NS(list_items=lambda **kwargs:NS(data=[item],meta=NS(cursor=None))),
        scores_v3=NS(get_many_v3=lambda **kwargs:NS(data=scores,meta=NS(cursor=None)))))
    from datetime import datetime, timezone
    assert runner.readback(client,'experiment','dataset',[expected],started_at=datetime.now(timezone.utc))['verified']
