"""Issue 53 adds sequences and comparisons, never another evaluator core."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts import issue53_profile_sequences as profile


def test_manifest_has_real_sequence_requirements_and_bilingual_coverage():
    manifest = profile.load_manifest()
    assert manifest['schema_version'] == 'memoir-response-sequences/1'
    assert {s['locale'] for s in manifest['scenarios']} == {'en-AU', 'zh-CN'}
    for scenario in manifest['scenarios']:
        assert scenario['steps'][0]['phase'] == 'first'
        assert sum(s['action'] == 'turn' for s in scenario['steps']) >= 2
        for i, step in enumerate(scenario['steps']):
            if step.get('phase') == 'resumed':
                assert any(s['action'] == 'reopen' for s in scenario['steps'][:i])
                assert step['requires'] == ['persisted_session', 'prior_sources', 'prior_replies', 'current_configuration']
    tags = set().union(*(set(s['coverage']) for s in manifest['scenarios']))
    assert {'name_only', 'name_story', 'short_extraction', 'long_emotional', 'correction',
            'already_answered', 'stop', 'skip', 'language_switch', 'photo_reference',
            'saved_replay', 'persisted_resume', 'future_rollback'} <= tags


def test_zero_dispatch_plan_binds_pairs_and_all_provenance(monkeypatch):
    import socket
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: pytest.fail('planning used network'))
    planned = profile.plan(samples=2)
    assert planned['dispatches'] == 0
    assert planned['dependency']['commit'] == profile.PR92_COMMIT
    for field in ('application', 'prompts', 'configuration_sources', 'dataset', 'evaluator', 'profiler'):
        assert planned['provenance'][field]
    pairs = {}
    for row in planned['rows']:
        pairs.setdefault(row['pair_id'], []).append(row)
    assert all({r['arm'] for r in rows} == {'baseline', 'candidate'} for rows in pairs.values())
    assert len({r['row_id'] for r in planned['rows']}) == len(planned['rows'])
    assert planned['budgets']['live_dispatches'] == 0
    assert planned['human_acceptance'] == 'pending_bilingual_heldout'


def test_empty_ingestion_keeps_every_planned_row_and_is_incomplete():
    planned = profile.plan()
    report = profile.compare(planned, [], {}, {}, directory=Path('/tmp'))
    assert len(report['rows']) == len(planned['rows'])
    assert all(r['execution'] == 'unavailable' for r in report['rows'])
    assert report['status'] == 'incomplete'
    assert not report['release_accepted']
    assert report['latency']['overall']['matched_complete_pairs'] == 0
    assert set(report['latency']['by_locale']) == {'en-AU', 'zh-CN'}
    assert {'first', 'later', 'resumed', 'replay'} <= set(report['latency']['by_phase'])


def test_missing_or_mock_only_evidence_cannot_certify_release():
    planned = profile.plan()
    rows = [dict(row_id=r['row_id'], execution='completed', evidence_mode='controlled_fixture',
                 output={'public_text': 'Fast fixture'}, timings={k: .01 for k in profile.MILESTONES})
            for r in planned['rows']]
    report = profile.compare(planned, rows, {}, {}, directory=Path('/tmp'))
    assert not report['release_accepted'] and report['status'] == 'incomplete'
    assert all(r['contracts']['status'] == 'unavailable' for r in report['rows'])
    assert all(r['provider_metrics']['usage'] is None for r in report['rows'])


def test_unexpected_duplicate_and_tampered_plan_fail_closed():
    planned = profile.plan()
    with pytest.raises(ValueError, match='duplicate_or_unplanned'):
        profile.compare(planned, [{'row_id': 'foreign'}], {}, {}, directory=Path('/tmp'))
    row = {'row_id': planned['rows'][0]['row_id']}
    with pytest.raises(ValueError, match='duplicate_or_unplanned'):
        profile.compare(planned, [row, row], {}, {}, directory=Path('/tmp'))
    changed = deepcopy(planned); changed['provenance']['dataset'] = 'tampered'
    with pytest.raises(ValueError, match='plan_changed'):
        profile.compare(changed, [], {}, {}, directory=Path('/tmp'))


@pytest.mark.parametrize('status', ['failed', 'timed_out', 'unavailable'])
def test_failed_planned_rows_and_unknown_provider_metrics_survive(status):
    planned = profile.plan()
    row = dict(row_id=planned['rows'][0]['row_id'], execution=status,
               timings={'first_meaningful_text_s': .1}, provider_metrics={'internal_attempts': None})
    report = profile.compare(planned, [row], {}, {}, directory=Path('/tmp'))
    assert report['rows'][0]['execution'] == status
    assert report['rows'][0]['provider_metrics']['internal_attempts'] is None
    assert report['latency']['overall']['planned_pairs'] == len(planned['rows']) // 2
    assert report['latency']['overall']['matched_complete_pairs'] == 0


def test_profiler_defaults_to_offline_plan_and_requires_explicit_old_live_mode(monkeypatch, capsys):
    from scripts import profile_first_reply
    monkeypatch.setattr(profile_first_reply.asyncio, 'run', lambda *a: pytest.fail('default dispatched'))
    assert profile_first_reply.main([]) == 0
    assert json.loads(capsys.readouterr().out)['dispatches'] == 0


def test_step_specific_gold_and_frozen_judge_definition(monkeypatch):
    planned=profile.plan()
    first=next(r for r in planned['rows'] if r['phase']=='first')
    assert first['item']['task']['context']['opening_turn'] is True
    stop=next(r for r in planned['rows'] if r['item']['gold']['facts']['stopped'])
    assert stop['item']['gold']['facts']['question'] is False
    monkeypatch.setattr(profile.suite,'judge_definition',lambda *a:pytest.fail('ingestion reloaded mutable judge'))
    rows=[dict(row_id=r['row_id'],execution='completed',output={'public_text':'controlled'}) for r in planned['rows']]
    pairs=profile.blind_packets(planned,rows)
    assert all(p['A']['evaluator_sha256']==planned['judge_definition']['compiled_sha256'] for p in pairs.values())
    assert all(p['human_preference_contract']['kind']=='separate_blinded_human_annotation_not_model_prompt' for p in pairs.values())


def test_failure_reason_is_preserved():
    planned=profile.plan()
    report=profile.compare(planned,[dict(row_id=planned['rows'][0]['row_id'],execution='failed',reason='specific_failure')],{}, {},directory=Path('/tmp'))
    assert report['rows'][0]['reason']=='specific_failure'


def test_controlled_adapter_cannot_claim_a_real_provider_configuration(tmp_path):
    import asyncio
    from scripts.issue53_sequence_application import controlled_sequences
    variants={arm:dict(model='unexecuted-route',requested_effort=None,effective_effort=None,policy_receipt_sha256=None)
              for arm in ('baseline','candidate')}
    planned=profile.plan(variants=variants)
    with pytest.raises(ValueError,match='cannot_attest_provider_configuration'):
        asyncio.run(controlled_sequences(planned,tmp_path/'never-allocated'))
    assert not (tmp_path/'never-allocated').exists()


@pytest.mark.parametrize('locale,target',[('en-AU','zh-CN'),('zh-CN','en-AU')])
def test_language_switch_updates_per_turn_judge_context(locale,target):
    planned=profile.plan(scenario=['issue53/switch-skip/'+locale])
    later=[r for r in planned['rows'] if r['step_id'] in {'turn-3','turn-4'}]
    assert all(r['item']['task']['context']['interview_language']==target for r in later)
    assert all(r['item']['task']['source']['language']==target for r in later)


def test_blind_export_serializes_labels_in_canonical_order_not_arm_order(monkeypatch):
    planned=profile.plan()
    # Force every pair to map baseline->B. Host insertion order must not reveal it.
    monkeypatch.setattr(profile,'blind_side',lambda p,r:'B' if r['arm']=='baseline' else 'A')
    rows=[dict(row_id=r['row_id'],execution='completed',output={'text':'Synthetic reply'}) for r in planned['rows']]
    exported=profile.blind_packets(planned,rows)
    assert len(exported)==40
    assert all(list(pair)[:2]==['A','B'] for pair in exported.values())
    serialized=json.loads(json.dumps(exported))
    assert all(list(pair)[:2]==['A','B'] for pair in serialized.values())
