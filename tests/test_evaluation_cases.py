"""Regression coverage for the checked-in end-to-end synthetic evaluation set."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from apps.api.evaluation_cases import normalise_case, run_case
from apps.api.trajectory_evaluation import evaluate_trajectory


CASES_PATH = Path(__file__).resolve().parent / "evaluation" / "cases.json"


def test_cases_have_reproducible_context_metadata():
    payload = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    defaults = payload.get("case_defaults") or {}
    cases = [normalise_case({**defaults, **case}) for case in payload["cases"]]
    assert cases
    for case in cases:
        assert case["input"]["language"] in {"en-AU", "zh-CN"}
        assert isinstance(case["profile"], dict)
        assert "entitlement" in case
        assert case["enabled_skills"]
        assert isinstance(case["available_tools"], list)


def test_checked_in_cases_pass_through_the_runtime_boundary():
    payload = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases = [normalise_case(case) for case in payload["cases"]]

    async def run_all():
        return [
            await run_case(
                {**case, "dataset": payload["dataset"], "dataset_version": payload["dataset_version"]},
                {"run_id": "pytest-evaluation", "case_id": case["id"]},
            )
            for case in cases
        ]

    results = asyncio.run(run_all())
    for case, result in zip(cases, results):
        trajectory = result["trajectory"]
        assert trajectory["correlation"]["case_id"] == case["id"]
        assert trajectory["schema_version"] == "memoir-trajectory/1"
        assert trajectory["steps"]
        assert all("pre_action_context" in step and "normalized_action" in step for step in trajectory["steps"])
        expected = dict(case)
        expected.update(case["expected"])
        scores = evaluate_trajectory(trajectory, expected=expected)
        assert all(score["value"] == 1 for score in scores), (case["id"], scores)
