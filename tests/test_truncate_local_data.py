from pathlib import Path
import json
import subprocess

import pytest

from scripts import truncate_local_data
from scripts.truncate_local_data import StorageClient
from test_agent_commit_postgres import database, OWNER


def test_storage_lists_all_buckets(monkeypatch):
    client = StorageClient("https://example.test", "secret")

    def request(method, path, payload=None):
        assert (method, path, payload) == ("GET", "bucket", None)
        return [{"name": "uploads"}, {"name": "memory-spark"}, {"name": "uploads"}]

    monkeypatch.setattr(client, "_request", request)

    assert client.list_buckets() == ["memory-spark", "uploads"]


def test_storage_remove_uses_supabase_delete_objects_endpoint(monkeypatch):
    client = StorageClient("https://example.test", "secret", "memory-spark")
    calls = []

    def delete(path, payload):
        calls.append((path, payload))
        return []

    monkeypatch.setattr(client, "_delete", delete)

    client.remove_objects(["user-a/agent/one.jsonl", "user-a/agent/two.jsonl"])

    assert calls == [
        (
            "object/memory-spark",
            {"prefixes": ["user-a/agent/one.jsonl", "user-a/agent/two.jsonl"]},
        )
    ]


def test_truncate_database_deletes_auth_users(monkeypatch):
    calls = []

    def run(command, check):
        calls.append((command, check))

    monkeypatch.setattr(truncate_local_data.subprocess, "run", run)

    truncate_local_data.truncate_database("postgresql://example.test/postgres")

    command, check = calls[0]
    sql = command[-1]
    assert check is True
    assert "public.guest_conversation_transfer" in sql
    assert "public.guest_merge_asset_access" in sql
    assert "restart identity cascade" in sql
    assert "delete from auth.users;" in sql


def test_clear_local_data_path_removes_contents_inside_allowed_root(tmp_path):
    data_path = tmp_path / "var" / "codex-users"
    (data_path / "user-a").mkdir(parents=True)
    (data_path / "user-a" / "memory.sqlite").write_text("data")

    removed = truncate_local_data.clear_local_data_path(
        str(data_path),
        Path(tmp_path),
        allowed_root=Path("var"),
        expected_name="codex-users",
    )

    assert removed == 1
    assert list(data_path.iterdir()) == []


@pytest.fixture(scope='module')
def cache_database(database):
    database('create role service_role;')
    migration = Path(__file__).resolve().parents[1] / 'supabase/migrations/202610020003_place_photo_searches.sql'
    database(migration.read_text())
    return database


@pytest.fixture
def reset_fixture(cache_database, monkeypatch):
    sql = cache_database
    sql('truncate public.user_memory, public.user_profile, public.place_photo_searches cascade;')
    sql(f"insert into auth.users(id) values ('{OWNER}') on conflict do nothing;")
    sql(f"insert into public.user_profile(user_id,profile) values ('{OWNER}','{{}}');")
    sql(f"insert into public.user_memory(user_id,kind,content) values ('{OWNER}','agent','Synthetic fixture');")
    result = {'items':[{'source_url':'https://archive.example/photo','image_url':'https://images.example/photo.jpg'}], 'complete':True}
    sql(f"insert into public.place_photo_searches(search_key,place,period,result) values ('{'a'*64}','Fixture place','1980s','{json.dumps(result)}');")
    original_run = subprocess.run
    def isolated_run(command, *args, **kwargs):
        if command[:2] == ['psql','-X'] and len(command) > 2 and command[2] == 'isolated-fixture':
            return original_run([*sql.command, '-c', command[-1]], *args, **kwargs)
        return original_run(command, *args, **kwargs)
    monkeypatch.setattr(truncate_local_data.subprocess, 'run', isolated_run)
    return sql, result


