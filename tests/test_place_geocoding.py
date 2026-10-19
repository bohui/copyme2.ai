import httpx
import pytest
from fastapi.testclient import TestClient
from apps.api.main import create_app
from apps.api.store import MemoryStore
from apps.api import place_geocoding as geo

CITY = {"place": "承德", "hierarchy": ["Earth", "中国", "河北", "承德"], "granularity": "city", "latitude": 40.97, "longitude": 117.93}
SUBURB = {"place": "大石庙镇", "hierarchy": [*CITY['hierarchy'], "大石庙镇"], "granularity": "suburb"}
GEOAPIFY_TOWN = {'name': '大石庙镇', 'lat': 40.921285, 'lon': 117.961817, 'result_type': 'suburb',
                'suburb': '大石庙镇', 'city': '承德市', 'state': '河北省', 'country': '中国',
                'rank': {'match_type': 'full_match', 'confidence': 1.0}}
TOWN_QUERY = '大石庙镇, 承德, 河北, 中国'


@pytest.fixture(autouse=True)
def isolate_geocoding(monkeypatch):
    for key in ('MEMOIR_GEO_PROVIDER', 'GOOGLE_MAPS_GEOCODING_API_KEY', 'GOOGLE_MAPS_GEOCODING_URL',
                'GEOAPIFY_API_KEY', 'GEOAPIFY_GEOCODING_URL'):
        monkeypatch.delenv(key, raising=False)
    clear_cache = geo.search_place.cache_clear
    clear_cache()
    yield
    clear_cache()


@pytest.mark.parametrize('provider,parameter,chinese,english', [
    ('google', 'language', 'zh-CN', 'en'), ('geoapify', 'lang', 'zh', 'en'),
])
def test_display_language_is_sent_to_the_provider_and_scopes_its_cache(monkeypatch, provider, parameter, chinese, english):
    monkeypatch.setenv('MEMOIR_GEO_PROVIDER', provider)
    monkeypatch.setenv('GOOGLE_MAPS_GEOCODING_API_KEY' if provider == 'google' else 'GEOAPIFY_API_KEY', 'synthetic-key')
    calls = []
    def get(url, **kwargs):
        calls.append(kwargs['params'][parameter])
        record = ({'geometry':{'location':{'lat':40.97,'lng':117.93}},'address_components':[
            {'long_name':'承德市','types':['locality']}, {'long_name':'中国','types':['country']}]}
            if provider == 'google' else GEOAPIFY_TOWN)
        return httpx.Response(200, json={'status':'OK','results':[record]}, request=httpx.Request('GET',url))
    monkeypatch.setattr(httpx, 'get', get)
    for language in ['zh-CN', 'en-AU', 'zh-CN']:
        assert geo.search_place_details(TOWN_QUERY, language=language)
    assert calls == [chinese, english]


def test_geoapify_localized_fields_are_checked_against_the_original_query(monkeypatch):
    monkeypatch.setenv('MEMOIR_GEO_PROVIDER', 'geoapify')
    monkeypatch.setenv('GEOAPIFY_API_KEY', 'synthetic-key')
    calls = []
    localized = {
        'name': '承德市', 'city': '承德市', 'state': '河北省', 'country': '中国',
        'country_code': 'cn', 'result_type': 'city', 'lat': 40.97, 'lon': 117.93,
        'rank': {'match_type': 'full_match', 'confidence': 1.0, 'confidence_city_level': 1.0},
    }
    canonical = {**localized, 'name': 'Chengde', 'city': 'Chengde',
                 'state': 'Hebei', 'country': 'China'}

    def get(url, **kwargs):
        calls.append(kwargs['params'])
        record = localized if kwargs['params'].get('lang') == 'en' else canonical
        return httpx.Response(200, json={'results': [record]}, request=httpx.Request('GET', url))

    monkeypatch.setattr(httpx, 'get', get)
    details = geo.search_place_details('Chengde, Hebei, China', language='en-AU')
    assert details['city'] == '承德市'
    assert len(calls) == 2
    assert calls[0]['lang'] == 'en'
    assert 'lang' not in calls[1]


