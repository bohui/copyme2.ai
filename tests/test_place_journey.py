from apps.api.codex_runtime import build_system_prompt
from apps.api.place_journey import extract_place_journey, validate_place_journey


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


def test_drops_unterminated_marker_payload():
    visible, journey = extract_place_journey(
        'I remember the feeling. [[MEMORY_SPARK_PLACE_JOURNEY]]{"place":"Secret"}'
    )

    assert visible == "I remember the feeling."
    assert journey is None


def test_prompt_includes_the_project_skill_contract():
    prompt = build_system_prompt("(none)")

    assert "memoir-place-journey" in prompt
    assert "MEMORY_SPARK_PLACE_JOURNEY" in prompt
    assert "Private notes from earlier turns:\n(none)" in prompt
