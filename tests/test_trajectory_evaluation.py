import asyncio
import json

import httpx
import pytest

from apps.api.codex_agent import CodexConnection
from apps.api.codex_runtime import CodexRuntime
from apps.api.trajectory_evaluation import (
    EVALUATION_RUBRIC_VERSION,
    LangfusePublisher,
    MemoirEvaluationRunner,
    TrajectoryRecorder,
    build_judge_input,
    comparison_matrix,
    evaluate_trajectory,
    load_judge_calibration,
    minimize_for_langfuse,
)


def test_recorder_keeps_observable_results_and_omits_private_fields():
    recorder = TrajectoryRecorder({"run_id": "run-1", "case_id": "case-1"})
    recorder.record(
        "codex",
        "tool.call",
        input={"name": "memory.search", "arguments": {"query": "Geelong"}},
        output={"result": "evidence", "reasoning": "do not store this"},
        metadata={"password": "secret"},
    )
    recorder.finish("A grounded reply", state={"revision": 2})

    payload = recorder.payload()
    encoded = json.dumps(payload)
    assert payload["steps"][0]["action"] == "tool.call"
    assert "evidence" in encoded
    assert "do not store this" not in encoded
    assert "secret" not in encoded
    assert payload["final"]["response"] == "A grounded reply"


def test_recorder_adds_pre_action_context_normalized_actions_and_reports_overflow():
    recorder = TrajectoryRecorder({"run_id": "run-1"}, max_steps=1)
    recorder.set_context(project_revision=3, entitlement="paid")
    step = recorder.record(
        "codex",
        "tool.call",
        input={"name": "memory.search", "arguments": {"query": "private story"}},
    )
    recorder.record("codex", "tool.call", input={"name": "memory.save"})

    assert step["pre_action_context"] == {"project_revision": 3, "entitlement": "paid"}
    assert step["normalized_action"] == {
        "name": "tool.call",
        "category": "tool",
        "tool_name": "memory.search",
        "arguments": {"query": "private story"},
    }
    assert recorder.payload()["limits"] == {
        "max_steps": 1,
        "observed_steps": 1,
        "dropped_steps": 1,
        "overflowed": True,
    }
    scores = evaluate_trajectory(recorder.payload(), expected={"max_steps": 1})
    assert next(score for score in scores if score["name"] == "step_budget")["value"] == 0


def test_provider_payload_minimizes_storyteller_text_and_identifiers():
    minimized = minimize_for_langfuse({
        "text": "My private story is not provider evidence.",
        "project_id": "project-secret",
        "tool_name": "memory.search",
        "status": "completed",
    })
    encoded = json.dumps(minimized)
    assert "My private story" not in encoded
    assert "project-secret" not in encoded
    assert minimized["tool_name"] == "memory.search"
    assert minimized["status"] == "completed"


def test_marker_gate_requires_a_valid_json_payload():
    recorder = TrajectoryRecorder()
    recorder.record(
        "worker",
        "worker.turn.completed",
        output={"reply": "[[MEMORY_SPARK_PLACE_JOURNEY]]not-json[[/MEMORY_SPARK_PLACE_JOURNEY]]"},
    )
    recorder.finish("done")

    scores = evaluate_trajectory(recorder.payload(), expected={"marker_syntax": True})
    assert next(score for score in scores if score["name"] == "marker_syntax")["value"] == 0


def test_evaluator_credits_a_bounded_retry_but_not_a_duplicate_success():
    recorder = TrajectoryRecorder()
    recorder.record(
        "worker",
        "tool.call",
        input={"name": "memory.search", "arguments": {"query": "Geelong"}},
        error={"code": "TRANSIENT"},
    )
    recorder.record(
        "worker",
        "tool.call",
        input={"name": "memory.search", "arguments": {"query": "Geelong"}},
        output={"count": 1},
    )
    recorder.record("application", "worker.turn.completed")
    recorder.finish("done")

    scores = evaluate_trajectory(
        recorder.payload(),
        expected={
            "allowed_action_sets": [["tool.call", "tool.call", "worker.turn.completed"]],
            "allowed_tools": ["memory.search"],
            "max_retries": 1,
            "max_repeated_success": 1,
        },
    )
    values = {score["name"]: score["value"] for score in scores}
    assert values["equivalent_valid_path"] == 1
    assert values["retry_budget"] == 1
    assert values["recovery"] == 1
    assert values["repetition_control"] == 1
    assert values["execution_quality"] == 1


