"""Disposable canonical state for provider-free, process-isolated tooling.

This harness is never a deployment or a live adapter. Restored legacy places
are display observations only; they are not imported as narrator testimony.
Canonical state is copied only between fresh disposable databases. Runtime
identity, admission, lease, persistence and publication remain application SQL.
"""
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import sys
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
STATE_VERSION = 'memoir-controlled-canonical-state/1'


def _test_adapter():
    tests = str(ROOT / 'tests')
    if tests not in sys.path:
        sys.path.insert(0, tests)
    from memoir_postgres_workflow import PostgresRest, quoted, seed_fresh_canonical_project
    return PostgresRest, quoted, seed_fresh_canonical_project


@contextmanager
def controlled_database():
    """A new local Unix-socket database, never an inherited service or Mac."""
    _test_adapter()
    from test_shared_memory_events_postgres import database, attachment_database, private_database, event_database
    if os.getenv('MEMOIR_TEST_POSTGRES_BACKEND', 'native') != 'native':
        raise ValueError('Controlled cloud tooling requires the local native PostgreSQL backend')
    generator = database.__wrapped__()
    try:
        sql = next(generator)
        sql = event_database.__wrapped__(private_database.__wrapped__(attachment_database.__wrapped__(sql)))
        previous_legacy = os.environ.pop('MEMOIR_LEGACY_ONLY_DEPLOYMENT', None)
        previous = os.environ.get('MEMOIR_PUBLICATION_DATABASE_URL')
        os.environ['MEMOIR_PUBLICATION_DATABASE_URL'] = sql.publication_dsn
        try:
            yield sql
        finally:
            if previous_legacy is not None:
                os.environ['MEMOIR_LEGACY_ONLY_DEPLOYMENT'] = previous_legacy
            if previous is None:
                os.environ.pop('MEMOIR_PUBLICATION_DATABASE_URL', None)
            else:
                os.environ['MEMOIR_PUBLICATION_DATABASE_URL'] = previous
    finally:
        generator.close()


def owner_tables(sql):
    # Names come from this just-created schema, never a snapshot or case input.
    tables = json.loads(sql("""select json_agg(table_name order by table_name) from information_schema.columns
        where table_schema='public' and table_name in (select table_name from information_schema.tables where table_schema='public' and table_type='BASE TABLE') and column_name='user_id' and table_name like 'user\\_%' escape '\\';""").stdout)
    if not tables or not all(re.fullmatch('user_[a-z_]+', name) for name in tables):
        raise ValueError('Controlled schema table identity is unavailable')
    return tables


def open_case(sql, case, state=None):
    """Fresh owner insertion rejects collisions; restoration accepts data only."""
    PostgresRest, quoted, seed = _test_adapter()
    state = state or {}
    canonical = state.get('canonical_state')
    if canonical is not None and state.get('schema_version') != STATE_VERSION:
        raise ValueError('Unsupported controlled canonical snapshot')
    owner = state.get('user_id') if canonical is not None else str(uuid4())
    if str(UUID(owner)) != owner:
        raise ValueError('Controlled owner must be a UUID')
    project = case['project_id']
    sql(f"insert into auth.users(id,is_anonymous) values({quoted(owner)},false);")
    allowed = owner_tables(sql)
    if canonical is None:
        seed(sql, owner, project)
    else:
        if state.get('project_id') != project or set(canonical) - set(allowed):
            raise ValueError('Controlled snapshot project or table scope mismatch')
        commands = ['begin;', 'set local session_replication_role=replica;']
        for table, records in canonical.items():
            if not isinstance(records, list):
                raise ValueError('Controlled snapshot records must be arrays')
            for row in records:
                if row.get('user_id') != owner or ('project_id' in row and row['project_id'] != project):
                    raise ValueError('Controlled snapshot contains another owner or project')
            # JSON values never become SQL, identifiers or psql commands. Disabling
            # insert triggers here restores exact synthetic state, not new input.
            columns = json.loads(sql(f"select json_agg(column_name order by ordinal_position) from information_schema.columns where table_schema='public' and table_name={quoted(table)} and is_generated='NEVER';").stdout)
            if not columns or not all(re.fullmatch('[a-z_][a-z0-9_]*', column) for column in columns):
                raise ValueError('Controlled schema columns unavailable')
            names = ','.join(columns)
            commands.append(f'insert into public.{table}({names}) select {names} from jsonb_populate_recordset(null::public.{table},{quoted(records)});')
        commands.append('commit;')
        sql('\n'.join(commands))
    entitlement = {'status':'paid','plan_key':'family_memoir_v1','family_tree':True,'timeline':True,
        'stripe_price_id':os.getenv('STRIPE_PRICE_FAMILY','synthetic-family-price')}
    adapter = PostgresRest(sql, owner, entitlement=entitlement)
    storage = adapter.storage()
    storage.project_id = project
    # Old snapshots cannot prove canonical original evidence. Preserve their
    # prior place display while canonical current-turn places use normal SQL.
    restored_places = deepcopy(state.get('legacy_place_history', state.get('place_history', []))) if canonical is None else deepcopy(state.get('legacy_place_history', []))
    return storage, adapter, restored_places


def snapshot_case(sql, storage, legacy_places):
    _, quoted, _ = _test_adapter()
    tables = {name:json.loads(sql(f'select coalesce(json_agg(t),\'[]\') from public.{name} t where user_id={quoted(storage.user_id)};').stdout)
        for name in owner_tables(sql)}
    places = deepcopy(legacy_places) + storage.lifetime_rpc('read_lifetime_place_journeys', p_project_id=storage.project_id)
    return {'schema_version':STATE_VERSION,'evidence_mode':'mock_only','user_id':storage.user_id,
        'project_id':storage.project_id,'canonical_state':tables,'legacy_place_history':deepcopy(legacy_places),
        'profile':storage.profile(),'memories':storage.all_memories(),'place':storage.place_journey(),
        'place_history':places,'family':storage.family_context(storage.project_id),
        'rounds_completed':storage.recall_rounds_completed()}
