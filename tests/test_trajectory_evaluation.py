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
    OpenAICompatibleJudge,
    TrajectoryRecorder,
    build_judge_input,
    build_judge_prompt,
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


def test_recorder_preserves_external_worker_linkage_and_tool_arguments():
    recorder = TrajectoryRecorder({"run_id": "run-1", "case_id": "case-1"})
    recorder.append_external([
        {
            "step_id": "worker-step-0007",
            "sequence": 7,
            "phase": "codex.turn",
            "action": "tool.call",
            "tool_name": "memory.search",
            "tool_arguments": {"query": "Hobart", "limit": 3},
            "observation": {
                "id": "worker-observation-7",
                "parent_id": "worker-observation-root",
                "trace_id": "worker-trace-1",
                "span_id": "worker-span-7",
            },
            "output": {"items": [{"id": "memory-1"}]},
        },
    ], source="codex-worker")

    step = recorder.payload()["steps"][0]
    assert step["external_step_id"] == "worker-step-0007"
    assert step["observation_id"] == "worker-observation-7"
    assert step["parent_observation_id"] == "worker-observation-root"
    assert step["trace_id"] == "worker-trace-1"
    assert step["span_id"] == "worker-span-7"
    assert step["tool_name"] == "memory.search"
    assert step["normalized_action"]["arguments"] == {"limit": 3, "query": "Hobart"}
    assert step["output"] == {"items": [{"id": "memory-1"}]}


def test_external_event_id_is_not_promoted_to_observation_linkage():
    recorder = TrajectoryRecorder()
    recorder.append_external([
        {
            "id": "worker-event-1",
            "action": "worker.completed",
            "output": {"ok": True},
        },
    ], source="codex-worker")

    step = recorder.payload()["steps"][0]
    assert step.get("external_step_id") is None
    assert "observation_id" not in step


def test_protocol_tool_events_normalize_tool_name_and_arguments():
    recorder = TrajectoryRecorder()
    recorder.record_protocol({
        "method": "item/completed",
        "params": {
            "item": {
                "type": "dynamicToolCall",
                "tool": "memory.search",
                "arguments": {"query": "Hobart", "limit": 2},
            },
        },
    }, phase="codex.turn")

    step = recorder.payload()["steps"][0]
    assert step["normalized_action"] == {
        "name": "item/completed",
        "category": "tool",
        "tool_name": "memory.search",
        "arguments": {"limit": 2, "query": "Hobart"},
    }


def test_deterministic_evaluator_can_require_worker_observation_linkage():
    recorder = TrajectoryRecorder()
    recorder.append_external([
        {
            "step_id": "worker-step-1",
            "phase": "codex",
            "action": "tool.call",
            "tool_name": "search",
            "tool_arguments": {"query": "Hobart"},
            "observation_id": "worker-observation-1",
            "parent_observation_id": "worker-root",
        },
    ], source="codex-worker")
    recorder.finish("done")

    scores = evaluate_trajectory(
        recorder.payload(),
        expected={"require_observation_linkage": True},
    )
    assert next(score for score in scores if score["name"] == "observation_linkage")["value"] == 1


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


def test_openai_compatible_judge_uses_template_and_records_safe_usage(monkeypatch):
    async def run():
        def handle(request):
            payload = json.loads(request.content)
            assert "custom evaluator instructions" in payload["messages"][1]["content"]
            assert payload["max_tokens"] == 1200
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": json.dumps({
                        "status": "scored",
                        "scores": {category: 1 for category in (
                            "tool_appropriateness", "evidence_use", "recovery", "repetition",
                            "stopping", "instruction_adherence", "final_response_quality",
                        )},
                        "comments": {},
                        "evidence": ["step-0001"],
                    })}}],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        monkeypatch.setattr("apps.api.trajectory_evaluation.httpx.AsyncClient", lambda **kwargs: client)
        judge = OpenAICompatibleJudge(
            base_url="http://judge",
            model="configured-model",
            instructions="custom evaluator instructions",
        )
        result = await judge({"ordered_steps": [{"step_id": "step-0001"}]})
        assert result["status"] == "scored"
        assert judge.calls == 1
        assert judge.last_call["usage"]["total_tokens"] == 20
        await client.aclose()

    asyncio.run(run())


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
                "request_id": "diag-test-1",
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
                "request_id": "diag-test-1",
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


