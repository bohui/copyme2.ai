"""Canonical draft readbacks for offline evaluation tests."""
from copy import deepcopy
from uuid import NAMESPACE_URL, uuid5


OWNER = '00000000-0000-4000-8000-000000000001'


def checkpoint(project, language, ordinal, text, source_id='original-1', *, owner=OWNER, records=None):
    conversation = str(uuid5(NAMESPACE_URL, project + '/conversation'))
    records = deepcopy(records) if records is not None else [{
        'id': 'chapter__first', 'event_id': 'saved-event', 'event_revision': 1,
        'preview': {'locale': language, 'text': text},
        'source_refs': [{'source_id': source_id, 'version': 1, 'quote': text}],
        'original_withheld': False, 'approval_required': False,
        'approved': False, 'human_locked': False}]
    head = {'owner_id': owner, 'conversation_id': conversation, 'project_id': project,
        'locale': language, 'status': 'ready', 'coverage_round': ordinal,
        'revision': ordinal // 5, 'source_revision': ordinal, 'current_source_revision': ordinal,
        'event_revision': ordinal, 'current_event_revision': ordinal, 'policy_epoch': 1,
        'snapshot_id': str(uuid5(NAMESPACE_URL, project + '/' + str(ordinal))),
        'snapshot_state': 'completed', 'root_digest': 'a' * 64,
        'retrieval_complete': True, 'approval_required': False, 'updating': False, 'error': None,
        'preview': records[0]['preview'], 'first_record': records[0],
        'progress': {'extraction': {'extracted_through': ordinal, 'pending_inputs': 0}}}
    pages = []
    for offset in range(0, len(records), 8):
        complete = offset + 8 >= len(records)
        pages.append({**{key: head[key] for key in (
            'owner_id', 'conversation_id', 'project_id', 'locale', 'snapshot_id', 'snapshot_state',
            'root_digest', 'source_revision', 'event_revision', 'policy_epoch', 'approval_required')},
            'snapshot_complete': True, 'preference_revision': 0, 'records': records[offset:offset + 8], 'complete': complete,
            'next_cursor': None if complete else str(uuid5(NAMESPACE_URL, project + '/page/' + str(offset)))})
    head.update(page_complete=len(records) == 1, next_cursor=None if len(records) == 1 else str(uuid5(NAMESPACE_URL, project + '/head-cursor')))
    identity = {key: head[key] for key in ('owner_id', 'conversation_id', 'project_id')} | {'language': language}
    return {'milestone': ordinal, 'draft': head, 'pages': pages, 'identity': identity,
            'readback_protocol': 'lifetime_private_draft_pages'}
