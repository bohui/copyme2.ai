"""Real SQL first/later/cold-resume/replay; synthetic worker, never AI quality."""
import asyncio
from copy import deepcopy
import json

import pytest

from scripts import issue53_profile_sequences as profile
from scripts.issue53_sequence_application import controlled_sequences, StreamObservation


def test_public_milestones_ignore_headers_private_json_and_generic_filler():
    ticks=iter(range(10))
    observation=StreamObservation('blue labels',clock=lambda:next(ticks))
    observation.observe({'type':'started'})
    observation.observe({'type':'progress','data':{'id':'collector'}})
    observation.observe({'type':'text_delta','text':'Thank you. '})
    assert observation.timings['first_meaningful_text_s'] is None
    observation.observe({'type':'text_delta','text':'You remember blue labels.'})
    observation.observe({'type':'question_validated','data':{'has_question':True}})
    observation.observe({'type':'reply_complete','data':{'cached':False,'has_question':True}})
    observation.observe({'type':'conversation_saved','data':{'conversation_saved':True}})
    assert list(observation.timings.values()) == [4,5,6,7]


def test_saved_replay_completion_uses_terminal_receipt_without_generation_milestones():
    ticks=iter(range(4))
    observation=StreamObservation('blue labels',clock=lambda:next(ticks))
    observation.observe({'type':'result','data':{'cached':True,'conversation_saved':True,'reply':None}})
    assert all(v is None for v in observation.timings.values())
    observation.observe({'type':'result','data':{'cached':True,'conversation_saved':True,'reply':'The labels were blue.'}})
    assert observation.timings['reply_complete_s']==2
    assert all(observation.timings[k] is None for k in profile.MILESTONES if k!='reply_complete_s')


def test_duplicate_public_milestones_do_not_replace_first_receipt_time():
    ticks=iter(range(6))
    observation=StreamObservation('blue labels',clock=lambda:next(ticks))
    for event in [{'type':'question_validated','data':{'has_question':True}},
                  {'type':'reply_complete','data':{'cached':False,'has_question':True}}]*2:
        observation.observe(event)
    assert observation.timings['validated_question_s']==1
    assert observation.timings['reply_complete_s']==2


@pytest.fixture(scope='module')
def native_pair(tmp_path_factory):
    directory=tmp_path_factory.mktemp('issue53-sequences')
    planned=profile.plan(scenario=['issue53/resume-replay-rollback/'+l for l in ('en-AU','zh-CN')], max_skill_calls=20)
    rows,journal=asyncio.run(controlled_sequences(planned,directory))
    return planned,rows,journal,directory


def test_real_connected_bilingual_first_later_resume_and_saved_replay(native_pair):
    planned,rows,journal,directory=native_pair
    assert json.loads((directory/'plan.json').read_text()) == planned
    report=profile.compare(planned,rows,journal,{},directory=directory)
    assert len(rows)==20
    assert sum(r['execution']=='completed' for r in rows)==16,rows
    complete=[r for r in report['rows'] if r['execution']=='completed']
    assert all(r['contracts']['status']=='pass' for r in complete),complete
    assert all(r['reason']=='future_rollback_configuration_adapter_unavailable' for r in rows if r['execution']!='completed')
    assert all(r['evidence_mode']=='mock_only' for r in rows)
    assert not report['release_accepted'] and report['status']=='incomplete'
    assert report['latency']['by_phase']['resumed']['matched_complete_pairs']==2
    for row in planned['rows']:
        if row['phase']=='resumed':
            capture=journal['rows'][row['row_id']]
            assert capture['resume']['new_runtime']
            assert len(capture['before']['sources'])==len(capture['before']['replies'])==2
        if row['phase']=='replay':
            assert journal['rows'][row['row_id']]['dispatches']==[]
    assert journal['budget']['dispatched']==12


