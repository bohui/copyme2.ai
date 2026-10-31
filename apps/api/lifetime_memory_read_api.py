"""Bounded, owner-scoped HTTP adapters for the canonical lifetime read model."""
from __future__ import annotations

import re

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
    page = storage.lifetime_rpc('read_lifetime_collection_page', p_project_id=project_id,
        p_kind=kind, p_after=str(cursor) if cursor else None, p_limit=limit, p_event_id=event_id)
    if kind == 'events':
        page = {**page, 'events': [{**event, **({'temporal_anchor':'present'} if _present_residence(event) else {})}
                                 for event in page.get('events', [])]}
    return page


_CURRENT_RESIDENCE = re.compile(
    r"^(?:I(?:\s+am|'m)?\s+)?(?:currently|now|at present)\s+(?:I\s+)?(?:am\s+)?"
    r"(?:live|living|reside|residing|stay|staying|based)\s+(?:in|at)\s+[^,.!?;，。！？；\n]+[.。!！]?|"
    r"^(?:我(?:们)?)?(?:现在|目前|当前|如今)(?:正|仍然)?(?:生活在|居住在|住在|定居(?:在)?)"
    r"[^,.!?;，。！？；\n]+[.。!！]?", re.I)
_NON_CURRENT = re.compile(
    r'\b(?:not|never|former|formerly|previously|no longer|used to|and|but|after|before|once|was|were)\b|不|没|曾经|以前|过去|住过|但', re.I)


def _present_residence(event):
    # Only a complete, single-clause residence statement establishes "now".
    if event.get('timing_conflict') or not event.get('evidence_complete') or event.get('evidence_next_cursor'):
        return False
    refs = event.get('source_refs') or []
    if not refs or _NON_CURRENT.search(event.get('title') or ''):
        return False
    return all(ref.get('attribution') in {None, 'self', 'narrator', 'storyteller', '我', '本人'}
        and _CURRENT_RESIDENCE.fullmatch((ref.get('quote') or '').strip())
        and not _NON_CURRENT.search(ref.get('quote') or '') for ref in refs)


def map_event_page(storage, project_id, *, cursor=None, limit=8):
    page = collection_page(storage, project_id, kind='events', cursor=cursor, limit=limit)
    fields = {'id', 'revision', 'kind', 'life_stage', 'status', 'change_sequence', 'title',
              'temporal', 'temporal_estimate', 'temporal_anchor', 'uncertainty', 'assertion', 'timing_conflict', 'locationConfidenceScore', 'yearConfidenceScore'}
    events = []
    for event in page.get('events', []):
        if event.get('status') != 'active':
            continue
        item = {key: value for key, value in event.items() if key in fields}
        if isinstance(item.get('temporal_estimate'), dict):
            item['temporal_estimate'] = {key: value for key, value in item['temporal_estimate'].items() if key != 'basis'}
        events.append({**item, 'relations_complete': event.get('details_complete', True)})
    return {**page, 'events': events}


def map_event_places(storage, project_id, event_id, *, cursor=None, limit=8):
    page = storage.lifetime_rpc('read_lifetime_event_places', p_project_id=project_id,
        p_event_id=event_id, p_after=str(cursor) if cursor else None, p_limit=limit)
    fields = {'key', 'role', 'status', 'place'}
    return {**page, 'items': [{key: value for key, value in item.items() if key in fields}
                            for item in page.get('items', [])]}


def map_event_order(storage, project_id, event_id, *, cursor=None, limit=8):
    page = collection_page(storage, project_id, kind='event_details', cursor=cursor, limit=limit, event_id=event_id)
    relations = [
        {key: value for key, value in item['value'].items() if key in {'kind', 'event_id'}}
        for item in page.get('details', []) if item.get('kind') == 'relations'
        and item.get('value', {}).get('kind') in {'before', 'after'}]
    return {**{key: value for key, value in page.items() if key != 'details'}, 'relations': relations}


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
