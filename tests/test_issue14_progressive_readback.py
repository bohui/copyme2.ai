"""Controlled application-shaped readbacks, never native/provider evidence."""
import asyncio
from copy import deepcopy

import pytest

from memoir_checkpoint_fixture import checkpoint

from scripts.issue14_progressive_readback import ProgressiveReadback, ReadbackError


REVISION = '9895006f0aaec8425abb21a99f88e39a3a982c2f'


def bridge(locale='en-AU'):
    return ProgressiveReadback(case_id=f'chapters.transitions.{locale}',
        run_id='synthetic-run', project_id=f'synthetic-{locale}', source_revision=REVISION)


def outcome(b):
    args = b.driver_inputs()
    sources, records, checkpoints = [], [], []
    for ordinal, text in enumerate(args['rounds'], 1):
        sources.append({'id': f'original-{ordinal}', 'version': 1, 'sequence': ordinal,
                        'text': text, 'status': 'active', 'project_id': args['project_id'],
                        'language': args['language'], 'kind': 'narrator_chat'})
        records.append({'round': ordinal, 'status': 'completed', 'background_settled': True,
            'accepted_source_id': sources[-1]['id'],
            'trajectory': {'correlation': b.before_round(args['case_id'], ordinal),
                           'final': {'status': 'completed'}},
            'canonical_state': {'project_id': args['project_id'], 'completed_rounds': ordinal, 'sources': deepcopy(sources),
                                'processing': {'extracted_through': ordinal, 'pending_inputs': 0}}})
        if ordinal % 5 == 0:
            checkpoints.append(checkpoint(args['project_id'], args['language'], ordinal,
                args['rounds'][0]))
    return {**{k: args[k] for k in ('case_id', 'project_id')}, 'status': 'completed',
            'evidence_mode': 'mock_only', 'rounds': records, 'checkpoints': checkpoints, 'canonical_identity': checkpoints[0]['identity']}


@pytest.mark.parametrize('locale', ['en-AU', 'zh-CN'])
def test_original_inputs_correlations_and_saved_checkpoint_projection(locale):
    b = bridge(locale)
    args = b.driver_inputs()
    assert len(args['rounds']) == 15
    assert args['language'] == locale
    assert set(args) == {'case_id', 'project_id', 'rounds', 'language'}
    assert 'expected' not in str(args)
    args['rounds'][0] = 'caller mutation'
    assert b.driver_inputs()['rounds'][0] != 'caller mutation'
    result = outcome(b)
    evidence = b.capture(result)
    assert evidence['status'] == 'structural_readback_complete'
    assert evidence['live_ready'] is evidence['durability_verified'] is False
    assert evidence['semantic_acceptance'] == 'human_review_required'
    assert [d['milestone'] for d in evidence['saved_checkpoints']] == [5, 10, 15]
    assert len(evidence['source_mapping']) == 15
    assert evidence['source_mapping'][0]['dataset_source_id'] == 's1'
    assert evidence['source_mapping'][0]['application_source_id'] == 'original-1'
    result['checkpoints'][0]['pages'][0]['records'][0]['preview']['text'] = 'changed later'
    assert evidence['saved_checkpoints'][0]['records'][0]['preview']['text'] != 'changed later'


@pytest.mark.parametrize('case_id', ['unknown', 'bilingual.chapters.transitions', 'chapters.transitions.en-GB'])
def test_only_reviewed_chapter_cases(case_id):
    with pytest.raises(ReadbackError):
        ProgressiveReadback(case_id=case_id, run_id='run', project_id='project', source_revision=REVISION)


@pytest.mark.parametrize('field,value', [('run_id', ''), ('run_id', 'a' * 257),
    ('project_id', 'a\nsecret'), ('source_revision', 'main'), ('source_revision', 'a' * 39)])
def test_unbound_context_rejected(field, value):
    args = dict(case_id='chapters.transitions.en-AU', run_id='run', project_id='project', source_revision=REVISION)
    args[field] = value
    with pytest.raises(ReadbackError):
        ProgressiveReadback(**args)


@pytest.mark.parametrize('ordinal', [0, 16, True, 1.0, '1'])
def test_round_correlation_rejects_wrong_ordinal(ordinal):
    b = bridge()
    with pytest.raises(ReadbackError):
        b.before_round(b.driver_inputs()['case_id'], ordinal)


