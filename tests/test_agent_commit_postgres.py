"""Run fencing/atomicity checks on a disposable local PostgreSQL, never Supabase."""
import os
from contextlib import nullcontext
import ipaddress
import json
import queue
import re
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from uuid import uuid4

import pytest


OWNER = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'
OLD = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
NEW = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'


class ProcessDeadline:
    """Bound task-owned commands, including pipe I/O, and poll cancellation."""

    def __init__(self, deadline=None, cancellation=None, environment=None):
        self.deadline = deadline
        self.environment = environment
        self.cancellation = cancellation

    def remaining(self):
        if self.cancellation is not None and self.cancellation.is_set():
            raise InterruptedError('Native fixture setup cancelled')
        if self.deadline is None:
            return .1
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Native fixture deadline reached')
        return min(.1, remaining)

    def run(self, command, *, check=False, text=False, input=None):
        self.remaining()
        # Retrying communicate(None) does not resume a partially written stdin.
        # A temporary input file keeps cancellation polling without pipe deadlock.
        with tempfile.TemporaryFile(mode='w+t' if text else 'w+b') if input is not None else nullcontext(None) as source:
            if source is not None:
                source.write(input);source.seek(0)
            process = subprocess.Popen(command, stdin=source,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=text, env=self.environment)
            try:
                while True:
                    try:
                        output, errors = process.communicate(timeout=self.remaining())
                        break
                    except subprocess.TimeoutExpired:
                        pass
                if check and process.returncode:
                    raise subprocess.CalledProcessError(process.returncode, command, output, errors)
                return subprocess.CompletedProcess(command, process.returncode, output, errors)
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=2)
                for pipe in (process.stdout, process.stderr):
                    if pipe is not None and not pipe.closed:
                        pipe.close()


@pytest.mark.parametrize('text', [False, True])
def test_deadline_runner_delivers_large_input_after_polling_timeout(text):
    value='x'*262144 if text else b'x'*262144
    result=ProcessDeadline(time.monotonic()+3).run([sys.executable,'-c',
        'import sys,time;time.sleep(.3);print(len(sys.stdin.buffer.read()))'],input=value,text=text,check=True)
    assert int(result.stdout.strip()) == len(value)


