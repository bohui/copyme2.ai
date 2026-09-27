from apps.api.family_context import (
    combine_family_skill_updates,
    empty_family_context_document,
    extract_author_timeline_context,
    extract_family_context,
    extract_family_skill_updates,
    extract_family_tree_context,
    family_features_enabled,
    merge_family_context_document,
    validate_author_timeline_context,
    validate_family_tree_context,
    validate_family_context,
)


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
                "date_expression": "around 1964",
                "precision": "approximate",
                "place": "Hobart",
                "person_ids": ["p-me"],
            }
        ],
        "life_periods": [
            {
                "id": "period-childhood",
                "title": "Childhood summers",
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
    assert context == {"people": [{"id": "p1", "name": "Avery"}], "relationships": [], "timeline": [], "life_periods": []}


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
    assert summary["added"] == {"people": 2, "relationships": 1, "timeline": 1, "life_periods": 0}
    assert document["schema_version"] == 1
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
