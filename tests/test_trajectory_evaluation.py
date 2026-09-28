import asyncio
import json

import httpx

from apps.api.codex_agent import CodexConnection
from apps.api.codex_runtime import CodexRuntime
from apps.api.trajectory_evaluation import (
    LangfusePublisher,
    MemoirEvaluationRunner,
    TrajectoryRecorder,
    build_judge_input,
    evaluate_trajectory,
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
    assert client.start_kwargs["metadata"]["evaluation_run_id"] == "run-1"
    assert {score["name"] for score in client.scores} == {
        "trajectory_schema",
        "step_budget",
        "terminal_completion",
    }
    assert len({score["score_id"] for score in client.scores}) == len(client.scores)
    assert client.flushed
    assert result["langfuse"] == {
        "trace_id": "trace-123",
        "observation_id": "observation-123",
    }
    assert client.observation.updated[0]["metadata"]["evaluation_run_id"] == "run-1"
    assert client.observation.updated[0]["metadata"]["trajectory_sha256"] == result["trajectory_sha256"]


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
