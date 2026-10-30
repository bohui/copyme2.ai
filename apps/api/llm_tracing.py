"""Best-effort Langfuse observations for model calls outside the gateway."""

from __future__ import annotations

from contextlib import contextmanager, ExitStack
from contextvars import ContextVar
import logging
import os
import sys
from typing import Any, Iterator, Mapping


_LOGGER = logging.getLogger(__name__)
_UNSET = object()
_client_cache: object = _UNSET
_gateway_span = ContextVar('memoir_gateway_span', default=False)
_trace_name = ContextVar('memoir_trace_name', default=None)


def gateway_metadata(name):
    return {'generation_name': name, 'trace_name': _trace_name.get() or name}


@contextmanager
def trace_scope(name):
    token = _trace_name.set(_trace_name.get() or name)
    scope = ExitStack()
    try:
        from langfuse import propagate_attributes
        scope.enter_context(propagate_attributes(trace_name=_trace_name.get()))
    except Exception:
        _LOGGER.debug('Langfuse trace attributes are unavailable', exc_info=True)
    try:
        yield
    finally:
        try:
            scope.close()
        except Exception:
            _LOGGER.debug('Langfuse trace attributes could not be closed', exc_info=True)
        _trace_name.reset(token)


def gateway_trace_headers() -> dict[str, str]:
    """Forward only W3C trace context, never baggage or private request data."""
    if not _gateway_span.get():
        return {}
    try:
        from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
        headers = {}
        TraceContextTextMapPropagator().inject(headers)
        return {key: value for key, value in headers.items() if key == 'traceparent'}
    except Exception:
        _LOGGER.debug('Gateway trace context is unavailable', exc_info=True)
        return {}


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


def _linked_prompt(metadata):
    manifest = (metadata or {}).get('prompt_manifest') or {}
    artifacts = manifest.get('artifacts') or []
    primary = next((item for item in artifacts if item.get('status') == 'published'), None)
    if primary is None:
        return None
    try:
        from langfuse.model import TextPromptClient
        from langfuse.api import Prompt_Text
        from .prompt_artifact import prompt_path, load_prompt_artifact
        text = load_prompt_artifact(prompt_path(primary['name']))
        return TextPromptClient(Prompt_Text(name=primary['name'],version=primary['version'],prompt=text,
            config={},labels=[],tags=[]))
    except Exception:
        return None


@contextmanager
def trace_llm_call(
    name: str,
    model: str | None = None,
    *,
    input_summary: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
    gateway: bool = False,
) -> Iterator[Any | None]:
    with trace_scope(name):
        with _trace_observation(name, model, input_summary=input_summary, metadata=metadata, gateway=gateway) as observation:
            yield observation


@contextmanager
def trace_skill_execution(name, phase, *, embedded=False):
    """Observe the whole attempt, including admission and canonical commit."""
    from .lifetime_memory_publication import PublicationUnavailable
    import asyncio
    metadata = {'skill': name, 'phase': phase, 'execution': 'embedded' if embedded else 'skill'}
    outcome = {'status': 'completed'}
    failure = None
    with trace_llm_call(name, metadata={**metadata, 'status': 'running'}, gateway=True) as observation:
        try:
            yield outcome
        except BaseException as error:
            # Keep raw exception text out of SDK-generated exception events.
            failure = sys.exc_info()
            outcome.update(status='blocked' if isinstance(error, PublicationUnavailable) else
                'cancelled' if isinstance(error, asyncio.CancelledError) else 'failed', error_type=type(error).__name__)
        status = outcome['status']
        update_llm_trace(observation, output=dict(outcome), metadata={**metadata, **outcome},
            level='WARNING' if status in {'blocked','cancelled'} else 'ERROR' if status=='failed' else 'DEFAULT',
            status_message=status)
    if failure is not None:
        raise failure[1].with_traceback(failure[2])


@contextmanager
def _trace_observation(name, model, *, input_summary=None, metadata=None, gateway=False):
    """Gateway calls get an app span; directly observed calls get a generation."""
    client = _get_client()
    if client is None:
        yield None
        return

    try:
        linked = _linked_prompt(metadata) if not gateway else None
        attributes = dict(metadata or {})
        if gateway and model is not None:
            attributes['model'] = model
        context = client.start_as_current_observation(
            **({"prompt": linked} if linked is not None and not gateway else {}),
            as_type="span" if gateway else "generation",
            name=name,
            **({"model": model} if not gateway else {}),
            input=dict(input_summary) if input_summary is not None else None,
            metadata=attributes or None,
        )
        enter = getattr(context, "__enter__", None)
        active = enter() if callable(enter) else context
    except Exception:  # pragma: no cover - depends on SDK/exporter state
        _LOGGER.debug("Langfuse observation could not be started", exc_info=True)
        yield None
        return

    token = _gateway_span.set(gateway)
    exception_info: tuple[Any, Any, Any] = (None, None, None)
    try:
        try:
            yield active
        except BaseException as error:
            exception_info = sys.exc_info()
            mark_llm_trace_error(active, name, error)
            raise
    finally:
        _gateway_span.reset(token)
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