@pytest.mark.parametrize('overrides', [
    {'rank': {'match_type': 'full_match', 'confidence': 0.2}},
    {'rank': {'match_type': 'full_match', 'confidence': 1.0, 'confidence_city_level': 0.3}},
    {'rank': {'match_type': 'full_match'}},
    {'rank': {'match_type': 'full_match', 'confidence': True}},
    {'rank': {'match_type': 'full_match', 'confidence': 1.1}},
    {'rank': {'match_type': 'full_match', 'confidence': '1.0'}},
    {'state': '江苏省'},
    {'state': ''},
    {'suburb': ''},
    {'city': '南京市'},
    {'country': 'Australia'},
    {'name': '另一镇', 'suburb': '另一镇'},
    {'result_type': 'building'},
])
def test_geoapify_rejects_low_confidence_or_conflicting_full_matches(monkeypatch, overrides):
    from apps.api.place_groups import resolve_place_groups
    record = {**GEOAPIFY_TOWN, 'lat': 32.06, 'lon': 118.79, **overrides}
    monkeypatch.setenv('MEMOIR_GEO_PROVIDER', 'geoapify')
    monkeypatch.setenv('GEOAPIFY_API_KEY', 'synthetic-key')
    monkeypatch.setattr(httpx, 'get', lambda url, **kwargs: httpx.Response(200,
        json={'results': [record]}, request=httpx.Request('GET', url)))
    grouped = resolve_place_groups([CITY, SUBURB])['places'][1]
    assert grouped['pin'] is None, 'An untrusted provider match must not create a READY pin'
    assert grouped['city']['place'] == CITY['place'], 'Keep the supplied containing city'
    target = geo.resolve_place_map(SUBURB, [CITY])
    assert target['fallback'] is True
    assert target['target']['place'] == CITY['place']


@pytest.mark.parametrize('query,record', [
    (TOWN_QUERY, {**GEOAPIFY_TOWN, 'rank': {'match_type': 'full_match', 'confidence': 0.95}}),
    ('chatswood, new south wales, australia', {
        'name': 'Chatswood', 'suburb': 'Chatswood', 'city': 'Sydney', 'state': 'New South Wales',
        'country': 'Australia', 'result_type': 'suburb', 'lat': -33.795, 'lon': 151.183,
        'rank': {'match_type': 'full_match', 'confidence': 1.0, 'confidence_city_level': 1.0}}),
    ('中国', {'name': '中国', 'country': '中国', 'result_type': 'country', 'lat': 35.0, 'lon': 104.0,
            'rank': {'match_type': 'full_match', 'confidence': 1.0, 'confidence_city_level': 0.0}}),
])
def test_geoapify_accepts_confident_results_matching_the_supplied_hierarchy(monkeypatch, query, record):
    monkeypatch.setenv('MEMOIR_GEO_PROVIDER', 'geoapify')
    monkeypatch.setenv('GEOAPIFY_API_KEY', 'synthetic-key')
    monkeypatch.setattr(httpx, 'get', lambda url, **kwargs: httpx.Response(200,
        json={'results': [record]}, request=httpx.Request('GET', url)))
    assert geo.search_place(query) == {'latitude': record['lat'], 'longitude': record['lon'],
                                      'attribution': 'Geoapify / OpenStreetMap'}


@pytest.mark.parametrize('query', ['大石庙镇, 河北, 承德, 中国', '中国', '河北, 中国', '承德, 河北, 中国'])
def test_geoapify_cannot_relabel_a_child_result_as_a_different_target(monkeypatch, query):
    monkeypatch.setenv('MEMOIR_GEO_PROVIDER', 'geoapify')
    monkeypatch.setenv('GEOAPIFY_API_KEY', 'synthetic-key')
    monkeypatch.setattr(httpx, 'get', lambda url, **kwargs: httpx.Response(200,
        json={'results': [GEOAPIFY_TOWN]}, request=httpx.Request('GET', url)))
    assert geo.search_place(query) is None


