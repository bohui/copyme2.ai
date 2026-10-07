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


def test_migrate_target_uses_supabase_migration_tracking():
    makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text()
    recipe_start = makefile.index("migrate:")
    recipe_end = makefile.index("\n\ninstall_skill:", recipe_start)
    recipe = makefile[recipe_start:recipe_end]

    assert "supabase db push --db-url" in recipe
    assert "--yes" in recipe
    assert "SUPABASE_DB_URL" in recipe
    assert "psql" not in recipe


def test_supabase_has_a_baseline_and_uniquely_versioned_incremental_migrations():
    migrations = sorted((Path(__file__).resolve().parents[1] / "supabase/migrations").glob("*.sql"))

    assert migrations[0].name == "202610010001_initial_schema.sql"
    versions = [migration.name.split('_', 1)[0] for migration in migrations]
    assert all(version.isdigit() and len(version) == 12 for version in versions)
    assert len(versions) == len(set(versions))
    assert "202610020003_place_photo_searches.sql" in {migration.name for migration in migrations}


def test_skill_install_rebuilds_the_api_and_codex_worker_without_a_harness():
    makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text()
    recipe = makefile.split("\ninstall_skill:", 1)[1].split("\n\nSTRIPE_MODE", 1)[0]

    assert "compose build -f $(COMPOSE_FILE) api codex-worker" in recipe
    assert "compose up -f $(COMPOSE_FILE) --no-build --force-recreate" in recipe
    assert "codex-harness" not in recipe


def test_temporal_worker_can_dispatch_supabase_memoir_lanes():
    compose = (Path(__file__).resolve().parents[1] / 'compose.yml').read_text()
    worker = compose.split('\n  worker:\n', 1)[1].split('\n  temporal:\n', 1)[0]
    assert 'SUPABASE_URL: ${SUPABASE_URL:-}' in worker
    assert 'SUPABASE_SECRET_KEY: ${SUPABASE_SECRET_KEY:-}' in worker
    assert 'MEMORY_SPARK_MEMOIR_COMPOSER_MODEL: ${MEMORY_SPARK_MEMOIR_COMPOSER_MODEL:-memoir-luna-low}' in worker
