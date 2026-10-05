"""Task-owned native canonical fixture, with a controlled external provider.

No live adapter is selectable here. The model process is the checked-in
synthetic app-server protocol, not Codex or a configured provider. Model token
ceilings are therefore exactly zero; protocol/worker contacts are counted
separately. Fixture receipts cannot establish model quality or live acceptance.
"""
import asyncio
import json
import os
import signal
from pathlib import Path
import sys
import tempfile
import time
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]


def save(path, value):
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


async def run_fixture(plan, run_dir, *, max_worker_requests, deadline):
    started = time.monotonic()
    receipt = {'schema_version': 'memoir-canonical-native-fixture/1',
        'run_id': plan['run_id'], 'status': 'blocked', 'evidence_mode': 'mock_only',
        'execution_started': False, 'resources_allocated': False,
        'provider_requests_started': 0, 'provider_input_tokens': 0, 'provider_output_tokens': 0,
        'fixture_protocol_calls': 0, 'private_worker_requests_started': 0,
        'limits': plan['execution_limits'],
        'application_revision': plan['application_revision'], 'dataset': plan['dataset'],
        'skill_manifest': plan['skill_manifest'], 'cases': [], 'cleanup': {},
        'live_acceptance': 'not_run', 'model_output_quality': 'unavailable',
        'judge': 'not_run', 'photo': 'not_run', 'geocoding': 'not_run',
        'langfuse': 'not_published'}
    summary_path = run_dir / 'summary.json'
    if time.monotonic() >= deadline:
        receipt['blockers'] = ['fixture_time_limit_reached_before_allocation']
        save(summary_path, receipt)
        return receipt

    # Remove configured authentication before importing the native test harness.
    # Every worker receives a fresh task home and a fixed synthetic command.
    from scripts.run_isolated_check import offline_environment
    environment = offline_environment(ROOT)
    environment = {key: value for key, value in environment.items() if key in
        {'PATH', 'HOME', 'TMPDIR', 'USER', 'LOGNAME', 'LANG', 'LC_ALL', 'SHELL', 'NEXT_TELEMETRY_DISABLED'}}
    workspace_manager = tempfile.TemporaryDirectory(prefix='memoir-canonical-', dir='/tmp')
    workspace = Path(workspace_manager.name)
    os.environ.clear()
    os.environ.update(environment)
    os.environ.update(MEMOIR_TEST_POSTGRES_BACKEND='apple-container',
        MEMORY_SPARK_DISABLE_PRIVDROP='1', STRIPE_PRICE_FAMILY='synthetic-price',
        MEMORY_SPARK_PRIVATE_DRAFT_CADENCE='5', MEMORY_SPARK_LLM_API_KEY='synthetic-only',
        MEMORY_SPARK_LLM_MODEL='synthetic-protocol',
        MEMORY_SPARK_MEMOIR_COMPOSER_MODEL='synthetic-protocol',
        MEMORY_SPARK_TEST_MODE='1', MEMORY_SPARK_ENTITLEMENT_MODEL='legacy',
        MEMORY_SPARK_TASK_DB=str(workspace / 'tasks.sqlite'),
        MEMORY_SPARK_DATABASE=str(workspace / 'application.sqlite'))
    # Reuse the existing stock postgres:18.3 / container-exec psql fixture.
    # It uses UUID names, no TCP, mounts or published ports, and exact cleanup.
    sys.path.insert(0, str(ROOT / 'tests'))
    try:
        from test_shared_memory_events_postgres import (
            database, attachment_database, private_database, event_database)
        from memoir_postgres_workflow import PostgresRest, quoted
        import httpx
        from fastapi import FastAPI
        from temporalio import activity
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker
        from apps.api.codex_runtime import CodexRuntime
        from apps.api.codex_worker_service import CodexWorker, WorkerTurnInput
        from apps.api.memory_event_worker import MemoirLaneBroker, MemoryEventWorker
        from apps.api.temporal_workflows import MemoirSkillLane
        from apps.api.trajectory_evaluation import evaluate_trajectory
        from scripts.canonical_evaluation import CanonicalEvaluationDriver
        from scripts.evaluation_budget import RequestLimitedTransport

    except Exception as error:
        receipt['status'] = 'incomplete'
        receipt['error_class'] = type(error).__name__
        workspace_manager.cleanup()
        receipt['cleanup']['workspace_removed'] = True
        save(summary_path, receipt)
        return receipt

    generator = database.__wrapped__()
    transport, readiness, temporal = None, None, None
    postgres_name = 'memoir-issue6-pg-' + uuid4().hex[:12]
    os.environ['MEMOIR_TEST_POSTGRES_CONTAINER_NAME'] = postgres_name
    receipt['postgres_container'] = postgres_name
    # Publish the exact task identity before allocation so interrupted startup
    # can be reconciled without discovering or stopping any other container.
    loop = asyncio.get_running_loop()
    owner_task = asyncio.current_task()
    previous_sigterm = signal.getsignal(signal.SIGTERM)
    loop.add_signal_handler(signal.SIGTERM, owner_task.cancel)
    receipt['execution_started'] = True
    save(summary_path, receipt)
    try:
        sql = next(generator)
        receipt['resources_allocated'] = True
        if sql.command[3] != postgres_name:
            raise RuntimeError('Native fixture container identity differs from the receipt')
        save(summary_path, receipt)
        sql = event_database.__wrapped__(private_database.__wrapped__(
            attachment_database.__wrapped__(sql)))
        for case in plan['cases']:
            sql(f"insert into auth.users(id,is_anonymous) values ({quoted(case['owner_id'])},false);")
        if time.monotonic() >= deadline:
            raise TimeoutError('Fixture deadline expired during setup')

        async def ready(reader, writer):
            writer.close()
            await writer.wait_closed()
        readiness = await asyncio.start_server(ready, '127.0.0.1', 0)
        base_url = f'http://127.0.0.1:{readiness.sockets[0].getsockname()[1]}/v1'
        app = FastAPI()
        originals = {case['project_id']: case['rounds'][0] for case in plan['cases']}
        provider_records = []

        @app.post('/internal/codex/turn')
        async def turn(payload: WorkerTurnInput):
            index = len(provider_records) + 1
            # Read only application-visible sources. No expected/truth
            # document is loaded into any runtime or provider packet.
            if payload.agent_role == 'author_timeline':
                packet = json.loads(payload.text)
                first = [s for s in packet['sources'] if s['sequence'] == 1]
                events = [] if packet['events'] else [
                    {'kind': 'event', 'title': s['text'][:300], 'source_refs':
                     [{'source_id': s['id'], 'version': s['version'], 'quote': s['text']}]} for s in first]
                control = {'reply': {'events': events}}
            elif payload.agent_role == 'composer':
                original = originals[payload.project_id]
                control = {'mode': 'composer', 'calls': str(workspace / 'composer.jsonl'),
                    'prose': original, 'summary': original,
                    'title': '回忆' if payload.language == 'zh-CN' else 'Memory'}
            else:
                control = {'reply': '请继续说。' if payload.language == 'zh-CN' else 'Tell me more.'}
            control_path = workspace / f'provider-{index}.json'
            control_path.write_text(json.dumps(control, ensure_ascii=False), encoding='utf-8')
            record = {'project_id': payload.project_id, 'agent_role': payload.agent_role,
                      'composer_phase': payload.composer_phase, 'status': 'started'}
            provider_records.append(record)
            receipt['fixture_protocol_calls'] = len(provider_records)
            save(run_dir / 'worker-receipts.json', provider_records)
            save(summary_path, receipt)
            provider = CodexWorker(home_root=workspace / 'worker-homes', base_url=base_url,
                model='synthetic-protocol', timeout=30,
                command=[sys.executable, str(ROOT / 'tests/fixtures/issue6_controlled_app_server.py'),
                         str(control_path)])
            result = await provider.turn(payload)
            record['status'] = 'completed'
            record['trajectory'] = result.get('trajectory')
            save(run_dir / 'worker-receipts.json', provider_records)
            return result

        transport = RequestLimitedTransport(httpx.ASGITransport(app=app),
            max_requests=max_worker_requests, max_elapsed_seconds=deadline - time.monotonic())
        runtime = CodexRuntime(home_root=workspace / 'api-homes', base_url=base_url,
            model='synthetic-protocol', worker_url='http://controlled.invalid',
            worker_secret='synthetic-only', worker_transport=transport, task_publisher_enabled=False)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Fixture deadline expired before Temporal startup')
        async with asyncio.timeout(remaining):
            temporal = await WorkflowEnvironment.start_local(download_dest_dir='/tmp/memoir-issue6-temporal',
                dev_server_database_filename=str(workspace / 'temporal.sqlite'), ip='127.0.0.1', ui=False)
            async with httpx.AsyncClient(transport=httpx.MockTransport(
                    PostgresRest(sql, plan['cases'][0]['owner_id'], service=True).handle)) as db:
                broker = MemoirLaneBroker(url='http://synthetic.invalid', key='synthetic-only', client=db)
                worker = MemoryEventWorker(broker, worker_url='http://controlled.invalid',
                    worker_secret='synthetic-only', worker_transport=transport)
                @activity.defn(name='memoir.execute_lane')
                async def execute(lane_id: str):
                    result = await worker.execute_lane(lane_id)
                    state = await broker.rpc('read_memoir_lane_state', p_lane_id=lane_id)
                    return {'status': result['status'], 'pending': state['pending']}
                queue = 'canonical-fixture-' + plan['run_id']
                async with Worker(temporal.client, task_queue=queue,
                        workflows=[MemoirSkillLane], activities=[execute]):
                    for case in plan['cases']:
                        case_dir = run_dir / 'cases' / case['case_id']
                        case_dir.mkdir(parents=True)
                        entitlement = {'status': 'paid', 'plan_key': 'family_memoir_v1',
                            'family_tree': True, 'timeline': True, 'stripe_price_id': 'synthetic-price'}
                        storage = PostgresRest(sql, case['owner_id'], entitlement=entitlement).storage()
                        partial = {'case_id': case['case_id'], 'owner_id': case['owner_id'],
                            'project_id': case['project_id'], 'status': 'started', 'rounds': [], 'checkpoints': []}
                        receipt['cases'].append(partial)
                        async def progress(value):
                            partial.update(value)
                            save(case_dir / 'receipt.json', partial)
                            save(summary_path, receipt)
                        try:
                            storage.save_profile({'preferred_language': case['language'],
                                'conversation_language': {'locale': case['language'], 'source': 'explicit', 'revision': 1}})
                            driver = CanonicalEvaluationDriver(storage=storage, runtime=runtime,
                                broker=broker, temporal_client=temporal.client, task_queue=queue)
                            result = await driver.run_case(case_id=case['case_id'], project_id=case['project_id'],
                                rounds=case['rounds'], language=case['language'], evidence_mode='mock_only',
                                settle_timeout=min(60, max(.001, deadline - time.monotonic())), progress=progress)
                            partial.update(result)
                            partial['canonical_state'] = await asyncio.to_thread(storage.memory_events, case['project_id'])
                            partial['deterministic_trajectory_evaluation'] = [
                                {'round': r['round'], 'evidence_mode': 'mock_only',
                                 'scores': evaluate_trajectory(r.get('trajectory') or {})} for r in result['rounds']]
                            partial['model_output_quality'] = 'unavailable'
                            save(case_dir / 'receipt.json', partial)
                            save(summary_path, receipt)
                        except BaseException:
                            partial['status'] = 'incomplete'
                            try:
                                partial['canonical_state'] = await asyncio.to_thread(storage.memory_events, case['project_id'])
                            except Exception as error:
                                partial['state_readback_error_class'] = type(error).__name__
                            save(case_dir / 'receipt.json', partial)
                            raise
                        finally:
                            storage.client.close()
        receipt['status'] = 'completed'
        receipt['blockers'] = ['live_model_acceptance_not_run', 'accepted_judge_calibration_unavailable']
        save(run_dir / 'worker-receipts.json', provider_records)
    except (Exception, asyncio.CancelledError) as error:
        receipt['status'] = 'incomplete'
        receipt['error_class'] = type(error).__name__
    finally:
        if transport is not None:
            receipt['private_worker_requests_started'] = transport.requests_started
            await transport.transport.aclose()
        for label, resource in [('temporal', temporal), ('readiness', readiness)]:
            if resource is None:
                continue
            try:
                if label == 'temporal':
                    await resource.shutdown()
                else:
                    resource.close()
                    await resource.wait_closed()
                receipt['cleanup'][label + '_closed'] = True
            except Exception as error:
                receipt['cleanup'][label + '_closed'] = False
                receipt['cleanup'][label + '_error_class'] = type(error).__name__
                receipt['status'] = 'incomplete'
        try:
            generator.close()
            receipt['cleanup']['postgres_fixture_closed'] = True
        except Exception as error:
            receipt['cleanup']['postgres_fixture_closed'] = False
            receipt['cleanup']['postgres_error_class'] = type(error).__name__
            receipt['status'] = 'incomplete'
        if workspace_manager is not None:
            try:
                workspace_manager.cleanup()
                receipt['cleanup']['workspace_removed'] = True
            except Exception as error:
                receipt['cleanup']['workspace_removed'] = False
                receipt['cleanup']['workspace_error_class'] = type(error).__name__
                receipt['status'] = 'incomplete'
        loop.remove_signal_handler(signal.SIGTERM)
        signal.signal(signal.SIGTERM, previous_sigterm)
        receipt['elapsed_seconds'] = round(time.monotonic() - started, 3)
        save(summary_path, receipt)
    return receipt
