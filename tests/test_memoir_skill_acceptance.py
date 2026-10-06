"""Offline evaluator regressions for issue #13; no provider or judge calls."""
from copy import deepcopy

import pytest

from scripts.memoir_five_case_evaluator import (
    SKILLS,
    aggregate_case,
    build_langfuse_round_scores,
    evaluate_round,
    merge_ui_skill_observations,
)


# This focused contract is separate from the immutable five-case fixtures.
CASE = {"id": "optional-skill-probe", "family_enabled": {"default": True}}
RESULT = {"reply": "A grounded reply.", "trace": [{"skill": "memoir-memory-context"}]}


@pytest.mark.parametrize("observation", [None, {"status": "unavailable"}, {"status": "blocked"}])
def test_optional_skill_evidence_does_not_block_a_round(observation):
    grade = evaluate_round(
        {}, CASE, 1, RESULT, execution_mode="live",
        ui_observations={skill: observation for skill in ("memoir-place-groups", "place-photo-research")},
        composer_observation=observation,
    )
    for skill in SKILLS[1:]:
        assert grade["skill_grades"][skill]["status"] == "not_applicable"
    assert grade["overall"] == "pass"


def test_optional_passes_do_not_inflate_contract_rates():
    grades = []
    for number, contract in enumerate(("required", "must_not_call", "not_applicable"), start=1):
        grades.append({
            "round": number,
            "expected": {"skill_status": {skill: contract for skill in SKILLS}},
            # Be robust to older captured reports that recorded optional passes.
            "skill_grades": {skill: {"status": "pass", "invocation": "pass", "output": "pass"} for skill in SKILLS},
            "overall": "pass",
        })
    summary = aggregate_case("optional-skill-probe", grades, execution_mode="live")
    for coverage in summary["skill_coverage"].values():
        assert coverage["contract_rounds"] == 2
        assert coverage["invocation_pass"] == 2
        assert coverage["output_pass"] == 2
        assert coverage["invocation_rate"] == 1.0
        assert coverage["output_rate"] == 1.0


def _required_ui_grade():
    case = {**CASE, "place_rounds": {"1": ["Hobart"]}}
    result = {**RESULT, "trace": [*RESULT["trace"], {"skill": "memoir-place-journey"}], "place_journeys": [{"place": "Hobart"}]}
    grade = evaluate_round({}, case, 1, result, execution_mode="live")
    return case, grade


@pytest.mark.parametrize("execution_mode, expected_status", [("live", "pass"), ("fixture", "mock_only")])
def test_browser_receipt_recomputes_round_status(execution_mode, expected_status):
    case, grade = _required_ui_grade()
    assert grade["overall"] == "unavailable"
    merged = merge_ui_skill_observations(
        [grade], {1: {"memoir-place-groups": {"executed": True, "called": True, "output_ok": True}}},
        {}, case, execution_mode=execution_mode,
    )
    assert merged[0]["overall"] == expected_status


def test_unavailable_browser_receipt_invalidates_previous_protocol_pass():
    case, grade = _required_ui_grade()
    grade["overall"] = "pass"
    grade["skill_grades"]["memoir-place-groups"] = {"status": "pass", "invocation": "pass", "output": "pass"}
    merged = merge_ui_skill_observations(
        [grade], {1: {"memoir-place-groups": {"status": "unavailable", "comment": "Browser receipt is missing."}}},
        {}, case, execution_mode="live",
    )
    assert merged[0]["overall"] == "unavailable"


@pytest.mark.parametrize("remaining_gap", ["state_failure", "provider_unavailable", "state_unavailable"])
def test_browser_receipt_cannot_clear_other_failures_or_provider_gaps(remaining_gap):
    case, grade = _required_ui_grade()
    grade = deepcopy(grade)
    if remaining_gap == "state_failure":
        grade["state_checks"]["visible_markers_stripped"]["status"] = "fail"
        grade["overall"] = "fail"
    elif remaining_gap == "provider_unavailable":
        grade["evidence_status"] = "unavailable"
    else:
        grade["state_checks"]["visible_markers_stripped"]["status"] = "unavailable"
    merged = merge_ui_skill_observations(
        [grade], {1: {"memoir-place-groups": {"executed": True, "called": True, "output_ok": True}}},
        {}, case, execution_mode="live",
    )
    assert merged[0]["overall"] == ("fail" if remaining_gap == "state_failure" else "unavailable")


