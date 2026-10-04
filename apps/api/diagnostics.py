"""Small, privacy-safe diagnostics shared by the Memoir model path.

The diagnostic stream is deliberately separate from evaluation trajectories.
It contains correlation IDs, bounded timings, and terminal classifications only;
it must never become a second copy of a storyteller prompt or reply.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any
from uuid import uuid4


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$")


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
