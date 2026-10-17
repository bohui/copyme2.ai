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


def test_retired_preferences_are_archived_and_inaccessible(sql):
    assert sql("select to_regclass('public.user_conversation_phase') is null;").stdout.strip()=='t'
    assert sql("select to_regclass('public.user_conversation_phase_archive') is not null;").stdout.strip()=='t'
    assert sql("select has_table_privilege('authenticated','public.user_conversation_phase_archive','select');").stdout.strip()=='f'
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
    assert sql('select count(*) from public.user_conversation_phase_archive;').stdout.strip()=='0'
    assert sql('select count(*) from public.user_lifetime_interview_strategy;').stdout.strip()=='0'


def test_upgrade_preserves_ai_plan_checkpoint_and_original_evidence():
    from test_agent_commit_postgres import database as make_database, OLD, as_user
    from test_lifetime_memory_checkpoints import create, read
    from test_interview_strategy_postgres import commit
    from test_two_lane_memory import accept, lane, service
    from apps.api.lifetime_memory_contracts import EvidenceEnvelope
    from apps.api.lifetime_memory_context import ContextCheckpoint
    from apps.api.interview_strategy import InterviewStrategyPlan

    cluster=make_database.__wrapped__()
    try:
        sql=private_database.__wrapped__(attachment_database.__wrapped__(next(cluster)))
        migrations=Path(__file__).resolve().parents[1]/'supabase/migrations'
        retirement=migrations/'202610170003_retire_conversation_phase.sql'
        for path in sorted(migrations.glob('*.sql')):
            if '202610040001_shared_memory_events.sql'<=path.name<retirement.name:
                sql(path.read_text())
        sql('update public.lifetime_two_lane_rollout set enabled=true,strategy_enabled=true,strategy_shadow=false;')
        identity=rpc(sql,'resolve_lifetime_conversation','null')
        project=literal(identity['project_id'])
        phase=rpc(sql,'read_user_conversation_phase',project)
        phase=rpc(sql,'change_user_conversation_phase',f"{project},'comfort',{phase['revision']}")
        identity,accepted=accept(sql,project=identity['project_id'])
        source=accepted['source']
        sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
        fence=rpc(sql,'capture_lifetime_fence',f"'{identity['conversation_id']}','{OLD}'")
        evidence=EvidenceEnvelope(source_id=source['id'],version=1,char_start=0,char_end=len(source['text']),
            original=source['text'],language='en-AU',assertion='asserted',allowed_use=['conversation'],policy_epoch=1).model_dump(mode='json')
        checkpoint=create(sql,fence,evidence)
        rpc(sql,'publish_lifetime_checkpoint',f"'{checkpoint}',{literal(fence)}::jsonb")
        sql('delete from public.user_agent_turn_lease;')
        lane_id=lane(sql,identity)
        page=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
        commit(sql,lane_id,page)
        before=rpc(sql,'read_lifetime_strategy_context',f"'{identity['conversation_id']}'")['plan']
        assert before['checkpoint_id']==checkpoint and before['phase_revision']==phase['revision']

        sql(retirement.read_text())

        restored=rpc(sql,'read_lifetime_strategy_context',f"'{identity['conversation_id']}'")['plan']
        assert InterviewStrategyPlan.model_validate(restored).strategy=='shape'
        assert restored==before
        restored_checkpoint=read(sql,identity)
        assert ContextCheckpoint.model_validate(restored_checkpoint).checkpoint_id.hex==checkpoint.replace('-','')
        assert restored_checkpoint['evidence']==[evidence]
        assert 'conversation_phase' not in restored_checkpoint['pinned']
        assert sql('select text from public.user_narrator_source;').stdout.strip()==source['text']
        archived=json.loads(sql('select to_jsonb(p)-\'user_id\'-\'project_id\' from public.user_conversation_phase_archive p;').stdout)
        assert archived=={k:v for k,v in phase.items() if k!='schema_version'}
        assert rpc(sql,'capture_lifetime_read_fence',project)['phase_revision']==0
    finally:
        cluster.close()
