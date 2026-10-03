from fastapi.testclient import TestClient
import pytest
from apps.api.main import create_app
from apps.api.store import MemoryStore


@pytest.fixture(autouse=True)
def no_live_browser_search(monkeypatch):
    # Catalogue unit tests never launch real browsers or query external sites.
    monkeypatch.setattr('apps.api.place_photo_browser.crawl_place_photos', lambda *args, **kwargs: [])
    monkeypatch.setattr('apps.api.place_photo_fingerprints.image_fingerprint', lambda url: {})


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
                "GPSLatitude": {"value": "40.98"}, "GPSLongitude": {"value": "117.94"},
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
                        params={"place": "Chengde", "period": "1980s", "latitude": 40.98, "longitude": 117.94}).json()
    assert result['status'] == 'READY'
    assert result['shortfall'] == 0
    assert len(result['items']) == 10
    assert all(p['attribution'] == 'Photographer' and p['date_expression'] == '1985' for p in result['items'])


def test_place_photo_search_excludes_wrong_decade_undated_and_banknotes(monkeypatch):
    from apps.api.place_photos import search_place_photos
    mock_catalogues(monkeypatch, [photo_page(1), photo_page(2, date="2018-02-12"),
        photo_page(3, date=""), photo_page(4, title="Chengde banknote.jpg"),
        photo_page(5, date="1969–1983"), photo_page(6, date="circa 1985")])
    assert [p['asset_id'] for p in search_place_photos("Chengde", "1980s")] == ['commons-1']
    assert search_place_photos("Chengde", "unknown childhood period") == []


def test_bare_year_search_covers_ten_calendar_years_either_side(monkeypatch):
    from apps.api.place_photos import _date_matches, _period_bounds, _search_queries
    assert _period_bounds("1980") == (1980, 1980)
    assert _period_bounds("1980年") == (1980, 1980)
    assert _date_matches("1980-01-01", "1980")
    assert _date_matches("1989-12-31", "1980")
    assert _date_matches("1970-01-01", "1980")
    assert _date_matches("1990-12-31", "1980")
    assert not _date_matches("1969-12-31", "1980")
    assert not _date_matches("1991-01-01", "1980")
    assert "1970" in _search_queries("Chengde", "1980")[0]
    assert "1990" in _search_queries("Chengde", "1980")[0]


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
                        params={"place": "Chengde", "period": "1980s", "latitude": 40.98, "longitude": 117.94}).json()
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


def test_flickr_search_uses_capture_dates_bilingual_queries_and_pagination(monkeypatch):
    import httpx
    from apps.api.place_photos import _flickr
    monkeypatch.setenv('FLICKR_API_KEY', 'test-key')
    calls = []
    def get(url, **kwargs):
        params = kwargs['params']
        if params['method'] == 'flickr.photos.licenses.getInfo':
            data = {'licenses': {'license': [
                {'id': '4', 'name': 'Attribution 2.0', 'url': 'https://creativecommons.org/licenses/by/2.0/'},
                {'id': '1', 'name': 'Noncommercial', 'url': 'https://creativecommons.org/licenses/by-nc/2.0/'},
            ]}}
        elif params['method'] == 'flickr.urls.lookupUser':
            data = {'user': {}}
        else:
            calls.append(params)
            assert params['min_taken_date'] == '1970-01-01 00:00:00'
            assert params['max_taken_date'] == '1999-12-31 23:59:59'
            assert 'geo' in params['extras']
            assert params['license'] == '4'
            assert 'min_upload_date' not in params
            photos = []
            if params['text'] == '承德':
                for index in range(10):
                    photos.append({'id': str(index + 1), 'owner': '123@N01', 'ownername': 'Photographer',
                        'title': '承德街景', 'datetaken': '1983-10-01 00:00:00', 'license': '4',
                        'url_z': f'https://live.staticflickr.com/1/{index}.jpg'})
            data = {'photos': {'pages': 2, 'photo': photos}}
        return httpx.Response(200, json={'stat': 'ok', **data}, request=httpx.Request('GET', url))
    monkeypatch.setattr(httpx, 'get', get)
    photos = _flickr('Chengde', '1980s')
    assert len(photos) == 10
    assert [(c['text'], c['page']) for c in calls] == [('Chengde', 1), ('Chengde', 2), ('承德', 1)]
    assert photos[0]['license'] == 'Attribution 2.0'