def test_replayed_rebound_receipts_and_lost_testimony_are_rejected(native_pair,tmp_path):
    planned,rows,journal,directory=native_pair
    fresh=profile.plan(scenario=[s['id'] for s in planned['scenarios']],max_skill_calls=20)
    with pytest.raises(ValueError,match='current_run_journal_required'):
        profile.compare(fresh,rows,journal,{},directory=directory)
    changed=deepcopy(journal)
    key=next(iter(changed['rows']))
    changed['rows'][key]['context']['invocation_id']='replayed'
    report=profile.compare(planned,rows,changed,{},directory=directory)
    assert report['rows'][0]['contracts']['status']=='fail'
    changed=deepcopy(journal)
    resumed=next(r for r in planned['rows'] if r['phase']=='resumed')
    changed['rows'][resumed['row_id']]['after']['sources'].pop(0)
    report=profile.compare(planned,rows,changed,{},directory=directory)
    assert next(r for r in report['rows'] if r['row_id']==resumed['row_id'])['contracts']['status']=='fail'


def judgment(*, status='pass', citations=None, critical=None):
    return dict(status=status,citations=citations or ['output','task'],critical_violations=critical or [],
                rationale='Grounded in the supplied source, current public output and saved exchanges.',
                response_id='independent-fixture-response',model='independent-judge-fixture')


def test_blind_existing_judgments_cannot_hide_a_locale_resume_regression(native_pair):
    planned,rows,journal,directory=native_pair
    packets=profile.blind_packets(planned,rows,journal)
    reviews={}
    for pair_id,pair in packets.items():
        baseline=next(r for r in planned['rows'] if r['pair_id']==pair_id and r['arm']=='baseline')
        comparison=judgment(citations=['A.output','B.output','task'])
        comparison['reviewer_kind']='human'
        comparison['preferred_side']=profile.blind_side(planned,baseline) if baseline['locale']=='zh-CN' and baseline['phase']=='resumed' else 'tie'
        reviews[pair_id]=dict(packet_sha256=pair['packet_sha256'],A=judgment(),B=judgment(),comparison=comparison)
        for side in ('A','B'):
            assert 'arm' not in pair[side] and 'timings' not in pair[side]
            assert 'sequence_requirements' in pair[side]['evidence']['task']
            assert 'witnesses' in pair[side]['evidence']
    report=profile.compare(planned,rows,journal,reviews,directory=directory)
    assert report['status']=='failed' and not report['release_accepted']
    regressions=[r for r in report['rows'] if r.get('semantic_regression')]
    assert len(regressions)==1 and regressions[0]['locale']=='zh-CN' and regressions[0]['phase']=='resumed'
    assert report['latency']['by_locale_phase']['zh-CN']['resumed']['matched_complete_pairs']==1


def test_critical_violation_and_missing_citations_remain_separate_from_latency(native_pair):
    planned,rows,journal,directory=native_pair
    packets=profile.blind_packets(planned,rows,journal)
    pair_id,pair=next(iter(packets.items()))
    comparison=judgment(citations=['A.output','B.output','task']);comparison.update(preferred_side='tie',reviewer_kind='human')
    review=dict(packet_sha256=pair['packet_sha256'],A=judgment(critical=['unsupported_fact']),B=judgment(),comparison=comparison)
    report=profile.compare(planned,rows,journal,{pair_id:review},directory=directory)
    assert report['status']=='failed'
    assert any(r['semantic']['status']=='fail' for r in report['rows'])
    review['A']['critical_violations']=[];review['comparison']['citations']=['A.output']
    report=profile.compare(planned,rows,journal,{pair_id:review},directory=directory)
    assert all(r['comparison']['status']=='unavailable' for r in report['rows'] if r['pair_id']==pair_id)
    assert all(r['semantic']['status']=='pass' for r in report['rows'] if r['pair_id']==pair_id)


