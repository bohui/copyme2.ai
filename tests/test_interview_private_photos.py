"""Private photo bytes use owner-authenticated access, never bearer display URLs."""
from io import BytesIO
from uuid import UUID

import httpx
import pytest
from PIL import Image

from apps.api.agent_storage import UserStorage

OWNER = '11111111-1111-4111-8111-111111111111'
PHOTO = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'


def test_photo_cue_reselection_has_a_new_revision_and_favourite_does_not_consume_it():
    from apps.api.photo_memories import PhotoMemoryInput, update_photo_memory
    payload = PhotoMemoryInput(action='select', photo={'image_url':'https://example.org/image.jpg'})
    first, state = update_photo_memory({}, 'project', payload)
    revision = state['selection_revision']
    UUID(revision)
    second, selected = update_photo_memory(first, 'project', payload)
    assert selected['selection_revision'] != revision
    _, favorite = update_photo_memory(second, 'project', PhotoMemoryInput(action='favorite', photo=payload.photo))
    assert favorite['selection_revision'] == selected['selection_revision']


def test_actual_private_image_format_is_verified_without_inventing_description():
    from apps.api.interview_photos import validate_photo_bytes
    output = BytesIO()
    Image.new('RGB', (3, 4), 'red').save(output, 'PNG')
    info = validate_photo_bytes(output.getvalue(), 'image/png')
    assert info == {'content_type':'image/png', 'byte_size':len(output.getvalue()), 'width':3, 'height':4}
    with pytest.raises(Exception):
        validate_photo_bytes(output.getvalue(), 'image/jpeg')
    with pytest.raises(Exception):
        validate_photo_bytes(b'<svg><script>bad()</script></svg>', 'image/svg+xml')


def test_private_upload_and_read_use_verified_metadata_path_and_never_sign():
    from apps.api.interview_photos import PRIVATE_PHOTO_BUCKET
    requests = []
    path = f'{OWNER}/private-photo/{PHOTO}.png'
    metadata = {'id':PHOTO, 'object_path':path, 'content_type':'image/png', 'byte_size':3, 'status':'ready'}
    def handle(request):
        requests.append(request)
        if request.url.path == '/auth/v1/user':
            return httpx.Response(200, json={'id':OWNER})
        if request.url.path.endswith('/begin_user_interview_photo'):
            return httpx.Response(200, json={**metadata, 'status':'pending'})
        if request.url.path.endswith(('/finish_user_interview_photo','read_user_interview_photo')):
            return httpx.Response(200, json=metadata)
        if request.method == 'GET':
            return httpx.Response(200, content=b'png')
        return httpx.Response(200, json={})
    storage = UserStorage('https://synthetic.invalid','key','token',client=httpx.Client(transport=httpx.MockTransport(handle)))
    assert storage.put_interview_photo('project', b'png', {'content_type':'image/png','byte_size':3,'width':1,'height':1})['id'] == PHOTO
    assert storage.get_interview_photo('project', PHOTO) == (b'png', metadata)
    assert all('/sign/' not in str(r.url) for r in requests)
    assert any(r.url.path == f'/storage/v1/object/authenticated/{PRIVATE_PHOTO_BUCKET}/{path}' for r in requests)
    assert all(r.headers['authorization'] == 'Bearer token' for r in requests)


def test_private_content_missing_or_foreign_metadata_never_fetches_bytes():
    calls = []
    def handle(request):
        calls.append(request)
        if request.url.path == '/auth/v1/user': return httpx.Response(200,json={'id':OWNER})
        return httpx.Response(200,json=None)
    storage=UserStorage('https://synthetic.invalid','key','token',client=httpx.Client(transport=httpx.MockTransport(handle)))
    with pytest.raises(ValueError): storage.get_interview_photo('project', PHOTO)
    assert not any('/storage/' in str(r.url) for r in calls)


def test_postgres_transport_preserves_narrative_blank_lines_and_backslashes():
    from interview_postgres_single import frame_sql
    assert frame_sql("select 'first\n\nlast';\n\nselect 2;") == "select E'first\\n\\nlast';\nselect 2;"
    assert frame_sql("select 'a\\b\n\nc''d';") == "select E'a\\\\b\\n\\nc''d';"


def test_unlink_route_authenticates_and_uses_only_owner_scoped_rpc(monkeypatch):
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from apps.api import interview_photos
    requests=[]
    def authenticated_storage(authorization):
        if authorization not in ('Bearer owner', 'Bearer other'):
            raise HTTPException(401, 'Sign in required')
        def handle(request):
            requests.append(request)
            if request.url.path=='/auth/v1/user':
                return httpx.Response(200,json={'id':OWNER if authorization=='Bearer owner' else '22222222-2222-4222-8222-222222222222'})
            assert request.url.path=='/rest/v1/rpc/unlink_user_interview_photo'
            return httpx.Response(200,json={'unlinked':True}) if authorization=='Bearer owner' else httpx.Response(403,json={'message':'photo association unavailable'})
        return UserStorage('https://synthetic.invalid','key',authorization[7:],client=httpx.Client(transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(interview_photos,'authenticated_storage',authenticated_storage)
    app=FastAPI();app.include_router(interview_photos.router)
    client=TestClient(app)
    path=f'/v1/agent/projects/project/photo-associations/{PHOTO}'
    assert client.delete(path).status_code==401
    assert client.delete(path,headers={'Authorization':'Bearer other'}).status_code==404
    assert client.delete(path,headers={'Authorization':'Bearer owner'}).status_code==204
    import json
    calls=[r for r in requests if '/rpc/' in r.url.path]
    assert len(calls)==2 and all(json.loads(r.content)=={'p_project_id':'project','p_association_id':PHOTO} for r in calls)
    assert all('/storage/' not in r.url.path for r in requests)
