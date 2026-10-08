#!/usr/bin/env python3
"""Explicit, one-shot existing-subscription evaluation; default is plan only.

Separate from the historical strict-budget launcher. Execution requires an exact
reviewed clean source head, existing pinned binaries and existing app gateway
configuration. No provider/account switching, installation or credential setup.
"""
import argparse
import asyncio
from contextlib import asynccontextmanager, contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import threading
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
EXISTING_ORIGIN = 'http://192.168.66.1:4000/v1'


def _binary(path, digest):
    path = Path(path)
    if (not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK)
            or type(digest) is not str or not re.fullmatch('[a-f0-9]{64}', digest)
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
        raise ValueError('An exact existing reviewed executable is required')
    return str(path)


def build_plan(*, run_id, source_revision, codex_binary, codex_sha256,
               temporal_binary, temporal_sha256, max_client_requests, max_elapsed_seconds):
    from scripts.issue14_progressive_readback import case_plans_for_run
    if (type(run_id) is not str or str(UUID(run_id)) != run_id or type(source_revision) is not str
            or not re.fullmatch('[0-9a-f]{40}', source_revision)
            or type(max_client_requests) is not int or not 0 < max_client_requests <= 160
            or type(max_elapsed_seconds) not in (int, float) or not math.isfinite(max_elapsed_seconds)
            or not 0 < max_elapsed_seconds <= 1800):
        raise ValueError('Explicit approved case/request/time bounds required')
    cases = case_plans_for_run(run_id)
    return {'schema_version': 'memoir-subscription-evaluation-plan/1', 'run_id': run_id,
        'source_revision': source_revision, 'case_ids': list(cases), 'cases': cases,
        'rounds_per_case': 15, 'checkpoints': [5, 10, 15], 'concurrency': 1,
        'max_client_requests': max_client_requests, 'max_elapsed_seconds': max_elapsed_seconds,
        'codex_binary': _binary(codex_binary, codex_sha256), 'codex_sha256': codex_sha256,
        'temporal_binary': _binary(temporal_binary, temporal_sha256), 'temporal_sha256': temporal_sha256,
        'gateway_origin': EXISTING_ORIGIN, 'execution_started': False,
        'counted_boundary': 'client_to_existing_gateway_http_requests',
        'actual_upstream_provider_requests': None, 'hard_token_cap_verified': False,
        'hard_dollar_cap_verified': False, 'upstream_cancellation_verified': False,
        'judge': 'not_run', 'langfuse': 'not_published', 'photo': 'not_run'}