def test_correlation_is_bounded_stable_and_isolated():
    from apps.api.trajectory_evaluation import normalise_correlation
    b = bridge()
    a = b.before_round(b.driver_inputs()['case_id'], 1)
    assert a == normalise_correlation(a)
    assert a == b.before_round(b.driver_inputs()['case_id'], 1)
    assert a['trace_id'] != b.before_round(b.driver_inputs()['case_id'], 2)['trace_id']
    assert a['trace_id'] != bridge('zh-CN').before_round('chapters.transitions.zh-CN', 1)['trace_id']
    with pytest.raises(ReadbackError):
        b.before_round('wrong-case', 1)


def test_subscription_label_does_not_grant_live_or_durable_acceptance():
    b = bridge()
    result = outcome(b)
    result['evidence_mode'] = 'subscription_progressive'
    evidence = b.capture(result)
    assert evidence['declared_evidence_mode'] == 'subscription_progressive'
    assert evidence['live_ready'] is evidence['durability_verified'] is False


@pytest.mark.parametrize('mutation', [
    lambda r: r.update(status='incomplete'),
    lambda r: r.update(case_id='wrong'),
    lambda r: r.update(project_id='wrong'),
    lambda r: r['rounds'].pop(),
    lambda r: r['rounds'][0].update(round=True),
    lambda r: r['rounds'][0].update(background_settled=False),
    lambda r: r['rounds'][0].update(accepted_source_id='wrong'),
    lambda r: r['rounds'][0]['trajectory']['correlation'].update(run_id='other'),
    lambda r: r['rounds'][0]['trajectory']['correlation'].update(application_revision='a' * 40),
    lambda r: r['rounds'][0]['trajectory']['final'].update(status='failed'),
    lambda r: r['rounds'][0]['canonical_state']['sources'][0].update(text='rewritten'),
    lambda r: r['rounds'][1]['canonical_state']['sources'][0].update(id='replaced'),
    lambda r: r['rounds'][0]['canonical_state']['sources'][0].update(version=True),
    lambda r: r['rounds'][0]['canonical_state']['sources'][0].update(sequence=2),
    lambda r: r['rounds'][0]['canonical_state']['sources'][0].update(status='revoked'),
    lambda r: r['rounds'][0]['canonical_state'].update(completed_rounds=0),
    lambda r: r['rounds'][0]['canonical_state']['processing'].update(extracted_through=0),
    lambda r: r['checkpoints'].pop(),
    lambda r: r['checkpoints'][0].update(milestone=10),
    lambda r: r['checkpoints'][0]['draft'].update(status='stale'),
    lambda r: r['checkpoints'][0]['draft'].update(coverage_round=4),
    lambda r: r['checkpoints'][0]['draft'].update(revision=True),
    lambda r: r['checkpoints'][0]['draft'].update(updating=True),
    lambda r: r['checkpoints'][0]['draft'].update(approval_required=True),
    lambda r: r['checkpoints'][0]['draft']['progress']['extraction'].update(pending_inputs=1),
    lambda r: r['checkpoints'][0]['pages'][0].update(records=[]),
    lambda r: r['checkpoints'][0]['pages'][0]['records'][0]['source_refs'][0].update(source_id='original-15'),
    lambda r: r['checkpoints'][0]['pages'][0]['records'][0]['source_refs'][0].update(quote='invented'),
    lambda r: r['checkpoints'][1]['pages'][0]['records'][0]['preview'].update(text='rewritten same dependencies'),
    lambda r: r['checkpoints'][1]['pages'][0]['records'][0].update(event_revision=0),
])
def test_missing_stale_mismatched_or_rewritten_readbacks_are_unavailable(mutation):
    b = bridge()
    result = outcome(b)
    mutation(result)
    with pytest.raises(ReadbackError):
        b.capture(result)
    assert b.observation(result) == {'output': None, 'metadata': {
        'issue14_progressive_readback_status': 'unavailable', 'live_ready': False}}


def test_projection_never_copies_arbitrary_metadata_or_private_trajectory():
    b = bridge()
    result = outcome(b)
    result['authorization'] = 'synthetic-secret'
    result['rounds'][0]['trajectory']['reasoning'] = 'synthetic-hidden'
    result['checkpoints'][0]['draft']['credentials'] = 'synthetic-secret'
    evidence = b.observation(result)
    assert 'synthetic-secret' not in str(evidence)
    assert 'synthetic-hidden' not in str(evidence)
    assert evidence['output']['status'] == 'structural_readback_complete'


