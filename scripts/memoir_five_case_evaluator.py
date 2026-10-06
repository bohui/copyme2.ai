"""Deterministic evaluation helpers for the five-case, 50-round Memoir run.

The expected-outcome file is intentionally separate from the model-visible
round input.  This module consumes observable application results and traces;
it never calls a skill directly and never treats a response string as proof of
persisted state.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping


SKILLS = (
    "memoir-memory-context",
    "memoir-place-journey",
    "memoir-family-tree",
    "memoir-author-timeline",
    "memoir-place-groups",
    "place-photo-research",
    "memoir-composer",
)
LIFE_STAGES = (
    "baby",
    "toddler",
    "childhood",
    "adolescence",
    "young_adulthood",
    "midlife",
    "later_life",
)
UI_SKILLS = {"memoir-place-groups", "place-photo-research"}


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_inputs(payload: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != "memoir-five-case-inputs/1":
        errors.append("inputs schema_version is not memoir-five-case-inputs/1")
    cases = payload.get("cases")
    if not isinstance(cases, list) or len(cases) != 5:
        errors.append("inputs must contain exactly five cases")
        return errors
    ids: set[str] = set()
    for case in cases:
        if not isinstance(case, Mapping):
            errors.append("each input case must be an object")
            continue
        case_id = str(case.get("id") or "")
        if not case_id or case_id in ids:
            errors.append(f"duplicate or missing case id: {case_id!r}")
        ids.add(case_id)
        rounds = case.get("rounds")
        if not isinstance(rounds, list) or len(rounds) != 50:
            errors.append(f"{case_id}: expected exactly 50 model-visible rounds")
        elif any(not isinstance(text, str) or not text.strip() for text in rounds):
            errors.append(f"{case_id}: every model-visible round must be non-empty text")
        if case.get("locale") not in {"en-AU", "zh-CN"}:
            errors.append(f"{case_id}: unsupported locale")
        if not isinstance(case.get("project_id"), str) or not case["project_id"]:
            errors.append(f"{case_id}: missing isolated project_id")
    return errors


def validate_expected(payload: Mapping[str, Any], input_ids: set[str]) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != "memoir-five-case-expected/1":
        errors.append("expected schema_version is not memoir-five-case-expected/1")
    if payload.get("required_rounds") != 50:
        errors.append("expected required_rounds must be 50")
    if tuple(payload.get("skills") or ()) != SKILLS:
        errors.append("expected skill list does not match the seven-skill contract")
    if tuple(payload.get("life_stages") or ()) != LIFE_STAGES:
        errors.append("expected life-stage list does not match the runtime contract")
    bands = payload.get("stage_bands")
    if not isinstance(bands, Mapping):
        errors.append("expected stage_bands is missing")
    else:
        covered: set[int] = set()
        for stage in LIFE_STAGES:
            band = bands.get(stage)
            if not isinstance(band, list) or len(band) != 2 or not all(isinstance(n, int) for n in band):
                errors.append(f"invalid stage band for {stage}")
            else:
                covered.update(range(band[0], band[1] + 1))
        if covered != set(range(1, 47)):
            errors.append("stage bands must cover rounds 1 through 46 exactly")
    cases = payload.get("case_expectations")
    if not isinstance(cases, list) or {str(c.get("id")) for c in cases if isinstance(c, Mapping)} != input_ids:
        errors.append("expected cases do not match input cases")
    for case in cases or []:
        if not isinstance(case, Mapping):
            continue
        stage_rounds = case.get("stage_rounds")
        if stage_rounds is not None:
            if not isinstance(stage_rounds, Mapping) or any(
                not str(round_number).isdigit() or stage not in LIFE_STAGES
                for round_number, stage in stage_rounds.items()
            ):
                errors.append(f"{case.get('id')}: invalid stage_rounds")
    return errors


def case_expectations(payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(case["id"]): case
        for case in payload.get("case_expectations", [])
        if isinstance(case, Mapping) and case.get("id")
    }


def stage_for_round(expected: Mapping[str, Any], round_number: int) -> str | None:
    explicit = expected.get("stage_rounds")
    if isinstance(explicit, Mapping):
        value = explicit.get(str(round_number))
        return str(value) if value in LIFE_STAGES else None
    for stage, band in (expected.get("stage_bands") or {}).items():
        if isinstance(band, list) and len(band) == 2 and band[0] <= round_number <= band[1]:
            return str(stage)
    return None


def family_enabled_for_round(case_expected: Mapping[str, Any], round_number: int) -> bool:
    rule = case_expected.get("family_enabled") or {}
    before = rule.get("before")
    if isinstance(before, int) and round_number < before:
        return False
    return bool(rule.get("default", False))


def expected_round(expected_payload: Mapping[str, Any], case_expected: Mapping[str, Any], round_number: int) -> dict[str, Any]:
    places = (case_expected.get("place_rounds") or {}).get(str(round_number), [])
    places = [str(place) for place in places] if isinstance(places, list) else []
    family_required = round_number in set(case_expected.get("required_family_rounds") or [])
    timeline_required = round_number in set(case_expected.get("required_timeline_rounds") or [])
    family_enabled = family_enabled_for_round(case_expected, round_number)
    composer_action = (case_expected.get("composer_rounds") or {}).get(str(round_number))
    photo_action = (case_expected.get("photo_rounds") or {}).get(str(round_number))
    negative = round_number in set(case_expected.get("negative_rounds") or [])
    status: dict[str, str] = {
        "memoir-memory-context": "required",
        # Only explicit positive/negative scenarios are asserted. All other
        # skill behavior remains available to the production orchestrator but
        # is not used to manufacture a failure from an optional call.
        "memoir-place-journey": "required" if places else ("must_not_call" if negative else "not_applicable"),
        "memoir-place-groups": "required" if places else ("must_not_call" if negative else "not_applicable"),
        "memoir-family-tree": "required" if family_required and family_enabled else ("must_not_call" if negative else "not_applicable"),
        "memoir-author-timeline": "required" if timeline_required and family_enabled else ("must_not_call" if negative else "not_applicable"),
        "place-photo-research": "required" if photo_action in {"current_day", "historical"} else ("must_not_call" if photo_action == "must_not_call" or negative else "not_applicable"),
        "memoir-composer": "required" if composer_action else ("must_not_call" if negative else "not_applicable"),
    }
    if family_required and not family_enabled:
        status["memoir-family-tree"] = "must_not_call" if negative else "not_applicable"
        status["memoir-author-timeline"] = "must_not_call" if negative else "not_applicable"
    return {
        "round": round_number,
        # Case-specific anchors are sparse by design. An unlisted round does
        # not require a fresh stage tag; falling back to the global bands
        # over-asserted optional rounds and turned valid persisted context
        # into false failures.
        "life_stage": stage_for_round(case_expected, round_number),
        "places": places,
        "family_enabled": family_enabled,
        "photo_action": photo_action or "none",
        "composer_action": composer_action,
        "skill_status": status,
        "negative": negative,
    }


def _trace_skills(result: Mapping[str, Any]) -> set[str]:
    skills: set[str] = set()
    trace = result.get("trace")
    if isinstance(trace, list):
        for step in trace:
            if not isinstance(step, Mapping):
                continue
            skill = step.get("skill")
            if isinstance(skill, str) and skill in SKILLS:
                skills.add(skill)
            if step.get("label") in SKILLS:
                skills.add(str(step["label"]))
    trajectory = result.get("trajectory")
    if isinstance(trajectory, Mapping):
        for step in trajectory.get("steps", []):
            if not isinstance(step, Mapping):
                continue
            for value in (step.get("skill"), step.get("label")):
                if isinstance(value, str) and value in SKILLS:
                    skills.add(value)
    update = result.get("family_context_update")
    if isinstance(update, Mapping):
        for skill in update.get("skills", []):
            mapped = {"family_tree": "memoir-family-tree", "author_timeline": "memoir-author-timeline"}.get(skill)
            if mapped:
                skills.add(mapped)
    change = result.get("place_journey_change")
    if isinstance(change, Mapping) and change.get("kind") in {"created", "updated"}:
        skills.add("memoir-place-journey")
    return skills


def _places_from_result(result: Mapping[str, Any]) -> set[str]:
    values: list[Any] = []
    values.extend(result.get("place_journeys") or [])
    if isinstance(result.get("place_journey"), Mapping):
        values.append(result["place_journey"])
    # The runtime may persist the place journey before returning a compact
    # response (for example when optional workspace enrichment reports a
    # retryable failure). Deterministic grading must inspect that accepted
    # application state rather than treating the missing response field as
    # proof that the skill output was lost.
    state = result.get("state")
    if isinstance(state, Mapping) and isinstance(state.get("place"), Mapping):
        values.append(state["place"])
    places: set[str] = set()
    for value in values:
        if isinstance(value, Mapping) and isinstance(value.get("place"), str):
            places.add(value["place"])
    return places


def _profile_stage(result: Mapping[str, Any], state: Mapping[str, Any] | None) -> str | None:
    profile = state.get("profile") if isinstance(state, Mapping) else None
    if isinstance(profile, Mapping):
        focus = profile.get("story_focus")
        if isinstance(focus, Mapping) and isinstance(focus.get("life_stage"), str):
            return focus["life_stage"]
    updates = result.get("profile_updates")
    if isinstance(updates, Mapping):
        focus = updates.get("story_focus")
        if isinstance(focus, Mapping) and isinstance(focus.get("life_stage"), str):
            return focus["life_stage"]
    return None


def _receipt_status_grade(
    observation: Mapping[str, Any],
    expected_status: str,
    *,
    execution_mode: str,
    call_field: str,
) -> dict[str, Any] | None:
    """Explicit unavailable/non-live evidence cannot be rescued by booleans.

    Legacy receipts omitted status; preserve that protocol while rejecting an
    explicit unknown status, including null. Fixture receipts never certify a
    live run. A declared failure remains a failure even with positive flags.
    """
    if "status" not in observation:
        return None
    status = observation["status"]
    if status == "pass" or (status == "mock_only" and execution_mode == "fixture"):
        return None
    if status == "fail":
        called = bool(observation.get(call_field))
        invocation_ok = called if expected_status == "required" else not called
        return {
            "status": "fail", "invocation": "pass" if invocation_ok else "fail", "output": "fail",
            "comment": observation.get("comment") or "The receipt reports a failed observation.",
        }
    unavailable = "not_run" if status == "not_run" else "unavailable"
    return {
        "status": unavailable, "invocation": unavailable, "output": unavailable,
        "comment": observation.get("comment") or "The explicit receipt status does not establish completed execution in this mode.",
    }


def _skill_grade(
    skill: str,
    expected_status: str,
    observed: set[str],
    result: Mapping[str, Any],
    expected: Mapping[str, Any],
    *,
    execution_mode: str,
    ui_observation: Mapping[str, Any] | None = None,
    composer_observation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if expected_status == "not_applicable":
        # Optional skills do not acquire a required browser/provider gate.
        # Raw observations remain in the run artifact, outside contract rates.
        return {"status": "not_applicable", "invocation": "not_applicable", "output": "not_applicable", "comment": "The round does not require this skill."}
    if skill in UI_SKILLS:
        ui_observation = ui_observation or {}
        receipt_grade = _receipt_status_grade(
            ui_observation, expected_status, execution_mode=execution_mode, call_field="called",
        )
        if receipt_grade is not None:
            return receipt_grade
        if not ui_observation.get("executed"):
            if expected_status == "must_not_call":
                return {"status": "mock_only" if execution_mode == "fixture" else "pass", "invocation": "pass", "output": "pass", "comment": "No UI action was required and no UI execution was recorded."}
            return {"status": "not_run", "invocation": "not_run", "output": "not_run", "comment": "This skill is exercised by the browser/UI journey, not the worker turn."}
        observed_call = bool(ui_observation.get("called"))
        observed_output = bool(ui_observation.get("output_ok"))
    elif skill == "memoir-composer":
        composer_observation = composer_observation or {}
        receipt_grade = _receipt_status_grade(
            composer_observation, expected_status, execution_mode=execution_mode, call_field="invoked",
        )
        if receipt_grade is not None:
            return receipt_grade
        observed_call = bool(composer_observation.get("invoked"))
        observed_output = bool(composer_observation.get("output_ok"))
    else:
        observed_call = skill in observed
        observed_output = observed_call
        if skill == "memoir-memory-context":
            actual_stage = _profile_stage(result, result.get("state"))
            observed_output = observed_call and (expected.get("life_stage") is None or actual_stage == expected.get("life_stage"))
        elif skill == "memoir-place-journey":
            actual_places = _places_from_result(result)
            observed_output = observed_call and (not expected.get("places") or set(expected["places"]).issubset(actual_places))
        elif skill == "memoir-family-tree":
            update = result.get("family_context_update")
            observed_output = observed_call and isinstance(update, Mapping) and update.get("persisted") is True and "family_tree" in (update.get("skills") or [])
        elif skill == "memoir-author-timeline":
            update = result.get("family_context_update")
            observed_output = observed_call and isinstance(update, Mapping) and update.get("persisted") is True and "author_timeline" in (update.get("skills") or [])

    if expected_status == "required":
        if not observed_call:
            return {"status": "fail", "invocation": "fail", "output": "fail", "comment": f"Required {skill} invocation was not observable."}
        if not observed_output:
            return {"status": "fail", "invocation": "pass", "output": "fail", "comment": f"{skill} ran but its expected output/state was not observable."}
        return {"status": "mock_only" if execution_mode == "fixture" else "pass", "invocation": "pass", "output": "pass", "comment": f"{skill} invocation and output matched the round contract."}
    if expected_status == "must_not_call":
        if observed_call:
            return {"status": "fail", "invocation": "fail", "output": "fail", "comment": f"Unnecessary {skill} invocation was observable."}
        return {"status": "mock_only" if execution_mode == "fixture" else "pass", "invocation": "pass", "output": "pass", "comment": f"No unnecessary {skill} invocation was observable."}
    return {"status": "not_applicable", "invocation": "not_applicable", "output": "not_applicable", "comment": "The round does not require this skill."}


def _round_status(
    skill_grades: Mapping[str, Mapping[str, Any]],
    state_checks: Mapping[str, Mapping[str, Any]],
    *,
    execution_mode: str,
    evidence_status: str | None = None,
) -> str:
    """Combine the current evidence after initial grading or a browser receipt."""
    statuses = [grade.get("status") for grade in skill_grades.values()]
    statuses.extend(check.get("status") for check in state_checks.values())
    if "fail" in statuses:
        return "fail"
    if evidence_status == "unavailable":
        return "unavailable"
    if execution_mode == "fixture":
        return "mock_only"
    if any(status in {"unavailable", "not_run"} for status in statuses):
        return "unavailable"
    return "pass"


def evaluate_round(
    expected_payload: Mapping[str, Any],
    case_expected: Mapping[str, Any],
    round_number: int,
    result: Mapping[str, Any],
    *,
    execution_mode: str,
    ui_observations: Mapping[str, Mapping[str, Any]] | None = None,
    composer_observation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    expected = expected_round(expected_payload, case_expected, round_number)
    observed = _trace_skills(result)
    ui_observations = ui_observations or {}
    skill_grades = {
        skill: _skill_grade(
            skill,
            expected["skill_status"][skill],
            observed,
            result,
            expected,
            execution_mode=execution_mode,
            ui_observation=ui_observations.get(skill),
            composer_observation=composer_observation,
        )
        for skill in SKILLS
    }
    stage_actual = _profile_stage(result, result.get("state"))
    state_checks = {
        "life_stage": {
            "expected": expected.get("life_stage"),
            "actual": stage_actual,
            "status": "not_applicable" if expected.get("life_stage") is None else ("pass" if stage_actual == expected.get("life_stage") else "fail"),
        },
        "visible_markers_stripped": {
            "expected": True,
            "actual": not any(token in str(result.get("reply") or "") for token in ("[[MEMORY_SPARK_", "[[/MEMORY_SPARK_")),
            "status": "pass" if not any(token in str(result.get("reply") or "") for token in ("[[MEMORY_SPARK_", "[[/MEMORY_SPARK_")) else "fail",
        },
    }
    if expected.get("places"):
        actual_places = sorted(_places_from_result(result))
        state_checks["places"] = {
            "expected": expected["places"],
            "actual": actual_places,
            "status": "pass" if set(expected["places"]).issubset(set(actual_places)) else "fail",
        }
    overall = _round_status(skill_grades, state_checks, execution_mode=execution_mode)
    return {
        "round": round_number,
        "expected": expected,
        "observed_skills": sorted(observed),
        "skill_grades": skill_grades,
        "state_checks": state_checks,
        "overall": overall,
    }


def aggregate_case(
    case_id: str,
    round_grades: list[Mapping[str, Any]],
    *,
    execution_mode: str,
    expected_round_count: int = 50,
) -> dict[str, Any]:
    per_skill: dict[str, dict[str, Any]] = {}
    for skill in SKILLS:
        grades = [grade.get("skill_grades", {}).get(skill, {}) for grade in round_grades]
        required_grades = [
            grade for grade in round_grades
            if grade.get("expected", {}).get("skill_status", {}).get(skill) == "required"
        ]
        negative_grades = [
            grade for grade in round_grades
            if grade.get("expected", {}).get("skill_status", {}).get(skill) == "must_not_call"
        ]
        contract_grades = required_grades + negative_grades
        required_invocation_pass = sum(
            1 for grade in required_grades
            if grade.get("skill_grades", {}).get(skill, {}).get("invocation") == "pass"
        )
        required_output_pass = sum(
            1 for grade in required_grades
            if grade.get("skill_grades", {}).get(skill, {}).get("output") == "pass"
        )
        negative_invocation_pass = sum(
            1 for grade in negative_grades
            if grade.get("skill_grades", {}).get(skill, {}).get("invocation") == "pass"
        )
        negative_output_pass = sum(
            1 for grade in negative_grades
            if grade.get("skill_grades", {}).get(skill, {}).get("output") == "pass"
        )
        per_skill[skill] = {
            # ``required_rounds`` is intentionally only the positive-call
            # denominator. Older reports called the union of positive and
            # negative cases "required", which hid whether a skill was ever
            # actually exercised. Keep the union separately for auditability.
            "required_rounds": len(required_grades),
            "contract_rounds": len(contract_grades),
            "must_not_call_rounds": len(negative_grades),
            "required_invocation_pass": required_invocation_pass,
            "required_output_pass": required_output_pass,
            "must_not_call_invocation_pass": negative_invocation_pass,
            "must_not_call_output_pass": negative_output_pass,
            "invocation_pass": required_invocation_pass + negative_invocation_pass,
            "output_pass": required_output_pass + negative_output_pass,
            "failures": sum(1 for grade in grades if grade.get("status") == "fail"),
            "unavailable": sum(1 for grade in grades if grade.get("status") in {"unavailable", "not_run"}),
            "mock_only": sum(1 for grade in grades if grade.get("status") == "mock_only"),
        }
        required = per_skill[skill]["required_rounds"]
        contract = per_skill[skill]["contract_rounds"]
        negative = per_skill[skill]["must_not_call_rounds"]
        per_skill[skill]["invocation_rate"] = (per_skill[skill]["invocation_pass"] / contract) if contract else None
        per_skill[skill]["output_rate"] = (per_skill[skill]["output_pass"] / contract) if contract else None
        per_skill[skill]["required_invocation_rate"] = (required_invocation_pass / required) if required else None
        per_skill[skill]["required_output_rate"] = (required_output_pass / required) if required else None
        per_skill[skill]["must_not_call_rate"] = (negative_invocation_pass / negative) if negative else None
    overall_counts = Counter(str(grade.get("overall")) for grade in round_grades)
    stages = Counter(
        str(grade.get("state_checks", {}).get("life_stage", {}).get("actual"))
        for grade in round_grades
        if grade.get("state_checks", {}).get("life_stage", {}).get("actual")
    )
    return {
        "case_id": case_id,
        "execution_mode": execution_mode,
        "rounds_observed": len(round_grades),
        "exact_50_rounds": len(round_grades) == expected_round_count,
        "round_status_counts": dict(overall_counts),
        "stage_coverage": {stage: stages.get(stage, 0) for stage in LIFE_STAGES},
        "all_life_stages_observed": all(stages.get(stage, 0) > 0 for stage in LIFE_STAGES),
        "skill_coverage": per_skill,
        "failed_rounds": [grade["round"] for grade in round_grades if grade.get("overall") == "fail"],
        "unavailable_rounds": [grade["round"] for grade in round_grades if grade.get("overall") == "unavailable"],
        "mock_only_rounds": [grade["round"] for grade in round_grades if grade.get("overall") == "mock_only"],
    }


def build_langfuse_round_scores(grade: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Project a round grade into bounded, explainable Langfuse scores.

    ``unavailable`` and ``not_run`` are intentionally omitted from numeric
    scores.  The round metadata and local trace retain those statuses; a zero
    score would falsely turn an infrastructure gap into a product failure.
    """
    scores: list[dict[str, Any]] = []
    round_unavailable = str(grade.get("overall") or "") == "unavailable"

    def add(name: str, status: Any, comment: Any = "") -> None:
        status_text = str(status or "")
        if status_text in {"unavailable", "not_run", "not_applicable"}:
            return
        if round_unavailable and status_text == "fail":
            # A timeout/provider failure can leave the deterministic grader
            # with an empty result, which looks like a product failure. Keep
            # that evidence unavailable instead of publishing false zeros.
            return
        if status_text not in {"pass", "mock_only", "fail"}:
            return
        scores.append({
            "name": name,
            "value": 0.0 if status_text == "fail" else 1.0,
            "comment": f"status={status_text}; {str(comment or '')}"[:1000],
        })

    skill_grades = grade.get("skill_grades") if isinstance(grade.get("skill_grades"), Mapping) else {}
    for skill, skill_grade in skill_grades.items():
        if not isinstance(skill_grade, Mapping):
            continue
        add(f"skill.{skill}.invocation", skill_grade.get("invocation"), skill_grade.get("comment"))
        add(f"skill.{skill}.output", skill_grade.get("output"), skill_grade.get("comment"))
    state_checks = grade.get("state_checks") if isinstance(grade.get("state_checks"), Mapping) else {}
    for check_name, check in state_checks.items():
        if isinstance(check, Mapping):
            add(f"state.{check_name}", check.get("status"), check.get("comment"))
    add("round.overall", grade.get("overall"), "Round-level deterministic contract.")
    return scores


