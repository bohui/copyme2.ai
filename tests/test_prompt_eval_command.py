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


def test_only_the_actual_source_window_contract_can_supply_input_prompt_provenance():
    from scripts.memoir_skill_eval_suite import packet
    from scripts.memoir_skill_scenarios import build_cases
    case=next(c for c in build_cases() if c['skill']=='memoir-author-timeline')
    actual=packet(case)
    manifest=evaluation_manifest(actual['instructions'],actual['schema'],input_packet=actual['input'])
    assert 'memoir/skills/author-timeline/window' in {a['name'] for a in manifest['artifacts']}
    changed=deepcopy(actual['input']);changed['window_contract']+='unpublished change'
    manifest=evaluation_manifest(actual['instructions'],actual['schema'],input_packet=changed)
    assert 'memoir/skills/author-timeline/window' not in {a['name'] for a in manifest['artifacts']}


def test_all_prompt_command_refuses_partial_calibration_even_when_receipt_says_passed(tmp_path):
    row=cases()[0];judge=row['input']['judge_ids'][0]
    record=dict(status='passed',dataset_version='2026-11-04T00:00:00+00:00',readback={'verified':True},fixture_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
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


def test_a_later_wrong_grade_does_not_inherit_an_earlier_passing_attempt(tmp_path):
    row=cases()[0];judge=row['input']['judge_ids'][0]
    verdict=dict(available=True,actual={'score':1},manifest=request(judge,row['input'])['manifest'])
    receipt=dict(status='passed',dataset_version='2026-11-04T00:00:00+00:00',readback={'verified':True},fixture_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        results=[dict(input=row['input'],output={'judgments':{judge:verdict}})])
    first=tmp_path/'first.json';first.write_text(json.dumps(receipt))
    receipt.update(status='failed',dataset_version='2026-11-04T00:01:00+00:00');verdict['actual']={'score':0}
    second=tmp_path/'second.json';second.write_text(json.dumps(receipt))
    import os
    os.utime(first,(2_000_000_000,2_000_000_000))
    with pytest.raises(ValueError,match='0/140'):campaign.calibrated([first,second])


def test_completed_phase_does_not_make_an_incomplete_workflow_pass():
    row=next(r for r in campaign.prompt_rows() if r['input']['prompt']=='memoir/agents/mira/reply')
    manifest=evaluation_manifest(__import__('apps.api.conversation_reply',fromlist=['reply_instructions']).reply_instructions())
    run=dict(calls=[dict(case_id='workflow/phase',provider_response_id='completed-phase',prompt_manifest=manifest)],
        results=[dict(case_id='workflow',status='unavailable',evidence_mode='incomplete controlled workflow')])
    result=campaign.evidence([row],{},run)[0]
    assert result['current_pin_observed'] is True
    assert result['status']=='unavailable'
    assert {s.name for s in campaign.scores(output=result)}=={'memoir/agents/mira/reply/current_pin_observed'}


def test_rechecks_do_not_reuse_an_older_passing_phase_or_different_answer_key():
    row=next(r for r in campaign.prompt_rows() if r['input']['prompt']=='memoir/agents/mira/reply')
    manifest=evaluation_manifest(__import__('apps.api.conversation_reply',fromlist=['reply_instructions']).reply_instructions())
    case=dict(case_id='workflow',status='pass',evidence_mode='observed',input_sha256='fixed-input',gold_sha256='fixed-gold')
    first=dict(started_at='2026-11-04T00:00:00+00:00',results=[case],calls=[dict(case_id='workflow',provider_response_id='r1',prompt_manifest=manifest)])
    later=dict(started_at='2026-11-04T00:01:00+00:00',results=[{**case,'status':'unavailable'}],calls=[])
    runs=campaign.retained_campaigns(first,[later])
    assert campaign.evidence([row],{},runs)[0]['status']=='unavailable'
    later['results'][0]['gold_sha256']='different-gold'
    with pytest.raises(ValueError,match='input or gold'):campaign.retained_campaigns(first,[later])


def test_prompt_ledger_publication_uses_the_real_generic_dataset_publisher():
    from types import SimpleNamespace as NS
    from scripts.run_memoir_judge_calibration import PROJECT
    rows=[dict(input={'case_id':'memoir/agents/mira/reply','prompt':'memoir/agents/mira/reply'},expected_output={'current_pin_observed':True})]
    output=dict(case_id='memoir/agents/mira/reply',status='unavailable',current_pin_observed=False,evidence=[],human_reviewed=False)
    stored=[];hosted=[]
    def create_item(**value):
        assert value['metadata']['skill'] is None
        stored.append(NS(id=value['id'],input=value['input'],expected_output=value['expected_output'],status='ACTIVE'))
    def experiment(**arguments):
        for item in stored:
            actual=arguments['task'](item=item)
            hosted.append(NS(experiment_dataset_id='dataset',input=json.dumps(item.input),output=json.dumps(actual),
                expected_output=json.dumps(item.expected_output),scores=arguments['evaluators'][0](output=actual)))
        return NS(experiment_id='experiment',dataset_run_url='http://langfuse.test/experiment')
    client=NS(api=NS(projects=NS(get=lambda:NS(data=[NS(id=PROJECT)])),datasets=NS(list=lambda **kw:NS(data=[],meta=NS(total_pages=1))),
        experiments=NS(list_items=lambda **kw:NS(data=hosted,meta=NS(cursor=None)))),
        create_dataset=lambda **kw:None,create_dataset_item=create_item,
        get_dataset=lambda *args,**kw:NS(id='dataset',items=stored,run_experiment=experiment),flush=lambda:None)
    assert campaign.publish(client,rows,[output],'retained-ledger')['readback']['verified']


def test_retained_provider_availability_is_reclassified_without_changing_original_receipt():
    row=dict(case_id='c1',status='fail',input_sha256='input',gold_sha256='gold')
    primary=dict(run_id='original',started_at='2026-11-04T00:00:00+00:00',results=[row],
        calls=[dict(case_id='c1/proposal',status='failed',http_status=502,provider_response_id=None)])
    revised=campaign.retained_campaigns(primary,[])[0]
    assert revised['results'][0]['status']=='unavailable'
    assert revised['results'][0]['source_status']=='fail'
    assert primary['results'][0]['status']=='fail'