@pytest.mark.parametrize('query,overrides', [
    ('承德, 河北, 中国', {'result_type': 'city', 'name': '承德', 'city': '南京市'}),
    ('河北, 中国', {'result_type': 'state', 'name': '河北', 'state': '江苏省'}),
    ('中国', {'result_type': 'country', 'name': '中国', 'country': 'Australia'}),
])
def test_geoapify_name_cannot_override_contradictory_administrative_fields(monkeypatch, query, overrides):
    monkeypatch.setenv('MEMOIR_GEO_PROVIDER', 'geoapify')
    monkeypatch.setenv('GEOAPIFY_API_KEY', 'synthetic-key')
    monkeypatch.setattr(httpx, 'get', lambda url, **kwargs: httpx.Response(200,
        json={'results': [{**GEOAPIFY_TOWN, **overrides}]}, request=httpx.Request('GET', url)))
    assert geo.search_place(query) is None


def test_search_place_uses_geoapify_geocoding(monkeypatch):
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, json={
            "results": [GEOAPIFY_TOWN],
        }, request=httpx.Request("GET", url))

    monkeypatch.setenv("MEMOIR_GEO_PROVIDER", "geoapify")
    monkeypatch.setenv("GEOAPIFY_API_KEY", "server-key")
    monkeypatch.setattr(httpx, "get", get)
    geo.search_place.cache_clear()

    assert geo.search_place("大石庙镇, 承德, 河北, 中国") == {
        "latitude": 40.921285,
        "longitude": 117.961817,
        "attribution": "Geoapify / OpenStreetMap",
    }
    assert calls == [("https://api.geoapify.com/v1/geocode/search", {
        "params": {"text": "大石庙镇, 承德, 河北, 中国", "format": "json", "limit": 1,
                   "apiKey": "server-key", "bias": "countrycode:none"},
        "headers": {"Accept": "application/json"},
        "timeout": 5,
    })]


def test_google_remains_the_default_and_preserves_administrative_details(monkeypatch):
    calls = []
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, json={'status': 'OK', 'results': [{
            'geometry': {'location': {'lat': 40.92, 'lng': 117.96}},
            'address_components': [
                {'long_name': '大石庙镇', 'types': ['locality']},
                {'long_name': '承德市', 'types': ['administrative_area_level_2']},
                {'long_name': '河北省', 'types': ['administrative_area_level_1']},
                {'long_name': '中国', 'types': ['country']}],
            'partial_match': True}]}, request=httpx.Request('GET', url))
    monkeypatch.setenv('GOOGLE_MAPS_GEOCODING_API_KEY', 'google-server-key')
    monkeypatch.setattr(httpx, 'get', get)
    assert geo.geo_provider() == 'google'
    query = '大石庙镇, 承德, 河北, 中国'
    assert geo.search_place_details(query) == {
        'latitude': 40.92, 'longitude': 117.96, 'city': '承德市', 'region': '河北省',
        'country': '中国', 'partial_match': True, 'attribution': 'Google Maps'}
    assert geo.search_place(query)['attribution'] == 'Google Maps'
    assert calls == [('https://maps.googleapis.com/maps/api/geocode/json', {
        'params': {'address': query, 'key': 'google-server-key'},
        'headers': {'Accept': 'application/json'}, 'timeout': 5})]


def test_switching_provider_keeps_query_caches_separate(monkeypatch):
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        body = {'status': 'OK', 'results': [{'geometry': {'location': {'lat': 40.9, 'lng': 117.9}}}]}
        if 'geoapify' in url:
            body = {'results': [{'lat': 40.8, 'lon': 117.8, 'name': 'Chengde', 'city': 'Chengde',
                'result_type': 'city', 'rank': {'match_type': 'full_match', 'confidence': 1.0}}]}
        return httpx.Response(200, json=body, request=httpx.Request('GET', url))
    monkeypatch.setenv('GOOGLE_MAPS_GEOCODING_API_KEY', 'google-key')
    monkeypatch.setenv('GEOAPIFY_API_KEY', 'geoapify-key')
    monkeypatch.setattr(httpx, 'get', get)
    assert geo.search_place('Chengde')['latitude'] == 40.9
    monkeypatch.setenv('MEMOIR_GEO_PROVIDER', 'geoapify')
    assert geo.search_place('Chengde')['latitude'] == 40.8
    monkeypatch.setenv('MEMOIR_GEO_PROVIDER', 'google')
    assert geo.search_place('Chengde')['latitude'] == 40.9
    assert len(calls) == 2


