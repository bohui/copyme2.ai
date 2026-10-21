"""Fixed snapshots exercise deterministic scorer contracts; no application/model execution."""

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


def test_fixed_trajectory_snapshots_pass_the_scorer_contracts():
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
        assert result["evaluation_scope"] == "scorer_fixture"
        trajectory = result["trajectory"]
        assert trajectory["correlation"]["case_id"] == case["id"]
        assert trajectory["schema_version"] == "memoir-trajectory/1"
        assert trajectory["steps"]
        assert all("pre_action_context" in step and "normalized_action" in step for step in trajectory["steps"])
        expected = dict(case)
        expected.update(case["expected"])
        scores = evaluate_trajectory(trajectory, expected=expected)
        assert all(score["value"] == 1 for score in scores), (case["id"], scores)


def test_synthetic_owner_is_a_unique_authenticated_shape_per_case():
    from uuid import UUID
    from apps.api.evaluation_cases import SyntheticStorage
    case=normalise_case(json.loads(CASES_PATH.read_text())['cases'][0])
    first=SyntheticStorage(case,{'case_id':'same-case'})
    second=SyntheticStorage(case,{'case_id':'same-case'})
    assert str(UUID(first.user_id))==first.user_id
    assert first.user_id!=second.user_id


def test_offline_runner_explicitly_asserts_synthetic_legacy_without_inheriting_authority(monkeypatch,tmp_path):
    from scripts.run_isolated_check import offline_environment
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL','synthetic-must-not-leak')
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','true')
    monkeypatch.setenv('OPENAI_API_KEY','synthetic-must-not-leak')
    env=offline_environment(tmp_path)
    assert env['MEMOIR_LEGACY_ONLY_DEPLOYMENT']=='1'
    assert all(key not in env for key in ('MEMOIR_PUBLICATION_DATABASE_URL','MEMOIR_LIFETIME_MEMORY','OPENAI_API_KEY'))