class _TreeObservation:
    def __init__(self, observation_id, trace_id="trace-tree"):
        self.id = observation_id
        self.trace_id = trace_id
        self.updated = []
        self.ended = False

    def update(self, **kwargs):
        self.updated.append(kwargs)

    def end(self):
        self.ended = True


class _TreeLangfuseDouble:
    def __init__(self):
        self.root = _TreeObservation("root-observation")
        self.children = []
        self.scores = []
        self.flushed = False

    def start_as_current_observation(self, **kwargs):
        self.root.start_kwargs = kwargs
        return self.root

    def start_observation(self, **kwargs):
        child = _TreeObservation(f"child-{len(self.children) + 1}")
        self.children.append((kwargs, child))
        return child

    def create_score(self, **kwargs):
        self.scores.append(kwargs)

    def flush(self):
        self.flushed = True


def test_langfuse_publisher_creates_step_observations_and_targets_step_scores():
    client = _TreeLangfuseDouble()

    async def task(case, correlation):
        recorder = TrajectoryRecorder(correlation)
        recorder.record(
            "codex",
            "tool.call",
            input={"name": "memory.search", "arguments": {"query": "private story"}},
            output={"count": 1},
        )
        recorder.finish("done")
        return {"trajectory": recorder.payload()}

    def evaluator(_trajectory, *, expected):
        return [
            {"name": "step_quality", "value": 1, "step_id": "step-0001"},
            {"name": "run_quality", "value": 1},
        ]

    runner = MemoirEvaluationRunner(task, publisher=LangfusePublisher(client), evaluator=evaluator)
    result = asyncio.run(runner.run_case({"id": "case-1", "input": {"text": "hello"}}, run_id="run-1"))

    assert len(client.children) == 1
    child_kwargs, child = client.children[0]
    assert child_kwargs["name"] == "tool.call"
    assert child_kwargs["metadata"]["trajectory_step_id"] == "step-0001"
    assert child_kwargs["input"]["normalized_action"]["tool_name"] == "memory.search"
    assert "private story" not in json.dumps(child_kwargs)
    assert child.ended
    assert {score["observation_id"] for score in client.scores} == {"child-1", "root-observation"}
    assert result["langfuse"]["step_observations"] == {"step-0001": "child-1"}
    assert client.flushed


def test_langfuse_scores_use_worker_trace_pair_and_round_identity():
    client = _LangfuseDouble()
    publisher = LangfusePublisher(client)
    trajectory = {
        "schema_version": "memoir-trajectory/1",
        "steps": [{
            "step_id": "step-0001",
            "sequence": 1,
            "phase": "codex",
            "action": "tool.call",
            "observation_id": "worker-observation-1",
            "trace_id": "worker-trace-1",
            "output": {"ok": True},
        }],
        "final": {"status": "completed", "response": "done"},
    }

    for round_id in ("001", "002"):
        with publisher.case(
            name=f"round-{round_id}",
            task={"case_id": "case-1", "round": round_id},
            correlation={"run_id": "run-1", "case_id": "case-1", "round_id": round_id},
        ) as sink:
            sink.publish(trajectory, [{"name": "step_quality", "value": 1, "step_id": "step-0001"}])

    assert [score["trace_id"] for score in client.scores] == ["worker-trace-1", "worker-trace-1"]
    assert [score["observation_id"] for score in client.scores] == ["worker-observation-1", "worker-observation-1"]
    assert client.scores[0]["score_id"] != client.scores[1]["score_id"]