def test_deterministic_evaluators_check_order_budget_and_state():
    recorder = TrajectoryRecorder()
    recorder.record("application", "memory.search")
    recorder.record("application", "memory.persist")
    recorder.finish("done", state={"revision": 2})

    scores = evaluate_trajectory(
        recorder.payload(),
        expected={
            "max_steps": 3,
            "required_actions": ["memory.search", "memory.persist"],
            "state_assertions": {"revision": 2},
        },
    )
    assert {score["name"]: score["value"] for score in scores} == {
        "trajectory_schema": 1.0,
        "step_budget": 1.0,
        "terminal_completion": 1.0,
        "required_actions": 1.0,
        "state_assertions": 1.0,
        "trajectory_quality": 1.0,
        "skill_selection": 1.0,
        "skill_adherence": 1.0,
        "skill_selection_adherence": 1.0,
        "execution_quality": 1.0,
        "state_correctness": 1.0,
        "final_response_quality": 1.0,
    }


def test_judge_input_contains_ordered_steps_and_terminal_state():
    recorder = TrajectoryRecorder()
    recorder.record("codex", "tool.call", input={"name": "search"}, output={"items": ["evidence"]})
    recorder.finish("reply", stop_reason="turn.completed", state={"saved": True})

    judge_input = build_judge_input(
        task={"text": "Find the memory"},
        available_tools=[{"name": "search"}],
        trajectory=recorder.payload(),
    )
    assert judge_input["ordered_steps"][0]["action"] == "tool.call"
    assert judge_input["final_response"] == "reply"
    assert judge_input["final_state"] == {"saved": True}
    assert judge_input["rubric_version"]
    assert "final_response_quality" in judge_input["rubric"]


def test_judge_calibration_requires_explicit_human_review():
    example = {
        "case_id": "place-cue-grounded",
        "scores": {"tool_appropriateness": 1},
        "rationale": "The selected tool is grounded in the named place.",
    }
    assert load_judge_calibration({
        "schema_version": "memoir-judge-calibration/1",
        "review_status": "human-reviewed",
        "reviewer": "reviewer@example.test",
        "reviewed_at": "2026-09-28",
        "examples": [example],
    }) == [example]
    with pytest.raises(ValueError, match="human-reviewed"):
        load_judge_calibration({
            "schema_version": "memoir-judge-calibration/1",
            "review_status": "requires-human-review",
            "reviewer": "reviewer@example.test",
            "reviewed_at": "2026-09-28",
            "examples": [example],
        })


def test_codex_turn_forwards_evaluation_metadata_to_responses_api():
    async def run():
        connection = CodexConnection([], ".")

        async def request(method, params):
            assert method == "turn/start"
            assert params["responsesapiClientMetadata"] == {
                "run_id": "run-1",
                "case_id": "case-1",
                "skill_hash": "skill-sha",
                "generation_name": "memoir-agent-evaluation",
            }
            connection.events.append({
                "method": "item/completed",
                "params": {"threadId": "thread", "item": {"type": "agentMessage", "text": "done"}},
            })
            return {"turn": {"id": "turn"}}

        async def receive():
            return {
                "method": "turn/completed",
                "params": {"threadId": "thread", "turn": {"id": "turn", "status": "completed"}},
            }

        connection.request = request
        connection.receive = receive
        assert await connection.turn(
            "thread",
            "hello",
            responsesapi_client_metadata={
                "run_id": "run-1",
                "case_id": "case-1",
                "skill_hash": "skill-sha",
                "generation_name": "memoir-agent-evaluation",
            },
        ) == "done"

    asyncio.run(run())


class _Observation:
    trace_id = "trace-123"
    id = "observation-123"

    def __init__(self):
        self.updated = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def update(self, **kwargs):
        self.updated.append(kwargs)


class _LangfuseDouble:
    def __init__(self):
        self.observation = _Observation()
        self.scores = []
        self.flushed = False

    def start_as_current_observation(self, **kwargs):
        self.start_kwargs = kwargs
        return self.observation

    def create_score(self, **kwargs):
        self.scores.append(kwargs)

    def flush(self):
        self.flushed = True


def test_runner_publishes_trace_and_idempotent_scores_to_langfuse_double():
    client = _LangfuseDouble()

    async def task(case, correlation):
        recorder = TrajectoryRecorder(correlation)
        recorder.record("application", "memory.search")
        recorder.finish("done")
        return {"reply": "done", "trajectory": recorder.payload()}

    runner = MemoirEvaluationRunner(
        task,
        publisher=LangfusePublisher(client),
    )
    result = asyncio.run(runner.run_case({"id": "case-1", "input": {"text": "hello"}} , run_id="run-1"))

    assert result["case_id"] == "case-1"
    assert result["correlation"]["application_revision"]
    assert client.start_kwargs["metadata"]["evaluation_run_id"] == "run-1"
    assert {score["name"] for score in client.scores} == {
        "trajectory_schema",
        "step_budget",
        "terminal_completion",
        "trajectory_quality",
        "skill_selection",
        "skill_adherence",
        "skill_selection_adherence",
        "execution_quality",
        "state_correctness",
        "final_response_quality",
    }
    assert len({score["score_id"] for score in client.scores}) == len(client.scores)
    assert client.flushed
    assert result["langfuse"] == {
        "trace_id": "trace-123",
        "observation_id": "observation-123",
    }
    assert client.observation.updated[0]["metadata"]["evaluation_run_id"] == "run-1"
    assert client.observation.updated[0]["metadata"]["trajectory_sha256"] == result["trajectory_sha256"]