@pytest.mark.parametrize('value,expected', [('', 'google'), ('  ', 'google'),
    (' Google ', 'google'), ('Geoapify', 'geoapify')])
def test_provider_flag_normalizes_explicit_values_and_blank_default(monkeypatch, value, expected):
    monkeypatch.setenv('MEMOIR_GEO_PROVIDER', value)
    assert geo.geo_provider() == expected


def test_malformed_geoapify_match_metadata_keeps_saved_parent_fallback(monkeypatch):
    monkeypatch.setenv('MEMOIR_GEO_PROVIDER', 'geoapify')
    monkeypatch.setenv('GEOAPIFY_API_KEY', 'key')
    monkeypatch.setattr(httpx, 'get', lambda url, **kwargs: httpx.Response(200,
        json={'results': [{'lat': 40.92, 'lon': 117.96, 'rank': ['invalid']}]},
        request=httpx.Request('GET', url)))
    assert geo.resolve_place_map(SUBURB, [CITY])['target']['place'] == CITY['place']
    assert geo.resolve_place_map(SUBURB, [])['status'] == 'UNAVAILABLE'


@pytest.mark.parametrize('provider', ['google', 'geoapify', 'amap'])
def test_missing_selected_provider_key_or_unknown_provider_never_uses_other_provider(monkeypatch, provider):
    monkeypatch.setenv('MEMOIR_GEO_PROVIDER', provider)
    monkeypatch.setenv('GEOAPIFY_API_KEY' if provider == 'google' else 'GOOGLE_MAPS_GEOCODING_API_KEY', 'other-key')
    def unexpected_request(*args, **kwargs):
        raise AssertionError('The other provider must not be contacted')
    monkeypatch.setattr(httpx, 'get', unexpected_request)
    with pytest.raises(geo.GeocodingUnavailable):
        geo.search_place('missing-key query')
    assert geo.resolve_place_map(SUBURB, [])['status'] == 'UNAVAILABLE'
    assert geo.resolve_place_map(SUBURB, [CITY])['target']['place'] == CITY['place']


@pytest.mark.parametrize('status', ['REQUEST_DENIED', 'OVER_QUERY_LIMIT', 'UNKNOWN_ERROR', None])
def test_google_error_status_is_unavailable(monkeypatch, status):
    monkeypatch.setenv('GOOGLE_MAPS_GEOCODING_API_KEY', 'google-key')
    monkeypatch.setattr(httpx, 'get', lambda url, **kwargs: httpx.Response(200,
        json={'status': status, 'results': []}, request=httpx.Request('GET', url)))
    with pytest.raises(geo.GeocodingUnavailable):
        geo.search_place('denied query')


@pytest.mark.parametrize('provider', ['google', 'geoapify'])
@pytest.mark.parametrize('coordinates', [None, (True, 117.9), (91, 117.9), (40.9, 181), ('nan', 117.9)])
def test_missing_or_invalid_coordinates_do_not_create_pins(monkeypatch, provider, coordinates):
    monkeypatch.setenv('MEMOIR_GEO_PROVIDER', provider)
    monkeypatch.setenv('GOOGLE_MAPS_GEOCODING_API_KEY' if provider == 'google' else 'GEOAPIFY_API_KEY', 'key')
    def get(url, **kwargs):
        results = []
        if coordinates:
            lat, lon = coordinates
            results = [{'geometry': {'location': {'lat': lat, 'lng': lon}}} if provider == 'google'
                       else {'lat': lat, 'lon': lon}]
        return httpx.Response(200, json={'status': 'OK' if results else 'ZERO_RESULTS', 'results': results},
                              request=httpx.Request('GET', url))
    monkeypatch.setattr(httpx, 'get', get)
    assert geo.search_place('invalid coordinates query') is None


@pytest.mark.parametrize('match_type,partial', [('full_match', False), ('inner_part', True),
    ('match_by_city_or_disrict', True), ('match_by_country_or_state', True), (None, True)])
