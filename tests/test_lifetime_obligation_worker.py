import asyncio
import pytest
from apps.api.lifetime_memory_maintenance import drain_lifetime_obligations_once


def test_worker_maintenance_uses_only_existing_server_broker_and_stays_active_when_generation_paused(monkeypatch):
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','true')
    monkeypatch.setenv('MEMOIR_LIFETIME_GENERATION_PAUSED','true')
    calls=[]
    class Broker:
        async def rpc(self,name,**params):
            calls.append((name,params));return {'processed':2,'failed':0,'busy':0}
    assert asyncio.run(drain_lifetime_obligations_once(Broker(),limit=4))['processed']==2
    assert calls==[('drain_lifetime_memory_obligations',{'p_limit':4})]


def test_disabled_generation_preserves_required_worker_and_invalid_budget_fails_before_rpc(monkeypatch):
    monkeypatch.delenv('MEMOIR_LIFETIME_MEMORY',raising=False)
    class Broker:
        async def rpc(self,name,**params):return {'processed':1,'failed':0,'busy':0}
    assert asyncio.run(drain_lifetime_obligations_once(Broker()))['processed']==1
    with pytest.raises(ValueError):asyncio.run(drain_lifetime_obligations_once(None,limit=0))
