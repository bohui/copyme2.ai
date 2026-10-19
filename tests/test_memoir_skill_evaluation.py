"""Evaluation coverage and evidence boundaries; no live services are needed."""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from scripts.run_memoir_skill_evaluation import (
    datasets, evaluate, item_id, junit_result, manifest, readback, verify_items, select_datasets,
)
from apps.api.background_skills import SKILLS


def test_named_datasets_cover_every_skill_and_hide_prompts_and_gold_from_model_packets():
    assert {name.rsplit('/', 1)[-1] for name in datasets()} == set(manifest()['skills'])
    for name, rows in datasets().items():
        assert {r['input']['skill'] for r in rows} == {name.rsplit('/', 1)[-1]}
        assert len({item_id(name, r) for r in rows}) == len(rows)
        for row in rows:
            assert 'expected_output' not in row['input']
            assert 'instructions' not in row['input']
            if row['input']['kind'] == 'live_contract':
                assert 'expected' not in row['input']['packet']


@pytest.mark.parametrize('mutation', ['input', 'gold', 'status', 'extra', 'missing'])
def test_hosted_dataset_conflicts_and_partial_readback_cannot_dispatch(mutation):
    name, rows = next(iter(datasets().items()))
    items = [SimpleNamespace(id=item_id(name, row), input=deepcopy(row['input']),
        expected_output=deepcopy(row['expected_output']), status='ACTIVE') for row in rows]
    verify_items(name, rows, items, complete=True)
    if mutation == 'input':
        items[0].input['selectors'] = ['arbitrary-command']
    elif mutation == 'gold':
        items[0].expected_output['status'] = 'failed'
    elif mutation == 'status':
        items[0].status = 'ARCHIVED'
    elif mutation == 'extra':
        items.append(SimpleNamespace(id='unreviewed-item', input={'case_id': 'unreviewed'}))
    else:
        items.pop()
    with pytest.raises(ValueError):
        verify_items(name, rows, items, complete=True)


@pytest.mark.parametrize('child,code,expected', [('', 0, 'passed'), ('<skipped/>', 0, 'unavailable'),
    ('<failure/>', 1, 'failed'), ('<error/>', 1, 'failed'), ('', 2, 'unavailable')])
def test_junit_needs_executed_assertions_and_no_skips(tmp_path, child, code, expected):
    path = tmp_path / 'junit.xml'
    path.write_text('<testsuites><testsuite><testcase>' + child + '</testcase></testsuite></testsuites>')
    assert junit_result(path, code)['status'] == expected
    path.write_text('<testsuites/>')
    assert junit_result(path, 0)['status'] == 'unavailable'


def test_unavailable_and_failed_checks_cannot_earn_numeric_credit():
    unavailable = evaluate(output=dict(status='unavailable', reason='provider_timeout'))
    assert unavailable.name == 'availability' and unavailable.value == 'unavailable'
    assert unavailable.data_type == 'CATEGORICAL'
    failed = evaluate(output=dict(status='failed', evidence='controlled assertions'))
    assert failed.value == 0
    assert evaluate(output=dict(status='passed', evidence='verified completion')).value == 1


@pytest.mark.parametrize('skill', sorted(SKILLS))
def test_current_registry_requires_the_real_trigger_and_rejects_unbound_skills(monkeypatch, skill):
    from apps.api.background_skills import SKILLS, SkillUnavailable, admit
    monkeypatch.setenv('MEMORY_SPARK_HISTORICAL_NEWS', '1')
    definition = SKILLS[skill]
    if skill == 'memoir-family-tree':
        with pytest.raises(SkillUnavailable, match='unwired|unavailable'):
            admit(skill, definition.trigger)
    else:
        assert admit(skill, definition.trigger).runner is not None
    with pytest.raises(SkillUnavailable):
        admit(skill, 'unrelated_user_request')


@pytest.mark.parametrize('count,scored,cursor,expected', [
    (8, 8, None, 'pending'), (9, 8, None, 'pending'),
    (9, 9, 'more-items', 'pending'), (9, 9, None, 'verified')])
