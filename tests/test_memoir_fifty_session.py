"""Trusted metadata and explicit fifty-profile checks on synthetic loopback only."""
import asyncio
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from test_issue14_subscription_session import gateway, controlled_temporal_startup, REVISION
from apps.api.agent_storage import UserStorage
from apps.api.memory_event_worker import MemoirLaneBroker
from scripts.issue14_subscription_session import OwnedSubscriptionSession, assert_owned_subscription_session
from scripts.issue14_subscription_transport import SubscriptionLimits, SubscriptionRun, SubscriptionTransport
from scripts.memoir_subscription_profiles import profile_for


async def session(tmp_path, endpoint, *, mutate=None):
    profile = profile_for('subscription_fifty')
    (tmp_path / 'journal').mkdir()
    run = SubscriptionRun.create(reservation_root=tmp_path / 'journal', run_id=str(uuid4()),
        source_revision=REVISION, limits=SubscriptionLimits(3000, 36000),
        case_ids=profile.case_ids, case_limits=SubscriptionLimits(600, 7200))
    transport = SubscriptionTransport.controlled(run=run, endpoint=endpoint)
    from memoir_postgres_workflow import PostgresRest
    storages, facades = {}, {}
    for case_id, plan in profile.plans(run.run_id).items():
        entitlement = profile.entitlement(plan, 1)
        if mutate and entitlement:
            mutate(entitlement)
        facade = PostgresRest(lambda *a, **k: pytest.fail('No PostgreSQL call expected'),
                              plan['owner_id'], entitlement=entitlement)
        facades[case_id] = facade
        storages[case_id] = facade.storage()
    broker = MemoirLaneBroker(url='http://synthetic.invalid', key='synthetic-service',
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[]))))
    binary = Path('/bin/true').resolve()
    try:
        return await OwnedSubscriptionSession.create(run=run, provider_transport=transport,
            storages=storages, broker=broker, temporal_client=object(), home_root=tmp_path / 'home',
            codex_binary=binary, codex_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
            api_key='synthetic-token', evaluation_profile='subscription_fifty', entitlement_facades=facades)
    except BaseException:
        await transport.aclose(); run.close(); await broker.client.aclose()
        for storage in storages.values(): storage.client.close()
        raise


@pytest.mark.parametrize('role', ['collector', 'workspace', 'memory_context', 'author_timeline', 'composer'])
def test_round_fifty_preserves_trusted_wire_metadata_for_every_role(tmp_path, gateway, monkeypatch, role):
    from apps.api.codex_worker_service import CodexWorker
    endpoint, contacts = gateway
    async def worker(self, payload, **kwargs):
        assert payload.evaluation['round_id'] == '50'
        assert payload.evaluation['dataset'] == 'memoir-five-case/1'
        if role == 'composer':
            assert payload.evaluation['checkpoint_id'].endswith(':50')
        async with httpx.AsyncClient(trust_env=False) as client:
            response = await client.post(self.base_url + '/responses',
                headers={'Authorization': 'Bearer synthetic-token'}, json={'stream': True,
                    'model': self.model, 'reasoning': {'effort': self.reasoning_effort},
                    'input': 'synthetic', 'client_metadata': {'x-codex-turn-metadata':
                        json.dumps(payload.evaluation)}})
            response.raise_for_status()
        return {'reply': 'Controlled'}
    monkeypatch.setattr(CodexWorker, 'turn', worker)
    async def scenario():
        owned = await session(tmp_path, endpoint)
        try:
            case = owned.case_ids[0]
            details = owned.case_plans[case]
            for n in range(1, 50):
                owned.activate_round(case, n); owned.finish_round()
            owned.activate_round(case, 50)
            if role in ('composer', 'author_timeline'):
                owned._job_context.set({'job_id': 'synthetic-workflow:activity'})
            async with httpx.AsyncClient(transport=owned.worker_transport, base_url=owned.worker_url) as client:
                result = await client.post('/internal/codex/turn', json={
                    'user_id': details['owner_id'], 'project_id': details['project_id'],
                    'language': details['language'], 'agent_role': role, 'text': 'synthetic',
                    'family_enabled': role in ('collector', 'workspace')})
                assert result.status_code == 200
            owned.finish_round(); owned.finish_case(case)
            assert len(contacts) == 1
            assert owned.run.snapshot()['cases'][0]['client_requests_reserved'] == 1
        finally:
            await owned.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('mutation', [lambda value: value.update(user_id=str(uuid4())),
    lambda value: value.update(status='free'), lambda value: value.update(plan_key='real-unrelated-plan'),
    lambda value: value.update(family_tree=False)])
def test_campaign_entitlement_must_match_synthetic_owner_before_worker_start(tmp_path, gateway, mutation):
    endpoint, contacts = gateway
    with pytest.raises(ValueError, match='synthetic campaign entitlement'):
        asyncio.run(session(tmp_path, endpoint, mutate=mutation))
    assert not (tmp_path / 'home').exists() and not contacts


def test_campaign_case_order_cannot_skip_the_original_first_case(tmp_path, gateway):
    endpoint, contacts = gateway
    async def scenario():
        owned = await session(tmp_path, endpoint)
        try:
            with pytest.raises(ValueError, match='Earlier cases'):
                owned.activate_round(owned.case_ids[1], 1)
            assert owned.run.snapshot()['client_requests_started'] == 0
        finally:
            await owned.close()
    asyncio.run(scenario())
    assert contacts == []


def test_original_chinese_family_transition_changes_only_owned_synthetic_facade(tmp_path, gateway):
    endpoint, contacts = gateway
    async def scenario():
        owned = await session(tmp_path, endpoint)
        try:
            first, chinese = owned.case_ids[:2]
            for n in range(1, 51):
                owned.activate_round(first, n); owned.finish_round()
            owned.finish_case(first)
            storage = owned.storage_for_case(chinese)
            for n in range(1, 16):
                owned.activate_round(chinese, n)
                assert storage.story_entitlement() is None
                owned.finish_round()
            owned.activate_round(chinese, 16)
            entitlement = storage.story_entitlement()
            assert entitlement['user_id'] == owned.case_plans[chinese]['owner_id']
            assert entitlement['stripe_price_id'] == 'synthetic-memoir-fifty-price'
            assert entitlement['family_tree'] is True
            assert owned.run.snapshot()['client_requests_started'] == 0
            assert owned._entitlement_facades[first].entitlement['user_id'] != entitlement['user_id']
        finally:
            await owned.close()
    asyncio.run(scenario())
    assert contacts == []
