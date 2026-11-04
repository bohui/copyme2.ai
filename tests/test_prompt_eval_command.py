"""Commands preserve scope and cannot turn calibration or bindings into coverage."""
import hashlib
import json
from copy import deepcopy

import pytest

from scripts import run_memoir_prompt_evaluation as campaign
from scripts import run_memoir_agent_evaluation as agents
from scripts.memoir_judge_calibration import SOURCE, cases, request
from scripts.run_memoir_skill_evaluation import evaluation_manifest


@pytest.mark.parametrize('arguments,skill,component',[
    (['--agent','mira'],'memoir-interviewer','lane-a'),
    (['--agent','atlas'],'memoir-background-agent','lane-b'),
    (['--skill','memoir-author-timeline'],'memoir-author-timeline','skills'),
])
def test_makefile_selectors_reach_only_the_requested_agent_or_skill(arguments,skill,component,capsys):
    assert agents.main(arguments)==0
    plan=json.loads(capsys.readouterr().out)
    assert plan['http_dispatches']==0
    rows={r['id']:r for r in agents.catalog()}
    assert plan['cases'] and all(rows[k]['skill']==skill and rows[k]['component']==component for k in plan['cases'])


def test_actual_runtime_assembler_is_used_for_static_request_provenance():
    from apps.api.conversation_reply import reply_instructions
    result=evaluation_manifest(reply_instructions())
    artifacts={a['name']:a for a in result['artifacts']}
    assert 'memoir/agents/mira/reply' in artifacts
    assert all(a['version'] and a['sha256'] for a in artifacts.values())
    assert not any(k.startswith('memoir/evaluators/') for k in artifacts)


def test_all_prompt_command_refuses_partial_calibration_even_when_receipt_says_passed(tmp_path):
    row=cases()[0];judge=row['input']['judge_ids'][0]
    record=dict(status='passed',readback={'verified':True},fixture_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        results=[dict(input=row['input'],output={'judgments':{judge:dict(available=True,
            actual={'score':1},manifest=request(judge,row['input'])['manifest'])}})])
    path=tmp_path/'receipt.json';path.write_text(json.dumps(record))
    with pytest.raises(ValueError,match='1/140'):campaign.calibrated([path])
    record['results'][0]['output']['judgments'][judge]['manifest']['artifacts'][0]['sha256']='outdated'
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError,match='0/140'):campaign.calibrated([path])


def test_per_prompt_coverage_requires_actual_current_pin_and_keeps_failures():
    row=next(r for r in campaign.prompt_rows() if r['input']['prompt']=='memoir/agents/mira/reply')
    manifest=evaluation_manifest(__import__('apps.api.conversation_reply',fromlist=['reply_instructions']).reply_instructions())
    observed=dict(case_id='observed',status='fail',evidence_mode='live_reply_proposal')
    call=dict(case_id='observed',provider_response_id='real-response-id',prompt_manifest=manifest)
    source=dict(calls=[call],results=[observed])
    result=campaign.evidence([row],{},source)[0]
    assert result['status']=='fail' and result['current_pin_observed']
    assert not result['canonical_delivery'] and not result['human_reviewed']
    stale=deepcopy(row);stale['input']['version']+=1
    assert campaign.evidence([stale],{},source)[0]['status']=='unavailable'
    call.pop('provider_response_id')
    assert campaign.evidence([row],{},source)[0]['status']=='unavailable'
