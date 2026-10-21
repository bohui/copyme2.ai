import json
from pathlib import Path

import pytest

from apps.api.place_journey import (
    extract_place_journey,
    extract_place_journeys,
    grounded_place_journeys,
    normalize_persisted_place_journey,
    place_journey_matches_message,
    place_journey_fingerprint,
    validate_place_journey,
)


def test_chinese_place_markers_normalize_earth_and_preserve_both_named_cities():
    message = '我叫慧博，现在生活在悉尼，但是我于1983年4月出生在河北省承德市附属医院'
    markers = ''.join('[[MEMORY_SPARK_PLACE_JOURNEY]]' + json.dumps({
        'place': place, 'hierarchy': ['地球', country, place], 'granularity': 'city',
    }, ensure_ascii=False) + '[[/MEMORY_SPARK_PLACE_JOURNEY]]'
        for place, country in [('悉尼', '澳大利亚'), ('承德市', '中国')])
    _, journeys = extract_place_journeys(markers)
    assert [journey['place'] for journey in journeys] == ['悉尼', '承德市']
    assert all(journey['hierarchy'][0] == 'Earth' for journey in journeys)
    assert all(place_journey_matches_message(journey, message) for journey in journeys)


def test_same_city_aliases_are_deduplicated_after_source_grounding():
    full = {'place': '承德市', 'hierarchy': ['Earth', '中国', '河北省', '承德市'],
            'granularity': 'city', 'latitude': 40.9517, 'longitude': 117.9632}
    short = {'place': '承德', 'hierarchy': ['Earth', '中国', '河北', '承德'], 'granularity': 'city'}
    result = grounded_place_journeys([full, short], '我在承德市长大，后来又回到承德。')
    assert len(result) == 1
    assert result[0]['place'] == '承德'
    assert result[0]['latitude'] == full['latitude']
    # The first alias is not grounded in this wording. It must not suppress the
    # later valid marker or donate its coordinates before grounding succeeds.
    result = grounded_place_journeys([full, short], '我后来又回到承德。')
    assert result == [short]
    assert 'latitude' not in short








def test_keeps_standalone_provinces_and_independent_cities_and_suburbs():
    province = {'place': '河北省', 'hierarchy': ['Earth', '中国', '河北省'], 'granularity': 'region'}
    city = {'place': '承德市', 'hierarchy': [*province['hierarchy'], '承德市'], 'granularity': 'city'}
    suburb = {'place': '双桥区', 'hierarchy': [*city['hierarchy'], '双桥区'], 'granularity': 'suburb'}
    assert grounded_place_journeys([province, city], '我记得河北省。') == [province]
    assert grounded_place_journeys([city, suburb], '我出生在承德市双桥区。') == [city, suburb]


def test_an_unrelated_hierarchy_cannot_remove_a_province_cue():
    province = {'place': '河北省', 'hierarchy': ['Earth', 'Other country', '河北省'], 'granularity': 'region'}
    city = {'place': '承德市', 'hierarchy': ['Earth', '中国', '河北省', '承德市'], 'granularity': 'city'}
    assert grounded_place_journeys([province, city], '河北省承德市') == [province, city]


@pytest.mark.parametrize('place,granularity', [
    ('家属院', 'landmark'), ('家属院', 'suburb'), ('市区', 'city'),
    ('学校', 'suburb'), ('the old river town', 'suburb'),
    ('河北省承德市附属医院', 'city'), ('承德师范学校', 'suburb'),
    ('Chatswood station', 'suburb'), ('Royal North Shore Hospital', 'city'),
    ('12 George Street', 'suburb'),
])
def test_rejects_generic_and_more_detailed_than_suburb_places(place, granularity):
    assert validate_place_journey({
        'place': place, 'hierarchy': ['Earth', place], 'granularity': granularity,
    }) is None


@pytest.mark.parametrize('place', ['大石庙镇', '双桥区', 'Chatswood', 'Townsville', 'College Park', 'Road Town'])
def test_accepts_named_towns_and_suburbs(place):
    assert validate_place_journey({
        'place': place, 'hierarchy': ['Earth', place], 'granularity': 'suburb',
    }) is not None


@pytest.mark.parametrize('detail', ['家属院', '承德师范学校', 'Chatswood station'])
def test_rejects_detailed_or_generic_hierarchy_even_with_a_city_label(detail):
    assert validate_place_journey({
        'place': '承德市', 'hierarchy': ['Earth', '中国', '承德市', detail], 'granularity': 'city',
    }) is None


