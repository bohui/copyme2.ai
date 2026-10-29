"""Controlled Langfuse/completion boundary tests; no SDK or hosted writes."""
import asyncio
from copy import deepcopy
import json

import pytest

from scripts import memoir_skill_eval_assets as assets
from scripts import memoir_skill_eval_suite as suite


class Store:
    def __init__(self):
        self.datasets = {}
        self.writes = []
        self.fail_after = None

    def read_dataset(self, name, *, snapshot):
        return deepcopy(self.datasets.get(name))

    def snapshot(self):
        return '2026-10-19T00:00:00+00:00'

    def create_dataset(self, name, value, *, expected_absent):
        if expected_absent and name in self.datasets: raise ValueError('concurrent_dataset_creation')
        self.writes.append(name)
        self.datasets[name] = value

    def upsert_item(self, name, key, value, *, expected_sha256):
        if self.fail_after is not None and len(self.writes) >= self.fail_after:
            raise OSError('controlled partial write')
        self.writes.append(key)
        items = self.datasets[name]['items']
        prior = next((r for r in items if r['id'] == key), None)
        if suite.digest(prior) != expected_sha256: raise ValueError('concurrent_item_update')
        items[:] = [r for r in items if r['id'] != key] + [value]


def desired():
    planned = suite.plan(skill=['memoir-interviewer'], locale=['en-AU'])
    name = planned['items'][0]['dataset']
    return {name: assets.dataset_rows(planned)[name]}


def publish(store, rows):
    reviewed = assets.preflight(store, rows, snapshot=store.snapshot())
    return assets.reconcile(store, reviewed, review_sha256=reviewed['review_sha256'])


def test_stable_updates_retirements_retry_and_readback():
    store = Store()
    rows = desired()
    assert publish(store, rows)['status'] == 'verified'
    assert publish(store, rows)['writes'] == []
    name = next(iter(rows))
    old_key = rows[name][0]['id']
    rows[name][0]['input']['task']['instruction'] += ' Reviewed change.'
    retired = rows[name].pop()
    reviewed = assets.preflight(store, rows, snapshot=store.snapshot())
    assert {r['kind'] for r in reviewed['operations']} == {'upsert_item', 'archive_item'}
    assets.reconcile(store, reviewed, review_sha256=reviewed['review_sha256'])
    current = {r['id']: r for r in store.datasets[name]['items']}
    assert current[old_key]['input'] == rows[name][0]['input']
    assert current[retired['id']]['status'] == 'ARCHIVED'
    assert assets.preflight(store, rows, snapshot=store.snapshot())['operations'] == []


def test_partial_writes_resume_without_duplicates_and_do_not_rewrite_history():
    store = Store()
    rows = desired()
    store.datasets['historical-v2'] = dict(items=[dict(id='old-experiment')])
    store.fail_after = 3
    with pytest.raises(OSError): publish(store, rows)
    assert len(store.datasets[next(iter(rows))]['items']) == 2
    store.fail_after = None
    publish(store, rows)
    assert len(store.datasets[next(iter(rows))]['items']) == 16
    assert store.datasets['historical-v2'] == dict(items=[dict(id='old-experiment')])
    with pytest.raises(ValueError, match='historical'): publish(store, {'historical-v2': []})


@pytest.mark.parametrize('mutation', ['unreviewed', 'concurrent', 'ownership', 'readback'])
def test_conflicts_fail_closed_without_unreviewed_writes(mutation):
    store, rows = Store(), desired()
    publish(store, rows)
    name = next(iter(rows))
    rows[name][0]['input']['task']['instruction'] += ' Update.'
    reviewed = assets.preflight(store, rows, snapshot=store.snapshot())
    before = len(store.writes)
    if mutation == 'unreviewed': reviewed['operations'][0]['value']['status'] = 'ARCHIVED'
    elif mutation == 'concurrent': store.datasets[name]['items'][0]['status'] = 'ARCHIVED'
    elif mutation == 'ownership':
        store.datasets[name]['synthetic'] = False
        with pytest.raises(ValueError, match='ownership'):
            assets.preflight(store, rows, snapshot=store.snapshot())
        return
    else:
        original = store.upsert_item
        def corrupt(*args, **kwargs):
            original(*args, **kwargs)
            store.datasets[name]['items'][-1]['status'] = 'ARCHIVED'
        store.upsert_item = corrupt
    with pytest.raises(ValueError):
        assets.reconcile(store, reviewed, review_sha256=reviewed['review_sha256'])
    if mutation != 'readback': assert len(store.writes) == before


def score_pair():
    expected = dict(item_id='item', dataset='synthetic', dataset_snapshot='2026-10-19T00:00:00Z',
        input_sha256='a'*64, output_sha256='b'*64, trace_id='trace', observation_id='generation',
        evaluators=[dict(name='skill/quality', version=2, compiled_sha256='c'*64, value='pass')])
    actual = {**deepcopy(expected), 'scores': [dict(name='skill/quality', evaluator_version=2,
        compiled_sha256='c'*64, trace_id='trace', observation_id='generation', output_sha256='b'*64, value='pass')]}
    return actual, expected