class ContainerSql:
    """Reuse psql transports while retaining fresh sessions and concurrent SQL."""

    def __init__(self, command, *, deadline=None):
        self.command = command
        self.deadline = deadline or ProcessDeadline()
        self.lock = threading.Lock()
        self.idle = []
        self.sessions = []

    def __call__(self, query):
        self.deadline.remaining()
        with self.lock:
            session = self.idle.pop() if self.idle else None
        if session is None:
            process = subprocess.Popen(self.command, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            errors = []
            reader = threading.Thread(target=lambda: errors.extend(process.stderr), daemon=True)
            reader.start()
            output = queue.Queue()
            def read_output():
                try:
                    for line in process.stdout:
                        output.put(line)
                finally:
                    output.put(None)
            stdout_reader = threading.Thread(target=read_output, daemon=True)
            stdout_reader.start()
            session = process, errors, reader, output, stdout_reader
            with self.lock:
                self.sessions.append(session)
        process, errors, reader, output, _ = session
        marker = 'memoir_sql_' + uuid4().hex
        lines = []
        try:
            # Each old one-shot psql invocation had a new session. Reset roles,
            # settings, temporary objects and psql's error presentation too.
            # Closing a one-shot connection rolled back an unfinished
            # transaction. Release its locks before returning this call too.
            written, write_errors = threading.Event(), []
            def write_input():
                try:
                    process.stdin.write('\\set VERBOSITY default\ndiscard all;\n' + query + '\nrollback;\n\\echo ' + marker + '\n')
                    process.stdin.flush()
                except Exception as error:
                    write_errors.append(error)
                finally:
                    written.set()
            writer = threading.Thread(target=write_input, daemon=True)
            writer.start()
            while not written.wait(self.deadline.remaining()):
                pass
            if write_errors:
                raise write_errors[0]
            while True:
                try:
                    line = output.get(timeout=self.deadline.remaining())
                except queue.Empty:
                    continue
                if line is None:
                    break
                if line.strip() == marker:
                    with self.lock:
                        self.idle.append(session)
                    return subprocess.CompletedProcess(self.command, 0, ''.join(lines), '')
                lines.append(line)
        except BrokenPipeError:
            pass
        except BaseException:
            process.kill()
            self._close(session)
            raise
        # The 100ms value is a polling interval, not the exit deadline.
        # Standalone fixtures retain their original five-second exit grace.
        exit_wait = (self.deadline if self.deadline.deadline is not None else
            ProcessDeadline(time.monotonic() + 5, self.deadline.cancellation))
        try:
            while process.poll() is None:
                try:
                    process.wait(timeout=exit_wait.remaining())
                except subprocess.TimeoutExpired:
                    continue
        finally:
            if process.poll() is None:
                process.kill()
            self._close(session)
        return subprocess.CompletedProcess(self.command, process.returncode or 1,
            ''.join(lines), ''.join(errors))

    @staticmethod
    def _close(session):
        process, _, reader, _, stdout_reader = session
        try:
            process.stdin.close()
        except BrokenPipeError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        reader.join(timeout=5)
        stdout_reader.join(timeout=5)
        process.stdout.close()
        process.stderr.close()

    def close(self):
        for session in self.sessions:
            self._close(session)
        self.idle.clear()
        self.sessions.clear()


def publication_guest_address(snapshot, name, port):
    """Fail closed before starting PostgreSQL on the opt-in guest interface."""
    if not isinstance(snapshot, list) or len(snapshot) != 1:
        raise ValueError('Expected exactly the task PostgreSQL container')
    container = snapshot[0]
    config = container['configuration']
    if config['id'] != name:
        raise ValueError('PostgreSQL container identity mismatch')
    expected = {'hostAddress': '127.0.0.1', 'hostPort': port,
        'containerPort': 5432, 'proto': 'tcp', 'count': 1}
    if config.get('publishedPorts') != [expected]:
        raise ValueError('PostgreSQL publication must be one exact host-loopback port')
    status = container['status']
    # Apple 1.x nests runtime networks under status; older supported releases
    # use a string status and top-level networks. Unknown shapes fail closed.
    networks = status.get('networks') if isinstance(status, dict) else container.get('networks')
    state = status.get('state') if isinstance(status, dict) else status
    if state != 'running' or not isinstance(networks, list) or len(networks) != 1:
        raise ValueError('Expected one running PostgreSQL guest interface')
    interface = ipaddress.IPv4Interface(networks[0]['ipv4Address'])
    address = interface.ip
    private = any(address in ipaddress.IPv4Network(network) for network in
        ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
    if (not private or address.is_loopback or address.is_link_local or address.is_multicast
            or address in (interface.network.network_address, interface.network.broadcast_address)):
        raise ValueError('Expected a private unicast PostgreSQL guest IPv4 address')
    return str(address)


@pytest.fixture(scope='module')
def database(*, deadline=None, cancellation=None, allocation=None, on_allocation=None,
             legacy_schema=True, postgres_image='postgres:18.3', tcp=False, publication_tcp=False,
             publication_endpoint=None, directory_root=None):
    # An opt-in guest startup gate must never wait without a task deadline.
    if publication_tcp and deadline is None:
        deadline = time.monotonic() + 180
    environment = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    commands = ProcessDeadline(deadline, cancellation, environment=environment)
    if postgres_image not in {'postgres:18.3', 'postgres:17.6'}:
        raise ValueError('Only the supported stock PostgreSQL fixture images are allowed')
    container_backend = os.getenv('MEMOIR_TEST_POSTGRES_BACKEND') == 'apple-container'
    publication_dsn = None
    if not container_backend and (os.geteuid() == 0 or not all(shutil.which(name) for name in ('initdb', 'pg_ctl', 'psql'))):
        pytest.skip('local PostgreSQL tools and a non-root account required')
    # A supplied root belongs to the supervising case process. It alone removes
    # these allocations after verified shutdown, retaining postmaster.pid/data
    # for its immediate-stop fallback if this child's bounded fast stop fails.
    directory_context = (nullcontext(tempfile.mkdtemp(prefix='memoir-lease-pg-', dir=directory_root))
        if directory_root is not None else tempfile.TemporaryDirectory(prefix='memoir-lease-pg-', dir='/tmp'))
    with directory_context as directory:
        data = str(Path(directory) / 'data')
        if container_backend:
            pg_container_name = os.getenv('MEMOIR_TEST_POSTGRES_CONTAINER_NAME') or 'memoir-issue6-pg-' + uuid4().hex[:12]
            if not re.fullmatch(r'memoir-issue6-pg-[0-9a-f]{12}', pg_container_name):
                raise ValueError('A task-owned UUID PostgreSQL container name is required')
            publish = []
            postgres = ['postgres', '-c', 'listen_addresses=' + ('*' if tcp else '')]
            if publication_tcp:
                with socket.socket() as listener:
                    listener.bind(('127.0.0.1', 0))
                    port = listener.getsockname()[1]
                publish = ['--publish', f'127.0.0.1:{port}:5432']
                # This shell owns no listener. Release it only after inspection
                # verifies the UUID, exact host binding and single guest IPv4.
                postgres = ['sh', '-ec',
                    'while [ ! -s /tmp/memoir-publication-address ]; do sleep 0.1; done; '
                    'exec docker-entrypoint.sh postgres -c '
                    '"listen_addresses=$(cat /tmp/memoir-publication-address)"']
                publication_dsn = f'host=127.0.0.1 port={port} user=postgres dbname=postgres'
                if publication_endpoint is not None:
                    publication_endpoint.update(host='127.0.0.1', port=port, container_port=5432)
            try:
                commands.remaining()
                if allocation is not None:
                    allocation['attempted'] = True
                    if on_allocation is not None:
                        on_allocation()
                commands.run(['container', 'run', '--detach', '--rm', '--name', pg_container_name,
                    '--cpus', '1', '--memory', '1G', '--env', 'POSTGRES_HOST_AUTH_METHOD=trust',
                    *publish, postgres_image, *postgres], check=True)
                if allocation is not None:
                    allocation['created'] = True
                    if on_allocation is not None:
                        on_allocation()
                if publication_tcp:
                    snapshot = commands.run(['container', 'inspect', pg_container_name], check=True, text=True)
                    address = publication_guest_address(json.loads(snapshot.stdout), pg_container_name, port)
                    if publication_endpoint is not None:
                        publication_endpoint.update(guest_address=address, binding_verified=True)
                    if on_allocation is not None:
                        on_allocation()
                    commands.run(['container', 'exec', pg_container_name, 'sh', '-ec',
                        'printf "%s" "$1" > /tmp/memoir-publication-address.tmp && '
                        'mv /tmp/memoir-publication-address.tmp /tmp/memoir-publication-address',
                        'fixture', address], check=True)
                until = time.monotonic() + 30
                while True:
                    # The image briefly starts a bootstrap server, then restarts
                    # it. Only the final server is a stable test boundary.
                    logs = commands.run(['container', 'logs', pg_container_name], text=True)
                    initialized = 'PostgreSQL init process complete; ready for start up.' in logs.stdout + logs.stderr
                    ready = commands.run(['container', 'exec', pg_container_name, 'pg_isready', '-h', '/var/run/postgresql', '-U', 'postgres']).returncode == 0
                    if initialized and ready:
                        break
                    if time.monotonic() >= until:
                        raise RuntimeError('Disposable PostgreSQL container did not become ready')
                    time.sleep(min(.25, commands.remaining()))
            except BaseException:
                ProcessDeadline(time.monotonic() + 10).run(['container', 'stop', pg_container_name], check=True)
                raise
            command = ['container', 'exec', '--interactive', pg_container_name, 'psql', '-U', 'postgres', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1', '-d', 'postgres']
        else:
            # native-tcp supports hosts that permit loopback but not Unix sockets.
            # Both modes use a fresh cluster and real, independent SQL sessions.
            tcp = tcp or os.getenv('MEMOIR_TEST_POSTGRES_BACKEND') == 'native-tcp'
            if tcp:
                with socket.socket() as listener:
                    listener.bind(('127.0.0.1', 0))
                    port = listener.getsockname()[1]
                options = f"-h 127.0.0.1 -p {port} -k ''"
                target = ['-h', '127.0.0.1', '-p', str(port)]
                publication_dsn = f'host=127.0.0.1 port={port} user=postgres dbname=postgres'
            else:
                options = f"-k {directory} -h ''"
                target = ['-h', directory]
                # Native callers can always open an independent connection to
                # this task-owned cluster. Unix sockets use PostgreSQL's default
                # port; there need not be a -p argument in the psql command.
                publication_dsn = f'host={directory} port=5432 user=postgres dbname=postgres'
            log = Path(directory) / 'server.log'
            try:
                commands.run(['initdb', '-D', data, '-U', 'postgres', '-A', 'trust', '--no-locale', '--encoding=UTF8'], check=True)
                commands.run(['pg_ctl', '-D', data, '-l', str(log),
                              '-o', options, '-w', 'start'], check=True)
            except BaseException as error:
                if (Path(data) / 'postmaster.pid').exists():
                    ProcessDeadline(time.monotonic() + 10, environment=environment).run(
                        ['pg_ctl', '-D', data, '-m', 'immediate', '-w', 'stop'], check=True)
                if isinstance(error, subprocess.CalledProcessError):
                    raise RuntimeError('Disposable PostgreSQL startup failed: ' +
                        (log.read_text() if log.exists() else str(error.stderr))) from error
                raise
            command = ['psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1', *target,
                       '-U', 'postgres', '-d', 'postgres']
        container_sql = ContainerSql(command, deadline=commands) if container_backend else None
        def sql(query, *, check=True):
            result = container_sql(query) if container_sql else commands.run(command, input=query, text=True)
            if check:
                assert result.returncode == 0, result.stderr
            return result
        sql.command = command
        sql.env = environment
        sql.publication_dsn = publication_dsn
        try:
            sql('''
                create role anon;
                create role authenticated;
                create schema auth;
                create table auth.users(id uuid primary key);
                create function auth.uid() returns uuid language sql stable as
                  $$select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid$$;
                grant usage on schema auth to authenticated;
                create schema storage;
                create table storage.buckets(id text primary key, name text, public boolean, file_size_limit bigint);
                create table storage.objects(bucket_id text, name text);
                create function storage.foldername(text) returns text[] language sql as
                  $$select string_to_array($1, '/')$$;
            ''')
            if legacy_schema:
                root = Path(__file__).resolve().parents[1] / 'supabase' / 'legacy-migrations'
                for name in ('202609230001_user_agent_storage.sql', '202609230002_agent_sessions.sql',
                             '202609250002_agent_turn_leases.sql', '202609250004_fenced_agent_turn_commit.sql'):
                    sql((root / name).read_text())
            sql(f"insert into auth.users values ('{OWNER}'), ('{OTHER}');")
            yield sql
        finally:
            try:
                if container_sql:
                    container_sql.close()
            finally:
                ProcessDeadline(time.monotonic() + 10, environment=environment).run(['container', 'stop', pg_container_name] if container_backend else
                               ['pg_ctl', '-D', data, '-m', 'fast', '-w', 'stop'], check=True)


@pytest.fixture
def sql(database):
    database('truncate public.user_agent_turn_lease, public.user_agent_session, public.user_memory;')
    return database


def as_user(query, user=OWNER):
    return f"set role authenticated; set request.jwt.claim.sub = '{user}'; {query}"


def commit(token=OLD, *, content='hello', paths="'{}'::text[]"):
    return f"select public.commit_user_agent_turn('{token}', 'thread', '{content}', {paths});"


def test_commit_checks_authenticated_lease_and_writes_both_rows(sql):
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    result = sql(as_user(commit())).stdout
    assert 'hello' in result
    assert sql('select count(*) from public.user_agent_session;').stdout.strip() == '1'
    assert sql('select count(*) from public.user_memory;').stdout.strip() == '1'
    assert sql(as_user(commit(), OTHER), check=False).returncode != 0
    assert sql("set role anon; " + commit(), check=False).returncode != 0


def test_sql_transport_resets_roles_and_stops_at_the_first_error(sql):
    baseline_user = sql('select current_user;').stdout.splitlines()[-1]
    assert sql(as_user('select current_user;')).stdout.splitlines()[-1] == 'authenticated'
    assert sql('select current_user;').stdout.splitlines()[-1] == baseline_user
    sql('begin; create temporary table transport_uncommitted(value integer);')
    assert sql("select to_regclass('transport_uncommitted');").stdout.strip() == ''
    failed = sql("select 1 / 0; select 'must not execute';", check=False)
    assert failed.returncode != 0 and 'division by zero' in failed.stderr
    assert 'must not execute' not in failed.stdout
    assert sql('select current_user;').stdout.splitlines()[-1] == baseline_user


def test_expired_or_replaced_lease_cannot_commit(sql):
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    sql("update public.user_agent_turn_lease set expires_at = clock_timestamp() - interval '1 second';")
    assert sql(as_user(commit()), check=False).returncode != 0
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{NEW}');"))
    assert sql(as_user(commit()), check=False).returncode != 0
    assert sql('select count(*) from public.user_agent_session;').stdout.strip() == '0'
    assert sql('select count(*) from public.user_memory;').stdout.strip() == '0'
    sql(as_user(commit(NEW)))


def test_memory_failure_rolls_back_session_write(sql):
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    sql("alter table public.user_memory add constraint test_reject_content check (content <> 'reject');")
    try:
        assert sql(as_user(commit(content='reject')), check=False).returncode != 0
        assert sql('select count(*) from public.user_agent_session;').stdout.strip() == '0'
    finally:
        sql('alter table public.user_memory drop constraint test_reject_content;')


def test_commit_only_publishes_its_own_staged_paths(sql):
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    wrong = f"array['sessions/turns/{NEW}/thread.jsonl']"
    assert sql(as_user(commit(paths=wrong)), check=False).returncode != 0
    right = f"array['sessions/turns/{OLD}/thread.jsonl']"
    sql(as_user(commit(paths=right)))


def test_commit_rechecks_expiry_after_waiting_for_row_lock(sql):
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    sql("update public.user_agent_turn_lease set expires_at = clock_timestamp() + interval '0.5 seconds';")
    holder = subprocess.Popen(sql.command, env=sql.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True)
    try:
        holder.stdin.write("begin; select 'locked' from public.user_agent_turn_lease for update;\n"
                           "select pg_sleep(1); commit;\n")
        holder.stdin.close()
        assert holder.stdout.readline().strip() == 'locked'
        result = sql(as_user(commit()), check=False)
        assert result.returncode != 0
        assert 'lease lost' in result.stderr
        assert sql('select count(*) from public.user_memory;').stdout.strip() == '0'
    finally:
        holder.wait(timeout=5)
