"""Interview history, attribution and context regressions at the provider boundary."""
from copy import deepcopy
import json
from uuid import UUID

from apps.api.conversation_reply import reply_packet, reply_schema
from apps.api.conversation_reply_transport import reply_messages
from apps.api.lifetime_memory_context import ContextCheckpoint
from apps.api.lifetime_memory_contracts import SourceManifest
from apps.api.lifetime_memory_engine import validate_governed_context, _AssistantExchange
from test_lifetime_memory_engine import fixture


def checkpoint_packet():
    governed, context = fixture()
    packet = validate_governed_context(governed, context)
    older = packet.current.narrator.model_copy(update={
        'source_id': UUID(int=41), 'original': 'My grandmother sold apples.', 'char_end': 27})
    checkpoint = ContextCheckpoint(checkpoint_id=UUID(int=42), identity=packet.identity,
        policy_epoch=packet.policy_epoch, coverage_end=1, model=packet.model,
        prompt_version=packet.prompt_version, pinned=packet.pinned,
        manifest=SourceManifest(identity=packet.identity, policy_epoch=packet.policy_epoch,
            source_revision=1, sources=[{'source_id': older.source_id, 'version': 1}]),
        evidence=[older])
    return packet.model_copy(update={'checkpoint': checkpoint, 'coverage_end': 1,
        'current': packet.current.model_copy(update={'sequence': 2})}), older


def test_lossless_checkpoint_originals_reach_the_interviewer():
    packet, older = checkpoint_packet()
    messages = reply_messages(reply_packet(packet), '')
    assert older.original in json.dumps(messages, ensure_ascii=False)


def test_saved_questions_and_answers_use_native_roles_in_chronological_order():
    governed, context = fixture()
    packet = validate_governed_context(governed, context)
    earlier = packet.current.model_copy(update={'sequence': 1, 'conversation_saved': True,
        'assistant': _AssistantExchange(role='assistant', text='Which school was that?', personal_testimony=False)})
    view = reply_packet(packet)
    view['dialogue'] = [earlier.model_dump(mode='json')]
    view['current']['sequence'] = 2
    view['current']['narrator'].update(source_id=str(UUID(int=50)), original='The village school.')
    messages = reply_messages(view, '')
    spoken = [(m['role'], m['content']) for m in messages if m['role'] in {'user', 'assistant'}]
    assert ('assistant', 'Which school was that?') in spoken
    assert spoken[-1] == ('user', 'The village school.')
    assert spoken.index(('user', earlier.narrator.original)) < spoken.index(('assistant', 'Which school was that?'))


def test_background_passages_are_sent_once_even_across_events_and_retrieval():
    packet, older = checkpoint_packet()
    view = reply_packet(packet)
    passage = dict(id=str(older.source_id), version=1, char_start=0,
        char_end=len(older.original), text=older.original, sequence=1)
    view['background_deliveries'] = [dict(skill='memoir-author-timeline', events=[
        dict(id=f'event-{i}', revision=1, original_passages=[passage, deepcopy(passage)],
            source_refs=[{'source_id': passage['id'], 'version': 1, 'char_start': 0, 'char_end': passage['char_end']}])
        for i in range(3)])]
    encoded = json.dumps(reply_messages(view, ''), ensure_ascii=False)
    assert encoded.count(older.original) == 1


def test_reply_schema_does_not_rewrite_cache_prefix_for_each_context():
    _, context = fixture()
    other = deepcopy(context)
    other['prepared_questions'] = [dict(id='new-question', question='Who came with you?',
        source_id=context['source']['id'], source_version=1, quote=context['source']['text'],
        char_start=0, char_end=len(context['source']['text']))]
    assert reply_schema(context) == reply_schema(other)