@pytest.mark.parametrize('mutation', ['none', 'empty', 'item', 'input', 'output', 'trace', 'observation', 'score', 'version', 'compiled', 'duplicate', 'value', 'missing_value'])
def test_score_counts_cannot_substitute_for_exact_identities(mutation):
    actual, expected = score_pair()
    if mutation == 'empty':
        assert assets.score_readback([], [])['status'] == 'incomplete'
        return
    if mutation in {'item', 'input', 'output', 'trace', 'observation'}:
        field = dict(item='item_id', input='input_sha256', output='output_sha256',
                     trace='trace_id', observation='observation_id')[mutation]
        actual[field] = 'foreign'
    elif mutation == 'score': actual['scores'][0]['name'] = 'unrelated'
    elif mutation == 'version': actual['scores'][0]['evaluator_version'] = 3
    elif mutation == 'compiled': actual['scores'][0]['compiled_sha256'] = 'd'*64
    elif mutation == 'duplicate': actual['scores'] *= 2
    elif mutation == 'value': actual['scores'][0]['value'] = 'fail'
    elif mutation == 'missing_value': actual['scores'][0].pop('value')
    assert assets.score_readback([actual], [expected])['status'] == ('verified' if mutation == 'none' else 'incomplete')


def test_numeric_score_does_not_accept_a_boolean_as_the_expected_value():
    actual, expected = score_pair()
    expected['evaluators'][0]['value'] = 1
    actual['scores'][0]['value'] = True
    assert assets.score_readback([actual], [expected])['status'] == 'incomplete'


@pytest.mark.parametrize('value,status', [(1.0, 'verified'), (0.0, 'incomplete'), (float('nan'), 'incomplete')])
def test_numeric_score_readback_accepts_sdk_float_without_accepting_wrong_values(value, status):
    actual, expected = score_pair()
    expected['evaluators'][0]['value'] = 1
    actual['scores'][0]['value'] = value
    assert assets.score_readback([actual], [expected])['status'] == status


def test_real_judge_adapter_handles_injection_as_data_and_draft_pin_gate(tmp_path):
    requests = []
    class Transport:
        async def complete(self, request):
            requests.append(request)
            return dict(text=json.dumps(dict(status='pass', citations=['output'], rationale='The supplied grouping output is supported.',
                critical_violations=[])), response_id='actual-transport-id', model='independent-fixture', usage=None)
    adapter = assets.IndependentJudgeAdapter(Transport(), controlled=True)
    planned = suite.plan(skill=['memoir-place-groups'], locale=['en-AU'])
    receipt = asyncio.run(suite.run(planned, tmp_path, sdk_judge=adapter, max_judge_calls=1))
    assert receipt['results'][0]['quality']['status'] == 'pass'
    assert receipt['budgets']['judge']['dispatched'] == 1
    assert requests[0]['store'] is False
    assert 'critical' in requests[0]['instructions']
    assert 'gold' in requests[0]['input']
    with pytest.raises(ValueError, match='published'):
        asyncio.run(assets.IndependentJudgeAdapter(Transport()).call(dict(publication='unpublished')))


def test_malformed_judge_text_and_missing_evidence_are_unavailable(tmp_path):
    class Transport:
        async def complete(self, request):
            return dict(text='not JSON', response_id='fixture', model='fixture')
    receipt = asyncio.run(suite.run(suite.plan(skill=['memoir-place-groups']), tmp_path,
        sdk_judge=assets.IndependentJudgeAdapter(Transport(), controlled=True), max_judge_calls=1))
    assert receipt['results'][0]['quality']['status'] == 'unavailable'
    assert receipt['results'][1]['quality']['reason'] == 'judge_budget_exhausted'


def test_scoped_execution_never_archives_unselected_items_and_shared_assets_are_nonempty():
    rows = assets.dataset_rows(suite.plan(skill=['memoir-interviewer'], locale=['en-AU']))
    assert sum(len(items) for name, items in rows.items() if name.startswith(assets.DATASET_PREFIX)) == 160
    assert len(rows['memoir/evaluation/workflows']) == 2
    assert len(rows['memoir/evaluation/judge-calibration']) == 20
    assert all(r['expected_output']['human_label'] is None for r in rows['memoir/evaluation/judge-calibration'])


def test_managed_rules_are_disabled_synthetic_only_and_sdk_does_not_schedule_judges():
    planned = suite.plan()
    managed = assets.managed_assets(planned, executor='managed')
    sdk = assets.managed_assets(planned, executor='sdk')
    assert len(managed['definitions']) == len(managed['rules']) == 20
    assert len(sdk['rules']) == 10
    assert all(not r['enabled'] and r['synthetic_only'] and r['dataset'].startswith(assets.DATASET_PREFIX)
               for r in managed['rules'])


def test_judge_sources_use_main_publisher_and_require_runtime_receipts(tmp_path):
    from scripts.prompt_registry import prompt_registry, EVALUATION_PROMPT_PATHS
    from apps.api.prompt_artifact import load_prompt_artifact
    ordinary = prompt_registry()
    publishing = prompt_registry(include_unpublished=True)
    assert len(EVALUATION_PROMPT_PATHS) == 12
    for name, relative in EVALUATION_PROMPT_PATHS.items():
        assert publishing[name] == relative
        source = suite.ROOT / relative
        assert (name in ordinary) is source.with_name(source.name + '.langfuse.json').is_file()
        unpublished = tmp_path / source.name
        unpublished.write_text(source.read_text())
        with pytest.raises(ValueError, match='receipt'):
            load_prompt_artifact(unpublished)