def test_langfuse_readback_requires_every_item_and_score(count, scored, cursor, expected):
    response = SimpleNamespace(data=[SimpleNamespace(scores=[1] if i < scored else [])
        for i in range(count)], meta=SimpleNamespace(cursor=cursor))
    client = SimpleNamespace(api=SimpleNamespace(experiments=SimpleNamespace(
        list_items=lambda **kwargs: response)))
    assert readback(client, 'experiment', 9, datetime.now(timezone.utc))['status'] == expected


@pytest.mark.parametrize('execute', [False, True])
@pytest.mark.parametrize('phase,case', [
    ('triggers', 'memoir-place-photo-research-native-discovery'),
    ('deliveries', 'memoir-place-photo-research-triggers'),
])
def test_case_from_another_phase_is_rejected_before_service_allocation(tmp_path, monkeypatch, capsys, execute, phase, case):
    import sys
    import scripts.run_memoir_skill_evaluation as evaluation

    rows = next(iter(select_datasets(datasets(), phase='triggers').values()))
    allocated = []
    client = SimpleNamespace(api=SimpleNamespace(projects=SimpleNamespace(get=lambda:
        SimpleNamespace(data=[SimpleNamespace(id='cmut9t75w00071z02n8bdv7it')]))))
    monkeypatch.setattr(evaluation, 'prompt_client', lambda *args: allocated.append('langfuse') or client)
    monkeypatch.setattr('scripts.export_langfuse_prompts.export_prompts', lambda *args, **kwargs: [])
    monkeypatch.setattr(evaluation, 'publish_datasets', lambda *args: (
        {'memoir/evaluation/skills/memoir-author-timeline': SimpleNamespace(items=[
            SimpleNamespace(input=row['input']) for row in rows])}, datetime.now(timezone.utc)))
    monkeypatch.setattr(evaluation, 'TracedProvider', lambda *args, **kwargs: SimpleNamespace())
    env = tmp_path / 'empty.env'
    env.write_text('')
    monkeypatch.setattr(sys, 'argv', ['run_memoir_skill_evaluation.py', '--phase', phase,
        '--case', case, '--env-file', str(env),
        '--output-root', str(tmp_path / 'results'), *(['--execute'] if execute else [])])
    try:
        status = evaluation.main()
    except SystemExit as error:
        status = error.code
    assert status == 2, 'A phase selecting zero cases must not report success'
    assert allocated == []
    assert not (tmp_path / 'results').exists()
    assert 'phase' in capsys.readouterr().err.lower()


def test_an_empty_experiment_cannot_report_passed(tmp_path, monkeypatch):
    import json
    import sys
    import scripts.run_memoir_skill_evaluation as evaluation

    name = 'memoir/evaluation/skills/memoir-author-timeline'
    monkeypatch.setattr(evaluation, 'datasets', lambda: {name: []})
    client = SimpleNamespace(api=SimpleNamespace(projects=SimpleNamespace(get=lambda:
        SimpleNamespace(data=[SimpleNamespace(id='cmut9t75w00071z02n8bdv7it')]))))
    monkeypatch.setattr(evaluation, 'prompt_client', lambda *args: client)
    monkeypatch.setattr('scripts.export_langfuse_prompts.export_prompts', lambda *args, **kwargs: [])
    monkeypatch.setattr(evaluation, 'publish_datasets', lambda *args:
        ({name: SimpleNamespace(items=[])}, datetime.now(timezone.utc)))
    monkeypatch.setattr(evaluation, 'TracedProvider', lambda *args, **kwargs: SimpleNamespace())
    env = tmp_path / 'empty.env'
    env.write_text('')
    output = tmp_path / 'results'
    monkeypatch.setattr(sys, 'argv', ['run_memoir_skill_evaluation.py', '--execute', '--phase', 'triggers',
        '--env-file', str(env), '--output-root', str(output)])
    assert evaluation.main() == 1
    receipt, = output.glob('*/receipt.json')
    result = json.loads(receipt.read_text())
    assert result['status'] == 'incomplete'
    assert result['results'] == result['experiments'] == []
