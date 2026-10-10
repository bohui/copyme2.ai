"""Offline campaign profile admission. No provider or native fixture is started."""
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
from uuid import uuid4

import pytest

from scripts import run_issue14_subscription_evaluation as launcher

FIFTY = 'subscription_fifty'


def plan(**changes):
    binary = Path(sys.executable).resolve()
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    args = dict(run_id=str(uuid4()), source_revision='a' * 40,
        codex_binary=binary, codex_sha256=digest, temporal_binary=binary, temporal_sha256=digest,
        max_client_requests=3000, max_elapsed_seconds=36000,
        evaluation_profile=FIFTY, max_case_client_requests=600, max_case_elapsed_seconds=7200)
    args.update(changes)
    return launcher.build_plan(**args)


def test_explicit_fifty_plan_preserves_original_dataset_order_and_checkpoints(monkeypatch):
    monkeypatch.setattr(launcher, 'configured_credential', lambda: pytest.fail('credential read'))
    p = plan()
    assert p['evaluation_profile'] == FIFTY
    assert p['rounds_per_case'] == 50
    assert p['checkpoints'] == list(range(5, 51, 5))
    assert p['case_ids'] == ['harbour-copper-notebook', 'chengdu-tea-ledger',
        'perth-workshop-compass', 'kunming-garden-lanterns', 'sydney-platform-letters']
    assert [c['language'] for c in p['cases'].values()].count('en-AU') == 3
    assert len({c['owner_id'] for c in p['cases'].values()}) == 5
    assert p['synthetic_entitlement'] == 'disposable_facade_only'
    assert p['max_case_client_requests'] == 600 and p['max_case_elapsed_seconds'] == 7200
    assert p['max_client_requests'] == 3000 and p['max_elapsed_seconds'] == 36000
    assert p['execution_started'] is False and p['upstream_cancellation_verified'] is False
    assert p['hard_token_cap_verified'] is p['hard_dollar_cap_verified'] is False
    assert p['dataset_version'] == 'memoir-five-case/1'
    assert p['dataset_sha256'] == 'e7f705bc4a96537b01cb5cde7d412972bdd929de49d339bc6b1a95bc9cb43927'


@pytest.mark.parametrize('changes', [
    {'evaluation_profile': 'fifty'}, {'max_case_client_requests': None},
    {'max_case_elapsed_seconds': None}, {'max_case_client_requests': 601},
    {'max_case_client_requests': True}, {'max_case_elapsed_seconds': 7201},
    {'max_case_elapsed_seconds': float('inf')}, {'max_client_requests': 3001},
    {'max_elapsed_seconds': 36001}, {'max_case_client_requests': 0},
    {'max_case_elapsed_seconds': 0},
])
def test_fifty_plan_requires_explicit_bounded_profile(changes):
    with pytest.raises(ValueError):
        plan(**changes)


def test_historical_profile_cannot_silently_inherit_fifty_bounds():
    with pytest.raises(ValueError):
        plan(evaluation_profile='subscription_progressive')
    with pytest.raises(ValueError):
        plan(evaluation_profile='subscription_progressive', max_client_requests=160,
             max_elapsed_seconds=1800)


def test_fifty_entitlement_is_synthetic_owner_scoped_and_product_cap_unchanged(monkeypatch):
    from scripts.memoir_subscription_profiles import profile_for
    from apps.api.recall import free_recall_rounds, recall_status
    from apps.api.family_context import family_features_enabled
    monkeypatch.delenv('MEMORY_SPARK_FREE_RECALL_ROUNDS', raising=False)
    p = plan()
    config = profile_for(FIFTY)
    values = [config.entitlement(c, 50) for c in p['cases'].values()]
    assert len({v['user_id'] for v in values}) == 5
    assert all(v['status'] == 'paid' and v['plan_key'] == 'family_memoir_v1' for v in values)
    assert all(recall_status(50, v)['payment_required'] is False for v in values)
    assert all(family_features_enabled(v, 'synthetic-memoir-fifty-price') is True for v in values)
    assert all(v['stripe_price_id'] == 'synthetic-memoir-fifty-price' for v in values)
    assert free_recall_rounds() == 20 and recall_status(20, None)['payment_required'] is True
    assert profile_for('subscription_progressive').entitlement(next(iter(p['cases'].values()))) is None
    chinese = next(c for c in p['cases'].values() if c['language'] == 'zh-CN')
    assert config.entitlement(chinese, 15) is None
    assert family_features_enabled(config.entitlement(chinese, 16), 'synthetic-memoir-fifty-price') is True
    values[0]['status'] = 'changed'
    assert config.entitlement(next(iter(p['cases'].values())))['status'] == 'paid'