def test_flickr_rejects_wrong_year_unknown_date_and_unlicensed_photos(monkeypatch):
    import httpx
    from apps.api.place_photos import _flickr
    monkeypatch.setenv('FLICKR_API_KEY', 'test-key')
    def get(url, **kwargs):
        params = kwargs['params']
        if params['method'] == 'flickr.photos.licenses.getInfo':
            data = {'licenses': {'license': [{'id': '4', 'name': 'Attribution', 'url': 'https://creativecommons.org/licenses/by/2.0/'}]}}
        else:
            assert params['max_taken_date'] == '1990-12-31 23:59:59'
            base = {'id': '1', 'owner': '123@N01', 'title': 'Chengde street', 'datetaken': '1980-10-01',
                    'license': '4', 'url_z': 'https://live.staticflickr.com/1/1.jpg'}
            data = {'photos': {'pages': 1, 'photo': [
                {**base, 'datetaken': '1991-10-01'}, {**base, 'datetakenunknown': '1'},
                {**base, 'license': '0'}, {**base, 'title': 'Chengdu street'},
                {**base, 'url_z': 'https://untrusted.example/photo.jpg'}, base]}}
        return httpx.Response(200, json={'stat': 'ok', **data}, request=httpx.Request('GET', url))
    monkeypatch.setattr(httpx, 'get', get)
    photos = _flickr('Chengde', '1980-1980')
    assert len(photos) == 2  # same item encountered in both language queries
    assert len({p['asset_id'] for p in photos}) == 1


def test_flickr_without_key_does_not_call_network(monkeypatch):
    from apps.api.place_photos import _flickr
    monkeypatch.delenv('FLICKR_API_KEY', raising=False)
    monkeypatch.setattr('httpx.get', lambda *a, **k: (_ for _ in ()).throw(AssertionError('unexpected call')))
    assert _flickr('Chengde', '1980s') == []


def test_flickr_album_expansion_keeps_generic_titles_but_checks_each_date(monkeypatch):
    import httpx
    from apps.api.place_photos import _flickr
    monkeypatch.setenv('FLICKR_API_KEY', 'test-key')
    def get(url, **kwargs):
        params = kwargs['params']
        method = params['method']
        if method == 'flickr.photos.licenses.getInfo':
            data = {'licenses': {'license': [{'id': '4', 'name': 'Attribution', 'url': 'https://creativecommons.org/licenses/by/2.0/'}]}}
        elif method == 'flickr.urls.lookupUser':
            data = {'user': {'id': '123@N01'}}
        elif method == 'flickr.photosets.getPhotos':
            assert params['photoset_id'] == '72157614775600805'
            assert 'text' not in params and 'min_taken_date' not in params
            base = {'title': 'Willow trees', 'datetaken': '1983-10-01', 'license': '4',
                    'url_z': 'https://live.staticflickr.com/1/1.jpg'}
            data = {'photoset': {'pages': 1, 'photo': [{'id': '1', **base},
                {**base, 'id': '2', 'datetaken': '2000-01-01'}]}}
        else:
            data = {'photos': {'pages': 1, 'photo': []}}
        return httpx.Response(200, json={'stat': 'ok', **data}, request=httpx.Request('GET', url))
    monkeypatch.setattr(httpx, 'get', get)
    photos = _flickr('Chengde', '1980s')
    assert len(photos) == 1
    assert photos[0]['title'] == 'Willow trees'
    assert photos[0]['source_url'] == 'https://www.flickr.com/photos/123@N01/1/'


def google_result(index, *, place='Chengde', date='1983', title=None,
                  license_url='https://creativecommons.org/licenses/by/4.0/'):
    result = {
        'title': title or f'{place} street photograph {date} #{index}',
        'link': f'https://images.example/{index}.jpg',
        'snippet': f'{place} historical street photograph, captured {date}.',
        'displayLink': 'archive.example',
        'image': {'contextLink': f'https://archive.example/photos/{index}'},
        'pagemap': {'metatags': [{'dateCreated': date, 'license': license_url, 'author': 'Archive photographer'}],
                    'imageobject': [{'latitude': 40.98, 'longitude': 117.94}]},
    }
    return result