def git_read(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()


def verify_source(revision):
    if (git_read('rev-parse', 'HEAD') != revision
            or git_read('status', '--porcelain', '--untracked-files=no')
            or any(path.endswith('.py') for path in git_read('ls-files', '--others', '--exclude-standard').splitlines())):
        raise ValueError('Exact reviewed clean source required')
    # Git status can hide changes behind assume-unchanged/skip-worktree flags or
    # cached stat data. Independently hash every tracked blob, not only Python.
    index = git_read('ls-files', '-v').splitlines()
    if any(not entry.startswith('H ') for entry in index):
        raise ValueError('Hidden Git index flags are forbidden')
    raw = subprocess.check_output(['git','ls-tree','-rz',revision], cwd=ROOT)
    for entry in raw.split(b'\0'):
        if not entry:
            continue
        metadata, name = entry.split(b'\t',1)
        mode, kind, expected = metadata.split()
        path = ROOT / os.fsdecode(name)
        if (kind != b'blob' or mode not in (b'100644',b'100755')
                or path.is_symlink() or not path.is_file()
                or any(parent.is_symlink() for parent in path.parents if parent != ROOT and ROOT in parent.parents)):
            raise ValueError('Ordinary reviewed source blobs required')
        content = path.read_bytes()
        actual = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
        if actual.encode() != expected:
            raise ValueError('Tracked source differs from reviewed Git blob')


def require_absent_container(name):
    if not re.fullmatch(r'memoir-issue6-pg-[a-f0-9]{12}', name):
        raise ValueError('Owned UUID container name required')
    # Discard stdout, which may contain container configuration. Only the
    # bounded exact-name absence error is inspected; uncertainty is not absence.
    result = subprocess.run(['container','inspect',name], stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE, text=True, timeout=8, check=False)
    if result.returncode == 0 or f'container not found: {name}' not in result.stderr.lower():
        raise ValueError('Owned container name is present or unverified')


@contextmanager
def postgres_fixture_ownership(database_function, name):
    """Narrow the unchanged fixture's process adapter in this one-shot process.

    Its historical error cleanup stops a requested name even after failed create.
    Suppress that stop unless this invocation observed successful creation. An
    uncertain create may leave an orphan for explicit reconciliation; it never
    licenses stopping another worker's container with the same name.
    """
    namespace = database_function.__globals__
    original = namespace['ProcessDeadline']
    ownership = {'creation_confirmed': False, 'creation_uncertain': False,
                 'unowned_stop_suppressed': False, 'stop_attempted': False}
    class OwnedDeadline(original):
        def run(self, command, **kwargs):
            if command[:2] == ['container','run']:
                require_absent_container(name)
                if command[command.index('--name')+1] != name or ownership['creation_confirmed']:
                    raise RuntimeError('Container creation scope mismatch')
                try:
                    result = super().run(command, **kwargs)
                except BaseException:
                    ownership['creation_uncertain'] = True
                    raise
                ownership['creation_confirmed'] = result.returncode == 0
                ownership['creation_uncertain'] = result.returncode != 0
                return result
            if command[:2] == ['container','stop']:
                if command[2:] != [name] or not ownership['creation_confirmed'] or ownership['stop_attempted']:
                    ownership['unowned_stop_suppressed'] = True
                    raise RuntimeError('Unowned container cleanup forbidden')
                ownership['stop_attempted'] = True
            return super().run(command, **kwargs)
    namespace['ProcessDeadline'] = OwnedDeadline
    try:
        yield ownership
    finally:
        namespace['ProcessDeadline'] = original


def configured_credential():
    # Called only in the explicitly authorized one-shot native process. Never
    # print/store it, accept it in argv, discover another account, or create one.
    if os.environ.get('MEMORY_SPARK_LLM_BASE_URL', '').rstrip('/') != EXISTING_ORIGIN:
        raise ValueError('Existing gateway route must match the reviewed route')
    expected = {'MEMORY_SPARK_LLM_MODEL': 'gpt-5.6-luna-pooled',
        'MEMORY_SPARK_LLM_REASONING_EFFORT': 'max',
        'MEMORY_SPARK_MEMOIR_COMPOSER_MODEL': 'memoir-luna-low',
        'MEMORY_SPARK_MEMOIR_COMPOSER_REASONING_EFFORT': 'low',
        'MEMORY_SPARK_AUTHOR_TIMELINE_REASONING_EFFORT': 'low'}
    if any(os.environ.get(key) not in (None, '', value) for key, value in expected.items()):
        raise ValueError('Existing model profile differs from reviewed profile')
    value = os.environ.get('MEMORY_SPARK_LLM_API_KEY')
    if not value or len(value) > 8192 or '\r' in value or '\n' in value:
        raise ValueError('Existing application gateway credential unavailable')
    return value


def load_existing_application_env(path):
    """Privately load only the authorized existing app's provider configuration.

    No shell evaluation/interpolation, credential argument, secret output or
    persistent rewrite. Only the one-shot Mac process invokes this function.
    """
    from io import StringIO
    from dotenv import dotenv_values
    allowed = {'MEMORY_SPARK_LLM_BASE_URL', 'MEMORY_SPARK_LLM_API_KEY',
        'MEMORY_SPARK_LLM_MODEL', 'MEMORY_SPARK_LLM_REASONING_EFFORT',
        'MEMORY_SPARK_MEMOIR_COMPOSER_MODEL', 'MEMORY_SPARK_MEMOIR_COMPOSER_REASONING_EFFORT',
        'MEMORY_SPARK_AUTHOR_TIMELINE_REASONING_EFFORT'}
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) not in (0o400, 0o600) or info.st_size > 1024 * 1024):
            raise ValueError()
        with os.fdopen(descriptor, encoding='utf-8') as stream:
            descriptor = None
            content = stream.read(1024 * 1024 + 1)
        if len(content.encode()) > 1024 * 1024:
            raise ValueError()
        values = dotenv_values(stream=StringIO(content), interpolate=False)
        selected = {key: value for key, value in values.items() if key in allowed and type(value) is str}
        if (selected.get('MEMORY_SPARK_LLM_BASE_URL', '').rstrip('/') != EXISTING_ORIGIN
                or not selected.get('MEMORY_SPARK_LLM_API_KEY')):
            raise ValueError()
        # Selecting a file is a distinct configuration source, not permission to
        # silently mix in another inherited credential/model profile.
        for key in allowed:
            os.environ.pop(key, None)
        os.environ.update(selected)
    except Exception:
        raise ValueError('Existing private application environment unavailable') from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _save(path, value):
    from scripts.run_isolated_check import save_receipt
    save_receipt(path, value)


