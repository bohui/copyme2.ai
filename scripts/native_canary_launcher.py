"""Reviewed native canary entrypoint: check, controlled test, or guarded run.

--check never prompts or starts an actor/database/Temporal/model. --execute is
for the parent-approved native window and user key handoff only. No key argument,
shared restart, provider fallback or persistent auth/configuration change exists.
"""
import argparse
import asyncio
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import signal
import shutil
import subprocess
import sys
import threading
import time
from uuid import uuid4
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_CONTAINER = 'llm-provider-codex-lb-1'
RUNTIME_PYTHON = '/app/.venv/bin/python'
TASK_FILES = ('canary_gateway_actor.py', 'canary_gateway_binding.py', 'canary_send_guard.py')


class NativeGateError(RuntimeError):
    """Only a fixed local admission reason, never external exception text."""
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def resource_gate():
    if platform.system() != 'Darwin':
        raise NativeGateError('approved_mac_resource_window_required')
    result = subprocess.run(['/usr/sbin/sysctl', '-n', 'kern.memorystatus_vm_pressure_level'],
        capture_output=True, text=True, timeout=5, check=False)
    if result.returncode != 0 or result.stdout.strip() != '1':
        raise NativeGateError('native_memory_pressure_elevated_or_unknown')
    return {'pressure_level': 1, 'checked_at_unix': time.time(), 'exclusive_window': 'parent_required'}


@contextmanager
def native_resource_lease(run_id, *, path=Path('/tmp/memoir-native-heavy.lock')):
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        if os.fstat(fd).st_uid != os.getuid():
            raise RuntimeError('Native resource lease has another owner')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another canary owns the native resource lease') from None
        os.ftruncate(fd, 0)
        os.write(fd, json.dumps({'run_id': run_id, 'pid': os.getpid()}).encode())
        os.fsync(fd)
        yield
    finally:
        os.close(fd)


def local_preflight(*, reviewed_head, docker=None, codex=None, codex_sha256=None, require_live=False):
    if not re.fullmatch('[a-f0-9]{40}', reviewed_head or ''):
        raise ValueError('An exact independently reviewed head is required')
    head, tree = subprocess.check_output(['git', 'rev-parse', 'HEAD', 'HEAD^{tree}'], cwd=ROOT, text=True).splitlines()
    if head != reviewed_head or subprocess.check_output(['git', 'status', '--porcelain=v1'], cwd=ROOT):
        raise NativeGateError('exact_clean_reviewed_head_required')
    pressure = resource_gate()
    if shutil.which('container') is None:
        raise NativeGateError('supported_apple_container_fixture_unavailable')
    if shutil.which('node') is None:
        raise NativeGateError('canonical_composer_node_runtime_unavailable')
    if any(importlib.util.find_spec(name) is None for name in ('pytest', 'httpx', 'fastapi', 'temporalio')):
        raise NativeGateError('native_python_dependencies_unavailable')
    if require_live:
        if (not docker or not Path(docker).is_absolute() or Path(docker).name != 'docker'
                or not Path(docker).is_file() or not os.access(docker, os.X_OK)):
            raise ValueError('The verified absolute Docker executable is required')
        if (not codex or not Path(codex).is_absolute() or not Path(codex).is_file()
                or not os.access(codex, os.X_OK) or not re.fullmatch('[a-f0-9]{64}', codex_sha256 or '')
                or hashlib.sha256(Path(codex).read_bytes()).hexdigest() != codex_sha256):
            raise ValueError('The exact installed Codex executable and hash are required')
    return {'source_revision': head, 'source_tree': tree, 'resource_gate': pressure,
        'execution_started': False, 'input_read': False, 'credentials_loaded': False, 'gateway_auth_verified': False,
        'provider_requests_started': 0, 'runtime_python': 'not_verified',
        'native_import_accounting_browser': 'not_run'}


class OwnedCommandFailed(RuntimeError):
    def __init__(self, output=b''):
        super().__init__('Owned native command failed')
        self.output = output[:8 * 1024 * 1024]