@pytest.mark.parametrize('bad', [None, [], 'completed', {}, {'status': 'completed'}])
def test_malformed_outcome_stays_unavailable(bad):
    assert bridge().observation(bad)['output'] is None


@pytest.mark.parametrize('mutation', [
    lambda r: r['rounds'][0]['canonical_state'].update(project_id='foreign'),
    lambda r: r['rounds'][0]['canonical_state']['sources'][0].update(language='zh-CN'),
    lambda r: r['rounds'][0]['canonical_state']['sources'][0].update(kind='narrator_transcript'),
    lambda r: r['rounds'][0]['canonical_state']['processing'].update(pending_inputs=1),
    lambda r: r['checkpoints'][0]['draft'].update(preview=None),
    lambda r: r['checkpoints'][0]['draft']['preview'].update(locale='zh-CN'),
    lambda r: r['checkpoints'][0]['draft']['preview'].update(text=''),
    lambda r: r['checkpoints'][0]['draft'].update(snapshot_state='proposed'),
    lambda r: r['checkpoints'][1]['draft'].update(source_revision=1),
    lambda r: r['checkpoints'][1]['pages'][0]['records'].append(deepcopy(r['checkpoints'][1]['pages'][0]['records'][0])),
    lambda r: r['checkpoints'][0]['pages'][0]['records'][0]['source_refs'][0].update(source_id=[]),
    lambda r: r['checkpoints'][0]['pages'][0]['records'][0]['source_refs'][0].update(version=True),
    lambda r: r['checkpoints'][0]['pages'][0]['records'][0]['source_refs'][0].update(char_start=0),
    lambda r: r['checkpoints'][0]['pages'][0]['records'][0]['source_refs'][0].update(char_start=True, char_end=2),
    lambda r: r['checkpoints'][0]['pages'][0]['records'][0]['source_refs'][0].update(char_start=2, char_end=1),
    lambda r: r['checkpoints'][0]['pages'][0]['records'][0]['source_refs'][0].update(char_start=0, char_end=999999),
    lambda r: r['checkpoints'][0]['pages'][0]['records'][0]['source_refs'][0].update(char_start=0, char_end=1),
])
def test_additional_inconsistent_saved_readback_shapes(mutation):
    b = bridge()
    result = outcome(b)
    mutation(result)
    assert b.observation(result)['output'] is None


def test_actual_span_only_string_versions_and_unchanged_manuscript_revision():
    b = bridge('zh-CN')
    result = outcome(b)
    for checkpoint in result['checkpoints']:
        draft = checkpoint['draft']
        draft['revision'] = 1
        checkpoint['pages'][0]['records'][0]['source_refs'] = [{'source_id': 'original-1', 'version': '1',
            'char_start': 0, 'char_end': len(b.driver_inputs()['rounds'][0])}]
    assert b.capture(result)['saved_checkpoints'][-1]['revision'] == 1


@pytest.mark.parametrize('changed', ['record', 'preview'])
def test_same_manuscript_revision_requires_identical_saved_snapshot(changed):
    b = bridge()
    result = outcome(b)
    for saved in result['checkpoints']:
        saved['draft']['revision'] = 1
    saved = result['checkpoints'][1]
    if changed == 'record':
        saved['pages'][0]['records'][0]['event_revision'] = 2
    else:
        saved['draft']['preview']['text'] = 'Different saved preview'
    assert b.observation(result)['output'] is None


@pytest.mark.parametrize('revision', [1, 2])
def test_changed_passage_requires_changed_canonical_event(revision):
    b = bridge()
    result = outcome(b)
    for saved in result['checkpoints'][1:]:
        record = saved['pages'][0]['records'][0]
        record['preview']['text'] = 'Changed saved text'
        record['event_revision'] = revision
    assert (b.observation(result)['output'] is not None) is (revision == 2)


def test_partition_cannot_switch_to_an_unrelated_event():
    b = bridge()
    result = outcome(b)
    result['checkpoints'][1]['pages'][0]['records'][0]['event_id'] = 'different-event'
    assert b.observation(result)['output'] is None


def test_reviewed_dataset_mutation_is_rejected_before_input_release(tmp_path, monkeypatch):
    import scripts.issue14_progressive_readback as module
    path = tmp_path / 'changed.json'
    path.write_bytes(module.DATASET_PATH.read_bytes() + b'\n')
    monkeypatch.setattr(module, 'DATASET_PATH', path)
    with pytest.raises(ReadbackError):
        bridge()


