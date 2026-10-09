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
import time
from uuid import UUID, uuid5

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
EXISTING_ORIGIN = 'http://192.168.66.1:4000/v1'
ARTIFACT_STORAGE_LIMITS = {'max_artifact_bytes': 25 * 1024 * 1024,
    'max_objects_per_owner': 512, 'max_bytes_per_owner': 512 * 1024 * 1024}


def _binary(path, digest):
    path = Path(path)
    if (not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK)
            or type(digest) is not str or not re.fullmatch('[a-f0-9]{64}', digest)
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
        raise ValueError('An exact existing reviewed executable is required')
    return str(path)


def build_plan(*, run_id, source_revision, codex_binary, codex_sha256,
               temporal_binary, temporal_sha256, max_client_requests, max_elapsed_seconds,
               waive_memory_pressure_check=False, evaluation_profile='subscription_progressive',
               max_case_client_requests=None, max_case_elapsed_seconds=None,
               enable_public_photo_research=False, photo_python_binary=None, photo_python_sha256=None,
               enable_browser_readback=False, browser_config=None):
    from apps.api.codex_timeout_policy import native_worker_deadlines
    from scripts.memoir_subscription_profiles import profile_for
    profile = profile_for(evaluation_profile)
    profile.validate_limits(max_client_requests, max_elapsed_seconds,
                            max_case_client_requests, max_case_elapsed_seconds)
    if (type(run_id) is not str or str(UUID(run_id)) != run_id or type(source_revision) is not str
            or not re.fullmatch('[0-9a-f]{40}', source_revision)
            or type(waive_memory_pressure_check) is not bool):
        raise ValueError('Explicit approved case/request/time bounds required')
    browser = None
    if type(enable_browser_readback) is not bool:
        raise ValueError('Explicit browser policy required')
    if enable_browser_readback:
        if profile.name != 'subscription_fifty' or type(browser_config) is not dict:
            raise ValueError('Browser readback requires the explicit fifty profile and native config')
        from scripts.memoir_fifty_browser_runner import validate_browser_config
        browser = validate_browser_config(browser_config, source_revision=source_revision)
    elif browser_config is not None:
        raise ValueError('Browser config requires explicit admission')
    photo = None
    if type(enable_public_photo_research) is not bool:
        raise ValueError('Explicit public photo policy required')
    if enable_public_photo_research:
        if profile.name != 'subscription_fifty' or photo_python_binary is None or photo_python_sha256 is None:
            raise ValueError('Public photo research needs the explicit fifty profile and existing interpreter pin')
        photo = {'enabled': True, 'python_binary': _binary(photo_python_binary, photo_python_sha256),
            'python_sha256': photo_python_sha256, 'llm_search_enabled': False,
            'max_searches_per_case': 2, 'max_searches_global': 10,
            'counted_in_model_gateway_requests': False, 'real_storage_writes': False,
            'network_scope': 'counted_keyless_catalogues_only',
            'public_http_limit_search': 128, 'public_http_limit_case': 256,
            'public_http_limit_global': 1280,
            'photo_browser_providers': 'not_admitted_uncounted_browser_network'}
    elif photo_python_binary is not None or photo_python_sha256 is not None:
        raise ValueError('Photo interpreter pins need explicit photo research admission')
    cases = profile.plans(run_id)
    for case, details in cases.items():
        profile.bridge(case_id=case, run_id=run_id, project_id=details['project_id'],
                       source_revision=source_revision)
    return {'schema_version': 'memoir-subscription-evaluation-plan/1', 'run_id': run_id,
        'source_revision': source_revision, 'case_ids': list(cases), 'cases': cases,
        'evaluation_profile': profile.name, 'rounds_per_case': profile.rounds,
        'checkpoints': list(profile.checkpoints), 'concurrency': 1,
        'artifact_storage': {'backend': 'owned_disposable_postgres',
            'provider_free_readiness_required': True, 'real_storage_writes': False,
            **ARTIFACT_STORAGE_LIMITS},
        **({'photo_research': photo} if photo is not None else {}),
        **({'browser_readback': browser} if browser is not None else {}),
        **({'max_case_client_requests': max_case_client_requests,
            'max_case_elapsed_seconds': max_case_elapsed_seconds,
            'synthetic_entitlement': 'disposable_facade_only',
            'dataset_version': profile.dataset_version, 'dataset_sha256': profile.dataset_sha256}
           if profile.name == 'subscription_fifty' else {}),
        'memory_pressure_check_waived': waive_memory_pressure_check,
        'worker_deadlines': native_worker_deadlines(),
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


def load_existing_application_env(path, *, include_public_photo_settings=False):
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
    if type(include_public_photo_settings) is not bool:
        raise ValueError('Explicit public photo environment policy required')
    if include_public_photo_settings:
        # Only existing non-secret search configuration. Never import a new
        # provider credential or a shared photo-worker/Supabase endpoint.
        allowed.update({'GOOGLE_CSE_ID', 'GOOGLE_CSE_URL', 'PLAYWRIGHT_BROWSERS_PATH'})
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


def memory_resource_check(*, waived=False):
    """Only this one-shot Memoir evaluation may explicitly waive pressure.

    Normal callers retain the historical gate. The supported Mac requirement,
    owned resources and exclusive native lease remain independent requirements.
    No system settings or other application's limits are changed.
    """
    if type(waived) is not bool:
        raise ValueError('An explicit boolean memory policy is required')
    if not waived:
        from scripts.native_canary_launcher import resource_gate
        return resource_gate()
    if sys.platform != 'darwin':
        raise ValueError('The authorized Mac fixture is still required')
    return {'pressure_level': None, 'checked_at_unix': time.time(),
        'memory_pressure_check_waived': True, 'scope': 'one_shot_memoir_evaluation',
        'exclusive_native_lease_required': True}


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


def native_case_profile(case, evaluation_profile):
    if evaluation_profile == 'subscription_fifty':
        from apps.api.conversation_locale import explicit_profile
        return explicit_profile({}, case['language'])
    return {'preferred_language': case['language'], 'conversation_language':
            {'locale': case['language'], 'source': 'explicit', 'revision': 1}}


def native_cleanup_complete(native, cleanup_failed):
    return (not cleanup_failed and not native['ownership']['creation_uncertain']
        and (not native['postgres_allocation']['created'] or native['postgres_removed'] is True)
        and (not native.get('temporal_start_attempted') or native['temporal_stopped'] is True))


def native_artifact_setup(sql, plan):
    """Verify the isolated byte fixture before any worker can contact a model.

    Called only in the already-owned PostgreSQL setup thread. Its existing
    deadline/cancellation seam and joined teardown cover initialization and the
    real runtime upload/readback probe; no independent services are started.
    """
    from memoir_postgres_workflow import initialize_artifact_storage, verify_artifact_storage
    probe_owner = str(uuid5(UUID(plan['run_id']), 'memoir-artifact-readiness'))
    if probe_owner in {case['owner_id'] for case in plan['cases'].values()}:
        raise ValueError('Artifact readiness owner must be separate from campaign cases')
    limits = initialize_artifact_storage(sql)
    if type(limits) is not dict or limits != ARTIFACT_STORAGE_LIMITS:
        raise ValueError('Isolated artifact readiness limits differ from the plan')
    evidence = asyncio.run(verify_artifact_storage(sql, probe_owner=probe_owner))
    if (type(evidence) is not dict or evidence.get('status') != 'verified'
            or evidence.get('byte_readback_verified') is not True
            or evidence.get('probe_cleaned') is not True
            or type(evidence.get('model_calls')) is not int or evidence['model_calls'] != 0
            or evidence.get('real_storage_writes') is not False):
        raise ValueError('Isolated artifact readiness was not verified')
    return {**evidence, 'limits': limits}


@asynccontextmanager
async def native_resources(plan, run, directory, receipt):
    """Own only one disposable PG container and loopback Temporal process."""
    import httpx
    from temporalio.testing import WorkflowEnvironment
    from apps.api.memory_event_worker import MemoirLaneBroker
    # This is a dedicated process. Remove inherited service/auth configuration;
    # the one existing provider credential stays only in execute_native's local.
    environment = native_environment(directory, plan['run_id'])
    if plan.get('evaluation_profile') == 'subscription_fifty':
        environment['STRIPE_PRICE_FAMILY'] = 'synthetic-memoir-fifty-price'
    postgres_name = 'memoir-issue6-pg-' + plan['run_id'].replace('-', '')[:12]
    os.environ.clear(); os.environ.update(environment)
    sys.path.insert(0, str(ROOT / 'tests'))
    from test_shared_memory_events_postgres import database, attachment_database, private_database, event_database
    from memoir_postgres_workflow import PostgresRest, quoted
    from scripts.memoir_subscription_profiles import profile_for
    profile = profile_for(plan.get('evaluation_profile', 'subscription_progressive'))
    cancellation = threading.Event()
    allocation = {'attempted': False, 'created': False}
    receipt['native'] = {'postgres_container': postgres_name, 'postgres_allocation': allocation,
        'rest_auth_facade': 'synthetic_PostgresRest',
        'entitlement': 'synthetic_campaign_facade_only' if profile.name == 'subscription_fifty' else 'free',
        'real_account_subscriptions_modified': False,
        'artifact_storage': {'status': 'not_verified', 'real_storage_writes': False},
        'temporal': 'owned_loopback', 'postgres_removed': False, 'temporal_stopped': False,
        'temporal_start_attempted': False}
    def record():
        _save(directory / 'receipt.json', receipt)
    receipt['resource_gate'] = memory_resource_check(waived=plan.get('memory_pressure_check_waived', False))
    require_absent_container(postgres_name)
    record()
    ownership_scope = postgres_fixture_ownership(database.__wrapped__, postgres_name)
    receipt['native']['ownership'] = ownership_scope.__enter__()
    generator = database.__wrapped__(deadline=run.deadline, cancellation=cancellation,
                                     allocation=allocation, on_allocation=record)
    setup_task = temporal = broker = None
    storages, entitlement_facades = {}, {}
    def setup():
        sql = next(generator)
        if sql.command[3] != postgres_name:
            raise ValueError('Owned PostgreSQL identity differs')
        sql = event_database.__wrapped__(private_database.__wrapped__(attachment_database.__wrapped__(sql)))
        artifact_evidence = native_artifact_setup(sql, plan)
        for case in plan['cases'].values():
            sql(f"insert into auth.users(id,is_anonymous) values ({quoted(case['owner_id'])},false);")
            if (plan.get('browser_readback') or {}).get('allow_browser_turns') is True:
                sql("insert into public.user_memoir_project(user_id,project_id) values ("
                    + quoted(case['owner_id']) + "," + quoted(case['project_id']) + " );")
        return sql, artifact_evidence
    try:
        setup_task = asyncio.create_task(asyncio.to_thread(setup))
        sql, artifact_evidence = await asyncio.shield(setup_task)
        receipt['native']['artifact_storage'] = artifact_evidence
        record()
        receipt['resource_gate'] = memory_resource_check(waived=plan.get('memory_pressure_check_waived', False))
        receipt['native']['temporal_start_attempted'] = True
        temporal = await WorkflowEnvironment.start_local(
            dev_server_existing_path=plan['temporal_binary'],
            dev_server_database_filename=str(directory / 'temporal.sqlite'), ip='127.0.0.1', ui=False)
        for case_id, case in plan['cases'].items():
            facade = PostgresRest(sql, case['owner_id'], entitlement=profile.entitlement(case, 1))
            storage = facade.storage()
            entitlement_facades[case_id] = facade
            storage.save_profile(native_case_profile(case, profile.name))
            storages[case_id] = storage
        client = httpx.AsyncClient(transport=httpx.MockTransport(
            PostgresRest(sql, next(iter(plan['cases'].values()))['owner_id'], service=True).handle))
        broker = MemoirLaneBroker(url='http://synthetic.invalid', key='synthetic-service', client=client)
        yield {'storages': storages, 'broker': broker, 'temporal_client': temporal.client,
               **({'entitlement_facades': entitlement_facades} if profile.name == 'subscription_fifty' else {})}
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
    from scripts.memoir_subscription_profiles import profile_for
    profile = profile_for(plan.get('evaluation_profile', 'subscription_progressive'))
    # Rebuild the full plan before any resource or output allocation. An edited
    # saved plan cannot change cases, dataset, entitlement or approved caps.
    validated = build_plan(**{key: plan[key] for key in ('run_id', 'source_revision',
        'codex_binary', 'codex_sha256', 'temporal_binary', 'temporal_sha256',
        'max_client_requests', 'max_elapsed_seconds')},
        evaluation_profile=profile.name,
        waive_memory_pressure_check=plan.get('memory_pressure_check_waived', False),
        max_case_client_requests=plan.get('max_case_client_requests'),
        max_case_elapsed_seconds=plan.get('max_case_elapsed_seconds'),
        enable_public_photo_research=bool(plan.get('photo_research')),
        photo_python_binary=(plan.get('photo_research') or {}).get('python_binary'),
        photo_python_sha256=(plan.get('photo_research') or {}).get('python_sha256'),
        enable_browser_readback='browser_readback' in plan, browser_config=plan.get('browser_readback'))
    if plan != validated:
        raise ValueError('Exact freshly validated evaluation plan required')
    directory = Path(directory)
    if plan.get('browser_readback'):
        output = Path(plan['browser_readback']['output_root']).resolve()
        if directory.resolve() not in output.parents:
            raise ValueError('Browser output must remain inside this owned run directory')
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    (directory / 'journal').mkdir(mode=0o700)
    _save(directory / 'plan.json', plan)
    run = SubscriptionRun.create(reservation_root=directory / 'journal', run_id=plan['run_id'],
        source_revision=plan['source_revision'], limits=SubscriptionLimits(
            plan['max_client_requests'], plan['max_elapsed_seconds']),
        **({'case_ids': profile.case_ids, 'case_limits': SubscriptionLimits(
            plan['max_case_client_requests'], plan['max_case_elapsed_seconds'])}
           if profile.name == 'subscription_fifty' else {}))
    receipt = {'schema_version': 'memoir-subscription-native-receipt/1', 'run_id': plan['run_id'],
        'source_revision': plan['source_revision'], 'status': 'incomplete', 'execution_started': True,
        'judge': 'not_run', 'langfuse': 'not_published', 'semantic_acceptance': 'human_review_required'}
    session = None
    photo_settings = {key: os.environ[key] for key in ('GOOGLE_CSE_ID', 'GOOGLE_CSE_URL')
                      if key in os.environ}
    photo_browsers = os.environ.get('PLAYWRIGHT_BROWSERS_PATH')
    transport = SubscriptionTransport.existing_route(run=run, authorization='Bearer ' + api_key)
    try:
        async with asyncio.timeout(run.remaining_seconds()):
            async with native_resources(plan, run, directory, receipt) as resources:
                session = await OwnedSubscriptionSession.create(run=run, provider_transport=transport,
                    **resources, home_root=directory / 'homes', codex_binary=plan['codex_binary'],
                    codex_sha256=plan['codex_sha256'], api_key=api_key, evaluation_profile=profile.name)
                if plan.get('browser_readback'):
                    from scripts.memoir_fifty_browser_runner import OwnedFiftyBrowserReadback
                    session.browser_readback = OwnedFiftyBrowserReadback.admit(session, plan['browser_readback'])
                if plan.get('photo_research'):
                    from scripts.memoir_fifty_photo import FiftyPhotoResearch
                    photo = plan['photo_research']
                    session.photo_research = await FiftyPhotoResearch.admit(
                        session=session, directory=directory / 'photos',
                        python_binary=photo['python_binary'], python_sha256=photo['python_sha256'],
                        existing_public_settings=photo_settings, playwright_browsers_path=photo_browsers)
                def progress(value):
                    receipt['evaluation_progress'] = value
                    _save(directory / 'receipt.json', receipt)
                runner = SubscriptionProgressiveRunner(session, **(
                    {'evidence_mode': profile.name} if profile.name == 'subscription_fifty' else {}))
                result = await runner.run(progress=progress)
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
        if session is not None and getattr(session, 'photo_research', None) is not None:
            receipt['photo_research'] = session.photo_research.snapshot()
        if session is not None and getattr(session, 'browser_readback', None) is not None:
            receipt['browser_readback'] = session.browser_readback.receipt()
        _save(directory / 'receipt.json', receipt)
    return receipt


def read_browser_config(path):
    path = Path(path)
    if (not path.is_absolute() or path.is_symlink() or not path.is_file()
            or path.stat().st_uid != os.getuid() or path.stat().st_size > 2 * 1024 * 1024):
        raise ValueError('An existing owner-owned bounded browser config is required')
    from scripts.issue14_subscription_session import _json
    return _json(path.read_bytes())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-existing-subscription', action='store_true')
    parser.add_argument('--waive-memory-pressure-check', action='store_true',
        help='Explicitly authorized one-shot Memoir memory waiver; keeps isolation and the native lease')
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--source-revision', required=True)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--existing-app-env', type=Path)
    for name in ('codex', 'temporal'):
        parser.add_argument(f'--{name}-binary', type=Path, required=True)
        parser.add_argument(f'--{name}-sha256', required=True)
    parser.add_argument('--enable-browser-readback', action='store_true')
    parser.add_argument('--browser-config', type=Path)
    parser.add_argument('--enable-public-photo-research', action='store_true')
    parser.add_argument('--photo-python-binary', type=Path)
    parser.add_argument('--photo-python-sha256')
    parser.add_argument('--evaluation-profile', choices=('subscription_progressive', 'subscription_fifty'),
        default='subscription_progressive')
    parser.add_argument('--max-case-client-requests', type=int)
    parser.add_argument('--max-case-elapsed-seconds', type=float)
    parser.add_argument('--max-client-requests', type=int, required=True)
    parser.add_argument('--max-elapsed-seconds', type=float, required=True)
    args = parser.parse_args(argv)
    execution_started = False
    try:
        if args.browser_config is not None and not args.enable_browser_readback:
            raise ValueError('Browser config requires explicit admission')
        browser_config = read_browser_config(args.browser_config) if args.browser_config is not None else None
        plan = build_plan(browser_config=browser_config, **{key: getattr(args, key) for key in ('run_id','source_revision',
            'codex_binary','codex_sha256','temporal_binary','temporal_sha256',
            'max_client_requests','max_elapsed_seconds','waive_memory_pressure_check',
            'evaluation_profile','max_case_client_requests','max_case_elapsed_seconds',
            'enable_public_photo_research','photo_python_binary','photo_python_sha256',
            'enable_browser_readback')})
        if not args.execute_existing_subscription:
            print(json.dumps(plan, sort_keys=True))
            return 0
        verify_source(args.source_revision)
        if plan.get('evaluation_profile', 'subscription_progressive') == 'subscription_fifty':
            from scripts.issue14_subscription_source_contract_v6 import audit_subscription_source_v6
            audit_subscription_source_v6(ROOT)
        if sys.platform != 'darwin':
            raise ValueError('This native bootstrap requires the authorized Mac fixture')
        from scripts.native_canary_launcher import native_resource_lease
        memory_resource_check(waived=plan['memory_pressure_check_waived'])
        if args.run_dir.exists() or args.run_dir.is_symlink() or ROOT in args.run_dir.resolve().parents:
            raise ValueError('A fresh task output directory outside the source checkout is required')
        # Refuse silent stock-image installation. The native preflight must have
        # the supported fixture image and both executable pins already present.
        subprocess.run(['container','image','inspect','postgres:18.3'], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if args.existing_app_env is not None:
            load_existing_application_env(args.existing_app_env, **(
                {'include_public_photo_settings': True} if args.enable_public_photo_research else {}))
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
            memory_resource_check(waived=plan['memory_pressure_check_waived'])
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
