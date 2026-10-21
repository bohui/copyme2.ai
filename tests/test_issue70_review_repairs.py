"""Native counterexamples from independent d8fa review, reconstructed locally."""
import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

from test_two_lane_memory import (database,sql,event_database,private_database,attachment_database,
    enable_only_disposable_database_rollout,accept,lane,service,PLACE,TEXT)
from test_shared_memory_events_postgres import rpc,literal
from test_agent_commit_postgres import OWNER,as_user


class Broker:
    def __init__(self,sql):self.sql=sql
    async def rpc(self,name,**parameters):
        args=','.join(k+'=>'+literal(v) for k,v in parameters.items())
        return json.loads(self.sql("set role service_role;select coalesce(to_jsonb(public."+name+'('+args+")), 'null'::jsonb);").stdout.splitlines()[-1])


def test_every_source_remains_in_lossless_checkpoint_or_mandatory_tail(sql):
    from apps.api.lifetime_memory_context import ContextCheckpoint
    identity,accepted=accept(sql,text='First recollection.')
    for n in range(2,16):
        text='I remember the violet kite.' if n==10 else 'Short recollection '+str(n)
        rpc(sql,'accept_user_narrator_source',f"{literal(identity['project_id'])},'{uuid4()}',{literal(text)}")
    # Wake the same owner at the newest canonical source revision.
    accept(sql,text='First recollection.',project=identity['project_id'],turn=accepted['client_turn_id'])
    lane_id=lane(sql,identity);page=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
    service(sql,'advance_two_lane_checkpoint',f"'{lane_id}','{page['token']}',1")
    checkpoint=rpc(sql,'read_lifetime_checkpoint',f"'{identity['conversation_id']}',1,'gpt-5.6-luna-pooled','lifetime-v1'")
    assert checkpoint is not None
    parsed=ContextCheckpoint.model_validate(checkpoint)
    assert parsed.coverage_end==14
    assert 'violet kite' in json.dumps(checkpoint)
    assert len(checkpoint['evidence'])==14


def test_complete_page_reclaim_still_finishes_durable_maintenance(sql):
    from apps.api.lifetime_memory_composer import execute_lifetime_lane
    identity,accepted=accept(sql,text='Original '+('memory '*11000))
    rpc(sql,'accept_user_narrator_source',f"{literal(identity['project_id'])},'{uuid4()}','Latest accepted recollection'")
    accept(sql,text='Original '+('memory '*11000),project=identity['project_id'],turn=accepted['client_turn_id'])
    sql("update public.user_narrator_source set processing_status='succeeded';")
    lane_id=lane(sql,identity);page=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
    assert page['complete'] and page['source'] is None and 'two_lane' not in page
    result=asyncio.run(execute_lifetime_lane(page,SimpleNamespace(broker=Broker(sql))))
    assert result['status']=='pending'
    assert sql('select complete from public.user_lifetime_compaction;').stdout.strip()=='f'
    page=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
    result=asyncio.run(execute_lifetime_lane(page,SimpleNamespace(broker=Broker(sql))))
    assert result['status']=='pending' and not result['retrieval_complete']
    assert result['error']=='LIFETIME_PROVIDER_AUTHORITY_UNAVAILABLE'
    assert sql('select complete from public.user_lifetime_compaction;').stdout.strip()=='t'
    assert sql('select summary_required from public.user_lifetime_compaction;').stdout.strip()=='t'
    # Coverage is complete, but this worker has no configured summary provider.
    # The required semantic step stays pending; no raw original is discarded.
    assert sql('select count(*) from public.user_lifetime_checkpoint;').stdout.strip()=='0'


def test_flag_off_acceptance_still_reconciles_an_unsaved_accepted_turn(sql):
    identity,accepted=accept(sql)
    sql('update public.lifetime_two_lane_rollout set enabled=false;')
    rejected=rpc(sql,'accept_user_interview_turn',f"{literal(identity['project_id'])},'{uuid4()}','Another source'",check=False)
    assert rejected.returncode!=0
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='1'


def test_language_only_preference_keeps_accepted_places(sql):
    identity,accepted=accept(sql);lane_id=lane(sql,identity);page=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
    result={'events':[],'place_journeys':[{k:v for k,v in {**PLACE,'schema_version':1}.items() if v is not None}],'prepared_questions':[]}
    service(sql,'commit_lifetime_memoir_lane_page',f"'{lane_id}','{page['token']}',0,{literal(result)}")
    sql(as_user("update public.user_profile set profile=jsonb_set(profile,'{preferred_language}','\"zh-CN\"');"))
    assert rpc(sql,'read_lifetime_place_journeys',literal(identity['project_id']))[0]['place']=='Hobart'


def test_supported_background_alias_is_valid_for_bounded_checkpoint(sql):
    identity,_=accept(sql);lane_id=lane(sql,identity);page=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
    result=service(sql,'advance_two_lane_checkpoint',f"'{lane_id}','{page['token']}',1,'memoir-luna-low'")
    assert result['complete']
