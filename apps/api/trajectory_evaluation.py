"""Observable Codex trajectories and local Langfuse evaluation helpers.

The recorder deliberately stores protocol and application observations only.
It never attempts to reconstruct hidden model reasoning.  The module has no
Langfuse import at module load time so the API and worker images can run
without installing the optional evaluation SDK.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Iterable, Mapping
from uuid import uuid4


TRAJECTORY_SCHEMA_VERSION = "memoir-trajectory/1"
_MAX_STRING = 4000
_MAX_COLLECTION = 100
_MAX_DEPTH = 8
_SENSITIVE_KEY = re.compile(
    r"(?:authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|secret|password|cookie|private[_-]?key)",
    re.IGNORECASE,
)
_PRIVATE_REASONING_KEY = re.compile(
    r"(?:chain[_-]?of[_-]?thought|reasoning|analysis|scratchpad|private[_-]?thought|hidden[_-]?state)",
    re.IGNORECASE,
)
_PRIVATE_CONTEXT_KEY = re.compile(
    r"^(?:base[_-]?instructions?|system[_-]?prompt|developer[_-]?prompt)$",
    re.IGNORECASE,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _sha256(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def redact_payload(value: Any, *, _key: str | None = None, _depth: int = 0) -> Any:
    """Return a bounded, JSON-safe copy suitable for evaluation evidence."""
    if _key and _SENSITIVE_KEY.search(_key):
        return "[REDACTED]"
    if _key and _PRIVATE_REASONING_KEY.search(_key):
        return "[OMITTED]"
    if _depth >= _MAX_DEPTH:
        return "[TRUNCATED]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, bytes):
        return {"sha256": hashlib.sha256(value).hexdigest(), "bytes": len(value)}
    if isinstance(value, str):
        if _key and _PRIVATE_CONTEXT_KEY.search(_key):
            return {
                "redacted": "private-instructions",
                "chars": len(value),
                "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
            }
        if len(value) <= _MAX_STRING:
            return value
        return {
            "text": value[:_MAX_STRING],
            "truncated": True,
            "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
        }
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, raw_value in list(value.items())[:_MAX_COLLECTION]:
            key = str(raw_key)
            result[key] = redact_payload(raw_value, _key=key, _depth=_depth + 1)
        if len(value) > _MAX_COLLECTION:
            result["_truncated_keys"] = len(value) - _MAX_COLLECTION
        return result
    if isinstance(value, (list, tuple, set)):
        values = [redact_payload(item, _depth=_depth + 1) for item in list(value)[:_MAX_COLLECTION]]
        if len(value) > _MAX_COLLECTION:
            values.append({"_truncated_items": len(value) - _MAX_COLLECTION})
        return values
    return redact_payload(str(value), _depth=_depth + 1)


def normalise_correlation(value: Mapping[str, Any] | None) -> dict[str, str]:
    """Keep only bounded scalar IDs that may cross the provider boundary."""
    if not isinstance(value, Mapping):
        return {}
    aliases = {
        "run_id": "run_id",
        "evaluation_run_id": "run_id",
        "case_id": "case_id",
        "evaluation_case_id": "case_id",
        "dataset": "dataset",
        "dataset_name": "dataset",
        "skill_hash": "skill_hash",
        "evaluation_skill_hash": "skill_hash",
        "generation_name": "generation_name",
        "evaluation_generation_name": "generation_name",
        "evaluator_version": "evaluator_version",
        "evaluation_version": "evaluator_version",
    }
    result: dict[str, str] = {}
    for source_key, target_key in aliases.items():
        raw = value.get(source_key)
        if raw is None:
            continue
        text = str(raw).strip().replace("\x00", "")
        if text:
            result[target_key] = text[:256]
    return result


def build_skill_manifest(skill_root: str | Path) -> dict[str, Any]:
    """Hash checked-in SKILL.md files so experiment runs pin their inputs."""
    root = Path(skill_root)
    entries: list[dict[str, str]] = []
    if root.is_dir():
        for path in sorted(root.glob("*/SKILL.md")):
            try:
                content = path.read_bytes()
            except OSError:
                continue
            entries.append({
                "name": path.parent.name,
                "sha256": hashlib.sha256(content).hexdigest(),
            })
    return {"skills": entries, "sha256": _sha256(entries)}


def _protocol_summary(message: Mapping[str, Any]) -> dict[str, Any]:
    """Keep protocol shape and tool results while dropping private fields."""
    summary: dict[str, Any] = {}
    for key in ("id", "method"):
        if key in message:
            summary[key] = message[key]
    if "params" in message:
        summary["params"] = redact_payload(message.get("params"))
    if "result" in message:
        summary["result"] = redact_payload(message.get("result"))
    if "error" in message:
        summary["error"] = redact_payload(message.get("error"))
    return summary


def protocol_request_evidence(method: str, params: Mapping[str, Any]) -> dict[str, Any]:
    """Redact private instruction text while retaining request shape."""
    evidence = redact_payload(params)
    if method != "turn/start" or not isinstance(evidence, dict):
        return evidence
    inputs = evidence.get("input")
    if isinstance(inputs, list):
        for item in inputs:
            if not isinstance(item, dict) or item.get("type") != "text":
                continue
            text = item.get("text")
            if isinstance(text, str):
                item["text"] = {
                    "redacted": "turn-input",
                    "chars": len(text),
                    "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                }
    return evidence


class TrajectoryRecorder:
    """Collect an ordered, redacted record of one application turn."""

    def __init__(
        self,
        correlation: Mapping[str, Any] | None = None,
        *,
        skill_manifest: Mapping[str, Any] | None = None,
        max_steps: int = 512,
    ) -> None:
        self.correlation = normalise_correlation(correlation)
        self.skill_manifest = redact_payload(skill_manifest) if skill_manifest else None
        self.max_steps = max_steps
        self.started_at = _utc_now()
        self.completed_at: str | None = None
        self.steps: list[dict[str, Any]] = []
        self.context: dict[str, Any] = {}
        self.final: dict[str, Any] = {}

    def set_context(self, **values: Any) -> None:
        self.context.update(redact_payload(values))

    def record(
        self,
        phase: str,
        action: str,
        *,
        context: Any = None,
        input: Any = None,
        output: Any = None,
        error: Any = None,
        metadata: Mapping[str, Any] | None = None,
        source: str | None = None,
    ) -> dict[str, Any]:
        sequence = len(self.steps) + 1
        step: dict[str, Any] = {
            "step_id": f"step-{sequence:04d}",
            "sequence": sequence,
            "occurred_at": _utc_now(),
            "phase": str(phase),
            "action": str(action),
        }
        if source:
            step["source"] = str(source)
        if context is not None:
            step["context"] = redact_payload(context)
        if input is not None:
            step["input"] = redact_payload(input)
        if output is not None:
            step["output"] = redact_payload(output)
        if error is not None:
            step["error"] = redact_payload(error)
        if metadata:
            step["metadata"] = redact_payload(metadata)
        self.steps.append(step)
        return step

    def record_protocol(self, message: Mapping[str, Any], *, phase: str = "codex") -> dict[str, Any]:
        method = message.get("method")
        action = str(method or ("protocol.error" if "error" in message else "protocol.response"))
        return self.record(phase, action, output=_protocol_summary(message))

    def append_external(self, steps: Iterable[Mapping[str, Any]], *, source: str) -> None:
        """Append worker steps while preserving their evidence and local order."""
        for external in steps:
            if not isinstance(external, Mapping):
                continue
            self.record(
                str(external.get("phase") or "worker"),
                str(external.get("action") or "worker.event"),
                context=external.get("context"),
                input=external.get("input"),
                output=external.get("output"),
                error=external.get("error"),
                metadata=external.get("metadata"),
                source=source,
            )

    def finish(
        self,
        response: Any = None,
        *,
        status: str = "completed",
        stop_reason: str | None = None,
        state: Mapping[str, Any] | None = None,
        error: Any = None,
    ) -> None:
        self.completed_at = _utc_now()
        self.final = {
            "status": str(status),
            "stop_reason": str(stop_reason or status),
            "response": redact_payload(response),
        }
        if state is not None:
            self.final["state"] = redact_payload(state)
        if error is not None:
            self.final["error"] = redact_payload(error)

    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": TRAJECTORY_SCHEMA_VERSION,
            "correlation": dict(self.correlation),
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "context": redact_payload(self.context),
            "skill_manifest": self.skill_manifest,
            "steps": list(self.steps),
            "final": dict(self.final),
        }

    def digest(self) -> str:
        return _sha256(self.payload())


def _nested_value(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _score(name: str, value: float, comment: str, *, step_id: str | None = None) -> dict[str, Any]:
    result = {"name": name, "value": float(max(0.0, min(1.0, value))), "comment": comment}
    if step_id:
        result["step_id"] = step_id
    return result


def evaluate_trajectory(
    trajectory: Mapping[str, Any],
    *,
    expected: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run deterministic gates; semantic judging can be added independently."""
    expected = expected or {}
    steps = trajectory.get("steps") if isinstance(trajectory, Mapping) else None
    steps = steps if isinstance(steps, list) else []
    final = trajectory.get("final") if isinstance(trajectory, Mapping) else {}
    final = final if isinstance(final, Mapping) else {}
    actions = [str(step.get("action")) for step in steps if isinstance(step, Mapping)]
    scores: list[dict[str, Any]] = []

    valid_sequence = (
        trajectory.get("schema_version") == TRAJECTORY_SCHEMA_VERSION
        and all(isinstance(step, Mapping) and step.get("sequence") == index for index, step in enumerate(steps, 1))
    )
    scores.append(_score("trajectory_schema", 1 if valid_sequence else 0, "Ordered trajectory schema is valid." if valid_sequence else "Trajectory schema or sequence is invalid."))

    max_steps = int(expected.get("max_steps", 512))
    within_budget = len(steps) <= max_steps
    scores.append(_score("step_budget", 1 if within_budget else 0, f"Observed {len(steps)} step(s); budget is {max_steps}."))

    terminal = final.get("status") == "completed" and bool(str(final.get("response") or "").strip())
    scores.append(_score("terminal_completion", 1 if terminal else 0, "Turn completed with a visible response." if terminal else "Turn did not complete with a visible response."))

    required = [str(item) for item in expected.get("required_actions", []) if item]
    missing = [item for item in required if item not in actions]
    if required:
        scores.append(_score("required_actions", 0 if missing else 1, "Missing required action(s): " + ", ".join(missing) if missing else "All required actions were observed."))

    forbidden = [str(item) for item in expected.get("forbidden_actions", []) if item]
    found = [item for item in forbidden if item in actions]
    if forbidden:
        scores.append(_score("forbidden_actions", 0 if found else 1, "Forbidden action(s) observed: " + ", ".join(found) if found else "No forbidden actions were observed."))

    assertions = expected.get("state_assertions") or {}
    if isinstance(assertions, Mapping) and assertions:
        failed = [path for path, value in assertions.items() if _nested_value(final.get("state"), str(path)) != value]
        scores.append(_score("state_assertions", 0 if failed else 1, "State assertion(s) failed: " + ", ".join(failed) if failed else "All expected final-state assertions passed."))

    expected_skill_hash = expected.get("skill_manifest_sha256")
    if expected_skill_hash:
        actual_manifest = trajectory.get("skill_manifest")
        actual_hash = actual_manifest.get("sha256") if isinstance(actual_manifest, Mapping) else None
        scores.append(_score("skill_manifest", 1 if actual_hash == expected_skill_hash else 0, "Skill manifest matches the case." if actual_hash == expected_skill_hash else "Skill manifest does not match the case."))
    return scores


