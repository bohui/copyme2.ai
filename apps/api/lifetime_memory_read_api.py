"""Bounded, owner-scoped HTTP adapters for the canonical lifetime read model."""
from __future__ import annotations

import httpx
from fastapi import HTTPException

from .lifetime_memory_reads import snapshot_lifetime_read, find_lifetime_read_identity


def mapped_identity(storage, project_id):
    if callable(getattr(storage, 'lifetime_rpc', None)):
        return find_lifetime_read_identity(storage, project_id)
    return None


def read_mapped(storage, project_id, reader, legacy=lambda: None):
    """Only mapped reads use the original capture through the final ASGI send."""
    if callable(getattr(storage, 'lifetime_rpc', None)):
        try:
            return snapshot_lifetime_read(storage, project_id,
                lambda fence: reader(fence) if fence is not None else legacy())
        except httpx.HTTPStatusError as error:
            try:
                code = error.response.json().get('code')
            except (ValueError, AttributeError):
                code = None
            if code in {'40001', 'PT409'}:
                raise HTTPException(409, 'This view changed. Reload from the first page.',
                    headers={'X-Error-Code': 'LIFETIME_READ_STALE'}) from None
            if code == '22023':
                raise HTTPException(422, 'Invalid or differently scoped page cursor',
                    headers={'X-Error-Code': 'LIFETIME_CURSOR_INVALID'}) from None
            raise HTTPException(503, 'This saved view is temporarily unavailable',
                headers={'X-Error-Code': 'LIFETIME_READ_UNAVAILABLE'}) from None
    return legacy()


def draft_head(storage, project_id, *, language=None):
    if language is not None and language not in {'en-AU', 'zh-CN'}:
        raise HTTPException(422, 'Unsupported draft language')
    parameters = {'p_project_id': project_id, **({'p_locale': language} if language else {})}
    head = storage.lifetime_rpc('read_lifetime_private_draft_head', **parameters)
    if head is None:
        canonical_only()
    if language is not None and head.get('locale') != language:
        raise HTTPException(409, 'This language edition is not available for the canonical draft',
            headers={'X-Error-Code': 'LIFETIME_EDITION_UNAVAILABLE'})
    from .two_lane_memory import two_lanes_enabled
    from .turn_progress import thinking_steps_enabled
    if two_lanes_enabled():
        head={**head,'skill_progress':storage.lifetime_rpc('read_lifetime_skill_progress',p_project_id=project_id) if thinking_steps_enabled() else None}
    return head


def retry_draft(storage, project_id, language=None):
    if language is not None and language not in {'en-AU', 'zh-CN'}:
        raise HTTPException(422, 'Unsupported draft language')
    # Mutations finish BEFORE capture_lifetime_read_fence, so a retry cannot
    # accidentally relabel a body captured before its edition/revision changed.
    try:
        if language:
            storage.lifetime_rpc('set_lifetime_draft_edition', p_project_id=project_id, p_locale=language)
        else:
            storage.retry_memoir_lane(project_id, 'composer')
        storage.retry_memoir_lane(project_id, 'timeline')
    except httpx.HTTPStatusError:
        raise HTTPException(409, 'This draft is already changing. Reload before retrying.',
            headers={'X-Error-Code': 'LIFETIME_DRAFT_RETRY_CONFLICT'}) from None


def draft_page(storage, project_id, snapshot_id, cursor=None, limit=8):
    parameters = {'p_project_id': project_id, 'p_snapshot_id': str(snapshot_id),
                  'p_after': str(cursor) if cursor else None, 'p_limit': limit}
    return storage.lifetime_rpc('read_lifetime_private_draft_page', **parameters)


def collection_page(storage, project_id, *, kind, cursor=None, limit=8, event_id=None):
    return storage.lifetime_rpc('read_lifetime_collection_page', p_project_id=project_id,
        p_kind=kind, p_after=str(cursor) if cursor else None, p_limit=limit, p_event_id=event_id)


def canonical_collection(storage, project_id, *, cursor=None, task_cursor=None, limit=8):
    page = collection_page(storage, project_id, kind='sources', cursor=cursor, limit=limit)
    selection = storage.lifetime_rpc('read_lifetime_collection_selection', p_project_id=project_id,
        p_after=str(task_cursor) if task_cursor else None, p_limit=limit)
    return {**page, **selection,
            'sources': [{**source, 'content': source['text']} for source in page.get('sources', [])]}


def unsupported_collection_job(storage, project_id):
    if mapped_identity(storage, project_id) is not None:
        raise HTTPException(409,
            'Use the canonical private draft and paginated original sources. Legacy collection jobs do not support lifetime provenance.',
            headers={'X-Error-Code': 'LIFETIME_COLLECTION_JOB_UNSUPPORTED'})


def canonical_only():
    raise HTTPException(404, 'Canonical conversation not found')
