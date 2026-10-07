"""Framed actor protocol tests use an owned Python subprocess and fake auth."""
import asyncio
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest


def test_bridge_rejects_live_url_or_arbitrary_command_before_process_allocation(tmp_path):
    from scripts.canary_gateway_bridge import NativeGatewayLease
    async def scenario():
        with pytest.raises(ValueError):
            await NativeGatewayLease.start_native(actor_command=['/bin/sh', '-c', 'echo nope'],
                run_id=str(uuid4()), source_revision='a' * 40, account_binding='b' * 64,
                consumer_authorization='Bearer synthetic-secret', source_sha256={'actor': 'c' * 64})
    asyncio.run(scenario())


@pytest.mark.parametrize('mode', ['bad_id', 'bad_challenge', 'wrong_account', 'eof', 'duplicate_json_key'])
def test_bridge_refuses_ambiguous_handshake_without_model_send(tmp_path, mode):
    from scripts.canary_gateway_bridge import NativeGatewayLease
    async def scenario():
        with pytest.raises(RuntimeError):
            await NativeGatewayLease.controlled(run_id=str(uuid4()), source_revision='a' * 40,
                account_binding='b' * 64, control={'mode': mode}, control_dir=tmp_path)
    asyncio.run(scenario())


def test_controlled_bridge_preserves_auth_and_never_becomes_live_ready(tmp_path):
    from scripts.canary_gateway_bridge import NativeGatewayLease
    async def scenario():
        lease = await NativeGatewayLease.controlled(run_id=str(uuid4()), source_revision='a' * 40,
            account_binding='b' * 64, control={}, control_dir=tmp_path)
        try:
            with pytest.raises(ValueError): lease.assert_ready(run_id=lease.run_id, source_revision='a' * 40)
            async with httpx.AsyncClient(trust_env=False) as client:
                denied = await client.post(lease.base_url + '/responses', json={'model': 'gpt-5.6-luna', 'stream': True})
                assert denied.status_code == 401
                response = await client.post(lease.base_url + '/responses',
                    headers={'Authorization': 'Bearer synthetic-consumer-only'},
                    json={'model': 'gpt-5.6-luna', 'stream': True, 'client_metadata': {'run_id': lease.run_id}})
                assert response.status_code == 200
                assert 'response.completed' in response.text
            receipt = await lease.refresh_receipt()
            assert receipt['guarded_send_entries'] == 1
            assert receipt['control_auth_verified'] is True
            assert 'synthetic-consumer-only' not in json.dumps(receipt)
        finally:
            stopped = await lease.stop()
            assert stopped['bridge_cleanup']['child_reaped'] is True
            assert stopped['bridge_cleanup']['listener_closed'] is True
    asyncio.run(scenario())


def test_bridge_eof_is_terminal_and_queued_http_requests_are_not_replayed(tmp_path):
    from scripts.canary_gateway_bridge import NativeGatewayLease
    async def scenario():
        lease = await NativeGatewayLease.controlled(run_id=str(uuid4()), source_revision='a' * 40,
            account_binding='b' * 64, control={'mode': 'response_eof'}, control_dir=tmp_path)
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                for _ in range(2):
                    response = await client.post(lease.base_url + '/responses',
                        headers={'Authorization': 'Bearer synthetic-consumer-only'},
                        json={'model': 'gpt-5.6-luna', 'stream': True, 'client_metadata': {'run_id': lease.run_id}})
                    assert response.status_code == 503
            assert lease.receipt()['bridge_requests_forwarded'] == 1
        finally:
            await lease.stop()
    asyncio.run(scenario())


@pytest.mark.parametrize('mode', ['response_bad_id', 'response_secret', 'response_extra_field', 'response_wrong_type'])
def test_malformed_actor_response_is_terminal_and_no_secret_is_returned(tmp_path, mode):
    from scripts.canary_gateway_bridge import NativeGatewayLease
    async def scenario():
        lease = await NativeGatewayLease.controlled(run_id=str(uuid4()), source_revision='a' * 40,
            account_binding='b' * 64, control={'mode': mode}, control_dir=tmp_path)
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                response = await client.post(lease.base_url + '/responses',
                    headers={'Authorization': 'Bearer synthetic-consumer-only'},
                    json={'model': 'gpt-5.6-luna', 'stream': True, 'client_metadata': {'run_id': lease.run_id}})
                assert response.status_code == 503
                assert 'synthetic-consumer-only' not in response.text
            assert lease.receipt()['bridge_failed'] is True
        finally:
            await lease.stop()
    asyncio.run(scenario())


