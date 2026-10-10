"""Development-checkout provenance and admission; no model or native services."""
import asyncio
from contextlib import asynccontextmanager, contextmanager
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

from scripts import run_issue14_subscription_evaluation as launcher


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    root = tmp_path / 'checkout'
    root.mkdir()
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=root, text=True).strip()
    git('init', '-q', '-b', 'codex/local-test')
    git('config', 'user.name', 'Synthetic')
    git('config', 'user.email', 'synthetic@invalid')
    (root / 'runtime.py').write_text('value = 1\n')
    (root / '.gitignore').write_text('.env\n')
    git('add', '.')
    git('commit', '-qm', 'fixture')
    revision = git('rev-parse', 'HEAD')
    (root / 'runtime.py').write_text('value = 2\n')
    (root / 'new.py').write_text('new = True\n')
    (root / '.env').write_text('PRIVATE_KEY=synthetic-secret\n')
    monkeypatch.setattr(launcher, 'ROOT', root)
    return root, revision


def plan(revision, local_source=None):
    binary = Path(sys.executable).resolve()
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    return launcher.build_plan(run_id=str(uuid4()), source_revision=revision,
        codex_binary=binary, codex_sha256=digest, temporal_binary=binary, temporal_sha256=digest,
        evaluation_profile='subscription_fifty', selected_case_ids=('harbour-copper-notebook',),
        collector_timeout_seconds=180, max_client_requests=569, max_elapsed_seconds=7200,
        max_case_client_requests=569, max_case_elapsed_seconds=7200, local_checkout_source=local_source)


def argv(value, directory, *extra):
    return ['--evaluation-profile', 'subscription_fifty', '--case-id', 'harbour-copper-notebook',
        '--run-id', value['run_id'], '--source-revision', value['source_revision'],
        '--run-dir', str(directory), '--codex-binary', value['codex_binary'],
        '--codex-sha256', value['codex_sha256'], '--temporal-binary', value['temporal_binary'],
        '--temporal-sha256', value['temporal_sha256'], '--max-client-requests', '569',
        '--max-elapsed-seconds', '7200', '--max-case-client-requests', '569',
        '--max-case-elapsed-seconds', '7200', '--collector-timeout-seconds', '180', *extra]


def test_snapshot_captures_dirty_branch_and_new_source_but_excludes_private_env(checkout):
    root, revision = checkout
    snapshot = launcher.local_checkout_snapshot(revision)
    assert snapshot['branch'] == 'codex/local-test' and snapshot['dirty'] is True
    assert snapshot['file_count'] == 3
    assert 'synthetic-secret' not in json.dumps(snapshot)
    (root / '.env').write_text('PRIVATE_KEY=changed-secret\n')
    launcher.verify_execution_source(revision, snapshot)
    (root / 'new.py').write_text('new = False\n')
    with pytest.raises(ValueError, match='changed'):
        launcher.verify_execution_source(revision, snapshot)


@pytest.mark.parametrize('change', ['edited', 'deleted', 'added'])
def test_snapshot_rejects_source_changes_after_planning(checkout, change):
    root, revision = checkout
    snapshot = launcher.local_checkout_snapshot(revision)
    if change == 'edited':
        (root / 'runtime.py').write_text('value = 3\n')
    elif change == 'deleted':
        (root / 'runtime.py').unlink()
    else:
        (root / 'another.py').write_text('another = True\n')
    with pytest.raises(ValueError, match='changed'):
        launcher.verify_execution_source(revision, snapshot)


def test_local_revision_must_identify_actual_head(checkout):
    with pytest.raises(ValueError, match='current HEAD'):
        launcher.local_checkout_snapshot('a' * 40)


def test_local_plan_preserves_original_rounds_limits_and_has_no_native_or_credential_access(checkout, tmp_path, monkeypatch, capsys):
    _, revision = checkout
    monkeypatch.setattr(launcher, 'configured_credential', lambda: pytest.fail('Credential access'))
    monkeypatch.setattr(launcher, 'execute_native', lambda *a: pytest.fail('Native allocation'))
    value = plan(revision)
    directory = tmp_path / 'unallocated'
    assert launcher.main(argv(value, directory, '--local-checkout')) == 0
    observed = json.loads(capsys.readouterr().out)
    assert observed['local_checkout_source'] == launcher.local_checkout_snapshot(revision)
    assert observed['rounds_per_case'] == 50 and observed['checkpoints'] == list(range(5, 51, 5))
    assert observed['max_client_requests'] == observed['max_case_client_requests'] == 569
    assert observed['max_elapsed_seconds'] == observed['max_case_elapsed_seconds'] == 7200
    launcher.validate_native_plan(observed)
    assert not directory.exists()


