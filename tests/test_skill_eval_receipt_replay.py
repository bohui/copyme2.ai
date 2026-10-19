"""A real prior native receipt cannot establish delivery in another run."""
import asyncio
from copy import deepcopy
import json

import pytest

from scripts import memoir_skill_eval_suite as suite
from scripts.memoir_skill_eval_application import ControlledApplication, verify_witness


@pytest.fixture(scope='module')
def prior_native(tmp_path_factory):
    directory = tmp_path_factory.mktemp('native-replay-origin')
    planned = suite.plan(case=['memoir-author-timeline/exact-testimony/en-AU'])
    receipt = asyncio.run(suite.run(planned, directory, application=ControlledApplication(), max_skill_calls=8))
    row, = receipt['results']
    assert row['contract']['status'] == 'pass', row
    assert row['canonical_delivery'] and receipt['budgets']['skill']['dispatched'] > 0
    return planned, receipt, row


@pytest.mark.parametrize('allowance,rebind', [(0, False), (8, False), (8, True)])
def test_replayed_or_rebound_native_receipt_cannot_pass_a_fresh_run(tmp_path, prior_native, allowance, rebind):
    planned, previous, old_row = prior_native
    class Replay:
        calls = 0
        def supports(self, item): return True
        async def execute(self, item, budget, directory, context):
            self.calls += 1
            witness = deepcopy(old_row['witnesses'])
            if rebind:
                witness['readback']['context'].update(context)
                witness['run_id'] = context['run_id']
                witness['receipt_sha256'] = suite.digest(witness['readback'])
            path = directory / witness['receipt_path']
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(witness['readback']))
            return deepcopy(old_row['output']), witness
    adapter = Replay()
    result = asyncio.run(suite.run(deepcopy(planned), tmp_path, application=adapter, max_skill_calls=allowance))
    row, = result['results']
    assert result['run_id'] != previous['run_id']
    assert row['contract']['status'] != 'pass', row
    assert not row.get('canonical_delivery') and not row['positive_delivery']
    assert result['budgets']['skill']['dispatched'] == 0
    if allowance == 0: assert adapter.calls == 0


@pytest.mark.parametrize('field', ['source_revision', 'source_content_sha256'])
def test_hosted_contract_rejects_receipt_root_source_tampering(tmp_path, field):
    planned = suite.plan(case=['memoir-place-groups/child-pin/en-AU'])
    result = asyncio.run(suite.run(planned, tmp_path))
    row, = result['results']; item, = planned['items']
    assert suite.hosted_contract(item, row['output'], row['binding'], result)['status'] == 'pass'
    stale = deepcopy(result); stale[field] = 'foreign-source'
    assert suite.hosted_contract(item, row['output'], row['binding'], stale)['status'] == 'unavailable'


@pytest.mark.parametrize('field', ['run_id', 'source_revision', 'source_content_sha256', 'invocation_id'])
def test_rewritten_receipt_context_is_checked_against_the_runner_context(tmp_path, prior_native, field):
    planned, receipt, row = prior_native
    witness = deepcopy(row['witnesses'])
    witness['readback']['context'][field] = 'tampered'
    witness['run_id'] = witness['readback']['context']['run_id']
    witness['receipt_sha256'] = suite.digest(witness['readback'])
    path = tmp_path / witness['receipt_path']; path.parent.mkdir(parents=True)
    path.write_text(json.dumps(witness['readback']))
    with pytest.raises(ValueError, match='application_current_context_mismatch'):
        verify_witness(planned['items'][0], row['output'], witness, tmp_path,
            expected_context=row['application_context'], dispatches=receipt['budgets']['skill']['calls'])


@pytest.mark.parametrize('mode', ['missing', 'partial', 'tampered'])
def test_current_dispatch_ledger_is_required_even_for_matching_context(tmp_path, prior_native, mode):
    planned, receipt, row = prior_native
    witness = deepcopy(row['witnesses']); calls = deepcopy(receipt['budgets']['skill']['calls'])
    if mode == 'missing': calls = []
    elif mode == 'partial': calls = calls[:-1]
    else:
        witness['readback']['dispatches'][0]['invocation_id'] = 'stale-dispatch'
        witness['receipt_sha256'] = suite.digest(witness['readback'])
    path = tmp_path / witness['receipt_path']; path.parent.mkdir(parents=True)
    path.write_text(json.dumps(witness['readback']))
    with pytest.raises(ValueError, match='application_current_dispatch_receipt_required'):
        verify_witness(planned['items'][0], row['output'], witness, tmp_path,
            expected_context=row['application_context'], dispatches=calls)


def test_runner_deadline_prevents_even_an_injected_application_adapter(tmp_path):
    class Clock:
        value = 0
        def __call__(self):
            self.value += 10
            return self.value
    class Forbidden:
        def supports(self, item): return True
        async def execute(self, *args): pytest.fail('Expired run dispatched the adapter')
    result = asyncio.run(suite.run(suite.plan(case=['memoir-author-timeline/exact-testimony/en-AU']),
        tmp_path, application=Forbidden(), seconds=1, clock=Clock()))
    row, = result['results']
    assert row['reason'] == 'skill_deadline_exhausted' and not row['canonical_delivery']
    assert result['budgets']['skill']['dispatched'] == 0


def test_partial_native_execution_keeps_its_consumed_dispatch_budget(tmp_path):
    result = asyncio.run(suite.run(suite.plan(case=['memoir-author-timeline/exact-testimony/en-AU']),
        tmp_path, application=ControlledApplication(), max_skill_calls=1))
    row, = result['results']
    assert row['contract']['status'] != 'pass' and not row['canonical_delivery']
    assert not row['positive_delivery'] and result['budgets']['skill']['dispatched'] == 1


def test_application_cannot_fall_back_to_an_unwitnessed_model_proposal(tmp_path):
    from test_interview_strategy import wire
    class Unwitnessed:
        def supports(self, item): return True
        async def execute(self, *args): return wire(selection_reason='latest_story'), None
    result = asyncio.run(suite.run(suite.plan(case=['memoir-interviewer/grounded-question/en-AU']),
        tmp_path, application=Unwitnessed()))
    row, = result['results']
    assert row['reason'] == 'independent_application_receipt_required'
    assert row['contract']['status'] == 'unavailable' and not row['positive_delivery'] and not row['canonical_delivery']
