"""Nonpersistent local input tests use fake keys only; no gateway is contacted."""
import asyncio
import getpass
import os
import warnings

import pytest


def test_task_environment_input_is_removed_and_secret_repr_is_redacted(monkeypatch):
    from scripts.canary_gateway_auth import task_consumer_authorization
    monkeypatch.setenv('MEMOIR_CANARY_GATEWAY_API_KEY', 'synthetic-existing-gateway-key')
    monkeypatch.setenv('MEMORY_SPARK_LLM_API_KEY', 'unrelated-provider-key')
    with task_consumer_authorization(input_mode='environment') as secret:
        assert 'MEMOIR_CANARY_GATEWAY_API_KEY' not in os.environ
        assert secret.authorization_header() == 'Bearer synthetic-existing-gateway-key'
        assert 'synthetic' not in str(secret)
        assert os.environ['MEMORY_SPARK_LLM_API_KEY'] == 'unrelated-provider-key'
    with pytest.raises(RuntimeError): secret.authorization_header()


def test_hidden_prompt_rejects_echo_fallback_and_does_not_read_a_pipe(monkeypatch):
    from scripts.canary_gateway_auth import task_consumer_authorization
    import scripts.canary_gateway_auth as auth
    monkeypatch.setattr(auth.sys.stdin, 'isatty', lambda: False)
    monkeypatch.setattr(auth.getpass, 'getpass', lambda **kwargs: pytest.fail('Must not prompt on a pipe'))
    with pytest.raises(ValueError, match='terminal'):
        with task_consumer_authorization(): pass
    monkeypatch.setattr(auth.sys.stdin, 'isatty', lambda: True)
    def unsafe(**kwargs):
        warnings.warn('Unable to hide input', getpass.GetPassWarning)
        pytest.fail('Echo fallback must stop before reading')
    monkeypatch.setattr(auth.getpass, 'getpass', unsafe)
    with pytest.raises(ValueError, match='hidden'):
        with task_consumer_authorization(): pass


