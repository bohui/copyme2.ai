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


@pytest.mark.parametrize('repair', [None, 'Repair a workspace citation.'])
@pytest.mark.parametrize('history', ['tail', 'recent_dialogue'])
def test_rebuilt_history_keeps_source_references_without_repeating_originals(tmp_path, repair, history):
    Native.calls = []
    first, second, context, _ = packets()
    settings = options(tmp_path, second, context)
    if history == 'recent_dialogue':
        settings['view']['dialogue'] = []
        narrator = first.current.narrator
        settings['view']['context']['recent_dialogue'] = [dict(
            question=dict(role='assistant', delivered=True, sequence=0, text='What do you remember?'),
            response=dict(id=str(narrator.source_id), version=narrator.version, sequence=1,
                role='user', complete=True, text=narrator.original))]
    async def run():
        async with open_interview(**settings, repair=repair):
            pass
    asyncio.run(run())
    items = next(call[1]['items'] for call in Native.calls if call[0] == 'thread/inject_items')
    context_item = next(item for item in items
        if item['role'] == 'user' and item['content'][0]['text'].startswith('{"memoir_context":'))
    entities = json.loads(context_item['content'][0]['text'])['memoir_context']['updates']
    context_index = items.index(context_item)
    assert context_index > 0
    assert all(item['role'] in {'user', 'assistant'} for item in items[:context_index])
    assert all(item['role'] == 'developer' for item in items[context_index + 1:])
    references = {ref['source_id']: ref for ref in entities['evidence'].values()}
    for packet in (first, second):
        narrator = packet.current.narrator
        ref = references[str(narrator.source_id)]
        assert ref == dict(source_id=str(narrator.source_id), version=narrator.version,
            char_start=narrator.char_start, char_end=narrator.char_end,
            role='storyteller', conversation_sequence=packet.current.sequence)
    assert sum(first.current.narrator.original in json.dumps(item) for item in items) == 1
    assert second.current.narrator.original not in json.dumps(items)


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