def test_runner_can_add_a_semantic_judge_and_compare_variants():
    async def judge(judge_input):
        assert judge_input["ordered_steps"]
        return {"judge": "calibration", "scores": {"evidence_use": 0.8}, "comments": {"evidence_use": "Grounded."}}

    async def task(case, correlation):
        recorder = TrajectoryRecorder(correlation)
        recorder.record("application", "memory.search")
        recorder.finish(f"reply-{correlation.get('variant', 'default')}")
        return {"trajectory": recorder.payload()}

    runner = MemoirEvaluationRunner(task, judges=[judge])
    results = asyncio.run(runner.run(
        [{"id": "case-1", "input": {"text": "hello"}}],
        run_id="run-1",
        variants=[{"variant": "baseline"}, {"variant": "candidate"}],
        max_concurrency=2,
    ))
    assert all(any(score["name"] == "judge.calibration.evidence_use" for score in result["scores"]) for result in results)
    matrix = comparison_matrix(results, baseline_variant="baseline")
    assert {row["variant"] for row in matrix} == {"baseline", "candidate"}
    assert all(result["correlation"]["evaluator_version"] == EVALUATION_RUBRIC_VERSION for result in results)


def test_worker_turn_adds_evaluation_envelope_only_when_requested(monkeypatch):
    async def run():
        captured = {}

        def handle(request):
            captured.update(json.loads(request.content))
            return httpx.Response(200, json={"thread_id": "thread", "reply": "done", "artifacts": []})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        monkeypatch.setattr("apps.api.codex_runtime.httpx.AsyncClient", lambda **kwargs: client)
        runtime = CodexRuntime(worker_url="http://worker", worker_secret="secret")
        result = await runtime._worker_turn(
            user_id="user",
            prior=None,
            memories=[],
            profile={},
            place_journey={},
            family_enabled=False,
            family_context={},
            project_id=None,
            text="hello",
            language="en-AU",
            evaluation={"run_id": "run-1", "case_id": "case-1"},
        )
        assert result["reply"] == "done"
        assert captured["evaluation"] == {"run_id": "run-1", "case_id": "case-1"}

    asyncio.run(run())


def test_runtime_returns_trajectory_only_for_an_evaluation_turn(monkeypatch):
    class Storage:
        user_id = "11111111-1111-4111-8111-111111111111"

        def acquire_agent_turn_lease(self, token, lease_seconds):
            return True

        def renew_agent_turn_lease(self, token, lease_seconds):
            return True

        def release_agent_turn_lease(self, token):
            return True

        def agent_session(self):
            return None

        def memories(self):
            return []

        def profile(self):
            return {'preferred_language': 'en-AU'}

        def place_journey(self):
            return None

        def story_entitlement(self):
            return None

        @staticmethod
        def agent_path(path):
            return path

        def commit_agent_turn(self, token, thread_id, text, source_paths):
            return {"id": "turn-1", "source_paths": source_paths}

    async def run():
        captured = {}

        def handle(request):
            captured.update(json.loads(request.content))
            return httpx.Response(200, json={
                "thread_id": "thread-1",
                "reply": "A grounded reply",
                "artifacts": [],
                "trajectory": {
                    "schema_version": "memoir-trajectory/1",
                    "steps": [{"phase": "codex", "action": "turn.completed"}],
                    "final": {"status": "completed", "response": "A grounded reply"},
                },
            })

        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        monkeypatch.setattr("apps.api.codex_runtime.httpx.AsyncClient", lambda **kwargs: client)
        runtime = CodexRuntime(worker_url="http://worker", worker_secret="secret")
        result = await runtime.turn(
            Storage(),
            "hello",
            evaluation={"run_id": "run-1", "case_id": "case-1"},
        )
        assert result["trajectory"]["correlation"] == {"run_id": "run-1", "case_id": "case-1"}
        assert result["trajectory"]["final"]["status"] == "completed"
        assert captured["evaluation"] == {"run_id": "run-1", "case_id": "case-1"}

    asyncio.run(run())