def invalidate_native_receipt(receipt, reason):
    receipt.update(status='incomplete', stop_reason=reason)
    for key in ('evaluation', 'evaluation_progress'):
        if type(receipt.get(key)) is dict:
            result = receipt[key]
            result.update(status='incomplete', output=None)
            for case in result.get('cases', []):
                if type(case.get('observation')) is dict:
                    case['observation']['output'] = None


def native_environment(directory, run_id):
    """Private Mac fixture options only; no inherited authentication or services."""
    from scripts.run_isolated_check import offline_environment
    environment = offline_environment(ROOT)
    environment.update(MEMOIR_TEST_POSTGRES_BACKEND='apple-container',
        MEMOIR_TEST_POSTGRES_CONTAINER_NAME='memoir-issue6-pg-' + run_id.replace('-', '')[:12],
        MEMORY_SPARK_PRIVATE_DRAFT_CADENCE='5', MEMORY_SPARK_DISABLE_PRIVDROP='1',
        MEMORY_SPARK_LLM_MODEL='gpt-5.6-luna-pooled', MEMORY_SPARK_LLM_REASONING_EFFORT='max',
        MEMORY_SPARK_MEMOIR_COMPOSER_MODEL='memoir-luna-low',
        MEMORY_SPARK_MEMOIR_COMPOSER_REASONING_EFFORT='low',
        MEMORY_SPARK_AUTHOR_TIMELINE_REASONING_EFFORT='low',
        MEMORY_SPARK_CODEX_HOME=str(directory / 'unused-module-worker'),
        MEMORY_SPARK_TASK_DB=str(directory / 'tasks.sqlite'),
        MEMORY_SPARK_DATABASE=str(directory / 'application.sqlite'))
    return environment


def native_cleanup_complete(native, cleanup_failed):
    return (not cleanup_failed and not native['ownership']['creation_uncertain']
        and (not native['postgres_allocation']['created'] or native['postgres_removed'] is True)
        and (not native.get('temporal_start_attempted') or native['temporal_stopped'] is True))


