"""Read-only recovery projections over the canonical Supabase conversation ledger.

These DTOs are shared HTTP contracts, not a mobile ledger. Bigint positions stay
strings and an absent receipt never claims that admission or generation stopped.
"""
from __future__ import annotations

import base64
import binascii
from datetime import datetime
import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from .conversation_text import original_conversation_text
from .recall import storage_recall_status

PROJECT_ID_PATTERN = r'^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$'


class RecallStatus(BaseModel):
    rounds_completed: int
    free_rounds: int
    payment_required: bool
    paid: bool


class TurnReceipt(BaseModel):
    schema_version: Literal[1] = 1
    client_turn_id: str
    project_id: str
    state: Literal['not_found', 'source_accepted', 'conversation_saved']
    conversation_saved: bool
    server_turn_id: str | None
    source_id: str | None
    source_version: str | None
    source_sequence: str | None
    conversation_sequence: str | None
    project_ordinal: str | None
    narrator_text: str | None
    reply: str | None
    source_status: Literal['active', 'withdrawn'] | None
    source_processing_state: Literal['pending', 'succeeded', 'retry'] | None
    # Source extraction is not proof of completed place/family enrichment.
    enrichment_state: Literal['unknown'] = 'unknown'
    recall_status: RecallStatus
    photo_cue: dict | None = None
    response_photos: list[dict] = Field(default_factory=list)


class ProjectSnapshot(BaseModel):
    project_id: str
    source_sequence: str
    event_sequence: str
    policy_epoch: str


class ProjectList(BaseModel):
    schema_version: Literal[1] = 1
    items: list[ProjectSnapshot]
    next_after_project_id: str | None


class NarratorSourceDetail(BaseModel):
    schema_version: Literal[1] = 1
    id: str
    project_id: str
    version: str
    sequence: str
    text: str
    source_kind: Literal['narrator_chat', 'narrator_transcript']
    status: Literal['active']
    language: Literal['en-AU', 'zh-CN']
    created_at: str


def narrator_source_detail(row):
    """Project original evidence without exposing owner/internal worker fields."""
    return NarratorSourceDetail(id=row['id'], project_id=row['project_id'],
        version=decimal(row['version']), sequence=decimal(row['sequence']),
        text=row['text'], source_kind=row['kind'], status=row['status'],
        language=row['language'], created_at=row['created_at'])


class ConversationExchange(BaseModel):
    server_turn_id: str
    client_turn_id: str | None
    kind: Literal['agent', 'agent_greeting']
    created_at: str
    source_sequence: str | None
    conversation_sequence: str | None
    source_id: str | None
    source_version: str | None
    source_status: Literal['active', 'withdrawn'] | None
    narrator_text: str | None
    reply: str | None
    photo_cue: dict | None = None
    response_photos: list[dict] = Field(default_factory=list)


class ConversationHistory(BaseModel):
    schema_version: Literal[1] = 1
    project_id: str
    policy_epoch: str
    items: list[ConversationExchange]
    next_cursor: str | None


def decimal(value):
    return str(int(value)) if value is not None else None


def visible_exchange(memory, source):
    """Prefer current evidence; never re-expose a revoked or corrected reply."""
    narrator, reply = None, None
    if memory:
        content = memory.get('content') or ''
        if content.startswith('Storyteller: '):
            question, separator, answer = content[len('Storyteller: '):].partition('\nMemory Spark: ')
            if separator:
                narrator = original_conversation_text(question)
                reply = answer
        if memory.get('kind') == 'agent_greeting':
            narrator = None
    if source:
        if source['status'] == 'withdrawn':
            return None, None
        narrator = source['text']
        if int(source['version']) > 1:
            reply = None
    return narrator, reply


