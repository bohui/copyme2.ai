"""Bounded canonical draft evidence shared by the retained evaluation paths."""
from uuid import UUID
import re


PAGE_LIMIT = 8
MAX_PAGES = 128
READBACK_PROTOCOL = 'lifetime_private_draft_pages'
PREDICATES = frozenset({
    'identity', 'draft_shape', 'draft_status', 'updating', 'error', 'approval_required',
    'snapshot_state', 'retrieval_complete', 'coverage_round', 'revision', 'snapshot_id',
    'root_digest', 'frozen_revisions', 'progress_shape', 'extraction_shape',
    'extracted_through', 'pending_inputs', 'preview_shape', 'preview_locale',
    'preview_text_type', 'preview_text_empty', 'protocol', 'pages_shape', 'page_bound',
    'page_shape', 'page_scope', 'page_complete', 'page_cursor', 'records_shape',
    'record_shape', 'record_id', 'record_approval', 'record_event', 'record_preview',
    'record_sources', 'helper_exception'})


class CheckpointReadbackError(ValueError):
    def __init__(self, predicate):
        super().__init__('Canonical checkpoint unavailable or inconsistent')
        self.predicate = predicate


def require(condition, predicate):
    if not condition:
        raise CheckpointReadbackError(predicate)


def _uuid(value):
    try:
        return type(value) is str and str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def checkpoint_binding(identity, owner, project, language):
    require(type(identity) is dict and identity.get('owner_id') == owner
        and identity.get('project_id') == project and _uuid(owner)
        and _uuid(identity.get('conversation_id')) and language in ('en-AU', 'zh-CN'), 'identity')
    return {key: identity[key] for key in ('owner_id', 'conversation_id', 'project_id')} | {'language': language}


def validate_head(head, binding, ordinal):
    require(type(head) is dict, 'draft_shape')
    require(all(head.get(key) == binding[key] for key in ('owner_id', 'conversation_id', 'project_id'))
        and head.get('locale') == binding['language'], 'identity')
    require(head.get('status') == 'ready', 'draft_status')
    require(head.get('updating') is False, 'updating')
    require(head.get('error') is None, 'error')
    require(head.get('approval_required') is False, 'approval_required')
    require(head.get('snapshot_state') == 'completed', 'snapshot_state')
    require(head.get('retrieval_complete') is True, 'retrieval_complete')
    require(type(head.get('coverage_round')) is int and head['coverage_round'] == ordinal, 'coverage_round')
    require(type(head.get('revision')) is int and head['revision'] > 0, 'revision')
    require(_uuid(head.get('snapshot_id')), 'snapshot_id')
    require(type(head.get('root_digest')) is str and re.fullmatch('[0-9a-f]{64}', head['root_digest']), 'root_digest')
    require(all(type(head.get(key)) is int and head[key] >= 0 for key in (
        'source_revision', 'current_source_revision', 'event_revision', 'current_event_revision', 'policy_epoch'))
        and head['source_revision'] == head['current_source_revision']
        and head['event_revision'] == head['current_event_revision'] and head['policy_epoch'] >= 1, 'frozen_revisions')
    progress = head.get('progress')
    require(type(progress) is dict, 'progress_shape')
    extraction = progress.get('extraction')
    require(type(extraction) is dict, 'extraction_shape')
    require(type(extraction.get('extracted_through')) is int and extraction['extracted_through'] == ordinal, 'extracted_through')
    require(type(extraction.get('pending_inputs')) is int and extraction['pending_inputs'] == 0, 'pending_inputs')
    preview = head.get('preview')
    require(type(preview) is dict, 'preview_shape')
    require(preview.get('locale') == binding['language'], 'preview_locale')
    require(type(preview.get('text')) is str, 'preview_text_type')
    require(bool(preview['text'].strip()), 'preview_text_empty')


