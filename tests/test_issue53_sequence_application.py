"""Real SQL first/later/cold-resume/replay; synthetic worker, never AI quality."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest

from scripts import issue53_profile_sequences as profile
from scripts.issue53_sequence_application import controlled_sequences, StreamObservation

IDENTITY=dict(project_id='project',client_turn_id='turn',accepted_source_id='source')
REPLY='You remember blue labels.'


def observation(**kwargs):
    return StreamObservation('blue labels',**IDENTITY,**kwargs)


def accepted(observer):
    observer.observe({'type':'source_accepted','data':IDENTITY})


def completed(reply=REPLY,**kwargs):
    return {'type':'reply_complete','data':{**IDENTITY,'cached':False,'has_question':True,'reply':reply,**kwargs}}


def test_public_milestones_ignore_headers_private_json_and_generic_filler():
    ticks=iter(range(11));observer=observation(clock=lambda:next(ticks))
    observer.observe({'type':'started'})
    observer.observe({'type':'progress','data':{'id':'collector'}})
    accepted(observer)
    observer.observe({'type':'text_delta','text':'Thank you. '})
    assert observer.timings['first_meaningful_text_s'] is None
    observer.observe({'type':'text_delta','text':REPLY})
    observer.observe({'type':'question_validated','data':{**IDENTITY,'has_question':True}})
    observer.observe(completed('Thank you. '+REPLY))
    observer.observe({'type':'conversation_saved','data':{**IDENTITY,'reply':'Thank you. '+REPLY,'conversation_saved':True}})
    assert list(observer.timings.values()) == [5,6,7,8]


def test_saved_replay_completion_uses_terminal_receipt_without_generation_milestones():
    ticks=iter(range(4));observer=observation(replay=True,expected_reply=REPLY,clock=lambda:next(ticks))
    observer.observe({'type':'result','data':{**IDENTITY,'cached':True,'conversation_saved':True,'reply':None}})
    assert all(v is None for v in observer.timings.values())
    observer.observe({'type':'result','data':{**IDENTITY,'cached':True,'conversation_saved':True,'reply':REPLY}})
    assert observer.timings['reply_complete_s']==2
    assert all(observer.timings[k] is None for k in profile.MILESTONES if k!='reply_complete_s')


def test_duplicate_public_milestones_do_not_replace_first_receipt_time():
    ticks=iter(range(8));observer=observation(clock=lambda:next(ticks));accepted(observer)
    observer.observe({'type':'text_delta','text':REPLY})
    for event in [{'type':'question_validated','data':{**IDENTITY,'has_question':True}},completed()]*2:observer.observe(event)
    assert observer.timings['validated_question_s']==3
    assert observer.timings['reply_complete_s']==4


@pytest.mark.parametrize('data',[None,[],{},dict(cached=False,has_question=True),
    {**IDENTITY,'cached':False,'has_question':True},
    {**IDENTITY,'cached':False,'has_question':True,'reply':None},
    {**IDENTITY,'cached':0,'has_question':True,'reply':REPLY},
    {**IDENTITY,'cached':False,'has_question':1,'reply':REPLY},
    {**IDENTITY,'cached':False,'has_question':True,'reply':'Other reply'},
    *[{**IDENTITY,key:'foreign','cached':False,'has_question':True,'reply':REPLY} for key in IDENTITY]])
def test_malformed_or_foreign_completion_cannot_set_timing(data):
    observer=observation();accepted(observer);observer.observe({'type':'text_delta','text':REPLY})
    observer.observe({'type':'reply_complete','data':data})
    assert observer.timings['reply_complete_s'] is None


def test_premature_plausible_completion_is_revoked_when_more_text_arrives():
    ticks=iter([0,.0001,.001,.002,2.322,2.334,3])
    observer=observation(clock=lambda:next(ticks));accepted(observer)
    observer.observe({'type':'text_delta','text':'You remember '});observer.observe(completed('You remember '))
    observer.observe({'type':'text_delta','text':'blue labels.'})
    assert observer.timings['reply_complete_s'] is None
    observer.observe(completed());observer.observe(completed())
    assert observer.timings['reply_complete_s']==2.334


@pytest.mark.parametrize('change',[{'project_id':'foreign'},{'client_turn_id':'foreign'},
    {'accepted_source_id':'foreign'},{'reply':'Other saved turn'},{'cached':1},{'conversation_saved':1}])
def test_cached_completion_requires_expected_replay_identity_and_saved_reply(change):
    observer=observation(replay=True,expected_reply=REPLY)
    observer.observe({'type':'result','data':{**IDENTITY,'reply':REPLY,'cached':True,'conversation_saved':True,**change}})
    assert observer.timings['reply_complete_s'] is None


def test_generated_observation_cannot_be_completed_by_a_cached_result_or_unaccepted_marker():
    observer=observation();observer.observe(completed())
    observer.observe({'type':'question_validated','data':{**IDENTITY,'has_question':True}})
    assert all(v is None for v in observer.timings.values())
    accepted(observer);observer.observe({'type':'text_delta','text':REPLY})
    observer.observe({'type':'result','data':{**IDENTITY,'reply':REPLY,'cached':True,'conversation_saved':True}})
    assert observer.timings['reply_complete_s'] is None


def test_error_closes_the_observation_and_retry_needs_its_own_clock():
    observer=observation();accepted(observer);observer.observe({'type':'text_delta','text':REPLY})
    observer.observe({'type':'error'});observer.observe(completed())
    assert observer.timings['reply_complete_s'] is None


def test_missing_saved_replay_prerequisite_retains_every_planned_row(tmp_path):
    scenario='issue53/resume-replay-rollback/en-AU'
    failed=scenario+'/turn-3/0/candidate';replay=scenario+'/replay/0/candidate'
    planned=profile.plan(scenario=[scenario],max_skill_calls=8,faults={failed:'save_failure'})
    rows,journal=asyncio.run(controlled_sequences(planned,tmp_path/'run'))
    by_id={r['row_id']:r for r in rows}
    assert len(rows)==len(planned['rows'])==10
    assert by_id[failed]['execution']=='failed'
    assert by_id[replay]['execution']=='unavailable'
    assert by_id[replay]['reason']=='saved_replay_prerequisite_unavailable'
    assert by_id[replay].get('timings',{})=={}
    assert by_id[replay.replace('candidate','baseline')]['execution']=='completed'
    assert journal['budget']['dispatched']==6
    assert all(call['live_model_dispatch'] is False for call in journal['budget']['calls'])
    report=profile.compare(planned,rows,journal,{},directory=tmp_path/'run')
    assert len(report['rows'])==10 and report['release_accepted'] is False


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


def assert_mobile_streams(journal):
    captures=[]
    for capture in journal['rows'].values():
        result=capture['output']['canonical_result']
        source=next(s for s in capture['after']['sources'] if s['id']==result['accepted_source_id'])
        captures.append(dict(projectId=result['project_id'],clientTurnId=source['client_turn_id'],
            reply=result['reply'],cached=capture['output']['cached'],events=capture['stream_observation']['events']))
    process=subprocess.run(['node','--import','tsx','tests/mobile-domain/helpers/consume-governed-stream.mts'],
        input=json.dumps(captures),text=True,capture_output=True,timeout=30,cwd=Path(__file__).resolve().parents[1])
    assert process.returncode==0,process.stdout+process.stderr


def test_captured_native_streams_preserve_mobile_reply_and_save_contract(native_pair):
    assert_mobile_streams(native_pair[2])


@pytest.mark.parametrize('tamper',['bare_completion','premature_completion','foreign_replay','wrong_replay_text'])
def test_resealed_early_completion_cannot_replace_bound_final_stream_receipt(native_pair,tmp_path,tamper):
    import shutil
    planned,rows,journal,directory=native_pair
    local=tmp_path/'evidence';shutil.copytree(directory,local)
    rows,changed=deepcopy(rows),deepcopy(journal)
    replay=tamper in {'foreign_replay','wrong_replay_text'}
    row=next(r for r in planned['rows'] if r['arm']=='candidate' and r['phase']==('replay' if replay else 'resumed'))
    capture=changed['rows'][row['row_id']];observation=capture['stream_observation']
    result=capture['output']['canonical_result']
    source=next(s for s in capture['after']['sources'] if s['id']==result['accepted_source_id'])
    binding={k:source[k] for k in ('project_id','client_turn_id')};binding['accepted_source_id']=source['id']
    inserted={'type':'reply_complete'};index=1
    if replay:
        inserted={'type':'result','data':{**binding,'cached':True,'conversation_saved':True,'reply':'A different saved turn.'}}
        if tamper=='foreign_replay':inserted['data'].update(project_id='foreign-project',accepted_source_id='foreign-source')
    elif tamper=='premature_completion':
        index=next(i+1 for i,e in enumerate(observation['events']) if e['type']=='question_validated')
        prefix=''.join(e['text'] for e in observation['events'][:index] if e['type']=='text_delta')
        inserted['data']={**binding,'cached':False,'has_question':True,'reply':prefix}
    before=observation['events'][index-1]['elapsed_s'];after=observation['events'][index]['elapsed_s']
    inserted['elapsed_s']=(before+after)/2
    observation['events'].insert(index,inserted)
    observation['timings']['reply_complete_s']=inserted['elapsed_s']
    imported=next(r for r in rows if r['row_id']==row['row_id'])
    imported['timings']=deepcopy(observation['timings']);imported['stream_observation_sha256']=profile.digest(observation)
    body={k:v for k,v in capture.items() if k not in {'sequence_receipt_path','sequence_receipt_sha256'}}
    (local/capture['sequence_receipt_path']).write_text(json.dumps(body));capture['sequence_receipt_sha256']=profile.digest(body)
    report=profile.compare(planned,rows,changed,{},directory=local)
    actual=next(r for r in report['rows'] if r['row_id']==row['row_id'])
    assert actual['contracts']['status']=='fail'
    assert actual['contracts']['reason']=='public_milestone_evidence_missing'
    assert report['latency']['overall']['matched_complete_pairs']<8
    assert report['release_accepted'] is False


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
