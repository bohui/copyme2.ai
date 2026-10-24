"""Real disposable application persistence, driven through the evaluation CLI."""
import asyncio
from copy import deepcopy
import json
import os

import pytest

from scripts import memoir_skill_eval_suite as suite
from scripts.memoir_skill_eval_application import ControlledApplication, verify_witness


@pytest.mark.parametrize('case', ['proposal', 'webpage', 'missing-consent', 'stale-edition',
                                  'timeline-coverage', 'unsafe-webpage', 'revoked-consent'])
@pytest.mark.parametrize('locale', ['en-AU', 'zh-CN'])
def test_game_phases_use_application_authority_and_independent_sql_readbacks(tmp_path, case, locale):
    planned = suite.plan(case=[f'memoir-story-game/{case}/{locale}'])
    result = asyncio.run(suite.run(planned, tmp_path, application=ControlledApplication(), max_skill_calls=32))
    row, = result['results']
    assert row['contract']['status'] == 'pass', row
    assert row['canonical_delivery'] is (case in {'proposal', 'webpage'})
    assert row['positive_delivery'] is (case in {'proposal', 'webpage'})
    witness = json.loads((tmp_path / row['witnesses']['receipt_path']).read_text())
    assert witness['scope'] == 'controlled_disposable_application'
    assert witness['item_id'] == planned['items'][0]['id']
    assert witness['source_readbacks'] and witness['completed_turns'] == 5
    assert witness['database_removed'] is True
    assert result['budgets']['skill']['dispatched'] >= 5
    assert row['quality']['status'] == 'unavailable'


def test_canonical_turn_receipt_binds_exact_task_output_and_persisted_source(tmp_path):
    planned = suite.plan(case=['memoir-author-timeline/exact-testimony/en-AU'])
    result = asyncio.run(suite.run(planned, tmp_path, application=ControlledApplication(), max_skill_calls=8))
    row, = result['results']
    assert row['contract']['status'] == 'pass', row
    assert row['canonical_delivery'] and row['witnesses']['persisted_canonical_state']
    context = dict(expected_context=row['application_context'], dispatches=result['budgets']['skill']['calls'])
    assert verify_witness(planned['items'][0], row['output'], row['witnesses'], tmp_path, **context)['verified']
    assert row['witnesses']['readback']['source_readbacks'][0]['text'] == planned['items'][0]['task']['source']['text']
    rebound = deepcopy(planned['items'][0])
    rebound['dataset_snapshot'] = '2026-10-20T00:00:00Z'
    with pytest.raises(ValueError): verify_witness(rebound, row['output'], row['witnesses'], tmp_path, **context)
    forged = deepcopy(row['output'])
    forged['canonical_result']['accepted_source_id'] = 'forged-source'
    with pytest.raises(ValueError): verify_witness(planned['items'][0], forged, row['witnesses'], tmp_path, **context)
    receipt_path = tmp_path / row['witnesses']['receipt_path']
    readback = json.loads(receipt_path.read_text())
    readback['source_readbacks'][0]['text'] = 'Forged testimony'
    receipt_path.write_text(json.dumps(readback))
    with pytest.raises(ValueError): verify_witness(planned['items'][0], row['output'], row['witnesses'], tmp_path, **context)


def test_application_budget_exhaustion_retains_every_item(tmp_path):
    planned = suite.plan(skill=['memoir-story-game'], locale=['en-AU'])
    result = asyncio.run(suite.run(planned, tmp_path, application=ControlledApplication(), max_skill_calls=0))
    assert len(result['results']) == 8
    assert result['budgets']['skill']['dispatched'] == 0
    assert all(r['execution'] == 'unavailable' for r in result['results'])


def test_play_without_browser_configuration_is_explicitly_blocked(tmp_path):
    result = asyncio.run(suite.run(suite.plan(case=['memoir-story-game/play/en-AU']),
        tmp_path, application=ControlledApplication()))
    assert result['results'][0]['reason'] == 'browser_origin_required'


@pytest.mark.skipif(not os.getenv('MEMOIR_BROWSER_URL'), reason='Requires isolated source frontend')
@pytest.mark.parametrize('locale', ['en-AU', 'zh-CN'])
def test_play_uses_saved_webpage_in_browser(tmp_path, locale):
    application = ControlledApplication(browser_url=os.environ['MEMOIR_BROWSER_URL'],
        browser_executable=os.getenv('MEMOIR_BROWSER_EXECUTABLE'))
    result = asyncio.run(suite.run(suite.plan(case=[f'memoir-story-game/play/{locale}']),
        tmp_path, application=application, max_skill_calls=32))
    row, = result['results']
    assert row['contract']['status'] == 'pass', row
    witness = json.loads((tmp_path / row['witnesses']['receipt_path']).read_text())
    assert witness['game']['browser']['verified']
    assert witness['game']['browser']['visits'] == ['initial', 'reload', 'new_context']


def test_cli_controlled_canonical_delivery_is_not_live_acceptance(tmp_path):
    from scripts.run_memoir_skill_evaluation import main
    assert main(['--execute', '--controlled-application', '--case',
        'memoir-interviewer/grounded-question/en-AU', '--output-root', str(tmp_path)]) == 1
    receipt = json.loads((tmp_path / 'receipt.json').read_text())
    row, = receipt['results']
    assert row['canonical_delivery']
    assert row['evidence_mode'] == 'controlled_disposable_application' and not row['live_delivery']
    assert row['quality']['status'] == 'unavailable'


def test_nested_supervisor_verifies_all_application_allocations(tmp_path, monkeypatch):
    from scripts.controlled_lifecycle import ALLOCATION_ROOT_ENV, new_native_root, reconcile_native_directory
    from scripts.run_isolated_check import offline_environment
    parent = new_native_root('memoir-controlled-pg-')
    monkeypatch.setenv(ALLOCATION_ROOT_ENV, str(parent))
    result = asyncio.run(suite.run(suite.plan(case=['memoir-interviewer/grounded-question/en-AU']),
        tmp_path, application=ControlledApplication()))
    assert result['results'][0]['canonical_delivery']
    cleanup = reconcile_native_directory(parent, offline_environment(suite.ROOT))
    assert cleanup['verified'] and cleanup['root_removed'] and not parent.exists()