def run_owned(command, *, input_bytes=None, seconds=30, env=None, cancellation=None):
    from scripts.run_isolated_check import stop_owned
    process, out = None, b''
    cancelled, handlers = [], {}
    if threading.current_thread() is threading.main_thread():
        # Record cancellation during spawn rather than losing a just-created
        # handle to an exception. Poll after spawn, then reap only our group.
        def request_stop(signum, frame): cancelled.append(signum)
        for signum in (signal.SIGTERM, signal.SIGINT):
            handlers[signum] = signal.signal(signum, request_stop)
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, start_new_session=True, env=env, cwd=ROOT)
        deadline, first = time.monotonic() + seconds, True
        while True:
            if cancelled or (cancellation is not None and cancellation.is_set()):
                raise OwnedCommandFailed(out)
            remaining = deadline - time.monotonic()
            if remaining <= 0: raise OwnedCommandFailed(out)
            try:
                out, err = process.communicate(input_bytes if first else None, timeout=min(.2, remaining))
                break
            except subprocess.TimeoutExpired as error:
                first = False
                out = error.output or b''
        if process.returncode != 0 or len(out) > 8 * 1024 * 1024:
            raise OwnedCommandFailed(out)
        return out
    finally:
        try:
            if process is not None:
                closed = stop_owned(process)
                if not closed['group_gone']: raise OwnedCommandFailed(out)
        finally:
            for signum, handler in handlers.items(): signal.signal(signum, handler)


def _docker_env():
    return {key: os.environ[key] for key in ('PATH', 'SYSTEMROOT', 'TMPDIR') if key in os.environ}


def runtime_source_preflight(docker, cancellation=None):
    from scripts.canary_gateway_actor import BOOTSTRAP_SOURCE_SHA256
    from scripts.canary_gateway_binding import SOURCE_SHA256
    expected = {**SOURCE_SHA256, **BOOTSTRAP_SOURCE_SHA256}
    program = """import hashlib,json,pathlib,sys
expected=json.load(sys.stdin)
actual={name:hashlib.sha256((pathlib.Path('/app/app')/name).read_bytes()).hexdigest() for name in expected}
if actual != expected: raise SystemExit(3)
print(json.dumps({'runtime_python':sys.executable,'installed_source_sha256':actual}))
"""
    raw = run_owned([docker, 'exec', '-i', RUNTIME_CONTAINER, RUNTIME_PYTHON, '-c', program],
        input_bytes=json.dumps(expected).encode(), env=_docker_env(), cancellation=cancellation)
    result = json.loads(raw)
    if result.get('runtime_python') != RUNTIME_PYTHON or result.get('installed_source_sha256') != expected:
        raise RuntimeError('Runtime interpreter/source preflight differed')
    return result


def stage_payload(run_id):
    from uuid import UUID
    if str(UUID(run_id)) != run_id:
        raise ValueError('Fresh UUID stage identity required')
    files = {}
    for name in TASK_FILES:
        raw = (ROOT / 'scripts' / name).read_bytes()
        files[name] = {'sha256': hashlib.sha256(raw).hexdigest(), 'base64': base64.b64encode(raw).decode()}
    return {'directory': '/tmp/memoir-canary-' + run_id, 'files': files}


def stage_actor(docker, run_id, cancellation=None):
    payload = stage_payload(run_id)
    program = """import base64,hashlib,json,os,pathlib,sys
p=json.load(sys.stdin); root=pathlib.Path(p['directory'])
root.mkdir(mode=0o700); scripts=root/'scripts'; scripts.mkdir(mode=0o700)
for name,item in p['files'].items():
 if name not in ('canary_gateway_actor.py','canary_gateway_binding.py','canary_send_guard.py'): raise SystemExit(3)
 raw=base64.b64decode(item['base64'],validate=True)
 if hashlib.sha256(raw).hexdigest()!=item['sha256']: raise SystemExit(3)
 fd=os.open(scripts/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb') as f: f.write(raw); f.flush(); os.fsync(f.fileno())
print(json.dumps({'directory':str(root),'source_sha256':{name:item['sha256'] for name,item in p['files'].items()}}))
"""
    raw = run_owned([docker, 'exec', '-i', RUNTIME_CONTAINER, RUNTIME_PYTHON, '-c', program],
        input_bytes=json.dumps(payload).encode(), env=_docker_env(), cancellation=cancellation)
    receipt = json.loads(raw)
    if (receipt.get('directory') != payload['directory'] or receipt.get('source_sha256') !=
            {name: item['sha256'] for name, item in payload['files'].items()}):
        raise RuntimeError('Owned actor staging was not verified')
    return receipt


