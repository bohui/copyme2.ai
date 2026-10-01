from pathlib import Path

from scripts import truncate_local_data
from scripts.truncate_local_data import StorageClient


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