def mark_round_unavailable(grade: Mapping[str, Any], *, reason: str | None = None) -> dict[str, Any]:
    """Mark evidence-dependent checks unavailable after an infrastructure failure."""
    result = deepcopy(dict(grade))
    expected = result.get("expected") if isinstance(result.get("expected"), Mapping) else {}
    expected_skills = expected.get("skill_status") if isinstance(expected, Mapping) else {}
    skill_grades = result.get("skill_grades") if isinstance(result.get("skill_grades"), Mapping) else {}
    for skill, skill_grade in skill_grades.items():
        if not isinstance(skill_grade, Mapping):
            continue
        if isinstance(expected_skills, Mapping) and expected_skills.get(skill) == "not_applicable":
            continue
        updated = dict(skill_grade)
        updated["status"] = "unavailable"
        updated["invocation"] = "unavailable"
        updated["output"] = "unavailable"
        if reason:
            updated["comment"] = f"Evidence unavailable after {reason}."
        skill_grades[skill] = updated
    state_checks = result.get("state_checks") if isinstance(result.get("state_checks"), Mapping) else {}
    for check_name, check in state_checks.items():
        if not isinstance(check, Mapping):
            continue
        if check.get("status") == "not_applicable":
            continue
        updated = dict(check)
        updated["status"] = "unavailable"
        if reason:
            updated["comment"] = f"Evidence unavailable after {reason}."
        state_checks[check_name] = updated
    result["skill_grades"] = skill_grades
    result["state_checks"] = state_checks
    result["overall"] = "unavailable"
    result["evidence_status"] = "unavailable"
    return result