def checkpoint_records(checkpoint, binding, ordinal, accepted):
    require(type(checkpoint) is dict and checkpoint.get('readback_protocol') == READBACK_PROTOCOL, 'protocol')
    head, pages = checkpoint.get('draft'), checkpoint.get('pages')
    validate_head(head, binding, ordinal)
    require(type(pages) is list and 0 < len(pages) <= MAX_PAGES, 'pages_shape')
    records, seen, cursors = [], set(), set()
    preference_revision = None
    for index, page in enumerate(pages):
        require(type(page) is dict, 'page_shape')
        require(all(type(page.get(key)) is type(head[key]) and page[key] == head[key] for key in (
            'owner_id', 'conversation_id', 'project_id', 'snapshot_id', 'root_digest',
            'locale', 'source_revision', 'event_revision', 'policy_epoch', 'snapshot_state'))
            and page.get('snapshot_complete') is True and page.get('approval_required') is False, 'page_scope')
        require(type(page.get('preference_revision')) is int and page['preference_revision'] >= 0
            and (preference_revision is None or page['preference_revision'] == preference_revision), 'page_scope')
        preference_revision = page['preference_revision']
        complete, cursor = index == len(pages) - 1, page.get('next_cursor')
        require(page.get('complete') is complete, 'page_complete')
        if complete:
            require(cursor is None, 'page_cursor')
        else:
            require(type(cursor) is str and 0 < len(cursor) <= 512 and cursor not in cursors, 'page_cursor')
        cursors.add(cursor)
        require(type(page.get('records')) is list and 0 < len(page['records']) <= PAGE_LIMIT, 'records_shape')
        for record in page['records']:
            require(type(record) is dict, 'record_shape')
            require(type(record.get('id')) is str and bool(record['id']) and record['id'] not in seen, 'record_id')
            require(record.get('approval_required') is False and record.get('original_withheld') is False, 'record_approval')
            require(type(record.get('event_id')) is str and bool(record['event_id'])
                and type(record.get('event_revision')) is int and record['event_revision'] > 0, 'record_event')
            preview, refs = record.get('preview'), record.get('source_refs')
            require(type(preview) is dict and preview.get('locale') == binding['language']
                and type(preview.get('text')) is str and bool(preview['text'].strip()), 'record_preview')
            require(type(refs) is list and bool(refs) and all(type(ref) is dict
                and type(ref.get('source_id')) is str and ref['source_id'] in accepted
                and type(ref.get('version')) in (str, int) and str(ref['version']) == '1' for ref in refs), 'record_sources')
            seen.add(record['id'])
            records.append(record)
    require(records[0]['preview'] == head['preview'], 'record_preview')
    require(records[0] == head.get('first_record'), 'record_preview')
    return records


async def read_checkpoint(storage, binding, ordinal, accepted, read):
    """Keep the caller's cancellation and request-ownership boundary on every read."""
    from apps.api.lifetime_memory_read_api import draft_page
    identity = await read(lambda: storage.lifetime_rpc('read_lifetime_project_identity', p_project_id=binding['project_id']))
    current = checkpoint_binding(identity, binding['owner_id'], binding['project_id'], binding['language'])
    require('conversation_id' not in binding or current['conversation_id'] == binding['conversation_id'], 'identity')
    binding = current
    head = await read(storage.saved_memoir_draft, binding['project_id'], binding['language'])
    validate_head(head, binding, ordinal)
    checkpoint = {'milestone': ordinal, 'draft': head, 'pages': [], 'readback_protocol': READBACK_PROTOCOL,
                  'identity': binding}
    cursor, seen = None, set()
    for _ in range(MAX_PAGES):
        page = await read(draft_page, storage, binding['project_id'], head['snapshot_id'], cursor, PAGE_LIMIT)
        require(type(page) is dict, 'page_shape')
        checkpoint['pages'].append(page)
        if page.get('complete') is True:
            break
        cursor = page.get('next_cursor')
        require(type(cursor) is str and 0 < len(cursor) <= 512 and cursor not in seen, 'page_cursor')
        seen.add(cursor)
    else:
        raise CheckpointReadbackError('page_bound')
    checkpoint_records(checkpoint, binding, ordinal, accepted)
    return checkpoint
