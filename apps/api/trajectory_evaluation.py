"""Observable Codex trajectories and local Langfuse evaluation helpers.

The recorder deliberately stores protocol and application observations only.
It never attempts to reconstruct hidden model reasoning.  The module has no
Langfuse import at module load time so the API and worker images can run
without installing the optional evaluation SDK.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Iterable, Mapping, Sequence
from uuid import uuid4

import httpx


TRAJECTORY_SCHEMA_VERSION = "memoir-trajectory/1"
EVALUATION_RUBRIC_VERSION = "memoir-trajectory-rubric/2"
JUDGE_RUBRIC_VERSION = "memoir-judge-rubric/1"
PRIVACY_POLICY_VERSION = "memoir-evaluation-privacy/1"
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
_NARRATIVE_KEY = re.compile(
    r"(?:^|_)(?:text|transcript|prompt|response|content|query|answer|message|story|task)(?:$|_)",
    re.IGNORECASE,
)
_IDENTIFIER_KEY = re.compile(
    r"(?:^|_)(?:user|account|project|thread|session|source|asset|memory|upload|path|file)(?:_id|_path|_name|$)",
    re.IGNORECASE,
)
_TOOL_KEY = re.compile(r"(?:^|_)(?:tool|function)(?:_name)?$", re.IGNORECASE)

JUDGE_RUBRIC: dict[str, str] = {
    "tool_appropriateness": "Choose only tools that advance the task and use the narrowest valid tool for the evidence available.",
    "evidence_use": "Ground claims in returned evidence and preserve uncertainty; never invent facts absent from the case.",
    "recovery": "Recover from tool errors with a bounded, useful retry or a clear safe stop.",
    "repetition": "Avoid duplicate successful actions and unproductive loops.",
    "stopping": "Stop once the task is complete or a safe, explicit blocker is reached.",
    "instruction_adherence": "Follow the task, entitlement, privacy, ownership, and output constraints.",
    "final_response_quality": "Give a concise, accurate, uncertainty-preserving response that matches the requested outcome.",
}


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


def _privacy_token(value: Any, label: str) -> dict[str, Any]:
    return {
        "redacted": label,
        "chars": len(str(value)),
        "sha256": _sha256(value),
    }


def minimize_for_langfuse(value: Any, *, _key: str | None = None, _depth: int = 0) -> Any:
    """Minimise local evidence before it crosses the Langfuse boundary.

    Full evidence remains in the local result artifact. Provider-facing
    observations keep shape, counts, hashes, tool names, and statuses but do
    not contain storyteller prose, prompts, identifiers, or filesystem paths.
    """
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
        if _key and (_NARRATIVE_KEY.search(_key) or _PRIVATE_CONTEXT_KEY.search(_key)):
            return _privacy_token(value, "narrative")
        if _key and _IDENTIFIER_KEY.search(_key):
            return _privacy_token(value, "identifier")
        return value if len(value) <= 256 else _privacy_token(value, "long-string")
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, raw_value in list(value.items())[:_MAX_COLLECTION]:
            key = str(raw_key)
            result[key] = minimize_for_langfuse(raw_value, _key=key, _depth=_depth + 1)
        if len(value) > _MAX_COLLECTION:
            result["_truncated_keys"] = len(value) - _MAX_COLLECTION
        return result
    if isinstance(value, (list, tuple, set)):
        values = [minimize_for_langfuse(item, _depth=_depth + 1) for item in list(value)[:_MAX_COLLECTION]]
        if len(value) > _MAX_COLLECTION:
            values.append({"_truncated_items": len(value) - _MAX_COLLECTION})
        return values
    return _privacy_token(str(value), "value")


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
        "dataset_version": "dataset_version",
        "rubric_version": "rubric_version",
        "judge_rubric_version": "judge_rubric_version",
        "model": "model",
        "provider": "provider",
        "variant": "variant",
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


def normalise_action(action: str, *, input: Any = None, metadata: Mapping[str, Any] | None = None,
                     phase: str | None = None) -> dict[str, Any]:
    """Normalise a model/application action without changing its raw label."""
    candidates: list[Mapping[str, Any]] = []
    if isinstance(input, Mapping):
        candidates.append(input)
    if isinstance(metadata, Mapping):
        candidates.append(metadata)
    tool_name = None
    arguments = None
    for candidate in candidates:
        for key in ("tool_name", "tool", "name", "function_name", "function"):
            value = candidate.get(key)
            if isinstance(value, str) and value.strip():
                tool_name = value.strip()
                break
        for key in ("tool_arguments", "arguments", "args", "parameters"):
            value = candidate.get(key)
            if isinstance(value, Mapping):
                arguments = {str(key): value[key] for key in sorted(value, key=str)}
                break
        if tool_name or arguments is not None:
            break
    action_name = str(action).strip()
    lower = action_name.lower()
    if not tool_name and (lower.startswith("tool.") or lower.startswith("function.")):
        tail = action_name.split(".", 1)[1].strip()
        if tail and tail not in {"call", "result", "error", "retry"}:
            tool_name = tail
    if tool_name:
        category = "tool"
    elif any(token in lower for token in ("error", "failed", "exception")):
        category = "error"
    elif any(token in lower for token in ("response", "reply", "complete", "stop")):
        category = "terminal"
    elif phase in {"codex", "worker"}:
        category = "model"
    else:
        category = "application"
    result: dict[str, Any] = {"name": action_name, "category": category}
    if tool_name:
        result["tool_name"] = tool_name
    if arguments is not None:
        result["arguments"] = redact_payload(arguments)
    return result


normalize_action = normalise_action


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
        self.max_steps = max(1, int(max_steps))
        self.started_at = _utc_now()
        self.completed_at: str | None = None
        self.steps: list[dict[str, Any]] = []
        self.context: dict[str, Any] = {}
        self.final: dict[str, Any] = {}
        self.dropped_steps = 0
        self.overflowed = False

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
        if len(self.steps) >= self.max_steps:
            self.dropped_steps += 1
            self.overflowed = True
            return {
                "step_id": f"overflow-{self.dropped_steps:04d}",
                "sequence": self.max_steps + self.dropped_steps,
                "accepted": False,
                "phase": str(phase),
                "action": str(action),
            }
        sequence = len(self.steps) + 1
        step: dict[str, Any] = {
            "step_id": f"step-{sequence:04d}",
            "sequence": sequence,
            "occurred_at": _utc_now(),
            "phase": str(phase),
            "action": str(action),
            "pre_action_context": redact_payload(self.context),
            "context": redact_payload(self.context),
        }
        if source:
            step["source"] = str(source)
        if context is not None:
            step["context"] = redact_payload(context)
            step["pre_action_context"] = redact_payload(context)
        if input is not None:
            step["input"] = redact_payload(input)
        if output is not None:
            step["output"] = redact_payload(output)
        if error is not None:
            step["error"] = redact_payload(error)
        if metadata:
            step["metadata"] = redact_payload(metadata)
        normalized = normalise_action(action, input=input, metadata=metadata, phase=phase)
        step["normalized_action"] = normalized
        if normalized.get("tool_name"):
            step["tool_name"] = normalized["tool_name"]
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
            "limits": {
                "max_steps": self.max_steps,
                "observed_steps": len(self.steps),
                "dropped_steps": self.dropped_steps,
                "overflowed": self.overflowed,
            },
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


def _step_tool_name(step: Mapping[str, Any]) -> str | None:
    normalized = step.get("normalized_action")
    if isinstance(normalized, Mapping) and normalized.get("tool_name"):
        return str(normalized["tool_name"])
    if step.get("tool_name"):
        return str(step["tool_name"])
    action = str(step.get("action") or "")
    if action.startswith("tool.") and action.split(".", 1)[1] not in {"call", "result", "error", "retry"}:
        return action.split(".", 1)[1]
    return None


def _step_arguments(step: Mapping[str, Any]) -> Mapping[str, Any]:
    normalized = step.get("normalized_action")
    if isinstance(normalized, Mapping) and isinstance(normalized.get("arguments"), Mapping):
        return normalized["arguments"]
    input_value = step.get("input")
    if isinstance(input_value, Mapping):
        for key in ("arguments", "args", "parameters", "tool_arguments"):
            if isinstance(input_value.get(key), Mapping):
                return input_value[key]
    return {}


def _matches_schema(value: Any, schema: Mapping[str, Any]) -> bool:
    expected_type = schema.get("type")
    if expected_type == "object" and not isinstance(value, Mapping):
        return False
    if expected_type == "array" and not isinstance(value, list):
        return False
    if expected_type == "string" and not isinstance(value, str):
        return False
    if expected_type == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
        return False
    if expected_type == "boolean" and not isinstance(value, bool):
        return False
    if "const" in schema and value != schema["const"]:
        return False
    if "enum" in schema and value not in schema["enum"]:
        return False
    if "pattern" in schema and isinstance(value, str) and not re.search(str(schema["pattern"]), value):
        return False
    return True


def _tool_argument_failure(tool: str, arguments: Mapping[str, Any], schema: Mapping[str, Any]) -> str | None:
    required = schema.get("required", [])
    if isinstance(required, list):
        missing = [str(key) for key in required if key not in arguments]
        if missing:
            return f"{tool}: missing required argument(s): {', '.join(missing)}"
    properties = schema.get("properties", {})
    if isinstance(properties, Mapping):
        for key, property_schema in properties.items():
            if key in arguments and isinstance(property_schema, Mapping) and not _matches_schema(arguments[key], property_schema):
                return f"{tool}: invalid argument {key}"
    if schema.get("additionalProperties") is False and isinstance(properties, Mapping):
        unknown = sorted(set(arguments) - set(properties))
        if unknown:
            return f"{tool}: unexpected argument(s): {', '.join(unknown)}"
    return None


def _contains_marker(value: Any, marker: str) -> bool:
    try:
        return marker in json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return False


_MARKER_START = re.compile(r"\[\[(MEMORY_SPARK_[A-Z0-9_]+)\]\]")


def _marker_syntax(value: Any) -> tuple[set[str], list[str]]:
    """Find machine markers in observable strings and validate their JSON bodies."""
    strings: list[str] = []

    def collect(item: Any) -> None:
        if isinstance(item, str):
            strings.append(item)
        elif isinstance(item, Mapping):
            for nested in item.values():
                collect(nested)
        elif isinstance(item, (list, tuple, set)):
            for nested in item:
                collect(nested)

    collect(value)
    names: set[str] = set()
    failures: list[str] = []
    for text in strings:
        for match in _MARKER_START.finditer(text):
            name = match.group(1)
            names.add(name)
            end_marker = f"[[/{name}]]"
            end = text.find(end_marker, match.end())
            if end < 0:
                failures.append(f"{name}: missing closing marker")
                continue
            body = text[match.end():end].strip()
            try:
                json.loads(body)
            except (TypeError, ValueError):
                failures.append(f"{name}: body is not valid JSON")
    return names, failures


def _nested_any(value: Any, paths: Sequence[str]) -> Any:
    for path in paths:
        found = _nested_value(value, path)
        if found is not None:
            return found
    return None


def evaluate_trajectory(
    trajectory: Mapping[str, Any],
    *,
    expected: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run deterministic gates before any semantic judge is called."""
    expected = expected or {}
    steps = trajectory.get("steps") if isinstance(trajectory, Mapping) else None
    steps = steps if isinstance(steps, list) else []
    final = trajectory.get("final") if isinstance(trajectory, Mapping) else {}
    final = final if isinstance(final, Mapping) else {}
    action_steps = [step for step in steps if isinstance(step, Mapping)]
    actions = [str(step.get("action")) for step in action_steps]
    tool_names = [tool for step in action_steps if (tool := _step_tool_name(step))]
    scores: list[dict[str, Any]] = []
    gates: dict[str, float] = {}

    def add(name: str, value: float, comment: str, *, step_id: str | None = None) -> None:
        score = _score(name, value, comment, step_id=step_id)
        scores.append(score)
        if step_id is None:
            gates[name] = score["value"]

    valid_sequence = (
        trajectory.get("schema_version") == TRAJECTORY_SCHEMA_VERSION
        and all(isinstance(step, Mapping) and step.get("sequence") == index for index, step in enumerate(steps, 1))
    )
    add("trajectory_schema", 1 if valid_sequence else 0, "Ordered trajectory schema is valid." if valid_sequence else "Trajectory schema or sequence is invalid.")

    max_steps = int(expected.get("max_steps", 512))
    limits = trajectory.get("limits") if isinstance(trajectory.get("limits"), Mapping) else {}
    within_budget = len(steps) <= max_steps and not bool(limits.get("overflowed"))
    add("step_budget", 1 if within_budget else 0, f"Observed {len(steps)} step(s); budget is {max_steps}." if within_budget else f"Step budget exceeded or recorder overflowed: {len(steps)} observed, budget {max_steps}.")

    terminal = final.get("status") == "completed" and bool(str(final.get("response") or "").strip())
    add("terminal_completion", 1 if terminal else 0, "Turn completed with a visible response." if terminal else "Turn did not complete with a visible response.")

    required = [str(item) for item in expected.get("required_actions", []) if item]
    missing = [item for item in required if item not in actions]
    if required:
        add("required_actions", 0 if missing else 1, "Missing required action(s): " + ", ".join(missing) if missing else "All required actions were observed.")

    forbidden = [str(item) for item in expected.get("forbidden_actions", []) if item]
    found = [item for item in forbidden if item in actions]
    if forbidden:
        add("forbidden_actions", 0 if found else 1, "Forbidden action(s) observed: " + ", ".join(found) if found else "No forbidden actions were observed.")

    alternatives = expected.get("allowed_action_sets") or expected.get("action_variants")
    if isinstance(alternatives, list) and alternatives:
        valid_path = False
        for alternative in alternatives:
            if not isinstance(alternative, list):
                continue
            position = 0
            for expected_action in alternative:
                try:
                    position = actions.index(str(expected_action), position) + 1
                except ValueError:
                    break
            else:
                valid_path = True
                break
        add("equivalent_valid_path", 1 if valid_path else 0, "Observed action order matches an allowed equivalent path." if valid_path else "Observed action order matches no allowed path.")

    allowed_tools = {str(tool) for tool in expected.get("allowed_tools", []) if tool}
    if allowed_tools:
        unexpected = sorted(set(tool_names) - allowed_tools)
        add("allowed_tools", 0 if unexpected else 1, "Unexpected tool(s): " + ", ".join(unexpected) if unexpected else "All observed tools are allowed.")

    argument_schemas = expected.get("tool_argument_schemas")
    if isinstance(argument_schemas, Mapping) and argument_schemas:
        for step in action_steps:
            tool = _step_tool_name(step)
            schema = argument_schemas.get(tool) if tool else None
            if not tool or not isinstance(schema, Mapping):
                continue
            failure = _tool_argument_failure(tool, _step_arguments(step), schema)
            if failure:
                add("tool_argument_schema", 0, failure, step_id=str(step.get("step_id") or "step"))
        if any(score["name"] == "tool_argument_schema" for score in scores):
            gates["tool_argument_schema"] = 0.0
        else:
            add("tool_argument_schema", 1, "All observed tool arguments match their case schemas.")

    required_markers = [str(marker) for marker in expected.get("required_markers", []) if marker]
    if required_markers or expected.get("marker_syntax") is True:
        marker_names, marker_failures = _marker_syntax(trajectory)
        missing_markers = [marker for marker in required_markers if marker not in marker_names]
        if expected.get("marker_syntax") is True and not marker_names:
            marker_failures.append("No machine marker was observed")
        problems = missing_markers + marker_failures
        add("marker_syntax", 0 if problems else 1, "Marker syntax failed: " + "; ".join(problems) if problems else "Required machine markers are present and valid JSON.")

    marker_grounding = expected.get("marker_grounding")
    if isinstance(marker_grounding, Mapping):
        ungrounded = []
        for marker, grounding in marker_grounding.items():
            marker_present = _contains_marker(trajectory, str(marker))
            grounded = bool(grounding) if isinstance(grounding, bool) else _contains_marker(trajectory, str(grounding))
            if marker_present and not grounded:
                ungrounded.append(str(marker))
        add("marker_grounding", 0 if ungrounded else 1, "Ungrounded marker(s): " + ", ".join(ungrounded) if ungrounded else "Markers are grounded in the case evidence.")

    retry_count = sum(1 for step in action_steps if any(token in str(step.get("action", "")).lower() for token in ("retry", "error", "failed")) or step.get("error"))
    if "max_retries" in expected:
        retry_limit = int(expected["max_retries"])
        add("retry_budget", 1 if retry_count <= retry_limit else 0, f"Observed {retry_count} retry/error step(s); budget is {retry_limit}.")
    successful_calls: dict[tuple[str, str], int] = {}
    for step in action_steps:
        tool = _step_tool_name(step)
        if not tool or step.get("error"):
            continue
        key = (tool, _sha256(_step_arguments(step)))
        successful_calls[key] = successful_calls.get(key, 0) + 1
    repeat_limit = int(expected.get("max_repeated_success", 1))
    repeated = max(successful_calls.values(), default=1) > repeat_limit
    if expected.get("max_repeated_success") is not None:
        add("repetition_control", 0 if repeated else 1, "A successful tool call was repeated too many times." if repeated else "Successful tool calls are not unnecessarily repeated.")

    step_failures = []
    for step in action_steps:
        normalized = step.get("normalized_action")
        category = normalized.get("category") if isinstance(normalized, Mapping) else None
        if step.get("error") or category == "error":
            step_failures.append(step)
    for step in step_failures:
        add("step_failure", 0, f"Step failed: {step.get('action')}", step_id=str(step.get("step_id") or "step"))

    assertions = expected.get("state_assertions") or {}
    if isinstance(assertions, Mapping) and assertions:
        failed = [path for path, value in assertions.items() if _nested_value(final.get("state"), str(path)) != value]
        add("state_assertions", 0 if failed else 1, "State assertion(s) failed: " + ", ".join(failed) if failed else "All expected final-state assertions passed.")

    for gate_name in ("entitlement_assertions", "ownership_assertions", "revision_assertions"):
        assertions = expected.get(gate_name) or {}
        if not isinstance(assertions, Mapping) or not assertions:
            continue
        failed = [path for path, value in assertions.items() if _nested_value(final.get("state"), str(path)) != value]
        add(gate_name.replace("_assertions", ""), 0 if failed else 1, "Assertion(s) failed: " + ", ".join(failed) if failed else "All case assertions passed.")

    ownership = expected.get("ownership")
    if isinstance(ownership, Mapping) and ownership:
        state = final.get("state") if isinstance(final.get("state"), Mapping) else {}
        access = state.get("access_control") if isinstance(state.get("access_control"), Mapping) else {}
        failed = [key for key, value in ownership.items() if access.get(str(key)) != value]
        add("ownership", 0 if failed else 1, "Ownership assertion(s) failed: " + ", ".join(failed) if failed else "Project and user ownership checks passed.")

    required_artifacts = expected.get("required_artifacts") or []
    if required_artifacts:
        artifact_values = _nested_any(final.get("state"), ("artifacts", "artifact_paths", "source_paths")) or []
        artifact_values = {str(item.get("path") if isinstance(item, Mapping) else item) for item in artifact_values}
        missing = [str(path) for path in required_artifacts if str(path) not in artifact_values]
        add("artifact_state", 0 if missing else 1, "Missing artifact(s): " + ", ".join(missing) if missing else "Required artifacts are present in final state.")

    artifact_assertions = expected.get("artifact_assertions") or []
    if artifact_assertions:
        artifact_state = final.get("state") if isinstance(final.get("state"), Mapping) else {}
        artifact_values = _nested_any(artifact_state, ("artifacts", "artifact_paths", "source_paths")) or []
        artifact_values = {str(item.get("path") if isinstance(item, Mapping) else item) for item in artifact_values}
        failed_artifacts = []
        for item in artifact_assertions:
            if isinstance(item, str):
                path = item
                required_exists = True
            elif isinstance(item, Mapping):
                path = str(item.get("path") or "")
                required_exists = bool(item.get("exists", True))
            else:
                continue
            if not path:
                failed_artifacts.append("<empty-path>")
                continue
            present = path in artifact_values
            if required_exists and not present:
                # A local evaluator may also assert a concrete, already
                # materialised file. The provider never receives this path.
                present = Path(path).exists()
            if (required_exists and not present) or (not required_exists and present):
                failed_artifacts.append(path)
        add("artifact_existence", 0 if failed_artifacts else 1, "Artifact existence assertion(s) failed: " + ", ".join(failed_artifacts) if failed_artifacts else "Artifact existence assertions passed.")

    response_requirements = expected.get("response_requirements") or {}
    response = str(final.get("response") or "")
    if isinstance(response_requirements, Mapping):
        required_phrases = [str(item) for item in response_requirements.get("contains", []) if item]
        forbidden_phrases = [str(item) for item in response_requirements.get("excludes", []) if item]
        folded_response = response.casefold()
        missing_phrases = [item for item in required_phrases if item.casefold() not in folded_response]
        found_phrases = [item for item in forbidden_phrases if item.casefold() in folded_response]
        if required_phrases or forbidden_phrases:
            add("response_contract", 0 if missing_phrases or found_phrases else 1, "Response contract failed." if missing_phrases or found_phrases else "Response contract passed.")

    expected_skill_hash = expected.get("skill_manifest_sha256")
    if expected_skill_hash:
        actual_manifest = trajectory.get("skill_manifest")
        actual_hash = actual_manifest.get("sha256") if isinstance(actual_manifest, Mapping) else None
        add("skill_manifest", 1 if actual_hash == expected_skill_hash else 0, "Skill manifest matches the case." if actual_hash == expected_skill_hash else "Skill manifest does not match the case.")

    # Stable category scores make comparison matrices useful even when a case
    # has optional gates. Every category is deterministic and explainable.
    execution_names = {"step_budget", "allowed_tools", "tool_argument_schema", "retry_budget", "repetition_control"}
    state_names = {"state_assertions", "entitlement", "ownership", "revision", "artifact_state", "artifact_existence"}
    skill_names = {"required_actions", "forbidden_actions", "allowed_tools", "skill_manifest", "marker_syntax", "marker_grounding"}
    final_names = {"terminal_completion", "response_contract"}
    def average(names: set[str], default: float = 1.0) -> float:
        values = [gates[name] for name in names if name in gates]
        return sum(values) / len(values) if values else default

    add("trajectory_quality", average({"trajectory_schema", "step_budget", "terminal_completion"}), "Ordered, bounded, terminal trajectory quality.")
    add("skill_selection_adherence", average(skill_names), "Skill and action selection follows the case constraints.")
    add("execution_quality", average(execution_names) * (0.0 if step_failures else 1.0), "Execution respects tool, retry, repetition, and step constraints.")
    add("state_correctness", average(state_names), "Final persisted state satisfies the case assertions.")
    add("final_response_quality", average(final_names, 1.0 if terminal else 0.0), "The final response meets the terminal and response contract.")
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
        "rubric_version": JUDGE_RUBRIC_VERSION,
        "privacy_policy_version": PRIVACY_POLICY_VERSION,
        "task": redact_payload(task),
        "available_tools": redact_payload(available_tools or []),
        "ordered_steps": redact_payload(trajectory.get("steps", [])),
        "final_response": redact_payload(final.get("response")),
        "stop_reason": final.get("stop_reason"),
        "final_state": redact_payload(final.get("state")),
        "rubric": dict(JUDGE_RUBRIC),
    }


