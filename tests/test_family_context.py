import copy
import hashlib
import json

import pytest

from apps.api.family_context import (
    combine_family_skill_updates,
    empty_family_context_document,
    extract_author_timeline_context,
    extract_family_context,
    extract_family_skill_updates,
    extract_family_tree_context,
    family_features_enabled,
    merge_family_context_document,
    normalise_family_context_document,
    validate_author_timeline_context,
    validate_family_tree_context,
    validate_family_context,
)


def test_person_introduction_survives_validation_and_canonical_updates():
    update = validate_family_tree_context({"people": [{
        "id": "mum", "name": "Mei", "introduction": "She grew roses, perhaps in the late 1960s."
    }]})
    document, _ = merge_family_context_document(empty_family_context_document("project"), update, "project")
    person = document["people"][0]
    assert person["introduction"] == "She grew roses, perhaps in the late 1960s."
    revised = validate_family_tree_context({"people": [{
        "id": "mum-again", "existing_id": person["id"], "name": "Mei",
        "introduction": "She grew roses and taught me to tend the garden."
    }]})
    document, _ = merge_family_context_document(document, revised, "project")
    assert len(document["people"]) == 1
    assert document["people"][0]["id"] == person["id"]
    assert document["people"][0]["introduction"] == "She grew roses and taught me to tend the garden."
    for invalid in ["x" * 1201, 42, "   "]:
        assert validate_family_tree_context({"people": [{"id": "mum", "name": "Mei", "introduction": invalid}]}) is None


def test_family_tree_and_author_timeline_are_distinct_skill_markers_with_one_document_contract():
    tree_marker = (
        "[[MEMORY_SPARK_FAMILY_TREE]]"
        '{"people":[{"id":"p-me","name":"Avery"}],"relationships":[]}'
        "[[/MEMORY_SPARK_FAMILY_TREE]]"
    )
    timeline_marker = (
        "[[MEMORY_SPARK_AUTHOR_TIMELINE]]"
        '{"timeline":[{"id":"e-school","title":"Started school",'
        '"date_expression":"around 1964","precision":"approximate",'
        '"person_ids":["person_existing"]}],"life_periods":[]}'
        "[[/MEMORY_SPARK_AUTHOR_TIMELINE]]"
    )

    visible, updates = extract_family_skill_updates(f"Reply. {tree_marker} {timeline_marker}")
    combined, skills = combine_family_skill_updates(updates)

    assert visible == "Reply."
    assert skills == ["family_tree", "author_timeline"]
    assert combined["people"] == [{"id": "p-me", "name": "Avery"}]
    assert combined["timeline"][0]["person_ids"] == ["person_existing"]
    assert extract_family_tree_context(tree_marker)[1]["timeline"] == []
    assert extract_author_timeline_context(timeline_marker)[1]["people"] == []


def test_each_skill_rejects_the_other_domain_and_timeline_can_link_to_saved_people():
    assert validate_family_tree_context({"timeline": [{"id": "e1", "title": "School"}]}) is None
    assert validate_author_timeline_context({"people": [{"id": "p1", "name": "Avery"}]}) is None
    assert validate_author_timeline_context(
        {"timeline": [{"id": "e1", "title": "School", "person_ids": ["person_existing"]}]}
    ) is not None


