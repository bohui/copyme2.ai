from fastapi.testclient import TestClient
from apps.api.main import create_app
from apps.api.store import MemoryStore


def test_project_retains_places_with_their_stages_and_picture_references():
    client = TestClient(create_app(MemoryStore()))
    headers = {"X-Account-Id": "place-owner"}
    project = client.post('/v1/projects', headers=headers, json={"mode": "self", "language": "en-AU"}).json()
    places = [{"place": "Chengde", "life_stage": "childhood", "hierarchy": ["Earth", "China", "Chengde"],
               "granularity": "city", "pictures": [{"asset_id": "picture-1", "title": "Old street"}]}]
    response = client.patch(f"/v1/projects/{project['id']}", headers=headers,
                            json={"profile": {"memory_places": places, "avatar_style": "female"}, "expected_revision": project['revision']})
    assert response.status_code == 200
    saved = client.get(f"/v1/projects/{project['id']}", headers=headers).json()['profile']
    assert saved['memory_places'] == places
    assert saved['avatar_style'] == 'female'


def test_place_photo_search_returns_attributed_real_image_urls(monkeypatch):
    import httpx
    payload = {"query": {"pages": {"1": {"pageid": 1, "title": "File:Chengde street.jpg", "imageinfo": [{
        "mime": "image/jpeg", "thumburl": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Chengde.jpg/640px-Chengde.jpg",
        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Chengde_street.jpg",
        "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"}, "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0/"},
                        "Artist": {"value": "Photographer"}, "DateTimeOriginal": {"value": "1985"}}}]}}}}
    def get(url, **kwargs):
        assert kwargs['params']['gsrsearch'].startswith('"Chengde"')
        return httpx.Response(200, json=payload, request=httpx.Request('GET', url))
    monkeypatch.setattr(httpx, 'get', get)
    client = TestClient(create_app(MemoryStore()))
    headers = {"X-Account-Id": "photo-owner"}
    project = client.post('/v1/projects', headers=headers, json={"mode": "self", "language": "en-AU"}).json()
    result = client.get(f"/v1/projects/{project['id']}/place-photos", headers=headers, params={"place": "Chengde"})
    assert result.status_code == 200
    picture = result.json()['items'][0]
    assert picture['image_url'].startswith('https://upload.wikimedia.org/')
    assert picture['attribution'] == 'Photographer'
    assert picture['date_expression'] == '1985'
    assert picture['license'] == 'CC BY-SA 4.0'


def test_project_rejects_malformed_place_history_without_losing_saved_profile():
    client = TestClient(create_app(MemoryStore()))
    headers = {"X-Account-Id": "place-owner"}
    project = client.post('/v1/projects', headers=headers, json={"mode": "self", "language": "en-AU"}).json()
    response = client.patch(f"/v1/projects/{project['id']}", headers=headers,
                            json={"profile": {"memory_places": "not a list"}})
    assert response.status_code == 422
    saved = client.get(f"/v1/projects/{project['id']}", headers=headers).json()
    assert saved['revision'] == project['revision']
