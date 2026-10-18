"""Retired user mode controls cannot compete with the persisted AI strategy."""
import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.store import MemoryStore
from test_lifetime_memory_postgres import database, attachment_database, private_database, event_database, sql
from test_shared_memory_events_postgres import rpc, literal


def test_mode_controls_are_absent_from_http_contract():
    with TestClient(create_app(MemoryStore())) as client:
        url='/v1/agent/projects/project/conversation-phase'
        assert client.get(url).status_code==404
        assert client.patch(url,json={'action':'shape','expected_revision':0}).status_code==404
        assert url not in client.get('/openapi.json').json()['paths']


def test_retired_preferences_have_no_storage_or_rpc(sql):
    assert sql("select to_regclass('public.user_conversation_phase') is null;").stdout.strip()=='t'
    assert sql("select to_regclass('public.user_conversation_phase_archive') is null;").stdout.strip()=='t'
    for signature in ('read_user_conversation_phase(text)','change_user_conversation_phase(text,text,bigint)',
                      'conversation_phase_action(text)'):
        assert sql(f"select to_regprocedure('public.{signature}') is null;").stdout.strip()=='t'
    assert sql("select count(*) from pg_proc p join pg_namespace n on n.oid=p.pronamespace "
               "where n.nspname='public' and p.prokind='f' and p.prosrc like '%public.user_conversation_phase%';").stdout.strip()=='0'


def test_control_words_are_narration_and_reads_do_not_initialize_phase(sql):
    identity=rpc(sql,'resolve_lifetime_conversation','null')
    project=literal(identity['project_id'])
    accepted=rpc(sql,'accept_user_interview_turn',f"{project},'{uuid4()}','Please shape my story.'")
    context=rpc(sql,'read_user_interview_context',project)
    receipt=rpc(sql,'read_user_interview_turn',f"{project},'{accepted['client_turn_id']}'")
    pins=rpc(sql,'read_lifetime_pinned',f"'{identity['conversation_id']}'")
    for value in (context,receipt,pins):
        assert 'conversation_phase' not in value
    assert sql('select count(*) from public.user_lifetime_interview_strategy;').stdout.strip()=='0'