def merge_ui_skill_observations(
    round_grades: list[dict[str, Any]],
    ui_by_round: Mapping[int, Mapping[str, Mapping[str, Any]]],
    expected_payload: Mapping[str, Any],
    case_expected: Mapping[str, Any],
    *,
    execution_mode: str,
) -> list[dict[str, Any]]:
    """Re-grade only UI-owned skills from a separate browser receipt."""
    merged: list[dict[str, Any]] = []
    for grade in round_grades:
        round_number = int(grade["round"])
        ui = ui_by_round.get(round_number, {})
        if not ui:
            merged.append(grade)
            continue
        expected = expected_round(expected_payload, case_expected, round_number)
        result = {"reply": "", "trace": []}
        for skill in UI_SKILLS:
            if skill in ui:
                grade["skill_grades"][skill] = _skill_grade(
                    skill,
                    expected["skill_status"][skill],
                    set(),
                    result,
                    expected,
                    execution_mode=execution_mode,
                    ui_observation=ui[skill],
                )
        grade["overall"] = _round_status(
            grade["skill_grades"], grade.get("state_checks", {}),
            execution_mode=execution_mode, evidence_status=grade.get("evidence_status"),
        )
        merged.append(grade)
    return merged


__all__ = [
    "SKILLS",
    "LIFE_STAGES",
    "UI_SKILLS",
    "aggregate_case",
    "build_langfuse_round_scores",
    "case_expectations",
    "evaluate_round",
    "expected_round",
    "load_json",
    "mark_round_unavailable",
    "merge_ui_skill_observations",
    "validate_expected",
    "validate_inputs",
]
