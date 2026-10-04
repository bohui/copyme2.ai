from copy import deepcopy
from io import BytesIO
from unittest.mock import Mock

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from apps.api import agent_routes
from apps.api.agent_storage import UserStorage
from apps.api.family_context import merge_family_context_document, validate_family_tree_context
from apps.api.family_photos import MAX_PHOTO_BYTES, portrait_bytes, save_person_photo, with_photo_urls
from apps.api.main import create_app
from apps.api.store import MemoryStore

OWNER = '11111111-1111-4111-8111-111111111111'
PATH = f'{OWNER}/attachment/portrait.jpg'


def image_bytes(size=(800, 400), mode='RGB', format='PNG', **options):
    output = BytesIO()
    Image.new(mode, size, (90, 140, 110, 80) if mode == 'RGBA' else (90, 140, 110)).save(output, format=format, **options)
    return output.getvalue()


def test_portrait_resizes_strips_metadata_and_honours_camera_orientation():
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = 'Private camera metadata'
    result = portrait_bytes(image_bytes(format='JPEG', exif=exif), 'image/jpeg')
    with Image.open(BytesIO(result)) as photo:
        assert photo.format == 'JPEG'
        assert photo.mode == 'RGB'
        assert photo.size == (256, 512)
        assert not photo.getexif()
    with Image.open(BytesIO(portrait_bytes(image_bytes(mode='RGBA'), 'image/png'))) as photo:
        assert photo.mode == 'RGB' and photo.size == (512, 256)


@pytest.mark.parametrize('content,kind,status', [
    (b'<svg></svg>', 'image/svg+xml', 415),
    (image_bytes(), 'image/jpeg', 415),
    (b'not an image', 'image/png', 422),
    (b'', 'image/png', 413),
    (b'x' * (MAX_PHOTO_BYTES + 1), 'image/png', 413),
])
def test_unusable_photos_are_rejected(content, kind, status):
    with pytest.raises(HTTPException) as error:
        portrait_bytes(content, kind)
    assert error.value.status_code == status


class PhotoStorage:
    def __init__(self):
        self.client = Mock()
        self.document = {'project_id': 'family', 'revision': 1,
                         'people': [{'id': 'mum', 'name': 'Mei', 'introduction': 'She grew roses.'},
                                    {'id': 'me', 'name': 'Avery'}],
                         'relationships': [{'id': 'parent'}], 'timeline': [{'id': 'school'}]}
        self.uploads = []
        self.deleted = []
        self.paid = True

    def story_entitlement(self):
        return {'status': 'paid' if self.paid else 'unpaid', 'plan_key': 'family_memoir_v1',
                'family_tree': True, 'timeline': True, 'stripe_price_id': 'price_family_test'}

    def family_context(self, project_id):
        return deepcopy(self.document) if project_id == 'family' else None

    def put_attachment(self, filename, content, kind):
        self.uploads.append((filename, content, kind))
        return f'{OWNER}/attachment/{filename}'

    def signed_attachment_url(self, path):
        return f'https://photos.test/{path}?token=private'

    def delete_attachment(self, path):
        self.deleted.append(path)

    def upsert_family_context(self, project_id, document, expected_revision):
        assert expected_revision == self.document['revision']
        self.document = {**deepcopy(document), 'revision': expected_revision + 1}
        return {'document': deepcopy(self.document), 'revision': self.document['revision']}


@pytest.fixture
def photo_api(monkeypatch):
    storage = PhotoStorage()
    monkeypatch.setenv('STRIPE_PRICE_FAMILY', 'price_family_test')
    monkeypatch.setattr(agent_routes, 'authenticated_storage', lambda authorization: storage)
    return TestClient(create_app(MemoryStore())), storage


def test_upload_reload_replace_remove_preserves_family_records(photo_api):
    client, storage = photo_api
    endpoint = '/v1/agent/family-context/family/people/mum/photo'
    response = client.put(endpoint, content=image_bytes(), headers={'Content-Type': 'image/png'})
    assert response.status_code == 200
    person = response.json()['person']
    path = person['photo_path']
    assert person['photo_url'].endswith('?token=private')
    assert person['introduction'] == 'She grew roses.'
    assert storage.uploads[0][2] == 'image/jpeg'
    with Image.open(BytesIO(storage.uploads[0][1])) as image:
        assert image.size == (512, 256)
    assert 'photo_url' not in storage.document['people'][0]
    read = client.get('/v1/agent/family-context?project_id=family').json()['family_context']
    assert read['people'][0]['photo_url'] == person['photo_url']
    replacement = client.put(endpoint, content=image_bytes(format='WEBP'), headers={'Content-Type': 'image/webp'})
    assert replacement.status_code == 200
    assert replacement.json()['person']['photo_path'] != path
    assert storage.deleted == [path]
    latest_path = storage.document['people'][0]['photo_path']
    removed = client.delete(endpoint)
    assert removed.status_code == 200
    assert 'photo_path' not in removed.json()['person'] and 'photo_url' not in removed.json()['person']
    assert storage.deleted == [path, latest_path]
    assert storage.document['relationships'] == [{'id': 'parent'}]
    assert storage.document['timeline'] == [{'id': 'school'}]
    assert storage.document['people'][1] == {'id': 'me', 'name': 'Avery'}
    assert storage.client.close.call_count == 4


