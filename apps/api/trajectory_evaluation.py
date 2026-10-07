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
import math
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Callable, Iterable, Mapping, Sequence
from uuid import uuid4

import httpx


TRAJECTORY_SCHEMA_VERSION = "memoir-trajectory/1"
EVALUATION_RUBRIC_VERSION = "memoir-trajectory-rubric/2"
JUDGE_RUBRIC_VERSION = "memoir-judge-rubric/1"
PRIVACY_POLICY_VERSION = "memoir-evaluation-privacy/1"
JUDGE_CALIBRATION_SCHEMA_VERSION = "memoir-judge-calibration/1"
JUDGE_CALIBRATION_REVIEW_STATUS = "human-reviewed"
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
_OBSERVATION_LINK_FIELDS = (
    "observation_id",
    "parent_observation_id",
    "trace_id",
    "span_id",
    "parent_span_id",
    "root_observation_id",
)

JUDGE_RUBRIC: dict[str, str] = {
    "tool_appropriateness": "Choose only tools that advance the task and use the narrowest valid tool for the evidence available.",
    "evidence_use": "Ground claims in returned evidence and preserve uncertainty; never invent facts absent from the case.",
    "recovery": "Recover from tool errors with a bounded, useful retry or a clear safe stop.",
    "repetition": "Avoid duplicate successful actions and unproductive loops.",
    "stopping": "Stop once the task is complete or a safe, explicit blocker is reached.",
    "instruction_adherence": "Follow the task, entitlement, privacy, ownership, and output constraints.",
    "final_response_quality": "Give a concise, accurate, uncertainty-preserving response that matches the requested outcome.",
}


def load_judge_calibration(payload: Any) -> list[Mapping[str, Any]]:
    """Load only calibration examples with explicit human-review evidence."""
    if not isinstance(payload, Mapping):
        raise ValueError("Judge calibration must be an object with schema_version, review_status, and examples")
    if payload.get("schema_version") != JUDGE_CALIBRATION_SCHEMA_VERSION:
        raise ValueError("Judge calibration schema version is missing or unsupported")
    if payload.get("review_status") != JUDGE_CALIBRATION_REVIEW_STATUS:
        raise ValueError("Judge calibration must be marked human-reviewed before it can be used")
    if not payload.get("reviewer") or not payload.get("reviewed_at"):
        raise ValueError("Judge calibration needs reviewer and reviewed_at evidence")
    examples = payload.get("examples")
    if not isinstance(examples, list) or not examples:
        raise ValueError("Judge calibration must contain at least one reviewed example")
    for example in examples:
        if not isinstance(example, Mapping):
            raise ValueError("Each judge calibration example must be an object")
        if not example.get("case_id") or not isinstance(example.get("scores"), Mapping):
            raise ValueError("Each judge calibration example needs case_id and scores")
        if not example.get("rationale"):
            raise ValueError("Each judge calibration example needs a human rationale")
        for category, value in example["scores"].items():
            if category not in JUDGE_RUBRIC:
                raise ValueError(f"Unknown judge calibration category: {category}")
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
                raise ValueError(f"Judge calibration score must be between 0 and 1: {category}")
    return examples


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
        "application_revision": "application_revision",
        "app_revision": "application_revision",
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
        "request_id": "request_id",
        "diagnostic_request_id": "request_id",
        "round_id": "round_id",
        "evaluation_round_id": "round_id",
        "trace_id": "trace_id",
        "observation_id": "observation_id",
        "job_id": "job_id",
        "checkpoint_id": "checkpoint_id",
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
    """Hash checked-in skill files so runs pin instructions and references."""
    root = Path(skill_root)
    entries: list[dict[str, Any]] = []
    if root.is_dir():
        for skill_dir in sorted(path for path in root.iterdir() if path.is_dir() and not path.name.startswith(".")):
            files: list[dict[str, str]] = []
            for path in sorted(skill_dir.rglob("*")):
                if not path.is_file() or any(part.startswith(".") for part in path.relative_to(skill_dir).parts):
                    continue
                try:
                    content = path.read_bytes()
                except OSError:
                    continue
                files.append({
                    "path": path.relative_to(skill_dir).as_posix(),
                    "sha256": hashlib.sha256(content).hexdigest(),
                })
            if files:
                entries.append({
                    "name": skill_dir.name,
                    "files": files,
                    "sha256": _sha256(files),
                })
    return {"skills": entries, "sha256": _sha256(entries)}


def build_application_revision(repo_root: str | Path | None = None) -> str:
    """Resolve an explicit or checked-out revision for experiment metadata."""
    configured = os.getenv("MEMORY_SPARK_APP_REVISION", "").strip()
    if configured:
        return configured[:256]
    root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    revision = result.stdout.strip()
    if result.returncode != 0 or not revision:
        return "unknown"
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return revision[:256]
    if status.returncode == 0 and status.stdout.strip():
        dirty_hash = hashlib.sha256(status.stdout.encode("utf-8")).hexdigest()[:12]
        return f"{revision}-dirty-{dirty_hash}"[:256]
    return revision[:256]


