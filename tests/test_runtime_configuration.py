from pathlib import Path

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


def test_migrate_target_applies_fenced_agent_commit_migration_in_order():
    makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text()
    recipe_start = makefile.index("migrate:")
    recipe_end = makefile.index("\n\ninstall_skill:", recipe_start)
    recipe = makefile[recipe_start:recipe_end]
    migrations = [
        "202609250003_story_entitlements.sql",
        "202609250004_fenced_agent_turn_commit.sql",
        "202609250005_family_price_provenance.sql",
    ]

    positions = [recipe.index(migration) for migration in migrations]

    assert positions == sorted(positions)