def test_unknown_person_project_and_unpaid_account_cannot_upload(photo_api):
    client, storage = photo_api
    for endpoint in ['/v1/agent/family-context/family/people/missing/photo',
                     '/v1/agent/family-context/other-family/people/mum/photo']:
        assert client.put(endpoint, content=image_bytes(), headers={'Content-Type': 'image/png'}).status_code == 404
    storage.paid = False
    assert client.put('/v1/agent/family-context/family/people/mum/photo', content=image_bytes(), headers={'Content-Type': 'image/png'}).status_code == 403
    assert not storage.uploads and storage.document['revision'] == 1


def test_invalid_upload_does_not_replace_saved_photo(photo_api):
    client, storage = photo_api
    storage.document['people'][0]['photo_path'] = PATH
    response = client.put('/v1/agent/family-context/family/people/mum/photo', content=b'not an image', headers={'Content-Type': 'image/png'})
    assert response.status_code == 422
    assert storage.document['people'][0]['photo_path'] == PATH
    assert not storage.uploads and not storage.deleted


def test_photo_route_requires_authentication(monkeypatch):
    monkeypatch.setenv('SUPABASE_URL', 'https://example.supabase.co')
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY', 'public-key')
    response = TestClient(create_app(MemoryStore())).put('/v1/agent/family-context/family/people/mum/photo', content=b'x')
    assert response.status_code == 401


def test_retry_preserves_concurrent_introduction_and_timeline_updates():
    storage = PhotoStorage()
    upsert = storage.upsert_family_context
    attempts = []

    def concurrent_update(project_id, document, expected_revision):
        attempts.append(expected_revision)
        if len(attempts) == 1:
            storage.document['revision'] += 1
            storage.document['people'][0]['introduction'] = 'She taught me to garden.'
            storage.document['people'][0]['photo_path'] = PATH
            storage.document['timeline'].append({'id': 'visit'})
            response = httpx.Response(409, text='Family context revision conflict', request=httpx.Request('POST', 'https://storage.test'))
            raise httpx.HTTPStatusError('conflict', request=response.request, response=response)
        return upsert(project_id, document, expected_revision)

    storage.upsert_family_context = concurrent_update
    result = save_person_photo(storage, 'family', 'mum', PATH + '-new')
    assert attempts == [1, 2]
    assert result['person']['introduction'] == 'She taught me to garden.'
    assert storage.document['timeline'][-1] == {'id': 'visit'}
    assert storage.deleted == [PATH]


def test_unavailable_display_url_does_not_undo_a_successful_save():
    storage = PhotoStorage()
    storage.signed_attachment_url = Mock(side_effect=ValueError('missing portrait'))
    result = save_person_photo(storage, 'family', 'mum', PATH)
    assert result['person']['photo_path'] == PATH and 'photo_url' not in result['person']
    assert with_photo_urls(storage, storage.document)['people'][0]['photo_path'] == PATH
    assert 'photo_url' not in storage.document['people'][0]


def test_portrait_survives_a_grounded_family_skill_update():
    storage = PhotoStorage()
    storage.document['people'][0]['photo_path'] = PATH
    marker = validate_family_tree_context({'people': [{'id': 'mum-again', 'existing_id': 'mum',
                                                      'name': 'Mei', 'introduction': 'She taught me to garden.'}]})
    document, _ = merge_family_context_document(storage.document, marker, 'family')
    assert document['people'][0]['photo_path'] == PATH
    assert document['people'][0]['introduction'] == 'She taught me to garden.'


def test_signing_and_deleting_attachment_enforces_verified_ownership():
    calls = []

    def server(request):
        calls.append(request)
        if request.url.path == '/auth/v1/user':
            return httpx.Response(200, json={'id': OWNER})
        return httpx.Response(200, json={'signedURL': f'/object/sign/memory-spark/{PATH}?token=private'})

    storage = UserStorage('https://example.supabase.co', 'public-key', 'user-jwt', client=httpx.Client(transport=httpx.MockTransport(server)))
    assert storage.signed_attachment_url(PATH) == f'https://example.supabase.co/storage/v1/object/sign/memory-spark/{PATH}?token=private'
    assert calls[-1].headers['authorization'] == 'Bearer user-jwt'
    assert calls[-1].url.path == f'/storage/v1/object/sign/memory-spark/{PATH}'
    assert calls[-1].content == b'{"expiresIn":3600}'
    storage.delete_attachment(PATH)
    assert calls[-1].content == ('{"prefixes":["' + PATH + '"]}').encode()
    for path in [None, 1, PATH.replace(OWNER, 'another-owner'), f'{OWNER}/agent/private.txt',
                 f'{OWNER}/attachment/../secret', f'{OWNER}/attachment//portrait.jpg', f'/{PATH}']:
        with pytest.raises(ValueError):
            storage.signed_attachment_url(path)
        with pytest.raises(ValueError):
            storage.delete_attachment(path)
    assert len(calls) == 3
