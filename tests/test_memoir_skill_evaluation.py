"""Evaluation coverage and evidence boundaries; no live services are needed."""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from scripts.run_memoir_skill_evaluation import (
    datasets, evaluate, item_id, junit_result, manifest, readback, verify_items,
)


def test_both_datasets_cover_every_registered_skill_and_hide_gold_from_model_packets():
    for name, rows in datasets().items():
        assert {r['input']['skill'] for r in rows} == set(manifest()['skills'])
        assert len({item_id(name, r) for r in rows}) == len(rows)
        for row in rows:
            assert 'expected_output' not in row['input']
            if row['input']['kind'] == 'live_contract':
                assert 'expected' not in row['input']['input']


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


@pytest.mark.parametrize('skill', manifest()['skills'])
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