def test_real_reset_preserves_photo_cache_while_user_tables_auth_and_cascaded_rows_clear(reset_fixture):
    sql, result = reset_fixture
    sql('create table public.reset_child(id serial primary key, memory_id uuid references public.user_memory(id));')
    try:
        sql('insert into public.reset_child(memory_id) select id from public.user_memory;')
        before = sql('select row_to_json(c) from public.place_photo_searches c;').stdout
        truncate_local_data.truncate_database('isolated-fixture')
        assert sql('select row_to_json(c) from public.place_photo_searches c;').stdout == before
        assert json.loads(sql('select result from public.place_photo_searches;').stdout) == result
        for table in ('public.user_profile','public.user_memory','public.reset_child','auth.users'):
            assert sql(f'select count(*) from {table};').stdout.strip() == '0'
    finally:
        sql('drop table public.reset_child;')


def test_transitive_cascade_to_cache_refuses_reset_before_any_rows_clear(reset_fixture):
    sql, _ = reset_fixture
    sql('create table public.reset_middle(id uuid primary key, memory_id uuid references public.user_memory(id));')
    sql('alter table public.place_photo_searches add column middle_id uuid references public.reset_middle(id) on delete cascade;')
    try:
        sql('insert into public.reset_middle(id,memory_id) select id,id from public.user_memory;')
        sql('update public.place_photo_searches set middle_id=(select id from public.reset_middle limit 1);')
        before = sql('select row_to_json(c) from public.place_photo_searches c;').stdout
        with pytest.raises(RuntimeError, match='psql failed'):
            truncate_local_data.truncate_database('isolated-fixture')
        assert sql('select row_to_json(c) from public.place_photo_searches c;').stdout == before
        assert sql('select count(*) from public.user_memory;').stdout.strip() == '1'
        assert sql('select count(*) from public.user_profile;').stdout.strip() == '1'
        assert int(sql('select count(*) from auth.users;').stdout) > 0
    finally:
        sql('alter table public.place_photo_searches drop column middle_id; drop table public.reset_middle;')


def test_partition_or_inheritance_dependency_is_also_protected(reset_fixture, monkeypatch):
    sql, _ = reset_fixture
    sql('create table public.reset_parent(); alter table public.place_photo_searches inherit public.reset_parent;')
    monkeypatch.setattr(truncate_local_data, 'APP_TABLES', (*truncate_local_data.APP_TABLES, 'public.reset_parent'))
    try:
        with pytest.raises(RuntimeError, match='psql failed'):
            truncate_local_data.check_reset_scope('isolated-fixture')
        assert sql('select count(*) from public.place_photo_searches;').stdout.strip() == '1'
    finally:
        sql('alter table public.place_photo_searches no inherit public.reset_parent; drop table public.reset_parent;')


def test_scope_preflight_precedes_storage_and_file_deletion(monkeypatch):
    monkeypatch.setenv('SUPABASE_DB_URL','isolated-fixture')
    monkeypatch.setenv('SUPABASE_URL','https://fixture.test')
    monkeypatch.setenv('SUPABASE_SECRET_KEY','fixture-only')
    def blocked(_): raise RuntimeError('cache dependency blocked')
    monkeypatch.setattr(truncate_local_data,'check_reset_scope',blocked)
    monkeypatch.setattr(truncate_local_data,'StorageClient',lambda *args:pytest.fail('Storage deletion started before preflight'))
    with pytest.raises(RuntimeError,match='cache dependency blocked'):
        truncate_local_data.reset_data()


def test_user_file_reset_preserves_per_run_public_search_metadata(tmp_path, monkeypatch):
    cache = tmp_path/'var/photo-research/fixture-run/search-cache/fixture.json'
    cache.parent.mkdir(parents=True)
    cache.write_text('{"cards":[],"status":"success"}')
    objects = tmp_path/'var/memory-spark/objects'
    objects.mkdir(parents=True)
    (objects/'fixture.txt').write_text('user object')
    users = tmp_path/'var/codex-users/fixture-user'
    users.mkdir(parents=True)
    (users/'fixture.txt').write_text('user state')
    for name, _, _ in truncate_local_data.LOCAL_CODEX_DATA_PATHS:
        monkeypatch.delenv(name,raising=False)
    truncate_local_data.clear_local_object_store(str(objects),tmp_path)
    truncate_local_data.clear_local_codex_data(tmp_path)
    assert cache.read_text() == '{"cards":[],"status":"success"}'
    assert not list(objects.iterdir())
    assert not list((tmp_path/'var/codex-users').iterdir())
