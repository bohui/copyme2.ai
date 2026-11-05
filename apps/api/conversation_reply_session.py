"""Persistent Codex interview threads; canonical storage authorizes every resume."""
from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
import tempfile

import httpx

from .codex_agent import CodexConnection, CodexRequestError, provider_config
from .codex_worker_files import write_config
from .codex_home_store import CodexHomeStore, HomeCheckpointUnavailable, checkpoint_failure
from .conversation_reply_context import conversation_context, context_update
from .lifetime_memory_context import serialize_packet


def _digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _read_state(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd) as source:
            if os.fstat(source.fileno()).st_size > 512_000:
                return None
            value = json.load(source)
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def _write_state(path, state):
    fd, temporary = tempfile.mkstemp(prefix='.interview-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as output:
            os.fchmod(output.fileno(), 0o600)
            json.dump(state, output, ensure_ascii=False, separators=(',', ':'))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _item(message):
    role = message['role']
    item = dict(type='message', role=role, content=[dict(
        type='output_text' if role == 'assistant' else 'input_text', text=message['content'])])
    if role == 'assistant':
        item['phase'] = 'final_answer'
    return item


class InterviewSession:
    def __init__(self, root, packet, view, schema, model, effort, base_url, tool_specs):
        self.packet = packet
        self.scope = _digest(serialize_packet(dict(identity=packet.identity.model_dump(mode='json'),
            epoch=packet.policy_epoch, generation=packet.fence.execution_generation,
            exclusions=packet.pinned.excluded_topics, instructions=packet.instructions,
            schema=schema, model=model, effort=effort, provider=base_url, tools=tool_specs)))
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o711)
        stem = f'interview-{packet.identity.owner_id}-{packet.identity.conversation_id}'
        self.path = self.root / ('.' + stem + '.json')
        self.home = self.root / (stem + '-' + self.scope[:16])
        self.home.mkdir(mode=0o700, exist_ok=True)
        self.state = _read_state(self.path)
        self.entities, self.history = conversation_context(view)
        self.sources = {}
        self.thread_id = None
        self.resumed = False

    def compatible(self):
        state = self.state
        if (not state or state.get('scope') != self.scope or not isinstance(state.get('entities'), dict)
                or not isinstance(state.get('thread_id'), str)
                or not isinstance(state.get('sequence'), int)
                or not state['sequence'] < self.packet.current.sequence):
            return False
        execution = self.packet.interview_context.get('execution')
        if execution:
            return all(execution.get(key) == state.get(key)
                for key in ('thread_id', 'sequence', 'source_id', 'reply_sha256'))
        # Tests and older adapters can prove commitment with the admitted raw tail.
        return any(row.sequence == state['sequence'] and str(row.narrator.source_id) == state.get('source_id')
            and row.assistant and _digest(row.assistant.text) == state.get('reply_sha256') for row in self.packet.tail)

    def accept(self, delivered_reply):
        _write_state(self.path, dict(scope=self.scope, thread_id=self.thread_id,
            sequence=self.packet.current.sequence, source_id=str(self.packet.current.narrator.source_id),
            source_version=self.packet.current.narrator.version,
            reply_sha256=_digest(delivered_reply), entities=self.entities, sources=self.sources))


@asynccontextmanager
async def open_interview(*, root, packet, view, schema, model, effort, base_url, api_key,
        command, timeout, admission, connection_factory=None, uid=None, apply_owner=False,
        trajectory=None, progress=None, connection_options=None, repair=None, tools=None,
        context_window=131072, compact_at=60000):
    from .model_configuration import configured_effort
    effort = effort or configured_effort()
    specs = tools.specs() if tools is not None else []
    session = InterviewSession(root, packet, view, schema, model, effort, base_url, specs)
    checkpoint = None
    session.checkpoint = None
    session.checkpoint_status = 'disabled'
    try:
        try:
            checkpoint = CodexHomeStore.configured()
        except ValueError as error:
            raise HomeCheckpointUnavailable('Mira runtime storage is not configured') from error
        if checkpoint is not None:
            session.checkpoint_status = 'pending'
            if not repair and await checkpoint.restore(session,
                    uid=os.getuid() if uid is None else uid, apply_owner=apply_owner):
                _write_state(session.path, session.state)
    except (OSError, ValueError, httpx.HTTPError) as error:
        session.checkpoint_status = 'restore_failed'
        checkpoint_failure('restore', error)
    write_config(session.home, session.root, os.getuid() if uid is None else uid,
        provider_config(base_url, model, governed=True), apply_owner=apply_owner)
    options = dict(provider_env={'MEMORY_SPARK_LLM_API_KEY': api_key}, timeout=timeout,
        request_admission=admission, trajectory=trajectory, progress=progress, **(connection_options or {}))
    if tools is not None:
        options['tool_handler'] = tools.call
    async with (connection_factory or CodexConnection)(command, session.home, **options) as connection:
        params = dict(cwd=str(session.home), modelProvider='llm_provider', model=model,
            approvalPolicy='never', sandbox='read-only', baseInstructions=packet.instructions,
            config=dict(model_context_window=context_window, model_auto_compact_token_limit=compact_at))
        if tools is not None:
            params['dynamicTools'] = tools.specs()
        if not repair and session.compatible():
            try:
                result = await connection.request('thread/resume', {**params,
                    'threadId': session.state['thread_id'], 'excludeTurns': True})
                session.thread_id = result['thread']['id']
                session.resumed = session.thread_id == session.state['thread_id']
            except CodexRequestError as error:
                if not error.missing_thread:
                    raise
        if not session.resumed:
            result = await connection.request('thread/start', params)
            session.thread_id = result['thread']['id']
        if not isinstance(session.thread_id, str) or not session.thread_id:
            raise ValueError('Interview thread is unavailable')
        # A failed, interrupted or uncommitted candidate must never be resumed.
        session.path.unlink(missing_ok=True)
        session.sources = (session.state.get('sources', {}) if session.resumed else {}).copy()
        for entry in [*view.get('dialogue', []), view['current']]:
            narrator = entry['narrator']
            session.sources[f"{narrator['source_id']}:{narrator['version']}"] = [entry['sequence'],
                dict(char_start=narrator['char_start'], char_end=narrator['char_end'])]
        session.entities, session.history = conversation_context(view, session.sources,
            after_sequence=session.state['sequence'] if session.resumed else None)
        previous = session.state['entities'] if session.resumed else None
        items = [_item(message) for message in session.history]
        items.append(_item(dict(role='user', content=context_update(session.entities, previous))))
        if repair:
            items.append(_item(dict(role='developer', content=repair)))
        await connection.request('thread/inject_items', dict(threadId=session.thread_id, items=items))
        yield session, connection
    # __aexit__ has reaped the app-server and its SQLite writers before upload.
    state = _read_state(session.path)
    if checkpoint is not None and state is not None:
        try:
            session.checkpoint = await checkpoint.save(session, state)
            session.checkpoint_status = 'verified'
        except (OSError, ValueError, httpx.HTTPError) as error:
            session.checkpoint_status = 'save_failed'
            checkpoint_failure('save', error)
            raise HomeCheckpointUnavailable('Mira runtime checkpoint was not verified') from error