def test_extracts_a_valid_family_context_and_keeps_uncertain_dates():
    visible, context = extract_family_context(
        "That sounds like an important thread to keep.\n"
        "[[MEMORY_SPARK_FAMILY_CONTEXT]]"
        '{"people":[{"id":"p-mum","name":"Mei","family_title":"mother",'
        '"living_status":"unknown"},{"id":"p-me","name":"Avery"}],'
        '"relationships":[{"from_person_id":"p-mum","to_person_id":"p-me",'
        '"relationship_type":"parent","direction":"directed"}],'
        '"timeline":[{"id":"e-school","title":"Started school",'
        '"date_expression":"around 1964","precision":"approximate",'
        '"place":"Hobart","person_ids":["p-me"]}],'
        '"life_periods":[{"id":"period-childhood","title":"Childhood summers",'
        '"start_expression":"the late 1950s","end_expression":"around 1965",'
        '"precision":"range","person_ids":["p-me"]}]} '
        "[[/MEMORY_SPARK_FAMILY_CONTEXT]]"
    )

    assert visible == "That sounds like an important thread to keep."
    assert context == {
        "people": [
            {"id": "p-mum", "name": "Mei", "family_title": "mother", "living_status": "unknown"},
            {"id": "p-me", "name": "Avery"},
        ],
        "relationships": [
            {
                "from_person_id": "p-mum",
                "to_person_id": "p-me",
                "relationship_type": "parent",
                "direction": "directed",
            }
        ],
        "timeline": [
            {
                "id": "e-school",
                "title": "Started school",
                "kind": "event",
                "date_expression": "around 1964",
                "precision": "approximate",
                "place": "Hobart",
                "person_ids": ["p-me"],
            },
            {
                "id": "period-childhood",
                "title": "Childhood summers",
                "kind": "period",
                "start_expression": "the late 1950s",
                "end_expression": "around 1965",
                "precision": "range",
                "person_ids": ["p-me"],
            }
        ],
    }


def test_invalid_graph_is_rejected_without_returning_partial_data():
    assert validate_family_context(
        {
            "people": [{"id": "p1", "name": "Avery"}],
            "relationships": [
                {
                    "from_person_id": "p1",
                    "to_person_id": "missing",
                    "relationship_type": "parent",
                }
            ],
        }
    ) is None


def test_unknown_keys_and_oversized_markers_are_rejected():
    assert validate_family_context({"people": [{"id": "p1", "name": "Avery"}], "debug": True}) is None

    oversized = (
        "A memory. "
        "[[MEMORY_SPARK_FAMILY_CONTEXT]]"
        + (" " * 20_001)
        + "[[/MEMORY_SPARK_FAMILY_CONTEXT]]"
    )
    visible, context = extract_family_context(oversized)
    assert visible == "A memory."
    assert context is None


def test_family_feature_requires_paid_family_entitlement_and_configured_price():
    entitlement = {
        "status": "paid",
        "plan_key": "family_memoir_v1",
        "family_tree": True,
        "timeline": True,
        "stripe_price_id": "price_family_live",
    }

    assert family_features_enabled(entitlement, "price_family_live") is True
    assert family_features_enabled({**entitlement, "status": "revoked"}, "price_family_live") is False
    assert family_features_enabled({**entitlement, "stripe_price_id": "price_printed"}, "price_family_live") is False
    assert family_features_enabled({**entitlement, "plan_key": "printed_memoir_v1"}, "price_family_live") is False


def test_unterminated_family_marker_is_removed_and_does_not_activate_context():
    visible, context = extract_family_context(
        "I remember my aunt. [[MEMORY_SPARK_FAMILY_CONTEXT]]{\"people\":[]}"
    )

    assert visible == "I remember my aunt."
    assert context is None


def test_multiple_family_markers_are_all_removed_from_visible_reply():
    marker = (
        "[[MEMORY_SPARK_FAMILY_CONTEXT]]"
        '{"people":[{"id":"p1","name":"Avery"}]}'
        "[[/MEMORY_SPARK_FAMILY_CONTEXT]]"
    )

    visible, context = extract_family_context(f"Reply. {marker} {marker}")

    assert visible == "Reply."
    assert context == {"people": [{"id": "p1", "name": "Avery"}], "relationships": [], "timeline": []}