def build_judge_input(
    *,
    task: Any,
    trajectory: Mapping[str, Any],
    available_tools: Any = None,
) -> dict[str, Any]:
    """Build the explicit full-run input expected by an external judge."""
    final = trajectory.get("final") if isinstance(trajectory, Mapping) else {}
    final = final if isinstance(final, Mapping) else {}
    return {
        "task": redact_payload(task),
        "available_tools": redact_payload(available_tools or []),
        "ordered_steps": redact_payload(trajectory.get("steps", [])),
        "final_response": redact_payload(final.get("response")),
        "stop_reason": final.get("stop_reason"),
        "final_state": redact_payload(final.get("state")),
    }


class LangfusePublisher:
    """Small adapter around the optional Langfuse Python SDK v4."""

    def __init__(self, client: Any = None) -> None:
        if client is None:
            try:
                from langfuse import get_client  # type: ignore[import-not-found]
            except ImportError as error:  # pragma: no cover - exercised by CLI setup
                raise RuntimeError("Install the evaluation extra to publish to Langfuse: pip install -e '.[evaluation]'") from error
            # Keep Memoir's environment namespace separate while allowing the
            # SDK to use its standard configuration names.
            for source, target in (
                ("MEMORY_SPARK_LANGFUSE_PUBLIC_KEY", "LANGFUSE_PUBLIC_KEY"),
                ("MEMORY_SPARK_LANGFUSE_SECRET_KEY", "LANGFUSE_SECRET_KEY"),
                ("MEMORY_SPARK_LANGFUSE_BASE_URL", "LANGFUSE_BASE_URL"),
                ("MEMORY_SPARK_LANGFUSE_ENVIRONMENT", "LANGFUSE_TRACING_ENVIRONMENT"),
            ):
                value = os.getenv(source)
                if value and not os.getenv(target):
                    os.environ[target] = value
            client = get_client()
        self.client = client

    def run_experiment(
        self,
        *,
        name: str,
        data: Iterable[Any],
        task: Callable[..., Any],
        evaluators: Iterable[Callable[..., Any]] = (),
        description: str | None = None,
    ) -> Any:
        """Delegate synchronous dataset experiments to the SDK v4 runner."""
        runner = getattr(self.client, "run_experiment", None)
        if not callable(runner):
            raise RuntimeError("The configured Langfuse client does not expose run_experiment")
        kwargs: dict[str, Any] = {
            "name": name,
            "data": list(data),
            "task": task,
            "evaluators": list(evaluators),
        }
        if description:
            kwargs["description"] = description
        return runner(**kwargs)

    @contextmanager
    def case(self, *, name: str, task: Any, correlation: Mapping[str, Any]):
        metadata = {f"evaluation_{key}": value for key, value in normalise_correlation(correlation).items()}
        kwargs: dict[str, Any] = {
            "as_type": "agent",
            "name": name,
            "input": redact_payload(task),
            "metadata": metadata,
        }
        create_trace_id = getattr(self.client, "create_trace_id", None)
        run_id = normalise_correlation(correlation).get("run_id")
        case_id = normalise_correlation(correlation).get("case_id")
        if callable(create_trace_id) and run_id:
            kwargs["trace_context"] = {
                "trace_id": create_trace_id(seed=f"{run_id}:{case_id or ''}"),
            }
        observation = self.client.start_as_current_observation(**kwargs)
        with observation as active:
            yield _LangfuseCase(self.client, active, correlation)


