"""Behavioral checks for dataset evaluators; all outputs here are controlled."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from apps.api.memory_events import validate_extraction
from scripts.issue6_semantic_evaluation import score_events


def dataset_case(case_id):
    fixture = Path(__file__).parent / "evaluation/issue6_semantic_datasets.json"
    datasets = json.loads(fixture.read_text())["datasets"]
    return next(item for dataset in datasets for item in dataset["items"]
                if item["case_id"] == case_id)


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


@pytest.mark.parametrize("locale,narrow_quote,stage_quote,expressions", [
    ("en-AU", "I worked a summer at the station kiosk.", "As a young adult", ("1974", "1976")),
    ("zh-CN", "我在车站的小亭子里做了一份暑期工作。", "青年时期", ("1974年", "1976年")),
])
def test_timing_anchors_can_be_cited_separately_from_event_evidence(locale, narrow_quote, stage_quote, expressions):
    case = dataset_case("grounding.recurring-events." + locale)
    events = []
    for source, expression, year in zip(case["input"]["sources"], expressions, (1974, 1976)):
        full_ref = {"source_id": source["id"], "version": 1, "quote": source["text"]}
        ref = {**full_ref, "quote": narrow_quote} if year == 1974 else full_ref
        events.append({"kind": "event", "title": "Summer job", "life_stage": "young_adulthood",
                       "source_refs": [ref], "stage_evidence": [full_ref],
                       "temporal": {"expression": expression, "precision": "year",
                                    "year_start": year, "year_end": year, "basis": [full_ref]}})
    assert len(validate_extraction({"events": events}, case["input"]["sources"], [])) == 2
    scores = score_events(case["input"], {"events": events}, case["expected_output"])
    assert scores["expected_placement"]["value"] == 1
    assert scores["factual_entailment"]["status"] == "human_review_required"

    # A date anchor may be present only in timing basis or only in the broader
    # stage citation, while the event's own quote stays narrow.
    full_ref = events[0]["stage_evidence"][0]
    events[0]["stage_evidence"] = [{**full_ref, "quote": stage_quote}]
    assert score_events(case["input"], {"events": events}, case["expected_output"])["expected_placement"]["value"] == 1
    events[0]["stage_evidence"] = [full_ref]
    events[0]["temporal"]["basis"] = [{**full_ref, "quote": expressions[0]}]
    assert score_events(case["input"], {"events": events}, case["expected_output"])["expected_placement"]["value"] == 1

    duplicate = {"events": [events[0], deepcopy(events[0])]}
    assert score_events(case["input"], duplicate, case["expected_output"])["expected_placement"]["value"] == 0


@pytest.mark.parametrize("locale,expression,uncertainty", [
    ("en-AU", "age 12", "Birth year alone leaves the calendar year as 1958 or 1959."),
    ("zh-CN", "十二岁", "只有出生年份，无法确定当时是1958年还是1959年。"),
])
def test_age_with_birth_year_retains_calendar_year_uncertainty(locale, expression, uncertainty):
    case = dataset_case("placement.age-with-birth-evidence." + locale)
    source = case["input"]["sources"][0]
    birth = case["input"]["context_sources"][0]
    ref = {"source_id": source["id"], "version": 1, "quote": source["text"]}
    birth_ref = {"source_id": birth["id"], "version": 1, "quote": birth["text"]}
    event = {"kind": "event", "title": "Repairing a radio", "life_stage": "childhood",
             "source_refs": [ref], "stage_evidence": [ref], "uncertainty": uncertainty,
             "temporal": {"expression": expression, "precision": "age",
                          "year_start": 1958, "year_end": 1959, "basis": [ref, birth_ref]}}
    sources = [birth, source]
    assert len(validate_extraction({"events": [event]}, sources, [])) == 1
    scores = score_events(case["input"], {"events": [event]}, case["expected_output"])
    assert scores["expected_placement"]["value"] == 1
    assert scores["factual_entailment"]["status"] == "human_review_required"

    unjustified_year = deepcopy(event)
    unjustified_year["temporal"]["year_end"] = 1958
    assert score_events(case["input"], {"events": [unjustified_year]}, case["expected_output"])["expected_placement"]["value"] == 0
    no_uncertainty = deepcopy(event)
    del no_uncertainty["uncertainty"]
    assert score_events(case["input"], {"events": [no_uncertainty]}, case["expected_output"])["expected_placement"]["value"] == 0

    no_birth = dataset_case("placement.age-without-birth-evidence." + locale)
    # The same inferred years cannot be carried over when no birth testimony
    # exists; a sourced age may still be retained without calendar years.
    ref["quote"] = no_birth["input"]["sources"][0]["text"]
    event["temporal"]["basis"] = [ref]
    assert score_events(no_birth["input"], {"events": [event]}, no_birth["expected_output"])["expected_placement"]["value"] == 0
    event["temporal"]["year_start"] = None
    event["temporal"]["year_end"] = None
    assert score_events(no_birth["input"], {"events": [event]}, no_birth["expected_output"])["expected_placement"]["value"] == 1


@pytest.mark.parametrize("locale,expression", [
    ("en-AU", "1972"), ("en-AU", "1982"),
    ("zh-CN", "1972年"), ("zh-CN", "1982年"),
])
def test_a_period_may_preserve_one_original_date_anchor(locale, expression):
    case = dataset_case("placement.interval." + locale)
    source = case["input"]["sources"][0]
    ref = {"source_id": source["id"], "version": 1, "quote": source["text"]}
    event = {"kind": "period", "title": "Managing a workshop", "life_stage": "midlife",
             "source_refs": [ref], "stage_evidence": [ref],
             "temporal": {"expression": expression, "precision": "range",
                          "year_start": 1972, "year_end": 1982, "basis": [ref]}}
    assert len(validate_extraction({"events": [event]}, case["input"]["sources"], [])) == 1
    assert score_events(case["input"], {"events": [event]}, case["expected_output"])["expected_placement"]["value"] == 1

    for field, wrong_value in (("year_start", 1973), ("year_end", 1983),
                               ("precision", "year"), ("expression", "unknown"),
                               ("expression", "1972–1982")):
        wrong = deepcopy(event)
        wrong["temporal"][field] = wrong_value
        assert score_events(case["input"], {"events": [wrong]}, case["expected_output"])["expected_placement"]["value"] == 0
    forged = deepcopy(event)
    forged["temporal"]["basis"][0]["quote"] = "A manufactured date basis."
    assert score_events(case["input"], {"events": [forged]}, case["expected_output"])["expected_placement"]["value"] == 0


@pytest.mark.parametrize("locale,expression,veto", [
    ("en-AU", "3 June 1988", " Do not include this event in my timeline."),
    ("zh-CN", "1988年6月3日", "不要将这件事记录到我的时间线里。"),
])
def test_recording_vetoed_proposals_cannot_earn_placement_credit(locale, expression, veto):
    case = dataset_case("placement.exact-date." + locale)
    source = case["input"]["sources"][0]
    original = source["text"]
    source["text"] += veto
    case["input"]["sources"].append({**source, "id": "s2", "text": original})
    ref = {"source_id": "s1", "version": 1, "quote": original}
    blocked = {"kind": "event", "title": "School painting contest", "life_stage": "childhood",
               "source_refs": [ref], "stage_evidence": [ref],
               "temporal": {"expression": expression, "precision": "day",
                            "year_start": 1988, "year_end": 1988, "basis": [ref]}}
    assert validate_extraction({"events": [blocked]}, case["input"]["sources"], []) == []
    scores = score_events(case["input"], {"events": [blocked]}, case["expected_output"])
    assert scores["event_count"]["value"] == 0
    assert scores["expected_placement"]["value"] == 0
    assert scores["factual_entailment"]["status"] == "human_review_required"

    allowed = deepcopy(blocked)
    for ref in [*allowed["source_refs"], *allowed["stage_evidence"], *allowed["temporal"]["basis"]]:
        ref["source_id"] = "s2"
    mixed = {"events": [blocked, allowed]}
    retained = validate_extraction(mixed, case["input"]["sources"], [])
    assert len(retained) == 1
    assert retained[0]["source_refs"][0]["source_id"] == "s2"
    scores = score_events(case["input"], mixed, case["expected_output"])
    assert scores["event_count"]["value"] == 1
    assert scores["expected_placement"]["value"] == 1