def test_controlled_lease_cannot_launch_real_codex_and_preserves_signal_owner(tmp_path):
    import signal
    from scripts.canary_gateway_bridge import NativeGatewayLease
    from scripts.canary_worker import CanaryWorker
    before = signal.getsignal(signal.SIGTERM)
    async def scenario():
        lease = await NativeGatewayLease.controlled(run_id=str(uuid4()), source_revision='a' * 40,
            account_binding='b' * 64, control={}, control_dir=tmp_path)
        try:
            assert signal.getsignal(signal.SIGTERM) == before
            with pytest.raises(ValueError):
                CanaryWorker.for_gateway_lease(home_root=tmp_path / 'untouched', lease=lease,
                    codex_binary='/bin/sh', expected_sha256='c' * 64)
            assert not (tmp_path / 'untouched').exists()
        finally:
            await lease.stop()
    asyncio.run(scenario())
    assert signal.getsignal(signal.SIGTERM) == before


def test_review_other_account_cannot_pass_otherwise_ready_lease_or_worker(tmp_path, monkeypatch):
    """Isolate the account check without starting any actor, listener or model."""
    import os
    import time
    from types import SimpleNamespace
    from scripts.canary_gateway_bridge import NativeGatewayLease
    from scripts.canary_worker import CanaryWorker
    lease = object.__new__(NativeGatewayLease)
    lease.__dict__.update(_controlled=False, _creator_pid=os.getpid(), _stopped=False,
        _stopping=False, _failed=False, _process=SimpleNamespace(returncode=None),
        _server_task=SimpleNamespace(done=lambda: False),
        _socket=SimpleNamespace(fileno=lambda: 7, getsockname=lambda: ('127.0.0.1', 45678)),
        _base_url='http://127.0.0.1:45678/v1', _deadline=time.monotonic() + 60,
        _cached_receipt={}, _forwarded=0, _actor_pid=1, _cleanup={},
        run_id=str(uuid4()), source_revision='a' * 40, account_binding='c' * 64)
    worker = object.__new__(CanaryWorker)
    worker.__dict__.update(evidence_mode='guarded_live_canary', gateway_lease=lease, _stopped=False,
        base_url=lease.base_url, model='gpt-5.6-luna', command=['codex'], _pinned_command=('codex',))
    with pytest.raises(ValueError, match='account'):
        lease.assert_ready(run_id=lease.run_id, source_revision=lease.source_revision)
    with pytest.raises(ValueError, match='account'):
        worker.assert_live_ready(run_id=lease.run_id, source_revision=lease.source_revision)
    from scripts.canary_app_launcher import run_application_canary
    from scripts.run_codexlb_canary import build_manifest
    plan = build_manifest(run_id=lease.run_id, source_revision=lease.source_revision)
    import scripts.canary_app_launcher as launcher
    def forbidden(*args, **kwargs):
        pytest.fail('Account mismatch must stop before source checks or application dispatch')
    monkeypatch.setattr(launcher.subprocess, 'check_output', forbidden)
    with pytest.raises(ValueError, match='account'):
        asyncio.run(run_application_canary(plan, storages={}, broker=None,
            temporal_client=None, worker=worker, run_dir=tmp_path / 'untouched'))
    assert not (tmp_path / 'untouched').exists()


def test_authenticated_unsupported_route_stops_canary_before_any_followup_send(tmp_path):
    from scripts.canary_gateway_bridge import NativeGatewayLease
    async def scenario():
        lease = await NativeGatewayLease.controlled(run_id=str(uuid4()), source_revision='a' * 40,
            account_binding='b' * 64, control={}, control_dir=tmp_path)
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                denied = await client.post(lease.base_url + '/responses/compact',
                    headers={'Authorization': 'Bearer synthetic-consumer-only'}, json={})
                assert denied.status_code == 404
                result = await client.post(lease.base_url + '/responses',
                    headers={'Authorization': 'Bearer synthetic-consumer-only'},
                    json={'model': 'gpt-5.6-luna', 'stream': True, 'client_metadata': {'run_id': lease.run_id}})
                assert result.status_code == 503
                assert lease.receipt()['bridge_requests_forwarded'] == 0
        finally:
            await lease.stop()
    asyncio.run(scenario())
