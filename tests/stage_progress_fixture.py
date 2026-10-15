"""Synthetic canonical replies and exact persisted stage evidence; no providers."""
from uuid import uuid4

from test_agent_commit_postgres import OWNER, OLD, as_user
from test_interview_work_plan_postgres import plan
from test_shared_memory_events_postgres import rpc, literal


def save_stage_source(sql, project, text):
    turn = str(uuid4())
    accepted = rpc(sql, 'accept_user_interview_turn',
        f"{literal(project)},'{turn}',{literal(text)},'narrator_chat','en-AU'")
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    identity = rpc(sql, 'resolve_lifetime_conversation', literal(project))
    fence = rpc(sql, 'capture_lifetime_fence', f"'{identity['conversation_id']}','{OLD}'")
    saved = rpc(sql, 'commit_lifetime_turn',
        f"{literal(fence)}::jsonb,'{turn}',{literal(plan(name=None))}::jsonb,"
        "'[]','A synthetic reply.','[]','fixture-engine','lifetime-v1','fixture-model'")
    assert saved['memory'][0]['life_stage'] == 'unplaced'
    return accepted['source']


def link_stage(sql, project, source, stage, start=0, end=None, event=None):
    """Seed the extraction boundary with exact, versioned original spans."""
    event = event or str(uuid4())
    end = len(source['text']) if end is None else end
    ref = {'source_id': source['id'], 'version': source['version'],
           'quote': source['text'][start:end], 'char_start': start, 'char_end': end}
    data = {'title': 'Synthetic stage memory', 'stage_evidence': [ref],
            'temporal': {'expression': 'unknown', 'precision': 'unknown'}}
    sql(f"insert into public.user_memory_event(user_id,project_id,id,kind,life_stage,status,data,change_sequence) "
        f"values('{OWNER}',{literal(project)},'{event}','event','{stage}','active',{literal(data)}::jsonb,1) on conflict do nothing;")
    sql(f"insert into public.user_memory_event_source values('{OWNER}',{literal(project)},'{event}',"
        f"'{source['id']}',{source['version']},md5({literal(ref)}),{literal(ref)}::jsonb) on conflict do nothing;")
    return event