@asynccontextmanager
async def native_resources(plan, run, directory, receipt):
    """Own only one disposable PG container and loopback Temporal process."""
    import httpx
    from temporalio.testing import WorkflowEnvironment
    from apps.api.memory_event_worker import MemoirLaneBroker
    from scripts.native_canary_launcher import resource_gate
    # This is a dedicated process. Remove inherited service/auth configuration;
    # the one existing provider credential stays only in execute_native's local.
    environment = native_environment(directory, plan['run_id'])
    postgres_name = 'memoir-issue6-pg-' + plan['run_id'].replace('-', '')[:12]
    os.environ.clear(); os.environ.update(environment)
    sys.path.insert(0, str(ROOT / 'tests'))
    from test_shared_memory_events_postgres import database, attachment_database, private_database, event_database
    from memoir_postgres_workflow import PostgresRest, quoted
    cancellation = threading.Event()
    allocation = {'attempted': False, 'created': False}
    receipt['native'] = {'postgres_container': postgres_name, 'postgres_allocation': allocation,
        'rest_auth_facade': 'synthetic_PostgresRest', 'entitlement': 'free',
        'temporal': 'owned_loopback', 'postgres_removed': False, 'temporal_stopped': False,
        'temporal_start_attempted': False}
    def record():
        _save(directory / 'receipt.json', receipt)
    receipt['resource_gate'] = resource_gate()
    require_absent_container(postgres_name)
    record()
    ownership_scope = postgres_fixture_ownership(database.__wrapped__, postgres_name)
    receipt['native']['ownership'] = ownership_scope.__enter__()
    generator = database.__wrapped__(deadline=run.deadline, cancellation=cancellation,
                                     allocation=allocation, on_allocation=record)
    setup_task = temporal = broker = None
    storages = {}
    def setup():
        sql = next(generator)
        if sql.command[3] != postgres_name:
            raise ValueError('Owned PostgreSQL identity differs')
        sql = event_database.__wrapped__(private_database.__wrapped__(attachment_database.__wrapped__(sql)))
        for case in plan['cases'].values():
            sql(f"insert into auth.users(id,is_anonymous) values ({quoted(case['owner_id'])},false);")
        return sql
    try:
        setup_task = asyncio.create_task(asyncio.to_thread(setup))
        sql = await asyncio.shield(setup_task)
        receipt['resource_gate'] = resource_gate()
        receipt['native']['temporal_start_attempted'] = True
        temporal = await WorkflowEnvironment.start_local(
            dev_server_existing_path=plan['temporal_binary'],
            dev_server_database_filename=str(directory / 'temporal.sqlite'), ip='127.0.0.1', ui=False)
        for case_id, case in plan['cases'].items():
            storage = PostgresRest(sql, case['owner_id']).storage()
            storage.save_profile({'preferred_language': case['language'], 'conversation_language':
                {'locale': case['language'], 'source': 'explicit', 'revision': 1}})
            storages[case_id] = storage
        client = httpx.AsyncClient(transport=httpx.MockTransport(
            PostgresRest(sql, next(iter(plan['cases'].values()))['owner_id'], service=True).handle))
        broker = MemoirLaneBroker(url='http://synthetic.invalid', key='synthetic-service', client=client)
        yield {'storages': storages, 'broker': broker, 'temporal_client': temporal.client}
    finally:
        cancellation.set()
        cleanup_failed = False
        if setup_task is not None and not setup_task.done():
            # The fixture cancellation/deadline terminates its owned commands.
            # Join the thread before closing its generator or removing resources.
            try:
                from scripts.issue14_subscription_runner import _settle_task
                await _settle_task(setup_task)
            except BaseException:
                pass
        if temporal is not None:
            try:
                await temporal.shutdown()
                receipt['native']['temporal_stopped'] = True
            except BaseException:
                cleanup_failed = True
        if broker is not None:
            try:
                await broker.client.aclose()
            except BaseException:
                cleanup_failed = True
        for storage in storages.values():
            try:
                storage.client.close()
            except BaseException:
                cleanup_failed = True
        had_live_generator = generator.gi_frame is not None
        try:
            await asyncio.to_thread(generator.close)
            receipt['native']['postgres_removed'] = (
                True if allocation['created'] and had_live_generator else None if allocation['created'] else False)
        except BaseException:
            cleanup_failed = True
            receipt['native']['postgres_removed'] = None
        finally:
            ownership_scope.__exit__(None,None,None)
        receipt['native']['cleanup_complete'] = native_cleanup_complete(receipt['native'], cleanup_failed)
        record()
        if not receipt['native']['cleanup_complete']:
            raise RuntimeError('Owned native cleanup incomplete') from None


