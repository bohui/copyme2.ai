"""Codex app-server stdio protocol. Caller supplies an isolated user runtime."""
import asyncio
import json
import logging
import os
import signal
import time
from pathlib import Path

from .diagnostics import configure_diagnostic_logger, elapsed_ms, log_diagnostic, new_request_id
from .trajectory_evaluation import normalise_correlation, protocol_request_evidence
from .issue14_execution_admission import check_issue14_dispatch, validate_optional_issue14_admission
from .codex_progress import WorkerProgress


diagnostic_logger = logging.getLogger("memoir.appserver.diagnostics")
configure_diagnostic_logger(diagnostic_logger)


class CodexConnection:
    def __init__(self, command, home, *, provider_env=None, timeout=120, trajectory=None,
                 issue14_admission=None, progress=None):
        if progress is not None and type(progress) is not WorkerProgress:
            raise TypeError('Owned protocol progress required')
        self.progress = progress
        self._issue14_admission = validate_optional_issue14_admission(issue14_admission)
        self.command = command
        # Codex uses this value for both cwd and HOME/CODEX_HOME.  Resolve it
        # once so a relative runtime root cannot become a nested path from the
        # child process's working directory and make app-server exit at start.
        self.home = Path(home).expanduser().resolve()
        self.provider_env = provider_env or {}
        self.timeout = timeout
        self.sequence = 0
        self.events = []
        self.trajectory = trajectory

    async def __aenter__(self):
        check_issue14_dispatch(self._issue14_admission, role='native')
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        env = {key: os.environ[key] for key in ('PATH', 'SYSTEMROOT', 'TMPDIR') if key in os.environ}
        env.update(self.provider_env)
        env.update({'HOME': str(self.home), 'CODEX_HOME': str(self.home)})
        launching = asyncio.create_task(asyncio.create_subprocess_exec(
            *self.command, cwd=self.home, env=env, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
            limit=16 * 1024 * 1024))
        try:
            self.process = await asyncio.shield(launching)
        except asyncio.CancelledError:
            # A lease/disconnect can cancel us while spawn is still returning
            # its handle. Obtain that handle before trying to reap the child.
            while not launching.done():
                try:
                    await asyncio.shield(launching)
                except asyncio.CancelledError:
                    continue
            self.process = launching.result()
            await self.__aexit__(None, None, None)
            raise
        try:
            await self.request('initialize', {'clientInfo': {'name': 'memory_spark', 'version': '1.0.0'},
                                              'capabilities': {'experimentalApi': True}})
            await self.send({'method': 'initialized', 'params': {}})
        except BaseException:
            await self.__aexit__(None, None, None)
            raise
        return self

    async def __aexit__(self, *args):
        # Include any children of app-server; the supervisor retains CAP_KILL
        # while the tenant process drops to an unprivileged UID.
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
            if self.process.returncode is None:
                await asyncio.wait_for(self.process.wait(), 5)
        except (ProcessLookupError, asyncio.TimeoutError):
            pass
        finally:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await self.process.wait()

    async def send(self, message):
        check_issue14_dispatch(self._issue14_admission, role='native')
        self.process.stdin.write((json.dumps(message) + '\n').encode())
        await self.process.stdin.drain()

    async def receive(self):
        line = await self.process.stdout.readline()
        if not line:
            raise RuntimeError('Codex app-server closed the connection')
        return json.loads(line)

    async def request(self, method, params):
        check_issue14_dispatch(self._issue14_admission, role='native')
        self.sequence += 1
        request_id = self.sequence
        if self.trajectory:
            self.trajectory.record('codex', f'request.{method}', input={
                'id': request_id,
                'params': protocol_request_evidence(method, params),
            })
        await self.send({'id': request_id, 'method': method, 'params': params})
        async with asyncio.timeout(self.timeout):
            while True:
                message = await self.receive()
                if message.get('id') == request_id and 'method' not in message:
                    if 'error' in message:
                        if self.trajectory:
                            self.trajectory.record('codex', f'response.{method}', error=message.get('error'))
                        raise RuntimeError('Codex app-server rejected ' + method)
                    if self.trajectory:
                        self.trajectory.record('codex', f'response.{method}', output=message.get('result'))
                    return message['result']
                await self.handle_event(message)

    async def handle_event(self, message):
        if self.trajectory:
            self.trajectory.record_protocol(message)
        # Never grant tool execution or approvals implicitly from model output.
        if 'id' in message and 'method' in message:
            await self.send({'id': message['id'], 'error': {'code': -32601,
                'message': 'This application has not enabled this tool'}})
        else:
            self.events.append(message)

    async def turn(self, thread_id, text, on_delta=None, responsesapi_client_metadata=None,
                   output_schema=None, on_event=None, effort=None):
        check_issue14_dispatch(self._issue14_admission, role='native',
            correlation=responsesapi_client_metadata)
        self.events.clear()
        started = time.perf_counter()
        params = {'threadId': thread_id, 'input': [{'type': 'text', 'text': text}],
                  'effort': effort or os.getenv('MEMORY_SPARK_LLM_REASONING_EFFORT', 'max')}
        if output_schema is not None:
            params['outputSchema'] = output_schema
        metadata = normalise_correlation(responsesapi_client_metadata)
        request_id = new_request_id(metadata.get('request_id'))
        metadata['request_id'] = request_id
        log_diagnostic(
            diagnostic_logger,
            'appserver_turn_start',
            request_id,
            component='memoir.appserver.client',
            model=metadata.get('model'),
        )
        if metadata:
            params['responsesapiClientMetadata'] = {
                key: value for key, value in metadata.items()
                if key in {
                    'run_id', 'case_id', 'dataset', 'dataset_version',
                    'application_revision', 'skill_hash', 'generation_name',
                    'evaluator_version', 'rubric_version', 'judge_rubric_version',
                    'model', 'provider', 'variant',
                    'round_id',
                    'trace_id', 'observation_id', 'job_id', 'checkpoint_id',
                    'request_id',
                }
            }
        if self.progress:
            self.progress.begin_turn()
        result = await self.request('turn/start', params)
        turn_id = result['turn']['id']
        if self.progress:
            self.progress.bind_turn(thread_id, turn_id)
        messages = []
        streamed_items = set()
        async with asyncio.timeout(self.timeout):
            while True:
                queued = bool(self.events)
                event = self.events.pop(0) if queued else await self.receive()
                if 'method' in event and 'id' in event:
                    await self.handle_event(event)
                    continue
                # handle_event already recorded queued notifications on receipt.
                # Distinct notifications with identical IDs/payloads still count.
                if self.trajectory and not queued:
                    self.trajectory.record_protocol(event, phase='codex.turn')
                params = event.get('params', {})
                if params.get('threadId') != thread_id:
                    continue
                if self.progress:
                    self.progress.observe(event.get('method'), params)
                if on_event and event.get('method') in ('item/started', 'item/completed') and params.get('turnId') == turn_id:
                    item = params.get('item', {})
                    # Forward only public operation metadata, never arguments,
                    # command output, agent text, or private reasoning.
                    names = {'commandExecution': 'Command', 'mcpToolCall': 'Tool',
                             'dynamicToolCall': 'Tool', 'fileChange': 'File update',
                             'webSearch': 'Web search'}
                    kind = item.get('type')
                    if kind in names and item.get('id'):
                        status = 'running' if event['method'] == 'item/started' else 'completed'
                        if item.get('status') in ('failed', 'declined') or item.get('exitCode') not in (None, 0):
                            status = 'failed'
                        await on_event({'type': 'codex_activity', 'data': {
                            'id': f"codex:{thread_id}:{turn_id}:{item['id']}",
                            'kind': 'tool_call', 'label': item.get('tool') or names[kind],
                            'operation': kind, 'status': status,
                        }})
                if event.get('method') == 'item/agentMessage/delta' and on_delta:
                    streamed_items.add(params.get('itemId'))
                    await on_delta(params.get('delta', ''))
                if event.get('method') == 'item/completed':
                    item = params.get('item', {})
                    if item.get('type') == 'agentMessage':
                        messages.append(item['text'])
                        if on_delta and item.get('id') not in streamed_items:
                            await on_delta(item['text'])
                if event.get('method') == 'turn/completed' and params['turn']['id'] == turn_id:
                    if params['turn']['status'] != 'completed':
                        log_diagnostic(
                            diagnostic_logger,
                            'appserver_turn_failed',
                            request_id,
                            component='memoir.appserver.client',
                            model=metadata.get('model'),
                            status='failed',
                            terminal_event='turn.completed',
                            terminal_status=params['turn'].get('status'),
                            failure_class='turn_status',
                            elapsed_ms=elapsed_ms(started),
                        )
                        if self.trajectory:
                            self.trajectory.record('codex.turn', 'turn.failed', output=params['turn'])
                        raise RuntimeError('Codex turn failed; no reply was substituted')
                    log_diagnostic(
                        diagnostic_logger,
                        'appserver_turn_terminal',
                        request_id,
                        component='memoir.appserver.client',
                        model=metadata.get('model'),
                        status='completed',
                        terminal_event='turn.completed',
                        terminal_status='completed',
                        elapsed_ms=elapsed_ms(started),
                    )
                    if self.trajectory:
                        self.trajectory.record('codex.turn', 'turn.completed', output={'turn': params['turn'], 'message_count': len(messages)})
                    if self.progress:
                        self.progress.complete_turn()
                    return '\n'.join(messages)


def provider_config(base_url, model):
    """Generate TOML without embedding gateway credentials in persisted config."""
    return '\n'.join([
        'model_provider = "llm_provider"',
        'model = ' + json.dumps(model),
        'model_reasoning_effort = ' + json.dumps(os.getenv('MEMORY_SPARK_LLM_REASONING_EFFORT', 'max')),
        'approval_policy = "never"',
        'sandbox_mode = "read-only"',
        '[model_providers.llm_provider]',
        'name = "Local llm_provider"',
        'base_url = ' + json.dumps(base_url.rstrip('/')),
        'wire_api = "responses"',
        'env_key = "MEMORY_SPARK_LLM_API_KEY"',
        'requires_openai_auth = false',
        '[features]',
        'memories = true',
        'shell_tool = false',
        '[memories]',
        'generate_memories = true',
        'use_memories = true',
        '',
    ])
