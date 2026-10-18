"""Per-user Codex app-server runtime and Supabase artifact synchronization."""

import asyncio
import httpx
import json
import logging
import os
import re
import time
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any, Mapping

from .agent_lock import AgentTurnBusyError, AgentTurnLease
from .diagnostics import configure_diagnostic_logger, elapsed_ms, failure_class, log_diagnostic, new_request_id
from .agent_storage import UserStorage
from .conversation_text import original_conversation_text
from .codex_timeout_policy import WORKER_MAX_TIMEOUT, WORKER_TIMEOUT, WORKSPACE_TIMEOUT
from .collector_configuration import collector_configuration
from .issue14_execution_admission import (
    check_issue14_dispatch, validate_optional_issue14_admission,
)
from .prompt_artifact import load_prompt_artifact
from .memoir_tasks import MemorySource
from .trajectory_evaluation import (
    TrajectoryRecorder,
    execution_correlation,
    normalise_correlation,
)

_MAX_WORKER_ERROR_BODY_BYTES = 64 * 1024
_WORKER_ERROR_BODY_EXTENSION = "memoir_worker_error_body"

diagnostic_logger = logging.getLogger("memoir.runtime.diagnostics")
configure_diagnostic_logger(diagnostic_logger)


class _WorkerStreamError(RuntimeError):
    """A streamed worker failure carrying its recorder-redacted receipt."""

    def __init__(self, message: str, trajectory: Mapping[str, Any] | None = None):
        super().__init__(message)
        if isinstance(trajectory, Mapping):
            self.trajectory = dict(trajectory)


async def _read_bounded_response_body(response: httpx.Response) -> bytes:
    """Read only a bounded HTTP error body while a streamed response is open."""
    try:
        return response.content[:_MAX_WORKER_ERROR_BODY_BYTES]
    except httpx.ResponseNotRead:
        pass

    body = bytearray()
    async for chunk in response.aiter_bytes():
        remaining = _MAX_WORKER_ERROR_BODY_BYTES - len(body)
        if remaining <= 0:
            break
        body.extend(chunk[:remaining])
        if len(body) >= _MAX_WORKER_ERROR_BODY_BYTES:
            break
    return bytes(body)


def _worker_error_payload(response: httpx.Response) -> Mapping[str, Any] | None:
    """Decode a bounded worker error body without ever exposing its contents."""
    body = response.extensions.pop(_WORKER_ERROR_BODY_EXTENSION, None)
    if not isinstance(body, bytes):
        try:
            body = response.content[:_MAX_WORKER_ERROR_BODY_BYTES]
        except httpx.ResponseNotRead:
            return None
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, TypeError, ValueError):
        return None
    return payload if isinstance(payload, Mapping) else None


_PROMPTS = Path(__file__).with_name("prompts")
CONVERSATION_LANGUAGE_INSTRUCTIONS = {
    locale: load_prompt_artifact(_PROMPTS / f"conversation-language-{locale}.md")
    for locale in ("en-AU", "zh-CN")
}


def normalize_conversation_language(language: str | None) -> str:
    return language if language in CONVERSATION_LANGUAGE_INSTRUCTIONS else "en-AU"


def conversation_language_instruction(language: str | None) -> str:
    return CONVERSATION_LANGUAGE_INSTRUCTIONS[normalize_conversation_language(language)]