def test_hidden_prompt_never_echoes_and_clears_on_error(monkeypatch, capsys):
    from scripts.canary_gateway_auth import task_consumer_authorization
    import scripts.canary_gateway_auth as auth
    monkeypatch.setattr(auth.sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr(auth.getpass, 'getpass', lambda **kwargs: 'synthetic-existing-gateway-key')
    with pytest.raises(RuntimeError, match='controlled failure'):
        with task_consumer_authorization() as secret:
            assert secret.authorization_header().endswith('synthetic-existing-gateway-key')
            raise RuntimeError('controlled failure')
    assert capsys.readouterr() == ('', '')
    with pytest.raises(RuntimeError): secret.authorization_header()


@pytest.mark.parametrize('raw', ['', 'bad\nheader', 'Bearer already-prefixed', 'short'])
def test_invalid_input_is_removed_without_disclosing_its_value(monkeypatch, raw):
    from scripts.canary_gateway_auth import task_consumer_authorization
    monkeypatch.setenv('MEMOIR_CANARY_GATEWAY_API_KEY', raw)
    with pytest.raises(ValueError) as error:
        with task_consumer_authorization(input_mode='environment'): pass
    assert not raw or raw not in str(error.value)
    assert 'MEMOIR_CANARY_GATEWAY_API_KEY' not in os.environ


def test_owned_worker_context_clears_worker_and_lease_auth(monkeypatch, tmp_path):
    from scripts.canary_gateway_auth import authenticated_canary_worker
    from scripts.canary_gateway_bridge import NativeGatewayLease
    from scripts.canary_worker import CanaryWorker
    from types import SimpleNamespace
    calls = []
    lease = SimpleNamespace(stopped=False)
    async def stop():
        lease.stopped = True
    lease.stop = stop
    def preflight(**kwargs): calls.append('preflight')
    async def start(**kwargs):
        assert kwargs['consumer_authorization'] == 'Bearer synthetic-existing-gateway-key'
        calls.append('start')
        return lease
    worker = SimpleNamespace(api_key='synthetic-existing-gateway-key')
    monkeypatch.setattr(NativeGatewayLease, 'validate_native_target', preflight)
    monkeypatch.setattr(NativeGatewayLease, 'start_native', start)
    monkeypatch.setattr(CanaryWorker, 'for_gateway_lease', lambda **kwargs: worker)
    monkeypatch.setenv('MEMOIR_CANARY_GATEWAY_API_KEY', 'synthetic-existing-gateway-key')
    async def scenario():
        async with authenticated_canary_worker(actor_options={}, home_root=tmp_path / 'unused',
                codex_binary='/unused/codex', expected_codex_sha256='a' * 64, input_mode='environment') as result:
            assert result is worker
            assert calls == ['preflight', 'start']
            assert 'MEMOIR_CANARY_GATEWAY_API_KEY' not in os.environ
        assert worker.api_key == ''
        assert lease.stopped
    asyncio.run(scenario())


def test_invalid_actor_target_fails_before_secret_input(monkeypatch, tmp_path):
    from scripts.canary_gateway_auth import authenticated_canary_worker
    from scripts.canary_gateway_bridge import NativeGatewayLease
    monkeypatch.setenv('MEMOIR_CANARY_GATEWAY_API_KEY', 'synthetic-unread-key')
    def rejected(**kwargs): raise ValueError('Unverified native target')
    monkeypatch.setattr(NativeGatewayLease, 'validate_native_target', rejected)
    async def scenario():
        with pytest.raises(ValueError, match='Unverified'):
            async with authenticated_canary_worker(actor_options={}, home_root=tmp_path / 'unused',
                    codex_binary='/unused/codex', expected_codex_sha256='a' * 64, input_mode='environment'):
                pytest.fail('Invalid target must never enter worker scope')
    asyncio.run(scenario())
    assert os.environ['MEMOIR_CANARY_GATEWAY_API_KEY'] == 'synthetic-unread-key'
    assert not (tmp_path / 'unused').exists()


def test_input_check_cli_does_not_verify_auth_or_disclose_secret(tmp_path):
    import json
    from pathlib import Path
    import subprocess
    import sys
    from scripts.run_isolated_check import offline_environment
    root = Path(__file__).resolve().parents[1]
    environment = offline_environment(root)
    environment['MEMOIR_CANARY_GATEWAY_API_KEY'] = 'synthetic-cli-input-key'
    result = subprocess.run([sys.executable, '-m', 'scripts.canary_gateway_auth',
        '--check-input', '--input-mode', 'environment'], cwd=root, env=environment,
        capture_output=True, text=True, timeout=5)
    assert result.returncode == 0
    assert json.loads(result.stdout) == {'status': 'input_shape_valid_and_cleared',
        'gateway_auth_verified': False, 'provider_requests_started': 0}
    assert 'synthetic-cli-input-key' not in result.stdout + result.stderr
    assert list(tmp_path.iterdir()) == []
    rejected = subprocess.run([sys.executable, '-m', 'scripts.canary_gateway_auth',
        '--key', 'synthetic-mistaken-argv-key'], cwd=root, env=offline_environment(root),
        capture_output=True, text=True, timeout=5)
    assert rejected.returncode == 2
    assert 'synthetic-mistaken-argv-key' not in rejected.stdout + rejected.stderr


def test_fresh_resource_gate_runs_after_hidden_input_but_before_actor(monkeypatch, tmp_path):
    from scripts.canary_gateway_auth import authenticated_canary_worker
    from scripts.canary_gateway_bridge import NativeGatewayLease
    monkeypatch.setenv('MEMOIR_CANARY_GATEWAY_API_KEY', 'synthetic-only-input')
    monkeypatch.setattr(NativeGatewayLease, 'validate_native_target', lambda **kwargs: None)
    async def forbidden(**kwargs): pytest.fail('Pressure gate must precede actor startup')
    monkeypatch.setattr(NativeGatewayLease, 'start_native', forbidden)
    def resource_gate():
        assert 'MEMOIR_CANARY_GATEWAY_API_KEY' not in os.environ
        raise RuntimeError('controlled pressure')
    async def scenario():
        with pytest.raises(RuntimeError, match='controlled pressure'):
            async with authenticated_canary_worker(actor_options={}, home_root=tmp_path / 'unused',
                codex_binary='/unused', expected_codex_sha256='a' * 64, input_mode='environment',
                before_actor_start=resource_gate):
                pytest.fail('Blocked resource gate entered worker scope')
    asyncio.run(scenario())
    assert not (tmp_path / 'unused').exists()
