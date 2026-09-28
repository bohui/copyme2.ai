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


def photo_page(pageid, *, date="1985", title=None):
    return {
        "pageid": pageid, "title": "File:" + (title or f"Chengde street {pageid}.jpg"),
        "imageinfo": [{"mime": "image/jpeg",
            "thumburl": f"https://upload.wikimedia.org/wikipedia/commons/{pageid}.jpg",
            "descriptionurl": f"https://commons.wikimedia.org/wiki/File:{pageid}.jpg",
            "sha1": str(pageid),
            "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"},
                "Artist": {"value": "Photographer"}, "DateTimeOriginal": {"value": date}}}],
    }


def mock_catalogues(monkeypatch, pages, loc=None):
    import httpx
    def get(url, **kwargs):
        payload = {"query": {"pages": {str(p["pageid"]): p for p in pages}}} if "commons" in url else {"results": loc or []}
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))
    monkeypatch.setattr(httpx, "get", get)


def test_place_photo_search_returns_ten_attributed_photos(monkeypatch):
    mock_catalogues(monkeypatch, [photo_page(i) for i in range(15)])
    client = TestClient(create_app(MemoryStore()))
    headers = {"X-Account-Id": "photo-owner"}
    project = client.post('/v1/projects', headers=headers, json={"mode": "self", "language": "en-AU"}).json()
    result = client.get(f"/v1/projects/{project['id']}/place-photos", headers=headers,
                        params={"place": "Chengde", "period": "1980s"}).json()
    assert result['status'] == 'READY'
    assert result['shortfall'] == 0
    assert len(result['items']) == 10
    assert all(p['attribution'] == 'Photographer' and p['date_expression'] == '1985' for p in result['items'])


def test_place_photo_search_excludes_wrong_decade_undated_and_banknotes(monkeypatch):
    from apps.api.place_photos import search_place_photos
    mock_catalogues(monkeypatch, [photo_page(1), photo_page(2, date="2018-02-12"),
        photo_page(3, date=""), photo_page(4, title="Chengde banknote.jpg"),
        photo_page(5, date="1979–1983"), photo_page(6, date="circa 1985")])
    assert [p['asset_id'] for p in search_place_photos("Chengde", "1980s")] == ['commons-1']
    assert search_place_photos("Chengde", "unknown childhood period") == []


def test_place_photo_search_expands_queries_and_deduplicates(monkeypatch):
    import httpx
    from apps.api.place_photos import search_place_photos
    queries = []
    def get(url, **kwargs):
        if 'commons' not in url:
            return httpx.Response(200, json={"results": []}, request=httpx.Request('GET', url))
        queries.append(kwargs['params']['gsrsearch'])
        pages = [photo_page(1)] if len(queries) == 1 else [photo_page(i) for i in range(1, 11)]
        return httpx.Response(200, json={"query": {"pages": {str(p['pageid']): p for p in pages}}}, request=httpx.Request('GET', url))
    monkeypatch.setattr(httpx, 'get', get)
    photos = search_place_photos('Chengde', '1980s')
    assert len(photos) == len({p['asset_id'] for p in photos}) == 10
    assert len(queries) == 2
    assert '1980' in queries[0] and '1989' in queries[0]


def loc_photo(index):
    return {"id": f"https://www.loc.gov/item/{index}/", "title": f"Chengde street {index}",
        "date": "1984", "image_url": [f"https://cdn.loc.gov/{index}.jpg"],
        "item": {"medium": ["1 photographic negative"], "rights": ["No known restrictions on publication."]}}


def test_second_catalogue_fills_shortfall_and_preserves_rights(monkeypatch):
    from apps.api.place_photos import search_place_photos
    records = [loc_photo(i) for i in range(10)]
    records[0]['item']['rights'] = []
    records[1]['date'] = '2018'
    records[2]['item']['medium'] = ['1 drawing']
    mock_catalogues(monkeypatch, [photo_page(i) for i in range(3)], records)
    photos = search_place_photos('Chengde', '1980年代')
    assert len(photos) == 10
    assert len([p for p in photos if p['asset_id'].startswith('loc-')]) == 7
    assert photos[-1]['license'] == 'No known restrictions on publication.'


def test_catalogue_failure_does_not_hide_other_results(monkeypatch):
    import httpx
    from apps.api.place_photos import search_place_photos
    def get(url, **kwargs):
        if 'commons' in url:
            raise httpx.ConnectError('unavailable')
        return httpx.Response(200, json={"results": [loc_photo(1)]}, request=httpx.Request('GET', url))
    monkeypatch.setattr(httpx, 'get', get)
    assert search_place_photos('Chengde', '1980s')[0]['asset_id'] == 'loc-1'


def test_api_reports_shortfall_instead_of_ready(monkeypatch):
    mock_catalogues(monkeypatch, [photo_page(1)])
    client = TestClient(create_app(MemoryStore()))
    headers = {"X-Account-Id": "photo-owner"}
    project = client.post('/v1/projects', headers=headers, json={"mode": "self", "language": "en-AU"}).json()
    result = client.get(f"/v1/projects/{project['id']}/place-photos", headers=headers,
                        params={"place": "Chengde", "period": "1980s"}).json()
    assert result['status'] == 'PARTIAL'
    assert result['target_count'] == 10 and result['shortfall'] == 9


def test_project_rejects_malformed_place_history_without_losing_saved_profile():
    client = TestClient(create_app(MemoryStore()))
    headers = {"X-Account-Id": "place-owner"}
    project = client.post('/v1/projects', headers=headers, json={"mode": "self", "language": "en-AU"}).json()
    response = client.patch(f"/v1/projects/{project['id']}", headers=headers,
                            json={"profile": {"memory_places": "not a list"}})
    assert response.status_code == 422
    saved = client.get(f"/v1/projects/{project['id']}", headers=headers).json()
    assert saved['revision'] == project['revision']
