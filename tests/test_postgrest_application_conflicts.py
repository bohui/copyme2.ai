"""Application conflicts must not enter PostgREST's serialization retry loop."""
import json

import httpx
import pytest

from fastapi import HTTPException
from apps.api.lifetime_memory_collection_jobs import _owner_rpc
from apps.api.lifetime_memory_read_api import read_mapped
from apps.api.private_draft_broker import receipt_scope_conflict

from test_lifetime_composer_capacity import (sql, event_database, private_database, attachment_database, database,  # noqa: F401
    resolve, rpc, literal, service, create_lane, OWNER)


def test_public_application_functions_never_raise_serialization_failure(sql):  # noqa: F811
    result = sql("select count(*) from pg_proc p join pg_namespace n on n.oid=p.pronamespace "
                 "where n.nspname='public' and p.prokind='f' and p.prosrc ~* 'errcode\\s*=\\s*''40001''';")
    assert result.stdout.strip() == '0'


def test_stale_lane_token_is_a_nonretryable_conflict_without_mutation(sql):  # noqa: F811
    identity = resolve(sql)
    project = identity['project_id']
    rpc(sql, 'accept_user_narrator_source', f"{literal(project)},'00000000-0000-4000-8000-000000000001','Our bicycle shed.'")
    lane = create_lane(sql, identity)
    claim = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    before = sql('select row_to_json(s) from public.user_narrator_source s;').stdout
    rejected = sql(f"\\set VERBOSITY verbose\nset role service_role; select public.commit_lifetime_memoir_lane_page("
                   f"'{lane}','00000000-0000-4000-8000-000000000099',0,'{{\"events\":[]}}','{claim['page_digest']}');", check=False)
    assert rejected.returncode != 0 and 'PT409' in rejected.stderr
    assert sql('select row_to_json(s) from public.user_narrator_source s;').stdout == before
    assert json.loads(sql(f"select row_to_json(l) from public.user_memoir_lane l where id='{lane}';").stdout)['token'] == claim['token']


def conflict(message='private changed content'):
    response = httpx.Response(409, json={'code':'PT409','message':message},
                              request=httpx.Request('POST','https://synthetic.invalid/rpc'))
    return httpx.HTTPStatusError('conflict', request=response.request, response=response)


def test_collection_conflict_retains_safe_reload_response():
    class Storage:
        def lifetime_rpc(self,*args,**kwargs):
            raise conflict()
    with pytest.raises(HTTPException) as failure:
        _owner_rpc(Storage(),'set_lifetime_collection')
    assert failure.value.status_code == 409 and 'private' not in failure.value.detail


def test_read_conflict_retains_safe_reload_response(monkeypatch):
    import apps.api.lifetime_memory_read_api as module
    def snapshot(*args,**kwargs):
        raise conflict()
    monkeypatch.setattr(module,'snapshot_lifetime_read',snapshot)
    class Storage:
        def lifetime_rpc(self,*args,**kwargs):
            pass
    with pytest.raises(HTTPException) as failure:
        read_mapped(Storage(),'project',lambda fence: None)
    assert failure.value.status_code == 409 and failure.value.headers['X-Error-Code']=='LIFETIME_READ_STALE'


def test_receipt_conflict_requires_the_exact_fence_message():
    assert receipt_scope_conflict(conflict('private draft receipt scope stale'))
    assert not receipt_scope_conflict(conflict())
