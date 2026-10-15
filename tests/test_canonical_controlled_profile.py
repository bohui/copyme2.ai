"""A separately labelled canonical diagnostic preserves matched SQL prestate."""
import asyncio
import os

from scripts.profile_canonical_controlled import canonical_campaign


def test_controlled_comparison_matches_real_prestate_and_labels_actual_contract(monkeypatch):
    monkeypatch.setenv('MEMOIR_TEST_POSTGRES_BACKEND','native')
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_MODEL','')
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_REASONING_EFFORT','')
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION','')
    receipt=asyncio.run(canonical_campaign(['I started school around 1964.','I remember its blue gate.']))
    assert receipt['status']=='completed' and receipt['temporary_homes_removed']
    assert receipt['provider_requests_started']==0
    assert receipt['semantic_acceptance']==receipt['latency_acceptance']=='not_run'
    assert receipt['effective_provider_effort'] is None
    assert receipt['legacy_prompt_comparison']=='blocked_pending_benchmark_definition'
    assert len(receipt['results'])==4
    for ordinal in (1,2):
        pair=[row for row in receipt['results'] if row['round']==ordinal]
        assert {row['variant'] for row in pair}=={'baseline','candidate'}
        assert len({row['pre_state_sha256'] for row in pair})==1
        assert len({row['input_sha256'] for row in pair})==1
        assert all(row['appserver_turns']==row['private_worker_requests']==1 for row in pair)
        assert all(row['thread_policy']=='fresh_ephemeral' and row['effective_prompt_version']=='lifetime-v1' for row in pair)
        assert all(row['effective_effort'] is None and row['provider_request_count'] is None for row in pair)
        assert all(row['timings']['first_visible_text_s']<=row['timings']['conversation_saved_s'] for row in pair)
    assert all(os.environ['MEMORY_SPARK_COLLECTOR_'+key]=='' for key in ('MODEL','REASONING_EFFORT','PROMPT_VERSION'))


def test_canonical_comparison_stops_on_first_failed_delivery_without_raw_error(monkeypatch):
    from apps.api.codex_worker_service import CodexWorker
    import json
    calls=[]
    async def failed(self,payload,**options):
        calls.append(payload.agent_role)
        raise RuntimeError('private-fixture-key')
    monkeypatch.setenv('MEMOIR_TEST_POSTGRES_BACKEND','native')
    monkeypatch.setattr(CodexWorker,'turn',failed)
    receipt=asyncio.run(canonical_campaign(['I started school.']))
    assert receipt['status']=='incomplete' and receipt['temporary_homes_removed']
    assert len(receipt['results'])==len(calls)==1
    assert receipt['results'][0]['status']=='failed'
    assert receipt['results'][0]['appserver_turns'] is None
    assert receipt['provider_requests_started']==0
    assert 'private-fixture-key' not in json.dumps(receipt)