ACTOR_RECONCILE_PROGRAM = """import json,os,pathlib,signal,sys,time
p=json.load(sys.stdin); pid=p.get('actor_pid')
expected=('/tmp/memoir-canary-'+p['run_id']+'/scripts/canary_gateway_actor.py').encode()
def state():
 if type(pid) is not int or pid<=1: return 'unknown'
 proc=pathlib.Path('/proc')/str(pid)
 try:
  args=(proc/'cmdline').read_bytes().split(b'\\0'); stat=(proc/'stat').read_text()
 except FileNotFoundError: return 'absent'
 if stat.rsplit(')',1)[-1].strip().split()[0]=='Z': return 'exited_unreaped'
 if not any(args): return 'exiting_or_unknown'
 return 'owned_actor_still_running' if len(args)>2 and args[1]==expected and args[2]==b'--stdio' else 'not_owned'
initial=state(); sent=[]
if initial=='owned_actor_still_running':
 for sig in (signal.SIGTERM,signal.SIGKILL):
  if state()!='owned_actor_still_running': break
  try: os.kill(pid,sig); sent.append(sig.name)
  except ProcessLookupError: break
  until=time.monotonic()+2
  while time.monotonic()<until and state() in ('owned_actor_still_running','exiting_or_unknown'): time.sleep(.05)
print(json.dumps({'initial_state':initial,'final_state':state(),'signals_sent':sent}))
"""


def reconcile_actor(docker, run_id, actor_pid):
    # PID alone is insufficient: require this run's immutable script argv.
    return json.loads(run_owned([docker, 'exec', '-i', RUNTIME_CONTAINER, RUNTIME_PYTHON,
        '-c', ACTOR_RECONCILE_PROGRAM], input_bytes=json.dumps({'run_id': run_id,
        'actor_pid': actor_pid}).encode(), seconds=12, env=_docker_env()))


def collect_actor_evidence(docker, run_id, actor_pid):
    # Read only this run's content-free journal/cleanup and exact process identity.
    program = """import json,os,pathlib,sys
p=json.load(sys.stdin); root=pathlib.Path('/tmp')/('memoir-canary-'+p['run_id'])
result={'runtime_state':{}}
for name in ('reservation.jsonl','cleanup.json'):
 path=root/'runtime-state'/name
 if path.is_file() and not path.is_symlink() and path.stat().st_size<=4*1024*1024:
  result['runtime_state'][name]=path.read_text()
state='unknown'; pid=p.get('actor_pid')
if type(pid) is int and pid>0:
 path=pathlib.Path('/proc')/str(pid)/'cmdline'
 try:
  raw=path.read_bytes(); state='owned_actor_still_running' if str(root/'scripts/canary_gateway_actor.py').encode() in raw.split(b'\\0') else 'pid_reused_or_other_process'
 except FileNotFoundError: state='absent'
result['actor_process_state']=state
print(json.dumps(result))
"""
    return json.loads(run_owned([docker, 'exec', '-i', RUNTIME_CONTAINER, RUNTIME_PYTHON, '-c', program],
        input_bytes=json.dumps({'run_id': run_id, 'actor_pid': actor_pid}).encode(), env=_docker_env()))


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def reconcile_postgres(name):
    # Never inspect/stop anything other than the UUID recorded before allocation.
    command = ['container', 'inspect', name]
    first = subprocess.run(command, capture_output=True, text=True, timeout=8)
    if first.returncode and f'container not found: {name}' in first.stderr.lower():
        return True
    subprocess.run(['container', 'stop', name], capture_output=True, timeout=10)
    last = subprocess.run(command, capture_output=True, text=True, timeout=8)
    return bool(last.returncode and f'container not found: {name}' in last.stderr.lower())