class _LangfuseCase:
    def __init__(self, client: Any, observation: Any, correlation: Mapping[str, Any]) -> None:
        self.client = client
        self.observation = observation
        self.correlation = normalise_correlation(correlation)

    @property
    def trace_id(self) -> str | None:
        value = getattr(self.observation, "trace_id", None)
        return str(value) if value else None

    @property
    def observation_id(self) -> str | None:
        value = getattr(self.observation, "id", None)
        return str(value) if value else None

    def publish(self, trajectory: Mapping[str, Any], scores: Iterable[Mapping[str, Any]]) -> None:
        digest = _sha256(trajectory)
        metadata = {
            f"evaluation_{key}": value
            for key, value in self.correlation.items()
        }
        metadata["trajectory_sha256"] = digest
        self.observation.update(
            output=redact_payload(trajectory),
            metadata=metadata,
        )
        trace_id = self.trace_id
        if not trace_id:
            return
        run_id = self.correlation.get("run_id", trace_id)
        for score in scores:
            name = str(score.get("name") or "trajectory_quality")
            step_id = str(score.get("step_id") or "run")
            evaluator_version = self.correlation.get("evaluator_version", "trajectory-rubric/1")
            score_id = hashlib.sha256(f"{run_id}:{evaluator_version}:{step_id}:{name}".encode()).hexdigest()
            kwargs = {
                "score_id": score_id,
                "name": name,
                "value": float(score.get("value", 0)),
                "trace_id": trace_id,
                "observation_id": self.observation_id,
                "data_type": "NUMERIC",
                "comment": str(score.get("comment") or ""),
            }
            try:
                self.client.create_score(**kwargs)
            except TypeError:  # pragma: no cover - compatibility with older test doubles
                kwargs.pop("score_id", None)
                self.client.create_score(**kwargs)
        flush = getattr(self.client, "flush", None)
        if callable(flush):
            flush()


