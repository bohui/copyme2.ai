"""Atomic locale provenance on real, disposable PostgreSQL (never Supabase).

Run with initdb, pg_ctl and psql on PATH. The fixture owns a fresh /tmp cluster,
listens only on loopback, uses no live credentials and always stops its server.
No single-user fallback: these tests must exercise real RLS and row contention.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import select
import shutil
import socket
import subprocess
import tempfile
import time
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[1]
OWNER = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'
GUEST = '33333333-3333-4333-8333-333333333333'


def literal(value):
    return 'null' if value is None else "'" + str(value).replace("'", "''") + "'"


def as_user(query, owner=OWNER, role='authenticated'):
    assert role in ('authenticated', 'anon')
    return (f"set role {role}; set request.jwt.claim.sub={literal(owner or '')}; "
            + query)


@pytest.fixture(scope='module')
def locale_postgres():
    tools = {name: shutil.which(name) for name in ('initdb', 'pg_ctl', 'psql')}
    if os.geteuid() == 0 or not all(tools.values()):
        pytest.skip('real locale concurrency tests require local PostgreSQL tools and a non-root user')
    # Ignore inherited connection targets and settings; this fixture can never
    # redirect itself to a developer or remote database through PG* variables.
    env = {key: value for key, value in os.environ.items() if not key.startswith('PG')}
    with tempfile.TemporaryDirectory(prefix='memoir-ui-locale-', dir='/tmp') as directory:
        data = str(Path(directory) / 'data')
        log = str(Path(directory) / 'postgres.log')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        subprocess.run([tools['initdb'], '-D', data, '-U', 'locale_fixture', '-A', 'trust',
                        '--no-locale', '--encoding=UTF8'], env=env, check=True,
                       capture_output=True, text=True, timeout=30)
        command = [tools['psql'], '-X', '-qAt', '-v', 'ON_ERROR_STOP=1', '-h', '127.0.0.1',
                   '-p', str(port), '-U', 'locale_fixture', '-d', 'postgres']

        def sql(query, *, check=True):
            result = subprocess.run(command, input="set statement_timeout='12s';\n" + query,
                                    env=env, capture_output=True, text=True, timeout=15)
            if check:
                assert result.returncode == 0, result.stderr
            return result

        sql.command = command
        sql.env = env
        started = False
        try:
            start = subprocess.run([tools['pg_ctl'], '-D', data, '-l', log, '-t', '10', '-w',
                '-o', f"-h 127.0.0.1 -p {port} -k '' -c shared_buffers=16MB -c max_connections=12 "
                      '-c work_mem=1MB -c maintenance_work_mem=16MB -c max_wal_size=64MB '
                      '-c max_parallel_workers=0 -c jit=off', 'start'],
                env=env, capture_output=True, text=True, timeout=15)
            assert start.returncode == 0, start.stderr + Path(log).read_text()
            started = True
            sql('''
                create role anon;
                create role authenticated;
                create schema auth;
                create table auth.users(
                  id uuid primary key,
                  raw_user_meta_data jsonb not null default '{}',
                  is_anonymous boolean not null default false
                );
                create function auth.uid() returns uuid language sql stable as
                  $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
                grant usage on schema auth to authenticated;
            ''')
            # Empty before the implementation, so TDD fails on missing RPCs.
            for migration in sorted((ROOT / 'supabase/migrations').glob('*ui_locale*.sql')):
                sql(migration.read_text())
            yield sql
        finally:
            if started or (Path(data) / 'postmaster.pid').exists():
                stop = subprocess.run([tools['pg_ctl'], '-D', data, '-m', 'immediate',
                                       '-t', '10', '-w', 'stop'], env=env,
                                      capture_output=True, text=True, timeout=15)
                assert stop.returncode == 0, stop.stderr


@pytest.fixture
def sql(locale_postgres):
    # Users cascade-delete only this isolated fixture's preference rows.
    locale_postgres('delete from auth.users;')
    locale_postgres(f"insert into auth.users(id,is_anonymous) values "
                    f"('{OWNER}',false),('{OTHER}',false),('{GUEST}',true);")
    return locale_postgres


def read(sql, owner=OWNER):
    return json.loads(sql(as_user(f'select public.read_ui_locale_preference({literal(owner)});', owner)).stdout)


def write(sql, locale='zh-CN', source='first_reply', owner=OWNER):
    return json.loads(sql(as_user(f'select public.set_ui_locale_preference('
                                 f'{literal(locale)},{literal(source)},{literal(owner)});', owner)).stdout)


def test_empty_account_has_no_preference(sql):
    assert read(sql) is None


def test_first_detection_is_frozen_and_returns_authoritative_record(sql):
    first = write(sql)
    assert first == {'locale': 'zh-CN', 'source': 'first_reply', 'revision': 1}
    assert write(sql, 'en-AU') == first
    assert read(sql) == first


def test_manual_overrides_detection_and_blocks_later_detection(sql):
    assert write(sql)['revision'] == 1
    manual = write(sql, 'en-AU', 'manual')
    assert manual == {'locale': 'en-AU', 'source': 'manual', 'revision': 2}
    assert write(sql, 'zh-CN') == manual
    assert read(sql) == manual


def test_manual_first_blocks_detection_and_same_value_is_idempotent(sql):
    manual = write(sql, 'en-AU', 'manual')
    assert write(sql, 'zh-CN') == manual
    assert write(sql, 'en-AU', 'manual') == manual
    assert write(sql, 'zh-CN', 'manual')['revision'] == 2


def test_same_locale_manual_promotes_provenance(sql):
    write(sql)
    assert write(sql, 'zh-CN', 'manual') == {
        'locale': 'zh-CN', 'source': 'manual', 'revision': 2}
    assert write(sql, 'en-AU')['source'] == 'manual'


@pytest.mark.parametrize('locale,source', [
    (None, 'manual'), ('', 'manual'), ('zh', 'manual'), ('en-US', 'manual'),
    ('ZH-CN', 'manual'), ('zh-CN ', 'manual'), ('zh-CN', None),
    ('zh-CN', ''), ('zh-CN', 'browser'), ('zh-CN', 'MANUAL'),
])
def test_invalid_inputs_do_not_mutate_existing_preference(sql, locale, source):
    before = write(sql, 'en-AU', 'manual')
    result = sql(as_user(f'select public.set_ui_locale_preference('
                        f'{literal(locale)},{literal(source)},{literal(OWNER)});'), check=False)
    assert result.returncode != 0
    assert read(sql) == before


def test_source_less_legacy_locale_is_established_manual_and_metadata_stays_intact(sql):
    metadata = {'ui_locale': 'en-AU', 'display_name': 'Storyteller', 'other': {'keep': True}}
    sql(f'update auth.users set raw_user_meta_data={literal(json.dumps(metadata))}::jsonb '
        f"where id='{OWNER}';")
    assert read(sql) == {'locale': 'en-AU', 'source': 'manual', 'revision': 0}
    legacy = write(sql, 'zh-CN')
    assert legacy == {'locale': 'en-AU', 'source': 'manual', 'revision': 1}
    assert write(sql, 'zh-CN', 'manual') == {
        'locale': 'zh-CN', 'source': 'manual', 'revision': 2}
    assert read(sql)['locale'] == 'zh-CN'
    unchanged = json.loads(sql(f"select raw_user_meta_data from auth.users where id='{OWNER}';").stdout)
    assert unchanged == metadata


@pytest.mark.parametrize('legacy', [None, '', 'en-US', 123, {'locale': 'zh-CN'}])
def test_invalid_legacy_metadata_does_not_block_first_detection(sql, legacy):
    sql(f"update auth.users set raw_user_meta_data={literal(json.dumps({'ui_locale': legacy}))}::jsonb "
        f"where id='{OWNER}';")
    assert read(sql) is None
    assert write(sql) == {'locale': 'zh-CN', 'source': 'first_reply', 'revision': 1}


def test_preferences_are_own_user_and_authenticated_anonymous_users_work(sql):
    write(sql, 'en-AU', 'manual', OWNER)
    write(sql, 'zh-CN', 'first_reply', OTHER)
    assert read(sql, OWNER)['locale'] == 'en-AU'
    assert read(sql, OTHER)['locale'] == 'zh-CN'
    assert write(sql, owner=GUEST) == {'locale': 'zh-CN', 'source': 'first_reply', 'revision': 1}
    assert sql(as_user('select user_id from public.user_ui_locale_preference order by user_id;')).stdout.strip() == OWNER
    assert sql(as_user('select count(*) from public.user_ui_locale_preference;', GUEST)).stdout.strip() == '1'


@pytest.mark.parametrize('role,owner', [('anon', None), ('anon', OWNER),
                                       ('authenticated', None), ('authenticated', '44444444-4444-4444-8444-444444444444')])
def test_unauthenticated_or_nonexistent_actor_cannot_call_rpcs(sql, role, owner):
    for query in (f'select public.read_ui_locale_preference({literal(OWNER)});',
                  f"select public.set_ui_locale_preference('zh-CN','manual',{literal(OWNER)});"):
        result = sql(as_user(query, owner, role), check=False)
        assert result.returncode != 0
    assert sql('select count(*) from public.user_ui_locale_preference;').stdout.strip() == '0'


@pytest.mark.parametrize('query', [
    f"insert into public.user_ui_locale_preference(user_id,locale,source) values ('{OTHER}','zh-CN','manual');",
    "update public.user_ui_locale_preference set locale='zh-CN';",
    'delete from public.user_ui_locale_preference;',
    'truncate public.user_ui_locale_preference;',
])
def test_authenticated_direct_writes_are_denied(sql, query):
    original = write(sql, 'en-AU', 'manual')
    assert sql(as_user(query), check=False).returncode != 0
    assert read(sql) == original


def test_rpc_security_contract_and_rls_are_explicit(sql):
    assert sql('''select bool_and(prosecdef and proconfig @> array['search_path=""'])
      from pg_proc where oid in ('public.read_ui_locale_preference(uuid)'::regprocedure,
        'public.set_ui_locale_preference(text,text,uuid)'::regprocedure);''').stdout.strip() == 't'
    assert sql("select relrowsecurity from pg_class where oid='public.user_ui_locale_preference'::regclass;").stdout.strip() == 't'
    for rpc in ('public.read_ui_locale_preference(uuid)', 'public.set_ui_locale_preference(text,text,uuid)'):
        assert sql(f"select has_function_privilege('anon','{rpc}','execute');").stdout.strip() == 'f'
        assert sql(f"select has_function_privilege('authenticated','{rpc}','execute');").stdout.strip() == 't'
    assert sql("select has_table_privilege('anon','public.user_ui_locale_preference','select');").stdout.strip() == 'f'
    assert sql("select has_table_privilege('authenticated','public.user_ui_locale_preference','insert,update,delete');").stdout.strip() == 'f'
    # No caller-supplied owner overload can bypass the auth.uid boundary.
    assert sql("select count(*) from pg_proc join pg_namespace n on n.oid=pronamespace "
               "where n.nspname='public' and proname in ('read_ui_locale_preference','set_ui_locale_preference');").stdout.strip() == '2'


def competing_writes(sql, first, second):
    """Prove the second RPC waits on the first transaction before committing."""
    held = subprocess.Popen(sql.command, env=sql.env, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    waiter_name = 'locale_waiter_' + uuid4().hex
    try:
        held.stdin.write(as_user('begin;\n\\o /dev/null\nselect public.set_ui_locale_preference('
                                f'{literal(first[0])},{literal(first[1])},{literal(OWNER)});\n'
                                '\\o\n\\echo LOCK_HELD\n'))
        held.stdin.flush()
        assert select.select([held.stdout], [], [], 5)[0], 'first writer did not acquire its row lock'
        assert held.stdout.readline().strip() == 'LOCK_HELD'
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(sql, f"set application_name='{waiter_name}'; " + as_user(
                f'select public.set_ui_locale_preference({literal(second[0])},{literal(second[1])},{literal(OWNER)});'))
            try:
                until = time.monotonic() + 5
                while time.monotonic() < until:
                    waiting = sql(f"select count(*) from pg_stat_activity where application_name='{waiter_name}' "
                                  "and wait_event_type='Lock';").stdout.strip()
                    if waiting == '1':
                        break
                    assert not future.done(), 'second writer escaped serialization'
                    time.sleep(.02)
                else:
                    pytest.fail('second writer was not observed waiting for the same account')
            finally:
                held.stdin.write('commit;\n\\q\n')
                held.stdin.flush()
                held.communicate(timeout=5)
            return json.loads(future.result(timeout=5).stdout)
    finally:
        if held.poll() is None:
            held.kill()
            held.communicate(timeout=5)


@pytest.mark.parametrize('first,second,expected', [
    (('zh-CN', 'first_reply'), ('en-AU', 'first_reply'), ('zh-CN', 'first_reply', 1)),
    (('zh-CN', 'first_reply'), ('en-AU', 'manual'), ('en-AU', 'manual', 2)),
    (('en-AU', 'manual'), ('zh-CN', 'first_reply'), ('en-AU', 'manual', 1)),
    (('zh-CN', 'manual'), ('en-AU', 'manual'), ('en-AU', 'manual', 2)),
])
def test_competing_initializations_and_manual_detection_both_orders(sql, first, second, expected):
    result = competing_writes(sql, first, second)
    assert result == dict(zip(('locale', 'source', 'revision'), expected))
    assert read(sql) == result
    assert sql('select count(*) from public.user_ui_locale_preference;').stdout.strip() == '1'


def test_concurrent_legacy_detection_cannot_replace_established_preference(sql):
    sql(f"update auth.users set raw_user_meta_data='{{\"ui_locale\":\"en-AU\"}}' where id='{OWNER}';")
    assert competing_writes(sql, ('zh-CN', 'first_reply'), ('zh-CN', 'first_reply')) == {
        'locale': 'en-AU', 'source': 'manual', 'revision': 1}


def test_deleting_account_cascades_preference(sql):
    write(sql)
    sql(f"delete from auth.users where id='{OWNER}';")
    assert sql('select count(*) from public.user_ui_locale_preference;').stdout.strip() == '0'


@pytest.mark.parametrize('expected', [None, OWNER])
def test_captured_actor_cannot_follow_switched_sdk_token(sql, expected):
    for query in (f'select public.read_ui_locale_preference({literal(expected)});',
                  f"select public.set_ui_locale_preference('zh-CN','manual',{literal(expected)});"):
        result=sql(as_user(query,OTHER),check=False)
        assert result.returncode != 0
    assert read(sql,OTHER) is None