def test_existing_driver_hook_abi_with_controlled_storage_no_dispatch(monkeypatch):
    from apps.api.agent_storage import UserStorage
    import scripts.canonical_evaluation as canonical
    b = bridge()
    sample = outcome(b)
    state = {'round': 0}
    class Storage(UserStorage):
        def __init__(self):
            self.user_id = sample['canonical_identity']['owner_id']
        def memory_events(self, project_id):
            assert project_id == b.driver_inputs()['project_id']
            return deepcopy(sample['rounds'][state['round']-1]['canonical_state']) if state['round'] else {
                'sources': [], 'events': [], 'completed_rounds': 0}
        def saved_memoir_draft(self, project_id, language):
            assert language == 'en-AU'
            return deepcopy(sample['checkpoints'][state['round']//5-1]['draft'])
        def lifetime_rpc(self, name, **parameters):
            if name == 'read_lifetime_project_identity':
                return deepcopy(sample['canonical_identity'])
            assert name == 'read_lifetime_private_draft_page'
            assert parameters['p_limit'] == 8 and parameters['p_after'] is None
            return deepcopy(sample['checkpoints'][state['round']//5-1]['pages'][0])
    class Runtime:
        async def turn(self, storage, text, **kwargs):
            state['round'] += 1
            ordinal = state['round']
            assert text == b.driver_inputs()['rounds'][ordinal-1]
            assert kwargs['evaluation'] == b.before_round(b.driver_inputs()['case_id'], ordinal)
            return {'reply': 'Controlled response', 'accepted_source_id': f'original-{ordinal}',
                    'trajectory': sample['rounds'][ordinal-1]['trajectory']}
    async def no_lanes(*args, **kwargs):
        return []
    # This is the pure orchestration/readback ABI test: explicit closed
    # boundaries supply its synthetic records. Real SQL/ASGI delivery is tested
    # by test_canonical_turn_publication and the native evaluation/canary suites.
    async def delivery(runtime, storage, text, *, options, evaluation=None, **unused):
        return await runtime.turn(storage,text,**options,evaluation=evaluation)
    async def read(storage, project_id, reader):
        return reader(None)
    def head(storage, project_id, *, language=None):
        draft=storage.saved_memoir_draft(project_id,language)
        return draft
    monkeypatch.setattr(canonical,'canonical_turn',delivery)
    monkeypatch.setattr(canonical,'canonical_read',read)
    monkeypatch.setattr(canonical,'draft_head',head)
    monkeypatch.setattr(canonical, 'dispatch_memoir_lanes_once', no_lanes)
    monkeypatch.setattr(canonical, 'private_draft_cadence', lambda: 5)
    driver = canonical.CanonicalEvaluationDriver(storage=Storage(), runtime=Runtime(),
        broker=None, temporal_client=None, task_queue='synthetic')
    result = asyncio.run(driver.run_case(**b.driver_inputs(), evidence_mode='mock_only', before_round=b.before_round))
    assert b.capture(result)['status'] == 'structural_readback_complete'
    assert state['round'] == 15


def test_existing_live_launcher_still_denies_before_factories():
    from scripts.run_issue14_evaluation import run_evaluation
    from apps.api.issue14_execution_admission import AdmissionDenied
    def forbidden():
        pytest.fail('No provider, worker or judge factory may run')
    with pytest.raises(AdmissionDenied):
        run_evaluation(admission=None, run_id='synthetic-run', source_revision=REVISION,
            runtime_factory=forbidden, worker_factory=forbidden, judge_factory=forbidden)


def test_fifteen_turns_cannot_relabel_the_historical_live_canary():
    from scripts.canonical_evaluation import CanonicalEvaluationDriver
    # The live guard must reject before dereferencing any storage/runtime fields.
    driver = object.__new__(CanonicalEvaluationDriver)
    with pytest.raises(ValueError, match='verified provider accounting adapter'):
        asyncio.run(driver.run_case(**bridge().driver_inputs(),
            evidence_mode='guarded_live_canary', single_attempt=True))


def test_readback_never_contacts_network_or_subprocess(monkeypatch):
    import socket
    import subprocess
    def forbidden(*args, **kwargs):
        pytest.fail('The pure bridge must not contact a network or spawn a process')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden)
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    b = bridge()
    assert b.observation(outcome(b))['output']['live_ready'] is False
