import json
import inspect
from pathlib import Path

from scripts.memoir_five_case_evaluator import (
    SKILLS,
    aggregate_case,
    evaluate_round,
    expected_round,
    load_json,
    validate_expected,
    validate_inputs,
)
from scripts.run_memoir_five_case_evaluation import FixtureWorker, _fixture_places, _has_timeline_cue


ROOT = Path(__file__).resolve().parents[1]
INPUTS = load_json(ROOT / "tests/evaluation/memoir_five_case_inputs.json")
EXPECTED = load_json(ROOT / "tests/evaluation/memoir_five_case_expected.json")
ORACLE_CORRECTIONS = load_json(ROOT / "tests/evaluation/memoir_five_case_oracle_corrections.json")


def test_checked_in_five_case_fixture_is_exactly_250_rounds_and_covers_the_contract():
    assert validate_inputs(INPUTS) == []
    assert validate_expected(EXPECTED, {case["id"] for case in INPUTS["cases"]}) == []
    assert sum(len(case["rounds"]) for case in INPUTS["cases"]) == 250
    assert tuple(EXPECTED["skills"]) == SKILLS


def test_round_contract_marks_negative_rounds_as_must_not_call():
    case_expected = next(item for item in EXPECTED["case_expectations"] if item["id"] == "harbour-copper-notebook")
    round_expected = expected_round(EXPECTED, case_expected, 47)
    assert round_expected["skill_status"]["place-photo-research"] == "must_not_call"
    assert round_expected["skill_status"]["memoir-place-journey"] == "must_not_call"
    assert round_expected["skill_status"]["memoir-composer"] == "must_not_call"


def test_round_contract_does_not_turn_unasserted_optional_behavior_into_a_negative():
    case_expected = next(item for item in EXPECTED["case_expectations"] if item["id"] == "harbour-copper-notebook")
    round_expected = expected_round(EXPECTED, case_expected, 2)
    assert round_expected["skill_status"]["memoir-author-timeline"] == "not_applicable"
    assert round_expected["skill_status"]["memoir-place-journey"] == "not_applicable"


def test_stage_contract_uses_sparse_case_anchors_not_global_bands():
    case_expected = next(item for item in EXPECTED["case_expectations"] if item["id"] == "chengdu-tea-ledger")
    assert expected_round(EXPECTED, case_expected, 1)["life_stage"] == "baby"
    assert expected_round(EXPECTED, case_expected, 3)["life_stage"] is None
    assert expected_round(EXPECTED, case_expected, 4)["life_stage"] == "toddler"


def test_round_thirty_boundary_oracle_matches_its_band_without_changing_runtime_schema():
    correction = ORACLE_CORRECTIONS["corrections"][0]
    assert ORACLE_CORRECTIONS["change_scope"] == "evaluator_oracle_only"
    assert ORACLE_CORRECTIONS["runtime_schema_changed"] is False
    assert ORACLE_CORRECTIONS["baseline_artifacts_overwritten"] is False
    assert correction["previous_expected_stage"] == "midlife"
    assert correction["corrected_expected_stage"] == "young_adulthood"
    assert EXPECTED["stage_bands"]["young_adulthood"] == [23, 30]
    harbour = next(item for item in EXPECTED["case_expectations"] if item["id"] == "harbour-copper-notebook")
    assert harbour["stage_rounds"]["30"] == "young_adulthood"
    assert expected_round(EXPECTED, harbour, 30)["life_stage"] == "young_adulthood"
    explicit_midlife_cases = {
        "chengdu-tea-ledger",
        "perth-workshop-compass",
        "kunming-garden-lanterns",
        "sydney-platform-letters",
    }
    for case_expected in EXPECTED["case_expectations"]:
        if case_expected["id"] in explicit_midlife_cases:
            assert case_expected["stage_rounds"]["30"] == "midlife"


def test_evaluator_does_not_treat_persisted_later_life_context_as_a_new_review_stage():
    case_expected = next(item for item in EXPECTED["case_expectations"] if item["id"] == "harbour-copper-notebook")
    result = {
        "reply": "A grounded reply.",
        "trace": [{"skill": "memoir-memory-context"}],
        "state": {"profile": {"story_focus": {"life_stage": "later_life"}}},
    }
    grade = evaluate_round(EXPECTED, case_expected, 48, result, execution_mode="fixture",
                           ui_observations={skill: {"executed": True, "called": False, "output_ok": True} for skill in ("memoir-place-groups", "place-photo-research")})
    assert grade["state_checks"]["life_stage"]["status"] == "not_applicable"
    assert grade["skill_grades"]["memoir-memory-context"]["output"] == "pass"


def test_aggregate_separates_required_and_negative_contract_rounds():
    case_expected = next(item for item in EXPECTED["case_expectations"] if item["id"] == "harbour-copper-notebook")
    grades = []
    for number in range(1, 51):
        expected = expected_round(EXPECTED, case_expected, number)
        grades.append({"round": number, "expected": expected, "skill_grades": {skill: {"status": "mock_only", "invocation": "pass", "output": "pass"} for skill in SKILLS}, "state_checks": {"life_stage": {"actual": expected.get("life_stage")}} , "overall": "mock_only"})
    summary = aggregate_case("harbour-copper-notebook", grades, execution_mode="fixture")
    coverage = summary["skill_coverage"]["memoir-place-journey"]
    assert coverage["required_rounds"] == 16
    assert coverage["must_not_call_rounds"] == 9
    assert coverage["contract_rounds"] == 25
    assert coverage["required_invocation_pass"] == 16
    assert coverage["must_not_call_invocation_pass"] == 9


def test_fixture_worker_has_no_expected_or_truth_constructor_inputs():
    parameters = inspect.signature(FixtureWorker).parameters
    assert list(parameters) == ["case"]
    worker = FixtureWorker({"id": "synthetic-only"})
    assert not hasattr(worker, "expected_payload")
    assert not hasattr(worker, "truth")


def test_fixture_contract_heuristics_read_only_current_visible_text():
    assert _fixture_places("I grew up in Hobart and later moved to Launceston.") == ["Hobart", "Launceston"]
    assert _fixture_places("A public historical photo of Hobart around 1978 is only background.") == []
    assert _has_timeline_cue("Around 1982 I moved to Launceston; the date is approximate.")
    assert not _has_timeline_cue("Please keep the private photo undated and do not call it historical evidence.")