class MemoirEvaluationRunner:
    """Run isolated local cases through a caller-supplied Memoir task callback."""

    def __init__(
        self,
        task: Callable[[Mapping[str, Any], Mapping[str, str]], Any],
        *,
        publisher: LangfusePublisher | None = None,
        evaluator: Callable[[Mapping[str, Any], Mapping[str, Any]], list[dict[str, Any]]] = evaluate_trajectory,
    ) -> None:
        self.task = task
        self.publisher = publisher
        self.evaluator = evaluator

    async def run_case(self, case: Mapping[str, Any], *, run_id: str | None = None) -> dict[str, Any]:
        case_id = str(case.get("id") or case.get("case_id") or uuid4())
        correlation = normalise_correlation({
            **(case.get("metadata") if isinstance(case.get("metadata"), Mapping) else {}),
            "run_id": run_id or case.get("run_id") or uuid4(),
            "case_id": case_id,
            "dataset": case.get("dataset") or case.get("dataset_name"),
            "skill_hash": case.get("skill_manifest_sha256"),
            "generation_name": case.get("generation_name") or "memoir-agent-evaluation",
            "evaluator_version": case.get("evaluator_version") or "trajectory-rubric/1",
        })

        @contextmanager
        def no_publish():
            yield None

        context = self.publisher.case(name="memoir-agent-evaluation", task=case.get("input", case), correlation=correlation) if self.publisher else no_publish()
        with context as sink:
            result = self.task(case, correlation)
            if inspect.isawaitable(result):
                result = await result
            if not isinstance(result, Mapping):
                raise TypeError("evaluation task must return a mapping containing trajectory")
            trajectory = result.get("trajectory")
            if not isinstance(trajectory, Mapping):
                raise ValueError("evaluation task returned no normalized trajectory")
            expected = case.get("expected") if isinstance(case.get("expected"), Mapping) else case
            scores = self.evaluator(trajectory, expected=expected)
            if sink is not None:
                sink.publish(trajectory, scores)
            result = {
                "case_id": case_id,
                "correlation": correlation,
                "scores": scores,
                "result": redact_payload(result),
                "trajectory_sha256": _sha256(trajectory),
            }
            if sink is not None:
                result["langfuse"] = {
                    "trace_id": sink.trace_id,
                    "observation_id": sink.observation_id,
                }
            return result

    async def run(self, cases: Iterable[Mapping[str, Any]], *, run_id: str | None = None) -> list[dict[str, Any]]:
        return [await self.run_case(case, run_id=run_id) for case in cases]