def test_protocol_item_lifecycle_pair_counts_one_successful_tool_call():
    recorder = TrajectoryRecorder()
    for method in ("item/started", "item/completed"):
        recorder.record_protocol({
            "method": method,
            "params": {
                "item": {
                    "id": "item-1",
                    "type": "mcpToolCall",
                    "tool": "memory.search",
                    "arguments": {"query": "Hobart"},
                },
            },
        }, phase="codex.turn")
    recorder.finish("done")

    scores = evaluate_trajectory(recorder.payload(), expected={"max_repeated_success": 1})
    assert next(score for score in scores if score["name"] == "repetition_control")["value"] == 1


def test_reasoning_protocol_items_are_filtered_before_trajectory_export():
    recorder = TrajectoryRecorder()
    recorder.record_protocol({
        "method": "item/completed",
        "params": {
            "item": {
                "id": "reasoning-1",
                "type": "reasoning",
                "summary": "private chain of thought",
                "content": [{"text": "private hidden reasoning"}],
            },
        },
    }, phase="codex.turn")

    payload = recorder.payload()
    encoded = json.dumps(payload)
    assert "private chain of thought" not in encoded
    assert "private hidden reasoning" not in encoded
    assert "private chain of thought" not in json.dumps(minimize_for_langfuse(payload))
    item = payload["steps"][0]["output"]["params"]["item"]
    assert item["type"] == "reasoning"
    assert item["summary"] == {"redacted": "private-reasoning"}


def test_reasoning_delta_notifications_are_filtered_before_recording_and_minimization():
    recorder = TrajectoryRecorder()
    private_values = []
    for method in ("item/reasoning/summaryTextDelta", "item/reasoning/textDelta"):
        private_value = f"private {method} content"
        private_values.append(private_value)
        recorder.record_protocol({
            "method": method,
            "params": {
                "delta": {
                    "text": private_value,
                    "nested": [{"summary": private_value}],
                },
                "itemId": "reasoning-1",
            },
        }, phase="codex.turn")

    payload = recorder.payload()
    encoded = json.dumps(payload)
    minimized = json.dumps(minimize_for_langfuse(payload))
    for private_value in private_values:
        assert private_value not in encoded
        assert private_value not in minimized
    for step in payload["steps"]:
        assert step["output"]["params"]["delta"] == {"redacted": "private-reasoning"}


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


def test_unavailable_judge_is_separate_from_deterministic_acceptance_evidence():
    async def unavailable(_judge_input):
        raise httpx.ConnectError("judge unavailable")

    async def task(case, correlation):
        recorder = TrajectoryRecorder(correlation)
        recorder.record("application", "memory.search")
        recorder.finish("done")
        return {"trajectory": recorder.payload()}

    result = asyncio.run(MemoirEvaluationRunner(task, judges=[unavailable]).run_case({"id": "case-1"}, run_id="run-1"))

    assert result["judge_evidence"]["status"] == "unavailable"
    assert result["judge_evidence"]["acceptance_role"] == "advisory"
    assert result["judge_evidence"]["judges"][0]["status"] == "unavailable"
    assert result["acceptance"]["status"] == "unavailable"
    assert result["acceptance"]["deterministic_status"] == "pass"
    assert result["failure_evidence"] == []


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
            return getattr(self, 'saved_profile', {'preferred_language': 'en-AU'})

        def save_profile(self, profile):
            self.saved_profile = dict(profile)

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
        supplied = TrajectoryRecorder({"run_id": "run-1", "case_id": "case-1"})

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
            evaluation_context={
                "enabled_skills": ["memoir-memory-context"],
                "available_tools": ["memory.search"],
            },
            trajectory=supplied,
        )
        assert result["trajectory"]["correlation"] == {"run_id": "run-1", "case_id": "case-1"}
        assert result["trajectory"]["final"]["status"] == "completed"
        assert captured["evaluation"] == {"run_id": "run-1", "case_id": "case-1"}
        assert result["trajectory"]["context"]["task"] == "hello"
        assert result["trajectory"]["context"]["project_id"] is None
        assert result["trajectory"]["context"]["model"] == runtime.model
        assert result["trajectory"]["context"]["enabled_skills"] == ["memoir-memory-context"]
        assert sum(step["action"] == "turn.received" for step in result["trajectory"]["steps"]) == 1

    asyncio.run(run())