def build_judge_prompt(judge_input: Mapping[str, Any], *, calibration_examples: Iterable[Mapping[str, Any]] = ()) -> str:
    """Create the full-run, calibrated input for an external semantic judge."""
    payload = {
        "instructions": "Score each rubric category from 0 to 1. Return JSON only with {scores:{category:number}, comments:{category:string}}. Cite ordered step IDs or final-state fields when explaining a score. Do not infer private reasoning.",
        "calibration_examples": redact_payload(list(calibration_examples)),
        "input": redact_payload(judge_input),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


async def run_judges(
    judges: Iterable[Callable[[Mapping[str, Any]], Any]],
    judge_input: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Run pluggable semantic judges and normalize their score shape."""
    scores: list[dict[str, Any]] = []
    for judge in judges:
        result = judge(judge_input)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, Mapping):
            raise TypeError("judge must return a mapping")
        judge_name = str(result.get("judge") or getattr(judge, "name", None) or "llm_judge")
        raw_scores = result.get("scores") if isinstance(result.get("scores"), Mapping) else result
        comments = result.get("comments") if isinstance(result.get("comments"), Mapping) else {}
        for category in JUDGE_RUBRIC:
            if category not in raw_scores:
                continue
            try:
                value = float(raw_scores[category])
            except (TypeError, ValueError):
                value = 0.0
            scores.append(_score(
                f"judge.{judge_name}.{category}",
                value,
                str(comments.get(category) or result.get("comment") or ""),
            ))
    return scores


class OpenAICompatibleJudge:
    """Optional JSON judge for an OpenAI-compatible provider endpoint.

    The evaluator remains runnable without this class; callers opt in by
    passing a judge to ``MemoirEvaluationRunner`` or the CLI. Calibration
    examples are included in the prompt and never published as raw traces.
    """

    name = "openai-compatible"

    def __init__(self, *, base_url: str, model: str, api_key: str = "", calibration_examples: Iterable[Mapping[str, Any]] = (), timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.calibration_examples = list(calibration_examples)
        self.timeout = timeout

    async def __call__(self, judge_input: Mapping[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "You are a calibrated evaluator for an observable memoir-agent trajectory."},
                {"role": "user", "content": build_judge_prompt(judge_input, calibration_examples=self.calibration_examples)},
            ],
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=body)
            response.raise_for_status()
            payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        parsed = json.loads(content) if isinstance(content, str) else content
        if not isinstance(parsed, Mapping):
            raise ValueError("Judge response must be a JSON object")
        return {"judge": self.name, **parsed}


HttpJsonJudge = OpenAICompatibleJudge


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
            "input": minimize_for_langfuse(task),
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
        metadata["trajectory_schema_version"] = str(trajectory.get("schema_version") or TRAJECTORY_SCHEMA_VERSION)
        metadata["privacy_policy_version"] = PRIVACY_POLICY_VERSION
        metadata["local_evidence"] = "available-in-runner-result"
        self.observation.update(
            output=minimize_for_langfuse(trajectory),
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
            case_id = self.correlation.get("case_id", "case")
            variant = self.correlation.get("variant", "default")
            score_id = hashlib.sha256(f"{run_id}:{case_id}:{variant}:{evaluator_version}:{step_id}:{name}".encode()).hexdigest()
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
    """Run isolated local cases through the real application callback boundary."""

    def __init__(
        self,
        task: Callable[[Mapping[str, Any], Mapping[str, str]], Any],
        *,
        publisher: LangfusePublisher | None = None,
        evaluator: Callable[[Mapping[str, Any], Mapping[str, Any]], list[dict[str, Any]]] = evaluate_trajectory,
        judges: Iterable[Callable[[Mapping[str, Any]], Any]] = (),
        available_tools: Any = None,
    ) -> None:
        self.task = task
        self.publisher = publisher
        self.evaluator = evaluator
        self.judges = list(judges)
        self.available_tools = available_tools
        self.default_skill_manifest = build_skill_manifest(Path(__file__).resolve().parents[2] / "skills")

    async def run_case(self, case: Mapping[str, Any], *, run_id: str | None = None, variant: Mapping[str, Any] | str | None = None) -> dict[str, Any]:
        case_id = str(case.get("id") or case.get("case_id") or uuid4())
        variant_values = variant if isinstance(variant, Mapping) else ({"variant": str(variant)} if variant else {})
        correlation = normalise_correlation({
            **(case.get("metadata") if isinstance(case.get("metadata"), Mapping) else {}),
            **variant_values,
            "run_id": run_id or case.get("run_id") or uuid4(),
            "case_id": case_id,
            "dataset": case.get("dataset") or case.get("dataset_name"),
            "dataset_version": case.get("dataset_version") or case.get("version"),
            "skill_hash": case.get("skill_manifest_sha256") or self.default_skill_manifest.get("sha256"),
            "generation_name": case.get("generation_name") or "memoir-agent-evaluation",
            "model": case.get("model") or os.getenv("MEMORY_SPARK_LLM_MODEL"),
            "provider": case.get("provider") or "llm_provider",
            "evaluator_version": case.get("evaluator_version") or EVALUATION_RUBRIC_VERSION,
            "rubric_version": case.get("rubric_version") or EVALUATION_RUBRIC_VERSION,
            "judge_rubric_version": case.get("judge_rubric_version") or JUDGE_RUBRIC_VERSION,
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
            if self.judges:
                judge_input = build_judge_input(
                    task=case.get("input", case),
                    trajectory=trajectory,
                    available_tools=self.available_tools if self.available_tools is not None else case.get("available_tools", []),
                )
                scores.extend(await run_judges(self.judges, judge_input))
            if sink is not None:
                sink.publish(trajectory, scores)
            failures = [
                {key: score.get(key) for key in ("name", "value", "comment", "step_id") if key in score}
                for score in scores if float(score.get("value", 1)) < 1
            ]
            result = {
                "case_id": case_id,
                "correlation": correlation,
                "scores": scores,
                "result": redact_payload(result),
                "trajectory_sha256": _sha256(trajectory),
                "failure_evidence": failures,
            }
            if sink is not None:
                result["langfuse"] = {
                    "trace_id": sink.trace_id,
                    "observation_id": sink.observation_id,
                }
            return result

    async def run(
        self,
        cases: Iterable[Mapping[str, Any]],
        *,
        run_id: str | None = None,
        variants: Iterable[Mapping[str, Any] | str] | None = None,
        max_concurrency: int = 1,
    ) -> list[dict[str, Any]]:
        cases_list = list(cases)
        variants_list = list(variants or [None])
        work = [(case, variant) for case in cases_list for variant in variants_list]
        semaphore = asyncio.Semaphore(max(1, int(max_concurrency)))

        async def run_one(case: Mapping[str, Any], variant: Mapping[str, Any] | str | None):
            async with semaphore:
                return await self.run_case(case, run_id=run_id, variant=variant)

        return list(await asyncio.gather(*(run_one(case, variant) for case, variant in work)))


def comparison_matrix(results: Iterable[Mapping[str, Any]], *, baseline_variant: str | None = None) -> list[dict[str, Any]]:
    """Return per-case score deltas against a named model/provider baseline."""
    grouped: dict[str, dict[str, Mapping[str, Any]]] = {}
    for result in results:
        case_id = str(result.get("case_id") or "")
        correlation = result.get("correlation") if isinstance(result.get("correlation"), Mapping) else {}
        variant = str(correlation.get("variant") or "default")
        grouped.setdefault(case_id, {})[variant] = result
    rows: list[dict[str, Any]] = []
    for case_id, variants in grouped.items():
        baseline_name = baseline_variant or ("default" if "default" in variants else next(iter(variants), ""))
        baseline = variants.get(baseline_name)
        if not baseline:
            continue
        baseline_scores = {str(score.get("name")): float(score.get("value", 0)) for score in baseline.get("scores", [])}
        for variant, result in variants.items():
            score_values = {str(score.get("name")): float(score.get("value", 0)) for score in result.get("scores", [])}
            rows.append({
                "case_id": case_id,
                "variant": variant,
                "baseline_variant": baseline_name,
                "scores": score_values,
                "deltas": {name: value - baseline_scores.get(name, 0.0) for name, value in score_values.items()},
            })
    return rows
