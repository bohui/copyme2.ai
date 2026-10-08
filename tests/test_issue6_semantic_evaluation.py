"""Behavioral checks for dataset evaluators; all outputs here are controlled."""
from scripts.issue6_semantic_evaluation import score_events


def test_an_event_citing_words_the_narrator_never_said_fails_evidence_scoring():
    inputs = {
        "sources": [{"id": "s1", "version": 1, "text": "Thanks, let's continue."}],
        "saved_events": [],
    }
    output = {"events": [{
        "kind": "event", "title": "Moved to a new town",
        "source_refs": [{"source_id": "s1", "version": 1,
                         "quote": "I moved to a new town in 1970."}],
    }]}
    scores = score_events(inputs, output, {"events": []})
    assert scores["schema_and_original_evidence"]["value"] == 0
    assert scores["event_count"]["value"] == 0
    assert scores["factual_entailment"]["status"] == "human_review_required"


def test_valid_quotes_do_not_make_a_wrong_life_stage_correct():
    text = "When I was a child, I helped repair a radio."
    ref = {"source_id": "s1", "version": 1, "quote": text}
    inputs = {"sources": [{"id": "s1", "version": 1, "text": text}],
              "saved_events": []}
    event = {"kind": "event", "title": "Repairing a radio",
             "life_stage": "midlife", "source_refs": [ref], "stage_evidence": [ref]}
    expected = {"events": [{"kind": "event", "evidence_anchor": "repair a radio",
                            "life_stage": "childhood"}]}
    scores = score_events(inputs, {"events": [event]}, expected)
    assert scores["schema_and_original_evidence"]["value"] == 1
    assert scores["expected_placement"]["value"] == 0
    event["life_stage"] = "childhood"
    assert score_events(inputs, {"events": [event]}, expected)["expected_placement"]["value"] == 1

def test_a_date_phrase_does_not_match_inside_a_different_numeric_token():
    text = "In 1958, I helped repair a radio marked with serial number 19580."
    ref = {"source_id": "s1", "version": 1, "quote": text}
    inputs = {"sources": [{"id": "s1", "version": 1, "text": text}], "saved_events": []}
    event = {"kind": "event", "title": "Repairing a radio", "life_stage": "unplaced",
             "source_refs": [ref],
             "temporal": {"expression": "19580", "precision": "year",
                          "year_start": 1958, "year_end": 1958, "basis": [ref]}}
    expected = {"events": [{"kind": "event", "evidence_anchor": "repair a radio",
                            "life_stage": "unplaced",
                            "temporal": {"expression": "1958", "precision": "year",
                                         "year_start": 1958, "year_end": 1958}}]}
    assert score_events(inputs, {"events": [event]}, expected)["expected_placement"]["value"] == 0


def test_an_unavailable_model_result_is_not_scored_as_a_pass_or_an_empty_extraction():
    scores = score_events({"sources": [], "saved_events": []}, None, {"events": []})
    assert scores["schema_and_original_evidence"] == {"value": None, "status": "unavailable"}
    assert scores["event_count"] == {"value": None, "status": "unavailable"}


def test_preserved_date_expressions_may_include_surrounding_original_words():
    text = "In my childhood in 1958, I helped repair a radio."
    ref = {"source_id": "s1", "version": 1, "quote": text}
    inputs = {"sources": [{"id": "s1", "version": 1, "text": text}], "saved_events": []}
    event = {"kind": "event", "title": "Repairing a radio", "life_stage": "childhood",
             "source_refs": [ref], "stage_evidence": [ref],
             "temporal": {"expression": "in 1958", "precision": "year",
                          "year_start": 1958, "year_end": 1958, "basis": [ref]}}
    expected = {"events": [{"kind": "event", "evidence_anchor": "repair a radio",
                            "life_stage": "childhood",
                            "temporal": {"expression": "1958", "precision": "year",
                                         "year_start": 1958, "year_end": 1958}}]}
    assert score_events(inputs, {"events": [event]}, expected)["expected_placement"]["value"] == 1

    event["temporal"]["year_start"] = 1959
    assert score_events(inputs, {"events": [event]}, expected)["expected_placement"]["value"] == 0
    event["temporal"]["year_start"] = 1958
    event["temporal"]["precision"] = "approximate"
    assert score_events(inputs, {"events": [event]}, expected)["expected_placement"]["value"] == 0
