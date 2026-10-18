"""Best-effort Langfuse observations for model calls outside the gateway."""

from __future__ import annotations

from contextlib import contextmanager
import logging
import os
import sys
from typing import Any, Iterator, Mapping


_LOGGER = logging.getLogger(__name__)
_UNSET = object()
_client_cache: object = _UNSET


def _first_configured(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _configure_sdk_environment() -> bool:
    """Map Memoir's names to the standard SDK names without overwriting them."""
    public_key = _first_configured("LANGFUSE_PUBLIC_KEY", "MEMORY_SPARK_LANGFUSE_PUBLIC_KEY")
    secret_key = _first_configured("LANGFUSE_SECRET_KEY", "MEMORY_SPARK_LANGFUSE_SECRET_KEY")
    base_url = _first_configured(
        "LANGFUSE_BASE_URL",
        "LANGFUSE_HOST",
        "MEMORY_SPARK_LANGFUSE_RUNTIME_BASE_URL",
        "MEMORY_SPARK_LANGFUSE_BASE_URL",
    )
    environment = _first_configured(
        "LANGFUSE_TRACING_ENVIRONMENT",
        "MEMORY_SPARK_LANGFUSE_ENVIRONMENT",
    )
    if not public_key or not secret_key:
        return False
    os.environ.setdefault("LANGFUSE_PUBLIC_KEY", public_key)
    os.environ.setdefault("LANGFUSE_SECRET_KEY", secret_key)
    if base_url:
        os.environ.setdefault("LANGFUSE_BASE_URL", base_url)
    if environment:
        os.environ.setdefault("LANGFUSE_TRACING_ENVIRONMENT", environment)
    return True


def _get_client() -> Any | None:
    global _client_cache
    if _client_cache is not _UNSET:
        return _client_cache  # type: ignore[return-value]
    if not _configure_sdk_environment():
        _client_cache = None
        return None
    try:
        from langfuse import get_client  # type: ignore[import-not-found]

        _client_cache = get_client()
    except Exception:  # pragma: no cover - depends on installed SDK/configuration
        _LOGGER.debug("Langfuse tracing is unavailable", exc_info=True)
        _client_cache = None
    return _client_cache  # type: ignore[return-value]


def _safe_update(observation: Any, **fields: Any) -> None:
    if observation is None:
        return
    fields = {key: value for key, value in fields.items() if value is not None}
    try:
        observation.update(**fields)
    except Exception:  # pragma: no cover - depends on SDK/exporter state
        _LOGGER.debug("Langfuse observation update failed", exc_info=True)


def update_llm_trace(
    observation: Any,
    *,
    output: Any = None,
    metadata: Mapping[str, Any] | None = None,
    usage_details: Mapping[str, int] | None = None,
    level: str | None = None,
    status_message: str | None = None,
) -> None:
    """Update a trace without allowing observability to break the model call."""
    _safe_update(
        observation,
        output=output,
        metadata=dict(metadata) if metadata is not None else None,
        usage_details=dict(usage_details) if usage_details is not None else None,
        level=level,
        status_message=status_message,
    )


def mark_llm_trace_error(observation: Any, operation: str, error: BaseException) -> None:
    """Record a bounded error classification without exporting exception text."""
    update_llm_trace(
        observation,
        level="ERROR",
        status_message=f"{operation} failed: {type(error).__name__}",
    )


@contextmanager
def trace_llm_call(
    name: str,
    model: str,
    *,
    input_summary: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> Iterator[Any | None]:
    """Create a generation observation, failing open when Langfuse is unavailable."""
    client = _get_client()
    if client is None:
        yield None
        return

    try:
        context = client.start_as_current_observation(
            as_type="generation",
            name=name,
            model=model,
            input=dict(input_summary) if input_summary is not None else None,
            metadata=dict(metadata) if metadata is not None else None,
        )
        enter = getattr(context, "__enter__", None)
        active = enter() if callable(enter) else context
    except Exception:  # pragma: no cover - depends on SDK/exporter state
        _LOGGER.debug("Langfuse observation could not be started", exc_info=True)
        yield None
        return

    exception_info: tuple[Any, Any, Any] = (None, None, None)
    try:
        try:
            yield active
        except BaseException as error:
            exception_info = sys.exc_info()
            mark_llm_trace_error(active, name, error)
            raise
    finally:
        try:
            exit_context = getattr(context, "__exit__", None)
            if callable(exit_context):
                exit_context(*exception_info)
            else:
                end = getattr(active, "end", None)
                if callable(end):
                    end()
        except Exception:  # pragma: no cover - depends on SDK/exporter state
            _LOGGER.debug("Langfuse observation could not be closed", exc_info=True)
