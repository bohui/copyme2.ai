"""Retirement migration on disposable PostgreSQL; never the development project."""
from pathlib import Path

import pytest

from test_agent_commit_postgres import as_user, database  # noqa: F401 - imported pytest fixture
from test_guest_conversation_transfer import attachment_database  # noqa: F401 - imported pytest fixture
from test_private_rounds_postgres import private_database  # noqa: F401 - imported pytest fixture


@pytest.fixture(scope='module')
def canonical_database(private_database):
    root = Path(__file__).resolve().parents[1]
    for path in sorted((root / 'supabase/migrations').glob('*.sql')):
        if path.name >= '202610040001':
            private_database(path.read_text())
    return private_database


def test_new_owner_can_resolve_without_legacy_rollout_attestation(canonical_database):
    sql = canonical_database
    assert sql("select to_regclass('public.lifetime_realtime_clearance') is null;").stdout.strip() == 't'
    result = sql(as_user('select public.resolve_lifetime_conversation(null);'))
    assert 'resolved' in result.stdout
    assert sql(as_user('select public.lock_lifetime_provider_activation();')).returncode == 0
    assert sql(as_user('select public.read_lifetime_admission(null);')).stdout.strip() == 'governed'


@pytest.mark.parametrize('function', ['lock_lifetime_realtime_admission()', 'lock_lifetime_legacy_worker_admission()'])
def test_retired_admission_cannot_be_used_by_old_clients(canonical_database, function):
    sql = canonical_database
    assert sql(as_user('select public.' + function + ';'), check=False).returncode != 0
    assert sql('select public.' + function + ';', check=False).returncode != 0


def test_unknown_owner_cannot_enter_provider(canonical_database):
    from uuid import UUID
    assert canonical_database(as_user('select public.lock_lifetime_provider_activation();', str(UUID(int=77))), check=False).returncode != 0


def test_collection_polling_enforces_page_bounds(canonical_database):
    sql = canonical_database
    assert sql("set role service_role; select public.pending_lifetime_collection_jobs(8,true);").stdout.strip() == '[]'
    assert sql("set role service_role; select public.pending_lifetime_collection_jobs(0,true);", check=False).returncode != 0
