"""Small, privacy-safe diagnostics shared by the Memoir model path.

The diagnostic stream is deliberately separate from evaluation trajectories.
It contains correlation IDs, bounded timings, and terminal classifications only;
it must never become a second copy of a storyteller prompt or reply.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
import re
import time
from typing import Any
from uuid import uuid4


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$")
_JSON_BOUNDARIES = frozenset({'json_decode', 'postgres_rest_json_record'})
# This is a fixed location allowlist, not a suffix match or an inspection of
# exception source code. Unknown files/functions cannot enter private receipts.
_JSON_FRAME_FUNCTIONS = {
    'apps/api/codex_runtime.py': frozenset({
        'turn', '_run_workspace_job', '_persist_workspace', '_workspace_extraction',
        '_worker_turn', 'consume_worker_stream', '_resolve_language', 'publish_task',
    }),
    'apps/api/codex_agent.py': frozenset({'receive'}),
    'apps/api/agent_storage.py': frozenset({
        'request', 'save_profile', 'profile', 'place_journey', 'save_place_journey',
        'family_context', 'upsert_family_context', 'save_memory', 'memories',
        'save_agent_session', 'put_agent_turn_file', 'commit_agent_turn',
        'update_agent_memory_source_paths', 'recall_rounds_completed', 'story_entitlement',
    }),
    'scripts/issue14_subscription_session.py': frozenset({'handle_async_request'}),
    'tests/memoir_postgres_workflow.py': frozenset({'handle'}),
}
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_JSON_FRAME_PATHS = {str(_REPOSITORY_ROOT / path): path for path in _JSON_FRAME_FUNCTIONS}
_JSON_FRAME_PATHS.update({path: path for path in _JSON_FRAME_FUNCTIONS})


def _bounded_position(value: Any, *, minimum: int = 0) -> bool:
    return type(value) is int and minimum <= value <= 2**31 - 1


def _safe_json_frame(value: Any) -> dict[str, Any] | None:
    if type(value) is not dict:
        return None
    filename, function, line = value.get('filename'), value.get('function'), value.get('line')
    if (type(filename) is str and filename in _JSON_FRAME_FUNCTIONS
            and type(function) is str and function in _JSON_FRAME_FUNCTIONS[filename]
            and _bounded_position(line, minimum=1)):
        return {'filename': filename, 'function': function, 'line': line}
    return None


def sanitize_json_failure_details(value: Any) -> dict[str, Any]:
    """Re-project private trajectory data at the receipt trust boundary.

    Never stringify unknown objects or retain messages, documents, source lines,
    locals, exception chains, absolute paths, or arbitrary traceback fields.
    """
    if type(value) is not dict or value.get('error_type') != 'JSONDecodeError':
        return {}
    safe: dict[str, Any] = {'error_type': 'JSONDecodeError'}
    boundary = value.get('parser_boundary')
    if type(boundary) is str and boundary in _JSON_BOUNDARIES:
        safe['parser_boundary'] = boundary
    for key in ('json_line', 'json_column', 'json_position'):
        number = value.get(key)
        if _bounded_position(number, minimum=0 if key == 'json_position' else 1):
            safe[key] = number
    frames = value.get('frames')
    if type(frames) is list:
        projected = [safe_frame for frame in frames[-64:]
                     if (safe_frame := _safe_json_frame(frame)) is not None]
        if projected:
            safe['frames'] = projected[-4:]
    return safe


def json_failure_details(error: BaseException) -> dict[str, Any]:
    """Locate a JSON parser failure privately, without formatting the exception.

    PostgreSQL framing attaches the original numeric coordinates to its
    JSONDecodeError. Only that known parser boundary can override
    the standard JSONDecodeError coordinates. No exception cause is inspected.
    """
    if not isinstance(error, json.JSONDecodeError):
        return {}
    attributes = vars(error)
    boundary = attributes.get('parser_boundary')
    attached = type(boundary) is str and boundary == 'postgres_rest_json_record'
    details = {'error_type': 'JSONDecodeError',
               'parser_boundary': boundary if attached else 'json_decode'}
    for target, standard in (('json_line', 'lineno'), ('json_column', 'colno'), ('json_position', 'pos')):
        details[target] = attributes.get(target if attached else standard)
    frames = []
    traceback = error.__traceback__
    while traceback is not None:
        code = traceback.tb_frame.f_code
        filename = _JSON_FRAME_PATHS.get(code.co_filename)
        frame = _safe_json_frame({'filename': filename, 'function': code.co_name, 'line': traceback.tb_lineno})
        if frame is not None:
            frames.append(frame)
            frames = frames[-4:]
        traceback = traceback.tb_next
    details['frames'] = frames
    return sanitize_json_failure_details(details)


def configure_diagnostic_logger(logger: logging.Logger) -> logging.Logger:
    """Give the allow-listed diagnostic stream its own stdout/stderr sink."""
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    return logger


def new_request_id(value: Any = None) -> str:
    """Return a bounded ID suitable for crossing service boundaries."""
    if value is not None:
        candidate = str(value).strip().replace("\x00", "")
        if _SAFE_ID.fullmatch(candidate):
            return candidate
    return str(uuid4())


def elapsed_ms(start: float) -> int:
    """Return a non-negative, rounded monotonic duration in milliseconds."""
    return max(0, round((time.perf_counter() - start) * 1000))


def failure_class(error: BaseException | None = None, *, status_code: Any = None) -> str:
    """Map transport failures to a stable, non-sensitive diagnostic class."""
    try:
        status = int(status_code) if status_code is not None else None
    except (TypeError, ValueError):
        status = None
    if status == 408 or status == 504:
        return "timeout"
    if status == 429:
        return "rate_limit"
    if status == 401 or status == 403:
        return "authorization"
    if status == 409:
        return "busy"
    if status in {502, 503}:
        return "upstream_unavailable"
    if status is not None and status >= 500:
        return "upstream_error"
    if status is not None and status >= 400:
        return "http_rejected"
    if isinstance(error, asyncio.CancelledError):
        return "cancelled"
    name = type(error).__name__.lower() if error is not None else ""
    if "timeout" in name:
        return "timeout"
    if "connect" in name or "connection" in name:
        return "connection"
    if "httpstatus" in name:
        return "http_status"
    if "requesterror" in name:
        return "request_error"
    if "providerunavailable" in name:
        return "upstream_unavailable"
    if "busy" in name:
        return "busy"
    if "runtime" in name:
        return "runtime_error"
    return "exception"


def log_diagnostic(logger: logging.Logger, event: str, request_id: Any, **fields: Any) -> None:
    """Emit one structured, allow-listed diagnostic record.

    Keeping the allow-list here makes accidental prompt/reply/header logging a
    code-review-visible failure rather than a formatting convention.
    """
    safe_fields: dict[str, Any] = {"event": str(event)[:64], "request_id": new_request_id(request_id)}
    allowed = {
        "component", "agent_role", "model", "status", "terminal_event",
        "terminal_status", "failure_class", "http_status", "error_code",
        "elapsed_ms", "streaming", "call_type",
    }
    for key, value in fields.items():
        if key not in allowed or value is None:
            continue
        if key in {"elapsed_ms", "http_status"}:
            try:
                safe_fields[key] = int(value)
            except (TypeError, ValueError):
                continue
        elif key == "streaming":
            safe_fields[key] = bool(value)
        else:
            text = str(value).strip().replace("\x00", "")
            if text:
                safe_fields[key] = text[:128]
    logger.info("memoir_diagnostic %s", json.dumps(safe_fields, sort_keys=True, separators=(",", ":")))