def _timeline_source_spans(text: str) -> list[tuple[str, int, int]]:
    """Split visible user text into source clauses while retaining offsets.

    Offsets make a marker entry's association explicit: a veto targets the
    nearest preceding author-owned source clause, while a later independent
    claim remains eligible. The split also keeps mixed uncertainty and a
    positive author claim from sharing one all-or-nothing sentence decision.
    """
    source = original_conversation_text(text) if isinstance(text, str) else ""
    separator = re.compile(
        r"[.!?。！？；;\n]+"
        r"|,(?=\s*(?:but|although|though|however|yet|and|then)\b)"
        r"|，(?=(?:但|但是|不过|然而|然后|同时|而且|可是|那时))"
        r"|\bplease\s+(?=(?:do not|don't|should not|shouldn't|never)\s+"
        r"(?:record|include|add|put|place|make|keep|treat|turn)\b)"
        r"|(?=\b(?:do not|don't|should not|shouldn't|never)\s+"
        r"(?:record|include|add|put|place|make|keep|treat|turn)\b)"
        r"|，"
        r"|请(?=(?:不要|别|不应|不应该)\s*"
        r"(?:(?:把|将)[^。！？.!?；;\n]{0,20}?)?\s*"
        r"(?:记录|加入|放进|列入|写入|算作|当作|成为))"
        r"|(?=(?:不要|别|不应|不应该)\s*"
        r"(?:(?:把|将)[^。！？.!?；;\n]{0,20}?)?\s*"
        r"(?:记录|加入|放进|列入|写入|算作|当作|成为))",
        re.IGNORECASE,
    )
    spans: list[tuple[str, int, int]] = []
    start = 0
    for match in separator.finditer(source):
        raw = source[start:match.start()]
        left = len(raw) - len(raw.lstrip())
        right = len(raw.rstrip())
        if right > left:
            spans.append((raw[left:right], start + left, start + right))
        start = match.end()
    raw = source[start:]
    left = len(raw) - len(raw.lstrip())
    right = len(raw.rstrip())
    if right > left:
        spans.append((raw[left:right], start + left, start + right))
    return spans


def _timeline_veto_scope(sentence: str) -> str | None:
    """Return the explicit user-veto scope for one source sentence."""
    if not isinstance(sentence, str):
        return None
    lowered = sentence.casefold()
    english = bool(
        re.search(
            r"\b(?:please\s+)?(?:do not|don't|should not|shouldn't|never)\s+"
            r"(?:record|include|add|put|place|make|keep|treat|turn)\b"
            r".{0,100}\b(?:timeline|dated events?|events?|records?)\b",
            lowered,
        )
        or re.search(
            r"\b(?:leave|keep|omit|exclude)\b.{0,50}\b(?:out of|off|from)\b"
            r".{0,30}\b(?:my\s+)?(?:timeline|records?|events?)\b",
            lowered,
        )
    )
    chinese = bool(
        re.search(
            r"(?:请)?(?:不要|别|不应|不应该)\s*"
            r"(?:(?:把|将)[^。！？.!?；;\n]{0,20}?)?\s*"
            r"(?:记录|加入|放进|列入|写入|算作|当作|成为)"
            r".{0,60}(?:时间线|事件|日期|记录)",
            sentence,
        )
    )
    if not (english or chinese):
        return None
    item_specific = bool(
        re.search(r"\b(?:this|that|the)\s+(?:event|item|entry|memory|reflection)\b", lowered)
        or re.search(
            r"\b(?:this|that|the)\s+(?!events?\b|records?\b|timeline\b)"
            r"[a-z][a-z'’-]*\b",
            lowered,
        )
        or re.search(r"(?:这件事|这个事件|这个条目|这段回忆|这条记录)", sentence)
    )
    return "item" if item_specific else "all"


