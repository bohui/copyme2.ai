"""Composer configuration is observed at canonical and provider HTTP seams."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
import time

import httpx
import pytest

from apps.api.codex_worker_service import CodexWorker, WorkerTurnInput
from apps.api.lifetime_memory_composer import execute_lifetime_lane
from apps.api.lifetime_memory_lane_engine import BoundedLaneInput, LanePublication, run_bounded_lane
from controlled_composer_review import controlled_review
from test_agent_commit_postgres import database as base_database
from test_canonical_composer_provenance import controlled_draft
from test_conversation_reply_transport import events, sse
from test_lifetime_composer_capacity import (sql, event_database, private_database, attachment_database,  # noqa: F401
    seeded_composer, rpc, literal, service, OWNER, OTHER)


@pytest.fixture(scope='module')
def database():
    yield from base_database.__wrapped__(publication_tcp=True, deadline=time.monotonic() + 300)


@pytest.mark.parametrize('entry', ['direct', 'worker'])
def test_canonical_composer_defaults_to_sol_61_low_without_changing_explicit_shared_routes(sql, monkeypatch, tmp_path, entry):
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY', 'true')
    monkeypatch.setenv('MEMORY_SPARK_MEMOIR_COMPOSER_MODEL', 'memoir-luna-low')
    monkeypatch.setenv('MEMORY_SPARK_MEMOIR_COMPOSER_REASONING_EFFORT', 'low')
    monkeypatch.setenv('MEMORY_SPARK_LLM_MODEL', 'gpt-5.6-luna-pooled')
    monkeypatch.delenv('MEMOIR_COMPOSER_MODEL', raising=False)
    monkeypatch.delenv('MEMOIR_COMPOSER_REASONING_EFFORT', raising=False)
    identity, source, _, claim = seeded_composer(sql, summary_messages=('Thanks. ' * 160,) * 4)
    publisher = LanePublication(sql.publication_dsn, authenticated_owner=OWNER)
    submissions = []
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL', sql.publication_dsn)
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP', '1')
    real_worker = CodexWorker(home_root=tmp_path / 'worker', base_url='https://provider.invalid/v1',
        api_key='synthetic', reasoning_effort='low')
    original_client = httpx.AsyncClient

    class Broker:
        async def rpc(self, name, **payload):
            args = ','.join(f'{key}=>{literal(value)}' for key, value in payload.items())
            return json.loads(sql(f"set role service_role;select coalesce(to_jsonb(public.{name}({args})),'null'::jsonb);").stdout.strip())

    async def worker(request):
        wire = json.loads(request.content)
        bounded = BoundedLaneInput.model_validate(wire['bounded_lane'])
        assert wire['model'] == bounded.budget.model == 'gpt-6.1-sol'
        assert bounded.budget.context_window == 131072
        assert bounded.budget.input_budget == 98304
        assert bounded.budget.output_headroom == 16384

        async def provider(incoming):
            body = json.loads(b''.join([chunk async for chunk in incoming.stream]))
            assert body['model'] == 'gpt-6.1-sol'
            assert body['reasoning']['effort'] == 'low'
            assert body['max_output_tokens'] == 16384
            submissions.append(bounded.phase)
            payload = json.loads(body['input'])['payload']
            if bounded.phase == 'prepare':
                output = dict(event_id=payload['partition']['id'], context=source['text'],
                    source_refs=payload['partition']['source_refs'])
            elif bounded.phase == 'draft':
                output = controlled_draft(payload, source['text'], 'Childhood')
            else:
                output = controlled_review(payload)
            return httpx.Response(200, content=sse(events(json.dumps(output))))

        if entry == 'worker':
            class ControlledClient(original_client):
                def __init__(self, *args, **kwargs):
                    if kwargs.get('transport') is None:
                        kwargs['transport'] = httpx.MockTransport(provider)
                    super().__init__(*args, **kwargs)
            monkeypatch.setattr(httpx, 'AsyncClient', ControlledClient)
            wire.pop('model')  # The worker's default must agree with the API budget.
            return httpx.Response(200, json=await real_worker.turn(WorkerTurnInput.model_validate(wire)))
        return httpx.Response(200, json=await run_bounded_lane(command=['must-not-start'],
            home_root=tmp_path / 'homes', base_url='https://provider.invalid/v1',
            api_key='synthetic', model=wire['model'], bounded_lane=bounded,
            publisher=publisher, provider_transport=httpx.MockTransport(provider), timeout=5))

    scope = SimpleNamespace(broker=Broker(), worker_url='https://worker.invalid',
        worker_secret='synthetic', worker_transport=httpx.MockTransport(worker), lane_publisher=publisher)
    result = asyncio.run(execute_lifetime_lane(claim, scope))
    assert result['status'] == 'saved' and result['retrieval_complete']
    assert submissions == ['prepare', 'draft', 'review']
    head = rpc(sql, 'read_lifetime_private_draft_head', literal(identity['project_id']))
    assert head['status'] == 'ready' and head['preview']['text'] == source['text']
    from apps.api.lifetime_memory_composer import lane_model_budget
    assert lane_model_budget().model == 'memoir-luna-low'
    assert not (tmp_path / 'homes').exists()


@pytest.mark.parametrize('setting,value,changed', [
    ('MEMOIR_COMPOSER_MODEL', 'memoir-luna-low', True),
    ('MEMOIR_COMPOSER_REASONING_EFFORT', 'medium', True),
    ('MEMORY_SPARK_MEMOIR_COMPOSER_MODEL', 'gpt-5.6-luna-pooled', False),
    ('MEMORY_SPARK_LLM_MODEL', 'gpt-6-astra', False),
])
def test_completed_composer_cache_tracks_only_its_selected_model_and_effort(monkeypatch, setting, value, changed):
    from apps.api.canonical_composer import compose_shared_snapshot
    from test_composer_review_regressions import unchanged_job
    monkeypatch.setenv('MEMOIR_COMPOSER_MODEL', 'gpt-5.6-sol')
    monkeypatch.setenv('MEMOIR_COMPOSER_REASONING_EFFORT', 'high')
    monkeypatch.setenv('MEMORY_SPARK_MEMOIR_COMPOSER_MODEL', 'memoir-luna-low')
    monkeypatch.setenv('MEMORY_SPARK_LLM_MODEL', 'gpt-5.6-luna-pooled')
    job = unchanged_job()
    phases, checkpoints = [], {}

    class Broker:
        async def rpc(self, name, **payload):
            if name == 'read_memoir_checkpoint':
                return deepcopy(checkpoints.get(payload['p_key']))
            checkpoints[payload['p_key']] = deepcopy(payload['p_value'])

    async def provider(runtime, storage, project, locale, phase, packet):
        phases.append(phase)
        if phase == 'prepare':
            return dict(event_id='childhood', context=job['sources'][0]['text'], source_refs=job['events'][0]['source_refs'])
        if phase == 'draft':
            return controlled_draft(packet, job['sources'][0]['text'], 'Childhood')
        return controlled_review(packet)

    monkeypatch.setattr('apps.api.canonical_composer.composer_call', provider)
    monkeypatch.setattr('apps.api.memoir_preview.composer_call', provider)
    worker = SimpleNamespace(broker=Broker(), worker_url='https://fixture.invalid', worker_secret='synthetic', worker_transport=None)
    previous = asyncio.run(compose_shared_snapshot(job, worker))
    pinned = deepcopy(previous)
    phases.clear()
    monkeypatch.setenv(setting, value)
    result = asyncio.run(compose_shared_snapshot({**job, 'previous':previous, 'base_revision':1}, worker))
    assert result['status'] == 'ready'
    assert (result['content_config'] != previous['content_config']) is changed
    assert phases == (['prepare','draft','review'] if changed else [])
    assert previous == pinned


@pytest.mark.parametrize('setting,value,budget_model', [
    ('MEMOIR_COMPOSER_MODEL', 'unreviewed-sol-alias', 'gpt-5.6-sol'),
    ('MEMOIR_COMPOSER_MODEL', 'gpt-6.1-sol', 'gpt-5.6-sol'),
    ('MEMOIR_COMPOSER_MODEL', '', 'gpt-5.6-sol'),
    ('MEMOIR_COMPOSER_REASONING_EFFORT', 'unbounded', 'gpt-5.6-sol'),
    ('MEMOIR_COMPOSER_REASONING_EFFORT', '', 'gpt-5.6-sol'),
    ('MEMOIR_COMPOSER_MODEL', 'gpt-5.6-sol', 'memoir-luna-low'),
])
def test_worker_rejects_invalid_or_stale_composer_configuration_before_dispatch(monkeypatch, tmp_path, setting, value, budget_model):
    from test_lifetime_memory_lane_engine import BUDGET, page, packet_for
    from apps.api.lifetime_memory_lane_engine import build_bounded_lane_input
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY', 'true')
    monkeypatch.setenv('MEMOIR_COMPOSER_MODEL', 'gpt-5.6-sol')
    monkeypatch.setenv('MEMOIR_COMPOSER_REASONING_EFFORT', 'high')
    monkeypatch.setenv(setting, value)
    monkeypatch.delenv('MEMOIR_PUBLICATION_DATABASE_URL', raising=False)
    current = page('composer')
    bounded = build_bounded_lane_input(current, phase='prepare', packet=packet_for(current, 'prepare'),
        budget=BUDGET.model_copy(update={'model':budget_model}))
    payload = WorkerTurnInput(user_id=bounded.fence.user_id, project_id=bounded.fence.project_id,
        model=budget_model, agent_role='composer', composer_phase='prepare', bounded_lane=bounded)
    worker = CodexWorker(home_root=tmp_path, api_key='synthetic')
    with pytest.raises(ValueError, match='[Cc]omposer'):
        asyncio.run(worker.turn(payload))
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('scope,model,changes,allowed', [
    ('composer','gpt-5.6-sol',{},True),
    ('timeline','gpt-5.6-sol',{},True),
    ('timeline','gpt-6.1-sol',{},True),
    ('composer','gpt-6.1-sol',{},True),
    ('composer','unreviewed-sol-alias',{},False),
    ('composer','gpt-5.6-sol',{'context_window':131073},False),
    ('composer','gpt-5.6-sol',{'input_budget':98305},False),
    ('composer','gpt-5.6-sol',{'output_headroom':16385},False),
])
def test_sol_transport_keeps_lane_scope_utf8_bound_and_reviewed_limits(scope, model, changes, allowed):
    from test_lifetime_memory_lane_engine import BUDGET, page, packet_for
    from apps.api.lifetime_memory_lane_engine import build_bounded_lane_input
    current = page(scope)
    phase = 'prepare' if scope == 'composer' else 'extract'
    budget = BUDGET.model_copy(update={'model':model, **changes})
    packet = packet_for(current, phase)
    if not allowed:
        with pytest.raises(ValueError, match='reviewed|bound'):
            build_bounded_lane_input(current, phase=phase, packet=packet, budget=budget)
        return
    bounded = build_bounded_lane_input(current, phase=phase, packet=packet, budget=budget)
    assert bounded.budget.count('雪🙂e\u0301') == 10
    assert bounded.budget.tokenizer == 'utf8-byte-upper-bound-v1'