async def execute_native(plan, directory, api_key):
    from scripts.issue14_subscription_transport import SubscriptionLimits, SubscriptionRun, SubscriptionTransport
    from scripts.issue14_subscription_session import OwnedSubscriptionSession
    from scripts.issue14_subscription_runner import SubscriptionProgressiveRunner
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    (directory / 'journal').mkdir(mode=0o700)
    _save(directory / 'plan.json', plan)
    run = SubscriptionRun.create(reservation_root=directory / 'journal', run_id=plan['run_id'],
        source_revision=plan['source_revision'], limits=SubscriptionLimits(
            plan['max_client_requests'], plan['max_elapsed_seconds']))
    receipt = {'schema_version': 'memoir-subscription-native-receipt/1', 'run_id': plan['run_id'],
        'source_revision': plan['source_revision'], 'status': 'incomplete', 'execution_started': True,
        'judge': 'not_run', 'langfuse': 'not_published', 'semantic_acceptance': 'human_review_required'}
    session = None
    transport = SubscriptionTransport.existing_route(run=run, authorization='Bearer ' + api_key)
    try:
        async with asyncio.timeout(run.remaining_seconds()):
            async with native_resources(plan, run, directory, receipt) as resources:
                session = await OwnedSubscriptionSession.create(run=run, provider_transport=transport,
                    **resources, home_root=directory / 'homes', codex_binary=plan['codex_binary'],
                    codex_sha256=plan['codex_sha256'], api_key=api_key)
                def progress(value):
                    receipt['evaluation_progress'] = value
                    _save(directory / 'receipt.json', receipt)
                result = await SubscriptionProgressiveRunner(session).run(progress=progress)
                receipt['evaluation'] = result
                receipt['worker_receipts'] = session.worker_receipts()
                receipt['status'] = result['status']
    except BaseException as error:
        # Error bodies can contain source text, headers or credentials.
        invalidate_native_receipt(receipt,
            'cancelled' if isinstance(error, asyncio.CancelledError) else 'native_execution_failed')
        try:
            run.stop('send_interrupted_or_failed')
        except Exception:
            pass
    finally:
        try:
            if session is not None:
                await session.close()
            else:
                await transport.aclose()
                run.close()
        except BaseException:
            invalidate_native_receipt(receipt, 'native_cleanup_failed')
        receipt['request_accounting'] = run.snapshot()
        _save(directory / 'receipt.json', receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-existing-subscription', action='store_true')
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--source-revision', required=True)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--existing-app-env', type=Path)
    for name in ('codex', 'temporal'):
        parser.add_argument(f'--{name}-binary', type=Path, required=True)
        parser.add_argument(f'--{name}-sha256', required=True)
    parser.add_argument('--max-client-requests', type=int, required=True)
    parser.add_argument('--max-elapsed-seconds', type=float, required=True)
    args = parser.parse_args(argv)
    execution_started = False
    try:
        plan = build_plan(**{key: getattr(args, key) for key in ('run_id','source_revision',
            'codex_binary','codex_sha256','temporal_binary','temporal_sha256',
            'max_client_requests','max_elapsed_seconds')})
        if not args.execute_existing_subscription:
            print(json.dumps(plan, sort_keys=True))
            return 0
        verify_source(args.source_revision)
        if sys.platform != 'darwin':
            raise ValueError('This native bootstrap requires the authorized Mac fixture')
        from scripts.native_canary_launcher import resource_gate, native_resource_lease
        resource_gate()
        if args.run_dir.exists() or args.run_dir.is_symlink() or ROOT in args.run_dir.resolve().parents:
            raise ValueError('A fresh task output directory outside the source checkout is required')
        # Refuse silent stock-image installation. The native preflight must have
        # the supported fixture image and both executable pins already present.
        subprocess.run(['container','image','inspect','postgres:18.3'], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if args.existing_app_env is not None:
            load_existing_application_env(args.existing_app_env)
        api_key = configured_credential()
        async def scenario():
            task = asyncio.current_task()
            loop = asyncio.get_running_loop()
            loop.add_signal_handler(signal.SIGTERM, task.cancel)
            try:
                return await execute_native(plan, args.run_dir, api_key)
            finally:
                loop.remove_signal_handler(signal.SIGTERM)
        with native_resource_lease(args.run_id):
            resource_gate()
            execution_started = True
            result = asyncio.run(scenario())
        print(json.dumps({'run_id': result['run_id'], 'status': result['status'],
                          'receipt_path': str(args.run_dir / 'receipt.json')}))
        return 0 if result['status'] == 'completed' else 3
    except Exception:
        print(json.dumps({'status':'incomplete' if execution_started else 'blocked',
            'reason':'native_execution_failed' if execution_started else 'subscription_preflight_failed',
            'execution_started':execution_started}))
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
