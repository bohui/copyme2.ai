"""PR93 experiment IO checks, retaining PR92 metadata/version/receipt boundaries."""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from scripts import memoir_skill_eval_assets as assets
from scripts.memoir_skill_eval_suite import digest, plan


def binding():
    row = dict(item_id='stable-item', dataset='memoir/evaluation/skills/memoir-interviewer', dataset_id='dataset-id',
        dataset_snapshot='2026-10-19T00:00:00+00:00', trace_id='trace', observation_id='generation',
        input={'task': 'synthetic'}, expected_output={'action': 'deliver'}, output={'question': 'What happened next?'},
        item_metadata=dict(locale='en-AU', expected_action='deliver', content_sha256='c'*64),
        evaluators=[dict(name='skill/quality', version=2, compiled_sha256='d'*64, value='pass')])
    return {**row, 'input_sha256': digest(row['input']), 'output_sha256': digest(row['output'])}


def sdk_item(wanted):
    return dict(id='result', traceId='trace', startTime='2026-10-19T00:00:00Z', level='DEFAULT', environment='default',
        experimentId='experiment', experimentName='synthetic', experimentItemId=wanted['item_id'],
        experimentDatasetId=wanted['dataset_id'], input=deepcopy(wanted['input']),
        expectedOutput=deepcopy(wanted['expected_output']), output=deepcopy(wanted['output']),
        experimentMetadata={k: wanted[k] for k in ('dataset', 'dataset_snapshot')},
        experimentItemMetadata=deepcopy(wanted['item_metadata']), scores=[dict(
            id='score', projectId='synthetic-project', name='skill/quality', source='API',
            timestamp='2026-10-19T00:00:00Z', createdAt='2026-10-19T00:00:00Z', updatedAt='2026-10-19T00:00:00Z',
            environment='default', dataType='CATEGORICAL', value='pass',
            subject=dict(kind='observation', id='generation', traceId='trace'),
            metadata=dict(evaluator_version=2, compiled_sha256='d'*64, output_sha256=digest(wanted['output'])))])


class Boundary:
    def __init__(self, pages):
        self.calls, self.pages = [], list(pages)
        self.api = SimpleNamespace(experiments=SimpleNamespace(list_items=self.read))

    def read(self, **kwargs):
        from langfuse.api.experiments.types import ExperimentItemsResponse
        from langfuse.api.core.pydantic_utilities import parse_obj_as
        self.calls.append(kwargs)
        return parse_obj_as(type_=ExperimentItemsResponse, object_=self.pages.pop(0))


@pytest.mark.parametrize('mutation', ['none', 'input', 'gold', 'output', 'metadata', 'dataset', 'snapshot',
    'trace', 'observation', 'value', 'duplicate_score', 'missing_score', 'version', 'compiled'])
def test_sdk_readback_matches_actual_payloads_metadata_and_scores(mutation):
    wanted = binding(); item = sdk_item(wanted)
    if mutation in {'input', 'output'}: item[mutation] = {'foreign': True}
    elif mutation == 'gold': item['expectedOutput'] = {'action': 'pause'}
    elif mutation == 'metadata': item['experimentItemMetadata']['locale'] = 'zh-CN'
    elif mutation == 'dataset': item['experimentDatasetId'] = 'foreign-dataset'
    elif mutation == 'snapshot': item['experimentMetadata']['dataset_snapshot'] = '2026-10-20T00:00:00Z'
    elif mutation == 'trace': item['traceId'] = 'foreign-trace'
    elif mutation == 'observation': item['scores'][0]['subject']['id'] = 'foreign-generation'
    elif mutation == 'value': item['scores'][0]['value'] = 'fail'
    elif mutation == 'duplicate_score': item['scores'] *= 2
    elif mutation == 'missing_score': item['scores'] = []
    elif mutation == 'version': item['scores'][0]['metadata']['evaluator_version'] = 3
    elif mutation == 'compiled': item['scores'][0]['metadata']['compiled_sha256'] = 'foreign'
    client = Boundary([dict(data=[item], meta=dict(cursor=None))])
    result = assets.read_experiment_scores(client, 'experiment', [wanted], started_at=datetime(2026, 10, 19, tzinfo=timezone.utc))
    assert result['status'] == ('verified' if mutation == 'none' else 'incomplete'), result
    assert client.calls[0]['fields'] == 'core,dataset,io,itemMetadata,experimentMetadata,scores'


@pytest.mark.parametrize('mode', ['complete', 'empty', 'bounded', 'duplicate'])
def test_sdk_pagination_is_bounded_and_empty_or_duplicate_items_never_verify(mode):
    wanted = binding(); item = sdk_item(wanted)
    pages = [dict(data=[], meta=dict(cursor='page2')), dict(data=[item], meta=dict(cursor=None))]
    if mode == 'empty': pages = [dict(data=[], meta=dict(cursor=None))]
    if mode == 'duplicate': pages = [dict(data=[item], meta=dict(cursor='page2')), dict(data=[item], meta=dict(cursor=None))]
    client = Boundary(pages)
    result = assets.read_experiment_scores(client, 'experiment', [wanted], max_pages=1 if mode == 'bounded' else 2,
        started_at=datetime(2026, 10, 19, tzinfo=timezone.utc))
    assert result['status'] == ('verified' if mode == 'complete' else 'incomplete'), result
    assert len(client.calls) <= (1 if mode == 'bounded' else 2)


def test_metadata_only_revision_is_a_reviewable_write_and_exact_readback():
    from test_skill_eval_assets import Store, publish
    rows = assets.dataset_rows(plan(skill=['memoir-interviewer']))
    name = 'memoir/evaluation/skills/memoir-interviewer'
    rows = {name: rows[name]}
    store = Store(); publish(store, rows)
    identity = rows[name][0]['id']
    rows[name][0]['metadata'].update(locale='zh-CN', expected_action='pause', content_sha256='e'*64)
    reviewed = assets.preflight(store, rows, snapshot=store.snapshot())
    assert len(reviewed['operations']) == 1 and reviewed['operations'][0]['id'] == identity
    assets.reconcile(store, reviewed, review_sha256=reviewed['review_sha256'])
    actual = next(r for r in store.read_dataset(name, snapshot=None)['items'] if r['id'] == identity)
    assert actual['metadata'] == rows[name][0]['metadata']


def test_sdk_readback_rejects_inconsistent_expected_hashes_before_reading():
    wanted = binding(); wanted['output_sha256'] = 'foreign'
    client = Boundary([])
    result = assets.read_experiment_scores(client, 'experiment', [wanted],
        started_at=datetime(2026, 10, 19, tzinfo=timezone.utc))
    assert result == dict(status='incomplete', reason='expected_payload_binding_mismatch')
    assert not client.calls
