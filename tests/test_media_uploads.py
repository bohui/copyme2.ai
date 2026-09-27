import base64

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app


@pytest.mark.parametrize('mime,filename,raw', [
    ('video/mp4', 'memory.mp4', b'\x00\x00\x00\x18ftypmp42' + b'\x00' * 12),
    ('video/webm', 'memory.webm', b'\x1a\x45\xdf\xa3' + b'\x00' * 12),
    ('video/quicktime', 'memory.mov', b'\x00\x00\x00\x18ftypqt  ' + b'\x00' * 12),
])
def test_video_upload_roundtrip_and_validation(mime, filename, raw):
    client = TestClient(create_app())
    headers = {'X-Account-Id': 'media-owner'}
    project = client.post('/v1/projects', json={'mode': 'self', 'language': 'en-AU'}, headers=headers).json()
    body = {'project_id': project['id'], 'kind': 'video', 'filename': filename, 'mime_type': mime, 'expected_size': len(raw)}
    assert client.post('/v1/uploads', json=body, headers=headers).status_code == 400
    body['rights_confirmed'] = True
    assert client.post('/v1/uploads', json={**body, 'expected_size': 100 * 1024 * 1024 + 1}, headers=headers).status_code == 413
    assert client.post('/v1/uploads', json={**body, 'mime_type': 'image/png'}, headers=headers).status_code == 415
    created = client.post('/v1/uploads', json=body, headers=headers)
    assert created.status_code == 201
    upload_id = created.json()['id']
    for sequence, part in enumerate([raw[:8], raw[8:]]):
        response = client.post(f'/v1/uploads/{upload_id}/parts', json={'sequence': sequence, 'content': base64.b64encode(part).decode()}, headers=headers)
        assert response.status_code == 200
    response = client.post(f'/v1/uploads/{upload_id}/finalize', json={}, headers=headers)
    assert response.status_code == 200
    asset = response.json()
    assert asset['kind'] == 'video'
    assert asset['size'] == len(raw)
    assert asset['visibility'] == 'private'
    assert asset['original_retained'] is True
    assert client.get(f'/v1/uploads/{upload_id}', headers=headers).json()['state'] == 'READY'
