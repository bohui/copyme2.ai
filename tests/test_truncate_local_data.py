from scripts.truncate_local_data import StorageClient


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
