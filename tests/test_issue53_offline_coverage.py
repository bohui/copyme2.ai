"""Bounded real-SQL coverage expansion; every external completion stays synthetic."""
import asyncio
from copy import deepcopy
import json
import os
import shutil

import pytest

from scripts import issue53_profile_sequences as profile
from scripts.issue53_sequence_application import controlled_sequences


@pytest.fixture(scope='module')
def full_native_manifest(tmp_path_factory):
    folder=tmp_path_factory.mktemp('issue53-full-manifest')
    locale=os.environ.get('ISSUE53_TEST_LOCALE')
    if locale is not None and locale not in {'en-AU','zh-CN'}:
        raise ValueError('unsupported_issue53_test_locale')
    selected=[s['id'] for s in profile.load_manifest()['scenarios'] if locale is None or s['locale']==locale]
    planned=profile.plan(scenario=selected,max_skill_calls=80,controlled_rollback=True)
    rows,journal=asyncio.run(controlled_sequences(planned,folder))
    report=profile.compare(planned,rows,journal,{},directory=folder)
    (folder/'comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    return planned,rows,journal,report,folder


def test_all_manifest_rows_execute_with_real_persistence_and_mocked_generation(full_native_manifest):
    planned,rows,journal,report,folder=full_native_manifest
    cohorts=len({s['locale'] for s in planned['scenarios']})
    assert len(planned['scenarios'])==6*cohorts and len(rows)==40*cohorts
    assert all(r['execution']=='completed' for r in rows),[(r['row_id'],r.get('reason')) for r in rows if r['execution']!='completed']
    assert journal['budget']['dispatched']==38*cohorts
    assert all(c['live_model_dispatch'] is False for c in journal['budget']['calls'])
    assert not report['release_accepted']
    assert all(r['contracts']['status']=='pass' for r in report['rows']),[
        (r['row_id'],r['contracts']) for r in report['rows'] if r['contracts']['status']!='pass']
    # Fixture contracts pass; semantic and human acceptance remain incomplete.
    assert report['status']=='incomplete'


def test_controlled_rollback_affects_next_generation_and_keeps_prior_saved_state(full_native_manifest):
    planned,rows,journal,report,folder=full_native_manifest
    for row in planned['rows']:
        if '/resume-replay-rollback/' not in row['scenario_id'] or row['step_id']!='turn-4':continue
        capture=journal['rows'][row['row_id']]
        assert next(r for r in report['rows'] if r['row_id']==row['row_id'])['contracts']['status']=='pass'
        policy=capture['controlled_policy']
        assert policy['scope']=='isolated_mock_transport'
        assert policy['observed_request_model']==policy['saved_model']=='gpt-5.6-luna-pooled'
        if row['arm']=='candidate': assert capture['before']['session'][0]['thread_model']=='synthetic-byte-bpe'
        assert capture['after']['sources'][:-1]==capture['before']['sources']
        assert capture['after']['replies'][:-1]==capture['before']['replies']
        assert capture['future_configuration']==planned['variants']['baseline']


def test_name_work_stop_skip_and_correction_contracts_are_observable(full_native_manifest):
    planned,rows,journal,report,folder=full_native_manifest
    for row in planned['rows']:
        capture=journal['rows'][row['row_id']]
        if row['action']=='replay':continue
        saved=capture['after']['replies'][-1]['plan']
        assert saved['work']['mode']==row['expected_work']
        if row['item']['gold']['facts']['stopped']:
            assert saved['candidates']==[] and saved['chosen_id'] is None
        elif capture['before']['replies']:
            assert saved['candidates'][0]['question']!=capture['before']['replies'][-1]['plan']['candidates'][0]['question']
        if '/name-clue/' in row['scenario_id'] and row['phase']=='first':
            assert saved['work']['name']==('韩凤江' if row['locale']=='zh-CN' else 'Joan')
        assert all(p['current']['narrator']['original']==row['item']['task']['source']['text'] for p in capture['packet_readbacks'])


def test_current_policy_tail_eligibility_does_not_erase_saved_testimony(full_native_manifest):
    planned,rows,journal,report,folder=full_native_manifest
    locale=planned['scenarios'][0]['locale']
    row=next(r for r in planned['rows'] if r['scenario_id']=='issue53/switch-skip/'+locale and r['step_id']=='turn-2')
    capture=journal['rows'][row['row_id']]
    packet=capture['packet_readbacks'][-1]
    assert packet['tail_readback']['complete']
    assert not packet['tail_readback']['records'][0].get('conversation_saved',False)
    assert 'assistant' not in packet['tail'][0]
    assert capture['before']['replies']==capture['after']['replies'][:-1]
    row=next(r for r in planned['rows'] if r['scenario_id']=='issue53/name-clue/'+locale and r['step_id']=='turn-2')
    capture=deepcopy(journal['rows'][row['row_id']])
    prior=next(c for c in journal['rows'].values() if c['row_id']==row['row_id'].replace('turn-2','turn-1'))
    capture['packet_readbacks'][-1]['tail'][0].pop('assistant')
    with pytest.raises(ValueError,match='prior_exchange_packet_missing'):
        profile._sequence(planned,row,capture,prior)


@pytest.mark.parametrize('tamper',['eligibility','envelope','policy'])
def test_rewritten_observations_cannot_replace_independent_dispatch_request(full_native_manifest,tmp_path,tamper):
    planned,rows,journal,report,folder=full_native_manifest
    copied=tmp_path/'changed';shutil.copytree(folder,copied)
    changed=deepcopy(journal)
    locale=planned['scenarios'][0]['locale']
    row=next(r for r in planned['rows'] if r['scenario_id']=='issue53/name-clue/'+locale
             and r['step_id']=='turn-2' and r['arm']=='candidate')
    capture=changed['rows'][row['row_id']]
    packet=capture['packet_readbacks'][-1]
    if tamper=='eligibility':
        packet['tail'][0].pop('assistant')
        eligible=packet['tail_readback']['records'][0]
        eligible['conversation_saved']=False;eligible.pop('assistant_reply')
    elif tamper=='envelope':
        other='zh-CN' if locale=='en-AU' else 'en-AU'
        capture['request_envelopes'][-1]['input']['interview_context']['interview_language']=other
        packet['interview_context']['interview_language']=other
    else:
        capture['controlled_policy']['observed_request_model']='fabricated-route'
    body={k:v for k,v in capture.items() if k not in {'sequence_receipt_path','sequence_receipt_sha256'}}
    (copied/capture['sequence_receipt_path']).write_text(json.dumps(body))
    capture['sequence_receipt_sha256']=profile.digest(body)
    imported=profile.compare(planned,rows,changed,{},directory=copied)
    actual=next(r for r in imported['rows'] if r['row_id']==row['row_id'])
    assert actual['contracts']['status']=='fail'
    assert actual['contracts']['reason'] in {'governed_packet_dispatch_mismatch','independent_dispatch_request_mismatch','controlled_policy_dispatch_mismatch'}


def test_blind_native_witnesses_hide_route_prompt_and_execution_order(full_native_manifest):
    planned,rows,journal,report,folder=full_native_manifest
    packets=profile.blind_packets(planned,rows,journal)
    for pair in packets.values():
        for side in ('A','B'):
            witnesses=pair[side]['evidence']['witnesses']
            encoded=json.dumps(witnesses)
            assert all(clue not in encoded for clue in ['gpt-5.6-luna-pooled','synthetic-byte-bpe',
                       'actual_prompt_version','created_at','updated_at','thread_model'])
            assert witnesses['after']['sources']


@pytest.mark.parametrize('fault',['malformed','disconnect','timeout','save_failure'])
@pytest.mark.parametrize('locale',['en-AU','zh-CN'])
def test_negative_streams_retain_failed_rows_and_durable_original_without_false_save(tmp_path,fault,locale):
    scenario='issue53/name-clue/'+locale
    row_id=scenario+'/turn-1/0/baseline'
    planned=profile.plan(scenario=[scenario],max_skill_calls=8,faults={row_id:fault})
    rows,journal=asyncio.run(controlled_sequences(planned,tmp_path/'run'))
    report=profile.compare(planned,rows,journal,{},directory=tmp_path/'run')
    failed=next(r for r in rows if r['row_id']==row_id)
    assert len(rows)==len(report['rows'])==6
    assert failed['execution']==('timed_out' if fault=='timeout' else 'failed')
    proof=journal['failures'][row_id]
    assert len(proof['after']['sources'])==1 and proof['after']['replies']==[]
    assert proof['after']['sources'][0]['text']==planned['rows'][0]['item']['task']['source']['text']
    assert not any(e['type']=='conversation_saved' for e in proof['stream_observation']['events'])
    assert failed['timings']['durable_save_s'] is None
    if fault=='save_failure':
        assert proof['stream_observation']['public_text']
    if fault=='disconnect':
        assert proof['transport_observations']==['upstream_fragment_sent_then_disconnect']
        if not proof['stream_observation']['public_text']:
            assert failed['timings']['first_meaningful_text_s'] is None
    assert len(proof['dispatches'])==1
    assert not report['release_accepted']
