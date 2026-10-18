"""Collector aliases retain canonical checkpoint evidence and access fences."""
from uuid import uuid4

from test_two_lane_memory import (
    database, sql, event_database, private_database, attachment_database,
    enable_only_disposable_database_rollout, accept, lane, service, TEXT,
)
from test_shared_memory_events_postgres import rpc, literal


def test_high_collector_checkpoint_keeps_originals_and_rejects_unreviewed_models(sql):
    model = 'gpt-5.6-luna-memoir-high'
    for role, expected in [('anon', 'f'), ('authenticated', 'f'), ('service_role', 't')]:
        assert sql(f"select has_function_privilege('{role}',"
            "'public.advance_two_lane_checkpoint(uuid,uuid,integer,text)','execute');").stdout.strip() == expected
    identity, accepted = accept(sql)
    rpc(sql, 'accept_user_narrator_source',
        f"{literal(identity['project_id'])},'{uuid4()}','Another remembered moment.'")
    lane_id = lane(sql, identity)
    page = service(sql, 'claim_memoir_lane', f"'{lane_id}',300")
    rejected = sql(f"set role service_role; select public.advance_two_lane_checkpoint("
        f"'{lane_id}','{page['token']}',1,'unreviewed-model');", check=False)
    assert rejected.returncode != 0 and 'bounded checkpoint configuration required' in rejected.stderr
    stale = sql(f"set role service_role; select public.advance_two_lane_checkpoint("
        f"'{lane_id}','{uuid4()}',1,'{model}');", check=False)
    assert stale.returncode != 0
    result = service(sql, 'advance_two_lane_checkpoint',
        f"'{lane_id}','{page['token']}',1,'{model}'")
    assert result['complete'] and result['coverage_end'] == 1
    checkpoint = rpc(sql, 'read_lifetime_checkpoint',
        f"'{identity['conversation_id']}',1,'{model}','lifetime-v1'")
    assert checkpoint['model'] == model
    assert sql(f"select lossless from public.user_lifetime_checkpoint where "
        f"conversation_id='{identity['conversation_id']}' and model='{model}';").stdout.strip() == 't'
    assert [(item['source_id'], item['original']) for item in checkpoint['evidence']] == [(accepted['source']['id'], TEXT)]
