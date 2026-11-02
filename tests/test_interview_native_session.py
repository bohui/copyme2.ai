import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
from uuid import UUID

import pytest

from apps.api.conversation_reply import reply_packet, reply_schema
from apps.api.conversation_reply_session import open_interview
from apps.api.lifetime_memory_engine import _AssistantExchange, validate_governed_context
from test_lifetime_memory_engine import fixture


class Native:
    calls = []

    def __init__(self, command, home, **options):
        self.calls.append(('connect', home, options))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def request(self, method, params):
        self.calls.append((method, deepcopy(params)))
        return {'thread': {'id': params.get('threadId', 'native-thread')}}


@asynccontextmanager
async def admission():
    yield


def packets():
    governed, context = fixture()
    first = validate_governed_context(governed, context)
    reply = 'Which school was that?'
    previous = first.current.model_copy(update={'conversation_saved': True,
        'assistant': _AssistantExchange(role='assistant', text=reply, personal_testimony=False)})
    second = first.model_copy(update={'tail': [previous], 'current': first.current.model_copy(update={
        'sequence': 2, 'narrator': first.current.narrator.model_copy(update={
            'source_id': UUID(int=5), 'original': 'The village school.', 'char_end': 19})})})
    return first, second, context, reply


def options(tmp_path, packet, context):
    return dict(root=tmp_path, packet=packet, view=reply_packet(packet), schema=reply_schema(context),
        model=packet.model, effort='low', base_url='http://provider.invalid/v1', api_key='synthetic',
        command=['fake'], timeout=2, admission=admission, connection_factory=Native)


def test_next_turn_resumes_native_history_and_appends_only_context_changes(tmp_path):
    Native.calls = []
    first, second, context, reply = packets()
    async def run():
        async with open_interview(**options(tmp_path, first, context)) as (session, _):
            session.accept(reply)
        paused = second.model_copy(update={'pinned': second.pinned.model_copy(update={'paused_topics': ['Shanghai']})})
        async with open_interview(**options(tmp_path, paused, context)) as (session, _):
            assert session.resumed
            session.accept('Who taught you there?')
    asyncio.run(run())
    assert [call[0] for call in Native.calls if call[0] != 'connect'] == [
        'thread/start', 'thread/inject_items', 'thread/resume', 'thread/inject_items']
    injections = [call[1]['items'] for call in Native.calls if call[0] == 'thread/inject_items']
    assert len(injections[1]) == 1
    delta = json.loads(injections[1][0]['content'][0]['text'])['memoir_context']['updates']
    assert delta['preferences']['current']['paused_topics'] == ['Shanghai']
    assert 'context' not in delta and 'brief' not in delta
    assert first.current.narrator.original not in json.dumps(injections[1])


@pytest.mark.parametrize('change', ['exclusion', 'epoch', 'uncommitted', 'retry', 'corrupt'])
def test_unsafe_or_uncommitted_history_starts_from_authorized_canonical_items(tmp_path, change):
    Native.calls = []
    first, second, context, reply = packets()
    async def run():
        async with open_interview(**options(tmp_path, first, context)) as (session, _):
            session.accept(reply)
            path = session.path
        candidate = second
        if change == 'exclusion':
            candidate = second.model_copy(update={'pinned': second.pinned.model_copy(update={'excluded_topics': ['school']})})
        elif change == 'epoch':
            candidate = second.model_copy(update={'policy_epoch': 2})
        elif change == 'uncommitted':
            candidate = second.model_copy(update={'interview_context': {'execution': {'thread_id': 'older-committed-thread'}}})
        elif change == 'retry':
            candidate = first
        elif change == 'corrupt':
            path.write_text('broken')
        async with open_interview(**options(tmp_path, candidate, context)) as (session, _):
            assert not session.resumed
    asyncio.run(run())
    assert not any(call[0] == 'thread/resume' for call in Native.calls)