async def execute_live(args, preflight):
    run_id = str(uuid4())
    run_dir = args.output_root / run_id
    run_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    receipt = {**preflight, 'run_id': run_id, 'status': 'blocked', 'cleanup': {},
        'actor_start_attempted': False, 'input_read': False,
        'postgres_allocation': {'attempted': False, 'created': False},
        'infrastructure': 'real PostgreSQL/Temporal with synthetic auth and entitlement facade',
        'provider_requests_started': 0, 'guarded_send_entries': 0,
        'langfuse_browser_gateway_readback': 'not_verified'}
    path = run_dir / 'native-receipt.json'
    def record(): save(path, receipt)
    record()
    postgres_name = 'memoir-issue6-pg-' + uuid4().hex[:12]
    workspace = run_dir / 'workspace'
    workspace.mkdir(mode=0o700)
    receipt['postgres_container'] = postgres_name
    cancellation = threading.Event()
    generator = setup_task = temporal = None
    storages, worker = {}, None
    # This entrypoint owns a fresh task process. Remove unrelated settings by
    # NAME without reading/copying their values; do not restore them later.
    keep = {'PATH', 'HOME', 'TMPDIR', 'USER', 'LOGNAME', 'LANG', 'LC_ALL', 'SHELL', 'TERM'}
    if args.input_mode == 'environment': keep.add('MEMOIR_CANARY_GATEWAY_API_KEY')
    for name in list(os.environ):
        if name not in keep: del os.environ[name]
    controlled_keys = {'MEMOIR_TEST_POSTGRES_BACKEND': 'apple-container',
        'MEMOIR_TEST_POSTGRES_CONTAINER_NAME': postgres_name, 'MEMORY_SPARK_TEST_MODE': '1',
        'MEMORY_SPARK_ENTITLEMENT_MODEL': 'legacy', 'STRIPE_PRICE_FAMILY': 'synthetic-price',
        'MEMORY_SPARK_CODEX_HOME': str(workspace / 'unused-default-worker-home'),
        'MEMORY_SPARK_LLM_API_KEY': '',
        'MEMORY_SPARK_TASK_DB': str(workspace / 'tasks.sqlite'),
        'MEMORY_SPARK_DATABASE': str(workspace / 'application.sqlite')}
    os.environ.update(controlled_keys)
    loop = asyncio.get_running_loop()
    owner = asyncio.current_task()
    old_sigterm = signal.getsignal(signal.SIGTERM)
    def interrupt():
        cancellation.set()
        owner.cancel()
    loop.add_signal_handler(signal.SIGTERM, interrupt)
    try:
        from scripts.canary_gateway_actor import expected_source_hashes
        from scripts.canary_gateway_auth import authenticated_canary_worker
        from scripts.canary_app_launcher import run_application_canary
        from scripts.run_codexlb_canary import build_manifest, APPROVED_ACCOUNT_BINDING
        plan = build_manifest(run_id=run_id, source_revision=args.reviewed_head)
        save(run_dir / 'plan.json', plan)
        resource_gate()
        receipt['stage'] = 'runtime_source_preflight'
        record()
        receipt['runtime_source_preflight'] = await asyncio.to_thread(runtime_source_preflight, args.docker, cancellation)
        receipt['stage'] = 'exclusive_actor_staging'
        receipt['actor_stage_attempted'] = True
        record()
        receipt['actor_stage'] = await asyncio.to_thread(stage_actor, args.docker, run_id, cancellation)
        record()
        actor_options = {'actor_command': [args.docker, 'exec', '-i', RUNTIME_CONTAINER,
            RUNTIME_PYTHON, f'/tmp/memoir-canary-{run_id}/scripts/canary_gateway_actor.py', '--stdio'],
            'run_id': run_id, 'source_revision': args.reviewed_head,
            'account_binding': APPROVED_ACCOUNT_BINDING, 'source_sha256': expected_source_hashes()}
        def input_read():
            receipt['input_read'] = True
            receipt['stage'] = 'gateway_input_validation'
            record()
        def before_actor():
            # Input shape was validated, but the gateway has not accepted it.
            receipt['credentials_loaded'] = True
            receipt['stage'] = 'post_input_resource_gate'
            record()
            receipt['resource_gate'] = resource_gate()
            receipt['actor_start_attempted'] = True
            # Once actor dispatch is possible, zero provider sends is unproven.
            # Guarded entries remain separate evidence, never an actual count.
            receipt['provider_requests_started'] = None
            receipt['guarded_send_entries'] = None
            receipt['stage'] = 'actor_startup_and_auth'
            record()
        def actor_started(value):
            receipt.update(actor_pid=value.get('actor_pid'), gateway_start_receipt=value,
                           gateway_auth_verified=True, reservation_created=True)
            record()
        receipt['stage'] = 'gateway_auth_input'
        record()
        async with authenticated_canary_worker(actor_options=actor_options, home_root=workspace / 'worker-homes',
                codex_binary=args.codex, expected_codex_sha256=args.codex_sha256,
                input_mode=args.input_mode, before_actor_start=before_actor,
                on_actor_started=actor_started, on_input_read=input_read) as worker:
            worker.before_dispatch = resource_gate
            deadline = worker.gateway_lease.deadline
            receipt.update(execution_started=True, gateway_auth_verified=True, status='running')
            receipt['stage'] = 'postgres_fixture'
            record()
            sys.path.insert(0, str(ROOT / 'tests'))
            from test_shared_memory_events_postgres import database, attachment_database, private_database, event_database
            from memoir_postgres_workflow import PostgresRest, quoted
            from temporalio.testing import WorkflowEnvironment
            from apps.api.memory_event_worker import MemoirLaneBroker
            import httpx
            allocation = receipt['postgres_allocation']
            generator = database.__wrapped__(deadline=deadline, cancellation=cancellation,
                allocation=allocation, on_allocation=record)
            def setup():
                sql = next(generator)
                if sql.command[3] != postgres_name:
                    raise RuntimeError('Owned PostgreSQL identity differs')
                sql = event_database.__wrapped__(private_database.__wrapped__(attachment_database.__wrapped__(sql)))
                for case in plan['cases']:
                    sql(f"insert into auth.users(id,is_anonymous) values ({quoted(case['owner_id'])},false);")
                return sql
            receipt['resource_gate'] = resource_gate()
            setup_task = asyncio.create_task(asyncio.to_thread(setup))
            async with asyncio.timeout_at(deadline):
                sql = await asyncio.shield(setup_task)
                receipt['resource_gate'] = resource_gate()
                receipt['stage'] = 'temporal_fixture'
                record()
                temporal = await WorkflowEnvironment.start_local(download_dest_dir='/tmp/memoir-issue6-temporal',
                    dev_server_database_filename=str(workspace / 'temporal.sqlite'), ip='127.0.0.1', ui=False)
                for case in plan['cases']:
                    entitlement = {'status': 'paid', 'plan_key': 'family_memoir_v1',
                        'family_tree': case['family_enabled'], 'timeline': case['family_enabled'],
                        'stripe_price_id': 'synthetic-price'}
                    storage = PostgresRest(sql, case['owner_id'], entitlement=entitlement).storage()
                    storages[case['project_id']] = storage
                    storage.save_profile({'preferred_language': case['language'], 'conversation_language':
                        {'locale': case['language'], 'source': 'explicit', 'revision': 1}})
                async with httpx.AsyncClient(transport=httpx.MockTransport(
                        PostgresRest(sql, plan['cases'][0]['owner_id'], service=True).handle)) as client:
                    broker = MemoirLaneBroker(url='http://synthetic.invalid', key='synthetic-only', client=client)
                    receipt['stage'] = 'canonical_application'
                    record()
                    result = await run_application_canary(plan, storages=storages, broker=broker,
                        temporal_client=temporal.client, worker=worker, run_dir=run_dir / 'application', deadline=deadline)
                receipt.update(status=result['status'], application_manifest=str(run_dir / 'application/manifest.json'),
                    guarded_send_entries=result['app_receipt'].get('guarded_send_entries'), provider_requests_started=None)
    except (Exception, asyncio.CancelledError, KeyboardInterrupt) as error:
        receipt.update(status='incomplete', error_class=type(error).__name__,
                       error_stage=receipt.get('stage'), blocked_reason=getattr(error, 'reason', None))
    finally:
        cancellation.set()
        async def close(name, action, seconds=15):
            try:
                async with asyncio.timeout(seconds):
                    result = await action()
                receipt['cleanup'][name] = result is not False
                if not receipt['cleanup'][name]:
                    receipt['status'] = 'incomplete'
            except (Exception, asyncio.CancelledError) as error:
                receipt['cleanup'][name] = False
                receipt['cleanup'][name + '_error_class'] = type(error).__name__
                receipt['status'] = 'incomplete'
            record()
        async def cleanup():
            if worker is not None:
                worker.api_key = ''
                await close('gateway_stopped', worker.gateway_lease.stop, 25)
                receipt['gateway'] = worker.gateway_lease.receipt()
                gateway = receipt['gateway']
                receipt['guarded_send_entries'] = gateway.get('guarded_send_entries',
                    receipt.get('guarded_send_entries'))
                receipt['cleanup']['gateway_guard_finished'] = bool(
                    gateway.get('cleanup', {}).get('closed') is True and
                    gateway.get('cleanup', {}).get('active_finished') is True)
                receipt['cleanup']['gateway_resources_finished'] = gateway.get('actor_cleanup', {}).get('finished') is True
                bridge_cleanup = gateway.get('bridge_cleanup')
                receipt['cleanup']['gateway_bridge_finished'] = bool(
                    isinstance(bridge_cleanup, dict) and all(bridge_cleanup.get(name) is True
                        for name in ('child_reaped', 'listener_closed', 'actor_exit_verified')))
                if not all(receipt['cleanup'][name] for name in (
                        'gateway_guard_finished', 'gateway_resources_finished', 'gateway_bridge_finished')):
                    receipt['status'] = 'incomplete'
            if setup_task is not None:
                async def setup_settled():
                    try: await asyncio.shield(setup_task)
                    except (Exception, asyncio.CancelledError): pass
                    return setup_task.done()
                await close('postgres_setup_settled', setup_settled, 25)
            for storage in storages.values(): storage.client.close()
            if temporal is not None: await close('temporal_closed', temporal.shutdown)
            if generator is not None and (setup_task is None or setup_task.done()):
                await close('postgres_generator_closed', lambda: asyncio.to_thread(generator.close), 15)
            if receipt['postgres_allocation']['attempted']:
                await close('postgres_removal_verified', lambda: asyncio.to_thread(reconcile_postgres, postgres_name), 30)
            if receipt.get('actor_stage'):
                try:
                    actor_pid = receipt.get('actor_pid') or receipt.get('gateway', {}).get('actor_pid')
                    reconciliation = await asyncio.to_thread(reconcile_actor, args.docker, run_id, actor_pid)
                    receipt['cleanup']['actor_reconciliation'] = reconciliation
                    if reconciliation['signals_sent']:
                        receipt['status'] = 'incomplete'
                    evidence = await asyncio.to_thread(collect_actor_evidence, args.docker, run_id, actor_pid)
                    save(run_dir / 'actor-evidence.json', evidence)
                    receipt['cleanup']['remote_actor_absence_verified'] = evidence['actor_process_state'] == 'absent'
                    if actor_pid and not receipt['cleanup']['remote_actor_absence_verified']:
                        receipt['status'] = 'incomplete'
                except Exception as error:
                    receipt['cleanup']['remote_actor_absence_verified'] = False
                    receipt['cleanup']['actor_evidence_error_class'] = type(error).__name__
                    receipt['status'] = 'incomplete'
            receipt['cleanup']['workspace_retained_for_evidence'] = True
            record()
        closing = asyncio.create_task(cleanup())
        while not closing.done():
            try: await asyncio.shield(closing)
            except asyncio.CancelledError: receipt['status'] = 'incomplete'
        await closing
        loop.remove_signal_handler(signal.SIGTERM)
        signal.signal(signal.SIGTERM, old_sigterm)
        if 'MEMOIR_CANARY_GATEWAY_API_KEY' in os.environ:
            del os.environ['MEMOIR_CANARY_GATEWAY_API_KEY']
        record()
    return {'status': receipt['status'], 'native_receipt': str(path), 'run_id': run_id,
            'provider_requests_started': receipt['provider_requests_started'],
            'guarded_send_entries': receipt['guarded_send_entries'],
            'durable_evidence': 'pending independent readback'}


