"""Saved-plan omissions cannot erase work/stop failures or admit their timings."""
import asyncio
from copy import deepcopy
import json
import shutil

import pytest

from scripts import issue53_profile_sequences as profile
from scripts.issue53_sequence_application import controlled_sequences


@pytest.fixture(scope='module')
def saved_plan_cases(tmp_path_factory):
    directory=tmp_path_factory.mktemp('issue53-saved-plan')
    planned=profile.plan(scenario=['issue53/name-clue/en-AU','issue53/emotional/en-AU'],max_skill_calls=12)
    rows,journal=asyncio.run(controlled_sequences(planned,directory))
    report=profile.compare(planned,rows,journal,{},directory=directory)
    assert len(rows)==12 and all(r['execution']=='completed' for r in rows)
    assert all(r['contracts']['status']=='pass' for r in report['rows'])
    return planned,rows,journal,directory


def changed_plan_report(cases,tmp_path,contract,mutation):
    planned,rows,journal,directory=cases
    copied=tmp_path/mutation;shutil.copytree(directory,copied)
    changed=deepcopy(journal)
    family='name-clue' if contract=='work' else 'emotional'
    row=next(r for r in planned['rows'] if r['scenario_id']==f'issue53/{family}/en-AU'
             and r['step_id']=='turn-3' and r['arm']=='candidate')
    capture=changed['rows'][row['row_id']]
    saved=capture['after']['replies'][-1]
    if contract=='work':
        saved['plan']['work']['mode']='reply_only'
    else:
        saved['plan']['candidates']=[dict(id='ignored-stop',question='Another question?',order=0,bridge='',
            context=dict(event_id=None,photo_id=None,life_stage=None,year=None))]
        saved['plan']['chosen_id']='ignored-stop'
    if mutation=='missing':saved.pop('plan')
    elif mutation=='null':saved['plan']=None
    elif mutation=='non_object':saved['plan']=[]
    elif mutation=='empty':saved['plan']={}
    elif mutation=='missing_work':saved['plan'].pop('work')
    elif mutation=='null_work':saved['plan']['work']=None
    elif mutation=='invalid_work':saved['plan']['work']['mode']='unknown'
    elif mutation=='missing_candidates':saved['plan'].pop('candidates')
    elif mutation=='invalid_candidates':saved['plan']['candidates']=None
    elif mutation=='missing_chosen_id':saved['plan'].pop('chosen_id')
    elif mutation=='invalid_chosen_id':saved['plan']['chosen_id']=[]
    body={k:v for k,v in capture.items() if k not in {'sequence_receipt_path','sequence_receipt_sha256'}}
    (copied/capture['sequence_receipt_path']).write_text(json.dumps(body))
    capture['sequence_receipt_sha256']=profile.digest(body)
    return profile.compare(planned,rows,changed,{},directory=copied),row


@pytest.mark.parametrize('contract',['work','stop'])
def test_known_saved_plan_violation_blocks_contract_and_latency(saved_plan_cases,tmp_path,contract):
    report,row=changed_plan_report(saved_plan_cases,tmp_path,contract,'known_violation')
    actual=next(r for r in report['rows'] if r['row_id']==row['row_id'])
    assert actual['contracts']['status']=='fail'
    assert actual['contracts']['reason']==('work_decision_mismatch' if contract=='work' else 'ignored_stop')
    assert report['status']=='failed' and not report['release_accepted']
    assert report['latency']['overall']['matched_complete_pairs']==5


@pytest.mark.parametrize('contract',['work','stop'])
@pytest.mark.parametrize('mutation',['missing','null','non_object','empty','missing_work','null_work',
    'invalid_work','missing_candidates','invalid_candidates','missing_chosen_id','invalid_chosen_id'])
def test_absent_or_malformed_saved_plan_cannot_erase_known_failure(saved_plan_cases,tmp_path,contract,mutation):
    report,row=changed_plan_report(saved_plan_cases,tmp_path,contract,mutation)
    actual=next(r for r in report['rows'] if r['row_id']==row['row_id'])
    assert actual['contracts']['status']=='fail'
    assert actual['contracts']['reason'] in {'saved_plan_evidence_required','saved_plan_evidence_invalid'}
    assert report['status']=='failed' and not report['release_accepted']
    assert report['latency']['overall']['matched_complete_pairs']==5
    assert row['pair_id'] not in {p['pair_id'] for p in report['latency']['overall']['paired_deltas']}
