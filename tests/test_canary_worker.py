import asyncio
import json
from pathlib import Path
import sys
from uuid import uuid4

import pytest


def test_task_worker_pins_all_roles_and_forwards_root_and_background_links(tmp_path, monkeypatch):
    from apps.api.codex_worker_service import WorkerTurnInput
    from scripts.canary_worker import CanaryWorker

    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP', '1')
    monkeypatch.setenv('MEMORY_SPARK_MEMOIR_COMPOSER_MODEL', 'other-alias')
    control = tmp_path / 'control.json'
    audit = tmp_path / 'audit.jsonl'
    control.write_text(json.dumps({'reply': 'Controlled application reply.', 'audit': str(audit)}))
    correlation = {'run_id': str(uuid4()), 'case_id': 'harbour-copper-notebook',
        'round_id': '5', 'trace_id': 'a' * 32, 'observation_id': 'b' * 16,
        'job_id': str(uuid4()), 'checkpoint_id': 'harbour:5'}
    async def run():
        async def ready(reader, writer):
            writer.close()
            await writer.wait_closed()
        server = await asyncio.start_server(ready, '127.0.0.1', 0)
        async with server:
            worker = CanaryWorker(home_root=tmp_path / 'fresh-homes',
                base_url=f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1',
                evidence_mode='controlled_provider',
                command_prefix=[sys.executable, str(Path(__file__).parent /
                    'fixtures/canary_audited_app_server.py'), str(control)])
            for role in ('collector', 'workspace', 'memory_context', 'author_timeline', 'composer'):
                result = await worker.turn(WorkerTurnInput(user_id=uuid4(), text='Synthetic evidence',
                    agent_role=role, evaluation=correlation))
                assert result['reply'] == 'Controlled application reply.'
    asyncio.run(run())
    records = [json.loads(line) for line in audit.read_text().splitlines()]
    starts = [r for r in records if r.get('method') == 'thread/start']
    turns = [r for r in records if r.get('method') == 'turn/start']
    assert len(starts) == len(turns) == 5
    assert all(r['model'] == 'gpt-5.6-luna' for r in starts)
    assert all(r['metadata']['trace_id'] == 'a' * 32 for r in turns)
    assert all(r['metadata']['checkpoint_id'] == 'harbour:5' for r in turns)
    assert all(r['metadata']['job_id'] == correlation['job_id'] for r in turns)
    assert all(r['effort'] == 'low' for r in turns)
    options = records[0]['argv']
    assert 'model_providers.llm_provider.request_max_retries=0' in options
    assert 'model_providers.llm_provider.stream_max_retries=0' in options
    assert 'model_providers.llm_provider.supports_websockets=false' in options
    assert 'memories.generate_memories=false' in options
    assert all(r['key_is_synthetic'] for r in records if 'key_is_synthetic' in r)


def test_live_worker_or_shared_route_is_rejected_before_creating_home(tmp_path):
    from scripts.canary_worker import CanaryWorker
    for mode, url in [('live_model', 'http://127.0.0.1:45678/v1'),
                      ('controlled_provider', 'http://127.0.0.1:4000/v1'),
                      ('controlled_provider', 'http://127.0.0.1:2455/v1')]:
        with pytest.raises(ValueError):
            CanaryWorker(home_root=tmp_path / 'untouched', base_url=url, evidence_mode=mode)
        assert not (tmp_path / 'untouched').exists()


def test_controlled_label_cannot_select_the_real_codex_binary(tmp_path):
    from scripts.canary_worker import CanaryWorker
    for prefix in (None, ['codex'], ['/arbitrary/app-server']):
        with pytest.raises(ValueError):
            CanaryWorker(home_root=tmp_path / 'untouched',
                base_url='http://127.0.0.1:45678/v1', evidence_mode='controlled_provider',
                command_prefix=prefix)
        assert not (tmp_path / 'untouched').exists()


def test_canary_serializes_roles_and_stops_queued_calls_after_failure(tmp_path, monkeypatch):
    from apps.api.codex_worker_service import CodexWorker, WorkerTurnInput
    from scripts.canary_worker import CanaryWorker
    worker = CanaryWorker(home_root=tmp_path / 'task-homes', base_url='http://127.0.0.1:45678/v1',
        evidence_mode='controlled_provider', command_prefix=[sys.executable,
            str(Path(__file__).parent / 'fixtures/issue6_controlled_app_server.py'), str(tmp_path / 'unused')])
    calls = []
    async def failing(self, payload, **kwargs):
        calls.append(payload.agent_role)
        await asyncio.sleep(.02)
        raise RuntimeError('synthetic failure')
    monkeypatch.setattr(CodexWorker, 'turn', failing)
    async def scenario():
        results = await asyncio.gather(*(worker.turn(WorkerTurnInput(user_id=uuid4(),
            text='Synthetic evidence', agent_role=role)) for role in ('collector', 'workspace')),
            return_exceptions=True)
        assert all(isinstance(result, RuntimeError) for result in results)
    asyncio.run(scenario())
    assert calls == ['collector']
    with pytest.raises(ValueError, match='verified provider'):
        worker.assert_live_ready()


def test_canary_never_adopts_an_inherited_customer_home(tmp_path, monkeypatch):
    from scripts.canary_worker import CanaryWorker
    monkeypatch.setenv('MEMORY_SPARK_LEGACY_CODEX_HOME', str(tmp_path / 'protected-customer-home'))
    worker = CanaryWorker(home_root=tmp_path / 'task-homes', base_url='http://127.0.0.1:45678/v1',
        evidence_mode='controlled_provider', command_prefix=[sys.executable,
            str(Path(__file__).parent / 'fixtures/issue6_controlled_app_server.py'), str(tmp_path / 'unused')])
    assert worker.legacy_root is None


def test_resource_failure_stops_worker_before_any_codex_process(tmp_path, monkeypatch):
    from apps.api.codex_worker_service import CodexWorker, WorkerTurnInput
    from scripts.canary_worker import CanaryWorker
    worker = CanaryWorker(home_root=tmp_path / 'task-homes', base_url='http://127.0.0.1:45678/v1',
        evidence_mode='controlled_provider', command_prefix=[sys.executable,
            str(Path(__file__).parent / 'fixtures/issue6_controlled_app_server.py'), str(tmp_path / 'unused')])
    def blocked(): raise RuntimeError('controlled resource pressure')
    worker.before_dispatch = blocked
    async def forbidden(*args, **kwargs): pytest.fail('Blocked resource gate reached Codex')
    monkeypatch.setattr(CodexWorker, 'turn', forbidden)
    with pytest.raises(RuntimeError, match='resource pressure'):
        asyncio.run(worker.turn(WorkerTurnInput(user_id=uuid4(), text='Synthetic evidence')))
    assert worker._stopped is True