@pytest.mark.parametrize('source_changed', [False, True])
def test_local_execution_uses_snapshot_and_preserves_native_preflight_and_lease(checkout, tmp_path, monkeypatch, capsys, source_changed):
    root, revision = checkout
    import scripts.native_canary_launcher as native
    import scripts.issue14_subscription_source_contract_v6 as contract
    events = []
    snapshot = launcher.local_checkout_snapshot
    calls = 0
    def observe(head):
        nonlocal calls
        calls += 1
        if calls == 2 and source_changed:
            (root / 'runtime.py').write_text('value = 3\n')
        return snapshot(head)
    monkeypatch.setattr(launcher, 'local_checkout_snapshot', observe)
    monkeypatch.setattr(launcher, 'verify_main_source', lambda *a: pytest.fail('Reviewed-main gate in local mode'))
    monkeypatch.setattr(contract, 'audit_subscription_source_v6', lambda *a: pytest.fail('Historical source audit in local mode'))
    monkeypatch.setattr(launcher.sys, 'platform', 'darwin')
    monkeypatch.setattr(launcher, 'memory_resource_check', lambda **kw: events.append('memory'))
    original_run = subprocess.run
    def inspect(command, **kw):
        if command[0] == 'git':
            return original_run(command, **kw)
        assert command == ['container', 'image', 'inspect', 'postgres:18.3']
        events.append('cached_image')
    monkeypatch.setattr(launcher.subprocess, 'run', inspect)
    def credential():
        events.append('credential')
        return 'synthetic-private'
    monkeypatch.setattr(launcher, 'configured_credential', credential)
    @contextmanager
    def lease(run_id):
        events.append('lease')
        yield
        events.append('release')
    monkeypatch.setattr(native, 'native_resource_lease', lease)
    async def execute(value, directory, key):
        assert key == 'synthetic-private' and value['local_checkout_source']['dirty'] is True
        events.append('execute')
        return {'run_id': value['run_id'], 'status': 'completed'}
    monkeypatch.setattr(launcher, 'execute_native', execute)
    result = launcher.main(argv(plan(revision), tmp_path / 'run', '--local-checkout', '--execute-existing-subscription'))
    output = json.loads(capsys.readouterr().out)
    assert 'synthetic-private' not in json.dumps(output)
    if source_changed:
        assert result == 3 and events == []
        assert output['preflight_stage'] == 'source_validation' and output['execution_started'] is False
    else:
        assert result == 0
        assert events == ['memory', 'cached_image', 'credential', 'lease', 'memory', 'execute', 'release']


@pytest.mark.parametrize('source_changed', [False, True])
def test_native_receipt_retains_local_provenance_and_invalidates_results_if_source_changes(checkout, tmp_path, monkeypatch, source_changed):
    root, revision = checkout
    import scripts.issue14_subscription_session as sessions
    import scripts.issue14_subscription_runner as runners
    from scripts.issue14_subscription_transport import SubscriptionTransport
    value = plan(revision, launcher.local_checkout_snapshot(revision))
    @asynccontextmanager
    async def resources(plan, run, directory, receipt):
        receipt['native'] = {'cleanup_complete': True}
        yield {}
    async def create(**kwargs):
        async def close():
            await kwargs['provider_transport'].aclose()
            kwargs['run'].close()
        return SimpleNamespace(close=close, worker_receipts=lambda: [])
    class Runner:
        def __init__(self, session, **kwargs):
            pass
        async def run(self, **kwargs):
            if source_changed:
                (root / 'runtime.py').write_text('value = 3\n')
            return {'status': 'completed', 'output': ['synthetic'], 'cases': []}
    monkeypatch.setattr(launcher, 'native_resources', resources)
    monkeypatch.setattr(sessions.OwnedSubscriptionSession, 'create', create)
    monkeypatch.setattr(runners, 'SubscriptionProgressiveRunner', Runner)
    monkeypatch.setattr(SubscriptionTransport, 'existing_route', lambda *, run, authorization:
        SubscriptionTransport.controlled(run=run, endpoint='http://127.0.0.1:65432/v1/responses'))
    directory = tmp_path / 'run'
    receipt = asyncio.run(launcher.execute_native(value, directory, 'synthetic-token'))
    assert receipt['local_checkout_source'] == value['local_checkout_source']
    assert receipt['local_checkout_unchanged'] is not source_changed
    assert receipt['request_accounting']['client_requests_started'] == 0
    assert receipt['native']['cleanup_complete'] is True
    assert receipt['status'] == ('incomplete' if source_changed else 'completed')
    if source_changed:
        assert receipt['stop_reason'] == 'source_changed_during_run' and receipt['evaluation']['output'] is None
    assert json.loads((directory / 'receipt.json').read_text()) == receipt


def test_default_source_admission_still_uses_reviewed_main(monkeypatch):
    verified = []
    monkeypatch.setattr(launcher, 'verify_main_source', lambda revision: verified.append(revision))
    monkeypatch.setattr(launcher, 'local_checkout_snapshot', lambda *a: pytest.fail('Local source default'))
    launcher.verify_execution_source('a' * 40)
    assert verified == ['a' * 40]