def test_persisted_document_assigns_canonical_ids_and_reports_changes():
    update = validate_family_context({
        "people": [
            {"id": "p-mum", "name": "Mei", "family_title": "mother"},
            {"id": "p-me", "name": "Avery"},
        ],
        "relationships": [{
            "from_person_id": "p-mum",
            "to_person_id": "p-me",
            "relationship_type": "parent",
        }],
        "timeline": [{
            "id": "e-school",
            "title": "Started school",
            "date_expression": "around 1964",
            "precision": "approximate",
            "person_ids": ["p-me"],
        }],
        "life_periods": [],
    })

    document, summary = merge_family_context_document(
        empty_family_context_document("project-family"), update, "project-family"
    )

    assert summary["changed"] is True
    assert summary["revision"] == 1
    assert summary["added"] == {"people": 2, "relationships": 1, "timeline": 1}
    assert document["schema_version"] == 2
    assert document["project_id"] == "project-family"
    assert document["people"][0]["id"].startswith("person_")
    assert document["relationships"][0]["from_person_id"] == document["people"][0]["id"]
    assert document["timeline"][0]["person_ids"] == [document["people"][1]["id"]]


def test_persisted_document_revises_only_explicit_existing_ids_and_retries_idempotently():
    first = validate_family_context({"people": [{"id": "p1", "name": "Avery"}]})
    document, first_summary = merge_family_context_document(
        None, first, "project-family"
    )
    canonical_id = document["people"][0]["id"]
    revision_one = document["revision"]

    revision = validate_family_context({
        "people": [{"id": "p1-again", "existing_id": canonical_id, "name": "Avery Chen"}]
    })
    revised, revised_summary = merge_family_context_document(document, revision, "project-family")
    retried, retry_summary = merge_family_context_document(document, revision, "project-family")

    assert first_summary["changed"] is True
    assert revised["people"] == [{"id": canonical_id, "name": "Avery Chen"}]
    assert revised["revision"] == revision_one + 1
    assert revised_summary["updated"]["people"] == 1
    assert retried == revised
    assert retry_summary == revised_summary


def test_repeated_unique_person_name_is_idempotent_without_existing_id():
    first = validate_family_tree_context({
        "people": [{"id": "friend", "name": "阿青", "family_title": "childhood friend"}]
    })
    document, first_summary = merge_family_context_document(None, first, "project-family")

    repeated = validate_family_tree_context({
        "people": [{"id": "friend-again", "name": "阿青"}]
    })
    merged, repeated_summary = merge_family_context_document(document, repeated, "project-family")

    assert first_summary["added"]["people"] == 1
    assert repeated_summary["changed"] is False
    assert repeated_summary["added"]["people"] == 0
    assert len(merged["people"]) == 1
    assert merged["people"][0]["id"] == document["people"][0]["id"]


def test_unified_timeline_persists_both_kinds_in_calendar_order_without_inventing_dates():
    update = validate_author_timeline_context({"timeline": [
        {"id": "return", "kind": "event", "title": "Returned", "date_expression": "2018年"},
        {"id": "work", "kind": "period", "title": "Carpentry", "start_expression": "1986年",
         "end_expression": "2005年", "place": "承德市", "visibility": "private", "include_in_print": False},
        {"id": "visit", "kind": "event", "title": "Visited grandmother", "date_expression": "1958年暑假"},
        {"id": "play", "kind": "event", "title": "Playing", "date_expression": "童年", "precision": "age"},
        {"id": "school", "kind": "period", "title": "School", "start_expression": "around 1960"},
    ]})
    document, summary = merge_family_context_document(None, update, "project-family")
    assert "life_periods" not in document
    assert [item["title"] for item in document["timeline"]] == [
        "Visited grandmother", "School", "Carpentry", "Returned", "Playing"]
    assert document["timeline"][0]["date_expression"] == "1958年暑假"
    assert "end_expression" not in document["timeline"][1]
    work = document["timeline"][2]
    assert (work["start_expression"], work["end_expression"], work["place"],
            work["visibility"], work["include_in_print"]) == ("1986年", "2005年", "承德市", "private", False)
    assert summary["added"]["timeline"] == 5
    retried, retry_summary = merge_family_context_document(document, update, "project-family")
    assert retried == document
    assert retry_summary["changed"] is False