def test_modified_fifty_plan_fails_before_native_or_output_allocation(tmp_path, monkeypatch):
    import asyncio
    p = plan()
    p['checkpoints'] = [50]
    monkeypatch.setattr(launcher, 'native_resources', lambda *a, **k: pytest.fail('allocated'))
    with pytest.raises(ValueError, match='Exact freshly validated'):
        asyncio.run(launcher.execute_native(p, tmp_path / 'run', 'synthetic-token'))
    assert not (tmp_path / 'run').exists()


def test_fifty_plan_only_never_reads_provider_env_or_allocates(tmp_path, monkeypatch):
    p = plan()
    monkeypatch.setattr(launcher, 'load_existing_application_env', lambda *a: pytest.fail('env read'))
    monkeypatch.setattr(launcher, 'configured_credential', lambda *a: pytest.fail('credential read'))
    monkeypatch.setattr(launcher, 'execute_native', lambda *a: pytest.fail('native allocated'))
    args = ['--evaluation-profile', FIFTY, '--run-id', p['run_id'],
        '--source-revision', p['source_revision'], '--run-dir', str(tmp_path / 'run'),
        '--max-client-requests', '3000', '--max-elapsed-seconds', '36000',
        '--max-case-client-requests', '600', '--max-case-elapsed-seconds', '7200',
        '--codex-binary', p['codex_binary'], '--codex-sha256', p['codex_sha256'],
        '--temporal-binary', p['temporal_binary'], '--temporal-sha256', p['temporal_sha256'],
        '--existing-app-env', str(tmp_path / 'not-read')]
    assert launcher.main(args) == 0
    assert not (tmp_path / 'run').exists()


def test_public_photo_profile_requires_explicit_existing_interpreter_pin():
    binary = Path(sys.executable).resolve()
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        plan(enable_public_photo_research=True)
    p = plan(enable_public_photo_research=True, photo_python_binary=binary, photo_python_sha256=digest)
    assert p['photo_research']['enabled'] is True
    assert p['photo_research']['llm_search_enabled'] is False
    assert p['photo_research']['max_searches_per_case'] == 2
    assert p['photo_research']['max_searches_global'] == 10
    assert p['photo_research']['counted_in_model_gateway_requests'] is False
    assert p['photo_research']['real_storage_writes'] is False
    with pytest.raises(ValueError):
        plan(enable_public_photo_research=False, photo_python_binary=binary, photo_python_sha256=digest)


def test_fifty_source_inventory_failure_blocks_before_any_native_or_credential_action(tmp_path, monkeypatch):
    import scripts.issue14_subscription_source_contract_v6 as source
    p = plan()
    monkeypatch.setattr(launcher, 'verify_source', lambda revision: None)
    def fail(root):
        raise ValueError('source mismatch')
    monkeypatch.setattr(source, 'audit_subscription_source_v6', fail)
    monkeypatch.setattr(launcher, 'configured_credential', lambda: pytest.fail('credential read'))
    monkeypatch.setattr(launcher, 'execute_native', lambda *a: pytest.fail('native allocated'))
    args = ['--execute-existing-subscription', '--evaluation-profile', FIFTY,
        '--run-id', p['run_id'], '--source-revision', p['source_revision'], '--run-dir', str(tmp_path / 'run'),
        '--max-client-requests', '3000', '--max-elapsed-seconds', '36000',
        '--max-case-client-requests', '600', '--max-case-elapsed-seconds', '7200',
        '--codex-binary', p['codex_binary'], '--codex-sha256', p['codex_sha256'],
        '--temporal-binary', p['temporal_binary'], '--temporal-sha256', p['temporal_sha256']]
    assert launcher.main(args) == 3
    assert not (tmp_path / 'run').exists()


def test_fifty_initial_profile_uses_real_initialized_locale_to_avoid_getter_backfill():
    from apps.api.conversation_locale import state
    for case in plan()['cases'].values():
        value = launcher.native_case_profile(case, FIFTY)
        assert state(value)['initialized'] is True
        assert state(value)['locale'] == case['language']
        assert value['preferred_language'] == case['language']
    historical = launcher.native_case_profile({'language': 'en-AU'}, 'subscription_progressive')
    assert historical == {'preferred_language': 'en-AU', 'conversation_language':
                          {'locale': 'en-AU', 'source': 'explicit', 'revision': 1}}


def test_browser_admission_is_explicit_and_uses_version_bound_validated_config(monkeypatch):
    import scripts.memoir_fifty_browser_runner as browser
    supplied = {'schema_version': 'native-test-config', 'allow_browser_turns': True}
    calls = []
    def validate(value, *, source_revision):
        calls.append((deepcopy(value), source_revision))
        return {**value, 'validated': True}
    monkeypatch.setattr(browser, 'validate_browser_config', validate)
    with pytest.raises(ValueError):
        plan(browser_config=supplied)
    with pytest.raises(ValueError):
        plan(enable_browser_readback=True)
    p = plan(enable_browser_readback=True, browser_config=supplied)
    assert p['browser_readback'] == {**supplied, 'validated': True}
    assert calls == [(supplied, p['source_revision'])]
    assert p['execution_started'] is False