def _receipt_grade(skill, contract, receipt, *, entrypoint="evaluate", mode="live"):
    case = {**CASE}
    result = deepcopy(RESULT)
    if contract == "required":
        if skill == "memoir-place-groups":
            case["place_rounds"] = {"1": ["Hobart"]}
            result["trace"].append({"skill": "memoir-place-journey"})
            result["place_journeys"] = [{"place": "Hobart"}]
        elif skill == "place-photo-research":
            case["photo_rounds"] = {"1": "current_day"}
        else:
            case["composer_rounds"] = {"1": "review_only"}
    elif contract == "must_not_call":
        case["negative_rounds"] = [1]
    if entrypoint == "merge":
        prior = evaluate_round({}, case, 1, result, execution_mode=mode)
        return merge_ui_skill_observations([prior], {1: {skill: receipt}}, {}, case, execution_mode=mode)[0]
    observations = {"composer_observation": receipt} if skill == "memoir-composer" else {"ui_observations": {skill: receipt}}
    return evaluate_round({}, case, 1, result, execution_mode=mode, **observations)


@pytest.mark.parametrize("skill,entrypoint", [
    ("memoir-place-groups", "evaluate"), ("memoir-place-groups", "merge"),
    ("place-photo-research", "evaluate"), ("place-photo-research", "merge"),
    ("memoir-composer", "evaluate"),
])
@pytest.mark.parametrize("contract", ["required", "must_not_call"])
@pytest.mark.parametrize("status", ["not_run", "unknown", "mock_only", None, "running", {"invalid": True}])
def test_explicit_nonlive_receipt_status_cannot_certify_live_success(skill, entrypoint, contract, status):
    called = contract == "required"
    receipt = {"status": status, "executed": True, "called": called, "invoked": called, "output_ok": True}
    grade = _receipt_grade(skill, contract, receipt, entrypoint=entrypoint)
    assert grade["skill_grades"][skill]["status"] in {"unavailable", "not_run"}
    assert grade["overall"] == "unavailable"
    scores = build_langfuse_round_scores(grade)
    assert not any(score["name"].startswith(f"skill.{skill}.") for score in scores)


@pytest.mark.parametrize("skill", ["memoir-place-groups", "place-photo-research", "memoir-composer"])
@pytest.mark.parametrize("contract", ["required", "must_not_call", "not_applicable"])
@pytest.mark.parametrize("status", ["not_run", "unknown", "mock_only"])
def test_explicit_receipt_failures_and_optional_semantics_remain_separate(skill, contract, status):
    receipt = {"status": status, "executed": True, "called": True, "invoked": True, "output_ok": True}
    grade = _receipt_grade(skill, contract, receipt)
    if contract == "not_applicable":
        assert grade["skill_grades"][skill]["status"] == "not_applicable"
        assert grade["overall"] == "pass"
    else:
        assert grade["skill_grades"][skill]["status"] in {"unavailable", "not_run"}


@pytest.mark.parametrize("skill", ["memoir-place-groups", "place-photo-research", "memoir-composer"])
@pytest.mark.parametrize("contract", ["required", "must_not_call"])
@pytest.mark.parametrize("receipt_status,mode,expected", [("omitted", "live", "pass"), ("pass", "live", "pass"), ("mock_only", "fixture", "mock_only"), ("fail", "live", "fail")])
def test_valid_legacy_and_terminal_receipt_statuses_keep_their_meaning(skill, contract, receipt_status, mode, expected):
    called = contract == "required"
    receipt = {"executed": True, "called": called, "invoked": called, "output_ok": True}
    if receipt_status != "omitted":
        receipt["status"] = receipt_status
    grade = _receipt_grade(skill, contract, receipt, mode=mode)
    assert grade["skill_grades"][skill]["status"] == expected
    assert grade["skill_grades"][skill]["invocation"] == "pass"
    assert grade["overall"] == expected