@pytest.mark.parametrize('mode',['missing','stale_dispatch','clock','source','resume','replay'])
def test_current_run_sequence_proofs_fail_closed(native_pair,tmp_path,mode):
    planned,rows,journal,directory=native_pair
    import shutil
    local=tmp_path/'evidence';shutil.copytree(directory,local)
    changed=deepcopy(journal)
    row=next(r for r in planned['rows'] if r['phase']==('replay' if mode=='replay' else 'resumed'))
    capture=changed['rows'][row['row_id']]
    if mode=='missing':
        (local/capture['sequence_receipt_path']).unlink()
    else:
        if mode=='stale_dispatch': capture['dispatches']=[]
        elif mode=='clock': capture['stream_observation']['timings']['durable_save_s']=-1
        elif mode=='source': capture['after']['sources'][0]['text']='Lost original testimony'
        elif mode=='resume': capture['resume']['new_runtime']=False
        elif mode=='replay': capture['dispatches']=[{'status':'completed'}]
        # Even rewritten/rehashed sequence files must satisfy the existing native
        # receipt, current dispatch ledger and independently expected sequence.
        body={k:v for k,v in capture.items() if k not in {'sequence_receipt_path','sequence_receipt_sha256'}}
        (local/capture['sequence_receipt_path']).write_text(json.dumps(body))
        capture['sequence_receipt_sha256']=profile.digest(body)
    report=profile.compare(planned,rows,changed,{},directory=local)
    assert next(r for r in report['rows'] if r['row_id']==row['row_id'])['contracts']['status']=='fail'
    assert not report['release_accepted']


def test_critical_model_judgment_survives_malformed_human_annotation(native_pair):
    planned,rows,journal,directory=native_pair
    pair_id,pair=next(iter(profile.blind_packets(planned,rows,journal).items()))
    review=dict(packet_sha256=pair['packet_sha256'],A=judgment(critical=['ignored_stop']),B=judgment(),comparison={})
    report=profile.compare(planned,rows,journal,{pair_id:review},directory=directory)
    assert report['status']=='failed'
    assert any(r['semantic']['status']=='fail' for r in report['rows'])


def test_rewritten_native_and_sequence_capsules_cannot_supply_dispatch_authority(native_pair,tmp_path):
    planned,rows,journal,directory=native_pair
    import shutil
    local=tmp_path/'rebound';shutil.copytree(directory,local)
    changed=deepcopy(journal)
    row=next(r for r in planned['rows'] if r['phase']=='resumed')
    capture=changed['rows'][row['row_id']]
    capture['dispatches']=[]
    native=capture['witness']['readback'];native['dispatches']=[]
    (local/capture['witness']['receipt_path']).write_text(json.dumps(native))
    capture['witness']['receipt_sha256']=profile.digest(native)
    body={k:v for k,v in capture.items() if k not in {'sequence_receipt_path','sequence_receipt_sha256'}}
    (local/capture['sequence_receipt_path']).write_text(json.dumps(body))
    capture['sequence_receipt_sha256']=profile.digest(body)
    report=profile.compare(planned,rows,changed,{},directory=local)
    result=next(r for r in report['rows'] if r['row_id']==row['row_id'])
    assert result['contracts']==dict(status='fail',reason='independent_runner_dispatch_ledger_mismatch')


def test_rebinding_old_receipts_to_fresh_plan_cannot_rebind_the_runner_ledger(native_pair):
    planned,rows,journal,directory=native_pair
    fresh=profile.plan(scenario=[s['id'] for s in planned['scenarios']],max_skill_calls=20)
    changed=deepcopy(journal)
    changed.update(run_id=fresh['run_id'],plan_sha256=fresh['plan_sha256'])
    for row in fresh['rows']:
        if row['row_id'] in changed['rows']:
            changed['rows'][row['row_id']]['context']=profile.context(fresh,row)
            changed['rows'][row['row_id']]['plan_sha256']=fresh['plan_sha256']
    with pytest.raises(ValueError,match='unplanned_or_stale_runner_dispatch'):
        profile.compare(fresh,rows,changed,{},directory=directory)


