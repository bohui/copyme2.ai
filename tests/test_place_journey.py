import json
from pathlib import Path

from apps.api.codex_runtime import build_system_prompt
from apps.api.place_journey import (
    extract_place_journey,
    extract_place_journeys,
    normalize_persisted_place_journey,
    place_journey_matches_message,
    place_journey_fingerprint,
    validate_place_journey,
)


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
        "place": "The old river town",
        "hierarchy": ["Earth", "Australia", "New South Wales"],
        "granularity": "region",
    })

    assert journey == {
        "schema_version": 1,
        "place": "The old river town",
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
        "place": "The old river town",
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
        "place": "The old river town",
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


def test_prompt_includes_the_project_skill_contract():
    prompt = build_system_prompt("(none)")

    assert "memoir-place-journey" in prompt
    assert "MEMORY_SPARK_PLACE_JOURNEY" in prompt
    assert "Private notes from earlier turns:\n(none)" in prompt


def test_place_label_preserves_source_script_in_an_english_conversation():
    prompt = build_system_prompt("(none)", language="en-AU")
    assert "Never translate or transliterate this field" in prompt
    journey = {"place": "承德", "hierarchy": ["Earth", "China", "Hebei", "承德"],
               "granularity": "city"}
    assert place_journey_matches_message(journey, "我1983年出生在河北承德附属医院。")
    assert not place_journey_matches_message(journey, "我现在住在悉尼。")


def test_prompt_makes_mira_a_low_pressure_oral_history_journalist():
    prompt = build_system_prompt("(none)")

    assert "You are Mira, the AI memoir interviewer for CopyMe2 Memoir." in prompt
    assert "Ask at most one main question per turn." in prompt
    assert "A photograph the storyteller chooses to discuss is a valid photo-first starting point" in prompt
    assert "Do not ask for name, birth date, hometown, occupation and a first story together." in prompt
    assert "Do not ask a question merely to fill a missing field" in prompt
    assert "Do not narrate the interview process in an ordinary memory prompt." in prompt
    assert "我们先不急着往后走" in prompt
    assert "Reserve explicit choices about pausing or changing pace" in prompt


def test_prompt_is_loaded_from_the_versioned_system_prompt_file():
    prompt = build_system_prompt("(none)")
    source = (Path(__file__).parents[1] / "Mira_Memoir_Journalist_System_Prompt_v1.0.md").read_text(
        encoding="utf-8"
    ).rstrip()

    assert prompt.startswith(source + "\n\nPrivate application context")
