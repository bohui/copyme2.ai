from copy import deepcopy

from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.store import MemoryStore
from apps.api import place_groups as groups


CITY = {'place': '承德', 'hierarchy': ['Earth', '中国', '河北', '承德'],
        'granularity': 'city', 'latitude': 40.97, 'longitude': 117.93}
DISTRICT = {'place': '双桥区', 'hierarchy': [*CITY['hierarchy'], '双桥区'],
          'granularity': 'suburb', 'latitude': 40.93, 'longitude': 117.96}
TOWN = {'place': '大石庙镇', 'hierarchy': ['Earth', '中国', '河北省', '承德市', '大石庙镇'],
        'granularity': 'suburb', 'latitude': 40.921, 'longitude': 117.962}


def test_multiple_places_from_one_turn_share_city_without_a_saved_city_entry(monkeypatch):
    district = {'place': '双桥区', 'hierarchy': ['Earth', '中国', '河北', '承德', '双桥区'],
                'granularity': 'suburb'}
    town = {key: value for key, value in TOWN.items() if key not in ('latitude', 'longitude')}
    before = deepcopy([town, district])
    def lookup(query):
        return {'latitude': 40.921 if query.startswith('大石庙镇') else 40.974,
                'longitude': 117.962 if query.startswith('大石庙镇') else 117.943,
                'city': '承德市', 'region': '河北省', 'country': '中国', 'partial_match': False}
    monkeypatch.setattr(groups, 'search_place_details', lookup)
    result = groups.resolve_place_groups([town, district])
    assert len({place['city_key'] for place in result['places']}) == 1
    assert [place['pin']['place'] for place in result['places']] == ['大石庙镇', '双桥区']
    assert result['places'][0]['pin']['latitude'] != result['places'][1]['pin']['latitude']
    assert [town, district] == before


def test_city_children_group_without_destroying_place_identity(monkeypatch):
    entries = [CITY, DISTRICT, TOWN]
    before = deepcopy(entries)
    monkeypatch.setattr(groups, 'search_place_details', lambda query: None)
    result = groups.resolve_place_groups(entries)
    assert len({record['city_key'] for record in result['places']}) == 1
    assert [record['pin']['place'] for record in result['places'][1:]] == ['双桥区', '大石庙镇']
    assert entries == before
    assert result['skills'] == ['memoir-place-groups']


def test_geocoder_city_membership_groups_different_paths_but_partial_matches_get_no_pin(monkeypatch):
    entries = [{**DISTRICT, 'hierarchy': ['Earth', '中国', '双桥区'], 'latitude': None, 'longitude': None},
               {**TOWN, 'hierarchy': ['Earth', '中国', '大石庙镇'], 'latitude': None, 'longitude': None}]
    def lookup(query):
        return {'latitude': 40.92, 'longitude': 117.96, 'city': '承德市', 'region': '河北省',
                'country': '中国', 'partial_match': query.startswith('双桥区')}
    monkeypatch.setattr(groups, 'search_place_details', lookup)
    result = groups.resolve_place_groups(entries)
    assert result['places'][0]['city_key'] == result['places'][1]['city_key']
    assert result['places'][0]['pin'] is None
    assert result['places'][1]['pin']['place'] == '大石庙镇'


def test_parent_coordinates_are_not_child_pins_and_other_cities_stay_separate(monkeypatch):
    monkeypatch.setattr(groups, 'search_place_details', lambda query: None)
    result = groups.resolve_place_groups([CITY, {**DISTRICT, 'latitude': CITY['latitude'], 'longitude': CITY['longitude']},
        {'place': 'Sydney', 'hierarchy': ['Earth', 'Australia', 'Sydney'], 'granularity': 'city',
         'latitude': -33.86, 'longitude': 151.2}])
    assert result['places'][1]['pin'] is None
    assert result['places'][0]['city_key'] != result['places'][2]['city_key']


def test_grouping_endpoint_is_project_owned_and_read_only(monkeypatch):
    monkeypatch.setattr(groups, 'search_place_details', lambda query: None)
    client = TestClient(create_app(MemoryStore()))
    headers = {'X-Account-Id': 'group-owner'}
    project = client.post('/v1/projects', headers=headers, json={'mode': 'self'}).json()
    url = f"/v1/projects/{project['id']}/place-groups"
    response = client.post(url, headers=headers, json={'places': [CITY, DISTRICT, TOWN]})
    assert response.status_code == 200
    assert response.json()['places'][1]['city']['place'] == '承德'
    assert client.get(f"/v1/projects/{project['id']}", headers=headers).json()['profile'] == project['profile']
    assert client.post(url, headers={'X-Account-Id': 'other'}, json={'places': [CITY]}).status_code in (403, 404)
    assert client.post(url, headers=headers, json={'places': [{'place': 'unknown'}]}).status_code == 422


def test_provider_city_centre_does_not_turn_into_child_pin(monkeypatch):
    monkeypatch.setattr(groups, 'search_place_details', lambda query: {
        'latitude': CITY['latitude'], 'longitude': CITY['longitude'],
        'city': '承德', 'country': '中国', 'region': '河北', 'partial_match': False})
    result = groups.resolve_place_groups([CITY, {key: value for key, value in DISTRICT.items()
                                                if key not in ('latitude', 'longitude')}])
    assert result['places'][1]['pin'] is None
    assert result['places'][1]['pin_status'] == 'UNRESOLVED'


def test_missing_region_does_not_split_the_same_city_or_merge_conflicting_regions(monkeypatch):
    monkeypatch.setattr(groups, 'search_place_details', lambda query: None)
    short = {'place': '悉尼', 'hierarchy': ['Earth', '澳大利亚', '悉尼'], 'granularity': 'city',
             'latitude': -33.8688, 'longitude': 151.2093}
    full = {**short, 'place': '悉尼市', 'hierarchy': ['Earth', '澳大利亚', '新南威尔士州', '悉尼市']}
    conflict = {**short, 'hierarchy': ['Earth', '澳大利亚', '另一个州', '悉尼']}
    result = groups.resolve_place_groups([short, full])
    assert result['places'][0]['city_key'] == result['places'][1]['city_key']
    result = groups.resolve_place_groups([short, full, conflict])
    assert result['places'][1]['city_key'] != result['places'][2]['city_key']
    assert result['places'][0]['city_key'] not in {result['places'][1]['city_key'],result['places'][2]['city_key']}
