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


def test_controlled_comparison_isolates_hostile_inherited_research_and_gateway_config(monkeypatch):
    from contextlib import contextmanager
    import httpx
    from apps.api.historical_news import accepted_hypothesis
    from apps.api.historical_news_provider import GatewayHistoricalProvider
    from scripts import profile_canonical_controlled as profile

    text = 'I was born in Perth, Australia in 1950.'
    assert accepted_hypothesis({'sources': [{'id': 'synthetic', 'version': 1,
        'status': 'active', 'text': text}]}) is not None
    inherited = {'MEMORY_SPARK_HISTORICAL_NEWS': 'true',
        'MEMORY_SPARK_HISTORICAL_NEWS_MODEL': 'synthetic-history',
        'MEMORY_SPARK_LLM_BASE_URL': 'https://provider.invalid/v1',
        'MEMORY_SPARK_LLM_API_KEY': 'synthetic-inherited-key',
        'MEMORY_SPARK_LLM_MODEL': 'synthetic-general',
        'MEMORY_SPARK_CODEX_WORKER_URL': 'https://worker.invalid',
        'OPENAI_API_KEY': 'synthetic-openai-key',
        'HTTPS_PROXY': 'http://proxy.invalid:8080'}
    for key, value in inherited.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv('MEMOIR_TEST_POSTGRES_BACKEND', 'native')
    contacts, database_environments = [], []
    async def blocked_discovery(self, query, **options):
        contacts.append('historical-discovery')
        raise RuntimeError('Synthetic network sentinel; no request sent')
    async def blocked_inspection(self, url, **options):
        contacts.append('historical-source')
        raise RuntimeError('Synthetic network sentinel; no source fetched')
    monkeypatch.setattr(GatewayHistoricalProvider, 'discover', blocked_discovery)
    monkeypatch.setattr(GatewayHistoricalProvider, 'inspect', blocked_inspection)
    real_send = httpx.AsyncClient.send
    async def only_mock_transport(client, *args, **kwargs):
        assert isinstance(client._transport, httpx.MockTransport), 'External HTTP transport forbidden'
        return await real_send(client, *args, **kwargs)
    monkeypatch.setattr(httpx.AsyncClient, 'send', only_mock_transport)
    real_database = profile.controlled_database
    @contextmanager
    def observed_database():
        try:
            with real_database() as sql:
                yield sql
        finally:
            # Isolation must also cover cleanup after publication delivery.
            database_environments.append({key: os.environ.get(key) for key in inherited})
    monkeypatch.setattr(profile, 'controlled_database', observed_database)

    receipt = asyncio.run(profile.canonical_campaign([text], candidate_model='synthetic-byte-bpe'))
    assert receipt['status'] == 'completed' and receipt['temporary_homes_removed']
    assert receipt['provider_requests_started'] == 0
    assert contacts == []
    assert len(database_environments) == 2
    assert all(env['MEMORY_SPARK_HISTORICAL_NEWS'] == '0' for env in database_environments)
    assert all(all(env[key] is None for key in inherited if key != 'MEMORY_SPARK_HISTORICAL_NEWS')
        for env in database_environments)
    assert all(os.environ[key] == value for key, value in inherited.items())
