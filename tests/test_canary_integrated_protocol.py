"""Real host bridge + actor framing + guard, with synthetic upstream only."""
import asyncio
from uuid import uuid4

import httpx
import pytest


def test_combined_source_map_pins_all_runtime_and_task_actor_bytes():
    import hashlib
    from pathlib import Path
    from scripts.canary_gateway_actor import expected_source_hashes, BOOTSTRAP_SOURCE_SHA256
    from scripts.canary_gateway_binding import SOURCE_SHA256
    pins = expected_source_hashes()
    assert all(pins[key] == value for key, value in {**SOURCE_SHA256, **BOOTSTRAP_SOURCE_SHA256}.items())
    root = Path(__file__).resolve().parents[1]
    for name in ('canary_gateway_actor.py', 'canary_gateway_binding.py', 'canary_send_guard.py'):
        assert pins['scripts/' + name] == hashlib.sha256((root / 'scripts' / name).read_bytes()).hexdigest()


@pytest.mark.parametrize('mode', ['budget', 'http_failure', 'terminal_failure'])
def test_real_actor_protocol_stops_without_replay_and_preserves_joined_receipt(tmp_path, mode):
    from scripts.canary_gateway_bridge import NativeGatewayLease
    from scripts.run_codexlb_canary import APPROVED_ACCOUNT_BINDING
    async def scenario():
        lease = await NativeGatewayLease.controlled(run_id=str(uuid4()), source_revision='a' * 40,
            account_binding=APPROVED_ACCOUNT_BINDING, control={'mode': mode}, control_dir=tmp_path,
            integrated_protocol=True)
        try:
            with pytest.raises(ValueError): lease.assert_ready()
            async with httpx.AsyncClient(trust_env=False) as client:
                payload = {'model': 'gpt-5.6-luna', 'stream': True, 'client_metadata': {
                    'run_id': lease.run_id, 'case_id': 'harbour-copper-notebook', 'round_id': '1',
                    'trace_id': '1' * 32, 'observation_id': '2' * 16}}
                headers = {'Authorization': 'Bearer synthetic-consumer-only'}
                if mode == 'budget':
                    for _ in range(2):
                        response = await client.post(lease.base_url + '/responses', headers=headers, json=payload)
                        assert response.status_code == 200
                    assert lease.receipt()['guarded_send_entries'] == 2
                else:
                    response = await client.post(lease.base_url + '/responses', headers=headers, json=payload)
                    assert response.status_code == (503 if mode == 'http_failure' else 200)
                forwarded = lease.receipt()['bridge_requests_forwarded']
                denied = await client.post(lease.base_url + '/responses', headers=headers, json=payload)
                assert denied.status_code == 503
                assert lease.receipt()['bridge_requests_forwarded'] == forwarded
                assert 'synthetic-consumer-only' not in response.text
        finally:
            receipt = await lease.stop()
            assert receipt['bridge_cleanup']['actor_exit_verified'] is True
            assert receipt['cleanup']['closed'] is True
            assert receipt['cleanup']['active_finished'] is True
            for attempt in receipt['attempts']:
                assert attempt['correlation']['run_id'] == lease.run_id
                assert attempt['correlation']['observation_id'] == '2' * 16
    asyncio.run(scenario())


def test_combined_manifest_cannot_claim_wrong_actor_source_or_merged_main():
    from scripts.run_codexlb_canary import build_manifest
    from scripts.canary_app_launcher import validate_plan
    from copy import deepcopy
    plan = build_manifest(run_id=str(uuid4()), source_revision='a' * 40)
    for field in ('gateway_source_sha256', 'integration_provenance', 'source_claim'):
        changed = deepcopy(plan)
        changed[field] = {} if field != 'source_claim' else 'exact-main-passed'
        with pytest.raises(ValueError): validate_plan(changed)