def turn_receipt(storage, project_id, client_turn_id):
    memory = storage.agent_turn_by_id(project_id, client_turn_id)
    source = storage.narrator_source_by_turn(project_id, client_turn_id)
    completed = storage.completed_round_by_turn(project_id, client_turn_id) if memory else None
    from .interview_plan import public_interview_fields
    read_interview = getattr(storage, 'interview_turn_by_id', None)
    interview = read_interview(project_id, client_turn_id) if callable(read_interview) else None
    narrator, reply = visible_exchange(memory, source)
    return TurnReceipt(
        client_turn_id=client_turn_id, project_id=project_id,
        state='conversation_saved' if memory else ('source_accepted' if source or interview else 'not_found'),
        **public_interview_fields(interview),
        conversation_saved=bool(memory), server_turn_id=memory['id'] if memory else None,
        source_id=source['id'] if source else None,
        source_version=decimal(source['version']) if source else None,
        source_sequence=decimal(source['sequence']) if source else None,
        conversation_sequence=decimal(memory.get('source_sequence')) if memory else None,
        project_ordinal=decimal(completed['ordinal']) if completed else None,
        narrator_text=narrator, reply=reply,
        source_status=source['status'] if source else None,
        source_processing_state=source['processing_status'] if source else None,
        recall_status=storage_recall_status(storage, storage.story_entitlement()),
    )


def project_snapshot(row):
    return ProjectSnapshot(project_id=row['project_id'],
        source_sequence=decimal(row['source_sequence']),
        event_sequence=decimal(row['event_sequence']), policy_epoch=decimal(row['policy_epoch']))


def history_cursor(user_id, project_id, memory):
    data = [1, user_id, project_id, memory['created_at'], memory['id']]
    return base64.urlsafe_b64encode(json.dumps(data, separators=(',', ':')).encode()).decode().rstrip('=')


def read_history_cursor(cursor, user_id, project_id):
    """A cursor is only a scoped seek boundary, never an authorization token."""
    if cursor is None:
        return None
    try:
        if len(cursor) > 1024:
            raise ValueError
        values = json.loads(base64.b64decode(cursor + '=' * (-len(cursor) % 4), altchars=b'-_', validate=True))
        if not isinstance(values, list) or len(values) != 5 or values[:3] != [1, user_id, project_id]:
            raise ValueError
        date = datetime.fromisoformat(values[3])
        if date.tzinfo is None:
            raise ValueError
        return date.isoformat(), str(UUID(values[4]))
    except (ValueError, TypeError, binascii.Error, UnicodeDecodeError):
        raise ValueError('Invalid or differently scoped conversation cursor') from None


def conversation_history(storage, project_id, limit, cursor):
    boundary = read_history_cursor(cursor, storage.user_id, project_id)
    project = storage.memoir_project(project_id)
    if project is None:
        raise LookupError('Project not found')
    rows = storage.project_conversation_page(project_id, limit + 1, boundary)
    page = rows[:limit]
    sources = storage.narrator_sources_by_turns(project_id,
        [row.get('client_turn_id') or row['id'] for row in page]) if page else []
    by_turn = {row['client_turn_id']: row for row in sources}
    items = []
    for row in reversed(page):
        source = by_turn.get(row.get('client_turn_id') or row['id'])
        narrator, reply = visible_exchange(row, source)
        from .interview_plan import public_interview_fields
        read_interview = getattr(storage, 'interview_turn_by_id', None)
        interview = read_interview(project_id, row.get('client_turn_id') or row['id']) if callable(read_interview) else None
        items.append(ConversationExchange(
            server_turn_id=row['id'], client_turn_id=row.get('client_turn_id'),
            kind=row['kind'], created_at=row['created_at'],
            source_sequence=decimal(source['sequence']) if source else None,
            conversation_sequence=decimal(row.get('source_sequence')),
            source_id=source['id'] if source else None,
            source_version=decimal(source['version']) if source else None,
            source_status=source['status'] if source else None,
            narrator_text=narrator, reply=reply, **public_interview_fields(interview),
        ))
    # This is a snapshot page, not a change feed. Clients re-fetch on return to
    # foreground; policy_epoch invalidates cached evidence after a correction.
    return ConversationHistory(project_id=project_id, policy_epoch=decimal(project['policy_epoch']),
        items=items, next_cursor=history_cursor(storage.user_id, project_id, page[-1]) if len(rows) > limit else None)
