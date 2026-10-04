import json
import inspect
from pathlib import Path
import asyncio

from scripts.memoir_five_case_evaluator import (
    SKILLS,
    aggregate_case,
    evaluate_round,
    expected_round,
    load_json,
    validate_expected,
    validate_inputs,
    build_langfuse_round_scores,
)
from scripts.run_memoir_five_case_evaluation import FixtureWorker, _fixture_places, _has_timeline_cue, langfuse_deterministic_status
from scripts.run_memoir_five_case_evaluation import make_arg_parser, run_case
from apps.api.trajectory_evaluation import LangfusePublisher, TrajectoryRecorder


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


def test_langfuse_round_scores_keep_skill_invocation_and_output_grades_separate():
    grade = {
        "overall": "fail",
        "skill_grades": {
            "memoir-family-tree": {
                "status": "fail",
                "invocation": "pass",
                "output": "fail",
                "comment": "The persisted family revision was stale.",
            },
            "memoir-composer": {
                "status": "unavailable",
                "invocation": "unavailable",
                "output": "unavailable",
                "comment": "Provider timeout.",
            },
        },
        "state_checks": {
            "life_stage": {"status": "pass"},
        },
    }

    scores = build_langfuse_round_scores(grade)
    values = {score["name"]: score["value"] for score in scores}
    assert values["skill.memoir-family-tree.invocation"] == 1
    assert values["skill.memoir-family-tree.output"] == 0
    assert values["state.life_stage"] == 1
    assert "skill.memoir-composer.invocation" not in values
    assert "round.overall" in values


def test_unavailable_round_omits_missing_evidence_scores_and_status_is_consistent():
    grade = {
        "overall": "unavailable",
        "skill_grades": {
            "memoir-memory-context": {
                "status": "fail",
                "invocation": "fail",
                "output": "fail",
                "comment": "No worker response was captured.",
            },
            "memoir-composer": {
                "status": "not_run",
                "invocation": "not_run",
                "output": "not_run",
            },
        },
        "state_checks": {
            "life_stage": {"status": "fail"},
            "visible_markers_stripped": {"status": "fail"},
        },
    }

    assert build_langfuse_round_scores(grade) == []
    assert langfuse_deterministic_status(grade) == "unavailable"


def test_five_case_runner_preserves_partial_trajectory_on_live_worker_failure(tmp_path):
    case = INPUTS["cases"][0]
    case_expected = next(item for item in EXPECTED["case_expectations"] if item["id"] == case["id"])
    args = make_arg_parser().parse_args([
        "--mode", "live",
        "--run-id", "partial-worker-failure",
        "--output-root", str(tmp_path),
    ])

    class RaisingRuntime:
        observed_worker_requests = 1
        model = "synthetic-worker"

        async def turn(self, _storage, _text, **kwargs):
            assert isinstance(kwargs["trajectory"], TrajectoryRecorder)
            recorder = TrajectoryRecorder(kwargs["evaluation"])
            recorder.record("codex", "worker.tool", output={"partial": True})
            recorder.finish(None, status="failed", stop_reason="worker.failed")
            error = RuntimeError("synthetic worker failure")
            error.trajectory = recorder.payload()
            raise error

    summary = asyncio.run(run_case(
        case,
        EXPECTED,
        case_expected,
        args=args,
        run_dir=tmp_path,
        execution_mode="live",
        runtime=RaisingRuntime(),
        max_rounds=1,
    ))

    round_trace = json.loads((tmp_path / "cases" / case["id"] / "rounds" / "round-001.json").read_text())
    assert round_trace["response"]["trajectory"]["steps"][0]["action"] == "worker.tool"
    assert summary["unavailable_rounds"] == [1]


def test_five_case_runner_preserves_recorder_on_runner_timeout(tmp_path, monkeypatch):
    case = INPUTS["cases"][0]
    case_expected = next(item for item in EXPECTED["case_expectations"] if item["id"] == case["id"])
    args = make_arg_parser().parse_args([
        "--mode", "live",
        "--run-id", "partial-runner-timeout",
        "--output-root", str(tmp_path),
    ])

    class SlowRuntime:
        model = "synthetic-worker"
        observed_worker_requests = 1

        async def turn(self, _storage, _text, **kwargs):
            kwargs["trajectory"].record("codex", "worker.partial", output={"captured": True})
            await asyncio.sleep(60)

    async def cancel_as_timeout(awaitable, timeout=None):
        task = asyncio.ensure_future(awaitable)
        await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise TimeoutError()

    monkeypatch.setattr("scripts.run_memoir_five_case_evaluation.asyncio.wait_for", cancel_as_timeout)
    summary = asyncio.run(run_case(
        case,
        EXPECTED,
        case_expected,
        args=args,
        run_dir=tmp_path,
        execution_mode="live",
        runtime=SlowRuntime(),
        max_rounds=1,
    ))

    round_trace = json.loads((tmp_path / "cases" / case["id"] / "rounds" / "round-001.json").read_text())
    trajectory = round_trace["response"]["trajectory"]
    assert trajectory["steps"][0]["action"] == "worker.partial"
    assert trajectory["final"]["status"] == "failed"
    assert summary["unavailable_rounds"] == [1]


class _FiveCaseObservation:
    trace_id = "five-case-trace"
    id = "five-case-observation"

    def __init__(self):
        self.updated = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def update(self, **kwargs):
        self.updated.append(kwargs)


class _FiveCaseLangfuseDouble:
    def __init__(self):
        self.observation = _FiveCaseObservation()
        self.scores = []
        self.flushed = False

    def start_as_current_observation(self, **kwargs):
        self.start_kwargs = kwargs
        return self.observation

    def create_score(self, **kwargs):
        self.scores.append(kwargs)

    def flush(self):
        self.flushed = True


def test_five_case_round_runner_publishes_minimized_trajectory_receipt(tmp_path):
    case = INPUTS["cases"][0]
    case_expected = next(item for item in EXPECTED["case_expectations"] if item["id"] == case["id"])
    args = make_arg_parser().parse_args([
        "--mode", "pilot",
        "--run-id", "test-five-case-publish",
        "--output-root", str(tmp_path),
    ])
    client = _FiveCaseLangfuseDouble()
    summary = asyncio.run(run_case(
        case,
        EXPECTED,
        case_expected,
        args=args,
        run_dir=tmp_path,
        execution_mode="fixture",
        max_rounds=1,
        langfuse_publisher=LangfusePublisher(client),
    ))

    assert summary["langfuse"]["published_rounds"] == 1
    round_trace = json.loads((tmp_path / "cases" / case["id"] / "rounds" / "round-001.json").read_text())
    assert round_trace["langfuse"]["status"] == "published"
    assert client.observation.updated[0]["metadata"]["evaluation_round_status"] == "mock_only"
    assert client.flushed