class CodexRuntime:
    def __init__(self, *, home_root=None, command=None, provider_env=None, model=None,
                 base_url=None, timeout=None, worker_url=None, worker_secret=None,
                 worker_transport=None, task_publisher_enabled=None, issue14_admission=None):
        self._issue14_admission = validate_optional_issue14_admission(issue14_admission)
        self.home_root = Path(home_root or os.getenv('MEMORY_SPARK_CODEX_HOME', 'var/codex-users'))
        self.command = command or [os.getenv('MEMORY_SPARK_CODEX_BIN', 'codex'), 'app-server']
        self.provider_env = provider_env or {}
        self.model = model or os.getenv('MEMORY_SPARK_LLM_MODEL', 'gpt-5.6-luna-pooled')
        self.composer_model = os.getenv('MEMORY_SPARK_MEMOIR_COMPOSER_MODEL', 'legal2ai-luna-low')
        self.base_url = base_url or os.getenv('MEMORY_SPARK_LLM_BASE_URL', 'http://127.0.0.1:4000/v1')
        self.api_key = os.getenv('MEMORY_SPARK_LLM_API_KEY', '')
        if timeout is None:
            try:
                timeout = float(os.getenv('MEMORY_SPARK_CODEX_WORKER_TIMEOUT', str(WORKER_TIMEOUT)))
            except ValueError:
                timeout = WORKER_TIMEOUT
            timeout = min(max(timeout, 0.001), WORKER_MAX_TIMEOUT)
        self.timeout = timeout
        self.worker_url = (worker_url or os.getenv('MEMORY_SPARK_CODEX_WORKER_URL', '')).rstrip('/') or None
        self.worker_secret = worker_secret or os.getenv('MEMORY_SPARK_CODEX_WORKER_SECRET', '')
        # Tests and local evaluation may inject an isolated HTTP transport while
        # production continues to use the normal network client.
        self.worker_transport = worker_transport
        # Production keeps the existing task-database gate. Isolated
        # evaluation fixtures may opt into the same workspace publication
        # branch with their own deterministic publisher.
        self.task_publisher_enabled = (
            bool(os.getenv('MEMORY_SPARK_TASK_DB'))
            if task_publisher_enabled is None
            else bool(task_publisher_enabled)
        )
        self._locks = {}
        self._workspace_locks = {}
        self._turn_sequences: dict[str, int] = {}
        # The configured provider does not expose token/cost usage to this
        # application. Keep a separate request counter for evaluation receipts
        # so it is never mistaken for billing evidence.
        self._observed_worker_requests = 0
        self._news_engine = None

    def record_worker_request(self) -> None:
        self._observed_worker_requests += 1

    @property
    def observed_worker_requests(self) -> int:
        return self._observed_worker_requests

    def _lock(self, user_id):
        return self._locks.setdefault(user_id, asyncio.Lock())


    @asynccontextmanager
    async def _storage_lease(self, storage, *, timeout=120):
        """Wait within a bounded budget for conversation/workspace writes."""
        deadline = asyncio.get_running_loop().time() + timeout
        async with AsyncExitStack() as scope:
            while True:
                try:
                    lease = await scope.enter_async_context(AgentTurnLease(storage))
                except AgentTurnBusyError:
                    if asyncio.get_running_loop().time() >= deadline:
                        raise
                    await asyncio.sleep(0.1)
                    continue
                yield lease
                return

    async def turn(self, storage: UserStorage, text: str, project_id: str | None = None,
                   language: str = "en-AU", on_delta=None,
                   on_event=None,
                   evaluation: Mapping[str, Any] | None = None,
                   include_trajectory: bool = False,
                   evaluation_context: Mapping[str, Any] | None = None,
                   first_reply_localization: bool = False,
                   conversation_text: str | None = None,
                   client_turn_id: str | None = None,
                   source_kind: str = 'narrator_chat', recording_ids=None,
                   uploaded_photo_ids: list[str] | None = None,
                   photo_selection: dict | None = None,
                   workspace_focus: dict | None = None,
                   user_response: bool = True,
                   saved_place_hints: list | None = None,
                   trajectory: TrajectoryRecorder | None = None,
                   lifetime_context=None):
        if lifetime_context is None:
            raise ValueError('A canonical publication context is required')
        from .lifetime_memory_runtime import run_lifetime_turn
        return await run_lifetime_turn(self, storage,
            conversation_text if conversation_text is not None else original_conversation_text(text),
            publication=lifetime_context, project_id=project_id, language=language, client_turn_id=client_turn_id,
            source_kind=source_kind, uploaded_photo_ids=uploaded_photo_ids, photo_selection=photo_selection, recording_ids=recording_ids,
            workspace_focus=workspace_focus, user_response=user_response, on_delta=on_delta, on_event=on_event,
            evaluation=evaluation,trajectory=trajectory)


    @staticmethod
    def _task_sources(memories):
        sources = []
        for item in memories:
            if not item.get('id') or item.get('kind') not in {'agent', 'memoir', 'story_round'}:
                continue
            if any(path == 'full-memoir' or path.startswith('story-chapter:') for path in item.get('source_paths', [])):
                continue
            content = str(item.get('content', ''))
            if item.get('kind') == 'agent':
                if not content.startswith('Storyteller: '):
                    continue
                content = content.removeprefix('Storyteller: ').split('\nMemory Spark:', 1)[0]
            elif content.startswith('{'):
                try:
                    record = json.loads(content)
                except ValueError:
                    continue
                if record.get('type') != 'story_round':
                    continue
                content = str(record.get('answer', ''))
            if content.strip():
                sources.append(MemorySource(id=str(item['id']), content=content))
        return sources


    async def _worker_turn(self, *, user_id, prior, memories, profile, place_journey,
                           family_enabled, family_context, project_id, text,
                           language, conversation_rounds_completed=None, on_delta=None,
                           evaluation=None, agent_role='collector', on_event=None,
                           extraction_focus=None, diagnostic_request_id=None, interview_context=None,
                           trajectory: TrajectoryRecorder | None = None, canonical_events=False, governed=None):
        check_issue14_dispatch(self._issue14_admission, role=agent_role, correlation=evaluation)
        if not self.worker_secret:
            raise RuntimeError('Codex worker secret is not configured')
        request_id = new_request_id(diagnostic_request_id)
        started = time.perf_counter()
        model = self.composer_model if agent_role == 'composer' else self.model
        if agent_role == 'collector':
            model = collector_configuration(model).model
        evaluation = execution_correlation(evaluation, model)
        if trajectory and agent_role == 'collector':
            trajectory.correlation.update(execution_correlation(trajectory.correlation, model))
            trajectory.set_context(model=model)
        log_diagnostic(
            diagnostic_logger,
            'worker_request_start',
            request_id,
            component='memoir.api.worker_client',
            agent_role=agent_role,
            model=model,
            streaming=bool(on_delta or on_event),
        )
        payload = {
            'user_id': user_id,
            'thread_id': prior.get('codex_thread_id') if prior else None,
            'memories': [str(item.get('content', ''))[:2000] for item in memories[:20]],
            'profile': profile or {},
            'place_journey': place_journey or {},
            'family_enabled': family_enabled,
            'family_context': family_context or {},
            'project_id': project_id,
            'text': text,
            'model': model,
            'language': language,
            'diagnostic_request_id': request_id,
        }
        if governed is not None:
            payload['governed'] = governed
        if interview_context is not None:
            payload['interview_context'] = interview_context
        if canonical_events:
            payload['canonical_events'] = True
        if conversation_rounds_completed is not None:
            payload['conversation_rounds_completed'] = conversation_rounds_completed
        if evaluation:
            payload['evaluation'] = normalise_correlation(evaluation)
        if agent_role != 'collector':
            payload['agent_role'] = agent_role
        if extraction_focus in {'family_tree', 'author_timeline', 'place_journey'}:
            payload['extraction_focus'] = extraction_focus
        if project_id:
            payload['task_sources'] = [source.model_dump() for source in self._task_sources(memories)]
        execution_timeout = WORKSPACE_TIMEOUT if agent_role == 'workspace' else self.timeout
        worker_headers = {
            'X-Codex-Worker-Secret': self.worker_secret,
            'X-Memoir-Request-ID': request_id,
        }
        encoded=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode('utf-8')
        worker_headers={**worker_headers,'Content-Type':'application/json','Content-Length':str(len(encoded))}
        if governed is None:
            raise ValueError('A canonical execution contract is required')
        from .lifetime_memory_publication import GovernedRequestBody, ProviderPublication
        publisher = ProviderPublication(os.getenv('MEMOIR_PUBLICATION_DATABASE_URL'), authenticated_owner=user_id)
        request_content = {'content': GovernedRequestBody(encoded, publisher=publisher, fence=governed['fence'])}
        result: Any = None

        def preserve_failure_trajectory(error: BaseException) -> None:
            """Attach worker evidence to the exception and outer turn receipt."""
            partial = getattr(error, 'trajectory', None)
            if not isinstance(partial, Mapping) and isinstance(result, Mapping):
                candidate = result.get('trajectory')
                if isinstance(candidate, Mapping):
                    partial = candidate
            if trajectory is not None:
                if isinstance(partial, Mapping):
                    trajectory.append_trajectory(partial, source='codex-worker-failure')
                trajectory.record('application', 'codex.worker.failed', output={
                    'error_type': type(error).__name__,
                    'has_partial_trajectory': isinstance(partial, Mapping),
                })
                trajectory.finish(
                    None,
                    status='failed',
                    stop_reason='worker.failed',
                    error={'error_type': type(error).__name__},
                )
                partial = trajectory.payload()
            if isinstance(partial, Mapping) and isinstance(error, Exception):
                error.trajectory = dict(partial)

        try:
            if on_delta or on_event:
                # Keep consuming the worker stream after provider_complete so
                # artifact enumeration can finish after the API has committed
                # the visible reply. The returned task owns the HTTP client.
                provider_complete = asyncio.get_running_loop().create_future()
                self.record_worker_request()

                async def consume_worker_stream():
                    terminal = None
                    try:
                        client_options = {'timeout': execution_timeout + 15}
                        if self.worker_transport is not None:
                            client_options['transport'] = self.worker_transport
                        async with httpx.AsyncClient(**client_options) as client:
                            async with client.stream(
                                'POST',
                                f'{self.worker_url}/internal/codex/turn',
                                headers={
                                    **worker_headers,
                                    'Accept': 'application/x-ndjson',
                                },
                                **request_content,
                            ) as response:
                                if response.status_code >= 400:
                                    response.extensions[_WORKER_ERROR_BODY_EXTENSION] = (
                                        await _read_bounded_response_body(response)
                                    )
                                response.raise_for_status()
                                async for line in response.aiter_lines():
                                    if not line:
                                        continue
                                    event = json.loads(line)
                                    if event['type'] == 'text_delta' and on_delta:
                                        await on_delta(event['text'])
                                    elif event['type'] == 'codex_activity' and on_event:
                                        await on_event(event)
                                    elif event['type'] == 'provider_complete':
                                        provider = event.get('data') or {}
                                        if not provider_complete.done():
                                            provider_complete.set_result(provider)
                                    elif event['type'] == 'result':
                                        terminal = event['data']
                                    elif event['type'] == 'error':
                                        from .lifetime_memory_policy import PolicyUnavailable
                                        if governed is not None and event.get('code') == PolicyUnavailable.code:
                                            raise PolicyUnavailable()
                                        from .lifetime_memory_activation import CanonicalActivationUnavailable
                                        if governed is not None and event.get('code') == CanonicalActivationUnavailable.code:
                                            raise CanonicalActivationUnavailable()
                                        partial = event.get('trajectory')
                                        raise _WorkerStreamError(
                                            'Codex worker turn failed',
                                            partial if isinstance(partial, Mapping) else None,
                                        )
                        if not provider_complete.done():
                            provider_complete.set_result(terminal or {})
                        return (terminal or {}).get('artifacts', [])
                    except BaseException as error:
                        if not provider_complete.done():
                            provider_complete.set_exception(error)
                        raise

                artifact_task = asyncio.create_task(consume_worker_stream())
                try:
                    result = await provider_complete
                except BaseException:
                    artifact_task.cancel()
                    await asyncio.gather(artifact_task, return_exceptions=True)
                    raise
                result = dict(result)
                result['_artifact_task'] = artifact_task
            else:
                client_options = {'timeout': execution_timeout + 15}
                if self.worker_transport is not None:
                    client_options['transport'] = self.worker_transport
                self.record_worker_request()
                async with httpx.AsyncClient(**client_options) as client:
                    response = await client.post(
                        f'{self.worker_url}/internal/codex/turn',
                        headers=worker_headers,
                        **request_content,
                    )
                    response.raise_for_status()
                    result = response.json()
        except httpx.HTTPStatusError as error:
            from .lifetime_memory_policy import PolicyUnavailable
            if (governed is not None and error.response.status_code == 503
                    and error.response.headers.get('X-Error-Code') == PolicyUnavailable.code):
                raise PolicyUnavailable() from None
            from .lifetime_memory_activation import CanonicalActivationUnavailable
            if (governed is not None and error.response.status_code == 503
                    and error.response.headers.get('X-Error-Code') == CanonicalActivationUnavailable.code):
                raise CanonicalActivationUnavailable() from None
            error_payload = _worker_error_payload(error.response)
            if isinstance(error_payload, Mapping):
                partial = error_payload.get('trajectory')
                if isinstance(partial, Mapping):
                    error.trajectory = dict(partial)
            preserve_failure_trajectory(error)
            status_code = error.response.status_code
            log_diagnostic(
                diagnostic_logger,
                'worker_request_failed',
                request_id,
                component='memoir.api.worker_client',
                agent_role=agent_role,
                model=model,
                status='failed',
                failure_class=failure_class(error, status_code=status_code),
                http_status=status_code,
                elapsed_ms=elapsed_ms(started),
            )
            if status_code == 409:
                busy = AgentTurnBusyError('Codex worker is busy for this user')
                if isinstance(getattr(error, 'trajectory', None), Mapping):
                    busy.trajectory = dict(error.trajectory)
                raise busy from None
            from .lifetime_memory_engine import CollectorResponseUnavailable
            rejected = CollectorResponseUnavailable('The saved message needs another response attempt')
            if isinstance(getattr(error, 'trajectory', None), Mapping):
                rejected.trajectory = dict(error.trajectory)
            raise rejected from None
        except httpx.RequestError as error:
            preserve_failure_trajectory(error)
            log_diagnostic(
                diagnostic_logger,
                'worker_request_failed',
                request_id,
                component='memoir.api.worker_client',
                agent_role=agent_role,
                model=model,
                status='failed',
                failure_class='request_error',
                elapsed_ms=elapsed_ms(started),
            )
            from .lifetime_memory_engine import CollectorResponseUnavailable
            unavailable = CollectorResponseUnavailable('The saved message needs another response attempt')
            if isinstance(getattr(error, 'trajectory', None), Mapping):
                unavailable.trajectory = dict(error.trajectory)
            raise unavailable from None
        except BaseException as error:
            preserve_failure_trajectory(error)
            log_diagnostic(
                diagnostic_logger,
                'worker_request_failed',
                request_id,
                component='memoir.api.worker_client',
                agent_role=agent_role,
                model=model,
                status='failed',
                failure_class=failure_class(error),
                elapsed_ms=elapsed_ms(started),
            )
            raise
        finally:
            await request_content['content'].aclose()
        if not isinstance(result, dict) or not isinstance(result.get('thread_id'), str) or not isinstance(result.get('reply'), str):
            log_diagnostic(
                diagnostic_logger,
                'worker_request_failed',
                request_id,
                component='memoir.api.worker_client',
                agent_role=agent_role,
                model=model,
                status='failed',
                failure_class='invalid_response',
                elapsed_ms=elapsed_ms(started),
            )
            raise RuntimeError('Codex worker returned an invalid turn result')
        result.setdefault('artifacts', [])
        result['_workspace_capable'] = True
        log_diagnostic(
            diagnostic_logger,
            'worker_request_terminal',
            request_id,
            component='memoir.api.worker_client',
            agent_role=agent_role,
            model=model,
            status='completed',
            terminal_event='worker.response',
            elapsed_ms=elapsed_ms(started),
        )
        return result