def test_mismatched_seed_and_extra_dispatch_cannot_be_called_a_matched_pair(native_pair):
    planned,rows,journal,directory=native_pair
    changed=deepcopy(journal)
    seed=next(iter(changed['seeds'].values()));seed['candidate_sha256']='foreign'
    report=profile.compare(planned,rows,changed,{},directory=directory)
    assert any(r['contracts'].get('reason')=='matched_seed_or_prestate_mismatch' for r in report['rows'])
    changed=deepcopy(journal)
    extra=deepcopy(changed['budget']['calls'][0]);extra.update(dispatch_id='extra',row_id='unplanned')
    changed['budget']['calls'].append(extra);changed['budget']['dispatched']+=1
    with pytest.raises(ValueError,match='duplicate_or_missing_dispatch_identity|unplanned_or_stale_runner_dispatch'):
        profile.compare(planned,rows,changed,{},directory=directory)


def test_imported_provider_metrics_cannot_be_promoted_to_observed_metrics(native_pair):
    planned,rows,journal,directory=native_pair
    changed=deepcopy(rows)
    changed[0]['provider_metrics']=dict(usage={'input_tokens':0},effective_effort='low',provider_retries=0)
    report=profile.compare(planned,changed,journal,{},directory=directory)
    row=report['rows'][0]
    assert row['contracts']['status']=='pass'
    assert all(v is None for v in row['provider_metrics'].values())
    assert row['imported_provider_metrics']['source']=='unverified_import'
    assert row['imported_provider_metrics']['values']['effective_effort']=='low'
    assert row['runner_observations']['source']=='verified_controlled_runner_ledger'
    assert row['runner_observations']['calls'][0]['live_model_dispatch'] is False


@pytest.mark.parametrize('mate_status',[None,'failed','timed_out','unavailable'])
def test_incomplete_pair_preserves_bound_available_candidate_critical_judgment(native_pair,mate_status):
    planned,rows,journal,directory=native_pair
    candidate=next(r for r in planned['rows'] if r['arm']=='candidate' and r['phase']=='first')
    baseline_id=next(r['row_id'] for r in planned['rows'] if r['pair_id']==candidate['pair_id'] and r['arm']=='baseline')
    incomplete=[r for r in rows if r['row_id']!=baseline_id]
    if mate_status is not None:
        incomplete.append(dict(row_id=baseline_id,execution=mate_status,reason='controlled missing mate'))
    pair=profile.blind_packets(planned,incomplete,journal)[candidate['pair_id']]
    side=profile.blind_side(planned,candidate)
    review=dict(packet_sha256=pair['packet_sha256'])
    review[side]=judgment(critical=['lost_testimony'])
    report=profile.compare(planned,incomplete,journal,{candidate['pair_id']:review},directory=directory)
    result=next(r for r in report['rows'] if r['row_id']==candidate['row_id'])
    assert result['semantic']['status']=='fail'
    assert result['semantic']['critical_violations']==['lost_testimony']
    assert report['status']=='failed' and not report['release_accepted']
    assert next(r for r in report['rows'] if r['row_id']==baseline_id)['execution']==(mate_status or 'unavailable')


def test_unavailable_human_preference_does_not_invent_a_regression(native_pair):
    planned,rows,journal,directory=native_pair
    baseline=next(r for r in planned['rows'] if r['arm']=='baseline' and r['phase']=='first')
    pair=profile.blind_packets(planned,rows,journal)[baseline['pair_id']]
    comparison=judgment(status='unavailable',citations=['A.output','B.output','task'])
    # A stray side value on an abstention cannot be treated as an assessment.
    comparison.update(preferred_side=profile.blind_side(planned,baseline),reviewer_kind='human')
    review=dict(packet_sha256=pair['packet_sha256'],A=judgment(),B=judgment(),comparison=comparison)
    report=profile.compare(planned,rows,journal,{baseline['pair_id']:review},directory=directory)
    assert not any(r.get('semantic_regression') for r in report['rows'])
    assert report['status']=='incomplete'
    assert all('preferred_side' not in r.get('comparison',{}) for r in report['rows'])


