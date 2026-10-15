"""One owned PostgreSQL + Temporal native test; external provider is controlled.

Run only in the parent's native resource window. This never calls a real model.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

import httpx
from temporalio.testing import WorkflowEnvironment
from temporal_test_server import local_options
from controlled_collector import extraction_proposal

from test_shared_memory_events_postgres import database, attachment_database, private_database, event_database, sql
from memoir_postgres_workflow import PostgresRest, quoted, seed_fresh_canonical_project


def test_ten_original_app_rounds_two_drafts_and_joined_single_attempt_jobs(sql, tmp_path, monkeypatch):
    from apps.api.memory_event_worker import MemoirLaneBroker
    from scripts.canary_app_launcher import run_application_canary
    from scripts.canary_worker import CanaryWorker
    from scripts.run_codexlb_canary import build_manifest
    root = Path(__file__).resolve().parents[1]
    plan = build_manifest(run_id=str(uuid4()), source_revision='a' * 40)
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB', str(tmp_path / 'tasks.sqlite'))
    monkeypatch.setenv('STRIPE_PRICE_FAMILY', 'synthetic-price')
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL', sql.publication_dsn)
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP', '1')
    storages = {}
    for case in plan['cases']:
        sql(f"insert into auth.users(id,is_anonymous) values ({quoted(case['owner_id'])},false);")
        seed_fresh_canonical_project(sql, case['owner_id'], case['project_id'])
        entitlement = {'status': 'paid', 'plan_key': 'family_memoir_v1',
                       'family_tree': case['family_enabled'], 'timeline': case['family_enabled'],
                       'stripe_price_id': 'synthetic-price'}
        storage = PostgresRest(sql, case['owner_id'], entitlement=entitlement).storage()
        storage.save_profile({'preferred_language': case['language'], 'conversation_language':
            {'locale': case['language'], 'source': 'explicit', 'revision': 1}})
        storages[case['project_id']] = storage
    control_path = tmp_path / 'provider-control.json'
    originals = {case['project_id']: case['rounds'][0].split(',')[0].split('，')[0] for case in plan['cases']}
    class ControlledWorker(CanaryWorker):
        control_lock = asyncio.Lock()
        async def turn(self, payload, **kwargs):
            # Only the external provider protocol is synthetic. The runtime,
            # worker, canonical source validators, PostgreSQL and Temporal run.
            async with self.control_lock:
                if payload.agent_role == 'author_timeline':
                    packet = json.loads(payload.bounded_lane.packet)['payload']
                    events = [] if packet['events'] else [{'kind': 'event', 'title': originals[payload.project_id],
                        'source_refs': [{'source_id': s['id'], 'version': s['version'], 'quote': originals[payload.project_id]}]}
                        for s in packet['sources'] if s['sequence'] == 1]
                    control = {'reply': {'events': events}}
                elif payload.agent_role == 'composer':
                    control = {'mode': 'composer', 'calls': str(tmp_path / 'composer.jsonl'),
                               'prose': originals[payload.project_id], 'summary': originals[payload.project_id],
                               'title': '回忆' if payload.language == 'zh-CN' else 'Memory'}
                elif payload.agent_role == 'collector':
                    control = {'reply': extraction_proposal(payload.language)}
                else:
                    control = {'reply': '请继续说。' if payload.language == 'zh-CN' else 'Tell me more.'}
                control_path.write_text(json.dumps(control, ensure_ascii=False))
                return await super().turn(payload, **kwargs)
    async def scenario():
        async def ready(reader, writer):
            writer.close()
            await writer.wait_closed()
        server = await asyncio.start_server(ready, '127.0.0.1', 0)
        options = local_options(tmp_path / 'temporal.sqlite')
        try:
            worker = ControlledWorker(home_root=tmp_path / 'worker-homes',
                base_url=f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1',
                evidence_mode='controlled_provider', canonical_model='synthetic-byte-bpe', command_prefix=[sys.executable,
                    str(root / 'tests/fixtures/issue6_controlled_app_server.py'), str(control_path)])
            if os.getenv('MEMOIR_NATIVE_RESOURCE_GATE') == '1':
                from scripts.native_canary_launcher import resource_gate
                resource_gate()
            async with await WorkflowEnvironment.start_local(**options) as env:
                async with httpx.AsyncClient(transport=httpx.MockTransport(
                        PostgresRest(sql, plan['cases'][0]['owner_id'], service=True).handle)) as client:
                    broker = MemoirLaneBroker(url='http://synthetic.invalid', key='synthetic-only', client=client)
                    result = await run_application_canary(plan, storages=storages, broker=broker,
                        temporal_client=env.client, worker=worker, run_dir=tmp_path / 'run')
                    assert result['status'] == 'app_completed_evidence_pending', result
                    assert result['provider_requests_started'] == 0
                    assert result['app_receipt']['evidence_mode'] == 'mock_only'
                    assert result['app_receipt']['requested_model'] == 'gpt-5.6-luna'
                    assert result['app_receipt']['effective_model'] == 'synthetic-byte-bpe'
                    assert len(result['round_roots']) == 10
                    assert all(r['status'] == 'completed' and r['background_job_ids'] for r in result['round_roots'])
                    assert all(c['draft_saved'] and c['draft']['coverage_round'] == 5 for c in result['checkpoints'])
                    assert result['app_receipt']['private_worker_requests_started'] <= 80
                    assert all(job['status'] == 'completed' for job in result['background_jobs'])
                    assert all(request['correlation']['trace_id'] for request in result['app_receipt']['worker_requests'])
                    for case in plan['cases']:
                        view = storages[case['project_id']].memory_events(case['project_id'])
                        assert [s['text'] for s in view['sources']] == case['rounds']
                        assert view['completed_rounds'] == view['processing']['extracted_through'] == 5
                    for job in result['background_jobs']:
                        history = await env.client.get_workflow_handle(job['workflow_id'], run_id=job['workflow_run_id']).fetch_history()
                        assert all(text.encode() not in b''.join(e.SerializeToString() for e in history.events)
                                   for case in plan['cases'] for text in case['rounds'])
        finally:
            server.close()
            await server.wait_closed()
            for storage in storages.values(): storage.client.close()
    asyncio.run(scenario())
