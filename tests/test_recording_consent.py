"""Consent and voice retention through authenticated HTTP and real PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import threading

import pytest
import psycopg

from test_original_recordings_http import (database, workflow, approved, attachment_database,
    private_database, event_database, sql, media, upload)
from test_original_recordings_postgres import server
from test_shared_memory_events_postgres import OWNER, OTHER, as_user

POLICY = {'policy_version':'original-recordings-v1', 'locale':'en-AU',
    'expected_revision':0, 'retain_originals':True, 'ai_processing':True}
ENDPOINT = '/api/v1/memoir/story/recording-consent'


@pytest.fixture
def consent_workflow(workflow):
    client,storage,sql,objects,calls,mode = workflow
    baseline = (Path(__file__).resolve().parents[1] / 'supabase/migrations/202610180001_initial_schema.sql').read_text()
    definition = re.search(r'CREATE FUNCTION public.original_recording_authorized\(.*?\$\$;', baseline, re.S)[0]
    sql(definition.replace('CREATE FUNCTION', 'CREATE OR REPLACE FUNCTION', 1))
    sql('truncate public.user_recording_consent;')
    sql("update auth.users set email=null,email_confirmed_at=null,phone=null,phone_confirmed_at=null;")
    sql(f"update auth.users set email='voice-fixture@example.invalid',email_confirmed_at=now() where id='{OWNER}';")
    return workflow


def grant(client, **values):
    return client.put(ENDPOINT, json={**POLICY, 'action':'grant', **values})


def test_opt_in_requires_both_purposes_and_confirmed_recoverable_identity(consent_workflow, media):
    client,storage,sql,objects,calls,mode = consent_workflow
    status = client.get(ENDPOINT)
    assert status.json()['consented'] is False and status.json()['recoverable_identity'] is True
    assert status.headers['cache-control'] == 'private, no-store'
    assert upload(client, media).status_code == 403
    for missing in ['retain_originals', 'ai_processing']:
        assert grant(client, **{missing:False}).status_code == 403
    sql(f"update auth.users set email_confirmed_at=null,raw_user_meta_data='{{\"recording_consent\":true}}' where id='{OWNER}';")
    assert client.get(ENDPOINT).json()['recoverable_identity'] is False
    assert grant(client).status_code == 403
    assert not objects and not calls


def test_consent_enables_exact_original_and_withdrawal_fences_reads_and_stt(consent_workflow, media):
    client,storage,sql,objects,calls,mode = consent_workflow
    consent = grant(client)
    assert consent.status_code == 200, consent.text
    assert consent.json()['consented'] is True and consent.json()['revision'] == 1
    response = upload(client, media)
    assert response.status_code == 200, response.text
    recording = response.json()['recording']
    assert client.get(recording['content_url']).content == media[0]
    before = len(calls)
    revoked = client.put(ENDPOINT, json={**POLICY, 'action':'revoke', 'expected_revision':1})
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()['consented'] is False and revoked.json()['revision'] == 2
    assert client.get(recording['content_url']).status_code == 404
    assert client.post('/api/v1/memoir/story/transcriptions', json={'recording_id':recording['id']}).status_code == 403
    assert grant(client).status_code == 409  # A delayed grant cannot undo withdrawal.
    assert len(calls) == before
    assert grant(client, expected_revision=2).status_code == 200


def test_anonymous_outsider_and_direct_table_writes_cannot_grant_consent(consent_workflow):
    client,storage,sql,objects,calls,mode = consent_workflow
    assert client.put(ENDPOINT, headers={'Authorization':'Bearer anonymous'}, json={**POLICY,'action':'grant'}).status_code == 403
    assert client.put(ENDPOINT, headers={'Authorization':'Bearer other'}, json={**POLICY,'action':'grant','owner_id':OWNER}).status_code == 422
    assert client.put(ENDPOINT, headers={'Authorization':'Bearer invalid'}, json={**POLICY,'action':'grant'}).status_code == 401
    assert grant(client).status_code == 200
    assert client.get(ENDPOINT, headers={'Authorization':'Bearer other'}).json()['consented'] is False
    assert sql(as_user('select * from public.user_recording_consent;'),check=False).returncode != 0
    assert sql(as_user(f"select public.recording_consent_operation('{OTHER}','consent_grant','{{}}');"),check=False).returncode != 0
    assert sql(as_user("update public.original_recording_rollout set enabled=true;"),check=False).returncode != 0


def test_revocation_waits_for_admitted_provider_guard(consent_workflow, media):
    client,storage,sql,objects,calls,mode = consent_workflow
    assert grant(client).status_code == 200
    recording = upload(client,media).json()['recording']
    entered = threading.Event()
    with psycopg.connect(sql.publication_dsn) as connection, ThreadPoolExecutor() as pool:
        connection.execute('select public.recording_server_operation(%s,%s,%s,%s)', (OWNER,'read',recording['id'],'{}'))
        def withdraw():
            entered.set()
            return client.put(ENDPOINT,json={**POLICY,'action':'revoke','expected_revision':1})
        future = pool.submit(withdraw)
        assert entered.wait(2)
        # Observe the database lock rather than relying on a scheduler delay.
        with psycopg.connect(sql.publication_dsn,autocommit=True) as observer:
            import time
            until=time.monotonic()+3
            while time.monotonic()<until:
                if observer.execute("select exists(select 1 from pg_stat_activity where wait_event_type='Lock' and query like 'select public.recording_server_operation%')").fetchone()[0]:
                    break
            else: pytest.fail('Withdrawal did not wait for the provider guard')
        assert not future.done()
        connection.commit()
        assert future.result(timeout=5).json()['consented'] is False
    assert client.get(recording['content_url']).status_code == 404


def test_rollout_identity_changes_and_invalid_policy_fail_closed(consent_workflow, media):
    client,storage,sql,objects,calls,mode = consent_workflow
    assert grant(client, policy_version='outdated').status_code == 422
    assert grant(client, retain_originals='true').status_code == 422
    assert grant(client).status_code == 200
    sql(f"update auth.users set email_confirmed_at=null where id='{OWNER}';")
    assert upload(client, media).status_code == 403
    sql('update public.original_recording_rollout set enabled=false;')
    assert client.get(ENDPOINT).json()['enabled'] is False
    assert grant(client, expected_revision=1).status_code == 403
    assert client.put(ENDPOINT,json={**POLICY,'action':'revoke','expected_revision':1}).status_code == 200
    assert not calls
