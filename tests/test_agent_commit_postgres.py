"""Run fencing/atomicity checks on a disposable local PostgreSQL, never Supabase."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
from uuid import uuid4

import pytest


OWNER = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'
OLD = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
NEW = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'


class ContainerSql:
    """Reuse psql transports while retaining fresh sessions and concurrent SQL."""

    def __init__(self, command):
        self.command = command
        self.lock = threading.Lock()
        self.idle = []
        self.sessions = []

    def __call__(self, query):
        with self.lock:
            session = self.idle.pop() if self.idle else None
        if session is None:
            process = subprocess.Popen(self.command, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            errors = []
            reader = threading.Thread(target=lambda: errors.extend(process.stderr), daemon=True)
            reader.start()
            session = process, errors, reader
            with self.lock:
                self.sessions.append(session)
        process, errors, reader = session
        marker = 'memoir_sql_' + uuid4().hex
        lines = []
        try:
            # Each old one-shot psql invocation had a new session. Reset roles,
            # settings, temporary objects and psql's error presentation too.
            process.stdin.write('\\set VERBOSITY default\ndiscard all;\n' + query + '\n\\echo ' + marker + '\n')
            process.stdin.flush()
            for line in process.stdout:
                if line.strip() == marker:
                    with self.lock:
                        self.idle.append(session)
                    return subprocess.CompletedProcess(self.command, 0, ''.join(lines), '')
                lines.append(line)
        except BrokenPipeError:
            pass
        process.wait(timeout=5)
        reader.join(timeout=5)
        self._close(session)
        return subprocess.CompletedProcess(self.command, process.returncode or 1,
            ''.join(lines), ''.join(errors))

    @staticmethod
    def _close(session):
        process, _, reader = session
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
        process.stdout.close()
        process.stderr.close()

    def close(self):
        for session in self.sessions:
            self._close(session)
        self.idle.clear()
        self.sessions.clear()


@pytest.fixture(scope='module')
def database():
    container_backend = os.getenv('MEMOIR_TEST_POSTGRES_BACKEND') == 'apple-container'
    if not container_backend and (os.geteuid() == 0 or not all(shutil.which(name) for name in ('initdb', 'pg_ctl', 'psql'))):
        pytest.skip('local PostgreSQL tools and a non-root account required')
    with tempfile.TemporaryDirectory(prefix='memoir-lease-pg-', dir='/tmp') as directory:
        data = str(Path(directory) / 'data')
        if container_backend:
            pg_container_name = 'memoir-issue6-pg-' + uuid4().hex[:12]
            subprocess.run(['container', 'run', '--detach', '--rm', '--name', pg_container_name,
                '--cpus', '1', '--memory', '1G', '--env', 'POSTGRES_HOST_AUTH_METHOD=trust',
                'postgres:18.3', 'postgres', '-c', 'listen_addresses='], check=True, capture_output=True)
            try:
                until = time.monotonic() + 30
                while True:
                    # The image briefly starts a bootstrap server, then restarts
                    # it. Only the final server is a stable test boundary.
                    logs = subprocess.run(['container', 'logs', pg_container_name], capture_output=True, text=True)
                    initialized = 'PostgreSQL init process complete; ready for start up.' in logs.stdout + logs.stderr
                    ready = subprocess.run(['container', 'exec', pg_container_name, 'pg_isready', '-h', '/var/run/postgresql', '-U', 'postgres'], capture_output=True).returncode == 0
                    if initialized and ready:
                        break
                    if time.monotonic() >= until:
                        raise RuntimeError('Disposable PostgreSQL container did not become ready')
                    time.sleep(.25)
            except BaseException:
                subprocess.run(['container', 'stop', pg_container_name], check=True, capture_output=True)
                raise
            command = ['container', 'exec', '--interactive', pg_container_name, 'psql', '-U', 'postgres', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1', '-d', 'postgres']
        else:
            subprocess.run(['initdb', '-D', data, '-A', 'trust', '--no-locale'], check=True, capture_output=True)
            subprocess.run(['pg_ctl', '-D', data, '-l', str(Path(directory) / 'server.log'),
                            '-o', f"-k {directory} -h ''", '-w', 'start'], check=True, capture_output=True)
            command = ['psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1', '-h', directory, '-d', 'postgres']
        container_sql = ContainerSql(command) if container_backend else None
        def sql(query, *, check=True):
            result = container_sql(query) if container_sql else subprocess.run(
                command, input=query, capture_output=True, text=True)
            if check:
                assert result.returncode == 0, result.stderr
            return result
        sql.command = command
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
                subprocess.run(['container', 'stop', pg_container_name] if container_backend else
                               ['pg_ctl', '-D', data, '-m', 'fast', '-w', 'stop'], check=True, capture_output=True)


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
    assert sql(as_user('select current_user;')).stdout.splitlines()[-1] == 'authenticated'
    assert sql('select current_user;').stdout.splitlines()[-1] == 'postgres'
    failed = sql("select 1 / 0; select 'must not execute';", check=False)
    assert failed.returncode != 0 and 'division by zero' in failed.stderr
    assert 'must not execute' not in failed.stdout
    assert sql('select current_user;').stdout.splitlines()[-1] == 'postgres'


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
    holder = subprocess.Popen(sql.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
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