def test_legacy_document_migration_preserves_ids_links_privacy_and_revision():
    old = {"schema_version": 1, "project_id": "project-family", "revision": 4,
           "updated_at": "2026-10-01T00:00:00Z", "source_sequence": 12,
           "people": [{"id": "p1", "name": "Avery"}], "relationships": [],
           "timeline": [{"id": "e1", "title": "Visit", "date_expression": "1958年暑假"}],
           "life_periods": [{"id": "period1", "title": "School", "start_expression": "when young",
                             "person_ids": ["p1"], "visibility": "private", "include_in_print": False}]}
    original = copy.deepcopy(old)
    migrated = normalise_family_context_document(old)
    assert migrated["schema_version"] == 2
    assert "life_periods" not in migrated
    assert migrated["revision"] == 4 and migrated["source_sequence"] == 12
    assert migrated["timeline"] == [
        {**old["timeline"][0], "kind": "event"}, {**old["life_periods"][0], "kind": "period"}]
    assert normalise_family_context_document(migrated) == migrated
    assert old == original
    correction = validate_author_timeline_context({"timeline": [
        {"id": "correction", "existing_id": "period1", "kind": "period", "title": "Primary school",
         "start_expression": "around 1960"}]})
    revised, summary = merge_family_context_document(old, correction, "project-family")
    assert len(revised["timeline"]) == 2
    assert revised["timeline"][1]["id"] == "period1"
    assert revised["timeline"][1]["person_ids"] == ["p1"]
    assert summary["updated"]["timeline"] == 1
    assert revised["revision"] == 5


def test_replaying_a_v1_marker_keeps_its_original_deterministic_ids():
    marker = {"people": [], "relationships": [],
              "timeline": [{"id": "e1", "title": "Visit", "date_expression": "1958年暑假"}],
              "life_periods": [{"id": "p1", "title": "Work", "start_expression": "1986", "end_expression": "2005"}]}
    def digest(value):
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":")).encode()).hexdigest()
    update_hash = digest(marker)
    old = {"schema_version": 1, "project_id": "project-family", "revision": 1,
           "people": [], "relationships": [],
           "timeline": [{**marker["timeline"][0], "id": f"timeline_{update_hash[:16]}_{digest('e1')[:8]}"}],
           "life_periods": [{**marker["life_periods"][0], "id": f"period_{update_hash[:16]}_{digest('p1')[:8]}"}]}
    document, summary = merge_family_context_document(old, marker, "project-family")
    assert len(document["timeline"]) == 2
    assert summary["changed"] is False
    assert document["revision"] == 1


def test_new_periods_at_different_places_remain_distinct_without_an_existing_id():
    def update(place):
        return validate_author_timeline_context({"timeline": [
            {"id": "school", "kind": "period", "title": "Primary school",
             "start_expression": "1960", "place": place}]})
    document, _ = merge_family_context_document(None, update("Hobart"), "project-family")
    revised, summary = merge_family_context_document(document, update("Sydney"), "project-family")
    assert len(revised["timeline"]) == 2
    assert {item["place"] for item in revised["timeline"]} == {"Hobart", "Sydney"}
    assert summary["added"]["timeline"] == 1


@pytest.mark.parametrize("items", [
    [{"id": "bad", "kind": "period", "title": "No boundaries"}],
    [{"id": "bad", "kind": "unknown", "title": "Invalid kind"}],
    [{"id": "bad", "kind": "event", "title": "Mixed fields", "start_expression": "1958"}],
    [{"id": "bad", "kind": "period", "title": "Mixed fields", "date_expression": "1958", "start_expression": "1958"}],
    [{"id": "same", "kind": "event", "title": "Visit"},
     {"id": "same", "kind": "period", "title": "Work", "start_expression": "1986"}],
])
def test_unified_timeline_rejects_invalid_kinds_dates_and_colliding_ids(items):
    assert validate_author_timeline_context({"timeline": items}) is None