def execute_controlled(args, preflight):
    from scripts.run_isolated_check import offline_environment
    run_id = str(uuid4())
    run_dir = args.output_root / run_id
    run_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    postgres_name = 'memoir-issue6-pg-' + uuid4().hex[:12]
    environment = offline_environment(ROOT)
    environment.update(MEMOIR_TEST_POSTGRES_BACKEND='apple-container',
        MEMOIR_TEST_POSTGRES_CONTAINER_NAME=postgres_name, MEMOIR_NATIVE_RESOURCE_GATE='1',
        MEMORY_SPARK_CODEX_HOME=str(run_dir / 'unused-default-worker-home'),
        MEMORY_SPARK_TASK_DB=str(run_dir / 'tasks.sqlite'),
        MEMORY_SPARK_DATABASE=str(run_dir / 'application.sqlite'))
    receipt = {**preflight, 'run_id': run_id, 'status': 'incomplete', 'evidence_mode': 'mock_only',
        'postgres_container': postgres_name, 'provider_requests_started': 0, 'cleanup': {}}
    save(run_dir / 'native-receipt.json', receipt)
    try:
        resource_gate()
        command = [sys.executable, '-B', '-m', 'pytest', '-q',
            'tests/test_canary_application_native.py', '--basetemp=' + str(run_dir / 'pytest-workspace'),
            '--junitxml=' + str(run_dir / 'native-test.xml')]
        result = run_owned(command, seconds=900, env=environment)
        (run_dir / 'native-test.log').write_bytes(result)
        receipt['cleanup']['owned_process_group_gone'] = True
        report = ET.parse(run_dir / 'native-test.xml')
        cases = report.findall('.//testcase')
        if (len(cases) != 1 or cases[0].get('classname') != 'tests.test_canary_application_native'
                or cases[0].get('name') != 'test_ten_original_app_rounds_two_drafts_and_joined_single_attempt_jobs'
                or any(report.findall('.//' + tag) for tag in ('skipped', 'failure', 'error'))):
            raise RuntimeError('The actual controlled application test did not pass')
        receipt['controlled_application_test_verified'] = True
        receipt['status'] = 'controlled_native_passed'
    except (Exception, KeyboardInterrupt) as error:
        receipt['error_class'] = type(error).__name__
        if isinstance(error, OwnedCommandFailed):
            (run_dir / 'native-test.log').write_bytes(error.output)
    finally:
        try:
            receipt['cleanup']['postgres_removal_verified'] = reconcile_postgres(postgres_name)
        except Exception:
            receipt['cleanup']['postgres_removal_verified'] = False
        if not receipt['cleanup']['postgres_removal_verified']: receipt['status'] = 'incomplete'
        save(run_dir / 'native-receipt.json', receipt)
    return {'status': receipt['status'], 'native_receipt': str(run_dir / 'native-receipt.json'),
            'provider_requests_started': 0, 'evidence_mode': 'mock_only'}


