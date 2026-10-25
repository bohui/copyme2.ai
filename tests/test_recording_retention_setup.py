from pathlib import Path

import httpx
import pytest

from scripts.setup_recording_retention import BUCKET, recording_schema, ensure_private_bucket, BASELINE


def test_targeted_setup_contains_only_consent_and_recording_ddl():
    ddl=recording_schema(BASELINE.read_text())
    assert 'CREATE TABLE IF NOT EXISTS public.user_recording_consent' in ddl
    assert 'CREATE OR REPLACE FUNCTION public.original_recording_authorized' in ddl
    assert 'CREATE OR REPLACE FUNCTION public.recording_server_operation' in ddl
    assert 'DROP ' not in ddl and 'TRUNCATE ' not in ddl
    assert 'user_profile' not in ddl and 'storage.objects' not in ddl


def test_setup_creates_missing_bucket_privately_and_preserves_existing_bucket():
    calls=[]
    def serve(request):
        calls.append((request.method,request.url.path))
        if len(calls)==1:return httpx.Response(404)
        return httpx.Response(200,json={'id':BUCKET,'public':False})
    with httpx.Client(base_url='https://fixture.test/',transport=httpx.MockTransport(serve)) as client:
        ensure_private_bucket(client)
        assert [method for method,_ in calls]==['GET','POST','GET']
        calls.clear()
    with httpx.Client(base_url='https://fixture.test/',transport=httpx.MockTransport(lambda _:httpx.Response(200,json={'id':BUCKET,'public':False}))) as client:
        ensure_private_bucket(client)
    with httpx.Client(base_url='https://fixture.test/',transport=httpx.MockTransport(lambda _:httpx.Response(200,json={'id':BUCKET,'public':True}))) as client:
        with pytest.raises(ValueError,match='private'):ensure_private_bucket(client)