def test_geoapify_partial_matches_are_not_independent_group_pins(monkeypatch, match_type, partial):
    from apps.api.place_groups import resolve_place_groups
    monkeypatch.setenv('MEMOIR_GEO_PROVIDER', 'geoapify')
    monkeypatch.setenv('GEOAPIFY_API_KEY', 'geoapify-key')
    monkeypatch.setattr(httpx, 'get', lambda url, **kwargs: httpx.Response(200, json={'results': [{
        **GEOAPIFY_TOWN, 'rank': {'match_type': match_type, 'confidence': 1.0}}]}, request=httpx.Request('GET', url)))
    assert geo.search_place_details(TOWN_QUERY)['partial_match'] is partial
    assert (geo.search_place(TOWN_QUERY) is None) is partial
    pin = resolve_place_groups([SUBURB])['places'][0]['pin']
    assert (pin is None) is partial


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


def test_city_alias_reuses_project_coordinates_without_geocoding(monkeypatch):
    def unexpected_lookup(query):
        raise AssertionError('A known city alias must not need the provider')
    monkeypatch.setattr(geo, 'search_place', unexpected_lookup)
    client = TestClient(create_app(MemoryStore()))
    headers = {'X-Account-Id': 'alias-owner'}
    project = client.post('/v1/projects', headers=headers, json={'mode': 'self'}).json()
    saved = {**CITY, 'place': '承德市', 'hierarchy': ['Earth', '中国', '河北省', '承德市']}
    assert client.patch(f"/v1/projects/{project['id']}", headers=headers,
                        json={'profile': {'memory_places': [saved]}}).status_code == 200
    current = {**CITY, 'latitude': None, 'longitude': None}
    response = client.post(f"/v1/projects/{project['id']}/place-map", headers=headers, json=current)
    assert response.status_code == 200
    assert response.json() == {'status': 'READY', 'target': {
        'place': '承德', 'latitude': CITY['latitude'], 'longitude': CITY['longitude']}, 'fallback': False}


def test_city_alias_is_a_parent_target_and_does_not_supply_child_coordinates(monkeypatch):
    monkeypatch.setattr(geo, 'search_place', lambda query: None)
    saved = {**CITY, 'place': '承德市', 'hierarchy': ['Earth', '中国', '河北省', '承德市']}
    result = geo.resolve_place_map(SUBURB, [saved])
    assert result['target']['place'] == '承德'
    assert result['fallback'] is True
    assert 'latitude' not in SUBURB


def test_alias_matching_preserves_regions_and_county_identity(monkeypatch):
    monkeypatch.setattr(geo, 'search_place', lambda query: None)
    saved = {**CITY, 'place': '承德市', 'hierarchy': ['Earth', '中国', '河北省', '承德市']}
    for current in (
        {**CITY, 'hierarchy': ['Earth', '中国', '另一省', '承德']},
        {**CITY, 'place': '承德县', 'hierarchy': ['Earth', '中国', '河北', '承德县'], 'granularity': 'suburb'},
    ):
        current.pop('latitude')
        current.pop('longitude')
        assert geo.resolve_place_map(current, [saved])['target'] is None


def test_grouping_metadata_shares_map_cache_and_preserves_partial_match(monkeypatch):
    calls = []
    def get(url, **kwargs):
        calls.append(kwargs['params']['text'])
        return httpx.Response(200, json={'results': [{**GEOAPIFY_TOWN,
            'rank': {'match_type': 'inner_part', 'confidence': 1.0}}]}, request=httpx.Request('GET', url))
    monkeypatch.setenv('MEMOIR_GEO_PROVIDER', 'geoapify')
    monkeypatch.setenv('GEOAPIFY_API_KEY', 'server-key')
    monkeypatch.setattr(httpx, 'get', get)
    geo.search_place.cache_clear()
    assert geo.search_place(TOWN_QUERY) is None
    details = geo.search_place_details(TOWN_QUERY)
    assert details['city'] == '承德市'
    assert details['partial_match'] is True
    assert details['region'] == '河北省'
    assert calls == [TOWN_QUERY]
    geo.search_place.cache_clear()
