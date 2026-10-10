"""Controlled fifty-round shapes are structural evidence, never live proof."""
from copy import deepcopy
import hashlib
import json
from uuid import UUID, uuid5

import pytest

from scripts import memoir_fifty_readback as module
from scripts.issue14_progressive_readback import ProgressiveReadback, ReadbackError


RUN_ID = '00000000-0000-4000-8000-000000000050'
REVISION = '9895006f0aaec8425abb21a99f88e39a3a982c2f'
ORIGINAL_IDS = ('harbour-copper-notebook', 'chengdu-tea-ledger',
                'perth-workshop-compass', 'kunming-garden-lanterns',
                'sydney-platform-letters')
ORIGINAL_HASH = 'e7f705bc4a96537b01cb5cde7d412972bdd929de49d339bc6b1a95bc9cb43927'


def bridge(case_id=ORIGINAL_IDS[0], run_id=RUN_ID):
    plan = module.case_plans_for_run(run_id)[case_id]
    return module.FiftyReadback(case_id=case_id, run_id=run_id,
                               project_id=plan['project_id'], source_revision=REVISION)


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
            'canonical_state': {'project_id': args['project_id'], 'completed_rounds': ordinal,
                                'sources': deepcopy(sources),
                                'processing': {'extracted_through': ordinal, 'pending_inputs': 0}}})
        if ordinal in module.CHECKPOINTS:
            checkpoints.append({'milestone': ordinal, 'draft': {
                'status': 'ready', 'covered_round': ordinal, 'milestone': ordinal,
                'revision': ordinal // 5, 'updating': False, 'error': None,
                'proposal_pending': False,
                'preview': {'locale': args['language'], 'text': args['rounds'][0]},
                'milestones': [{'milestone': n, 'covered_round': n, 'state': 'completed',
                                'manuscript_revision': n // 5} for n in range(5, ordinal + 1, 5)],
                'progress': {'extraction': {'extracted_through': ordinal, 'pending_inputs': 0}},
                'sections': [{'id': 'chapter__first', 'chapter_id': 'chapter',
                    'fingerprint': 'a' * 64, 'revision': 1, 'content': args['rounds'][0],
                    'source_refs': [{'source_id': 'original-1', 'version': 1,
                                     'quote': args['rounds'][0]}]}]}})
    return {**{k: args[k] for k in ('case_id', 'project_id')}, 'status': 'completed',
            'evidence_mode': module.EVIDENCE_MODE, 'rounds': records, 'checkpoints': checkpoints}


def test_original_five_cases_are_pinned_ordered_and_not_extended_fifteen_inputs():
    raw = module.DATASET_PATH.read_bytes()
    original = json.loads(raw)
    assert hashlib.sha256(raw).hexdigest() == module.DATASET_SHA256 == ORIGINAL_HASH
    assert original['dataset_version'] == module.DATASET_VERSION == 'memoir-five-case/1'
    assert module.CASE_IDS == ORIGINAL_IDS
    assert module.CHECKPOINTS == tuple(range(5, 51, 5))
    assert module.EVIDENCE_MODE == 'subscription_fifty'
    assert len({text for case in original['cases'] for text in case['rounds']}) == 250
    languages = []
    for case in original['cases']:
        b = bridge(case['id'])
        args = b.driver_inputs()
        assert set(args) == {'case_id', 'project_id', 'rounds', 'language'}
        assert args['rounds'] == case['rounds']
        assert len(args['rounds']) == len(set(args['rounds'])) == 50
        assert args['project_id'] != case['project_id']
        assert args['language'] == case['locale']
        languages.append(args['language'])
        args['rounds'][0] = 'caller changed the prompt'
        assert b.driver_inputs()['rounds'] == case['rounds']
    assert languages.count('en-AU') == 3
    assert languages.count('zh-CN') == 2


def test_identity_plans_are_stable_fresh_and_campaign_namespaced():
    from scripts.issue14_progressive_readback import case_plans_for_run as progressive_plans
    first = module.case_plans_for_run(RUN_ID)
    second = module.case_plans_for_run('00000000-0000-4000-8000-000000000051')
    assert tuple(first) == ORIGINAL_IDS
    assert first == module.case_plans_for_run(RUN_ID)
    identifiers = {p[key] for p in first.values() for key in ('owner_id', 'project_id')}
    assert len(identifiers) == 10
    assert all(UUID(value).version == 5 for value in identifiers)
    assert identifiers.isdisjoint(p[key] for p in second.values() for key in ('owner_id', 'project_id'))
    assert identifiers.isdisjoint(p[key] for p in progressive_plans(RUN_ID).values()
                                 for key in ('owner_id', 'project_id'))
    campaign = uuid5(UUID(RUN_ID), 'memoir-five-case/1/subscription_fifty')
    for case_id, plan in first.items():
        assert plan['owner_id'] == str(uuid5(campaign, case_id + '/owner'))
        assert plan['project_id'] == str(uuid5(campaign, case_id + '/project'))
        assert plan['project_id'] != str(uuid5(UUID(RUN_ID), case_id + '/project'))
    first[ORIGINAL_IDS[0]]['project_id'] = 'mutated'
    assert module.case_plans_for_run(RUN_ID)[ORIGINAL_IDS[0]]['project_id'] != 'mutated'


@pytest.mark.parametrize('run_id', ['not-a-uuid', '00000000000040008000000000000050',
                                  '00000000-0000-4000-8000-0000000000AB', None, 50])
def test_identity_plan_rejects_noncanonical_run_id(run_id):
    with pytest.raises(ValueError):
        module.case_plans_for_run(run_id)


@pytest.mark.parametrize('case_id', ORIGINAL_IDS)
def test_complete_original_fifty_inputs_and_ten_saved_checkpoints(case_id):
    b = bridge(case_id)
    result = outcome(b)
    evidence = b.capture(result)
    assert evidence['schema_version'] == 'memoir-fifty-readback/1'
    assert evidence['status'] == 'structural_readback_complete'
    assert evidence['dataset_content_hash'] == ORIGINAL_HASH
    assert evidence['declared_evidence_mode'] == 'subscription_fifty'
    assert len(evidence['source_mapping']) == 50
    for ordinal, mapping in enumerate(evidence['source_mapping'], 1):
        assert mapping == {'dataset_source_id': f'{case_id}/round/{ordinal}',
                           'application_source_id': f'original-{ordinal}',
                           'version': 1, 'round': ordinal,
                           'trace_id': b.before_round(case_id, ordinal)['trace_id']}
    assert [row['milestone'] for row in evidence['saved_checkpoints']] == list(module.CHECKPOINTS)
    assert evidence['durability_verified'] is evidence['live_ready'] is False
    assert evidence['provider_cohort_verified'] is False
    assert evidence['semantic_acceptance'] == 'human_review_required'
    assert 'canonical_event_entailment' in evidence['unassessed']
    assert 'chapter_word_limit' in evidence['unassessed']
    assert b.observation(result)['metadata'] == {
        'memoir_fifty_readback_status': 'structural_readback_complete', 'live_ready': False}
    result['checkpoints'][0]['draft']['sections'][0]['content'] = 'mutated'
    assert evidence['saved_checkpoints'][0]['sections'][0]['content'] != 'mutated'


@pytest.mark.parametrize('ordinal', [0, 51, True, 1.0, '1'])
def test_fifty_round_bounds_are_exact(ordinal):
    with pytest.raises(ReadbackError):
        bridge().before_round(ORIGINAL_IDS[0], ordinal)


def test_round_correlations_bind_dataset_run_revision_project_case_and_ordinal():
    b = bridge()
    first = b.before_round(ORIGINAL_IDS[0], 1)
    assert first['dataset'] == 'memoir-five-case/1'
    assert first['dataset_version'] == ORIGINAL_HASH
    assert first['application_revision'] == REVISION
    assert first == b.before_round(ORIGINAL_IDS[0], 1)
    assert first['trace_id'] != b.before_round(ORIGINAL_IDS[0], 50)['trace_id']
    assert first['trace_id'] != bridge(run_id='00000000-0000-4000-8000-000000000051').before_round(ORIGINAL_IDS[0], 1)['trace_id']
    assert first['trace_id'] != bridge(ORIGINAL_IDS[1]).before_round(ORIGINAL_IDS[1], 1)['trace_id']
    with pytest.raises(ReadbackError):
        b.before_round(ORIGINAL_IDS[1], 1)


@pytest.mark.parametrize('mutation', [
    lambda r: r.update(status='incomplete'),
    lambda r: r.update(case_id='foreign'),
    lambda r: r.update(project_id='foreign'),
    lambda r: r.update(evidence_mode='subscription_progressive'),
    lambda r: r.update(evidence_mode='mock_only'),
    lambda r: r.update(evidence_mode='guarded_live_canary'),
    lambda r: r['rounds'].pop(),
    lambda r: r['rounds'][49].update(round=True),
    lambda r: r['rounds'][49].update(background_settled=False),
    lambda r: r['rounds'][49].update(accepted_source_id='original-1'),
    lambda r: r['rounds'][49]['trajectory']['correlation'].update(dataset_version='wrong'),
    lambda r: r['rounds'][49]['trajectory']['correlation'].update(application_revision='a' * 40),
    lambda r: r['rounds'][49]['trajectory']['final'].update(status='failed'),
    lambda r: r['rounds'][49]['canonical_state']['sources'][49].update(text='repeated old input'),
    lambda r: r['rounds'][49]['canonical_state']['sources'][0].update(id='changed-source'),
    lambda r: r['rounds'][49]['canonical_state']['sources'][0].update(version=True),
    lambda r: r['rounds'][49]['canonical_state']['sources'][0].update(sequence=2),
    lambda r: r['rounds'][49]['canonical_state']['sources'][0].update(language='zh-CN'),
    lambda r: r['rounds'][49]['canonical_state']['sources'][0].update(status='revoked'),
    lambda r: r['rounds'][49]['canonical_state']['sources'][0].update(kind='summary'),
    lambda r: r['rounds'][49]['canonical_state']['processing'].update(pending_inputs=1),
    lambda r: r['checkpoints'].pop(),
    lambda r: r['checkpoints'][9].update(milestone=45),
    lambda r: r['checkpoints'][9]['draft'].update(status='pending'),
    lambda r: r['checkpoints'][9]['draft'].update(covered_round=49),
    lambda r: r['checkpoints'][9]['draft'].update(revision=True),
    lambda r: r['checkpoints'][9]['draft'].update(updating=True),
    lambda r: r['checkpoints'][9]['draft'].update(proposal_pending=True),
    lambda r: r['checkpoints'][9]['draft'].update(error='failed'),
    lambda r: r['checkpoints'][9]['draft']['progress']['extraction'].update(extracted_through=49),
    lambda r: r['checkpoints'][9]['draft']['milestones'][0].update(manuscript_revision=2),
    lambda r: r['checkpoints'][9]['draft'].update(sections=[]),
    lambda r: r['checkpoints'][0]['draft']['sections'][0]['source_refs'][0].update(source_id='original-50'),
    lambda r: r['checkpoints'][9]['draft']['sections'][0]['source_refs'][0].update(quote='invented'),
    lambda r: r['checkpoints'][9]['draft']['sections'][0]['source_refs'][0].update(version=True),
    lambda r: r['checkpoints'][9]['draft']['sections'][0]['source_refs'][0].update(char_start=0, char_end=99999),
    lambda r: r['checkpoints'][9]['draft']['sections'][0].update(content='rewritten same fingerprint'),
    lambda r: r['checkpoints'][9]['draft']['sections'][0].update(revision=2),
    lambda r: r['checkpoints'][9]['draft']['sections'][0].update(event_ids=['changed']),
])
def test_incomplete_or_inconsistent_fifty_evidence_fails_closed(mutation):
    b = bridge()
    result = outcome(b)
    mutation(result)
    with pytest.raises(ReadbackError):
        b.capture(result)
    assert b.observation(result) == {'output': None, 'metadata': {
        'memoir_fifty_readback_status': 'unavailable', 'live_ready': False}}


@pytest.mark.parametrize('bad', [None, [], 'completed', {}, {'status': 'completed'}])
def test_malformed_fifty_outcome_is_null(bad):
    assert bridge().observation(bad)['output'] is None


def test_span_references_and_same_saved_revision_remain_valid():
    b = bridge(ORIGINAL_IDS[1])
    result = outcome(b)
    for checkpoint in result['checkpoints']:
        draft = checkpoint['draft']
        draft['revision'] = 1
        for row in draft['milestones']:
            row['manuscript_revision'] = 1
        draft['sections'][0]['source_refs'] = [{'source_id': 'original-1', 'version': '1',
            'char_start': 0, 'char_end': len(b.driver_inputs()['rounds'][0])}]
    assert b.capture(result)['saved_checkpoints'][-1]['revision'] == 1
    result['checkpoints'][9]['draft']['preview']['text'] = 'different saved snapshot'
    assert b.observation(result)['output'] is None


@pytest.mark.parametrize('revision', [1, 2])
def test_changed_fingerprint_still_requires_increasing_section_revision(revision):
    b = bridge()
    result = outcome(b)
    result['checkpoints'][9]['draft']['sections'][0].update(
        content='changed text', fingerprint='b' * 64, revision=revision)
    assert (b.observation(result)['output'] is not None) is (revision == 2)


def test_hash_drift_is_rejected_before_input_release(tmp_path, monkeypatch):
    path = tmp_path / 'changed-inputs.json'
    path.write_bytes(module.DATASET_PATH.read_bytes() + b'\n')
    monkeypatch.setattr(module, 'DATASET_PATH', path)
    with pytest.raises(ReadbackError):
        bridge()


@pytest.mark.parametrize('mutation', [
    lambda d: d.update(dataset_version='memoir-five-case/2'),
    lambda d: d['cases'].reverse(),
    lambda d: d['cases'].pop(),
    lambda d: d['cases'][0].update(locale='zh-CN'),
    lambda d: d['cases'][0]['rounds'].pop(),
    lambda d: d['cases'][0]['rounds'].append('extra input'),
    lambda d: d['cases'][0]['rounds'].__setitem__(49, d['cases'][0]['rounds'][0]),
    lambda d: d['cases'][0]['rounds'].__setitem__(49, None),
])
def test_exact_original_shape_remains_required_even_if_pin_is_changed(mutation, tmp_path, monkeypatch):
    dataset = json.loads(module.DATASET_PATH.read_bytes())
    mutation(dataset)
    raw = json.dumps(dataset).encode()
    path = tmp_path / 'invalid-input-shape.json'
    path.write_bytes(raw)
    monkeypatch.setattr(module, 'DATASET_PATH', path)
    monkeypatch.setattr(module, 'DATASET_SHA256', hashlib.sha256(raw).hexdigest())
    with pytest.raises(ReadbackError):
        bridge()


@pytest.mark.parametrize('case_id', ['unknown', 'chapters.transitions.en-AU', 'chapters.transitions.zh-CN'])
def test_fifty_profile_rejects_other_datasets(case_id):
    with pytest.raises(ReadbackError):
        module.FiftyReadback(case_id=case_id, run_id=RUN_ID,
                            project_id='project', source_revision=REVISION)


def test_legacy_fifteen_profile_cannot_release_or_accept_fifty():
    with pytest.raises(ReadbackError):
        ProgressiveReadback(case_id=ORIGINAL_IDS[0], run_id=RUN_ID,
                            project_id='project', source_revision=REVISION)
    old = ProgressiveReadback(case_id='chapters.transitions.en-AU', run_id=RUN_ID,
                              project_id='project', source_revision=REVISION)
    assert len(old.driver_inputs()['rounds']) == 15
    with pytest.raises(ReadbackError):
        old.before_round('chapters.transitions.en-AU', 16)
    assert old.observation(outcome(old))['output'] is None


def test_projection_and_inputs_never_load_truth_or_dispatch(monkeypatch):
    import socket
    import subprocess
    from pathlib import Path
    read_bytes = Path.read_bytes
    def inputs_only(path):
        assert path == module.DATASET_PATH, 'Truth or expected answers must not be loaded'
        return read_bytes(path)
    def forbidden(*args, **kwargs):
        pytest.fail('Pure readback may not dispatch subprocesses or network requests')
    monkeypatch.setattr(Path, 'read_bytes', inputs_only)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden)
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    b = bridge()
    result = outcome(b)
    result['authorization'] = 'synthetic-secret'
    result['rounds'][0]['trajectory']['reasoning'] = 'synthetic-hidden'
    result['checkpoints'][0]['draft']['credentials'] = 'synthetic-secret'
    evidence = b.observation(result)
    assert evidence['output']['live_ready'] is False
    assert 'synthetic-secret' not in str(evidence)
    assert 'synthetic-hidden' not in str(evidence)