def test_google_cse_filters_location_and_created_range_across_pages(monkeypatch):
    import httpx
    from apps.api.place_photos import _google_cse
    monkeypatch.setenv('GOOGLE_CSE_API_KEY', 'test-google-key')
    monkeypatch.setenv('GOOGLE_CSE_ID', 'b2de41f6592f74c3e')
    calls = []

    def get(url, **kwargs):
        if 'customsearch.googleapis.com' not in url:
            return httpx.Response(200, json={'results': []}, request=httpx.Request('GET', url))
        params = kwargs['params']
        calls.append(params.copy())
        assert params['cx'] == 'b2de41f6592f74c3e'
        assert params['key'] == 'test-google-key'
        assert params['searchType'] == 'image'
        assert params['num'] == 10
        assert params['rights'] == 'cc_publicdomain|cc_attribute|cc_sharealike'
        assert 'sort' not in params  # Capture dates, not webpage publication dates.
        assert 'Chengde' in params['q'] and '承德' in params['q']
        assert '1980' in params['q'] and '1989' in params['q']
        if params['start'] == 1:
            items = [google_result(1)]
            items.extend([
                google_result(2, date='1969'),
                google_result(3, place='Chengdu'),
                google_result(4, license_url='https://creativecommons.org/licenses/by-nc/2.0/'),
                google_result(5, date='2000'),
                google_result(6, title='Banknote', date='1983'),
            ])
            return httpx.Response(200, json={
                'items': items,
                'queries': {'nextPage': [{'startIndex': 11}]},
            }, request=httpx.Request('GET', url))
        assert params['start'] == 11
        return httpx.Response(200, json={'items': [google_result(i) for i in range(10, 19)]},
                              request=httpx.Request('GET', url))

    monkeypatch.setattr(httpx, 'get', get)
    photos = _google_cse('Chengde', '1980s')
    assert len(photos) == 10
    assert len({photo['asset_id'] for photo in photos}) == 10
    assert [call['start'] for call in calls] == [1, 11]
    assert all(photo['allowed_actions']['embed'] for photo in photos)
    assert all(photo['license'] == 'CC BY' for photo in photos)
    assert all(photo['date_expression'] == '1983' for photo in photos)


def test_google_cse_requires_server_credentials(monkeypatch):
    from apps.api.place_photos import _google_cse
    monkeypatch.setenv('GOOGLE_CSE_ID', 'b2de41f6592f74c3e')
    monkeypatch.setattr('httpx.get', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('unexpected call')))
    monkeypatch.setenv('GOOGLE_CSE_API_KEY', '<null>')
    assert _google_cse('Chengde', '1980s') == []
    monkeypatch.delenv('GOOGLE_CSE_API_KEY', raising=False)
    assert _google_cse('Chengde', '1980s') == []


def test_google_cse_pagination_makes_place_endpoint_ready(monkeypatch):
    import httpx
    monkeypatch.setenv('GOOGLE_CSE_API_KEY', 'test-google-key')
    monkeypatch.setenv('GOOGLE_CSE_ID', 'b2de41f6592f74c3e')

    def get(url, **kwargs):
        if 'customsearch.googleapis.com' not in url:
            if 'commons' in url:
                return httpx.Response(200, json={}, request=httpx.Request('GET', url))
            return httpx.Response(200, json={'results': []}, request=httpx.Request('GET', url))
        params = kwargs['params']
        if params['start'] == 1:
            data = {'items': [google_result(1)], 'queries': {'nextPage': [{'startIndex': 11}]}}
        else:
            data = {'items': [google_result(index) for index in range(10, 19)]}
        return httpx.Response(200, json=data, request=httpx.Request('GET', url))

    monkeypatch.setattr(httpx, 'get', get)
    client = TestClient(create_app(MemoryStore()))
    headers = {'X-Account-Id': 'google-photo-owner'}
    project = client.post('/v1/projects', headers=headers, json={'mode': 'self', 'language': 'en-AU'}).json()
    result = client.get(f"/v1/projects/{project['id']}/place-photos", headers=headers,
                        params={'place': 'Chengde', 'period': '1980s', 'latitude': 40.98, 'longitude': 117.94}).json()
    assert result['status'] == 'READY'
    assert result['target_count'] == 10 and result['shortfall'] == 0
    assert len(result['items']) == 10
    assert all(item['asset_id'].startswith('google-') for item in result['items'])
