import apps.api.main as main
from apps.api.store import MemoryStore


def test_runtime_store_does_not_use_supabase_db_url(monkeypatch):
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://supabase.example.test/postgres")

    app = main.create_app()

    assert isinstance(app.state.store, MemoryStore)
    assert not hasattr(app.state.store, "database_url")


def test_runtime_store_uses_supabase_user_storage_without_db_url(monkeypatch):
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)

    app = main.create_app()

    assert isinstance(app.state.store, MemoryStore)
