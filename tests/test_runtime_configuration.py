import pytest

import apps.api.main as main
from apps.api.store import MemoryStore


def test_runtime_store_uses_supabase_db_url(monkeypatch):
    calls = []

    def fake_from_url(url, *, object_store_path=None):
        calls.append((url, object_store_path))
        return MemoryStore()

    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://supabase.example.test/postgres")
    monkeypatch.delenv("MEMORY_SPARK_TEST_MODE", raising=False)
    monkeypatch.setattr(main.PostgresMemoryStore, "from_url", fake_from_url)

    main.create_app()

    assert calls == [("postgresql://supabase.example.test/postgres", None)]


def test_runtime_requires_supabase_db_url_outside_test_mode(monkeypatch):
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    monkeypatch.delenv("MEMORY_SPARK_TEST_MODE", raising=False)

    with pytest.raises(RuntimeError, match="SUPABASE_DB_URL must be configured"):
        main.create_app()