def test_extracts_all_places_and_removes_invalid_duplicate_and_incomplete_markers():
    def marker(place, **overrides):
        return ('[[MEMORY_SPARK_PLACE_JOURNEY]]' + json.dumps({
            'place': place, 'hierarchy': ['Earth', '中国', '河北', '承德', place],
            'granularity': 'suburb', **overrides,
        }, ensure_ascii=False) + '[[/MEMORY_SPARK_PLACE_JOURNEY]]')

    text = ('童年的两处地方。\n'
            + marker('大石庙镇')
            + marker('invalid', latitude=91, longitude=120)
            + '[[MEMORY_SPARK_PLACE_JOURNEY]]not json[[/MEMORY_SPARK_PLACE_JOURNEY]]'
            + '[[MEMORY_SPARK_PLACE_JOURNEY]]unfinished'
            + marker('双桥区') + marker('大石庙镇')
            + '[[MEMORY_SPARK_PLACE_JOURNEY]]trailing')
    visible, journeys = extract_place_journeys(text)
    assert visible == '童年的两处地方。'
    assert [place['place'] for place in journeys] == ['大石庙镇', '双桥区']
    assert all(place['granularity'] == 'suburb' for place in journeys)
    assert extract_place_journey(text) == (visible, journeys[0])


def test_extracts_and_removes_valid_place_journey_marker():
    text = (
        "That sounds like a place worth returning to.\n"
        "[[MEMORY_SPARK_PLACE_JOURNEY]]"
        '{"place":"Anshan","hierarchy":["Earth","China","Liaoning","Anshan"],'
        '"granularity":"city","latitude":41.1086,"longitude":122.99,"duration_ms":5200}'
        "[[/MEMORY_SPARK_PLACE_JOURNEY]]"
    )

    visible, journey = extract_place_journey(text)

    assert visible == "That sounds like a place worth returning to."
    assert journey == {
        "schema_version": 1,
        "place": "Anshan",
        "hierarchy": ["Earth", "China", "Liaoning", "Anshan"],
        "granularity": "city",
        "latitude": 41.1086,
        "longitude": 122.99,
        "duration_ms": 5200,
    }


def test_allows_a_hierarchy_only_journey_for_an_unresolved_place():
    journey = validate_place_journey({
        "place": "Wauchope",
        "hierarchy": ["Earth", "Australia", "New South Wales"],
        "granularity": "region",
    })

    assert journey == {
        "schema_version": 1,
        "place": "Wauchope",
        "hierarchy": ["Earth", "Australia", "New South Wales"],
        "granularity": "region",
        "duration_ms": 5200,
    }


def test_rejects_exact_or_invalid_coordinates():
    assert validate_place_journey({
        "place": "Somewhere",
        "hierarchy": ["Earth", "Australia", "Somewhere"],
        "granularity": "city",
        "latitude": 91,
        "longitude": 151,
    }) is None
    assert validate_place_journey({
        "place": "Somewhere",
        "hierarchy": ["Earth", "Australia", "Somewhere"],
        "granularity": "city",
        "latitude": 35,
    }) is None


def test_normalizes_a_hierarchy_only_persisted_record():
    row = {
        "schema_version": 1,
        "status": "active",
        "revision": 3,
        "place": "Wauchope",
        "hierarchy": ["Earth", "Australia", "New South Wales"],
        "granularity": "region",
        "latitude": None,
        "longitude": None,
        "duration_ms": 5200,
        "updated_at": "2026-09-26T00:00:00Z",
    }

    normalized = normalize_persisted_place_journey(row)

    assert normalized == {
        "schema_version": 1,
        "status": "active",
        "revision": 3,
        "place": "Wauchope",
        "hierarchy": ["Earth", "Australia", "New South Wales"],
        "granularity": "region",
        "latitude": None,
        "longitude": None,
        "duration_ms": 5200,
        "updated_at": "2026-09-26T00:00:00Z",
    }
    assert place_journey_fingerprint(normalized)[-1] == 5200


def test_drops_unterminated_marker_payload():
    visible, journey = extract_place_journey(
        'I remember the feeling. [[MEMORY_SPARK_PLACE_JOURNEY]]{"place":"Secret"}'
    )

    assert visible == "I remember the feeling."
    assert journey is None


def test_place_journey_marker_must_match_the_current_storyteller_message():
    journey = {
        "place": "Geelong",
        "hierarchy": ["Earth", "Australia", "Victoria", "Geelong"],
        "granularity": "city",
    }

    assert not place_journey_matches_message(journey, "Tell me about that day.")
    assert not place_journey_matches_message(journey, "I remember living in Victoria.")
    assert place_journey_matches_message(journey, "I remember a summer in Geelong.")
