import httpx
from fastapi.testclient import TestClient
from apps.api.main import create_app
from apps.api.store import MemoryStore
from apps.api import place_geocoding as geo

CITY = {"place": "承德", "hierarchy": ["Earth", "中国", "河北", "承德"], "granularity": "city", "latitude": 40.97, "longitude": 117.93}
SUBURB = {"place": "大石庙镇", "hierarchy": [*CITY['hierarchy'], "大石庙镇"], "granularity": "suburb"}


def test_search_place_uses_google_geocoding(monkeypatch):
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, json={
            "status": "OK",
            "results": [{"geometry": {"location": {"lat": 40.921285, "lng": 117.961817}}}],
        }, request=httpx.Request("GET", url))

    monkeypatch.setenv("GOOGLE_MAPS_GEOCODING_API_KEY", "server-key")
    monkeypatch.setattr(httpx, "get", get)
    geo.search_place.cache_clear()

    assert geo.search_place("大石庙镇, 承德, 河北, 中国") == {
        "latitude": 40.921285,
        "longitude": 117.961817,
        "attribution": "Google Maps",
    }
    assert calls == [("https://maps.googleapis.com/maps/api/geocode/json", {
        "params": {"address": "大石庙镇, 承德, 河北, 中国", "key": "server-key"},
        "headers": {"Accept": "application/json"},
        "timeout": 5,
    })]


def test_searches_detailed_place_before_nearest_saved_parent(monkeypatch):
    queries = []
    monkeypatch.setattr(geo, 'search_place', lambda query: queries.append(query))
    result = geo.resolve_place_map(SUBURB, [CITY])
    assert queries == ['大石庙镇, 承德, 河北, 中国']
    assert result['target']['place'] == '承德'
    assert result['fallback'] is True
    assert SUBURB['place'] == '大石庙镇'


def test_searches_parents_in_order_without_saved_coordinates(monkeypatch):
    queries = []
    def search(query):
        queries.append(query)
        return {'latitude': 40.97, 'longitude': 117.93} if query.startswith('承德,') else None
    monkeypatch.setattr(geo, 'search_place', search)
    result = geo.resolve_place_map(SUBURB, [])
    assert queries == ['大石庙镇, 承德, 河北, 中国', '承德, 河北, 中国']
    assert result['target']['place'] == '承德'


def test_detailed_search_success_and_owner_boundary(monkeypatch):
    monkeypatch.setattr(geo, 'search_place', lambda query: {'latitude': 40.921285, 'longitude':117.961817})
    client = TestClient(create_app(MemoryStore()))
    headers = {'X-Account-Id':'owner'}
    project = client.post('/v1/projects', headers=headers, json={'mode':'self'}).json()
    url = f"/v1/projects/{project['id']}/place-map"
    response = client.post(url, headers=headers, json=SUBURB)
    assert response.status_code == 200
    assert response.json()['target']['place'] == '大石庙镇'
    assert response.json()['fallback'] is False
    assert client.post(url, headers={'X-Account-Id':'other'}, json=SUBURB).status_code in (403,404)
    assert client.post(url, headers=headers, json={'place':'x'}).status_code == 422


def test_provider_outage_still_uses_saved_parent(monkeypatch):
    def fail(query):
        raise httpx.ConnectError('offline')
    monkeypatch.setattr(geo, 'search_place', fail)
    assert geo.resolve_place_map(SUBURB, [CITY])['target']['place'] == '承德'
    assert geo.resolve_place_map(SUBURB, [])['status'] == 'UNAVAILABLE'


def test_grouping_metadata_shares_map_cache_and_preserves_partial_match(monkeypatch):
    calls = []
    def get(url, **kwargs):
        calls.append(kwargs['params']['address'])
        return httpx.Response(200, json={'status': 'OK', 'results': [{
            'geometry': {'location': {'lat': 40.92, 'lng': 117.96}}, 'partial_match': True,
            'address_components': [
                {'long_name': '大石庙镇', 'types': ['locality']},
                {'long_name': '承德市', 'types': ['administrative_area_level_2']},
                {'long_name': '河北省', 'types': ['administrative_area_level_1']},
                {'long_name': '中国', 'types': ['country']}]}]}, request=httpx.Request('GET', url))
    monkeypatch.setenv('GOOGLE_MAPS_GEOCODING_API_KEY', 'server-key')
    monkeypatch.setattr(httpx, 'get', get)
    geo.search_place.cache_clear()
    assert geo.search_place('cached grouping query')['latitude'] == 40.92
    details = geo.search_place_details('cached grouping query')
    assert details['city'] == '承德市'
    assert details['partial_match'] is True
    assert details['region'] == '河北省'
    assert calls == ['cached grouping query']
    geo.search_place.cache_clear()