def main():
    class SafeParser(argparse.ArgumentParser):
        def error(self, message): self.exit(2, 'Invalid native canary options; never put credentials in argv.\n')
    parser = SafeParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--check', action='store_true')
    modes.add_argument('--test-native', action='store_true')
    modes.add_argument('--execute', action='store_true')
    parser.add_argument('--reviewed-head', required=True)
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--docker')
    parser.add_argument('--codex')
    parser.add_argument('--codex-sha256')
    parser.add_argument('--input-mode', choices=('prompt', 'environment'), default='prompt')
    args = parser.parse_args()
    admitted = False
    old_sigterm = None
    try:
        if args.output_root.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError('Native evidence/workspace must be outside the reviewed checkout')
        preflight = local_preflight(reviewed_head=args.reviewed_head, docker=args.docker,
            codex=args.codex, codex_sha256=args.codex_sha256, require_live=args.execute)
        if args.check:
            print(json.dumps({**preflight, 'status': 'local_check_passed', 'execution_started': False,
                              'input_read': False, 'credentials_loaded': False, 'gateway_auth_verified': False}))
            return 0
        with native_resource_lease(str(uuid4())):
            admitted = True
            def interrupted(signum, frame): raise KeyboardInterrupt
            old_sigterm = signal.signal(signal.SIGTERM, interrupted)
            if args.execute:
                from scripts.run_canonical_five_case_evaluation import service_logs_to_stderr
                with service_logs_to_stderr():
                    result = asyncio.run(execute_live(args, preflight))
            else:
                result = execute_controlled(args, preflight)
        print(json.dumps(result))
        return 0 if result['status'] in {'controlled_native_passed', 'app_completed_evidence_pending'} else 3
    except (Exception, KeyboardInterrupt) as error:
        print(json.dumps({'status': 'incomplete' if admitted else 'blocked',
            'execution_started': None if admitted else False, 'credentials_loaded': None if admitted else False,
            'input_read': None if admitted else False,
            'provider_requests_started': None if admitted else 0, 'error_class': type(error).__name__,
            'blocked_reason': getattr(error, 'reason', None)}))
        return 3
    finally:
        if old_sigterm is not None: signal.signal(signal.SIGTERM, old_sigterm)


if __name__ == '__main__':
    raise SystemExit(main())