def test_individual_packet_binding_survives_loss_of_mate_after_review(native_pair):
    planned,rows,journal,directory=native_pair
    candidate=next(r for r in planned['rows'] if r['arm']=='candidate' and r['phase']=='first')
    original_pair=profile.blind_packets(planned,rows,journal)[candidate['pair_id']]
    baseline_id=next(r['row_id'] for r in planned['rows'] if r['pair_id']==candidate['pair_id'] and r['arm']=='baseline')
    reduced=[r for r in rows if r['row_id']!=baseline_id]
    side=profile.blind_side(planned,candidate)
    review=dict(packet_sha256=original_pair['packet_sha256'],side_packet_sha256={side:original_pair[side]['packet_sha256']})
    review[side]=judgment(critical=['ignored_stop'])
    report=profile.compare(planned,reduced,journal,{candidate['pair_id']:review},directory=directory)
    row=next(r for r in report['rows'] if r['row_id']==candidate['row_id'])
    assert row['semantic']['status']=='fail'
    assert row['comparison']['status']=='unavailable'
    assert report['status']=='failed'


@pytest.mark.parametrize('alternate',[None,[],[1],0,1,'invalid',True])
def test_valid_pair_binding_preserves_critical_judgment_despite_malformed_optional_side_binding(native_pair,alternate):
    planned,rows,journal,directory=native_pair
    candidate=next(r for r in planned['rows'] if r['arm']=='candidate' and r['phase']=='first')
    pair=profile.blind_packets(planned,rows,journal)[candidate['pair_id']]
    side=profile.blind_side(planned,candidate)
    review=dict(packet_sha256=pair['packet_sha256'],side_packet_sha256=alternate)
    review[side]=judgment(critical=['lost_testimony'])
    report=profile.compare(planned,rows,journal,{candidate['pair_id']:review},directory=directory)
    result=next(r for r in report['rows'] if r['row_id']==candidate['row_id'])
    assert result['semantic']['critical_violations']==['lost_testimony']
    assert result['semantic']['status']=='fail' and report['status']=='failed'


@pytest.mark.parametrize('pair_hash',[None,'stale-pair'])
def test_valid_single_side_binding_needs_no_valid_pair_binding(native_pair,pair_hash):
    planned,rows,journal,directory=native_pair
    candidate=next(r for r in planned['rows'] if r['arm']=='candidate' and r['phase']=='first')
    pair=profile.blind_packets(planned,rows,journal)[candidate['pair_id']]
    side=profile.blind_side(planned,candidate)
    review=dict(packet_sha256=pair_hash,side_packet_sha256={side:pair[side]['packet_sha256']})
    review[side]=judgment(critical=['unsupported_fact'])
    report=profile.compare(planned,rows,journal,{candidate['pair_id']:review},directory=directory)
    result=next(r for r in report['rows'] if r['row_id']==candidate['row_id'])
    assert result['semantic']['status']=='fail' and report['status']=='failed'
    assert result['comparison']['status']=='unavailable'


def test_abstention_with_valid_critical_evidence_still_blocks_without_direction(native_pair):
    planned,rows,journal,directory=native_pair
    baseline=next(r for r in planned['rows'] if r['arm']=='baseline' and r['phase']=='first')
    pair=profile.blind_packets(planned,rows,journal)[baseline['pair_id']]
    comparison=judgment(status='unavailable',citations=['A.output','B.output','task'],critical=['unsupported_fact'])
    comparison.update(preferred_side=profile.blind_side(planned,baseline),reviewer_kind='human')
    review=dict(packet_sha256=pair['packet_sha256'],A=judgment(),B=judgment(),comparison=comparison)
    report=profile.compare(planned,rows,journal,{baseline['pair_id']:review},directory=directory)
    assert report['status']=='failed'
    assert not any(r.get('semantic_regression') for r in report['rows'])