def _protocol_summary(message: Mapping[str, Any]) -> dict[str, Any]:
    """Keep protocol shape and tool results while dropping private fields."""
    summary: dict[str, Any] = {}
    method = str(message.get("method") or "")
    for key in ("id", "method"):
        if key in message:
            summary[key] = message[key]
    if "params" in message:
        summary["params"] = redact_payload(
            _filter_protocol_message_value(method, message.get("params"))
        )
    if "result" in message:
        summary["result"] = redact_payload(
            _filter_protocol_message_value(method, message.get("result"))
        )
    if "error" in message:
        summary["error"] = redact_payload(message.get("error"))
    return summary


_PRIVATE_PROTOCOL_ITEM_TYPES = {
    "analysis",
    "chain-of-thought",
    "chainofthought",
    "reasoning",
    "reasoning_summary",
}

_PRIVATE_REASONING_DELTA_METHODS = {
    "item/reasoning/summarytextdelta",
    "item/reasoning/textdelta",
}


def _filter_protocol_private_items(value: Any) -> Any:
    """Remove private reasoning payloads before local or provider export."""
    if isinstance(value, Mapping):
        item_type = str(value.get("type") or "").strip().casefold().replace("_", "-")
        if item_type in {item.replace("_", "-") for item in _PRIVATE_PROTOCOL_ITEM_TYPES}:
            filtered: dict[str, Any] = {
                key: value[key]
                for key in ("id", "type", "status", "phase")
                if key in value and isinstance(value[key], (str, int, float, bool))
            }
            for key in ("summary", "content", "text"):
                if key in value:
                    filtered[key] = {"redacted": "private-reasoning"}
            return filtered
        return {str(key): _filter_protocol_private_items(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_filter_protocol_private_items(item) for item in value]
    return value


def _filter_protocol_message_value(method: str, value: Any) -> Any:
    """Apply method-specific privacy filtering before recorder/export redaction.

    Reasoning delta notifications carry private text in a flat ``delta`` field
    rather than in a typed reasoning item.  Redact every delta-shaped value for
    those methods so future nested provider payloads cannot leak it either.
    """
    filtered = _filter_protocol_private_items(value)
    if method.casefold() not in _PRIVATE_REASONING_DELTA_METHODS:
        return filtered

    def redact_deltas(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {
                str(key): {"redacted": "private-reasoning"}
                if str(key).casefold() == "delta"
                else redact_deltas(nested)
                for key, nested in item.items()
            }
        if isinstance(item, (list, tuple, set)):
            return [redact_deltas(nested) for nested in item]
        return item

    return redact_deltas(filtered)


def _protocol_action_metadata(message: Mapping[str, Any]) -> dict[str, Any]:
    """Extract observable tool fields from Codex item protocol events."""
    candidates: list[Mapping[str, Any]] = []
    for container_key in ("params", "result"):
        container = message.get(container_key)
        if not isinstance(container, Mapping):
            continue
        candidates.append(container)
        for item_key in ("item", "toolCall", "tool_call", "call"):
            item = container.get(item_key)
            if isinstance(item, Mapping):
                candidates.insert(0, item)
    tool_name = None
    arguments = None
    for candidate in candidates:
        for key in ("tool_name", "tool", "name", "function_name", "function", "mcpToolName"):
            value = candidate.get(key)
            if isinstance(value, str) and value.strip():
                tool_name = value.strip()
                break
        for key in ("tool_arguments", "arguments", "args", "parameters", "input"):
            value = candidate.get(key)
            if isinstance(value, Mapping):
                arguments = value
                break
        if tool_name or arguments is not None:
            break
    metadata: dict[str, Any] = {}
    if tool_name:
        metadata["tool_name"] = tool_name
    if arguments is not None:
        metadata["tool_arguments"] = arguments
    params = message.get("params")
    item = params.get("item") if isinstance(params, Mapping) else None
    if isinstance(item, Mapping) and item.get("id") is not None:
        metadata["protocol_item_id"] = str(item["id"])[:256]
        method = str(message.get("method") or "")
        if method in {"item/started", "item/completed"}:
            metadata["protocol_lifecycle"] = method.rsplit("/", 1)[-1]
        failed = item.get("status") in {"failed", "declined"} or item.get("exitCode") not in (None, 0)
        if failed:
            metadata["protocol_failed"] = True
    return metadata


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
        observation_id: str | None = None,
        parent_observation_id: str | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        parent_span_id: str | None = None,
        root_observation_id: str | None = None,
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
        for key, value in {
            "observation_id": observation_id,
            "parent_observation_id": parent_observation_id,
            "trace_id": trace_id,
            "span_id": span_id,
            "parent_span_id": parent_span_id,
            "root_observation_id": root_observation_id,
        }.items():
            if value is not None and not isinstance(value, (Mapping, list, tuple, set)):
                step[key] = str(value)[:256]
        self.steps.append(step)
        return step

    def record_protocol(self, message: Mapping[str, Any], *, phase: str = "codex") -> dict[str, Any]:
        method = message.get("method")
        action = str(method or ("protocol.error" if "error" in message else "protocol.response"))
        metadata = _protocol_action_metadata(message)
        step = self.record(
            phase,
            action,
            output=_protocol_summary(message),
            metadata=metadata or None,
        )
        for key in ("protocol_item_id", "protocol_lifecycle", "protocol_failed"):
            if key in metadata:
                step[key] = metadata[key]
        return step

    def append_external(self, steps: Iterable[Mapping[str, Any]], *, source: str) -> None:
        """Append worker steps while preserving their evidence and local order."""
        for external in steps:
            if not isinstance(external, Mapping):
                continue
            external_input = external.get("input")
            if isinstance(external_input, Mapping):
                external_input = dict(external_input)
            else:
                external_input = {}
            # Worker adapters have used both the normalized input shape and
            # top-level tool fields.  Preserve both without allowing a
            # top-level field to overwrite an explicit input value.
            for key in ("tool_name", "tool", "name", "function_name", "function"):
                if key in external and key not in external_input:
                    external_input[key] = external.get(key)
            for key in ("tool_arguments", "arguments", "args", "parameters"):
                if key in external and key not in external_input:
                    external_input[key] = external.get(key)
            step = self.record(
                str(external.get("phase") or "worker"),
                str(external.get("action") or "worker.event"),
                context=external.get("context"),
                input=external_input or (external.get("input") if external.get("input") is not None else None),
                output=external.get("output"),
                error=external.get("error"),
                metadata=external.get("metadata"),
                source=source,
            )
            if not step.get("accepted", True):
                continue
            if external.get("step_id") is not None:
                step["external_step_id"] = str(external["step_id"])[:256]
            if external.get("sequence") is not None:
                try:
                    step["external_sequence"] = int(external["sequence"])
                except (TypeError, ValueError):
                    pass

            # Keep the small, non-content identifiers needed to navigate a
            # worker trace.  They are deliberately allow-listed rather than
            # copying arbitrary worker metadata into the application record.
            linkage_sources = [external]
            for key in ("observation", "span", "trace"):
                nested = external.get(key)
                if isinstance(nested, Mapping):
                    nested_source = dict(nested)
                    # SDK objects commonly expose their identifier as `id`.
                    # Interpret that shorthand only in its typed nested
                    # container; a worker event's own `id` is not telemetry
                    # linkage and must not be promoted accidentally.
                    if nested.get("id") is not None:
                        if key == "observation":
                            nested_source.setdefault("observation_id", nested["id"])
                        elif key == "span":
                            nested_source.setdefault("span_id", nested["id"])
                        elif key == "trace":
                            nested_source.setdefault("trace_id", nested["id"])
                    linkage_sources.append(nested_source)
            metadata = external.get("metadata")
            if isinstance(metadata, Mapping):
                linkage_sources.append(metadata)
            aliases = {
                "observation_id": ("observation_id", "observationId"),
                "parent_observation_id": ("parent_observation_id", "parentObservationId", "parent_id", "parentId"),
                "trace_id": ("trace_id", "traceId"),
                "span_id": ("span_id", "spanId"),
                "parent_span_id": ("parent_span_id", "parentSpanId"),
                "root_observation_id": ("root_observation_id", "rootObservationId"),
            }
            for target, keys in aliases.items():
                value = next(
                    (candidate[key] for candidate in linkage_sources for key in keys
                     if candidate.get(key) is not None),
                    None,
                )
                if value is not None and not isinstance(value, (Mapping, list, tuple, set)):
                    step[target] = str(value)[:256]
            normalized = external.get("normalized_action")
            if isinstance(normalized, Mapping):
                step["normalized_action"] = redact_payload(normalized)
                if normalized.get("tool_name") and not step.get("tool_name"):
                    step["tool_name"] = str(normalized["tool_name"])[:256]
            external_metadata = external.get("metadata")
            for key in ("protocol_item_id", "protocol_lifecycle", "protocol_failed"):
                value = external.get(key)
                if value is None and isinstance(external_metadata, Mapping):
                    value = external_metadata.get(key)
                if value is not None and not isinstance(value, (Mapping, list, tuple, set)):
                    step[key] = value if isinstance(value, bool) else str(value)[:256]

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


def _contains_mapping(actual: Any, expected: Any) -> bool:
    """Return whether expected is a bounded recursive subset of actual."""
    if isinstance(expected, Mapping):
        return isinstance(actual, Mapping) and all(
            key in actual and _contains_mapping(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and actual == expected
    return actual == expected


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
    completed_protocol_calls: set[tuple[str, str, str]] = set()
    for step in action_steps:
        tool = _step_tool_name(step)
        if not tool or step.get("error"):
            continue
        protocol_item_id = str(step.get("protocol_item_id") or "").strip()
        if protocol_item_id:
            # Codex emits item/started and item/completed for one logical
            # operation. Preserve both events, but count only one successful
            # completion for repetition control.
            if step.get("protocol_lifecycle") != "completed" or step.get("protocol_failed"):
                continue
        key = (tool, _sha256(_step_arguments(step)))
        if protocol_item_id:
            protocol_key = (protocol_item_id, key[0], key[1])
            if protocol_key in completed_protocol_calls:
                continue
            completed_protocol_calls.add(protocol_key)
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
    unrecovered_failures = []
    for failed_step in step_failures:
        failed_tool = _step_tool_name(failed_step)
        failed_args = _sha256(_step_arguments(failed_step))
        recovered = any(
            candidate.get("sequence", 0) > failed_step.get("sequence", 0)
            and not candidate.get("error")
            and _step_tool_name(candidate) == failed_tool
            and _sha256(_step_arguments(candidate)) == failed_args
            for candidate in action_steps
        )
        if not recovered:
            unrecovered_failures.append(failed_step)
    if step_failures:
        add("recovery", 0 if unrecovered_failures else 1, "Failed step(s) were not recovered." if unrecovered_failures else "Transient failed step(s) were recovered by a bounded repeat.")

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

    task_result_assertions = expected.get("task_result_assertions") or []
    if isinstance(task_result_assertions, list) and task_result_assertions:
        state = final.get("state") if isinstance(final.get("state"), Mapping) else {}
        task_results = state.get("task_results") if isinstance(state.get("task_results"), list) else []
        failed_tasks = []
        for assertion in task_result_assertions:
            if not isinstance(assertion, Mapping):
                failed_tasks.append("<invalid-assertion>")
                continue
            kind = str(assertion.get("kind") or "")
            candidates = [task for task in task_results if isinstance(task, Mapping) and task.get("kind") == kind]
            if not candidates or not any(_contains_mapping(candidate, assertion) for candidate in candidates):
                failed_tasks.append(kind or "<missing-kind>")
        add(
            "task_result",
            0 if failed_tasks else 1,
            "Deterministic task result assertion(s) failed: " + ", ".join(failed_tasks)
            if failed_tasks else "Deterministic task result assertions passed.",
        )

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

    expected_skills = expected.get("enabled_skills")
    if isinstance(expected_skills, list):
        context = trajectory.get("context") if isinstance(trajectory.get("context"), Mapping) else {}
        actual_skills = context.get("enabled_skills")
        actual_manifest = trajectory.get("skill_manifest")
        manifest_names = {
            str(entry.get("name"))
            for entry in (actual_manifest.get("skills", []) if isinstance(actual_manifest, Mapping) else [])
            if isinstance(entry, Mapping) and entry.get("name")
        }
        expected_names = {str(skill) for skill in expected_skills if skill}
        actual_names = {str(skill) for skill in actual_skills} if isinstance(actual_skills, list) else set()
        valid = actual_names == expected_names and expected_names.issubset(manifest_names)
        add(
            "enabled_skills",
            1 if valid else 0,
            "Enabled skills match the case and checked-in manifest."
            if valid else "Enabled skills do not match the case or checked-in manifest.",
        )

    if expected.get("require_observation_linkage"):
        missing = [
            str(step.get("step_id") or "step")
            for step in action_steps
            if not str(step.get("observation_id") or "").strip()
        ]
        add(
            "observation_linkage",
            0 if missing else 1,
            "Missing worker observation identifier(s): " + ", ".join(missing)
            if missing else "Every observed step has a worker observation identifier.",
        )

    if expected.get("require_parent_observation_linkage"):
        missing = [
            str(step.get("step_id") or "step")
            for step in action_steps
            if not str(step.get("parent_observation_id") or "").strip()
        ]
        add(
            "parent_observation_linkage",
            0 if missing else 1,
            "Missing parent observation identifier(s): " + ", ".join(missing)
            if missing else "Every observed step has a parent observation identifier.",
        )

    # Stable category scores make comparison matrices useful even when a case
    # has optional gates. Every category is deterministic and explainable.
    execution_names = {"step_budget", "allowed_tools", "tool_argument_schema", "retry_budget", "repetition_control", "recovery"}
    state_names = {"state_assertions", "entitlement", "ownership", "revision", "artifact_state", "artifact_existence", "task_result"}
    skill_selection_names = {"required_actions", "forbidden_actions", "equivalent_valid_path", "allowed_tools", "enabled_skills"}
    skill_adherence_names = {"skill_manifest", "marker_syntax", "marker_grounding"}
    final_names = {"terminal_completion", "response_contract"}
    def average(names: set[str], default: float = 1.0) -> float:
        values = [gates[name] for name in names if name in gates]
        return sum(values) / len(values) if values else default

    add("trajectory_quality", average({"trajectory_schema", "step_budget", "terminal_completion"}), "Ordered, bounded, terminal trajectory quality.")
    selection_score = average(skill_selection_names)
    adherence_score = average(skill_adherence_names)
    add("skill_selection", selection_score, "The selected skill/action path follows the case constraints.")
    add("skill_adherence", adherence_score, "The observed skill output follows its manifest and marker contracts.")
    # Keep the combined name for existing dashboards while exposing the two
    # separately actionable dimensions above.
    add("skill_selection_adherence", (selection_score + adherence_score) / 2, "Skill selection and adherence follow the case constraints.")
    add("execution_quality", average(execution_names), "Execution respects tool, retry, repetition, recovery, and step constraints.")
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


def build_judge_prompt(
    judge_input: Mapping[str, Any],
    *,
    calibration_examples: Iterable[Mapping[str, Any]] = (),
    instructions: str | None = None,
) -> str:
    """Create the full-run, calibrated input for an external semantic judge."""
    payload = {
        "instructions": instructions or "Score each rubric category from 0 to 1. Return JSON only with {scores:{category:number}, comments:{category:string}}. Cite ordered step IDs or final-state fields when explaining a score. Do not infer private reasoning.",
        "calibration_examples": redact_payload(list(calibration_examples)),
        "input": redact_payload(judge_input),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


async def run_judges(
    judges: Iterable[Callable[[Mapping[str, Any]], Any]],
    judge_input: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Run pluggable semantic judges and normalize their score shape.

    This compatibility wrapper returns only scores.  The evaluation runner
    uses :func:`run_judges_report` so provider errors remain explicit evidence
    instead of becoming deterministic acceptance failures.
    """
    report = await run_judges_report(judges, judge_input)
    return report["scores"]


async def run_judges_report(
    judges: Iterable[Callable[[Mapping[str, Any]], Any]],
    judge_input: Mapping[str, Any],
) -> dict[str, Any]:
    """Run semantic judges while separating advisory evidence from gates."""
    scores: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    for judge in judges:
        configured_name = str(getattr(judge, "name", None) or "llm_judge")
        try:
            result = judge(judge_input)
            if inspect.isawaitable(result):
                result = await result
            if not isinstance(result, Mapping):
                raise TypeError("judge must return a mapping")
        except Exception as error:
            last_call = getattr(judge, "last_call", None)
            receipt = {
                "judge": configured_name,
                "status": "unavailable",
                "error_type": type(error).__name__,
            }
            if isinstance(last_call, Mapping):
                receipt["call"] = redact_payload(last_call)
            receipts.append(receipt)
            continue

        judge_name = str(result.get("judge") or configured_name)
        explicit_status = str(result.get("status") or "scored").strip().lower()
        if explicit_status in {"unavailable", "error", "blocked"}:
            receipt = {
                "judge": judge_name,
                "status": "unavailable" if explicit_status != "blocked" else "blocked",
            }
            if result.get("reason"):
                receipt["reason"] = str(result["reason"])[:256]
            receipts.append(receipt)
            continue
        raw_scores = result.get("scores") if isinstance(result.get("scores"), Mapping) else result
        comments = result.get("comments") if isinstance(result.get("comments"), Mapping) else {}
        observed_categories: list[str] = []
        for category in JUDGE_RUBRIC:
            if category not in raw_scores:
                continue
            try:
                value = float(raw_scores[category])
            except (TypeError, ValueError):
                value = 0.0
            score = _score(
                f"judge.{judge_name}.{category}",
                value,
                str(comments.get(category) or result.get("comment") or ""),
            )
            score["source"] = "llm_judge"
            score["acceptance_role"] = "advisory"
            scores.append(score)
            observed_categories.append(category)
        receipt = {
            "judge": judge_name,
            "status": "scored" if observed_categories else "unavailable",
            "categories": observed_categories,
        }
        last_call = getattr(judge, "last_call", None)
        if isinstance(last_call, Mapping):
            receipt["call"] = redact_payload(last_call)
        receipts.append(receipt)

    statuses = {str(receipt.get("status")) for receipt in receipts}
    if not receipts:
        status = "not_configured"
    elif "scored" in statuses:
        status = "scored"
    elif "blocked" in statuses:
        status = "blocked"
    else:
        status = "unavailable"
    return {
        "status": status,
        "acceptance_role": "advisory",
        "judges": receipts,
        "scores": scores,
    }


class OpenAICompatibleJudge:
    """Optional JSON judge for an OpenAI-compatible provider endpoint.

    The evaluator remains runnable without this class; callers opt in by
    passing a judge to ``MemoirEvaluationRunner`` or the CLI. Calibration
    examples are included in the prompt and never published as raw traces.
    """

    name = "openai-compatible"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str = "",
        calibration_examples: Iterable[Mapping[str, Any]] = (),
        timeout: float = 60.0,
        instructions: str | None = None,
        max_tokens: int = 1200,
        reasoning_effort: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.calibration_examples = list(calibration_examples)
        self.timeout = timeout
        self.instructions = instructions
        self.max_tokens = max(128, min(int(max_tokens), 4096))
        self.reasoning_effort = reasoning_effort
        self.calls = 0
        self.last_call: dict[str, Any] = {}

    async def __call__(self, judge_input: Mapping[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        self.calls += 1
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "You are a calibrated evaluator for an observable memoir-agent trajectory."},
                {"role": "user", "content": build_judge_prompt(
                    judge_input,
                    calibration_examples=self.calibration_examples,
                    instructions=self.instructions,
                )},
            ],
        }
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=body)
                response.raise_for_status()
                payload = response.json()
        except Exception as error:
            self.last_call = {
                "status": "error",
                "error_type": type(error).__name__,
                "http_status": getattr(getattr(error, "response", None), "status_code", None),
                "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
            }
            raise
        usage = payload.get("usage") if isinstance(payload, Mapping) and isinstance(payload.get("usage"), Mapping) else None
        self.last_call = {
            "status": "response",
            "http_status": response.status_code,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
            "usage": redact_payload(usage) if usage is not None else None,
        }
        content = payload["choices"][0]["message"]["content"]
        parsed = json.loads(content) if isinstance(content, str) else content
        if not isinstance(parsed, Mapping):
            raise ValueError("Judge response must be a JSON object")
        return {"judge": self.name, **parsed}


HttpJsonJudge = OpenAICompatibleJudge


@contextmanager
def _observation_scope(observation: Any):
    """Use either SDK-style context managers or older observation objects."""
    if hasattr(observation, "__enter__") and hasattr(observation, "__exit__"):
        with observation as active:
            yield active
        return
    try:
        yield observation
    finally:
        end = getattr(observation, "end", None)
        if callable(end):
            end()


class LangfusePublisher:
    """Small adapter around the optional Langfuse Python SDK v4."""

    def __init__(self, client: Any = None, *, env: Mapping[str, str] | None = None) -> None:
        if client is None:
            try:
                from langfuse import get_client  # type: ignore[import-not-found]
            except ImportError as error:  # pragma: no cover - exercised by CLI setup
                raise RuntimeError("Install the evaluation extra to publish to Langfuse: pip install -e '.[evaluation]'") from error
            # Keep Memoir's environment namespace separate while allowing the
            # SDK to use its standard configuration names.  The runner passes
            # its parsed .env mapping explicitly because python-dotenv is not
            # a runtime dependency of the evaluation script.  Langfuse SDK v4
            # reads LANGFUSE_HOST (not LANGFUSE_BASE_URL).
            sources = env or {}

            def configured(*names: str) -> str:
                for name in names:
                    value = os.getenv(name, "") or sources.get(name, "")
                    if value and value.strip():
                        return value.strip()
                return ""

            for target, names in (
                ("LANGFUSE_PUBLIC_KEY", ("LANGFUSE_PUBLIC_KEY", "MEMORY_SPARK_LANGFUSE_PUBLIC_KEY")),
                ("LANGFUSE_SECRET_KEY", ("LANGFUSE_SECRET_KEY", "MEMORY_SPARK_LANGFUSE_SECRET_KEY")),
                ("LANGFUSE_HOST", ("LANGFUSE_HOST", "MEMORY_SPARK_LANGFUSE_HOST", "LANGFUSE_BASE_URL", "MEMORY_SPARK_LANGFUSE_BASE_URL")),
                ("LANGFUSE_TRACING_ENVIRONMENT", ("LANGFUSE_TRACING_ENVIRONMENT", "MEMORY_SPARK_LANGFUSE_ENVIRONMENT")),
            ):
                value = configured(*names)
                if value and not os.getenv(target):
                    os.environ[target] = value
            client = get_client()
        self.client = client
        self.auth_check_status = "not_supported"
        auth_check = getattr(client, "auth_check", None)
        if callable(auth_check):
            try:
                authenticated = auth_check()
            except Exception as error:  # pragma: no cover - SDK/network dependent
                raise RuntimeError("Langfuse authentication check failed") from error
            if not authenticated:
                raise RuntimeError("Langfuse authentication check failed")
            self.auth_check_status = "passed"

    def flush(self) -> None:
        """Flush after case root scopes have been closed.

        Case publication flushes while its root observation is still active so
        per-case callers get prompt delivery. Short-lived runners also need a
        final flush after the case context exits, otherwise the root span's
        end/update can remain queued when the process terminates.
        """
        flush = getattr(self.client, "flush", None)
        if callable(flush):
            flush()

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
        round_id = normalise_correlation(correlation).get("round_id")
        if callable(create_trace_id) and run_id:
            kwargs["trace_context"] = {
                "trace_id": create_trace_id(seed=f"{run_id}:{case_id or ''}:{round_id or ''}"),
            }
        observation = self.client.start_as_current_observation(**kwargs)
        with _observation_scope(observation) as active:
            yield _LangfuseCase(self.client, active, correlation)


class _LangfuseCase:
    def __init__(self, client: Any, observation: Any, correlation: Mapping[str, Any]) -> None:
        self.client = client
        self.observation = observation
        self.correlation = normalise_correlation(correlation)
        self.step_observations: dict[str, str] = {}
        self.step_traces: dict[str, str] = {}
        self.publish_errors: list[dict[str, str]] = []

    @property
    def trace_id(self) -> str | None:
        value = getattr(self.observation, "trace_id", None)
        return str(value) if value else None

    @property
    def observation_id(self) -> str | None:
        value = getattr(self.observation, "id", None)
        return str(value) if value else None

    def _start_step_observation(self, step: Mapping[str, Any]) -> str | None:
        step_id = str(step.get("step_id") or "")
        if not step_id:
            return None
        external_observation_id = str(step.get("observation_id") or "").strip()
        if external_observation_id:
            # A worker-supplied Langfuse ID is authoritative.  Do not create
            # a duplicate child and make step scores point to the wrong span.
            self.step_observations[step_id] = external_observation_id[:256]
            step_trace_id = str(step.get("trace_id") or self.trace_id or "").strip()
            if step_trace_id:
                self.step_traces[step_id] = step_trace_id[:256]
            return external_observation_id[:256]

        starter = getattr(self.client, "start_observation", None)
        if not callable(starter):
            return None
        action = str(step.get("action") or "worker.step")[:256]
        linkage = {
            key: str(step[key])[:256]
            for key in _OBSERVATION_LINK_FIELDS
            if step.get(key) is not None
        }
        metadata = {
            "trajectory_step_id": step_id,
            "trajectory_sequence": step.get("sequence"),
            "trajectory_source": step.get("source"),
            **{f"worker_{key}": value for key, value in linkage.items()},
        }
        observation_input = minimize_for_langfuse({
            "pre_action_context": step.get("pre_action_context"),
            "input": step.get("input"),
            "normalized_action": step.get("normalized_action"),
        })
        observation_output = minimize_for_langfuse({
            "output": step.get("output"),
            "error": step.get("error"),
        })
        kwargs: dict[str, Any] = {
            "as_type": "span",
            "name": action,
            "input": observation_input,
            "output": observation_output,
            "metadata": metadata,
        }
        parent_id = str(step.get("parent_observation_id") or self.observation_id or "").strip()
        trace_id = str(step.get("trace_id") or self.trace_id or "").strip()
        if parent_id and trace_id:
            kwargs["trace_context"] = {
                "trace_id": trace_id,
                "parent_span_id": parent_id,
            }
        observation = None
        try:
            observation = starter(**kwargs)
        except TypeError:
            # SDK versions before explicit trace-context support can still
            # create a child under the active root observation.
            kwargs.pop("trace_context", None)
            try:
                observation = starter(**kwargs)
            except Exception as error:  # pragma: no cover - SDK dependent
                self.publish_errors.append({"step_id": step_id, "error_type": type(error).__name__})
                return None
        except Exception as error:  # pragma: no cover - SDK/network dependent
            self.publish_errors.append({"step_id": step_id, "error_type": type(error).__name__})
            return None
        if observation is None:
            return None
        with _observation_scope(observation) as active:
            child_id = getattr(active, "id", None)
            if child_id:
                child_id = str(child_id)[:256]
                self.step_observations[step_id] = child_id
                child_trace_id = str(step.get("trace_id") or self.trace_id or "").strip()
                if child_trace_id:
                    self.step_traces[step_id] = child_trace_id[:256]
                return child_id
        return None

    def publish(
        self,
        trajectory: Mapping[str, Any],
        scores: Iterable[Mapping[str, Any]],
        *,
        extra_metadata: Mapping[str, Any] | None = None,
    ) -> None:
        digest = _sha256(trajectory)
        root_metadata = {
            f"evaluation_{key}": value
            for key, value in self.correlation.items()
        }
        root_metadata["trajectory_sha256"] = digest
        root_metadata["trajectory_schema_version"] = str(trajectory.get("schema_version") or TRAJECTORY_SCHEMA_VERSION)
        root_metadata["privacy_policy_version"] = PRIVACY_POLICY_VERSION
        root_metadata["local_evidence"] = "available-in-runner-result"
        if isinstance(extra_metadata, Mapping):
            root_metadata.update({
                f"evaluation_{str(key)}": redact_payload(value)
                for key, value in extra_metadata.items()
                if str(key) not in {
                    "trajectory_sha256",
                    "trajectory_schema_version",
                    "privacy_policy_version",
                    "local_evidence",
                }
            })
        self.observation.update(
            output=minimize_for_langfuse(trajectory),
            metadata=root_metadata,
        )
        for step in trajectory.get("steps", []) if isinstance(trajectory.get("steps"), list) else []:
            if isinstance(step, Mapping):
                self._start_step_observation(step)
        trace_id = self.trace_id
        if not trace_id:
            return
        run_id = self.correlation.get("run_id", trace_id)
        for score in scores:
            # Langfuse replaces a score only when its ID, name and UTC date
            # match. Replay the retained trajectory's recorded time, rather
            # than assigning the publication day's timestamp on each retry.
            try:
                score_timestamp = datetime.fromisoformat(str(trajectory.get("started_at") or ""))
                if score_timestamp.tzinfo is None or score_timestamp.utcoffset() is None:
                    raise ValueError("Missing timezone")
                score_timestamp = score_timestamp.astimezone(timezone.utc)
            except (ValueError, OverflowError) as error:
                raise ValueError("Langfuse scores require a timezone-aware trajectory started_at") from error
            name = str(score.get("name") or "trajectory_quality")
            step_id = str(score.get("step_id") or "run")
            evaluator_version = self.correlation.get("evaluator_version", "trajectory-rubric/1")
            case_id = self.correlation.get("case_id", "case")
            variant = self.correlation.get("variant", "default")
            round_id = self.correlation.get("round_id", "")
            score_id = hashlib.sha256(f"{run_id}:{case_id}:{round_id}:{variant}:{evaluator_version}:{step_id}:{name}".encode()).hexdigest()
            score_trace_id = str(score.get("trace_id") or self.step_traces.get(step_id) or trace_id)
            score_observation_id = str(
                score.get("observation_id")
                or self.step_observations.get(step_id)
                or self.observation_id
            )
            kwargs = {
                "score_id": score_id,
                "timestamp": score_timestamp,
                "name": name,
                "value": float(score.get("value", 0)),
                "trace_id": score_trace_id,
                "observation_id": score_observation_id,
                "data_type": "NUMERIC",
                "comment": str(score.get("comment") or ""),
            }
            # Keep the replay identity on every publication. An SDK error may
            # occur after accepting the score; retrying without its ID can
            # create a second logical score and conceal the original failure.
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
        self.application_revision = build_application_revision()
        self.default_skill_manifest = build_skill_manifest(Path(__file__).resolve().parents[2] / "skills")

    async def run_case(self, case: Mapping[str, Any], *, run_id: str | None = None, variant: Mapping[str, Any] | str | None = None) -> dict[str, Any]:
        case_id = str(case.get("id") or case.get("case_id") or uuid4())
        variant_values = variant if isinstance(variant, Mapping) else ({"variant": str(variant)} if variant else {})
        correlation = normalise_correlation({
            **(case.get("metadata") if isinstance(case.get("metadata"), Mapping) else {}),
            **variant_values,
            "run_id": run_id or case.get("run_id") or uuid4(),
            "case_id": case_id,
            "application_revision": case.get("application_revision") or self.application_revision,
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
            try:
                result = self.task(case, correlation)
                if inspect.isawaitable(result):
                    result = await result
                if not isinstance(result, Mapping):
                    raise TypeError("evaluation task must return a mapping containing trajectory")
                trajectory = result.get("trajectory")
                if not isinstance(trajectory, Mapping):
                    raise ValueError("evaluation task returned no normalized trajectory")
            except Exception as error:
                # A callback can fail before it returns any trajectory. Keep a
                # truthful local outcome without fabricating steps or allowing
                # gather() to discard the already completed sibling cases.
                # Exception messages can contain storyteller text or secrets.
                return {
                    "case_id": case_id,
                    "correlation": correlation,
                    "scores": [],
                    "result": {"trajectory": None, "error_type": type(error).__name__},
                    "trajectory_sha256": None,
                    "failure_evidence": [{
                        "stage": "task_callback",
                        "error_type": type(error).__name__,
                        "comment": "Task did not return a complete normalized trajectory.",
                    }],
                    "acceptance": {
                        "status": "error",
                        "deterministic_status": "unavailable",
                        "judge_status": "not_run",
                        "judge_role": "advisory",
                    },
                    "judge_evidence": {
                        "status": "not_run",
                        "acceptance_role": "advisory",
                        "judges": [],
                        "scores": [],
                        "advisory_failures": [],
                    },
                }
            expected = dict(case)
            if isinstance(case.get("expected"), Mapping):
                expected.update(case["expected"])
            deterministic_scores = self.evaluator(trajectory, expected=expected)
            scores = list(deterministic_scores)
            judge_evidence = {
                "status": "not_configured",
                "acceptance_role": "advisory",
                "judges": [],
                "scores": [],
            }
            if self.judges:
                judge_input = build_judge_input(
                    task=case.get("input", case),
                    trajectory=trajectory,
                    available_tools=self.available_tools if self.available_tools is not None else case.get("available_tools", []),
                )
                judge_evidence = await run_judges_report(self.judges, judge_input)
                scores.extend(judge_evidence["scores"])
            if sink is not None:
                sink.publish(trajectory, scores)

            deterministic_failures = [
                {key: score.get(key) for key in ("name", "value", "comment", "step_id") if key in score}
                for score in deterministic_scores if float(score.get("value", 1)) < 1
            ]
            judge_failures = [
                {key: score.get(key) for key in ("name", "value", "comment", "step_id") if key in score}
                for score in judge_evidence["scores"] if float(score.get("value", 1)) < 1
            ]
            deterministic_status = "fail" if deterministic_failures else "pass"
            acceptance_status = deterministic_status if deterministic_status == "fail" else (
                "pass" if judge_evidence["status"] == "scored" else "unavailable"
            )
            failures = [
                *deterministic_failures,
            ]
            result = {
                "case_id": case_id,
                "correlation": correlation,
                "scores": scores,
                "result": redact_payload(result),
                "trajectory_sha256": _sha256(trajectory),
                "failure_evidence": failures,
                "acceptance": {
                    "status": acceptance_status,
                    "deterministic_status": deterministic_status,
                    "judge_status": judge_evidence["status"],
                    "judge_role": "advisory",
                },
                "judge_evidence": {
                    **judge_evidence,
                    "advisory_failures": judge_failures,
                },
            }
            if sink is not None:
                result["langfuse"] = {
                    "trace_id": sink.trace_id,
                    "observation_id": sink.observation_id,
                }
                if sink.step_observations:
                    result["langfuse"]["step_observations"] = dict(sink.step_observations)
                if sink.publish_errors:
                    result["langfuse"]["publish_errors"] = list(sink.publish_errors)
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
    """Compare only numeric metrics observed on both non-error results."""
    def observed_scores(result: Mapping[str, Any]) -> dict[str, float]:
        return {
            str(score["name"]): float(score["value"])
            for score in result.get("scores", [])
            if isinstance(score, Mapping) and score.get("name")
            and isinstance(score.get("value"), (int, float))
            and not isinstance(score.get("value"), bool)
            and math.isfinite(score["value"])
        }

    def failed(result: Mapping[str, Any]) -> bool:
        acceptance = result.get("acceptance")
        return isinstance(acceptance, Mapping) and acceptance.get("status") == "error"

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
        baseline_scores = observed_scores(baseline)
        for variant, result in variants.items():
            score_values = observed_scores(result)
            comparable = set(score_values) & set(baseline_scores)
            if failed(baseline) or failed(result):
                comparable.clear()
            unavailable = sorted((set(score_values) | set(baseline_scores)) - comparable)
            status = "unavailable" if not comparable else ("partial" if unavailable else "compared")
            rows.append({
                "case_id": case_id,
                "variant": variant,
                "baseline_variant": baseline_name,
                "scores": score_values,
                "comparison_status": status,
                "unavailable_metrics": unavailable,
                "deltas": {name: score_values[name] - baseline_scores[name] for name in sorted(comparable)},
            })
    return rows
